#!/usr/bin/env python3
"""Play a section in Live, record it through BlackHole, measure it, and compare it with your profile
and with the previous take of the same section. Live is controlled through hypnomix live
(AbletonOSC), so you don't need the mouse. Without a profile, only the Δ-vs-previous column shows.

Usage:
  hypnomix loop --bar 33 --bars 16                  # play, record, measure
  hypnomix loop --bar 33 --bars 16 --label vox-2db  # name the take
  hypnomix loop --bar 33 --bars 16 --set "db Lead -2" --set "send Lead A 0.35"
  hypnomix loop --no-play --secs 20                 # just record what's playing
  hypnomix loop --bar 33 --bars 16 --ab "db Lead -2"  # A/B: before vs after one change

Takes go to hypnomix-out/loop/<section>/<n>-<label>.wav plus a .json; the mixer snapshot is saved
alongside them so you can return to any take with `hypnomix live restore`.
Note: the profile holds whole-song medians, so a loud chorus loop will sit above them; the column
comparing with the previous take is the one to watch.
"""
import argparse, json, re, shlex, subprocess, sys, time
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix.ears.measure import measure                     # noqa: E402
from hypnomix.session.profile import audio_metrics, profile_ranges  # noqa: E402
from hypnomix.core.paths import out as out_dir                       # noqa: E402

SHOW = [("integrated_lufs", "LUFS", 1), ("true_peak_dbtp", "true peak", 1), ("crest_factor_db", "crest", 1),
        ("short_term_spread_lu", "ST spread", 1), ("band_sub_20_60", "sub", 1), ("band_bass_60_250", "bass", 1),
        ("band_lowmid_250_500", "low-mid", 1), ("band_mid_500_2k", "mid", 1), ("band_highmid_2k_6k", "high-mid", 1),
        ("band_air_6k_20k", "air", 1), ("spectral_centroid_hz", "centroid Hz", 0), ("side_to_mid_db", "side/mid", 1),
        ("lr_corr_below_150hz", "low mono corr", 2)]


class Recorder:
    """Records a CoreAudio input (BlackHole) straight to a float WAV via PortAudio.
    (ffmpeg's avfoundation input dropped ~2 buffers/s at 44.1 kHz, which faked +1 dB true-peak overs.)"""
    def __init__(self, secs, out, device="BlackHole 2ch", channels=2):
        import queue as _q, threading
        import sounddevice as sd
        names = [d["name"] for d in sd.query_devices()]
        hits = [i for i, n in enumerate(names) if device.lower() in n.lower() and sd.query_devices(i)["max_input_channels"] >= channels]
        if not hits:
            sys.exit(f"{device} not found among {names}. If BlackHole is installed but missing: sudo killall coreaudiod")
        dev = hits[0]
        self.sr = int(sd.query_devices(dev)["default_samplerate"])
        self.n_total, self.n, self.q, self.overflows = int(secs * self.sr), 0, _q.Queue(), 0
        self.f = sf.SoundFile(str(out), "w", self.sr, channels, subtype="FLOAT")
        self.done = threading.Event()

        def cb(indata, frames, t, status):
            if status.input_overflow:
                self.overflows += 1
            self.q.put(indata.copy())

        self.stream = sd.InputStream(device=dev, channels=channels, samplerate=self.sr, dtype="float32",
                                     blocksize=1024, latency="high", callback=cb)
        self.stream.start()
        threading.Thread(target=self._write, daemon=True).start()

    def _write(self):
        while self.n < self.n_total:
            blk = self.q.get()[: self.n_total - self.n]
            self.f.write(blk); self.n += len(blk)
        self.stream.stop(); self.stream.close(); self.f.close(); self.done.set()

    def wait(self):
        self.done.wait()
        if self.overflows:
            print(f"  ! {self.overflows} input overflows while recording — take may have gaps", file=sys.stderr)


def record(secs, out, device="BlackHole 2ch", channels=2):
    return Recorder(secs, out, device, channels)


def trim_silence(path, thresh_db=-60):
    y, sr = sf.read(str(path), always_2d=True)
    env = np.abs(y).max(axis=1)
    on = np.flatnonzero(env > 10 ** (thresh_db / 20))
    if not len(on):
        sys.exit(f"{path} is silent: is Live's output set to the Multi-Output Device (speakers + BlackHole)?")
    y = y[on[0]:on[-1] + 1]
    sf.write(str(path), y, sr, subtype="FLOAT")
    return len(y) / sr


UNDO = []   # (track, device, param, raw value before the change) for --revert


def run_cmd(live, cmd):
    """Apply a live.py CLI-style command, e.g. 'db Lead -2', 'send Lead A 0.3', 'param Master Glue Threshold 0.4'."""
    a = shlex.split(cmd)
    op, args = a[0], a[1:]
    if op in ("param", "paramd"):
        t, d, p = args[:3]
        UNDO.append((t, d, p, live.get_param(t, d, p)[0]))
    f = {"db": lambda t, v: live.set_db(t, float(v)), "nudge": lambda t, v: live.nudge_db(t, float(v)),
         "send": lambda t, r, v: live.set_send(t, r, float(v)), "pan": lambda t, v: live.set_pan(t, float(v)),
         "mute": lambda t, v: live.mute(t, int(v)), "solo": lambda t, v: live.solo(t, int(v)),
         "param": lambda t, d, p, v: live.set_param(t, d, p, float(v)),
         "paramd": lambda t, d, p, v: live.set_param_display(t, d, p, float(v))}.get(op)
    if not f:
        sys.exit(f"unknown change {cmd!r} (use db/nudge/send/pan/mute/solo/param/paramd)")
    need = {"db": 2, "nudge": 2, "send": 3, "pan": 2, "mute": 2, "solo": 2, "param": 4, "paramd": 4}[op]
    if len(args) != need or (op in ("mute", "solo") and args[1] not in ("0", "1")):
        sys.exit(f"change {cmd!r}: expected {op} with {need} arguments (mute/solo: TRACK 0|1); refusing to guess")
    r = f(*args)
    print(f"  ✓ {cmd}" + (f"  → {r}" if r is not None else ""))


def take(live, a, folder, label):
    n = max([int(f.name[:2]) for f in folder.glob("[0-9][0-9]-*.wav")] or [0]) + 1
    wav = folder / f"{n:02d}-{label}.wav"
    if a.no_play:
        secs = a.secs
        rec = record(secs, wav, a.device, a.channels)
    else:
        if live.is_playing():
            live.stop(); time.sleep(0.3)
        bpb, tempo = live.beats_per_bar(), live.tempo()
        spb = 60 / tempo
        secs = a.bars * bpb * spb
        pre = 1 if a.bar > 1 else 0                              # one bar of pre-roll hides the jump
        rec = record(secs + (pre * bpb + 2) * spb + 1.5, wav, a.device, a.channels)
        time.sleep(0.3)                                          # let the stream settle
        if not getattr(live, '_warmed', False):         # first playback after a burst of edits often glitches
            live.play_from(a.bar - pre); time.sleep(1.5); live.stop(); time.sleep(0.3); live._warmed = True
        pos = live.play_from(a.bar - pre)
        target = (a.bar - 1) * bpb
        # audio starts when playback starts; the section starts this many seconds later
        head = (live.t_pos - live.t_started) + (target - pos) * spb
    rec.wait()
    if not a.no_play:
        live.stop()
        y, sr = sf.read(str(wav), always_2d=True)
        on = np.flatnonzero(np.abs(y).max(axis=1) > 10 ** (-60 / 20))
        if not len(on):
            sys.exit(f"{wav} is silent: is Live's output set to the Multi-Output Device?")
        i0 = on[0] + int(round(head * sr))
        y = y[i0:i0 + int(round(secs * sr))]
        sf.write(str(wav), y, sr, subtype="FLOAT")
        dur = len(y) / sr
    else:
        dur = trim_silence(wav)
    m = audio_metrics(measure(wav))
    meta = {"label": label, "bar": a.bar, "bars": a.bars, "secs": round(dur, 2), "metrics": m}
    if live:
        try:
            meta["mix"] = live.snapshot()
        except Exception as e:                                  # snapshot is a bonus, never fatal
            meta["mix_error"] = str(e)
    wav.with_suffix(".json").write_text(json.dumps(meta, indent=1))
    return wav, m


def report(m, prev, prof, title):
    print(f"\n{title}")
    print(f"  {'metric':<14}{'now':>9}{'Δ prev':>9}   {'profile p25…p75':<18}")
    for k, name, dp in SHOW:
        v = m.get(k)
        if v is None:
            continue
        r = prof.get(k)
        flag = ""
        if r and r.get("p25") is not None:
            flag = "  ▲ high" if v > r["p75"] else "  ▼ low" if v < r["p25"] else ""
            rng = f"{r['p25']:.{dp}f} … {r['p75']:.{dp}f}"
        else:
            rng = ""
        d = f"{v - prev[k]:+.{dp}f}" if prev and prev.get(k) is not None else ""
        print(f"  {name:<14}{v:>9.{dp}f}{d:>9}   {rng:<18}{flag}")


def main():
    ap = argparse.ArgumentParser(prog="hypnomix loop", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bar", type=int, default=1)
    ap.add_argument("--bars", type=int, default=8)
    ap.add_argument("--label", default="take")
    ap.add_argument("--set", action="append", default=[], help="change to apply before the take (repeatable)")
    ap.add_argument("--ab", action="append", default=[], help="A/B: take as-is, apply these changes, take again")
    ap.add_argument("--revert", action="store_true", help="with --ab: put the mix back after the B take")
    ap.add_argument("--no-play", action="store_true", help="don't drive Live, just record --secs")
    ap.add_argument("--secs", type=float, default=20)
    ap.add_argument("--device", default="BlackHole 2ch")
    ap.add_argument("--channels", type=int, default=2)
    if len(sys.argv) <= 1:           # no arguments: show the usage instead of connecting to Live and playing bar 1
        ap.print_help()
        sys.exit(2)
    a = ap.parse_args()

    if a.ab and a.no_play:
        sys.exit("--ab needs Live (drop --no-play)")
    live = None
    if not a.no_play:
        from hypnomix.live.osc import Live
        live = Live()
        if not live.ping():
            sys.exit("Live isn't answering (AbletonOSC). Run: hypnomix doctor")
    section = "live-input" if a.no_play else f"bars{a.bar:03d}-{a.bar + a.bars - 1:03d}"
    folder = out_dir("loop", section)
    prof = profile_ranges()
    prev_json = sorted(folder.glob("*.json"))
    prev = json.loads(prev_json[-1].read_text())["metrics"] if prev_json else None

    for c in a.set:
        run_cmd(live, c)
    UNDO.clear()                     # --revert only undoes the --ab changes

    if a.ab:
        before = live.snapshot()
        wa, ma = take(live, a, folder, f"{a.label}-A")
        report(ma, prev, prof, f"A  TAKE {wa}")
        for c in a.ab:
            run_cmd(live, c)
        wb, mb = take(live, a, folder, f"{a.label}-B")
        report(mb, ma, prof, f"B  TAKE {wb}   (Δ = B − A)")
        if a.revert:
            live.restore(before)
            for t, d, p, v in reversed(UNDO):
                live.set_param(t, d, p, v)
            live.reenable_automation()
            print(f"\n  mix reverted to A ({len(UNDO)} device settings restored, automation re-enabled)")
    else:
        w, m = take(live, a, folder, a.label)
        report(m, prev, prof, f"TAKE {w}" + ("   (Δ vs previous take)" if prev else ""))
    if live:
        live.close()


if __name__ == "__main__":
    main()
