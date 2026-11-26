"""Instrument hits out of time with the band, in a REAPER project: Live's `timing` check on the shared model, with
the nudges written as REAPER stretch markers.

Hits are found in each item's own audio (its take file, from the take's start offset, at its playrate) and placed
on the song's timeline. Everything after that is `session/timing.judge`, the same code the Live check uses: the
song's own grid (straight, triplets or mixed, bar by bar), each player's usual push or lay-back, the band (or the
drums) as the reference, tolerances from the song's looseness, the bass locked to the drums, melodic parts moved
only partway and as an option.

A fix (only approved items, into the new .rpp) puts stretch markers on the item's active take: one on the hit,
moved part of the way to its reference, and one on the hit either side holding it, so only that short stretch of
audio is stretched (REAPER keeps the pitch when the take keeps pitch). Everything stays editable in REAPER: drag a
marker, or delete it to undo one fix. Not moved (listed instead): items that already have stretch markers, items
that loop past the end of their file, MIDI items, and moves the neighbouring hits leave too little room for.
"""
import re

import numpy as np

from hypnomix.session import timing as TM

MELODIC_ROLES = {"guitar", "keys", "synth", "strings", "pad", "brass"}
DRUM_ROLES = {"kick", "snare", "hats", "toms", "overheads", "drums"}


def refine(mono, sr, secs, before=0.06, after=0.08):
    """Each onset moved to the attack it belongs to: on a 1 ms level envelope, the point halfway up from the quietest
    moment just before to the peak just after. The onset detector works on a ~93 ms spectrum window, so on tonal
    parts (bass, guitar) it fires up to half a window EARLY while drums land on time; measured on a planted band,
    the raw detector put bass and guitar 43-50 ms early against the drums, the refined one within 2 ms."""
    h, w = max(1, int(round(0.001 * sr))), max(2, int(round(0.002 * sr)))
    e = np.sqrt(np.convolve(mono.astype(np.float64) ** 2, np.ones(w) / w, "same"))[::h]
    step = h / sr
    out = []
    for s in secs:
        i0, i1 = max(0, int((s - before) / step)), min(len(e) - 1, int((s + after) / step))
        if i1 - i0 < 5:
            out.append(s)
            continue
        seg = e[i0:i1]
        pk = int(np.argmax(seg))
        lo = int(np.argmin(seg[:pk + 1])) if pk > 0 else 0
        half = seg[lo] + 0.5 * (seg[pk] - seg[lo])
        out.append((i0 + lo + int(np.argmax(seg[lo:pk + 1] >= half))) * step)
    return np.array(out)


def item_onsets(c, sr_o=TM.SR_O, hop=TM.HOP_O):
    """[{beat-less hit: t (timeline s), src (source s), strength}] heard from one item's active take."""
    import librosa
    from hypnomix.core import dsp
    tk = c.take
    s0 = (tk.section[0] if tk.section else 0.0) + tk.offset
    s1 = s0 + c.length * tk.rate
    y, sr = dsp.load(tk.path)
    mono = y.mean(1)
    a, b = max(0, int((s0 - 0.05) * sr)), min(len(mono), int((s1 + 0.05) * sr))
    seg = mono[a:b]
    if len(seg) < sr // 2:
        return []
    seg = librosa.resample(seg, orig_sr=sr, target_sr=sr_o) if sr != sr_o else seg
    env = librosa.onset.onset_strength(y=seg, sr=sr_o, hop_length=hop)
    frames = librosa.onset.onset_detect(onset_envelope=env, sr=sr_o, hop_length=hop, backtrack=True, units="frames")
    if not len(frames):
        return []
    peaks = librosa.onset.onset_detect(onset_envelope=env, sr=sr_o, hop_length=hop, backtrack=False, units="frames")
    strength = np.array([env[p] for p in peaks[: len(frames)]])
    src = refine(mono, sr, a / sr + frames * hop / sr_o)
    if tk.stretch:                                     # stretch markers: source -> take time, inverse of the map
        sec0 = tk.section[0] if tk.section else 0.0
        mpos = np.array([m[0] for m in tk.stretch]); msrc = np.array([m[1] for m in tk.stretch]) + sec0
        tau = np.interp(src, msrc, mpos)
        tau = np.where(src < msrc[0], mpos[0] + (src - msrc[0]), tau)
        tau = np.where(src > msrc[-1], mpos[-1] + (src - msrc[-1]), tau)
        t = c.start + tau / tk.rate
    else:
        t = c.start + (src - s0) / tk.rate
    keep = (t >= c.start) & (t < c.end)
    return [dict(t=float(x), src=float(s), strength=float(st)) for x, s, st in zip(t[keep], src[keep], strength[keep])]


def fixable(c):
    """None when stretch markers can be written on this item, else why not."""
    tk = c.take
    if tk is None or tk.kind != "audio":
        return "not an audio item"
    if tk.stretch:
        return "the item already has stretch markers: nudge it by hand in REAPER"
    import soundfile as sf
    try:
        dur = sf.info(str(tk.path)).duration
    except Exception:
        from hypnomix.core import dsp
        try:
            y, sr = dsp.load(tk.path)
            dur = len(y) / sr
        except Exception:
            return "its file could not be read"
    s0 = (tk.section[0] if tk.section else 0.0) + tk.offset
    if c.loop and s0 + c.length * tk.rate > (tk.section[0] + tk.section[1] if tk.section else dur) + 1e-3:
        return "the item loops past the end of its file: nudge it by hand in REAPER"
    return None


def analyse(p, tracks, to_grid=False, melodic=(), bass=(), drums=()):
    """tracks: names of audio tracks to check. Returns (tracks with hits, issues, notes) like Live's `timing`."""
    spb = 60.0 / p.tempo
    notes = {"unfixable": {}, "missing": set(), "off": [], "bass": sorted(bass), "drums": sorted(drums),
             "all_onsets": {}}                     # every onset per item, quiet ones too: the anchors of a nudge
    out = []
    for name in tracks:
        t = next((x for x in p.tracks if x.name == name), None)
        if t is None or not t.on:
            continue
        hits = []
        for c in t.clips:
            if c.muted or c.kind != "audio" or c.path is None:
                continue
            found = item_onsets(c)
            notes["all_onsets"][id(c)] = sorted(h["src"] for h in found)
            for h in found:
                h.update(beat=h["t"] / spb, sec=h["src"], clip=c, track=name)
                hits.append(h)
        if not hits:
            continue
        floor = np.percentile([h["strength"] for h in hits], TM.GHOST_PCT)
        hits = [h for h in sorted(hits, key=lambda h: h["beat"]) if h["strength"] >= floor]
        clean = []
        for h in hits:                                  # a player's own flams/drags are left as played
            if clean and (h["beat"] - clean[-1]["beat"]) * spb < 0.040:
                continue
            clean.append(h)
        out.append((name, t, clean))
    out, issues = TM.judge(out, spb, notes, to_grid, melodic, bass, drums)
    for n, i in enumerate(issues, 1):
        i["id"] = f"timing-{n}"
    return out, issues, notes


def findings(p, tracks, issues, notes, strength=1.0):
    """Findings in the scan's format, each fixable one carrying its stretch-marker edit."""
    from hypnomix.project.rpp_edit import locator
    spb = 60.0 / p.tempo
    hits_by_clip, track_of = {}, {name: t for name, t, _ in tracks}
    for _, _, hs in tracks:
        for h in hs:
            hits_by_clip.setdefault(id(h["clip"]), []).append(h)
    out = []
    for i in issues:
        h, c = i["hit"], i["hit"]["clip"]
        tol = max(TM.SLOTS[i["kind"]][0], TM.SLOTS[i["kind"]][1] * notes["looseness"])
        sev = "low" if i.get("optional") else "high" if (i.get("lock") or abs(i["off"]) > 1.5 * tol or
                                                         i["kind"] == "downbeat") else "medium"
        late = "late" if i["off"] > 0 else "early"
        move = i["move"] * strength
        why = fixable(c)
        # anchors: the onsets either side, quiet ones included (a hit the ghost filter set aside still has to stay
        # where it is: anchoring past it would drag it along with the fix)
        every = notes.get("all_onsets", {}).get(id(c)) or sorted(x["src"] for x in hits_by_clip[id(c)])
        before = [x for x in every if x < h["src"] - 0.005]
        after = [x for x in every if x > h["src"] + 0.005]
        prev_s = before[-1] if before else h["src"] - 0.25 * spb * c.take.rate
        next_s = after[0] if after else h["src"] + 0.25 * spb * c.take.rate
        room = min(h["src"] - prev_s, next_s - h["src"]) / c.take.rate
        if why is None and room < 2.5 * abs(move):
            why = "the hits either side are too close for a gentle stretch: nudge it by hand in REAPER"
        f = dict(id=i["id"], tool="timing", kind=i["kind"], severity=sev, track=i["track"], where=TM.where(i["beat"]),
                 problem=(("OPTIONAL (melodic part: its looseness is part of the feel). " if i.get("optional") else "")
                          + ("LOW END: " if i.get("low") else "")
                          + (f"bass {abs(i['off']) * 1000:.0f} ms {late} against the drums on the {i['kind']}" if i.get("lock")
                             else f"{i['kind']} hit {abs(i['off']) * 1000:.0f} ms {late} against the {i['ref']}")),
                 fix=(why if why else f"nudge {move * 1000:+.0f} ms with stretch markers"
                      + (" toward the drums" if i.get("lock") else "")
                      + (" (a gentle partial move, not onto the grid; skip it to keep the feel)" if i.get("optional") else "")),
                 applies="manual" if why else "set", optional=bool(i.get("optional")))
        if not why:
            f["edit"] = dict(op="timing", item=locator(track_of[i["track"]], c), src=h["src"], move=move,
                             prev=prev_s, next=next_s)
        out.append(f)
    return out


# ---------------------------------------------------------------- writing stretch markers
def apply(p, fixes):
    """fixes: [(finding, edit)] approved. Stretch markers per item: a holding marker on each neighbour and the moved
    marker on each hit (a moved marker wins over another fix's holding marker at the same place). Returns
    ([done ids], [(finding, why skipped)])."""
    from hypnomix.project import rpp
    from hypnomix.project.rpp_edit import locate
    by_item, skipped = {}, []
    for f, ed in fixes:
        hit = locate(p, ed["item"])
        if hit is None:
            skipped.append((f, "its item is no longer where the scan found it"))
            continue
        by_item.setdefault(id(hit[1]), (hit[1], []))[1].append((f, ed))
    done = []
    for c, items in by_item.values():
        tk = c.take
        s0 = (tk.section[0] if tk.section else 0.0)
        pos = lambda src: (src - s0 - tk.offset)                  # take time of a source position, unstretched
        marks = {}                                                 # source seconds -> (take time, moved?)
        for f, ed in items:
            for s in (ed["prev"], ed["next"]):
                key = round(s, 6)
                if key not in marks:
                    marks[key] = (pos(s), False)
        ok_ids = []
        for f, ed in items:
            marks[round(ed["src"], 6)] = (pos(ed["src"]) + ed["move"] * tk.rate, True)
            ok_ids.append(f["id"])
        pts = sorted((s, tt) for s, (tt, _) in marks.items())
        L = c.length * tk.rate
        if any(b[1] <= a[1] + 1e-4 for a, b in zip(pts, pts[1:])) or any(tt < 0 or tt > L for _, tt in pts):
            skipped += [(f, "the stretch markers would cross: nudge these hits by hand in REAPER") for f, _ in items]
            continue
        toks = []
        for s, tt in pts:
            toks += (["+"] if toks else []) + [float(tt), float(s - s0)]
        group = tk.native
        pr = next((x for x in group if isinstance(x, rpp.Line) and x.key == "PLAYRATE"), None)
        item = c.native
        at = item.children.index(pr) + 1 if pr is not None and pr in item.children else None
        line = rpp.Line(["SM", *toks])
        item.add(line, at=at)
        group.insert(group.index(pr) + 1 if pr in group else len(group), line)
        tk.stretch = [(tt, s - s0) for s, tt in pts]
        done += ok_ids
    return done, skipped
