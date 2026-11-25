"""Edits to a REAPER project, made on the parsed chunks of `project.load(...)` and saved as a NEW .rpp.

Every edit changes only the lines it names; everything else is written back exactly as REAPER saved it.

  fade(clip, "in"|"out", seconds, shape)     lengthen an item fade (never shortens one)
  item_volume(clip, db)                      item volume up or down (VOLPAN field 1)
  dip(project, track, t0, t1, db, ramp)      a dip in the track's volume envelope between t0 and t1
  ease(project, track, t, db, ease_s)        a jump of `db` at t arrives gradually (Live `smooth`'s ease)
  add_take(clip, path, name)                 a new take playing `path` like the active take, made active
  rename(track, name)

Volume envelopes: REAPER saves amplitudes (1.0 = 0 dB) and MULTIPLIES the envelope with the fader (checked in
REAPER 7.86), so a new envelope starts at 1.0 and leaves the fader alone. Points are kept within +6 dB.
"""
import math
import uuid
from pathlib import Path

from hypnomix.project import rpp

MAX_LIN = 2.0            # REAPER's volume envelope top (+6 dB)


def lin(db):
    return 10 ** (db / 20)


def guid():
    return "{" + str(uuid.uuid4()).upper() + "}"


# ---------------------------------------------------------------- items
def fade(clip, which, seconds, shape=None):
    """Make the item's fade at least `seconds` long. Returns True when something changed."""
    item = clip.native
    key = "FADEIN" if which == "in" else "FADEOUT"
    ln = item.line(key)
    if ln is None:
        item.set(key, 1, float(seconds), 0, 1, 0, 0, 0, after="LOOP")
    else:
        t = list(ln.tokens)
        while len(t) < 8:
            t.append("0")
        cur = max(float(t[2]), float(t[3]))        # an auto-crossfade length wins when set
        if cur >= seconds - 1e-9:
            return False
        t[2] = float(seconds)
        if shape is not None:
            t[1] = shape
            t[4] = shape
        ln.set(*t[1:])
    if which == "in":
        clip.fade_in = max(clip.fade_in, seconds)
    else:
        clip.fade_out = max(clip.fade_out, seconds)
    return True


def item_volume(clip, db):
    item = clip.native
    ln = item.line("VOLPAN")
    if ln is None:
        ln = item.set("VOLPAN", 1, 0, 1, -1)
    t = list(ln.tokens)
    t[1] = min(16.0, float(t[1]) * lin(db))       # REAPER's item volume tops out near +24 dB; stay well under
    ln.set(*t[1:])
    clip.gain = float(t[1])


def add_take(clip, path, name=None):
    """A new take on the item that plays `path` with the active take's offset, rate and volume, made active.
    The original take stays on the item (switch takes to A/B)."""
    item = clip.native
    tk = clip.take
    # make every existing take non-selected
    for ln in item.lines("TAKE"):
        if "SEL" in ln.tokens[1:]:
            ln.set(*[x for x in ln.tokens[1:] if x != "SEL"])
    pr = next((c for c in (tk.native or []) if isinstance(c, rpp.Line) and c.key == "PLAYRATE"), None)
    vol = tk.gain
    lines = [rpp.Line(["TAKE", "SEL"]), rpp.Line(["NAME", name or path.name]),
             rpp.Line(["TAKEVOLPAN", 0, float(vol), -1]), rpp.Line(["SOFFS", float(tk.offset)]),
             rpp.Line(["PLAYRATE", *(pr.tokens[1:] if pr is not None else [1, 1, 0, -1, 0, 0.0025])]),
             rpp.Line(["CHANMODE", 0]), rpp.Line(["GUID", guid()])]
    for ln in lines:
        item.add(ln)
    src = rpp.Chunk(["SOURCE", "WAVE"])
    item.add(src)
    base = getattr(item, "project_dir", None)
    try:
        shown = str(Path(path).resolve().relative_to(Path(base).resolve())) if base else str(path)
    except ValueError:
        shown = str(path)                       # outside the project folder: keep the full path
    src.add(rpp.Line(["FILE", shown]))
    src.children[0].indent = item._child_indent() + "  "
    src.close_raw = None
    return True


# ---------------------------------------------------------------- volume envelope
def volume_envelope(track, create=True):
    """The track's (post-FX) volume envelope chunk, created at 1.0 when missing. None when it exists but is off."""
    tr = track.native
    env = tr.chunk("VOLENV2")
    if env is not None:
        act = env.line("ACT")
        if act is not None and len(act.tokens) > 1 and act.tokens[1] == "0":
            return None
        return env
    if not create:
        return None
    env = rpp.Chunk(["VOLENV2"])
    first_item = next((k for k, c in enumerate(tr.children) if isinstance(c, rpp.Chunk) and c.name == "ITEM"), None)
    tr.add(env, at=first_item)
    ind = env.indent + "  "
    for toks in (["EGUID", guid()], ["ACT", 1, -1], ["VIS", 1, 1, 1], ["LANEHEIGHT", 0, 0], ["ARM", 0],
                 ["DEFSHAPE", 0, -1, -1], ["VOLTYPE", 1], ["PT", 0, 1, 0]):
        env.add(rpp.Line(toks, indent=ind))
    return env


def points(env):
    return sorted((float(l.tokens[1]), float(l.tokens[2]), l) for l in env.lines("PT") if len(l.tokens) >= 3)


def value_at(pts, t, fader=True):
    """Envelope value at t as REAPER plays it (held before the first and after the last point). A fader-scaled
    envelope (VOLTYPE 1, REAPER's default) runs straight in fader position between points, not in amplitude."""
    from hypnomix.project.model import envelope_at
    if not pts:
        return 1.0
    return float(envelope_at([(a, b) for a, b, _ in pts], t, fader))


def is_fader(env):
    return env.get("VOLTYPE", cast=int, default=0) == 1


def _set_point(env, t, v):
    pts = points(env)
    hit = next((l for tm, _, l in pts if abs(tm - t) < 1e-6), None)
    v = max(0.0, min(MAX_LIN, v))
    if hit is not None:
        tk = list(hit.tokens)
        tk[2] = v
        hit.set(*tk[1:])
        return
    ln = rpp.Line(["PT", float(t), float(v), 0])
    lines = env.lines("PT")
    after = next((l for l in lines if float(l.tokens[1]) > t), None)
    at = env.children.index(after) if after is not None else (env.children.index(lines[-1]) + 1 if lines else len(env.children))
    env.add(ln, at=at)


def shape_range(env, factor, t0, t2):
    """Multiply the envelope by factor(t) between t0 and t2 (factor 1 outside): existing points inside are scaled,
    and points are added where the factor changes shape, so deliberate rides survive under the change."""
    pts = points(env)
    keys = sorted({t0, t2, *factor.knots})
    base = {t: value_at(pts, t, is_fader(env)) for t in keys}
    for tm, v, l in pts:
        if t0 < tm < t2 and all(abs(tm - k) > 1e-6 for k in keys):
            tk = list(l.tokens)
            tk[2] = max(0.0, min(MAX_LIN, v * factor(tm)))
            l.set(*tk[1:])
    for t in keys:
        _set_point(env, t, base[t] * factor(t))


class _Factor:
    def __init__(self, knots, fn):
        self.knots, self.fn = knots, fn

    def __call__(self, t):
        return self.fn(t)


def dip(track, t0, t1, db, ramp=0.02):
    """Turn the track down by `db` between t0 and t1, with `ramp`-second slopes either side."""
    env = volume_envelope(track)
    if env is None:
        raise ValueError(f"{track.name}: its volume envelope is switched off; switch it on or skip this fix")
    a0, a1, b0, b1 = t0 - ramp, t0, t1, t1 + ramp
    g = lin(-abs(db))

    def fn(t):
        if t <= a0 or t >= b1:
            return 1.0
        if t < a1:
            return 1 + (g - 1) * (t - a0) / ramp
        if t <= b0:
            return g
        return g + (1 - g) * (t - b0) / ramp

    shape_range(env, _Factor([a0, a1, b0, b1], fn), a0, b1)


def ease(track, t, size_db, amount=0.5, ease_s=0.3, pre_s=0.01):
    """A level jump of size_db at t arrives over ease_s: take amount x the jump away right at t, back to normal
    by t + ease_s (the same move as Live `smooth`)."""
    env = volume_envelope(track)
    if env is None:
        raise ValueError(f"{track.name}: its volume envelope is switched off; switch it on or skip this fix")
    off = -size_db * amount
    t0, t1, t2 = t - pre_s, t, t + ease_s

    def fn(x):
        if x <= t0 or x >= t2:
            return 1.0
        if x <= t1:
            return lin(off * (x - t0) / (t1 - t0))
        return lin(off * (t2 - x) / (t2 - t1))

    shape_range(env, _Factor([t0, t1, t2], fn), t0, t2)


def rename(track, name):
    track.native.set("NAME", name)
    track.name = name


def locate(project, loc):
    """(track, clip) for a locator {"track", "start", "guid"} written by the scan; None when it is not there."""
    tr = project.track(loc["track"])
    if tr is None or tr.name != loc["track"]:
        tr = next((t for t in project.tracks if t.name == loc["track"]), None)
    if tr is None:
        return None
    for c in tr.clips:
        g = c.native.get("IGUID") if c.native is not None else None
        if loc.get("guid") and g == loc["guid"]:
            return tr, c
    for c in tr.clips:
        if abs(c.start - float(loc["start"])) < 0.001:
            return tr, c
    return None


def locator(track, clip):
    return {"track": track.name, "start": round(clip.start, 6),
            "guid": clip.native.get("IGUID") if clip.native is not None else None}


def save(project, out):
    return rpp.save(project.native, out)


def check(src, out):
    """Structure check of a written project against the original: [errors]. It must parse, keep every track
    (name, folder depth) and every item (position, length), and only add takes."""
    from hypnomix.project import reaper
    errs = []
    try:
        a, b = reaper.read(src), reaper.read(out)
    except Exception as e:
        return [f"the new project does not read back ({e})"]
    if len(a.tracks) != len(b.tracks):
        errs.append(f"track count changed: {len(a.tracks)} → {len(b.tracks)}")
    for x, y in zip(a.tracks, b.tracks):
        if (x.parent.name if x.parent else None) != (y.parent.name if y.parent else None):
            errs.append(f"{y.name}: its folder changed")
        if len(x.clips) != len(y.clips):
            errs.append(f"{y.name}: item count changed ({len(x.clips)} → {len(y.clips)})")
        for c, d in zip(x.clips, y.clips):
            if abs(c.start - d.start) > 1e-6 or abs(c.length - d.length) > 1e-6:
                errs.append(f"{y.name}: an item moved or changed length at {c.start:.3f} s")
            if len(d.takes) < len(c.takes):
                errs.append(f"{y.name}: an item lost a take at {c.start:.3f} s")
    text = rpp.dumps(b.native)
    opens = sum(1 for l in text.splitlines() if l.strip().startswith("<"))
    closes = sum(1 for l in text.splitlines() if l.strip() == ">")
    if opens != closes:
        errs.append(f"unbalanced chunks ({opens} open, {closes} close)")
    return errs
