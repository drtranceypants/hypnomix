#!/usr/bin/env python3
"""Pull a take's hits part of the way toward the click, in place, keeping the player's feel.

  hypnomix tighten SET.als --track "Drums" [--strength 0.5] [--preview DIR]
  hypnomix tighten SET.als --track "Drums" --apply "SET (tighter).als"

`hypnomix timing` fixes only the hits that are clearly wrong against the band. This one treats the
whole take, like a gentle quantise: every hit that is further than --keep-within from its grid slot
moves --strength of the way there (default half way), never more than --max-ms. Hits already close
stay exactly where they are, so the take gets tighter without turning into a machine.

  --strength 0.5      share of each hit's error to remove (0.1 to 0.9; never all of it)
  --grid 16           the finest slot hits are compared with: 4, 8 or 16 (use 8 for a straight rock beat)
  --keep-within 8     ms: hits this close to their slot are left alone
  --max-ms 45         ms: no hit moves further than this
  --keep-lag          keep the player's usual push or lay-back: tighten around it, not onto the click

How: a warp marker goes on every hit (moved or not), so only the audio between two hits stretches, and
by a few percent at most. A hit whose move would squeeze the audio next to it too hard is left alone.
Clips that are not warped yet are switched to warp first (they play the same; needed for markers).
Looped clips are skipped. Everything stays editable in Live: drag or delete any marker.

--preview writes the track before and after as two WAVs (rendered without Live, clip audio only).
--apply writes a NEW set and runs `hypnomix check` on it. Close the set in Live first.
Assumes a constant tempo and 4/4.
"""
import argparse, sys
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix.session import beats as B

MAX_STRETCH = 0.30     # audio between two hits is never sped up or slowed by more than this


def plan_clip(ci, tempo, a):
    """Decide the new position of every hit in one clip. Returns (hits, lag_ms)."""
    from hypnomix.session import timing as tm
    spb = 60.0 / tempo
    hits = tm.clip_onsets(ci, tempo)
    if not hits:
        return [], 0.0
    floor = np.percentile([h["strength"] for h in hits], tm.GHOST_PCT)
    hits = [h for h in sorted(hits, key=lambda h: h["sec"]) if h["strength"] >= floor]
    clean = []
    for h in hits:                                     # a flam or drag stays as played
        if clean and h["sec"] - clean[-1]["sec"] < 0.040:
            continue
        clean.append(h)
    step = 4.0 / a.grid                                # beats per slot
    for h in clean:
        slot = round(h["beat"] / step) * step
        h["err"] = (h["beat"] - slot) * spb            # seconds late (+) or early (-)
        h["near"] = abs(h["err"]) <= 0.35 * step * spb
    near = [h["err"] for h in clean if h["near"]]
    lag = float(np.median(near)) if near and a.keep_lag else 0.0
    for h in clean:
        off = h["err"] - lag
        h["move"] = 0.0
        if h["near"] and abs(off) * 1000 > a.keep_within:
            h["move"] = float(np.clip(-off * a.strength, -a.max_ms / 1000, a.max_ms / 1000))
    # never squeeze the audio between two hits too hard: back a move off until both sides are gentle
    for _ in range(3):
        for k, h in enumerate(clean):
            if not h["move"]:
                continue
            for o in ([clean[k - 1]] if k else []) + ([clean[k + 1]] if k + 1 < len(clean) else []):
                gap = abs(o["sec"] - h["sec"])
                rel = abs(h["move"] - o["move"]) / max(gap, 1e-6)
                if rel > MAX_STRETCH:
                    h["move"] *= MAX_STRETCH / rel * 0.98
    return clean, float(np.median(near)) * 1000 if near else 0.0


def apply_clip(ci, hits, tempo):
    """Write the markers: one on every hit, holding or moving it; guards keep the rest of the clip as it was."""
    from hypnomix.session import timing as tm
    spb = 60.0 / tempo
    secs = np.array([h["sec"] for h in hits])
    lo, hi = secs[0] - spb, secs[-1] + spb
    pts = np.concatenate([[max(0.0, lo)], secs, [hi]])
    old_b = tm.arr_to_clipbeat(ci, tm.file_to_arr(ci, pts, tempo))
    new_b = old_b.copy()
    new_b[1:-1] += np.array([h["move"] for h in hits]) / spb
    keep = [(s, b) for b, s in ci["markers"] if s < pts[0] - 1e-4 or s > pts[-1] + 1e-4]
    pairs = sorted(keep + list(zip(pts.tolist(), new_b.tolist())))
    ok = all(s2 > s1 + 1e-5 and b2 > b1 + 1e-6 for (s1, b1), (s2, b2) in zip(pairs, pairs[1:]))
    if not ok:
        return False
    B.set_markers(ci["el"], pairs)
    ci["markers"] = [(b, s) for s, b in pairs]
    return True


def main():
    ap = argparse.ArgumentParser(prog="hypnomix tighten", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als"); ap.add_argument("--track", required=True)
    ap.add_argument("--strength", type=float, default=0.5); ap.add_argument("--grid", type=int, choices=(4, 8, 16), default=16)
    ap.add_argument("--keep-within", type=float, default=8.0); ap.add_argument("--max-ms", type=float, default=45.0)
    ap.add_argument("--keep-lag", action="store_true")
    ap.add_argument("--preview", metavar="DIR"); ap.add_argument("--apply", metavar="NEW.als")
    from hypnomix.session import liveversion as LV; LV.add_force_flag(ap)
    a = ap.parse_args()
    if not 0.1 <= a.strength <= 0.9:
        sys.exit("--strength must be between 0.1 and 0.9: a full snap to the grid takes the life out of a take")
    from hypnomix.session import automation as aa, smooth as sm
    src = Path(a.als)
    tree = aa.load(src); root = tree.getroot()
    if B.tempo_points(root):
        sys.exit("this set has tempo automation: tighten needs a constant tempo")
    tempo = B.set_tempo(root)
    t = aa.find_track(root, a.track)
    clips = B.clips_of(t)
    if not clips:
        sys.exit(f"no audio clips in the Arrangement on {a.track!r}")
    drums = any(w in a.track.lower() for w in ("drum", "kick", "snare", "hat", "perc", "kit"))
    before_y = None
    if a.preview:
        before_y = render(t, src, tempo)
    tot = dict(hits=0, moved=0, kept=0, skipped=0, warped=0)
    b_err, a_err, moves = [], [], []
    for c in clips:
        ci = sm.clip_info(c, src.parent, tempo)
        if ci["disabled"] or not ci["path"].exists():
            continue
        if ci["loop_on"]:
            tot["skipped"] += 1
            continue
        if B.straight_warp(c, tempo, drums=drums):
            tot["warped"] += 1
            ci = sm.clip_info(c, src.parent, tempo)
        if len(ci["markers"]) < 2:
            tot["skipped"] += 1
            continue
        hits, _ = plan_clip(ci, tempo, a)
        if len(hits) < 2:
            continue
        if not apply_clip(ci, hits, tempo):
            tot["skipped"] += 1
            continue
        tot["hits"] += len(hits)
        for h in hits:
            if h["near"]:
                b_err.append(abs(h["err"]) * 1000)
                a_err.append(abs(h["err"] + h["move"]) * 1000)
            if h["move"]:
                tot["moved"] += 1
                moves.append(abs(h["move"]) * 1000)
            else:
                tot["kept"] += 1
    if not tot["hits"]:
        sys.exit("no hits found to tighten (looped clips are skipped)")
    print(f"{src.name} / {a.track}: {tot['hits']} hits at {tempo:g} BPM, compared with the {a.grid}th-note grid")
    print(f"  distance from the grid: median {np.median(b_err):.0f} ms → {np.median(a_err):.0f} ms; "
          f"worst tenth {np.percentile(b_err, 90):.0f} ms → {np.percentile(a_err, 90):.0f} ms")
    print(f"  {tot['moved']} hits moved {a.strength * 100:.0f}% of the way (median {np.median(moves) if moves else 0:.0f} ms, "
          f"largest {max(moves) if moves else 0:.0f} ms); {tot['kept']} left exactly as played")
    if tot["warped"]:
        print(f"  {tot['warped']} clips had warp switched on (they play the same; "
              f"{'Beats' if drums else 'Complex Pro'} mode)")
    if tot["skipped"]:
        print(f"  {tot['skipped']} clips skipped (looped, or their markers could not be kept in order)")
    if a.preview:
        od = Path(a.preview); od.mkdir(parents=True, exist_ok=True)
        after_y = render(t, src, tempo)
        n = max(len(before_y), len(after_y))
        for name, yy in (("A (as played)", before_y), ("B (tighter)", after_y)):
            yy = np.pad(yy, ((0, n - len(yy)), (0, 0)))
            click = B.click_track(n, 44100, np.arange(0, n / 44100, 60.0 / tempo), 0, 4, level=0.2)
            sf.write(str(od / f"{a.track} {name}.wav"), yy, 44100, subtype="PCM_24")
            sf.write(str(od / f"{a.track} {name} + click.wav"), yy + click[:, None], 44100, subtype="PCM_24")
        print(f"  preview (with and without a click) → {od}")
    if not a.apply:
        print("\nnothing written: add --apply \"NEW.als\".")
        return
    B.finish(tree, src, a.apply)


def render(track, als, tempo, sr=44100):
    """The track's clips as audio, following every warp marker (clip gain applied; no fades, no devices)."""
    from hypnomix.session import smooth as sm, timing as tm
    spb = 60.0 / tempo
    clips = [sm.clip_info(c, Path(als).parent, tempo) for c in B.clips_of(track)]
    clips = [c for c in clips if not c["disabled"] and c["path"].exists() and not c["loop_on"]]
    if not clips:
        return np.zeros((1, 2), dtype=np.float32)
    N = int((max(c["end"] for c in clips) + 4) * spb * sr)
    out = np.zeros((N, 2), dtype=np.float32)
    for ci in clips:
        y, fsr = B.load(ci["path"])
        if fsr != sr:
            import librosa
            y = np.stack([librosa.resample(y[:, ch], orig_sr=fsr, target_sr=sr) for ch in range(y.shape[1])], 1)
        y = y[:, :2] if y.shape[1] >= 2 else np.repeat(y, 2, 1)
        grid = np.arange(ci["start"], ci["end"] + 1e-9, 0.25)                 # every 16th of the clip
        fs = sm.file_seconds(ci, grid, tempo)
        extra = [(s, float(tm.file_to_arr(ci, [s], tempo)[0])) for _, s in ci["markers"]]
        pairs = sorted(set([(float(s), float(b) * spb) for s, b in zip(fs, grid)]
                           + [(float(s), b * spb) for s, b in extra if ci["start"] <= b <= ci["end"]]))
        w = B.warp_render(y, sr, pairs)
        i0, i1 = int(ci["start"] * spb * sr), min(N, int(ci["end"] * spb * sr))
        seg = w[i0:i1] * ci["gain"]
        out[i0:i0 + len(seg)] += seg
    return out


if __name__ == "__main__":
    main()
