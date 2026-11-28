#!/usr/bin/env python3
"""Trim a loop so its first downbeat sits exactly at the clip start and nothing of the next bar leaks in.

  hypnomix loopedges FILE.wav --bpm B --downbeat S --bar N --bars 4 [--bpb 4] [--fade-ms 4] [--out CUT.wav]
  hypnomix loopedges FILE.mid --bar N --bars 4 [--bpb 4] [--out CUT.mid]

Audio: the grid bar lines are only a guess. Players hit a little early or late, so around the start line
(+/- 40 ms) it finds the strongest attack, walks back to where the attack begins and starts the clip
there (on a zero crossing, so there is no click). Around the end line it does the same for the NEXT
bar's downbeat and ends the clip just before that attack (1 ms guard), so an early hit is never
stuck on the end of the loop. No attack found: the bar line is kept and `no_transient` is flagged.

The report also gives how much shorter/longer the cut is than the grid bars (`length_off` above 25 ms),
the level jump across the seam, and `tail_rings` if the end rings loudly (try a longer --fade-ms).
A short fade-out ends the cut (no fade-in; the attack stays sharp).

Stems of one loop share the same bounds, taken from the one with the most transient energy at the
start (usually the drums); the others report their own offset in ms. Nothing is changed for them.

MIDI: notes that start within 1/32 beat of the start line move onto it; notes played early just before
the end line are dropped (the loop's own downbeat plays them next pass), or moved to the start if
the start has no note of that pitch; notes that would ring past the end are shortened. Notes in the
middle never move. The cut's notes are relative to the loop start. Channels are not kept.
"""
import argparse, struct, sys
from pathlib import Path

import numpy as np
import soundfile as sf
import librosa

WINDOW_MS = 40.0       # search window around each bar line
WALK_MS = 15.0         # how far back from the peak the attack start can be
HOP = 64               # flux hop in samples (1.45 ms at 44.1 kHz)
NFFT = 256


# ---------- audio ----------

def _mono(y):
    y = np.asarray(y, dtype=np.float64)
    return y.mean(axis=1) if y.ndim > 1 else y


def _env(m, sr):
    """1 ms RMS envelope, one value per sample (centered moving average of the square)."""
    n = max(1, int(round(sr * 0.001)))
    k = np.ones(n) / n
    return np.sqrt(np.maximum(np.convolve(m * m, k, mode="same"), 0.0))


def _zc_before(m, i, sr, max_ms=1.0):
    """Nearest zero crossing at or before sample i, at most max_ms back; else i."""
    i = int(min(max(i, 0), len(m) - 1))
    lo = max(0, i - int(round(sr * max_ms / 1000.0)))
    for k in range(i, lo, -1):
        if m[k] == 0.0 or (m[k - 1] < 0) != (m[k] < 0):
            return k - 1 if m[k] != 0.0 else k
    return i


def _find_attack(m, env, sr, center_s, window_ms=WINDOW_MS):
    """Strongest onset within +/- window of center_s. Returns (attack_start_sample, strength) or (None, 0)."""
    c = int(round(center_s * sr))
    w = int(round(sr * window_ms / 1000.0))
    a, b = max(0, c - w), min(len(m), c + w)
    if b - a < 4 * HOP:
        return None, 0.0
    # spectral flux over a slightly wider span so the window edges are valid
    pad = int(sr * 0.02)
    a2, b2 = max(0, a - pad), min(len(m), b + pad)
    S = np.abs(librosa.stft(m[a2:b2], n_fft=NFFT, hop_length=HOP, center=True))
    flux = np.maximum(0.0, np.diff(S, axis=1, prepend=S[:, :1])).sum(axis=0)
    centers = a2 + np.arange(len(flux)) * HOP
    ok = (centers >= a) & (centers <= b)
    if not ok.any() or flux[ok].max() <= 0:
        return None, 0.0
    fi = np.where(ok)[0][int(np.argmax(flux[ok]))]
    fpos = int(centers[fi])
    # onset peak: loudest 1 ms envelope up to WALK_MS after the flux frame (and a frame before)
    p0 = max(0, fpos - 2 * HOP)
    p1 = min(len(m), fpos + int(sr * WALK_MS / 1000.0))
    pk = p0 + int(np.argmax(env[p0:p1]))
    walk = int(sr * WALK_MS / 1000.0)
    w0 = max(0, pk - walk)
    floor = float(env[w0:pk + 1].min())
    peak = float(env[pk])
    if peak < 1e-3 or peak < 3.0 * max(floor, 1e-6):
        return None, 0.0                       # no real rise: pad, sustained noise, silence
    thr = floor + 0.10 * (peak - floor)
    k = pk
    while k > w0 and env[k - 1] >= thr:
        k -= 1
    return k, float(flux[fi])


def _db(x):
    return 20.0 * np.log10(max(float(x), 1e-9))


def _rms(x):
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def align_audio(y, sr, start_s, end_s, fade_ms=4.0, guard_ms=1.0, window_ms=WINDOW_MS):
    """Find where a loop should really start and end. Pure; y is the source file (mono or channels)."""
    m = _mono(y)
    env = _env(m, sr)
    flags = []
    s_att, s_str = _find_attack(m, env, sr, start_s, window_ms)
    if s_att is None:
        flags.append("no_transient")
        s_idx = int(round(start_s * sr))
        s_att_ms = None
    else:
        s_idx = s_att
        s_att_ms = (s_att / sr - start_s) * 1000.0
    s_idx = _zc_before(m, s_idx, sr)
    e_att, _ = _find_attack(m, env, sr, end_s, window_ms)
    if e_att is None:
        flags.append("no_transient_end")
        e_idx = int(round(end_s * sr))
        e_att_ms = None
    else:
        e_idx = e_att - int(round(sr * guard_ms / 1000.0))
        e_att_ms = (e_att / sr - end_s) * 1000.0
    e_idx = _zc_before(m, e_idx, sr)
    new_start, new_end = s_idx / sr, e_idx / sr
    grid = end_s - start_s
    played = new_end - new_start
    diff_ms = (played - grid) * 1000.0
    if abs(diff_ms) > 25.0:
        flags.append("length_off")
    seg = m[s_idx:e_idx]
    n20, n50 = int(sr * 0.02), int(sr * 0.05)
    jump = None
    rings = False
    if len(seg) > 2 * n20:
        jump = _db(_rms(seg[-n20:])) - _db(_rms(seg[:n20]))
    if len(seg) > 4 * n50:
        # tail energy against the quietest typical stretch of the loop (10th percentile of 50 ms windows)
        wins = [_rms(seg[i:i + n50]) for i in range(0, len(seg) - n50, n50)]
        rings = _db(_rms(seg[-n50:])) - _db(np.percentile(wins, 10)) > 12.0
    if rings:
        flags.append("tail_rings")
    return {"new_start": new_start, "new_end": new_end, "start_sample": s_idx, "end_sample": e_idx,
            "start_shift_ms": (new_start - start_s) * 1000.0, "end_shift_ms": (new_end - end_s) * 1000.0,
            "start_attack_offset_ms": s_att_ms, "end_attack_offset_ms": e_att_ms,
            "grid_len_s": grid, "played_len_s": played, "length_diff_ms": diff_ms,
            "seam_jump_db": jump, "tail_rings": rings, "fade_ms": fade_ms, "flags": flags}


def align_group(stems, start_s, end_s, ref=None, each=False, fade_ms=4.0, guard_ms=1.0):
    """Shared bounds for stems of one loop. stems = {name: (y, sr)}. ref = name, else the stem with the
    most transient energy in the start window. each=True aligns every stem to its own onset instead."""
    if not stems:
        raise ValueError("no stems")
    strengths, att = {}, {}
    for name, (y, sr) in stems.items():
        m = _mono(y)
        a, st = _find_attack(m, _env(m, sr), sr, start_s)
        strengths[name] = st
        att[name] = None if a is None else a / sr
    if ref is None:
        ref = max(strengths, key=lambda k: strengths[k])
    if ref not in stems:
        raise ValueError(f"unknown reference stem {ref!r}")
    ry, rsr = stems[ref]
    base = align_audio(ry, rsr, start_s, end_s, fade_ms, guard_ms)
    out = {}
    for name, (y, sr) in stems.items():
        off = None if att[name] is None or att[ref] is None else (att[name] - att[ref]) * 1000.0
        r = align_audio(y, sr, start_s, end_s, fade_ms, guard_ms) if each else \
            {"new_start": base["new_start"], "new_end": base["new_end"], "flags": []}
        if att[name] is None and "no_transient" not in r["flags"]:
            r = dict(r, flags=r["flags"] + ["no_transient"])
        out[name] = {"offset_ms": off, "new_start": r["new_start"], "new_end": r["new_end"], "flags": r["flags"]}
    return {"ref": ref, "each": each, "new_start": base["new_start"], "new_end": base["new_end"],
            "reference": base, "stems": out}


def cut_audio(y, sr, new_start, new_end, fade_ms=4.0):
    """The cut itself: samples new_start..new_end with a fade-out ending at new_end (no fade-in)."""
    a, b = int(round(new_start * sr)), int(round(new_end * sr))
    seg = np.array(y[a:b], dtype=np.float32, copy=True)
    n = min(len(seg), int(round(sr * fade_ms / 1000.0)))
    if n > 1:
        ramp = np.linspace(1.0, 0.0, n, dtype=np.float32)
        seg[-n:] *= ramp[:, None] if seg.ndim > 1 else ramp
    return seg


# ---------- MIDI ----------

def align_midi(notes, start_beat, end_beat, window_beats=1 / 32, end_guard_beats=1 / 128):
    """notes = (pitch, start, dur, vel) in beats. Returns the loop's notes relative to start_beat + counts."""
    eps = 1e-9
    w = window_beats
    kept = []
    nudged = removed = wrapped = shortened = 0
    for p, s, d, v in notes:
        if s < start_beat - w - eps or s >= end_beat - eps:
            continue                                   # not in this loop
        end = s + d
        if abs(s - start_beat) <= w + eps or s < start_beat:
            if abs(s - start_beat) > eps:
                nudged += 1
            kept.append([p, start_beat, end - start_beat, v, "start"])
        elif s >= end_beat - w - eps:
            kept.append([p, s, d, v, "late"])
        else:
            kept.append([p, s, d, v, "mid"])
    have = {k[0] for k in kept if k[4] == "start"}
    out = []
    for p, s, d, v, kind in kept:
        if kind == "late":
            if p in have:
                removed += 1
                continue
            wrapped += 1
            have.add(p)
            s = start_beat
        out.append([p, s, max(d, 0.0), v])
    for n in out:
        if n[1] + n[2] > end_beat + eps:
            n[2] = max(end_beat - end_guard_beats - n[1], 0.0)
            shortened += 1
    out.sort(key=lambda n: (n[1], n[0]))
    res = [(p, s - start_beat, d, v) for p, s, d, v in out]
    return {"notes": res, "nudged": nudged, "removed": removed, "wrapped": wrapped, "shortened": shortened,
            "length_beats": end_beat - start_beat}


def _vlq(data, i):
    v = 0
    while True:
        b = data[i]; i += 1
        v = (v << 7) | (b & 0x7F)
        if not b & 0x80:
            return v, i


def read_midi(path):
    """Minimal .mid reader: returns (notes in beats as (pitch, start, dur, vel), ppq, first tempo us/beat)."""
    data = Path(path).read_bytes()
    if data[:4] != b"MThd":
        raise ValueError("not a MIDI file")
    ppq = struct.unpack(">H", data[12:14])[0]
    if ppq & 0x8000:
        raise ValueError("SMPTE time division is not supported")
    i = 8 + struct.unpack(">I", data[4:8])[0]
    notes, tempo = [], None
    while i + 8 <= len(data):
        if data[i:i + 4] != b"MTrk":
            break
        ln = struct.unpack(">I", data[i + 4:i + 8])[0]
        j, end, t, run = i + 8, i + 8 + ln, 0, 0
        on = {}
        while j < end:
            dt, j = _vlq(data, j)
            t += dt
            st = data[j]
            if st == 0xFF:
                typ = data[j + 1]
                l, j2 = _vlq(data, j + 2)
                if typ == 0x51 and tempo is None and l == 3:
                    tempo = int.from_bytes(data[j2:j2 + 3], "big")
                j = j2 + l
                continue
            if st in (0xF0, 0xF7):
                l, j = _vlq(data, j + 1)
                j += l
                continue
            if st & 0x80:
                run = st; j += 1
            st = run
            kind = st & 0xF0
            n = 1 if kind in (0xC0, 0xD0) else 2
            a = data[j]; b = data[j + 1] if n == 2 else 0
            j += n
            key = (st & 0x0F, a)
            if kind == 0x90 and b > 0:
                on.setdefault(key, []).append((t, b))
            elif kind == 0x80 or (kind == 0x90 and b == 0):
                if on.get(key):
                    t0, vel = on[key].pop(0)
                    notes.append((a, t0 / ppq, (t - t0) / ppq, vel))
        i = end
    notes.sort(key=lambda n: (n[1], n[0]))
    return notes, ppq, tempo or 500000


def _put_vlq(v):
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    return bytes(reversed(out))


def write_midi(path, notes, ppq=480, tempo=500000):
    ev = []
    for p, s, d, v in notes:
        a = int(round(s * ppq)); b = max(a + 1, int(round((s + d) * ppq)))
        ev.append((a, 1, bytes([0x90, p, v]))); ev.append((b, 0, bytes([0x80, p, 0])))
    ev.sort(key=lambda e: (e[0], e[1]))
    body = b"\x00\xff\x51\x03" + tempo.to_bytes(3, "big")
    last = 0
    for t, _, msg in ev:
        body += _put_vlq(t - last) + msg
        last = t
    body += b"\x00\xff\x2f\x00"
    Path(path).write_bytes(b"MThd" + struct.pack(">IHHH", 6, 0, 1, ppq) + b"MTrk" + struct.pack(">I", len(body)) + body)


# ---------- CLI ----------

def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix loopedges", description="Trim a loop's start and end onto its real attacks.")
    ap.add_argument("file", help="a .wav/.flac/.aif loop source, or a .mid file")
    ap.add_argument("--bpm", type=float, help="tempo (audio)")
    ap.add_argument("--downbeat", type=float, default=0.0, help="seconds where bar 1 starts (audio; default 0)")
    ap.add_argument("--bar", type=int, default=1, help="first bar of the loop, counting from 1")
    ap.add_argument("--bars", type=int, default=4, help="length in bars")
    ap.add_argument("--bpb", type=int, default=4, help="beats per bar")
    ap.add_argument("--fade-ms", type=float, default=4.0)
    ap.add_argument("--out", help="write the cut here")
    a = ap.parse_args(argv)
    f = Path(a.file)
    if f.suffix.lower() in (".mid", ".midi"):
        notes, ppq, tempo = read_midi(f)
        sb = (a.bar - 1) * a.bpb
        r = align_midi(notes, sb, sb + a.bars * a.bpb)
        print(f"{f.name}: bars {a.bar}-{a.bar + a.bars - 1}: {len(r['notes'])} notes; nudged {r['nudged']}, "
              f"removed {r['removed']}, wrapped {r['wrapped']}, shortened {r['shortened']}")
        if a.out:
            write_midi(a.out, r["notes"], ppq, tempo)
            print("wrote", a.out)
        return 0
    if not a.bpm:
        ap.error("--bpm is required for audio")
    y, sr = sf.read(str(f), always_2d=True)
    bar_s = a.bpb * 60.0 / a.bpm
    start_s = a.downbeat + (a.bar - 1) * bar_s
    end_s = start_s + a.bars * bar_s
    r = align_audio(y, sr, start_s, end_s, a.fade_ms)
    print(f"{f.name}: bars {a.bar}-{a.bar + a.bars - 1}  grid {start_s:.4f}-{end_s:.4f} s")
    print(f"  start {r['new_start']:.4f} s ({r['start_shift_ms']:+.1f} ms)   end {r['new_end']:.4f} s ({r['end_shift_ms']:+.1f} ms)")
    print(f"  length {r['played_len_s']:.4f} s vs grid {r['grid_len_s']:.4f} s ({r['length_diff_ms']:+.1f} ms)")
    if r["seam_jump_db"] is not None:
        print(f"  seam level jump {r['seam_jump_db']:+.1f} dB")
    for fl in r["flags"]:
        print("  flag:", fl + ("  (try a longer --fade-ms)" if fl == "tail_rings" else ""))
    if a.out:
        sf.write(a.out, cut_audio(y, sr, r["new_start"], r["new_end"], a.fade_ms), sr)
        print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
