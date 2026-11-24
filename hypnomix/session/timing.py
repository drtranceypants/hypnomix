#!/usr/bin/env python3
"""Find instrument hits that are out of time with the band, and nudge only those, keeping the feel.

Reads a saved Live set (.als) and the audio each Arrangement clip plays. On every chosen track it
finds the transients (drum hits, picked notes, piano attacks), places each on the song's 16th-note
grid, and compares it with its REFERENCE:

  band  the median of the other chosen tracks hitting the same slot, when at least two do (default).
        A band that is consistently a little behind the click keeps that feel; only hits that
        disagree with the rest of the band are flagged ("flams" between parts meant to land together).
  grid  otherwise: the grid plus that player's own usual push or lay-back (so their feel stays),
        or with --to-grid, the bare grid.

Tolerances follow the song's own looseness (the typical player's timing spread), so only clear
outliers count as messy. Downbeats are held tightest, upbeats loosest:

  slot        tolerance                       moved
  downbeat    2.0 x looseness (min 12 ms)     80%     (beat 1 of the bar)
  beat        2.5 x looseness (min 20 ms)     60%     (beats 2, 3, 4)
  8th upbeat  3.0 x looseness (min 30 ms)     40%
  16th        3.5 x looseness (min 40 ms)     30%

Hits inside their tolerance are never touched. Soft ghost notes are ignored, and a track's own
flams (two hits within 40 ms) are left alone. The report lists the messiest bars first.

--apply writes a NEW set (same folder as the original) where each fixed hit gets warp markers:
one on the hit, moved part of the way to its reference, and one on the hits either side, holding
them, so only that small stretch of audio is stretched. Everything stays editable in Live (drag
the markers, or delete them to undo one fix). Only warped, non-looping clips can be fixed; others
are reported.

Usage:
  hypnomix timing SET.als [--track Drums --track Bass ...] [--to-grid]
  hypnomix timing SET.als --track ... --apply "SET (timing).als" [--strength 1.0]
Close the set in Live before --apply. Assumes a constant tempo and 4/4.
"""
import argparse, math, sys
from pathlib import Path

import numpy as np
import librosa

from hypnomix.session import automation as aa
from hypnomix.session import smooth as sm   # clip -> audio mapping, track selection

BPB = 4
SLOTS = {  # name: (minimum tolerance s, multiple of the song's own looseness, share of the error to remove)
    "downbeat": (0.012, 2.0, 0.8),
    "beat": (0.020, 2.5, 0.6),
    "8th": (0.030, 3.0, 0.4),
    "16th": (0.040, 3.5, 0.3),
    "triplet": (0.030, 3.0, 0.4),       # 8th-note triplets: as loose as off-beat 8ths
    "16th triplet": (0.040, 3.5, 0.3),
}
# Melodic parts (guitar, keys, strings) carry the feel: only clear outliers, only as an option, and only partway.
MELODIC_TOL = 1.5      # their tolerance is this many times the usual one
MELODIC_SHARE = 0.3    # move at most this share of the error (never fully onto the band or grid)
MELODIC_MAX = 0.015    # and never more than 15 ms
SEARCH = 0.070        # a hit more than this from a 16th slot isn't assigned to it
GHOST_PCT = 60        # ignore hits weaker than this percentile of the track's onsets
SR_O = 22050
HOP_O = 64            # ~3 ms onset resolution


def slot_kind(key12):
    """What kind of grid line a hit sits on, from its position in twelfths of a beat (holds 16ths and triplets)."""
    if key12 % (12 * BPB) == 0:
        return "downbeat"
    if key12 % 12 == 0:
        return "beat"
    if key12 % 6 == 0:
        return "8th"
    if key12 % 4 == 0:
        return "triplet"
    if key12 % 3 == 0:
        return "16th"
    return "16th triplet"


# ---------------------------------------------------------------- onsets per clip
def clip_onsets(ci, tempo):
    """Onsets (arrangement beats, strength, file seconds) heard from one clip."""
    y, sr, _ = sm.load_audio(ci["path"])
    mono = y.mean(1)
    span_b = np.array([ci["start"], ci["end"]])
    s0, s1 = sm.file_seconds(ci, span_b, tempo)
    if ci["loop_on"] or s1 <= s0:
        # looping clips: map each repeat separately is not supported for fixes; analyse the first pass
        s1 = max(s1, s0 + 0.5)
    a, b = max(0, int(s0 * sr) - int(0.05 * sr)), min(len(mono), int(s1 * sr) + int(0.05 * sr))
    seg = mono[a:b]
    if len(seg) < sr // 2:
        return []
    seg = librosa.resample(seg, orig_sr=sr, target_sr=SR_O) if sr != SR_O else seg
    env = librosa.onset.onset_strength(y=seg, sr=SR_O, hop_length=HOP_O)
    frames = librosa.onset.onset_detect(onset_envelope=env, sr=SR_O, hop_length=HOP_O,
                                        backtrack=True, units="frames")
    if not len(frames):
        return []
    peaks = librosa.onset.onset_detect(onset_envelope=env, sr=SR_O, hop_length=HOP_O,
                                       backtrack=False, units="frames")
    strength = np.array([env[p] for p in peaks[: len(frames)]])
    secs = a / sr + frames * HOP_O / SR_O
    # file seconds -> clip beats -> arrangement beats (inverse of the warp map)
    beats = file_to_arr(ci, secs, tempo)
    keep = (beats >= ci["start"]) & (beats < ci["end"])
    return [dict(beat=float(bt), sec=float(sc), strength=float(st))
            for bt, sc, st in zip(beats[keep], secs[keep], strength[keep])]


def content_start(ci):
    return ci["ls"] + (ci["rel"] if ci["loop_on"] else 0.0)


def file_to_arr(ci, secs, tempo):
    secs = np.asarray(secs, dtype=float)
    if ci["warped"] and len(ci["markers"]) >= 2:
        b, s = (np.array(x) for x in zip(*ci["markers"]))
        clip_b = np.interp(secs, s, b)
        lo = (b[1] - b[0]) / max(1e-9, s[1] - s[0])        # beats per second before the first marker
        hi = (b[-1] - b[-2]) / max(1e-9, s[-1] - s[-2])    # and after the last one
        clip_b = np.where(secs < s[0], b[0] + (secs - s[0]) * lo, clip_b)
        clip_b = np.where(secs > s[-1], b[-1] + (secs - s[-1]) * hi, clip_b)
    elif ci["warped"]:
        clip_b = secs * tempo / 60.0
    else:
        return ci["start"] + (secs - content_start(ci)) * tempo / 60.0
    return ci["start"] + (clip_b - content_start(ci))


def arr_to_clipbeat(ci, arr_beats):
    return content_start(ci) + (np.asarray(arr_beats, dtype=float) - ci["start"])


# ---------------------------------------------------------------- analysis
def analyse(root, als_dir, names, to_grid, include_off=False, melodic=()):
    tempo = float(root.find(".//Tempo/Manual").get("Value"))
    spb = 60.0 / tempo                     # seconds per beat
    tracks, notes = [], {"unfixable": {}, "missing": set(), "off": []}
    for tname, t in sm.audio_tracks(root, names, include_off, notes["off"]):
        ev = t.find("./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events")
        if ev is None:
            continue
        hits = []
        for c in ev.findall("AudioClip"):
            ci = sm.clip_info(c, als_dir, tempo)
            if ci["disabled"]:
                continue
            if not ci["path"].exists():
                notes["missing"].add(str(ci["path"]))
                continue
            for h in clip_onsets(ci, tempo):
                h["clip"] = ci
                hits.append(h)
        if not hits:
            continue
        floor = np.percentile([h["strength"] for h in hits], GHOST_PCT)
        hits = [h for h in sorted(hits, key=lambda h: h["beat"]) if h["strength"] >= floor]
        # a track's own flams/drags (two hits within 40 ms) are left as played
        clean = []
        for h in hits:
            if clean and (h["beat"] - clean[-1]["beat"]) * spb < 0.040:
                continue
            clean.append(h)
        for h in clean:
            h["track"] = tname
        tracks.append((tname, t, clean))
    # the song's own grid (straight 16ths, triplets or mixed, bar by bar), from every track's hits
    from hypnomix.core import grid as G
    allh = [h for _, _, hs in tracks for h in hs]
    g = G.detect([h["beat"] for h in allh], [h["strength"] for h in allh], BPB)
    notes["grid"] = g.summary()
    kept = []
    for tname, t, hs in tracks:
        for h in hs:
            snapped, key = g.snap(h["beat"])
            h["slot"] = key
            h["grid_err"] = (h["beat"] - snapped) * spb
        kept.append((tname, t, [h for h in hs if abs(h["grid_err"]) <= SEARCH]))
    tracks = kept

    by_slot = {}
    feel = {}
    for tname, _, hits in tracks:
        errs = np.array([h["grid_err"] for h in hits])
        lag = float(np.median(errs))                       # this player's usual push/lay-back
        spread = float(np.median(np.abs(errs - lag))) * 1.4826  # robust std of their timing
        feel[tname] = (lag, spread)
        for h in hits:
            by_slot.setdefault(h["slot"], []).append(h)
    # how loose the song is overall: the typical player's spread
    looseness = float(np.median([sp for _, sp in feel.values()])) if feel else 0.0
    notes["looseness"] = looseness
    notes["feel"] = feel

    issues = []
    for slot, group in by_slot.items():
        kind = slot_kind(slot)
        floor_tol, mult, share = SLOTS[kind]
        tol0 = max(floor_tol, mult * looseness)
        for h in group:
            mel = h["track"] in melodic
            tol = tol0 * (MELODIC_TOL if mel else 1.0)
            others = [o for o in group if o["track"] != h["track"]]
            if len(others) >= 2 and not to_grid:
                ref_err = float(np.median([o["grid_err"] for o in others]))
                ref = "band"
            else:
                ref_err, ref = (0.0 if to_grid else feel[h["track"]][0]), "grid"
            off = h["grid_err"] - ref_err
            if abs(off) <= tol:
                continue
            move = -off * share
            if mel:
                move = float(np.clip(-off * min(share, MELODIC_SHARE), -MELODIC_MAX, MELODIC_MAX))
            issues.append(dict(track=h["track"], hit=h, slot=slot, kind=kind, ref=ref,
                               off=off, move=move, beat=h["beat"], optional=mel))
    issues.sort(key=lambda i: i["beat"])
    return tempo, tracks, issues, notes


def messiest_bars(issues, n=10):
    bars = {}
    for i in issues:
        b = int(i["beat"] // BPB) + 1
        bars.setdefault(b, []).append(abs(i["off"]))
    score = sorted(((sum(v), b, len(v)) for b, v in bars.items()), reverse=True)
    return score[:n]


# ---------------------------------------------------------------- warp-marker fixes
def fixable(ci):
    return ci["warped"] and not ci["loop_on"] and len(ci["markers"]) >= 2


def add_marker(ci, sec, beat):
    """Insert (or move) a warp marker keeping SecTime and BeatTime strictly increasing."""
    wm_parent = ci["el"].find("./WarpMarkers")
    ms = [(float(w.get("SecTime")), float(w.get("BeatTime")), w) for w in wm_parent.findall("WarpMarker")]
    for s, b, w in ms:
        if abs(s - sec) < 1e-4:
            w.set("BeatTime", repr(beat))
            break
    else:
        nid = max([int(w.get("Id")) for _, _, w in ms] + [0]) + 1
        new = wm_parent.makeelement("WarpMarker", {"Id": str(nid), "SecTime": repr(sec), "BeatTime": repr(beat)})
        idx = sum(1 for s, _, _ in ms if s < sec)
        wm_parent.insert(idx, new)
    ms = sorted((float(w.get("SecTime")), float(w.get("BeatTime"))) for w in wm_parent.findall("WarpMarker"))
    ok = all(b2 > b1 + 1e-6 and s2 > s1 + 1e-6 for (s1, b1), (s2, b2) in zip(ms, ms[1:]))
    ci["markers"] = [(b, s) for s, b in ms]
    return ok


def apply(issues, tracks, tempo, strength):
    spb = 60.0 / tempo
    done, skipped = [], []
    hits_by_clip = {}
    for _, _, hits in tracks:
        for h in hits:
            hits_by_clip.setdefault(id(h["clip"]), []).append(h)
    for i in issues:
        h, ci = i["hit"], i["hit"]["clip"]
        if not fixable(ci):
            skipped.append((i, "clip is looped or not warped"))
            continue
        neigh = sorted(hits_by_clip[id(ci)], key=lambda x: x["sec"])
        k = neigh.index(h)
        move_b = i["move"] * strength / spb
        prev_s = neigh[k - 1]["sec"] if k > 0 else h["sec"] - 0.25 * spb
        next_s = neigh[k + 1]["sec"] if k + 1 < len(neigh) else h["sec"] + 0.25 * spb
        # anchors must be far enough that the stretch stays gentle (max ~40% speed change)
        if min(h["sec"] - prev_s, next_s - h["sec"]) < 2.5 * abs(move_b) * spb:
            skipped.append((i, "needs a hand: the hits either side are too close to stretch cleanly"))
            continue
        snapshot = [(w.get("SecTime"), w.get("BeatTime")) for w in ci["el"].find("./WarpMarkers")]
        before = list(ci["markers"])
        # Live plays audio past the last marker (and before the first) at the speed of the end segment. A
        # nudge's anchors can become the new first/last marker, and then the rest of the clip would play at
        # the nudge's stretched speed and drift away. Guard markers one beat further out, on the clip's
        # current timing, keep the end segments at their old speed.
        g = spb
        secs_now = [m_s for _, m_s in ci["markers"]]
        guard = []
        if not secs_now or next_s >= max(secs_now) - 1e-6:
            guard.append(next_s + g)
        if not secs_now or prev_s <= min(secs_now) + 1e-6:
            if prev_s - g >= 0:
                guard.append(prev_s - g)
        pts = [prev_s, h["sec"], next_s] + guard
        cur = arr_to_clipbeat(ci, file_to_arr(ci, pts, tempo))
        ok = True
        for gs, gb in zip(guard, cur[3:]):
            ok = ok and add_marker(ci, gs, float(gb))
        ok = ok and add_marker(ci, prev_s, float(cur[0]))
        ok = ok and add_marker(ci, next_s, float(cur[2]))
        ok = ok and add_marker(ci, h["sec"], float(cur[1]) + move_b)
        ok = ok and whole_clip_ok(ci, before, prev_s, next_s, tempo)
        if not ok:
            restore(ci, snapshot)
            skipped.append((i, "would cross an existing warp marker, or would move audio outside the hit"))
            continue
        done.append(i)
    return done, skipped


def whole_clip_ok(ci, before, lo_s, hi_s, tempo, tol_ms=0.5):
    """After a nudge, every moment of the clip outside (lo_s, hi_s) must play exactly when it did before."""
    end = max(s_ for _, s_ in ci["markers"] + before) + 600.0
    grid = np.concatenate([np.arange(0.0, lo_s, 0.005), np.arange(hi_s, end, 0.005)])
    if not len(grid):
        return True
    old = dict(ci); old["markers"] = before
    dev = np.abs(file_to_arr(ci, grid, tempo) - file_to_arr(old, grid, tempo)) * 60.0 / tempo * 1000
    return float(dev.max()) <= tol_ms


def restore(ci, snapshot):
    parent = ci["el"].find("./WarpMarkers")
    for w in list(parent):
        parent.remove(w)
    for n, (s, b) in enumerate(snapshot):
        parent.append(parent.makeelement("WarpMarker", {"Id": str(n), "SecTime": s, "BeatTime": b}))
    ci["markers"] = sorted((float(b), float(s)) for s, b in snapshot)


# ---------------------------------------------------------------- main
def where(beat):
    return f"{int(beat // BPB) + 1}.{beat % BPB + 1:.2f}"


def write_json(path, src, tempo, tracks, issues, notes, a):
    import json
    out = []
    for i in issues:
        tol = max(SLOTS[i["kind"]][0], SLOTS[i["kind"]][1] * notes["looseness"])
        sev = "high" if abs(i["off"]) > 1.5 * tol or i["kind"] == "downbeat" else "medium"
        if i.get("optional"):
            sev = "low"
        ci = i["hit"]["clip"]
        manual = not fixable(ci)
        late = "late" if i["off"] > 0 else "early"
        out.append(dict(id=i["id"], tool="timing", kind=i["kind"], severity=sev, track=i["track"],
                        where=where(i["beat"]),
                        problem=(("OPTIONAL (melodic part: its looseness is part of the feel). " if i.get("optional") else "")
                                 + f"{i['kind']} hit {abs(i['off']) * 1000:.0f} ms {late} against the {i['ref']}"),
                        fix=(f"nudge {i['move'] * a.strength * 1000:+.0f} ms with warp markers"
                             + (" (a gentle partial move, not onto the grid; skip it to keep the feel)" if i.get("optional") else "")
                             if not manual else "clip is looped or not warped: nudge it by hand in Live"),
                        applies="manual" if manual else "set", optional=bool(i.get("optional"))))
    feel = {t: {"lag_ms": round(l * 1000, 1), "spread_ms": round(sp * 1000, 1)} for t, (l, sp) in notes["feel"].items()}
    Path(path).write_text(json.dumps({"tool": "timing", "set": str(src), "tempo": tempo,
                                      "looseness_ms": round(notes["looseness"] * 1000, 1), "feel": feel,
                                      "grid": notes.get("grid", []),
                                      "tracks": [t for t, _, _ in tracks], "melodic": sorted(getattr(a, "melodic", []) or []),
                                      "findings": out}, indent=1))


def main():
    ap = argparse.ArgumentParser(prog="hypnomix timing", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als")
    ap.add_argument("--track", action="append", default=[], help="instrument tracks to compare (repeatable)")
    ap.add_argument("--to-grid", action="store_true", help="compare every hit with the grid, not the band")
    ap.add_argument("--include-off", action="store_true", help="also use switched-off tracks")
    ap.add_argument("--melodic", action="append", default=[], help="a melodic track (guitar, keys, strings; repeatable): "
                    "only clear outliers, offered as optional, moved at most 30%% of the way and 15 ms")
    ap.add_argument("--apply", metavar="OUT.als", help="write warp-marker fixes to this new set")
    ap.add_argument("--strength", type=float, default=1.0, help="scale every move (0-1, default 1)")
    ap.add_argument("--list", type=int, default=40, help="how many problem hits to print (default 40)")
    ap.add_argument("--json", metavar="OUT.json", help="also write the findings as JSON (each with an id)")
    ap.add_argument("--ids", help="with --apply: only nudge these finding ids (comma-separated, from --json)")
    a = ap.parse_args()
    src = Path(a.als)
    if a.apply and Path(a.apply).resolve().parent != src.resolve().parent:
        sys.exit(f"write the new set in the same folder as the original ({src.resolve().parent})")
    tree = aa.load(src)
    root = tree.getroot()
    tempo, tracks, issues, notes = analyse(root, src.parent, a.track, a.to_grid, a.include_off, set(a.melodic))
    spb = 60 / tempo
    for n, i in enumerate(issues, 1):
        i["id"] = f"timing-{n}"
    if a.json:
        write_json(a.json, src, tempo, tracks, issues, notes, a)
    print(f"{src.name}: {tempo:g} BPM, {len(tracks)} tracks, "
          f"{sum(len(h) for _, _, h in tracks)} hits compared\n")
    for tname, _, hits in tracks:
        errs = np.array([abs(h["grid_err"]) * 1000 for h in hits])
        mine = [i for i in issues if i["track"] == tname]
        lag, spread = notes["feel"][tname]
        print(f"  {tname:<28} {len(hits):5d} hits, plays {abs(lag) * 1000:3.0f} ms "
              f"{'behind' if lag > 0 else 'ahead of'} the grid (spread {spread * 1000:.0f} ms), "
              f"{len(mine)} out of place")
    if not issues:
        print("\nEverything is within tolerance.")
        return
    print("\nmessiest bars (total ms out of place, hits):")
    print("  " + ", ".join(f"bar {b} ({s * 1000:.0f} ms, {n})" for s, b, n in messiest_bars(issues)))
    print(f"\n{'bar.beat':>9}  {'track':<24} {'slot':<8} {'vs':<5} {'off':>7}  fix")
    worst = sorted(issues, key=lambda i: -abs(i["off"]))[: a.list]
    for i in sorted(worst, key=lambda i: i["beat"]):
        late = "late" if i["off"] > 0 else "early"
        print(f"{where(i['beat']):>9}  {i['track'][:24]:<24} {i['kind']:<8} {i['ref']:<5} "
              f"{abs(i['off']) * 1000:4.0f} ms {late:<5}  move {i['move'] * a.strength * 1000:+.0f} ms")
    if notes.get("grid"):
        print("grid (from where the hits land): " + "; ".join(f"bars {a}-{b} {nm}" if a != b else f"bar {a} {nm}"
                                                       for a, b, nm in notes["grid"]))
    kinds = {k: sum(1 for i in issues if i["kind"] == k) for k in SLOTS}
    print(f"song looseness {notes['looseness'] * 1000:.0f} ms (typical player's spread); tolerances: "
          + ", ".join(f"{k} {max(v[0], v[1] * notes['looseness']) * 1000:.0f} ms" for k, v in SLOTS.items()))
    print(f"\n{len(issues)} hits out of place: " + ", ".join(f"{v} on {k}s" for k, v in kinds.items()))
    if notes["off"]:
        print("skipped switched-off tracks: " + ", ".join(notes["off"]))
    for m in sorted(notes["missing"]):
        print(f"skipped (audio file not found): {m}")

    if a.apply:
        if a.ids:
            want = {x.strip() for x in a.ids.split(",") if x.strip()}
            issues = [i for i in issues if i["id"] in want]
            if not issues:
                sys.exit("none of those ids were found (same options as the scan?)")
        done, skipped = apply(issues, tracks, tempo, a.strength)
        aa.save(tree, src, a.apply)
        print(f"applied {len(done)} nudges as warp markers; {len(skipped)} left alone:")
        reasons = {}
        for _, why in skipped:
            reasons[why] = reasons.get(why, 0) + 1
        for why, n in reasons.items():
            print(f"  {n} × {why}")
        print("Close the original set in Live before opening the new one.")


if __name__ == "__main__":
    main()
