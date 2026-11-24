#!/usr/bin/env python3
"""Master a stereo mix for release: clean the sub, glue, (optionally) match a reference's tone,
keep the low end mono, and limit to a loudness target on true peaks. Every move is logged with why.

Usage:
    hypnomix master mix.wav [--target -14] [--ceiling -1] [--reference ref.wav [--match 0.6]]
                   [--glue 1.5] [--warmth 0] [--width 1.0] [--cd] [--out DIR]

Targets: -14 LUFS suits Spotify/YouTube/Tidal (they turn louder songs down anyway); -9 to -11 for
loud genres if you know why you want it; -16 for Apple Music-first or very dynamic music.
Writes <name> (master).wav (24-bit), optional 16-bit/44.1 kHz CD version, and a MASTER notes .md.
"""
from hypnomix.core.paths import out_at
import argparse, json, sys
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.core.paths import out as out_dir


def loudness_to_target(y, sr, target, ceiling, iters=5):
    """Find the input gain so that after the limiter the song measures `target` LUFS."""
    g = target - dsp.lufs(y, sr)
    best = None
    for _ in range(iters):
        out, gr = dsp.limit(y * dsp.undb(g), sr, ceiling)
        L = dsp.lufs(out, sr)
        best = (out, gr, g, L)
        if abs(L - target) < 0.1:
            break
        g += (target - L) * (1.15 if L < target else 1.0)       # limiter eats some of each dB we add
    return best


def codec_worst(y, sr):
    """Highest true peak after AAC 256 and MP3 320 round trips (None if ffmpeg can't encode)."""
    import tempfile
    from hypnomix.engineer.translate import codec_peak
    with tempfile.TemporaryDirectory() as td:
        p = dsp.save(Path(td) / "m.wav", y, sr, 24)
        peaks = [codec_peak(p, c) for c in ("aac", "mp3")]
    peaks = [x for x in peaks if x is not None]
    return max(peaks) if peaks else None


def top_and_tail(y, sr, log):
    """Silence before the first note trimmed to 50 ms, a 3 ms fade-in, and a fade-out if the song ends abruptly."""
    env = np.max(np.abs(y), axis=1)
    on = np.flatnonzero(env > dsp.undb(-60))
    if not len(on):
        return y
    a = max(0, on[0] - int(0.05 * sr))
    y = y[a:].copy()
    fi = int(0.003 * sr)
    y[:fi] *= np.linspace(0, 1, fi)[:, None]
    note = f"trimmed {a / sr:.2f} s of silence, 3 ms fade-in"
    env = np.max(np.abs(y), axis=1)
    last = np.flatnonzero(env > dsp.undb(-60))
    if len(last) and len(y) - last[-1] > int(1.0 * sr):
        cut = last[-1] + int(1.0 * sr)
        note += f", trimmed {(len(y) - cut) / sr:.1f} s of trailing silence"
        y = y[:cut].copy()
        fo = int(0.5 * sr)
        y[-fo:] *= np.linspace(1, 0, fo)[:, None]
    tail = dsp.db(np.max(np.abs(y[-int(0.05 * sr):])))
    if tail > -45:
        fo = int(min(1.5, len(y) / sr / 10) * sr)
        y[-fo:] *= (np.linspace(1, 0, fo) ** 2)[:, None]
        note += f", {fo / sr:.1f} s fade-out (the file ended while music was still playing)"
    log.append(("Top and tail", note, "No clicks at the start or end, and no dead air before the song begins in a playlist."))
    return y


KEYS = {"Subsonic clean-up": "hpf", "Reference tone match": "match", "Glue compression": "glue",
        "Mono low end": "monolow", "Stereo width": "width", "Warmth": "warmth", "Limiter": "limiter",
        "Codec-safe ceiling": "limiter", "Top and tail": "toptail"}


def master(y, sr, target=-14.0, ceiling=-1.0, reference=None, match=0.6, glue_gr=1.5, warmth=0.0, width=1.0, log=None,
           only=None):
    """only: a set of stage keys (hpf, match, glue, monolow, width, warmth, limiter, toptail) to run and nothing
    else: the approved moves of a plan. None = the whole chain."""
    log = log if log is not None else []
    on = lambda k: only is None or k in only
    if not on("match"):
        reference = None
    if not on("glue"):
        glue_gr = 0
    if not on("warmth"):
        warmth = 0.0
    if not on("width"):
        width = 1.0
    st = dict(hpf_hz=22)                                     # the settings, as numbers (used by `hypnomix chain`)
    y = dsp.stereo(y)
    before = dict(lufs=dsp.lufs(y, sr), tp=dsp.true_peak(y, sr), corr_low=dsp.correlation(y, sr, 150))

    if on("hpf"):
        y = dsp.filt(y, dsp.highpass(22, sr, 2))
        log.append(("Subsonic clean-up", "high-pass 22 Hz, 12 dB/oct",
                    "Energy below ~25 Hz is felt by no speaker but still eats limiter headroom."))

    if reference is not None:
        r, _ = dsp.load(reference, sr)
        h, (f, curve) = dsp.matching_fir(y, dsp.stereo(r), sr, max_db=3.0)
        st["eq_curve"] = (f, curve * match)
        if match < 1:
            from scipy.signal import firwin2
            pts = np.unique(np.concatenate([[0], np.geomspace(20, sr / 2 * 0.999, 200), [sr / 2]]))
            h = firwin2(4097, pts, dsp.undb(np.interp(pts, f, curve * match)), fs=sr)
        y = dsp.apply_fir(y, h)
        bands = [(60, "low"), (250, "low-mid"), (1000, "mid"), (3000, "presence"), (10000, "air")]
        moves = ", ".join(f"{n} {np.interp(hz, f, curve) * match:+.1f} dB" for hz, n in bands)
        log.append(("Reference tone match", f"linear-phase EQ toward {Path(reference).name} at {int(match * 100)}%: {moves}",
                    "Matching the tonal tilt of a record you love is the fastest way to a mix that sits next to it in a "
                    "playlist. Capped at ±3 dB and applied partially so your mix keeps its character."))

    if glue_gr > 0:
        th = dsp.threshold_for_gr(y, sr, glue_gr, 1.5, 30, 150, 6, detector="rms")
        y, g = dsp.compress(y, sr, th, 1.5, 30, 150, 6, detector="rms")
        st["glue"] = dict(threshold_db=th, ratio=1.5, attack_ms=30, release_ms=150, target_gr_db=glue_gr)
        y *= dsp.undb(min(glue_gr, -np.mean(g)) * 0.7)
        log.append(("Glue compression", f"1.5:1, attack 30 ms, release 150 ms, threshold {th:.1f} dB, "
                                         f"avg {-np.mean(g):.1f} dB / max {-g.min():.1f} dB reduction",
                    "A slow attack lets the drum transients through while the body of the mix moves together. "
                    "1–2 dB is glue; more is an effect."))

    cl = dsp.correlation(y, sr, 150)
    if cl < 0.97 and on("monolow"):
        y = dsp.mono_below(y, sr, 120)
        st["bass_mono_hz"] = 120
        log.append(("Mono low end", f"everything below 120 Hz summed to mono (low-end L/R correlation was {cl:.2f})",
                    "Stereo bass wanders, cancels on mono speakers and makes the limiter work harder."))

    if width != 1.0:
        y = dsp.width(y, width)
        st["width"] = width
        log.append(("Stereo width", f"side level ×{width:.2f}", "Wider sides feel bigger but fold down worse on phones."))

    if warmth > 0:
        y = dsp.saturate(y, warmth * 4, mix=0.35)
        st["saturation"] = dict(drive_db=warmth * 4, mix=0.35)
        log.append(("Warmth", f"tanh saturation, drive {warmth * 4:.1f} dB at 35% mix",
                    "Gentle harmonics make bass audible on small speakers and round off harsh peaks before the limiter."))

    if not on("limiter"):                      # approved moves only, loudness left where the mix was
        out = top_and_tail(y, sr, log) if on("toptail") else y
        after = dict(lufs=dsp.lufs(out, sr), tp=dsp.true_peak(out, sr), corr_low=dsp.correlation(out, sr, 150),
                     avg_gr=0.0, max_gr=0.0, pct_limiting=0.0, settings=st)
        return out, before, after, log
    out, gr, g, L = loudness_to_target(y, sr, target, ceiling)
    # codec-safe: encode test copies; if AAC/MP3 decoding overshoots, lower the ceiling and limit again
    used_ceiling, first_worst, worst = ceiling, None, None
    for _ in range(3):
        worst = codec_worst(out, sr)
        first_worst = worst if first_worst is None else first_worst
        if worst is None or worst <= -0.3:
            break
        used_ceiling = round(used_ceiling - (worst + 0.5), 1)
        out, gr, g, L = loudness_to_target(y, sr, target, used_ceiling)
    act = gr < -0.1
    avg_gr = float(-np.mean(gr[act])) if act.any() else 0.0      # how hard it works when it works
    pct = float(np.mean(act) * 100)
    log.append(("Limiter", f"input +{g:.1f} dB, true-peak ceiling {used_ceiling} dBTP, look-ahead 5 ms, release 80 ms; "
                           f"limiting {pct:.0f}% of the time, avg {avg_gr:.1f} dB when it does, max {-gr.min():.1f} dB",
                "The limiter sets the final loudness. Watch the average reduction: under ~2 dB is transparent, 3–6 dB "
                "starts to flatten drums, above that the mix needs to be louder before mastering."))
    if used_ceiling != ceiling:
        log.append(("Codec-safe ceiling", f"AAC/MP3 test encodes peaked at {first_worst:+.2f} dBTP with a {ceiling} dBTP "
                                          f"ceiling, so the limiter ran again at {used_ceiling} dBTP"
                                          + (f" (now {worst:+.2f} dBTP after encoding)" if worst is not None else ""),
                    "Lossy encoders (Spotify, Apple Music, YouTube) rebuild the waveform and overshoot the original "
                    "peaks; a dense master can clip after encoding even when the WAV doesn't."))
    if on("toptail"):
        out = top_and_tail(out, sr, log)
    tp = dsp.true_peak(out, sr)
    after = dict(lufs=L, tp=tp, corr_low=dsp.correlation(out, sr, 150), avg_gr=avg_gr, max_gr=float(-gr.min()), pct_limiting=pct)
    st["limiter"] = dict(gain_db=g, ceiling_dbtp=used_ceiling, release_ms=80)
    after["settings"] = st
    return out, before, after, log


def notes(name, before, after, log, target, files):
    warn = []
    if after["avg_gr"] > 4:
        warn.append(f"The limiter is working hard ({after['avg_gr']:.1f} dB on loud parts). Try --target {target + 2:g}, "
                    "or tame the loudest elements in the mix (kick, snare, bass) first.")
    if after["tp"] > -0.95:
        warn.append(f"True peak {after['tp']:.2f} dBTP is above -1. Lossy encoding may clip; lower --ceiling.")
    md = [f"# Master notes: {name}", "",
          "| | mix | master |", "|---|---|---|",
          f"| Integrated loudness | {before['lufs']:.1f} LUFS | {after['lufs']:.1f} LUFS |",
          f"| True peak | {before['tp']:.1f} dBTP | {after['tp']:.1f} dBTP |",
          f"| Low-end L/R correlation (<150 Hz) | {before['corr_low']:.2f} | {after['corr_low']:.2f} |", "",
          "## Chain, in order", ""]
    for i, (what, setting, why) in enumerate(log, 1):
        md += [f"{i}. **{what}**: {setting}  ", f"   *Why:* {why}"]
    if warn:
        md += ["", "## Warnings", *[f"- {w}" for w in warn]]
    md += ["", "## Files", *[f"- `{f}`" for f in files], "",
           "Next: `hypnomix translate` (phones, mono, streaming) and `hypnomix qc` before you upload."]
    return "\n".join(md) + "\n"


def main():
    ap = argparse.ArgumentParser(prog="hypnomix master", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mix")
    ap.add_argument("--target", type=float, default=-14.0)
    ap.add_argument("--ceiling", type=float, default=-1.0)
    ap.add_argument("--reference")
    ap.add_argument("--match", type=float, default=0.6, help="how far to move toward the reference tone (0–1)")
    ap.add_argument("--glue", type=float, default=1.5, help="target glue-compression dB (0 = off)")
    ap.add_argument("--warmth", type=float, default=0.0, help="0–1 saturation amount")
    ap.add_argument("--width", type=float, default=1.0)
    ap.add_argument("--cd", action="store_true", help="also write a 16-bit / 44.1 kHz dithered copy")
    ap.add_argument("--out")
    ap.add_argument("--plan", nargs="?", const=True, metavar="SCAN_DIR",
                    help="change nothing: list every stage of the chain as a finding for review")
    ap.add_argument("--only", help="run only these stages: " + ", ".join(sorted(set(KEYS.values()))))
    a = ap.parse_args()
    y, sr = dsp.load(a.mix)
    name = Path(a.mix).stem
    only = {s.strip() for s in a.only.split(",") if s.strip()} if a.only else None
    if only and only - set(KEYS.values()):
        sys.exit(f"unknown stage(s): {', '.join(sorted(only - set(KEYS.values())))}")
    if a.plan:
        import time
        from hypnomix.workflow import plan as P
        t0 = time.time()
        print(f"planning the master of {name} (nothing is written) …", file=sys.stderr)
        _, before, after, log = master(y, sr, a.target, a.ceiling, a.reference, a.match, a.glue, a.warmth, a.width)
        settings = dict(target=a.target, ceiling=a.ceiling, reference=a.reference, match=a.match, glue=a.glue,
                        warmth=a.warmth, width=a.width)
        findings = [dict(kind=KEYS.get(what, "stage"), severity="medium" if KEYS.get(what) == "limiter" else "low",
                         track=Path(a.mix).name, problem=f"{what}: {setting}", fix=why,
                         plan=dict(tool="master", file=str(Path(a.mix).resolve()), key=KEYS.get(what, "stage"), **settings))
                    for what, setting, why in log]
        plan_notes = [f"master plan: the mix is {before['lufs']:.1f} LUFS, {before['tp']:.1f} dBTP; with every stage it "
                 f"would be {after['lufs']:.1f} LUFS, {after['tp']:.1f} dBTP (limiter avg {after['avg_gr']:.1f} dB "
                 f"when working)", "approved stages run in chain order into fixed/master/; without the limiter the "
                 "loudness stays where the mix is"]
        P.write(P.scan_dir(a.plan, a.mix, " master"), "master", a.mix, findings, plan_notes, time.time() - t0)
        return
    print(f"mastering {name} → {a.target} LUFS, {a.ceiling} dBTP …", file=sys.stderr)
    out, before, after, log = master(y, sr, a.target, a.ceiling, a.reference, a.match, a.glue, a.warmth, a.width,
                                     only=only)
    od = out_at(a.out, "master")
    od.mkdir(parents=True, exist_ok=True)
    dest, k = od / f"{name} (master).wav", 1
    while only and dest.exists():              # approved-moves runs never overwrite an earlier result
        k += 1
        dest = od / f"{name} (master {k}).wav"
    files = [dsp.save(dest, out, sr, 24)]
    if a.cd:
        cd, _ = (out, sr) if sr == 44100 else (dsp.load(files[0], 44100))
        files.append(dsp.save(od / f"{name} (master 16-44).wav", cd, 44100, 16))
    text = notes(name, before, after, log, a.target, files)
    (od / f"{name} (master notes).md").write_text(text)
    after_j = dict(after, settings={k: v for k, v in after["settings"].items() if k != "eq_curve"})
    (od / f"{name} (master).json").write_text(json.dumps(dict(before=before, after=after_j,
                                                              chain=[dict(step=s, setting=t, why=w) for s, t, w in log]), indent=1))
    print(text)


if __name__ == "__main__":
    main()
