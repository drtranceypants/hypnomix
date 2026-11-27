"""Read a REAPER project (.rpp) into the import model (hypnomix.project.importer), through HypnoMix's own REAPER
reader (hypnomix.project.reaper).

Carried: tracks (name, order, fader, pan, mute, solo), folders as buses their tracks feed (items on a folder track
go on a track of their own feeding it), audio items (position, length, start in the file, item and take volume,
fades as straight fades, mute, the active take), the master fader, the tempo, the tempo map (square points as steps;
a ramp, taken as straight in time, as small steps of RAMP_STEP seconds or less, so the beats agree with the audio),
the time signature, markers and regions. Listed in the report: plug-ins (the master's too), the other takes, items
played at another rate, looped items longer than their source, stretch markers, MIDI items (kept in the project in
its own form), envelopes, curved fades, time signature changes.
"""
import math
from pathlib import Path

import soundfile as sf

from hypnomix.project import reaper

RAMP_STEP = 0.25                  # seconds: a tempo ramp is written as constant steps this long or shorter


def num(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def markers(root):
    """MARKER lines -> [dict(name, time, end)]: `MARKER idx pos name flags ...`; a region (flags & 1) is two lines
    with one index, its start and its end."""
    out, open_regions = [], {}
    for ln in root.lines("MARKER"):
        tk = ln.tokens
        if len(tk) < 3:
            continue
        idx, pos = tk[1], num(tk[2])
        name = tk[3] if len(tk) > 3 else ""
        flags = int(num(tk[4])) if len(tk) > 4 else 0
        if flags & 1:
            if idx in open_regions:
                m = open_regions.pop(idx)
                m["end"] = pos
                continue
            m = dict(name=name or f"Region {idx}", time=pos, end=None)
            open_regions[idx] = m
            out.append(m)
        else:
            out.append(dict(name=name or f"Marker {idx}", time=pos, end=None))
    return out


def tempo_map(root, bpm):
    """TEMPOENVEX points (`PT seconds bpm shape [time signature] ...`) -> (tempo points over beats, time signature
    changes, ramps). Shape 1 (square) holds to the next point. Any other shape is taken as a straight line in time
    and written as constant steps of RAMP_STEP seconds or less (each at the tempo in its middle), so the session's
    map, which is made of those steps, puts every beat where the ramp puts it."""
    from hypnomix.project.importer import MAX_TEMPO_POINTS
    ch = root.chunk("TEMPOENVEX")
    pts = []
    for ln in (ch.lines("PT") if ch is not None else []):
        tk = ln.tokens
        if len(tk) >= 3:
            pts.append((num(tk[1]), num(tk[2], bpm), int(num(tk[3])) if len(tk) > 3 else 0,
                        len(tk) > 4 and num(tk[4]) > 0))
    pts.sort(key=lambda x: x[0])
    if not pts:
        return [(0.0, bpm)], 0, 0
    out, beat, ramps = [(0.0, pts[0][1] if pts[0][0] <= 0 else bpm)], 0.0, 0
    if pts[0][0] > 0:                                # the project tempo up to the first point
        beat = pts[0][0] * bpm / 60.0
        out += [(beat, bpm), (beat, pts[0][1])]
    for (s0, v0, shape, _), (s1, v1, _, _) in zip(pts, pts[1:]):
        if s1 <= s0:
            out.append((beat, v1))
            continue
        if shape == 1 or abs(v1 - v0) < 1e-9:       # held: one step at the next point
            beat += (s1 - s0) * v0 / 60.0
            out += [(beat, v0), (beat, v1)]
            continue
        ramps += 1
        room = max(1, (MAX_TEMPO_POINTS - len(out)) // 2 - 2)  # never more points than the session keeps: past
        k = max(1, min(math.ceil((s1 - s0) / RAMP_STEP), room))  # that, a ramp gets wider steps
        dt = (s1 - s0) / k
        for i in range(k):
            v = v0 + (v1 - v0) * (i + 0.5) / k       # the tempo in the middle of this step
            out.append((beat, v))                    # a step to v here (two points at one beat) ...
            beat += dt * v / 60.0
            out.append((beat, v))                    # ... held to the end of the step
        out.append((beat, v1))
    return out, sum(1 for p in pts[1:] if p[3]), ramps


def source_seconds(path):
    try:
        return float(sf.info(str(path)).duration)
    except Exception:
        return None


MAX_RPP_BYTES = 16 << 20         # a .rpp's text (a big real one is a few MB)
MAX_RPP_LINES = 2_000_000


def precheck(path):
    """Refuse, before parsing, a .rpp bigger than an import carries: its size, its lines, and its tracks and items
    counted from the text (parsing builds every one, at about 100x the text's size)."""
    from hypnomix.project import importer
    size = path.stat().st_size
    if size > MAX_RPP_BYTES:
        raise SystemExit(f"{path.name}: {size >> 20} MB of project text, more than the {MAX_RPP_BYTES >> 20} MB an "
                         f"import reads; nothing was written")
    raw = path.read_bytes()
    lines = raw.count(b"\n")
    tracks, items = raw.count(b"<TRACK"), raw.count(b"<ITEM")
    for what, have, cap in (("lines", lines, MAX_RPP_LINES), ("tracks", tracks, importer.MAX_TRACKS),
                            ("items", items, importer.MAX_REGIONS)):
        if have > cap:
            raise SystemExit(f"{path.name}: has {have} {what}, more than the {cap} an import carries; nothing was "
                             f"written")


def read(path):
    path = Path(path).expanduser().resolve()
    precheck(path)
    token = reaper.TOUCH_OUTSIDE.set(False)        # absolute paths elsewhere are not touched while reading
    try:
        p = reaper.read(path)
    finally:
        reaper.TOUCH_OUTSIDE.reset(token)
    root = p.native
    # the generic reader's warnings, but not its tempo-map note: the import carries the tempo map
    not_carried = [w for w in getattr(p, "warnings", []) if not w.startswith("the project has a tempo map")]
    from hypnomix.project.importer import Budget
    budget = Budget(path.name)
    tracks, by = [], {}
    curved, other_takes = 0, 0
    for t in p.tracks:
        kind = {"folder": "bus", "midi": "midi"}.get(t.kind, "audio")
        tr = dict(name=t.name, kind=kind, volume=t.volume, pan=t.pan, muted=t.muted, solo=t.solo,
                  regions=[], midi=[], notes=[], plugins=[d.name for d in t.devices], key=f"r{t.index}")
        if t.polarity:
            tr["notes"].append("polarity flipped in the project (not carried)")
        for env in t.envelopes:
            tr["notes"].append(f"{env} envelope (not carried)")
        if t.parent is not None and id(t.parent) in by:
            tr["output"] = by[id(t.parent)]["key"]
        by[id(t)] = tr
        for c in t.clips:
            tk = c.take
            where = f"{t.name} / {c.name or 'item'}"
            if tk is None or c.kind == "empty":
                continue
            if c.kind == "midi":
                tr["notes"].append(f"MIDI item {c.name!r} at {c.start:.2f} s (MIDI items are not carried yet)")
                continue
            if len(c.takes) > 1:
                other_takes += len(c.takes) - 1
            if abs(tk.rate - 1.0) > 1e-6:
                not_carried.append(f"{where}: plays at x{tk.rate:.4f} in the project: placed at its own speed")
            if c.stretch_markers or tk.stretch:
                not_carried.append(f"{where}: stretch markers (placed unstretched)")
            start = tk.offset
            if tk.section:
                start += tk.section[0]
            loop_note = None
            if c.loop and tk.path and reaper._under(tk.path, path.parent):    # never touch a path elsewhere
                dur = source_seconds(tk.path)
                if dur is not None and start + c.length > dur + 1e-3:
                    loop_note = f"item {c.name or 'item'!r}: looped, longer than its file: only its first pass is placed"
            for L, shape in ((c.fade_in, c.fade_in_shape), (c.fade_out, c.fade_out_shape)):
                curved += L > 0 and shape != 0
            reg = dict(name=c.name or tk.name or (Path(tk.path).stem if tk.path else "item"),
                       file=tk.path, position=c.start, start=max(0.0, start), length=c.length,
                       gain=abs(c.level), muted=c.muted, fade_in=c.fade_in, fade_out=c.fade_out,
                       envelope=c.envelope)
            if tk.extra_paths:
                reg["files"] = [tk.path] + list(tk.extra_paths)
            if loop_note:
                reg["notes"] = [loop_note]                    # said only if the region is placed
            budget.add(regions=1)
            if c.level < 0:
                not_carried.append(f"{where}: polarity flipped on the take (not carried)")
            tr["regions"].append(reg)
        tracks.append(tr)
        if kind == "bus" and tr["regions"]:          # items on a folder track: a track of their own, feeding it
            tracks.append(dict(name=f"{t.name} (items)", kind="audio", regions=tr["regions"], midi=[], notes=[
                f"the items of the folder track {t.name!r}, which is a bus here"], output=tr["key"]))
            tr["regions"] = []
    if other_takes:
        not_carried.append(f"{other_takes} other take(s) of items (only each item's active take is carried)")
    if curved:
        not_carried.append(f"{curved} fade(s) with a curved shape: written as straight fades of the same length")
    pts, sig_changes, ramps = tempo_map(root, p.tempo)
    if ramps:
        not_carried.append(f"{ramps} tempo ramp(s): taken as straight in time and written as steps of {RAMP_STEP:g} s or "
                           f"less (each at the tempo in its middle)")
    if sig_changes:
        not_carried.append(f"{sig_changes} time signature change(s) in the tempo map (the first one is used)")
    den = int(p.meter[1])                            # the reader keeps the real meter (beats_per_bar is quarters)
    mv = root.line("MASTER_VOLUME")
    head = root.tokens[1:3] if len(root.tokens) > 2 else []
    saved = f" (saved by version {head[1]})" if len(head) > 1 and head[1] else ""
    master_fx = []
    mfx = root.chunk("MASTERFXLIST")
    for c in (mfx.chunks() if mfx is not None else []):
        if c.name in reaper.FX_TAGS:
            label = c.tokens[1] if len(c.tokens) > 1 else c.name
            master_fx.append(label.split(":", 1)[1].strip() if ":" in label else Path(label).stem)
    if master_fx:
        not_carried.append("the master's plug-ins: " + ", ".join(master_fx))
    model = dict(name=path.stem, source=path, daw=f".rpp project{saved}", rate=p.sample_rate, bpm=p.tempo, tempo=[],
                 tempo_points=pts, num=p.meter[0], den=den, markers=markers(root), tracks=tracks,
                 not_carried=not_carried, warnings=[])
    if mv is not None and len(mv.tokens) > 1:
        model["master_volume"] = num(mv.tokens[1], 1.0)
        if len(mv.tokens) > 2 and abs(num(mv.tokens[2])) > 1e-6:
            not_carried.append("the master's pan (the master is centred)")
    not_carried.append("plug-ins and their settings (each track's are listed); sends and receives")
    return model
