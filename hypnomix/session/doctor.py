#!/usr/bin/env python3
"""Automatic first-pass diagnosis of the set that is OPEN in Live (no clicks needed).

1. Session map: groups and their child tracks, devices, faders, automation (from the .als).
2. The bounce vs your profile (bands, loudness, mono low end).
3. The loudest 8 bars of the bounce -> soloed takes of every top-level group there:
   who owns the sub (20-60), bass (60-250), speech band (1-4 k), and who spreads the low end in stereo.
Writes hypnomix-out/doctor/<song>.json and prints a summary.

Usage: hypnomix doctor SET.als BOUNCE.wav [--bars 8]
"""
import argparse, gzip, json, math, os, subprocess, sys, time
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt

from hypnomix.core.paths import out as out_dir
from hypnomix.live.osc import Live  # noqa


def band_db(x, sr, lo, hi):
    s = butter(4, [lo, hi], "bandpass", fs=sr, output="sos") if lo > 0 else butter(4, hi, "lowpass", fs=sr, output="sos")
    y = sosfilt(s, x)
    return 10 * math.log10((y ** 2).mean() + 1e-15)


def low_corr(y, sr):
    s = butter(4, 150, "lowpass", fs=sr, output="sos")
    L, R = sosfilt(s, y[:, 0]), sosfilt(s, y[:, 1])
    if np.abs(L).max() < 1e-5:
        return None
    return float(np.corrcoef(L, R)[0, 1])


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("set"); ap.add_argument("bounce"); ap.add_argument("--bars", type=int, default=8)
    a = ap.parse_args()
    song = Path(a.set).stem
    out = {"song": song}
    # --- session map from the .als
    r = ET.fromstring(gzip.open(a.set).read())
    tempo = float(r.find(".//Tempo/Manual").get("Value"))
    out["tempo"] = tempo
    # --- live session
    l = Live()
    if not l.ping():
        sys.exit("Live not answering")
    tr = [(t, n) for t, n in l.tracks() if t >= 0]
    groups = [(t, n) for t, n in tr if l.query("/live/track/get/is_foldable", t)[1]]
    grouped = {t for t, n in tr if l.query("/live/track/get/is_grouped", t)[1]}
    top = [(t, n) for t, n in tr if t not in grouped]
    out["top_level"] = [n for t, n in top]
    out["devices"] = {n: l.devices(t) for t, n in tr}
    out["devices"]["Master"] = l.devices(-1)
    out["faders"] = {n: round(l.get_db(t), 1) for t, n in tr}
    auto = subprocess.run([sys.executable, "-m", "hypnomix.cli", "automation", "list", a.set], capture_output=True, text=True).stdout
    out["automation"] = auto.strip().splitlines()
    # --- loudest section of the bounce
    y, sr = sf.read(a.bounce, always_2d=True)
    bpb = int(r.find(".//TimeSignatures/RemoteableTimeSignature/Numerator").get("Value")) if r.find(".//TimeSignatures/RemoteableTimeSignature/Numerator") is not None else 4
    bar_s = bpb * 60 / tempo
    win = int(a.bars * bar_s * sr)
    m = y.mean(1)
    rms = np.convolve(m ** 2, np.ones(int(sr)) / sr, "valid")[:: int(sr)]
    best = int(np.argmax(np.convolve(rms, np.ones(int(a.bars * bar_s)), "valid")))
    bar0 = int(best / bar_s) + 1
    out["loud_bar"] = bar0
    print(f"{song}: {tempo:.1f} BPM, loudest {a.bars} bars start at bar {bar0}")
    # --- solo takes of each top-level track/group at that spot
    res = {}
    muted = {t for t, n in top if l.query("/live/track/get/mute", t)[1]}
    l.close(); time.sleep(0.3)                       # free the reply port for loop.py
    for t, n in top:
        if t in muted:
            continue
        p = subprocess.run([sys.executable, "-m", "hypnomix.cli", "loop", "--bar", str(bar0), "--bars", str(a.bars),
                            "--label", f"doctor-{t}", "--set", f"solo {t} 1"], capture_output=True, text=True)
        l2 = Live(); l2.solo(t, 0); l2.close(); time.sleep(0.2)
        wav = next((ln.split("TAKE ", 1)[1].split("   ")[0].strip() for ln in p.stdout.splitlines() if "TAKE " in ln), None)
        if not wav:
            res[n] = {"silent": True}; continue
        z, zr = sf.read(wav, always_2d=True)
        zm = z.mean(1)
        if np.abs(zm).max() < 1e-4:
            res[n] = {"silent": True}; continue
        res[n] = {"rms": round(10 * math.log10((zm ** 2).mean() + 1e-15), 1),
                  "sub": round(band_db(zm, zr, 20, 60), 1), "bass": round(band_db(zm, zr, 60, 250), 1),
                  "speech": round(band_db(zm, zr, 1000, 4000), 1), "low_corr": low_corr(z, zr), "wav": wav}
    out["groups"] = res
    # ownership: share of each band across groups
    for band in ("sub", "bass", "speech"):
        tot = sum(10 ** (v[band] / 10) for v in res.values() if not v.get("silent"))
        for n, v in res.items():
            if not v.get("silent"):
                v[band + "_share"] = round(100 * 10 ** (v[band] / 10) / tot)
    (out_dir("doctor") / f"{song}.json").write_text(json.dumps(out, indent=1))
    print(f"{'group':<30}{'level':>7}{'sub%':>6}{'bass%':>7}{'speech%':>9}{'lowcorr':>9}")
    for n, v in sorted(res.items(), key=lambda kv: -kv[1].get("rms", -999)):
        if v.get("silent"):
            print(f"{n[:29]:<30}  (silent here)"); continue
        lc = f"{v['low_corr']:.2f}" if v["low_corr"] is not None else "  -"
        print(f"{n[:29]:<30}{v['rms']:>7}{v['sub_share']:>6}{v['bass_share']:>7}{v['speech_share']:>9}{lc:>9}")


if __name__ == "__main__":
    main()
