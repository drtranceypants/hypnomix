#!/usr/bin/env python3
"""Will it still sound right everywhere else? Checks a mix or master the way it'll actually be heard.

  mono        what is lost when L+R are summed (phones held sideways, club PAs, Bluetooth speakers)
  phone       a small speaker: nothing below ~300 Hz, a bump at 1–3 kHz. Is the bass line still audible?
  earbuds     cheap earbuds: rolled-off lows, hyped highs. Is the top end harsh?
  car         big low-end boom. Does the low end get out of hand?
  streaming   how much Spotify, Apple Music, YouTube, Tidal and Amazon turn it down (or up)
  codecs      MP3 320 and AAC 256 encode/decode: does it clip after encoding?

Usage:
    hypnomix translate song.wav [--render] [--preview] [--out DIR]
    --render writes the phone/earbud/car/mono versions so you can listen to them yourself.
    --preview writes what the streaming encoders hand back, decoded to WAV so any player (and the review page)
              can play them: MP3 320, AAC 256, and "as Spotify plays it" (AAC 256 turned to -14 LUFS the way
              its default normalisation does: louder songs down, quieter songs up only as far as -1 dBTP allows).
              Same length and start as the original, for A/B.
"""
from hypnomix.core.paths import out_at
import argparse, subprocess, sys, tempfile
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.core.paths import out as out_dir

# loudness normalisation reference levels (LUFS) and whether quiet songs get turned up
PLATFORMS = [("Spotify", -14, True), ("Apple Music", -16, True), ("YouTube", -14, False),
             ("Tidal", -14, False), ("Amazon Music", -14, False), ("Deezer", -15, False)]


def sim(y, sr, kind):
    eq = dsp.EQ()
    if kind == "phone":
        eq.add("highpass", 320, q=1.0).add("bell", 2000, 5, 0.8).add("lowpass", 9000)
    elif kind == "earbuds":
        eq.add("highpass", 60).add("bell", 150, -3, 0.8).add("bell", 4500, 4, 1.2).add("highshelf", 9000, 3)
    elif kind == "car":
        eq.add("lowshelf", 90, 7).add("bell", 400, 2, 1.0).add("highshelf", 8000, -3)
    out = eq.apply(y, sr)
    if kind == "phone":
        out = dsp.stereo(out.mean(axis=1, keepdims=True))
    return out


def codec_peak(path, codec):
    with tempfile.TemporaryDirectory() as td:
        enc = Path(td) / ("x.mp3" if codec == "mp3" else "x.m4a")
        args = ["-b:a", "320k", "-c:a", "libmp3lame"] if codec == "mp3" else ["-b:a", "256k", "-c:a", "aac"]
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), *args, str(enc)], capture_output=True)
        if r.returncode:
            return None
        dec = Path(td) / "d.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(enc), "-c:a", "pcm_f32le", str(dec)], check=True)
        y, sr = dsp.load(dec)
        return dsp.true_peak(y, sr)


def _decode(path, codec, td):
    """Encode with ffmpeg and decode back to float audio (None if the encoder is missing)."""
    enc = Path(td) / ("x.mp3" if codec == "mp3" else "x.m4a")
    args = ["-b:a", "320k", "-c:a", "libmp3lame"] if codec == "mp3" else ["-b:a", "256k", "-c:a", "aac"]
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), *args, str(enc)], capture_output=True)
    if r.returncode:
        return None
    dec = Path(td) / f"{codec}.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(enc), "-c:a", "pcm_f32le", str(dec)], check=True)
    return dsp.load(dec)[0]


def codec_preview(path, outdir, normalise_to=-14.0):
    """Write decoded MP3 320 / AAC 256 WAVs and an 'as Spotify plays it' WAV next to each other in outdir.
    Returns {kind: {path, true_peak, lufs}}; a kind whose encoder is missing is left out (key 'skipped')."""
    y, sr = dsp.load(path)
    n = len(y)
    od = Path(outdir)
    od.mkdir(parents=True, exist_ok=True)
    stem = Path(path).stem
    res, skipped = {}, []
    with tempfile.TemporaryDirectory() as td:
        for codec, label in (("mp3", "mp3 320"), ("aac", "aac 256")):
            z = _decode(path, codec, td)
            if z is None:
                skipped.append(label)
                continue
            z = np.pad(z, ((0, max(0, n - len(z))), (0, 0)))[:n]      # same length as the original, for A/B
            p = dsp.save(od / f"{stem} ({label}).wav", z, sr, 32)       # float: overshoots kept as decoded
            res[label] = dict(path=str(p), true_peak=dsp.true_peak(z, sr), lufs=dsp.lufs(z, sr))
            if codec == "aac":
                L, tp = dsp.lufs(z, sr), dsp.true_peak(z, sr)
                gain = normalise_to - L
                if gain > 0:
                    gain = min(gain, -1.0 - tp)                       # quiet songs go up only to -1 dBTP
                s = z * dsp.undb(gain)
                q = dsp.save(od / f"{stem} (as Spotify plays it).wav", s, sr, 32)
                res["as Spotify plays it"] = dict(path=str(q), gain_db=round(float(gain), 2),
                                                  true_peak=dsp.true_peak(s, sr), lufs=dsp.lufs(s, sr))
    if skipped:
        res["skipped"] = skipped
    return res


def analyse(path, render=False, outdir=None):
    y, sr = dsp.load(path)
    y = dsp.stereo(y)
    if not len(y) or float(np.max(np.abs(y))) < 1e-9:
        return dict(silent=True, lufs=None, tp=None, rows=[],
                    notes=["the file is silent (every sample is zero), so there is nothing to check"])
    L = dsp.lufs(y, sr)
    tp = dsp.true_peak(y, sr)
    rows, notes = [], []
    edges = [(40, 120), (120, 400), (400, 2000), (2000, 6000), (6000, 16000)]
    names = ["low end", "low-mids", "mids", "presence", "highs"]
    ref_e, _ = dsp.band_energy(y, sr, edges)

    mono = dsp.stereo(y.mean(axis=1, keepdims=True))
    mono_e, _ = dsp.band_energy(mono, sr, edges)
    loss = 10 * np.log10((mono_e + 1e-20) / (ref_e + 1e-20))
    d_mono = dsp.lufs(mono, sr) - L
    worst = int(np.argmin(loss))
    rows.append(("Mono", f"{d_mono:+.1f} LU overall; worst: {names[worst]} {loss[worst]:+.1f} dB",
                 "OK" if d_mono > -2 and loss.min() > -3 else "WARN"))
    if loss.min() <= -3:
        notes.append(f"In mono the {names[worst]} drop {abs(loss[worst]):.1f} dB: something there is wide or out of phase "
                     "(stereo widener, chorus, a flipped mic). `hypnomix align` checks the mic pairs.")
    corr = dsp.correlation(y)
    rows.append(("Phase (L/R correlation)", f"{corr:+.2f}", "OK" if corr > 0.2 else "WARN" if corr > 0 else "FAIL"))

    sims = {}
    for kind in ("phone", "earbuds", "car"):
        z = sim(y, sr, kind)
        z *= dsp.undb(L - dsp.lufs(z, sr))                   # compare at equal loudness
        sims[kind] = z
        e, _ = dsp.band_energy(z, sr, edges)
        sims[kind + "_bands"] = 10 * np.log10((e + 1e-20) / max(float(e.sum()), 1e-20))
    # phone: does the bass line survive? energy in 300-1000 Hz harmonics relative to the mids
    pb = sims["phone_bands"]
    rows.append(("Phone speaker", f"low-mids {pb[1]:.1f} dB, presence {pb[3]:.1f} dB of total", "INFO"))
    sub_share = 10 * np.log10((ref_e[0] + 1e-20) / max(float(ref_e.sum()), 1e-20))
    if sub_share > -6:
        notes.append(f"{sub_share:.1f} dB of the energy is below 120 Hz, which phones can't play: on a phone this song "
                     "loses most of its kick and bass. Saturation on the bass (harmonics at 200–800 Hz) or a 3–5 kHz click "
                     "on the kick keeps them audible.")
    eb = sims["earbuds_bands"]
    if eb[3] > -6:
        notes.append("On bright earbuds the 2–6 kHz range dominates: check vocals and cymbals for harshness at low volume.")
    cb = sims["car_bands"]
    if cb[0] > -2:
        notes.append("In a car the low end will boom: compare your bass with a reference at the same volume.")

    for name, ref, up in PLATFORMS:
        change = ref - L
        if change > 0 and not up:
            change = 0.0
        if change > 0 and up:
            change = min(change, -1.0 - tp)                     # they only raise gain up to their peak headroom
        change = round(change, 1) + 0.0
        rows.append((f"{name} playback", f"{change:+.1f} dB ({'turned down' if change < 0 else 'turned up' if change > 0 else 'unchanged'})", "INFO"))
    if L > -10:
        notes.append(f"At {L:.1f} LUFS every major platform turns this down by {abs(-14 - L):.0f} dB or more: the extra "
                     "loudness bought with limiting is thrown away, and only the squashed dynamics remain.")

    for codec in ("mp3", "aac"):
        p = codec_peak(path, codec)
        if p is None:
            rows.append((f"{codec.upper()} encode", "encoder not available in ffmpeg", "SKIP"))
            continue
        rows.append((f"{codec.upper()} encode peak", f"{p:+.2f} dBTP", "OK" if p < -0.1 else "FAIL"))
        if p >= -0.1:
            notes.append(f"After {codec.upper()} encoding the peaks reach {p:+.2f} dBTP and will clip on playback: master "
                         "with a lower true-peak ceiling (-1.5 or -2 dBTP).")

    if render:
        od = out_at(outdir, "translate", Path(path).stem)
        for kind in ("phone", "earbuds", "car"):
            dsp.save(od / f"{Path(path).stem} ({kind}).wav", sims[kind] * dsp.undb(min(0, -1 - dsp.true_peak(sims[kind], sr))), sr)
        dsp.save(od / f"{Path(path).stem} (mono).wav", mono, sr)
    return dict(lufs=L, tp=tp, rows=rows, notes=notes)


def main():
    ap = argparse.ArgumentParser(prog="hypnomix translate", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file"); ap.add_argument("--render", action="store_true"); ap.add_argument("--out")
    ap.add_argument("--preview", action="store_true", help="write decoded MP3 / AAC / as-Spotify-plays-it WAVs")
    a = ap.parse_args()
    r = analyse(a.file, a.render, a.out)
    if r.get("silent"):
        text = (f"# Translation check: {Path(a.file).name}\n\nThis file is silent (every sample is zero), so there is "
                f"nothing to check. Bounce or export it again.\n")
        (out_at(a.out, "translate") / f"{Path(a.file).stem} (translation).md").write_text(text)
        print(text)
        sys.exit(1)
    if a.preview:
        pv = codec_preview(a.file, out_at(a.out, "translate", Path(a.file).stem))
        for k, v in pv.items():
            if k == "skipped":
                r["rows"].append(("Preview", f"encoder missing: {', '.join(v)}", "SKIP"))
                continue
            extra = f", turned {v['gain_db']:+.1f} dB" if "gain_db" in v else ""
            r["rows"].append((f"Preview: {k}", f"{v['lufs']:.1f} LUFS, {v['true_peak']:+.2f} dBTP{extra} → "
                                               f"`{Path(v['path']).name}`", "INFO"))
    md = [f"# Translation check: {Path(a.file).name}", "", f"{r['lufs']:.1f} LUFS, {r['tp']:+.1f} dBTP", "",
          "| check | result | |", "|---|---|---|", *[f"| {a_} | {b} | {c} |" for a_, b, c in r["rows"]], ""]
    md += ["## What to listen for", *[f"- {n}" for n in r["notes"]]] if r["notes"] else ["Nothing worrying. Still: listen on a phone."]
    text = "\n".join(md) + "\n"
    od = out_at(a.out, "translate")
    (od / f"{Path(a.file).stem} (translation).md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
