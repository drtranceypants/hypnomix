#!/usr/bin/env python3
"""Turn audio into MIDI with Spotify's Basic Pitch, estimate the key from the notes,
and optionally drop the notes into a Session View clip in Live.

Works best on one instrument or voice: a sung or hummed idea, or a stem from ears/separate.py.

Usage:
    hypnomix midi idea.wav [--out DIR] [--bpm 64]
            [--onset 0.5] [--frame 0.3] [--min-ms 80] [--fmin 60] [--fmax 2000]
            [--to-live TRACK SLOT]     # write into Live (track name or index, scene slot index)

Writes <out>/<name>.mid and prints note count, range and key.
"""
from hypnomix.core.paths import out_at
from hypnomix.core import args as A
import argparse, sys, warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
from hypnomix.core.paths import out as out_dir
PITCHES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
# Krumhansl-Kessler key profiles
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def key_from_notes(notes):
    hist = np.zeros(12)
    for start, end, pitch, amp, _ in notes:
        hist[int(pitch) % 12] += (end - start) * amp
    if hist.sum() == 0:
        return "?", 0.0
    scores = [(np.corrcoef(hist, np.roll(prof, k))[0, 1], f"{PITCHES[k]} {mode}")
              for prof, mode in ((MAJOR, "major"), (MINOR, "minor")) for k in range(12)]
    scores.sort(reverse=True)
    return scores[0][1], round(float(scores[0][0]), 2)


def to_live(notes, track, slot, bpm):
    from hypnomix.live.osc import Live
    live = Live()
    bpm = bpm or live.tempo()
    tid = live.tid(track)
    beat = lambda s: s * bpm / 60.0
    length = max(4.0, np.ceil(beat(max(e for _, e, *_ in notes)) / 4) * 4)
    if live.query("/live/clip_slot/get/has_clip", tid, slot)[2]:
        raise SystemExit(f"slot {slot} on {live.name(tid)} already has a clip; pick an empty one")
    live.send("/live/clip_slot/create_clip", tid, slot, float(length))
    live.query("/live/clip_slot/get/has_clip", tid, slot)  # wait until it exists
    flat = []
    for s, e, p, amp, _ in notes:
        flat += [int(p), float(beat(s)), float(max(beat(e) - beat(s), 1 / 16)), int(np.clip(amp * 127, 1, 127)), False]
    for i in range(0, len(flat), 5 * 64):  # keep OSC packets small
        live.send("/live/clip/add/notes", tid, slot, *flat[i:i + 5 * 64])
    live.send("/live/clip/set/name", tid, slot, "Basic Pitch")
    print(f"wrote {len(notes)} notes into {live.name(tid)} slot {slot} ({length:.0f} beats at {bpm:g} BPM)", file=sys.stderr)
    live.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--out", default=None)
    ap.add_argument("--bpm", type=A.number(20, 400), help="tempo (20 to 400) written into the .mid and used for Live (default: Live's tempo, else 120)")
    ap.add_argument("--onset", type=float, default=0.5, help="higher = fewer notes start")
    ap.add_argument("--frame", type=float, default=0.3, help="higher = notes end sooner")
    ap.add_argument("--min-ms", type=float, default=80)
    ap.add_argument("--fmin", type=float); ap.add_argument("--fmax", type=float)
    ap.add_argument("--to-live", nargs=2, metavar=("TRACK", "SLOT"))
    a = ap.parse_args()

    try:
        from basic_pitch.inference import predict
        from basic_pitch import ICASSP_2022_MODEL_PATH
    except ImportError:
        from hypnomix.extras import hint
        sys.exit(f"audio to MIDI: {hint('ml')}")
    _, midi, notes = predict(a.audio, ICASSP_2022_MODEL_PATH, onset_threshold=a.onset, frame_threshold=a.frame,
                             minimum_note_length=a.min_ms, minimum_frequency=a.fmin, maximum_frequency=a.fmax,
                             midi_tempo=a.bpm or 120)
    if not notes:
        raise SystemExit("no notes found — try a lower --onset/--frame")
    notes = sorted(notes, key=lambda n: n[0])
    out = out_at(a.out, "midi"); out.mkdir(parents=True, exist_ok=True)
    mid = out / (Path(a.audio).stem + ".mid")
    midi.write(str(mid))
    lo, hi = min(int(n[2]) for n in notes), max(int(n[2]) for n in notes)
    name = lambda p: f"{PITCHES[p % 12]}{p // 12 - 1}"
    key, conf = key_from_notes(notes)
    print(f"{len(notes)} notes, {name(lo)}–{name(hi)}, key {key} (r={conf}) → {mid}")
    if a.to_live:
        to_live(notes, a.to_live[0], int(a.to_live[1]), a.bpm)


if __name__ == "__main__":
    main()
