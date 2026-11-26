#!/usr/bin/env python3
"""Master a stereo mix for release: clean the sub, glue, (optionally) match a reference's tone,
keep the low end mono, and limit to a loudness target on true peaks. Every move is logged with why.

Usage:
    hypnomix master mix.wav [--target -14] [--ceiling -1] [--reference ref.wav [--match 0.6]]
                   [--glue 1.5] [--warmth 0] [--width 1.0] [--cd] [--out DIR]

Targets: -14 LUFS suits Spotify/YouTube/Tidal (they turn louder songs down anyway); -9 to -11 for
loud genres if you know why you want it; -16 for Apple Music-first or very dynamic music.
Writes <name> (master).wav (24-bit), optional 16-bit/44.1 kHz CD version, and a MASTER notes .md. Running it again
never replaces an earlier master: the next run writes <name> (master 2).wav with its own notes, then (master 3)...

Optional stages (all off unless asked for; see docs/MASTERING.md):
    --amount 0..100            scale every move (100 = the chain as described; 0 = only the safety ceiling)
    --stabilize TARGET         dynamic EQ toward a tonal target (`hypnomix tonal build`): only when a band
                               leaves the range  [--stabilize-max-cut 3 --stabilize-max-boost 2
                               --stabilize-speed 2 --stabilize-window 3 --stabilize-toward edge|mean
                               --stabilize-bands eight|third]
    --dyneq "freq:thresh:ratio:q[:range],…"  manual dynamic EQ bells (thresh = band RMS dBFS)
                               [--dyneq-attack 10 --dyneq-release 150]
    --harsh                    turn down sustained 2-6 kHz build-ups only where they happen
                               [--harsh-range 2000:6000 --harsh-thresh 6 --harsh-depth 0.7 --harsh-max 4]
    --width-bands "lo:hi:amount,…"  side level per range (1 = unchanged, 0 = mono)
    --mono-below HZ            low end mono below HZ (replaces the automatic 120 Hz check)
    --limiter-mode clean|punch|loud  [--clip-db N: the most the limiter may do; the clipper shaves the rest;
                               --clip-knee dB]
    --dither tpdf|shaped|off   on every 16- and 24-bit export (default tpdf)
"""
from hypnomix.core.paths import out_at
from hypnomix.core import args as A
import argparse, json, sys
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.core.paths import out as out_dir
from hypnomix.engineer import stages


def loudness_to_target(y, sr, target, ceiling, iters=5, pre=None):
    """Find the input gain so that after the limiter the song measures `target` LUFS.
    pre(x, ceiling) -> x runs between the gain and the limiter (the clipper of the punch / loud modes)."""
    g = target - dsp.lufs(y, sr)
    best = None
    for _ in range(iters):
        x = y * dsp.undb(g)
        if pre is not None:
            x = pre(x, ceiling)
        out, gr = dsp.limit(x, sr, ceiling)
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
    with tempfile.TemporaryDirectory(prefix="hypnomix-work-") as td:
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
        "Codec-safe ceiling": "limiter", "Top and tail": "toptail",
        "Tonal stabilizer": "stabilize", "Dynamic EQ": "dyneq", "Harshness tamer": "harsh",
        "Multiband width": "widthbands", "Clipper": "limiter", "Loudness vs damage": "limiter", "Dither": "dither"}

# the optional stages and their fine controls (argparse dest -> default); all off by default
OPTS = dict(amount=100.0, stabilize=None, stabilize_bands="eight", stabilize_max_cut=3.0, stabilize_max_boost=2.0,
            stabilize_speed=2.0, stabilize_window=3.0, stabilize_toward="edge", dyneq=None, dyneq_attack=10.0,
            dyneq_release=150.0, harsh=False, harsh_range="2000:6000", harsh_thresh=6.0, harsh_depth=0.7,
            harsh_max=4.0, width_bands=None, mono_below=None, limiter_mode="clean", clip_db=None, clip_knee=None, dither="tpdf")
CLIP_DEFAULT = {"punch": 3.0, "loud": 1.0}


def _mono_below_partial(y, sr, freq, a):
    """Like dsp.mono_below, but only `a` (0-1) of the low side signal is removed."""
    if a >= 1:
        return dsp.mono_below(y, sr, freq)
    m = dsp.mono_below(y, sr, freq)
    return y + (m - y) * a


def _limit(y, sr, target, ceiling, mode, clip_at, stat, knee=None):
    """Limiter for every mode: the clipper (punch / loud) sits between the gain and the limiter at clip_at dBFS
    (the chosen ceiling + clip_db), so the limiter never works more than about clip_db; whatever is taller is
    clipped. clip_at stays put when the codec-safe check lowers the limiter's ceiling: otherwise each lower
    ceiling would clip more, and clipped material overshoots MORE after encoding (a runaway seen on a real mix)."""
    pre = None
    if mode != "clean":
        def pre(x, c):
            out, n = stages.clipper(x, sr, clip_at, mode, knee)
            stat["clipped"] = n
            return out
    return loudness_to_target(y, sr, target, ceiling, pre=pre)


def master(y, sr, target=-14.0, ceiling=-1.0, reference=None, match=0.6, glue_gr=1.5, warmth=0.0, width=1.0, log=None,
           only=None, opts=None):
    """only: a set of stage keys (hpf, match, glue, monolow, width, warmth, limiter, toptail, and the optional
    stabilize, dyneq, harsh, widthbands, dither) to run and nothing else: the approved moves of a plan.
    None = the whole chain. opts: the optional stages' settings (see OPTS); None = all off, amount 100."""
    log = log if log is not None else []
    o = dict(OPTS, **{k: v for k, v in (opts or {}).items() if k in OPTS})
    amt = max(0.0, min(100.0, float(o["amount"]))) / 100
    on = lambda k: (only is None or k in only) and (amt > 0 or k in ("limiter", "dither"))
    match, glue_gr, warmth, width = match * amt, glue_gr * amt, warmth * amt, 1 + (width - 1) * amt
    if amt == 0:
        reference = None
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
    before = dict(lufs=dsp.lufs(y, sr), tp=dsp.true_peak(y, sr), corr_low=dsp.correlation(y, sr, 150),
                  crest=stages.crest_db(y))
    if amt < 1:
        st["amount"] = amt * 100

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

    if o["stabilize"] and on("stabilize"):
        from hypnomix.ears import tonal
        t = o["stabilize"] if isinstance(o["stabilize"], dict) else tonal.load_target(o["stabilize"])
        y, rep = stages.stabilize(y, sr, t, o["stabilize_bands"], o["stabilize_max_cut"], o["stabilize_max_boost"],
                                  o["stabilize_speed"], o["stabilize_window"], 1.0, o["stabilize_toward"], amt)
        moved = [b for b in rep["bands"] if b["pct_active"] > 0]
        desc = "; ".join(f"{b['band']} {b['min_db']:+.1f}…{b['max_db']:+.1f} dB ({b['pct_active']:.0f}% of the time)"
                         for b in moved) or "no band left the range: nothing moved"
        st["stabilize"] = dict(target=t["name"], bands=rep["bands"])
        log.append(("Tonal stabilizer", f"toward target '{t['name']}' ({o['stabilize_bands']} bands, max cut "
                    f"{o['stabilize_max_cut'] * amt:.1f} / boost {o['stabilize_max_boost'] * amt:.1f} dB, speed "
                    f"{o['stabilize_speed']:g} s, toward the {o['stabilize_toward']}): {desc}",
                    "A band only moves while it sits outside the range your chosen songs cover, and slowly, so the "
                    "song keeps its own shape and only the sections that drift away from your sound are nudged back."))

    if o["dyneq"] and on("dyneq"):
        bands = stages.parse_dyneq(o["dyneq"]) if isinstance(o["dyneq"], str) else o["dyneq"]
        y, rep = stages.dyneq(y, sr, bands, o["dyneq_attack"], o["dyneq_release"], amount=amt)
        st["dyneq"] = rep["bands"]
        desc = "; ".join(f"{b['freq']:g} Hz above {b['thresh']:g} dB at {b['ratio']:g}:1, Q {b['q']:g}: active "
                         f"{b['pct_active']:.0f}% of the time, avg {b['avg_cut_db']:.1f} / max {b['max_cut_db']:.1f} dB "
                         f"(band peaks at {b['level_p95_db']:.0f} dB)" for b in rep["bands"])
        log.append(("Dynamic EQ", desc, "A dynamic band only turns down while that range is too loud (a boomy note, "
                    "a sharp vocal), and leaves it alone the rest of the time, unlike a static EQ cut."))

    if o["harsh"] and on("harsh"):
        lo, hi = (float(x) for x in str(o["harsh_range"]).split(":"))
        y, rep = stages.harsh(y, sr, lo, hi, o["harsh_thresh"], o["harsh_depth"], o["harsh_max"], amount=amt)
        st["harsh"] = dict(events=rep["events"][:20])
        top = ", ".join(f"{e['start_s']:.1f}s ({e['freq_hz'] / 1000:.1f} kHz, +{e['above_usual_db']:.1f} dB)"
                        for e in sorted(rep["events"][:5], key=lambda e: e["start_s"]))
        log.append(("Harshness tamer", f"{lo / 1000:g}-{hi / 1000:g} kHz, {o['harsh_thresh']:g} dB over the neighbours "
                    f"(against the song's own balance), depth {o['harsh_depth']:g}, max {o['harsh_max'] * amt:.1f} dB: "
                    f"{len(rep['events'])} moment(s), active {rep['pct_active']:.0f}% of the time, avg "
                    f"{rep['avg_cut_db']:.1f} / max {rep['max_cut_db']:.1f} dB" + (f"; loudest at {top}" if top else ""),
                    "Only the moments where the 2-6 kHz range builds up against the bands around it are turned down, "
                    "so the song keeps its brightness and loses the bite that tires ears on loud playback."))

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
    if o["mono_below"] and on("monolow"):
        hz = float(o["mono_below"])
        y = _mono_below_partial(y, sr, hz, amt)
        st["bass_mono_hz"] = hz
        log.append(("Mono low end", f"below {hz:g} Hz summed to mono{'' if amt >= 1 else f' ({amt * 100:.0f}% of the way)'}"
                    f" (low-end L/R correlation was {cl:.2f}; your choice of frequency)",
                    "Stereo bass wanders, cancels on mono speakers and makes the limiter work harder."))
    elif cl < 0.97 and on("monolow"):
        y = _mono_below_partial(y, sr, 120, amt)
        st["bass_mono_hz"] = 120
        log.append(("Mono low end", f"everything below 120 Hz summed to mono (low-end L/R correlation was {cl:.2f})"
                    + ("" if amt >= 1 else f", {amt * 100:.0f}% of the way"),
                    "Stereo bass wanders, cancels on mono speakers and makes the limiter work harder."))

    if width != 1.0:
        y = dsp.width(y, width)
        st["width"] = width
        log.append(("Stereo width", f"side level ×{width:.2f}", "Wider sides feel bigger but fold down worse on phones."))

    if o["width_bands"] and on("widthbands"):
        wb = stages.parse_width_bands(o["width_bands"]) if isinstance(o["width_bands"], str) else o["width_bands"]
        corr0 = dsp.correlation(y)
        y, rep = stages.width_bands(y, sr, wb, amount=amt)
        st["width_bands"] = rep["bands"]
        desc = ", ".join(f"{b['lo']:g}-{b['hi']:g} Hz side ×{b['applied']:.2f}" for b in rep["bands"])
        log.append(("Multiband width", f"{desc} (L/R correlation {corr0:+.2f} → {dsp.correlation(y):+.2f})",
                    "Width per range: a narrower low-mid keeps the centre solid and folds down to mono well, wider "
                    "highs add air. Only the side signal is scaled, so anything in the centre is untouched."))

    if warmth > 0:
        y = dsp.saturate(y, warmth * 4, mix=0.35)
        st["saturation"] = dict(drive_db=warmth * 4, mix=0.35)
        log.append(("Warmth", f"tanh saturation, drive {warmth * 4:.1f} dB at 35% mix",
                    "Gentle harmonics make bass audible on small speakers and round off harsh peaks before the limiter."))

    if not on("limiter"):                      # approved moves only, loudness left where the mix was
        out = top_and_tail(y, sr, log) if on("toptail") else y
        after = dict(lufs=dsp.lufs(out, sr), tp=dsp.true_peak(out, sr), corr_low=dsp.correlation(out, sr, 150),
                     avg_gr=0.0, max_gr=0.0, pct_limiting=0.0, settings=st, crest=stages.crest_db(out))
        _dither_note(o, only, log, st)
        return out, before, after, log
    mode = o["limiter_mode"] if o["limiter_mode"] in ("clean", "punch", "loud") and amt > 0 else "clean"
    pre_l, pre_crest = dsp.lufs(y, sr), stages.crest_db(y)
    if amt < 1:                                # the loudness move is scaled too: amount 0 = only the ceiling
        target = pre_l + (target - pre_l) * amt
    clip_db = float(o["clip_db"]) if o["clip_db"] is not None else CLIP_DEFAULT.get(mode, 0.0)
    clip_eff = clip_db / max(amt, 1e-3)
    stat = {"clipped": 0}
    knee = o["clip_knee"]
    clip_at = ceiling + clip_eff
    out, gr, g, L = _limit(y, sr, target, ceiling, mode, clip_at, stat, knee)
    # codec-safe: encode test copies; if AAC/MP3 decoding overshoots, lower the ceiling and limit again.
    # Never more than 3 dB below the chosen ceiling, and a step that makes the encodes worse is undone.
    used_ceiling, first_worst, worst = ceiling, None, None
    best = None
    codec_note = ""
    for _ in range(3):
        worst = codec_worst(out, sr)
        first_worst = worst if first_worst is None else first_worst
        if best is not None and worst is not None and worst >= best[0]:
            worst, used_ceiling, out, gr, g, L, stat["clipped"] = best
            codec_note = "; a lower ceiling made the encodes worse, so the better attempt was kept"
            break
        best = (worst, used_ceiling, out, gr, g, L, stat["clipped"])
        if worst is None or worst <= -0.3:
            break
        nxt = max(ceiling - 3.0, round(used_ceiling - (worst + 0.5), 1))
        if nxt >= used_ceiling:
            codec_note = f"; stopped at {ceiling - 3.0:g} dBTP (3 dB under your ceiling): lower --target or use clean mode"
            break
        used_ceiling = nxt
        out, gr, g, L = _limit(y, sr, target, used_ceiling, mode, clip_at, stat, knee)
    else:
        worst = codec_worst(out, sr)               # the last attempt is measured too, so the notes are true
        if best is not None and worst is not None and best[0] is not None and worst >= best[0]:
            worst, used_ceiling, out, gr, g, L, stat["clipped"] = best
            codec_note = "; a lower ceiling made the encodes worse, so the better attempt was kept"
    act = gr < -0.1
    avg_gr = float(-np.mean(gr[act])) if act.any() else 0.0      # how hard it works when it works
    pct = float(np.mean(act) * 100)
    log.append(("Limiter", f"input +{g:.1f} dB, true-peak ceiling {used_ceiling} dBTP, look-ahead 5 ms, release 80 ms; "
                           f"limiting {pct:.0f}% of the time, avg {avg_gr:.1f} dB when it does, max {-gr.min():.1f} dB",
                "The limiter sets the final loudness. Watch the average reduction: under ~2 dB is transparent, 3–6 dB "
                "starts to flatten drums, above that the mix needs to be louder before mastering."))
    if used_ceiling != ceiling or (first_worst is not None and first_worst > -0.3):
        if worst is not None and worst > -0.3:
            codec_note += (f". WARNING: the encodes still peak at {worst:+.2f} dBTP: lower --target, or use clean mode "
                           "(clipped peaks overshoot most)")
        log.append(("Codec-safe ceiling", f"AAC/MP3 test encodes peaked at {first_worst:+.2f} dBTP with a {ceiling} dBTP "
                                          f"ceiling, so the limiter ran again at {used_ceiling} dBTP"
                                          + (f" (now {worst:+.2f} dBTP after encoding)" if worst is not None else "")
                                          + codec_note,
                    "Lossy encoders (Spotify, Apple Music, YouTube) rebuild the waveform and overshoot the original "
                    "peaks; a dense master can clip after encoding even when the WAV doesn't."))
    if mode != "clean":
        log.append(("Clipper", f"{mode}: oversampled {'clip' if mode == 'punch' else 'soft clip'}, "
                    f"{knee if knee is not None else (1.5 if mode == 'punch' else 3.0):g} dB knee"
                    f" at {clip_at:+.1f} dBFS, before the limiter, so the limiter does at most about "
                    f"{clip_at - used_ceiling:.1f} dB; {stat['clipped']} sample(s) ({stat['clipped'] / max(1, len(y)) * 100:.3f}%) "
                    "went through it",
                    "punch: the tallest few samples of each hit are shaved instead of the whole mix ducking around "
                    "them, so drums keep their snap at the same loudness. loud: a soft clip adds density and "
                    "harmonics; louder for the same limiting, with more colour."))
    crest_after = stages.crest_db(out)
    trade = (f"{L - before['lufs']:+.1f} LU louder than the mix, crest factor {before['crest']:.1f} → {crest_after:.1f} dB "
             f"({before['crest'] - crest_after:.1f} dB of peaks traded; {pre_crest:.1f} dB going into the limiter), "
             f"{stat['clipped']} sample(s) clipped, limiter avg {avg_gr:.1f} dB when working")
    if mode != "clean":
        c_out, c_gr, _, _ = loudness_to_target(y, sr, target, used_ceiling)
        c_act = c_gr < -0.1
        c_avg = float(-np.mean(c_gr[c_act])) if c_act.any() else 0.0
        trade += (f"; the clean limiter at the same target: crest {stages.crest_db(c_out):.1f} dB, limiter avg "
                  f"{c_avg:.1f} dB / max {-c_gr.min():.1f} dB")
    log.append(("Loudness vs damage", trade,
                "Every dB of loudness past the mix is paid for in peaks (crest factor). Under ~3 dB traded is "
                "usually inaudible; past ~6 dB drums lose their attack. Compare at matched loudness before choosing."))
    st["tradeoff"] = dict(lufs_gained=L - before["lufs"], crest_before=pre_crest, crest_after=crest_after,
                          samples_clipped=stat["clipped"], mode=mode)
    if on("toptail"):
        out = top_and_tail(out, sr, log)
    tp = dsp.true_peak(out, sr)
    after = dict(lufs=L, tp=tp, corr_low=dsp.correlation(out, sr, 150), avg_gr=avg_gr, max_gr=float(-gr.min()), pct_limiting=pct,
                 crest=stages.crest_db(out))
    st["limiter"] = dict(gain_db=g, ceiling_dbtp=used_ceiling, release_ms=80, mode=mode)
    after["settings"] = st
    _dither_note(o, only, log, st)
    return out, before, after, log


def _dither_note(o, only, log, st):
    """The export's dither is a move too: logged so a plan lists it and the notes say what was done."""
    if only is not None and "dither" not in only:
        st["dither"] = None
        return
    kind = o["dither"] if o["dither"] in ("tpdf", "shaped", "off") else "tpdf"
    st["dither"] = kind
    what = {"tpdf": "TPDF (triangular, ±1 LSB, flat spectrum)",
            "shaped": "TPDF with first-order noise shaping (the hiss is pushed up toward the top octave)",
            "off": "off: plain rounding"}[kind]
    log.append(("Dither", f"{what} on the 24-bit export (and the 16-bit CD copy if asked for)",
                "Rounding to fixed bits without dither turns the lost detail into distortion on fades and reverb "
                "tails; dither swaps it for a steady hiss far below hearing (about -141 dBFS at 24 bits, -98 at 16)."))


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
          f"| Low-end L/R correlation (<150 Hz) | {before['corr_low']:.2f} | {after['corr_low']:.2f} |",
          *([f"| Crest factor (peak - RMS) | {before['crest']:.1f} dB | {after['crest']:.1f} dB |"]
            if "crest" in before and "crest" in after else []), "",
          "## Chain, in order", ""]
    for i, (what, setting, why) in enumerate(log, 1):
        md += [f"{i}. **{what}**: {setting}  ", f"   *Why:* {why}"]
    if warn:
        md += ["", "## Warnings", *[f"- {w}" for w in warn]]
    md += ["", "## Files", *[f"- `{f}`" for f in files], "",
           "Next: `hypnomix translate` (phones, mono, streaming) and `hypnomix qc` before you upload."]
    return "\n".join(md) + "\n"


def add_stage_args(ap):
    """The optional stages' options (shared with anything that wants to offer them)."""
    g = ap.add_argument_group("optional stages (all off unless asked for)")
    g.add_argument("--amount", type=float, default=100.0, help="0-100: scale every move (100 = full, 0 = ceiling only)")
    g.add_argument("--stabilize", metavar="TARGET", help="dynamic EQ toward this tonal target (name or .json)")
    g.add_argument("--stabilize-bands", choices=["eight", "third"], default="eight")
    g.add_argument("--stabilize-max-cut", type=float, default=3.0)
    g.add_argument("--stabilize-max-boost", type=float, default=2.0)
    g.add_argument("--stabilize-speed", type=float, default=2.0, help="seconds: how slowly the gains move")
    g.add_argument("--stabilize-window", type=float, default=3.0, help="seconds of audio each band is judged on")
    g.add_argument("--stabilize-toward", choices=["edge", "mean"], default="edge")
    g.add_argument("--dyneq", metavar="BANDS", help='"freq:thresh:ratio:q[:range],…" e.g. "180:-24:2:1.5,3k:-30:3:2:4"')
    g.add_argument("--dyneq-attack", type=float, default=10.0, help="ms")
    g.add_argument("--dyneq-release", type=float, default=150.0, help="ms")
    g.add_argument("--harsh", action="store_true", help="tame sustained 2-6 kHz build-ups where they happen")
    g.add_argument("--harsh-range", default="2000:6000", help="lo:hi Hz")
    g.add_argument("--harsh-thresh", type=float, default=6.0, help="dB over the neighbouring bands before acting")
    g.add_argument("--harsh-depth", type=float, default=0.7, help="dB of cut per dB over the threshold")
    g.add_argument("--harsh-max", type=float, default=4.0, help="largest cut, dB")
    g.add_argument("--width-bands", metavar="BANDS", help='"lo:hi:amount,…" e.g. "200:800:0.8,6000:16000:1.2"')
    g.add_argument("--mono-below", type=float, metavar="HZ", help="low end mono below HZ (instead of the 120 Hz check)")
    g.add_argument("--limiter-mode", choices=["clean", "punch", "loud"], default="clean")
    g.add_argument("--clip-db", type=float, help="punch/loud: the most the limiter may do, dB (punch 3, loud 1)")
    g.add_argument("--clip-knee", type=float, help="punch/loud: knee width, dB (punch 1.5, loud 3)")
    g.add_argument("--dither", choices=["tpdf", "shaped", "off"], default="tpdf", help="on 24- and 16-bit exports")
    return ap


def opts_from(a):
    return {k: getattr(a, k) for k in OPTS if hasattr(a, k)}


def _plan_opts(a, source):
    """An approved-moves run started by `fix` (it passes only the classic settings) picks the optional stages'
    settings up from the plan it came from: <scan>/master.json, two folders above --out."""
    if not (a.only and a.out):
        return {}
    pj = Path(a.out).expanduser().resolve().parents[1] / "master.json"
    if not pj.exists():
        return {}
    try:
        fs = json.loads(pj.read_text(encoding="utf-8")).get("findings", [])
    except Exception:
        return {}
    src = str(Path(source).resolve())
    for f in fs:
        pl = f.get("plan") or {}
        if pl.get("file") == src and isinstance(pl.get("opts"), dict):
            return pl["opts"]
    return {}


def main():
    ap = argparse.ArgumentParser(prog="hypnomix master", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mix")
    ap.add_argument("--target", type=A.number(-70, 0), default=-14.0, help="loudness to master to, LUFS (-70 to 0)")
    ap.add_argument("--ceiling", type=A.number(-12, 0), default=-1.0, help="true-peak ceiling, dBTP (-12 to 0)")
    ap.add_argument("--reference")
    ap.add_argument("--match", type=A.number(0, 1), default=0.6, help="how far to move toward the reference tone (0–1)")
    ap.add_argument("--glue", type=float, default=1.5, help="target glue-compression dB (0 = off)")
    ap.add_argument("--warmth", type=A.number(0, 1), default=0.0, help="0–1 saturation amount")
    ap.add_argument("--width", type=float, default=1.0)
    ap.add_argument("--cd", action="store_true", help="also write a 16-bit / 44.1 kHz dithered copy")
    ap.add_argument("--out")
    ap.add_argument("--plan", nargs="?", const=True, metavar="SCAN_DIR",
                    help="change nothing: list every stage of the chain as a finding for review")
    ap.add_argument("--only", help="run only these stages: " + ", ".join(sorted(set(KEYS.values()))))
    add_stage_args(ap)
    a = ap.parse_args()
    y, sr = dsp.load(a.mix)
    name = Path(a.mix).stem
    only = {s.strip() for s in a.only.split(",") if s.strip()} if a.only else None
    if only and only - set(KEYS.values()):
        sys.exit(f"unknown stage(s): {', '.join(sorted(only - set(KEYS.values())))}")
    opts = opts_from(a)
    planned = _plan_opts(a, a.mix)
    for k, v in planned.items():               # options given on this command line win over the plan's
        if k in OPTS and opts.get(k) == OPTS[k]:
            opts[k] = v
    try:
        if opts.get("dyneq"):
            stages.parse_dyneq(opts["dyneq"])
        if opts.get("width_bands"):
            stages.parse_width_bands(opts["width_bands"])
        if opts.get("stabilize"):
            from hypnomix.ears import tonal
            tonal.load_target(opts["stabilize"])
    except (ValueError, FileNotFoundError) as e:
        sys.exit(str(e))
    if a.plan:
        import time
        from hypnomix.workflow import plan as P
        t0 = time.time()
        print(f"planning the master of {name} (nothing is written) …", file=sys.stderr)
        _, before, after, log = master(y, sr, a.target, a.ceiling, a.reference, a.match, a.glue, a.warmth, a.width,
                                       opts=opts)
        settings = dict(target=a.target, ceiling=a.ceiling, reference=a.reference, match=a.match, glue=a.glue,
                        warmth=a.warmth, width=a.width, opts=opts)
        findings = P.stage_findings(log, KEYS, "master", a.mix, settings, medium=("limiter", "stabilize"))
        plan_notes = [f"master plan: the mix is {before['lufs']:.1f} LUFS, {before['tp']:.1f} dBTP; with every stage it "
                 f"would be {after['lufs']:.1f} LUFS, {after['tp']:.1f} dBTP (limiter avg {after['avg_gr']:.1f} dB "
                 f"when working)", "approved stages run in chain order into fixed/master/; without the limiter the "
                 "loudness stays where the mix is"]
        if opts.get("amount", 100) != 100:
            plan_notes.append(f"every move is scaled to {opts['amount']:g}% (--amount)")
        P.write(P.scan_dir(a.plan, a.mix, " master"), "master", a.mix, findings, plan_notes, time.time() - t0)
        return
    print(f"mastering {name} → {a.target} LUFS, {a.ceiling} dBTP …", file=sys.stderr)
    out, before, after, log = master(y, sr, a.target, a.ceiling, a.reference, a.match, a.glue, a.warmth, a.width,
                                     only=only, opts=opts)
    od = out_at(a.out, "master")
    od.mkdir(parents=True, exist_ok=True)
    k = 1                                      # a run never overwrites an earlier one: (master), (master 2), (master 3) ...
    while any((od / f"{name} ({lab}){suf}").exists() for lab, suf in
              (("master" if k == 1 else f"master {k}", ".wav"), ("master" if k == 1 else f"master {k}", ".json"),
               ("master notes" if k == 1 else f"master {k} notes", ".md"),
               ("master 16-44" if k == 1 else f"master {k} 16-44", ".wav"))):
        k += 1
    tag = "master" if k == 1 else f"master {k}"
    dest = od / f"{name} ({tag}).wav"
    dith = after["settings"].get("dither")     # None: approved run without the dither move (legacy behaviour)
    files = [dsp.save(dest, out, sr, 24, dither=dith)]
    if a.cd:
        cd = out if sr == 44100 else resample_to(out, sr, 44100)
        cd_tp = dsp.true_peak(cd, 44100)
        files.append(dsp.save(od / f"{name} ({tag} 16-44).wav", cd, 44100, 16, dither=dith or "tpdf"))
        log.append(("CD copy", f"16-bit / 44.1 kHz from the float master, {dith or 'tpdf'} dither, true peak "
                               f"{cd_tp:+.2f} dBTP" + ("" if sr == 44100 else f" after resampling from {sr} Hz"),
                    "Made from the unrounded master, so it is dithered once, not twice."))
    text = notes(name, before, after, log, a.target, files)
    (od / f"{name} ({'master notes' if k == 1 else f'master {k} notes'}).md").write_text(text, encoding="utf-8")
    after_j = dict(after, settings={k: v for k, v in after["settings"].items() if k != "eq_curve"})
    (od / f"{name} ({tag}).json").write_text(json.dumps(dict(before=before, after=after_j, opts=opts,
                                                              chain=[dict(step=s, setting=t, why=w) for s, t, w in log]),
                                                         indent=1, default=str), encoding="utf-8")
    print(text)


def resample_to(y, sr, new_sr):
    import math
    from scipy.signal import resample_poly
    g = math.gcd(int(sr), int(new_sr))
    return resample_poly(y, new_sr // g, sr // g, axis=0)


if __name__ == "__main__":
    main()
