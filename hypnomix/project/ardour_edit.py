"""Edits to an Ardour session, made on the parsed XML of `project.load(...)` and saved as a NEW .ardour snapshot.

Every edit changes only the attributes and elements it names; everything it does not understand is written back
as it was read (element order, attributes and text untouched; only the XML is re-serialised).

  fade(p, clip, "in"|"out", seconds, shape)  lengthen a region fade (never shortens one), with its curve
  region_gain(clip, db)                      region gain up or down (scale-amplitude)
  dip(p, track, t0, t1, db, ramp)            a dip in the region gain envelope over the burst
  ease(p, clip, db, ease_s)                  `db` taken off at the region start, back to normal over ease_s
  fader(track, db) / pan(track, value) / mute(track, on)   the route's fader, pan (-1..+1) and mute
  save(p, out)  check(src, out)  diff(src, out)

Times follow the session: samples before Ardour 7, "a<superclock>" from Ardour 7 (see `ardour.py`).
Region gain envelopes and fades are region-relative; a fader, pan or mute that plays automation is refused.
"""
import copy
import math
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from hypnomix.project import ardour as AR
from hypnomix.project import mpe as MP

MAX_LIN = 2.0                      # Ardour's gain ceiling (+6 dB)
SHAPES = ("linear", "power", "slow")
FADE_POINTS = 9


def lin(db):
    return 10 ** (db / 20)


def num(v):
    return f"{v:.12g}"


def flag(el, name, on):
    """Set a yes/no attribute in the style the session already uses ('yes'/'no' or '1'/'0')."""
    cur = (el.get(name) or "").strip().lower()
    word = cur in ("yes", "no")
    el.set(name, ("yes" if on else "no") if word else ("1" if on else "0"))


class Ctx:
    """The session's time format: seconds <-> the strings Ardour writes."""

    def __init__(self, p):
        self.root = p.native
        self.version = AR.session_version(self.root)
        self.sr = p.sample_rate
        warn = []
        self.clock, *_ = AR.tempo_map(self.root, self.sr, self.version, warn)
        self.scps = self.clock.scps

    def fmt(self, sec):
        if self.version >= 7000:
            return f"a{int(round(sec * self.scps))}"
        return str(int(round(sec * self.sr)))


def _ctx(p):
    return Ctx(p)


def _events_el(alist):
    ev = alist.find("events")
    if ev is None:
        ev = ET.SubElement(alist, "events")
    return ev


def _read_events(alist, ctx):
    """[(seconds, value, raw time)] of an AutomationList (empty when it has none)."""
    ev = alist.find("events") if alist is not None else None
    out = []
    if ev is None or not (ev.text or "").strip():
        return out
    for line in ev.text.strip().splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if parts[0][:1] == "b":
            raise ValueError("this envelope is written in music time; edit it by hand in HypnoMix DAW")
        out.append((ctx.clock.pos(parts[0]), float(parts[1]), parts[0]))
    return out


def _write_events(alist, ctx, pts):
    ev = _events_el(alist)
    ev.text = "\n" + "".join(f"{raw or ctx.fmt(t)} {num(v)}\n" for t, v, raw in pts)


def _next_id(root):
    ids = [int(x.get("id")) for x in root.iter() if (x.get("id") or "").isdigit()]
    return max(ids, default=0) + 1


def _alist(parent, ctx, kind, template=None):
    """Make parent's AutomationList (fresh, with no events), keeping a template's attributes when it has them."""
    for old in list(parent):
        parent.remove(old)
    parent.attrib.pop("default", None)
    al = ET.SubElement(parent, "AutomationList")
    if template is not None:
        for k, v in template.attrib.items():
            al.set(k, v)
        if "id" in template.attrib:
            al.set("id", str(_next_id(ctx.root)))
    else:
        al.set("automation-id", kind)
        al.set("state", "Off")
    return al


# ---------------------------------------------------------------- region fades
def fade_curve(shape, n=FADE_POINTS):
    """[(fraction, gain)] rising 0 -> 1 for a fade in."""
    if shape not in SHAPES:
        raise ValueError(f"unknown fade shape {shape!r}; use one of {', '.join(SHAPES)}")
    out = []
    for i in range(n):
        x = i / (n - 1)
        g = x if shape == "linear" else math.sin(x * math.pi / 2) if shape == "power" else x * x
        out.append((x, g))
    return out


def fade(p, clip, which, seconds, shape="linear"):
    """Make the region's fade at least `seconds` long, as a curve of the given shape. Returns True when it changed."""
    rg = clip.native
    if clip.kind != "audio":
        raise ValueError(f"{clip.name}: only audio regions have fades")
    ctx = _ctx(p)
    seconds = min(float(seconds), clip.length)
    cur = clip.fade_in if which == "in" else clip.fade_out
    if cur >= seconds - 1e-9:
        return False
    tag, inv = ("FadeIn", "InverseFadeIn") if which == "in" else ("FadeOut", "InverseFadeOut")
    curve = fade_curve(shape)
    if which == "out":
        curve = [(x, 1.0 - g) for x, g in curve]          # a fade out falls 1 -> 0 over the same shape
    node = rg.find(tag)
    if node is None:
        node = ET.SubElement(rg, tag)
    old = node.find("AutomationList")
    al = _alist(node, ctx, "fadein" if which == "in" else "fadeout", old)
    _write_events(al, ctx, [(x * seconds, g, None) for x, g in curve])
    inode = rg.find(inv)
    if inode is not None:                                   # the crossfade partner: the complement, so layers meet
        iold = inode.find("AutomationList")
        ial = _alist(inode, ctx, "inversefadein" if which == "in" else "inversefadeout", iold)
        _write_events(ial, ctx, [(x * seconds, 1.0 - g, None) for x, g in curve])
    flag(rg, "fade-in-active" if which == "in" else "fade-out-active", True)
    if which == "in":
        clip.fade_in = seconds
    else:
        clip.fade_out = seconds
    return True


def region_gain(clip, db):
    """Region gain (scale-amplitude) up or down by db; kept within Ardour's ceiling."""
    rg = clip.native
    cur = AR.num(rg.get("scale-amplitude"), 1.0)
    new = min(MAX_LIN * 4, cur * lin(db))
    rg.set("scale-amplitude", num(new))
    clip.take.gain = new


# ---------------------------------------------------------------- region gain envelope
def _envelope(p, clip, knots, factor):
    """Multiply the region's gain envelope by factor(t) over knots[0]..knots[-1] (region seconds). Existing
    points inside are scaled, points are added at the knots, and what is outside is left as it was."""
    rg = clip.native
    ctx = _ctx(p)
    node = rg.find("Envelope")
    if node is None:
        node = ET.SubElement(rg, "Envelope")
    old = node.find("AutomationList")
    pts = [] if node.get("default") in ("yes", "1", "true") or old is None else _read_events(old, ctx)
    if not pts:
        pts = [(0.0, 1.0, None), (clip.length, 1.0, None)]

    def base(t):
        if t <= pts[0][0]:
            return pts[0][1]
        for (t0, v0, _), (t1, v1, _) in zip(pts, pts[1:]):
            if t0 <= t <= t1:
                return v0 if t1 == t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
        return pts[-1][1]

    lo, hi = knots[0], knots[-1]
    new = []
    for t, v, raw in pts:
        if lo < t < hi and all(abs(t - k) > 1e-9 for k in knots):
            v = max(0.0, min(MAX_LIN, v * factor(t)))
        new.append((t, v, raw))
    for k in knots:
        v = max(0.0, min(MAX_LIN, base(k) * factor(k)))
        hit = next((i for i, x in enumerate(new) if abs(x[0] - k) < 1e-9), None)
        if hit is not None:
            new[hit] = (new[hit][0], v, new[hit][2])
        else:
            new.append((k, v, None))
    new.sort(key=lambda x: x[0])
    al = _alist(node, ctx, "envelope", old)
    _write_events(al, ctx, new)
    flag(rg, "envelope-active", True)
    clip.envelope = [(t, v) for t, v, _ in new]


def dip(p, track, t0, t1, db, ramp=0.02):
    """Turn the track down by db between t0 and t1 (timeline seconds), with ramp-second slopes either side, as a
    dip in the gain envelope of every sounding region there. Returns how many regions got it."""
    g = lin(-abs(db))
    a0, a1, b0, b1 = t0 - ramp, t0, t1, t1 + ramp

    def fn(t):
        if t <= a0 or t >= b1:
            return 1.0
        if t < a1:
            return 1 + (g - 1) * (t - a0) / ramp
        if t <= b0:
            return g
        return g + (1 - g) * (t - b0) / ramp

    n = 0
    for c in track.clips:
        if c.kind != "audio" or c.muted or c.end <= a0 or c.start >= b1:
            continue
        ks = sorted({min(c.length, max(0.0, k - c.start)) for k in (a0, a1, b0, b1)})
        _envelope(p, c, ks, lambda t, c=c: fn(t + c.start))
        n += 1
    return n


def ease(p, clip, db, ease_s=0.3):
    """Take `db` off at the region's start, back to normal by ease_s (a level jump arriving gradually)."""
    t2 = min(ease_s, clip.length)
    off = float(db)

    def fn(t):
        return 1.0 if t >= t2 else lin(off * (t2 - t) / t2)

    _envelope(p, clip, [0.0, t2], fn)


# ---------------------------------------------------------------- routes
def _controllable(rt, name):
    return AR.controllable(rt, name)


def _automation_plays(rt, auto_id):
    for al in rt.iter("AutomationList"):
        if al.get("automation-id") == auto_id and al.get("state", "Off") != "Off":
            return True
    return False


def fader(track, db):
    """The route's fader up or down by db (Amp gaincontrol)."""
    rt = track.native
    amp = next((x for x in rt.findall("Processor") if x.get("type") == "amp"), None)
    c = _controllable(amp, "gaincontrol") if amp is not None else None
    if c is None:
        raise ValueError(f"{track.name}: no fader found in the session")
    if _automation_plays(rt, "gain"):
        raise ValueError(f"{track.name}: its fader plays automation; change that by hand")
    new = max(0.0, min(MAX_LIN, AR.num(c.get("value"), 1.0) * lin(db)))
    c.set("value", num(new))
    track.volume = new * (track.trim if getattr(track, "trim", None) else 1.0)


def pan(track, value):
    """The route's pan to `value` (-1 left .. +1 right): Ardour's azimuth is 0 (left) .. 1 (right)."""
    rt = track.native
    pn = rt.find("Pannable")
    c = _controllable(pn, "pan-azimuth") if pn is not None else None
    if c is None:
        raise ValueError(f"{track.name}: no pan found in the session")
    if _automation_plays(rt, "pan-azimuth"):
        raise ValueError(f"{track.name}: its pan plays automation; change that by hand")
    c.set("value", num(max(0.0, min(1.0, (float(value) + 1) / 2))))
    track.pan = float(value)


def mute(track, on=True):
    rt = track.native
    c, mm = _controllable(rt, "mute"), rt.find("MuteMaster")
    if c is None and mm is None:
        raise ValueError(f"{track.name}: no mute found in the session")
    if _automation_plays(rt, "mute"):
        raise ValueError(f"{track.name}: its mute plays automation; change that by hand")
    if c is not None:
        c.set("value", "1" if on else "0")
    if mm is not None:
        flag(mm, "muted", on)
    track.muted = bool(on)


# ---------------------------------------------------------------- locating, saving
def locator(track, clip):
    return {"track": track.name, "start": round(clip.start, 6),
            "guid": clip.native.get("id") if clip.native is not None else None}


def locate(p, loc):
    """(track, clip) for a locator written by the scan; None when it is not there any more."""
    tr = p.track(loc["track"])
    if tr is None or tr.name != loc["track"]:
        tr = next((t for t in p.tracks if t.name == loc["track"]), None)
    if tr is None:
        return None
    for c in tr.clips:
        if loc.get("guid") and c.native is not None and c.native.get("id") == loc["guid"]:
            return tr, c
    for c in tr.clips:
        if abs(c.start - float(loc["start"])) < 0.001:
            return tr, c
    return None


def save(p, out):
    """Write the session as a new snapshot. Its Session name is the snapshot name, as Ardour writes on a Save As."""
    out = Path(out)
    p.native.set("name", out.stem)
    tree = ET.ElementTree(p.native)
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")          # whole or not at all: never a cut-off snapshot that the
    try:                                                          # engine would list (its name does not end in .ardour)
        tree.write(tmp, encoding="UTF-8", xml_declaration=True)
        os.replace(tmp, out)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return out


# ---------------------------------------------------------------- checks
CHANGEABLE_REGION_ATTRS = ("scale-amplitude", "fade-in-active", "fade-out-active", "envelope-active")
CHANGEABLE_REGION_CHILDREN = ("FadeIn", "FadeOut", "InverseFadeIn", "InverseFadeOut", "Envelope")


def _stripped(root):
    """A copy of the session with everything an edit may change taken out: what is left must be identical."""
    r = copy.deepcopy(root)
    r.attrib.pop("name", None)
    for rg in r.iter("Region"):
        for a in CHANGEABLE_REGION_ATTRS:
            rg.attrib.pop(a, None)
        for ch in list(rg):
            if ch.tag in CHANGEABLE_REGION_CHILDREN:
                rg.remove(ch)
    for rt in r.iter("Route"):
        for amp in rt.findall("Processor"):
            if amp.get("type") == "amp":
                c = AR.controllable(amp, "gaincontrol")
                if c is not None:
                    c.attrib.pop("value", None)
        for owner in (rt, rt.find("Pannable")):
            if owner is None:
                continue
            for name in ("mute", "pan-azimuth"):
                c = AR.controllable(owner, name)
                if c is not None:
                    c.attrib.pop("value", None)
        mm = rt.find("MuteMaster")
        if mm is not None:
            mm.attrib.pop("muted", None)
    MP.strip_mpe_styles(r)                         # the MPE glide fix: bend / pressure / slide interpolation only
    return r


def _same(a, b, path=""):
    """[where] the two trees differ (tag, attributes, text, children, in order)."""
    if a.tag != b.tag or a.attrib != b.attrib or (a.text or "").strip() != (b.text or "").strip() \
            or len(a) != len(b):
        return [f"{path}/{a.tag}"]
    out = []
    for x, y in zip(a, b):
        out += _same(x, y, f"{path}/{a.tag}")
    return out


TIME_NEW = re.compile(r"^(a-?\d+|b-?\d+)$")
TIME_OLD = re.compile(r"^-?\d+$")


def _problems(p, root):
    """Problems in the session as written: duplicate ids, malformed fade/envelope times, regions outside sources."""
    errs = []
    ids = {}
    for el in root.iter():
        i = el.get("id")
        if i is not None:
            ids.setdefault(i, []).append(el.tag)
    errs += [f"id {i} is used {len(t)} times" for i, t in ids.items() if len(t) > 1]
    version = AR.session_version(root)
    good = TIME_NEW if version >= 7000 else TIME_OLD
    for rg in root.iter("Region"):
        for tag in CHANGEABLE_REGION_CHILDREN:
            node = rg.find(tag)
            if node is None:
                continue
            for line in ((node.findtext("AutomationList/events") or "").strip().splitlines()):
                parts = line.split()
                try:
                    ok = len(parts) >= 2 and good.match(parts[0]) and math.isfinite(float(parts[1]))
                except ValueError:
                    ok = False
                if not ok:
                    errs.append(f"{rg.get('name')}: a {tag} point is not well-formed: {line.strip()!r}")
    return errs


def _source_errors(p):
    import soundfile as sf
    errs = []
    for t in p.tracks:
        for c in t.clips:
            if c.kind != "audio" or c.take is None or c.take.path is None or not Path(c.take.path).exists():
                continue
            try:
                dur = sf.info(str(c.take.path)).duration
            except Exception:
                continue
            if c.take.offset + c.length > dur + 0.01:
                errs.append(f"{t.name}: region '{c.name}' runs past the end of its file")
    return errs


def _model_diff(a, b):
    """-> (structure errors, [changes]) between two loaded projects with the same layout."""
    errs, changes = [], []
    if [(t.name, t.kind, t.parent.name if t.parent else None) for t in a.tracks] != \
            [(t.name, t.kind, t.parent.name if t.parent else None) for t in b.tracks]:
        return ["tracks, their order or their folders changed"], []
    for x, y in zip(a.tracks, b.tracks):
        if len(x.clips) != len(y.clips):
            errs.append(f"{x.name}: region count changed ({len(x.clips)} to {len(y.clips)})")
            continue
        if abs(x.volume - y.volume) > 1e-6:
            changes.append(f"{x.name}: fader {20 * math.log10(max(x.volume, 1e-9)):+.1f} dB to "
                           f"{20 * math.log10(max(y.volume, 1e-9)):+.1f} dB (trim included)")
        if abs(x.pan - y.pan) > 1e-6:
            changes.append(f"{x.name}: pan {x.pan:+.2f} to {y.pan:+.2f}")
        if x.muted != y.muted:
            changes.append(f"{x.name}: {'muted' if y.muted else 'unmuted'}")
        for c, d in zip(x.clips, y.clips):
            tag = f"{x.name} @ {c.start:.3f} s"
            if (c.name, c.kind, c.layer, c.muted, c.opaque) != (d.name, d.kind, d.layer, d.muted, d.opaque) \
                    or abs(c.start - d.start) > 1e-9 or abs(c.length - d.length) > 1e-9 \
                    or (c.take and abs(c.take.offset - d.take.offset) > 1e-9) or c.path != d.path:
                errs.append(f"{tag}: a region moved, changed length, source or layer")
                continue
            if abs(c.level - d.level) > 1e-9:
                changes.append(f"{tag}: region gain {20 * math.log10(max(c.level, 1e-9)):+.1f} dB to "
                               f"{20 * math.log10(max(d.level, 1e-9)):+.1f} dB")
            for which, ca, da, la, lb in (("in", c.fade_in, d.fade_in, c.fade_in_curve, d.fade_in_curve),
                                          ("out", c.fade_out, d.fade_out, c.fade_out_curve, d.fade_out_curve)):
                if abs(ca - da) > 1e-9 or la != lb:
                    changes.append(f"{tag}: fade {which} {ca * 1000:.1f} ms to {da * 1000:.1f} ms"
                                   + (" (curve written)" if lb else ""))
            if c.envelope != d.envelope:
                changes.append(f"{tag}: gain envelope {'changed' if c.envelope else 'added'} "
                               f"({len(d.envelope or [])} points)")
    return errs, changes


def check(src, out):
    """Structure check of the written session against the original: [errors]. It must read back; ids stay
    unique; fade and envelope times are well-formed; regions stay inside their files; and nothing outside what an
    approved edit may change differs (tracks, folders, regions, positions, lengths, plug-ins, routing)."""
    from hypnomix import project as PJ
    errs = []
    try:
        a, b = PJ.load(src), PJ.load(out)
    except (Exception, SystemExit) as e:
        return [f"the new session does not read back ({e})"]
    where = _same(_stripped(a.native), _stripped(b.native))
    if where:
        errs.append("something outside the approved edits differs (" + where[0] + ")")
    new = set(_problems(b, b.native)) - set(_problems(a, a.native))
    errs += sorted(new)
    errs += sorted(set(_source_errors(b)) - set(_source_errors(a)))
    e2, _ = _model_diff(a, b)
    errs += e2
    return errs


def diff(src, out):
    """What changed between the original and the written session, as the reader sees it: [one line each]."""
    from hypnomix import project as PJ
    a, b = PJ.load(src), PJ.load(out)
    _, changes = _model_diff(a, b)
    return changes + MP.style_changes(a.native, b.native)
