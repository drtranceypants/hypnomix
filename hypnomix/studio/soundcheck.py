#!/usr/bin/env python3
"""Set your recording level before you press record. Play or sing the loudest part for ~15 seconds;
soundcheck listens to your audio interface input and tells you what to change.

Checks: peak and headroom, average level, clipping, noise floor (between notes), mains hum (50/60 Hz),
DC offset. Advice is for 24-bit recording: peaks around -12 to -6 dBFS, no need to record hot.

Usage:
    hypnomix soundcheck --list                         show input devices
    hypnomix soundcheck [--device "USB Audio"] [--channel 1] [--secs 15]
    hypnomix soundcheck --file take.wav                check a recording you already made
    hypnomix soundcheck --watch [--device …]           live meter (Ctrl-C to stop)
"""
import argparse, sys, time
from pathlib import Path

import numpy as np

from hypnomix.core import dsp


def hum(y, sr):
    """Strength of mains hum: energy at 50 or 60 Hz and harmonics vs the neighbouring bins, dB."""
    m = y.mean(axis=1)
    n = min(len(m), sr * 8)
    S = np.abs(np.fft.rfft(m[:n] * np.hanning(n))) ** 2
    f = np.fft.rfftfreq(n, 1 / sr)
    best = (0.0, None)
    for base in (50, 60):
        ex = []
        for h in (1, 2, 3, 4):
            c = base * h
            on = S[(f > c - 1) & (f < c + 1)].sum()
            near = np.median(S[(f > c - 15) & (f < c + 15)]) * np.sum((f > c - 1) & (f < c + 1))
            ex.append(10 * np.log10(on / (near + 1e-20) + 1e-20))
        v = float(np.mean(sorted(ex)[-2:]))
        if v > best[0]:
            best = (v, base)
    return best


def analyse(y, sr):
    peak = dsp.sample_peak(y)
    clips = int(np.sum(np.abs(y) >= 0.999))
    b = dsp.block_rms_db(y, sr, 0.05)
    loud = float(np.percentile(b, 90))
    floor = float(np.percentile(b, 5))
    hm, base = hum(y, sr)
    dc = float(np.abs(y.mean(axis=0)).max())
    advice = []
    if clips or peak > -1:
        advice.append(f"TOO HOT: peaks at {peak:.1f} dBFS ({clips} clipped samples). Turn the preamp gain down about "
                      f"{max(6, peak + 12):.0f} dB. Clipping at the converter can't be undone later.")
    elif peak > -4:
        advice.append(f"Hot: peaks at {peak:.1f} dBFS. A louder performance will clip; turn gain down ~4 dB.")
    elif peak < -24:
        advice.append(f"Too quiet: peaks at {peak:.1f} dBFS. Turn the gain up about {abs(peak + 10):.0f} dB "
                      "(the noise floor stays where it is; the signal rises above it).")
    elif peak < -16:
        advice.append(f"A bit low: peaks at {peak:.1f} dBFS. Up ~{abs(peak + 10):.0f} dB would be ideal, but this is usable in 24-bit.")
    else:
        advice.append(f"Good level: peaks at {peak:.1f} dBFS, {abs(peak):.0f} dB of headroom.")
    snr = loud - floor
    if floor > -50:
        advice.append(f"Noisy: {floor:.0f} dBFS between notes. Check for a fan/AC, a dirty cable, or a preamp turned up "
                      "with a quiet source (move the mic closer instead).")
    elif snr < 30:
        advice.append(f"Signal is only {snr:.0f} dB above the noise. Get closer to the mic or play louder.")
    if hm > 12:
        advice.append(f"Mains hum at {base} Hz ({hm:.0f} dB above its surroundings): ground loop or a single-coil "
                      "pickup near a power supply. Try another socket, move away from screens, or a DI with ground lift.")
    if dc > 0.005:
        advice.append("DC offset present: usually a faulty interface channel or pedal; it wastes headroom.")
    return dict(peak=peak, clips=clips, loud=loud, floor=floor, hum=(hm, base), dc=dc, advice=advice)


def pick_device(name, channels):
    import sounddevice as sd
    devs = sd.query_devices()
    if name is None:
        i = sd.default.device[0]
        return i, devs[i]
    hits = [i for i, d in enumerate(devs) if name.lower() in d["name"].lower() and d["max_input_channels"] >= channels]
    if not hits:
        sys.exit(f"no input device matching {name!r}; run with --list")
    return hits[0], devs[hits[0]]


def record(device, channel, secs):
    import sounddevice as sd
    i, d = pick_device(device, channel)
    sr = int(d["default_samplerate"])
    print(f"listening on {d['name']} input {channel} for {secs:g} s: play your loudest part now …", file=sys.stderr)
    y = sd.rec(int(secs * sr), samplerate=sr, channels=channel, device=i, dtype="float32")
    sd.wait()
    return y[:, channel - 1: channel].astype(np.float64), sr


def watch(device, channel):
    import sounddevice as sd
    i, d = pick_device(device, channel)
    sr = int(d["default_samplerate"])
    held = -120.0
    def cb(indata, frames, t, status):
        nonlocal held
        x = indata[:, channel - 1]
        pk = float(dsp.db(np.max(np.abs(x))))
        held = max(pk, held - 1.5)
        bar = int(max(0, (pk + 60) / 60 * 50))
        zone = "CLIP" if pk > -1 else "hot " if pk > -6 else "good" if pk > -18 else "low "
        sys.stdout.write(f"\r{'█' * bar:<50} {pk:6.1f} dBFS  hold {held:6.1f}  {zone}")
        sys.stdout.flush()
    with sd.InputStream(device=i, channels=channel, samplerate=sr, blocksize=int(sr * 0.1), callback=cb):
        print(f"{d['name']} input {channel}  (good: -18 … -6 dBFS peaks)  Ctrl-C to stop")
        try:
            while True:
                time.sleep(0.2)
        except KeyboardInterrupt:
            print()


def main():
    ap = argparse.ArgumentParser(prog="hypnomix soundcheck", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true"); ap.add_argument("--device"); ap.add_argument("--channel", type=int, default=1)
    ap.add_argument("--secs", type=float, default=15); ap.add_argument("--file"); ap.add_argument("--watch", action="store_true")
    a = ap.parse_args()
    if a.list:
        import sounddevice as sd
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"]:
                print(f"{i:>3}  {d['name']:<40} {d['max_input_channels']} in  {int(d['default_samplerate'])} Hz")
        return
    if a.watch:
        return watch(a.device, a.channel)
    y, sr = dsp.load(a.file) if a.file else record(a.device, a.channel, a.secs)
    r = analyse(y, sr)
    print(f"\npeak {r['peak']:.1f} dBFS · loud parts {r['loud']:.0f} dBFS · noise floor {r['floor']:.0f} dBFS · "
          f"hum {r['hum'][0]:.0f} dB @ {r['hum'][1]} Hz")
    for x in r["advice"]:
        print(f"  • {x}")


if __name__ == "__main__":
    main()
