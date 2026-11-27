"""`hypnomix vocallevel` on a REAPER project (.rpp), from the shared project model: the same line split, `upper` and
`jump` checks, report and JSON as for a Live set (`session/vocallevel.py`), and `--apply NEW.rpp` writes the same
fixes as smooth S-curve points on track volume envelopes.

    hypnomix vocallevel SONG.rpp [--renders DIR | --heard DIR] [--tracks ...] [--melody TRACK] [--order ORDER]
                       [--jump 1.5] [--upper-under 1.5] [--keep-ending 2] [--json OUT.json]
                       [--apply NEW.rpp [--group FOLDER]]

Where the levels come from:
  (neither)      each vocal track rendered from the project (items, takes, fades; no FX), then multiplied by what
                 the project does to its level after that: the track's fader and its volume envelopes (post-FX,
                 pre-FX and trim; a fader-scaled envelope, VOLTYPE 1, followed in fader position as REAPER plays it),
                 and the same for every folder above it. Track compressors are not modelled: a first look.
  --renders DIR  raw renders (scan's raw/renders/, one file per track named after it): the same fader and envelope
                 curve is applied.
  --heard DIR    one file per vocal track already as heard (REAPER: solo each track and render): used as they are.

Tracks: --tracks, else every file in the folder, else every heard audio track whose name says vocal (lead,
harmony, backing, vox ...). Measuring works on any project `project.load` reads; --apply writes REAPER projects.

--apply NEW.rpp: the upper trims (at most 4 dB) go on each upper part's volume envelope (VOLENV2, created at 1.0
when the track has none: REAPER multiplies it with the fader), the line evening (at most 3 dB) on the melody's
folder (--group) when everything in that folder is a vocal (MIDI and instrument tracks count as non-vocals) and the
folder has no trims of its own, else on each vocal track (once: a vocal under a vocal folder gets it from the
folder). Every change is a raised-cosine S-curve about 1.2 s long, a point every 0.1 s, centred in the gap between
lines; existing points are kept and scaled by the change, so deliberate rides survive. A track whose existing points
in a change window are curved or square (any shape but linear) is refused and listed: make that change by hand. The
original is never written, under any spelling of its name, and neither is any existing file: an --apply or --json
name that is already there is refused before anything is measured (`rpp.save` refuses them too). The new project
then goes through the same structure check as `fix` (renamed "(BROKEN, do not open)", numbered when that name is
taken, when it fails) and is measured again with the new envelopes.

Envelope points far from every change are left exactly as they are. A track whose envelope is above +6 dB (REAPER's
volume envelope top as HypnoMix writes it) in a change window, or that a change would push above it, is refused and
listed rather than clipped: make that change by hand. Whether REAPER itself stores volume points above +6 dB has
not been checked in REAPER.

Checked by unit tests on synthetic projects; on 2026-11-26 the --apply envelopes were opened in REAPER 7.86 on a
two-track test project and read back (106 points, all within +-3 dB; written before the 2026-11-27 change that leaves untouched points as they
are and refuses hot envelopes, which is unit-tested only); not run on a real song, not judged by ear.
"""
import json
import sys
from pathlib import Path

import numpy as np

from hypnomix import project as PJ
from hypnomix.project.model import envelope_at
from hypnomix.session import vocallevel as VL

SR = 44100
VOLUME_ENVELOPES = ("Volume", "Volume (pre-FX)", "Trim Volume")    # every one multiplies the level heard
GRID_S = 0.01


# ---------------------------------------------------------------- reading
def find_track(p, name, prefix=False):
    """The track called `name`: exact name, then file-safe name, then the same ignoring case. A name that only
    begins a track's name matches only with prefix=True (names the user typed) and only when one track begins so;
    file stems never do, so a render that matches no track is never put on another one."""
    exact = next((t for t in p.tracks if t.name == name), None) or \
        next((t for t in p.tracks if t.safe_name == name), None)
    if exact is not None:
        return exact
    low = name.lower()
    same = [t for t in p.tracks if t.name.lower() == low] or [t for t in p.tracks if t.safe_name.lower() == low]
    if same:
        return same[0]
    if prefix:
        begins = [t for t in p.tracks if t.name.lower().startswith(low)]
        if len(begins) == 1:
            return begins[0]
    return None


def gain_curve(track, n, sr):
    """The track's level multiplier over n samples as heard after its items: fader x volume envelopes, for the track
    and every folder above it. Envelopes are evaluated on a 10 ms grid and interpolated."""
    grid = np.arange(int(n / sr / GRID_S) + 2) * GRID_S
    g = np.ones_like(grid)
    t = track
    while t is not None:
        g *= t.volume
        for lab in VOLUME_ENVELOPES:
            pts = t.envelopes.get(lab)
            if pts:
                g *= envelope_at(pts, grid, fader=lab in getattr(t, "fader_envelopes", ()))
        t = t.parent
    return np.interp(np.arange(n) / sr, grid, g).astype(np.float32)


def vocal_tracks(p):
    """Heard audio tracks whose names say vocal."""
    from hypnomix.engineer import roles as RO
    return [t.name for t in p.audio_tracks() if RO.by_name(t.name) in ("lead_vocal", "backing_vocal")]


def signals(p, a):
    """({track name: mono signal as heard}, sr, how measured)."""
    from hypnomix.session.vocallevel import _load
    folder = Path(a.renders or a.heard) if (a.renders or a.heard) else None
    if folder is not None:
        files = {f.stem: f for f in sorted(folder.glob("*.wav"))}
        names = a.tracks or list(files)
        sig, sr = {}, None
        for name in names:
            t = find_track(p, name, prefix=bool(a.tracks))
            f = files.get(name) or (files.get(t.safe_name) if t is not None else None)
            if f is None:
                continue
            label = t.name if t is not None else name
            y, sr = _load(f)
            if a.renders:
                if t is None:
                    print(f"  {name}: no such track in the project, its file is used as it is")
                else:
                    y = y * gain_curve(t, len(y), sr)
            sig[label] = y.astype(np.float32)
        how = "as heard (solo renders)" if a.heard else "renders x fader x volume envelopes (FX not modelled)"
        return sig, sr, how
    names = a.tracks or vocal_tracks(p)
    sig, warn = {}, []
    L = p.end()
    for name in names:
        t = find_track(p, name, prefix=bool(a.tracks))
        if t is None:
            print(f"  {name}: no such track in the project")
            continue
        y = p.render(t, SR, L, warn).astype(np.float32)
        if not np.any(y):
            continue
        sig[t.name] = y * gain_curve(t, len(y), SR)
    for w in dict.fromkeys(warn):
        print(f"  warning: {w}")
    return sig, SR, "rendered from the project x fader x volume envelopes (FX not modelled)"


# ---------------------------------------------------------------- folders
def _descendants(p, folder):
    out, todo = [], [folder]
    while todo:
        f = todo.pop()
        for c in p.children(f):
            out.append(c)
            todo.append(c)
    return out


def folder_of(p, name):
    t = find_track(p, name) if name else None
    return t.parent.name if t is not None and t.parent is not None else None


def non_vocal_members(p, folder, vocals):
    """Tracks under `folder` that play audio or MIDI and are not vocals (the folder's own items count; a MIDI or
    instrument track counts even without items): automating the folder would ride them too. None when `folder` is
    no folder track."""
    f = next((t for t in p.tracks if t.name == folder), None)
    if f is None or f.kind != "folder":
        return None
    vs = set(vocals)
    plays = lambda t: t.kind == "midi" or any(c.kind in ("audio", "midi") for c in t.clips)
    out = [t.name for t in _descendants(p, f) if t.name not in vs and plays(t)]
    if f.name not in vs and any(c.kind in ("audio", "midi") for c in f.clips):
        out.insert(0, f"{f.name} (its own items)")
    return out


# ---------------------------------------------------------------- writing
def _shape(ln):
    """A PT line's shape: 0 linear, 1 square, 2 slow start/end, 3 fast start, 4 fast end, 5 bezier."""
    try:
        return int(float(ln.tokens[3])) if len(ln.tokens) > 3 else 0
    except ValueError:
        return 0


def _curved_in(pts, windows):
    """The time of the first existing point whose segment to the next point is not a straight line (shape != 0,
    between different values) and overlaps a change window, else None. New points there would be placed on a
    straight-line reading of a curve and split it, changing the ride by more than the plan."""
    for (t0, v0, ln), (t1, v1, _) in zip(pts, pts[1:]):
        if _shape(ln) == 0 or abs(v1 - v0) < 1e-9:
            continue
        if any(t0 < w1 and t1 > w0 for w0, w1 in windows):
            return t0
    return None


def write_gains(track, segs, ramp=VL.RAMP_S, step=VL.STEP_S):
    """Multiply the track's volume envelope by the per-line gains as smooth S-curves (VL.smooth_db): a point every
    `step` s through each change, and every existing point scaled by the curve where it sits, so the existing
    envelope is kept and only offset. Returns the number of lines changed."""
    from hypnomix.project import rpp
    from hypnomix.project import rpp_edit as E
    segs = sorted(segs)
    if not any(abs(g) > 1e-3 for _, _, g in segs):
        return 0
    env = E.volume_envelope(track)
    if env is None:
        raise ValueError(f"{track.name}: its volume envelope is switched off; switch it on, or make this change by hand")
    fader = E.is_fader(env)
    pts = E.points(env)
    have = {round(t, 4) for t, _, _ in pts}
    secs, windows = set(), []
    for a, b, _ in VL._steps(segs, ramp):            # every change sits on a step edge: sample its whole S-curve
        for e in (a, b):
            windows.append((e - ramp / 2 - step, e + ramp / 2 + step))
            secs.update(round(float(q), 4) for q in np.arange(e - ramp / 2 - step, e + ramp / 2 + step + 1e-9, step))
    curved = _curved_in(pts, windows)
    if curved is not None:
        raise ValueError(f"{track.name}: has curved/square envelope points in the change window (at {curved:.2f} s); "
                         f"make this change by hand")
    secs = sorted(q for q in secs if q >= 0 and q not in have)
    lin = lambda d: 10 ** (d / 20)
    moves = []                                         # (existing point, new value): only where the curve moves
    for (t, v, ln), d in zip(pts, VL.smooth_db(segs, [t for t, _, _ in pts], ramp)):
        if t >= 0 and abs(d) >= 1e-3:
            moves.append((t, v, ln, v * lin(d)))
    new_pts = []
    for q, d in zip(secs, VL.smooth_db(segs, secs, ramp)):
        b = E.value_at(pts, q, fader)                  # the envelope as REAPER plays it now, there
        new_pts.append((q, b, b * lin(d)))
    top = E.MAX_LIN + 1e-9                             # never clip: a ride above +6 dB would be cut down silently
    hot = next((t for t, v, _, nv in moves if v > top or nv > top), None)
    if hot is None:
        hot = next((q for q, b, nv in new_pts if b > top or nv > top), None)
    if hot is None:
        hot = next((t for t, v, _ in pts if v > top and any(w0 <= t <= w1 for w0, w1 in windows)), None)
    if hot is not None:
        raise ValueError(f"{track.name}: its volume envelope is, or would go, above +6 dB in the change window "
                         f"(at {hot:.2f} s); make this change by hand")
    old = env.lines("PT")
    ind = old[0].indent if old else env._child_indent()
    at = env.children.index(old[0]) if old else len(env.children)
    for ln in old:
        env.children.remove(ln)
    for t, v, ln, nv in moves:                         # an existing point keeps its shape and flags, scaled
        tk = list(ln.tokens)
        tk[2] = float(max(0.0, nv))
        ln.set(*tk[1:])
    out = [(t, ln) for t, _, ln in pts]                # every other point is put back exactly as it was
    for q, _, nv in new_pts:
        out.append((q, rpp.Line(["PT", float(q), float(max(0.0, nv)), 0], indent=ind)))
    out.sort(key=lambda x: x[0])                       # stable: points at one time keep their order
    for k, (_, ln) in enumerate(out):
        env.children.insert(at + k, ln)
    return sum(1 for _, _, g in segs if abs(g) > 1e-3)


def apply_gains(p, gains, group, vocals, log=print):
    """Write the plan's gains into the loaded project. The line evening goes on `group` only when it is a folder
    holding nothing but vocals, with every vocal inside it; otherwise on each vocal track, added to its own trims.
    Returns (done lines, steepest dB/s, refused)."""
    gains = {k: list(v) for k, v in gains.items()}
    gg = gains.pop("__group__", [])
    if any(abs(g) > 1e-3 for _, _, g in gg):
        other = non_vocal_members(p, group, vocals) if group else None
        f = next((t for t in p.tracks if t.name == group), None) if group else None
        inside = {t.name for t in _descendants(p, f)} if f is not None else set()
        outside = [v for v in vocals if v not in inside and v != group]
        own_trims = any(abs(g) > 1e-3 for _, _, g in gains.get(group, [])) if group else False
        if other is None or other or outside or own_trims:
            if own_trims and not other and other is not None and not outside:
                log(f"  {group} has its own trims: the line evening goes on each vocal track")
            if other:
                log(f"  {group} also holds {', '.join(other)}: not automating the folder (it would ride them with "
                    f"every vocal line); the line evening goes on the vocal tracks instead")
            elif group and other is None:
                log(f"  {group} is not a folder track: the line evening goes on the vocal tracks instead")
            elif outside and not group:
                log("  no folder holds the vocals: the line evening goes on each vocal track")
            elif outside:
                log(f"  {', '.join(outside)} not inside {group}: the line evening goes on the vocal tracks instead")
            vs = set(vocals)
            for v in vocals:
                own = {(a, b): g for a, b, g in gains.get(v, [])}
                t = find_track(p, v)
                up = t.parent if t is not None else None
                while up is not None and up.name not in vs:
                    up = up.parent
                if up is not None:          # a vocal folder above it carries the evening: never twice
                    if own:
                        gains[v] = [(a, b, g) for (a, b), g in own.items()]
                    continue
                gains[v] = [(a, b, own.get((a, b), 0.0) + g) for a, b, g in gg]
        else:
            gains[group] = gg
    done, worst, refused = [], 0.0, []
    for name, segs in gains.items():
        t = find_track(p, name)
        if t is None:
            refused.append(f"{name}: no such track")
            continue
        try:
            k = write_gains(t, segs)
        except ValueError as e:
            refused.append(str(e))
            continue
        if k:
            sl = VL.steepest(segs)
            worst = max(worst, sl)
            done.append(f"{t.name}: {k} line(s), steepest {sl:.1f} dB/s")
    return done, worst, refused


# ---------------------------------------------------------------- the command
def _plan(sig, sr, a, melody, order):
    return VL.plan(sig, sr, melody, order, a.jump, a.upper_under, a.keep_ending, a.lines_from)


def remeasure(old_path, new_path, sig, sr, a, melody, order):
    """The signals as the new project plays them: each one times (new level curve / old), measured again."""
    p_old, q = PJ.load(old_path), PJ.load(new_path)
    sig2 = {}
    for name, y in sig.items():
        t0, t1 = find_track(p_old, name), find_track(q, name)
        if t0 is None or t1 is None:
            sig2[name] = y
            continue
        c0, c1 = gain_curve(t0, len(y), sr), gain_curve(t1, len(y), sr)
        r = np.where(c0 > 1e-9, c1 / np.maximum(c0, 1e-9), 1.0).astype(np.float32)
        sig2[name] = y * r
    return _plan(sig2, sr, a, melody, order)


def run(a):
    src = Path(a.als)
    VL.check_paths(a)                         # a missing project, an existing --apply/--json: one sentence, early
    ardour = PJ.ardour_session(src) is not None or src.suffix.lower() == ".ardour"
    if a.apply and Path(a.apply).suffix.lower() != (".ardour" if ardour else ".rpp"):
        sys.exit("--apply writes REAPER projects (SONG.rpp --apply NEW.rpp), HypnoMix Studio sessions (SESSION.ardour "
                 "--apply NEW.ardour, or --engine into the open session) and Live sets; for this project make the "
                 "moves by hand from the report")
    if getattr(a, "engine", None) is not None and not ardour:
        sys.exit("--engine writes into a HypnoMix Studio session the engine has open: give that session (.ardour)")
    if getattr(a, "engine", None) is not None and a.apply:
        sys.exit("choose one: --engine (into the open session) or --apply NEW.ardour (a new snapshot)")
    p = PJ.load(src)
    sig, sr, how = signals(p, a)
    if not sig:
        sys.exit("no vocal tracks found: name them (Lead Vocal, Harmony ...) or pass --tracks")
    tracks = list(sig)
    from hypnomix.engineer import roles as RO
    melody = a.melody
    if melody and melody not in sig:
        t = find_track(p, melody, prefix=True)
        melody = t.name if t is not None else melody
    for opt, val in (("--melody", melody if a.melody else None), ("--lines-from", a.lines_from)):
        if val and val not in sig:            # a misspelt name would be measured as silence (as in the Live path)
            sys.exit(f"{opt}: no track called {val!r} (the tracks are: {', '.join(tracks)})")
    melody = melody or next((t for t in tracks if t.lower().startswith("lead")), None) or \
        next((t for t in tracks if RO.by_name(t) == "lead_vocal"), None)
    order = VL.pitch_order(a.order, sig, sr)
    rows, findings, gains = _plan(sig, sr, a, melody, order)
    VL.report(src.name, tracks, rows, findings, how, order, melody)
    if a.json:
        VL.write_new_text(a.json, json.dumps(dict(tool="vocallevel", set=str(src), daw=p.daw, measured=how,
                                                  order=order, melody=melody, lines=rows, findings=findings,
                                                  gains=gains), default=float, indent=1))
    if p.daw == "ardour" and (a.apply or getattr(a, "engine", None) is not None):
        from hypnomix.workflow import vocallevel_ardour as VA
        rc = VA.run(p, src, a, gains, tracks, melody)
        if rc:
            sys.exit(rc)                      # (the command line ignores what main returns)
        return rc
    if not a.apply:
        return 0
    out = Path(a.apply)
    if p.daw != "reaper" or out.suffix.lower() != ".rpp":
        sys.exit("--apply writes REAPER projects (SONG.rpp --apply NEW.rpp) and Live sets; for this project make the "
                 "moves by hand from the report")
    from hypnomix.project import rpp_edit as E
    grp = a.group or folder_of(p, melody)
    done, worst, refused = apply_gains(p, gains, grp, tracks)
    for r in refused:
        print(f"  not written: {r}")
    if not done:
        print(f"nothing to change: {out} not written")
        return 0 if not refused else 1
    E.save(p, out)                            # a new file: rpp.save refuses the original and any existing file
    errs = E.check(src, out)
    if errs:
        from hypnomix.project import rpp
        bad = rpp.free_name(out.with_name(out.stem + " (BROKEN, do not open).rpp"))     # never over an earlier one
        out.replace(bad)
        print(f"check FAILED: the written project is not sound. Renamed to {bad.name}; keep using the original.")
        for e in errs:
            print(f"  {e}")
        return 1
    print(f"wrote {out}: " + "; ".join(done))
    print(f"  smooth S-curves ({VL.RAMP_S:g} s, a point every {VL.STEP_S:g} s); steepest move {worst:.1f} dB/s")
    print("  structure check OK (same tracks, folders, items, positions and lengths)")
    rows2, findings2, _ = remeasure(src, out, sig, sr, a, melody, order)
    sp0, sp1 = VL.spread(rows), VL.spread(rows2)
    print(f"  measured again: {len(findings2)} finding(s), was {len(findings)}"
          + (f"; spread (10-90%) {sp0[2] - sp0[1]:.1f} → {sp1[2] - sp1[1]:.1f} dB" if sp0 and sp1 else ""))
    for f in findings2:
        print(f"    {f['kind']:<17} {f['where']:<17} {f['problem']}")
    return 0
