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
marker, or delete it to undo one fix. In an Ardour (Hypnomix) or Live project the same hits are found, but the nudge is
never written: the finding is `applies: manual` with the how-to for that DAW, so it shows on the hand-off checklist
once approved. Not moved (listed instead): items that already have stretch markers, items
that loop past the end of their file, MIDI items, and moves the neighbouring hits leave too little room for.
"""
import re
from pathlib import Path

import numpy as np

from hypnomix.session import timing as TM

DAW_NAMES = {"reaper": "REAPER", "ardour": "Hypnomix (Ardour)", "live": "Live"}


def daw_name(p):
    """The DAW a project is for, in the words the fix text uses ("REAPER", "Hypnomix (Ardour)", "Live")."""
    return DAW_NAMES.get(str(getattr(p, "daw", "") or "reaper").lower(), str(getattr(p, "daw", "") or "your DAW"))


def by_hand(p, ms, lock=False):
    """The fix text for a nudge the project's own DAW gets by hand (hypnomix writes timing into REAPER projects only)."""
    d = str(getattr(p, "daw", "") or "reaper").lower()
    how = {"ardour": "split the region around the hit and slide that piece, or stretch it with the Stretch tool",
           "live": "with a warp marker on the hit"}.get(d, "with stretch markers")
    return (f"nudge {ms:+.0f} ms by hand in {daw_name(p)}" + (" toward the drums" if lock else "") + f": {how} "
            "(hypnomix writes timing nudges into REAPER projects only)")


MELODIC_ROLES = {"guitar", "keys", "synth", "strings", "pad", "brass"}
DRUM_ROLES = {"kick", "snare", "hats", "toms", "overheads", "drums"}


_CHECKED = {}                    # (path, size, modification time) of files dsp.load has passed once in this run
_CHECKED_MAX = 4096
_SEEK_EXACT = {"WAV", "WAVEX", "RF64", "W64", "AIFF", "FLAC", "OGG", "CAF", "AU"}   # seek + read gives the whole-file read's samples to the bit


def item_audio(path, s0, s1):
    """(mono audio from 50 ms before `s0` to 50 ms after `s1` (file seconds), the frame it starts at, the file's sample
    rate). The first time a file is met it is read and checked whole, exactly as dsp.load does (so a file that cannot be
    measured still stops the check with the same plain sentence); every later item on that file reads only its own
    stretch, so 24,000 items on 24 files cost 24 whole reads, not 24,000. The values are those of the whole-file read,
    to the bit, for the formats in _SEEK_EXACT (wav, aiff, flac, ogg...); any other (mp3) is read whole for every item,
    as before, because a seek in it can differ from the whole read at the 1e-7 level."""
    from hypnomix.core import dsp
    path = Path(path)
    try:
        st = path.stat()
        key = (str(path), st.st_size, st.st_mtime_ns)
    except OSError:
        key = None
    if key is not None and key in _CHECKED:
        try:
            import soundfile as sf
            with sf.SoundFile(str(path)) as f:
                if f.format.upper() not in _SEEK_EXACT:
                    raise ValueError("seeking is not sample-exact in this format")   # (mp3 differs at the 1e-7 level): read it whole
                sr, n = int(f.samplerate), int(f.frames)
                a, b = max(0, int((s0 - 0.05) * sr)), min(n, int((s1 + 0.05) * sr))
                if b <= a:
                    return np.zeros(0), a, sr
                f.seek(a)
                return f.read(b - a, dtype="float64", always_2d=True).mean(1), a, sr
        except Exception:
            pass                                          # a format only the whole-file reader opens: read it whole
    y, sr = dsp.load(path)
    if key is not None:
        if len(_CHECKED) >= _CHECKED_MAX:
            _CHECKED.clear()
        _CHECKED[key] = True
    a, b = max(0, int((s0 - 0.05) * sr)), min(len(y), int((s1 + 0.05) * sr))
    return y[a:b].mean(1), a, sr


def item_onsets(c, sr_o=TM.SR_O, hop=TM.HOP_O):
    """[{beat-less hit: t (timeline s), src (source s), strength}] heard from one item's active take."""
    import librosa
    tk = c.take
    s0 = (tk.section[0] if tk.section else 0.0) + tk.offset
    s1 = s0 + c.length * tk.rate
    seg, a, sr = item_audio(tk.path, s0, s1)
    if len(seg) < sr // 2:
        return []
    seg = librosa.resample(seg, orig_sr=sr, target_sr=sr_o) if sr != sr_o else seg
    env = librosa.onset.onset_strength(y=seg, sr=sr_o, hop_length=hop)
    frames = librosa.onset.onset_detect(onset_envelope=env, sr=sr_o, hop_length=hop, backtrack=True, units="frames")
    if not len(frames):
        return []
    peaks = librosa.onset.onset_detect(onset_envelope=env, sr=sr_o, hop_length=hop, backtrack=False, units="frames")
    strength = np.array([env[p] for p in peaks[: len(frames)]])
    src = a / sr + frames * hop / sr_o                # the same detector as Live's `timing`
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


def fixable(c, where="REAPER"):
    """None when stretch markers can be written on this item, else why not (`where`: the DAW, for the by-hand text)."""
    tk = c.take
    if tk is None or tk.kind != "audio":
        return "not an audio item"
    if tk.stretch:
        return f"the item already has stretch markers: nudge it by hand in {where}"
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
        return f"the item loops past the end of its file: nudge it by hand in {where}"
    return None


def analyse(p, tracks, to_grid=False, melodic=(), bass=(), drums=()):
    """tracks: names of audio tracks to check. Returns (tracks with hits, issues, notes) like Live's `timing`."""
    spb = 60.0 / p.tempo
    notes = {"unfixable": {}, "missing": set(), "off": [], "bass": sorted(bass), "drums": sorted(drums),
             "all_onsets": {}, "skipped_missing": 0}   # all_onsets: every onset per item, quiet ones too (the anchors of a nudge)
    out = []
    for name in tracks:
        t = next((x for x in p.tracks if x.name == name), None)
        if t is None or not t.on:
            continue
        hits = []
        for c in t.clips:
            if c.muted or c.kind != "audio" or c.path is None:
                continue
            if not Path(c.path).exists():              # the files group reports it; one lost file must not sink the check
                notes["missing"].add(str(c.path))
                notes["skipped_missing"] += 1
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
    writes = str(getattr(p, "daw", "") or "reaper").lower() == "reaper"     # only a REAPER project gets the markers written
    for i in issues:
        h, c = i["hit"], i["hit"]["clip"]
        tol = max(TM.SLOTS[i["kind"]][0], TM.SLOTS[i["kind"]][1] * notes["looseness"])
        sev = "low" if i.get("optional") else "high" if (i.get("lock") or abs(i["off"]) > 1.5 * tol or
                                                         i["kind"] == "downbeat") else "medium"
        late = "late" if i["off"] > 0 else "early"
        move = i["move"] * strength
        why = fixable(c, daw_name(p))
        # anchors: the onsets either side, quiet ones included (a hit the ghost filter set aside still has to stay
        # where it is: anchoring past it would drag it along with the fix)
        every = notes.get("all_onsets", {}).get(id(c)) or sorted(x["src"] for x in hits_by_clip[id(c)])
        before = [x for x in every if x < h["src"] - 0.005]
        after = [x for x in every if x > h["src"] + 0.005]
        prev_s = before[-1] if before else h["src"] - 0.25 * spb * c.take.rate
        next_s = after[0] if after else h["src"] + 0.25 * spb * c.take.rate
        room = min(h["src"] - prev_s, next_s - h["src"]) / c.take.rate
        if why is None and room < 2.5 * abs(move):
            why = f"the hits either side are too close for a gentle stretch: nudge it by hand in {daw_name(p)}"
        f = dict(id=i["id"], tool="timing", kind=i["kind"], severity=sev, track=i["track"], where=TM.where(i["beat"]),
                 problem=(("OPTIONAL (melodic part: its looseness is part of the feel). " if i.get("optional") else "")
                          + ("LOW END: " if i.get("low") else "")
                          + (f"bass {abs(i['off']) * 1000:.0f} ms {late} against the drums on the {i['kind']}" if i.get("lock")
                             else f"{i['kind']} hit {abs(i['off']) * 1000:.0f} ms {late} against the {i['ref']}")),
                 fix=(why if why else (f"nudge {move * 1000:+.0f} ms with stretch markers"
                                       + (" toward the drums" if i.get("lock") else "")
                                       if writes else by_hand(p, move * 1000, i.get("lock")))
                      + (" (a gentle partial move, not onto the grid; skip it to keep the feel)" if i.get("optional") else "")),
                 applies="manual" if (why or not writes) else "set", optional=bool(i.get("optional")))
        if not why and writes:             # by hand (Ardour, Live): no edit to apply; the hand-off checklist lists it
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
