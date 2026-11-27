"""`hypnomix chain` in REAPER: the same chains as in Live, built from REAPER's own plug-ins (all free, all stock).

    Live device          REAPER                              set by
    EQ Eight             ReaEQ (5 bands; a 2nd one if needed) band type, frequency, gain, bandwidth (from Q)
    Glue Compressor      ReaComp                              threshold, 2:1, attack, release, RMS detector, knee
    Compressor           ReaComp                              threshold, ratio, attack, release, knee
    Utility (bass mono)  JS: Mid/Side Encoder → ReaEQ → ReaEQ → JS: Mid/Side Decoder
                         the side channel high-passed at the frequency (Linkwitz-Riley, 24 dB/oct), the mid channel
                         through the matching all-pass so the two recombine exactly above it (measured in REAPER:
                         leak under -68 dB at 400 Hz, -94 dB at 2 kHz; the low end mono)
    Utility (width)      JS: Stereo Field Manipulator         width %
    Saturator            JS: Saturation                       amount (a gentle equivalent of the drive)
    Limiter              ReaLimit                             ceiling, and threshold = ceiling - gain (ReaLimit
                                                              raises the level by ceiling - threshold: measured)

Values are set by what the plug-in shows (Hz, dB, ms), so they read in REAPER exactly as planned. With --verify
REAPER renders the loudest bars of the master (no BlackHole: REAPER writes the file itself), HypnoMix measures
them and trims ReaLimit until the loudness matches the offline master, and lowers the ceiling if true peak is over.
Every change is an undo step in REAPER ("hypnomix: ...").
"""
import math
import tempfile
from pathlib import Path

import numpy as np

from hypnomix.core import dsp

REAEQ = "ReaEQ (Cockos)"
REACOMP = "ReaComp (Cockos)"
REALIMIT = "ReaLimit (Cockos)"
MS_ENC, MS_DEC = "JS: Mid/Side Encoder", "JS: Mid/Side Decoder"
WIDTH = "JS: Stereo Field Manipulator"
SAT = "JS: Saturation"
BAND_TYPE = {"lowshelf": 0, "highshelf": 1, "lowcut12": 4, "lowcut48": 4, "highcut12": 3, "highcut48": 3,
             "bell": 8, "notch": 6}
LIVE_EQ_NAMES = {"Low Cut 12": "lowcut12", "High Cut 12": "highcut12", "Bell": "bell", "Low Shelf": "lowshelf",
                 "High Shelf": "highshelf", "Notch": "notch"}


def q_to_octaves(q):
    """ReaEQ sets a band's width in octaves; EQ Eight (and the plans) in Q."""
    return 2 / math.log(2) * math.asinh(1 / (2 * max(q, 0.05)))


class Builder:
    def __init__(self, r, track, dry=False):
        self.r, self.track, self.dry, self.notes = r, track, dry, []

    def add(self, name):
        if self.dry:
            return None
        return self.r.add_fx(self.track, name)["fx"]

    def shown(self, fx, param, value, label=None):
        if self.dry:
            return
        try:
            return self.r.set_shown(self.track, fx, param, value)["shown"]
        except Exception as e:
            self.notes.append(f"{label or param}: could not be set ({e}); set it by hand to {value}")

    def norm(self, fx, param, value):
        if not self.dry:
            return self.r.set_norm(self.track, fx, param, value)["shown"]

    def bass_mono(self, hz):
        """Mono below hz, stereo untouched above: M/S, side high-passed, mid all-passed to match, back to L/R."""
        if self.dry:
            return
        self.add(MS_ENC)
        bw = round(q_to_octaves(0.7071), 2)

        def one_channel_eq(ch, bands):
            fx = self.add(REAEQ)
            for k in range(5):
                if k < len(bands):
                    self.r.named(self.track, fx, f"BANDTYPE{k}", str(bands[k]))
                    self.r.named(self.track, fx, f"BANDENABLED{k}", "1")
                    self.shown(fx, 3 * k, hz, "bass mono frequency")
                    self.shown(fx, 3 * k + 2, bw, "bass mono slope")
                else:
                    self.r.named(self.track, fx, f"BANDENABLED{k}", "0")
            for out in (False, True):                    # this ReaEQ reads and writes one channel; the other passes
                self.r.pins(self.track, fx, out, 0, ch)
                self.r.pins(self.track, fx, out, 1, 0)
        one_channel_eq(2, [4, 4])                        # side: two 12 dB high-passes = Linkwitz-Riley 24 dB/oct
        one_channel_eq(1, [5])                           # mid: the all-pass with the same phase
        self.add(MS_DEC)

    def reaeq(self, bands):
        """Bands of one plan onto ReaEQs of 5 bands each; unused bands switched off."""
        done = []
        for start in range(0, max(1, len(bands)), 5):
            part = bands[start:start + 5]
            fx = self.add(REAEQ)
            for k in range(5):
                if self.dry:
                    continue
                if k >= len(part):
                    self.r.named(self.track, fx, f"BANDENABLED{k}", "0")
                    continue
                b = part[k]
                self.r.named(self.track, fx, f"BANDTYPE{k}", str(BAND_TYPE[b["type"]]))
                self.r.named(self.track, fx, f"BANDENABLED{k}", "1")
                self.shown(fx, 3 * k, b["freq"], f"band {start + k + 1} frequency")
                if b["type"] in ("bell", "lowshelf", "highshelf"):
                    self.shown(fx, 3 * k + 1, b["gain"], f"band {start + k + 1} gain")
                self.shown(fx, 3 * k + 2, round(q_to_octaves(b.get("q", 0.71)), 2), f"band {start + k + 1} width")
            done.append(fx)
        return done


# ---------------------------------------------------------------- master
def build_master(r, plan, existing="refuse", dry=False):
    tid = "master"
    if not dry:
        have = [f["name"] for f in r.fx_list(tid)]
        if have:
            if existing == "bypass":
                for i in range(len(have)):
                    r.enable(tid, i, False)
            elif existing != "keep":
                raise SystemExit(f"the master already has plug-ins {have}; use --existing bypass or --existing keep")
    b = Builder(r, tid, dry)
    rows = []
    for step in plan:
        d = step["device"]
        if d == "EQ Eight":
            b.reaeq(step["bands"])
            rows.append(("ReaEQ", "; ".join(f"{x['type']} {x['freq']:g} Hz" + (f" {x['gain']:+.1f} dB" if x["type"] in
                                             ("bell", "lowshelf", "highshelf") else "") for x in step["bands"]), step["why"]))
        elif d == "Glue Compressor":
            fx = b.add(REACOMP)
            b.shown(fx, "Threshold", step["threshold_db"])
            b.shown(fx, "Ratio", step["ratio"])
            b.shown(fx, "Attack", step["attack_ms"])
            b.shown(fx, "Release", step["release_s"] * 1000)
            b.shown(fx, "RMS size", 50)          # the plan's threshold was measured with an RMS detector
            b.shown(fx, "Knee", 6)
            rows.append(("ReaComp", f"threshold {step['threshold_db']} dB, {step['ratio']}:1, attack {step['attack_ms']} ms, "
                                    f"release {step['release_s'] * 1000:.0f} ms, RMS, 6 dB knee", step["why"]))
        elif d == "Utility":
            parts = []
            if step.get("bass_mono_hz"):
                b.bass_mono(step["bass_mono_hz"])
                parts.append(f"mono below {step['bass_mono_hz']} Hz (M/S encoder, side high-pass, mid all-pass, decoder)")
            if step.get("width_pct", 100) != 100:
                fx = b.add(WIDTH)
                b.shown(fx, "Width (%)", step["width_pct"])
                parts.append(f"Stereo Field Manipulator: width {step['width_pct']}%")
            rows.append(("JS (stock)", "; ".join(parts), step["why"]))
        elif d == "Saturator":
            fx = b.add(SAT)
            amount = round(min(60.0, step["drive_db"] * 6 * step["dry_wet_pct"] / 100), 1)
            b.shown(fx, "Amount (%)", amount)
            rows.append(("JS: Saturation", f"amount {amount}% (for drive {step['drive_db']} dB at "
                                           f"{step['dry_wet_pct']}% wet)", step["why"]))
        elif d == "Limiter":
            fx = b.add(REALIMIT)
            b.shown(fx, "Ceiling", step["ceiling_db"])
            b.shown(fx, "Threshold", step["ceiling_db"] - step["gain_db"])
            if step.get("release_ms"):
                b.shown(fx, "Release", step["release_ms"])
            step["_fx"] = fx
            rows.append(("ReaLimit", f"threshold {step['ceiling_db'] - step['gain_db']:+.1f} dB, ceiling {step['ceiling_db']} dB "
                                     f"(= {step['gain_db']:+.1f} dB of gain)", step["why"]))
    return rows, b.notes


def verify(r, plan, ctx, bars=8, rounds=3):
    """REAPER renders the loudest bars of the master; trim ReaLimit until they match the offline master."""
    from hypnomix.engineer.chain import loudest_bars
    info = r.ping()
    tempo = info.get("tempo") or 120.0
    bar = loudest_bars(ctx["master_audio"], ctx["sr"], tempo, 4, bars)
    t0 = (bar - 1) * 4 * 60 / tempo
    secs = bars * 4 * 60 / tempo
    a = int(t0 * ctx["sr"])
    want = dsp.lufs(ctx["master_audio"][a:a + int(secs * ctx["sr"])], ctx["sr"])
    lim = next(s for s in plan if s["device"] == "Limiter")
    fx, gain, ceiling = lim["_fx"], lim["gain_db"], lim["ceiling_db"]
    lines = [f"Calibrating on bars {bar}-{bar + bars - 1} ({t0:.1f}-{t0 + secs:.1f} s): the offline master measures "
             f"{want:.1f} LUFS there."]
    with tempfile.TemporaryDirectory(prefix="hypnomix-work-") as td:
        for k in range(rounds):
            wav = r.render_master(t0, t0 + secs, Path(td) / f"verify-{k}.wav")
            y, sr = dsp.load(wav)
            got, tp = dsp.lufs(y, sr), dsp.true_peak(y, sr)
            d = want - got
            lines.append(f"  pass {k + 1}: REAPER renders {got:.1f} LUFS, true peak {tp:+.1f} dBTP ({d:+.1f} LU from target)")
            changed = False
            if tp > lim["ceiling_db"] + 0.05:
                ceiling -= tp - lim["ceiling_db"] + 0.1
                r.set_shown("master", fx, "Ceiling", round(ceiling, 2))
                changed = True
            if abs(d) >= 0.3:
                gain += d
                changed = True
            if changed:
                r.set_shown("master", fx, "Threshold", round(ceiling - gain, 2))
            if not changed:
                break
        # ReaLimit limits sample peaks: between samples the signal can go higher (true peak). Check the whole song,
        # where the worst overshoot may be outside the loud bars, and pull the ceiling down by what is over
        dur = len(ctx["master_audio"]) / ctx["sr"]
        for k in range(3):
            wav = r.render_master(0, dur, Path(td) / f"whole-{k}.wav")
            y, sr = dsp.load(wav)
            tp, got = dsp.true_peak(y, sr), dsp.lufs(y, sr)
            lines.append(f"  whole song: {got:.1f} LUFS, true peak {tp:+.2f} dBTP")
            if tp <= lim["ceiling_db"] + 0.05:
                break
            ceiling -= tp - lim["ceiling_db"] + 0.1
            r.set_shown("master", fx, "Ceiling", round(ceiling, 2))
            r.set_shown("master", fx, "Threshold", round(ceiling - gain, 2))
            lines.append(f"    true peak over {lim['ceiling_db']:+.1f} dBTP: ceiling lowered to {ceiling:+.2f} dB "
                         "(ReaLimit limits samples, not the peaks between them)")
        else:
            lines.append(f"  STILL OVER: true peak {tp:+.2f} dBTP after 3 passes; lower ReaLimit's ceiling by hand")
    lines.append(f"ReaLimit: threshold {ceiling - gain:+.1f} dB, ceiling {ceiling:+.2f} dB ({gain:+.1f} dB of gain).")
    return lines


# ---------------------------------------------------------------- strips
def build_strips(r, recipe, dry=False):
    import json
    import re
    rec = json.loads(Path(recipe).read_text(encoding="utf-8", errors="replace"))
    tracks = {} if dry else {re.sub(r"^\d+\s*", "", t["name"]).lower(): t["index"] for t in r.tracks()}
    out = []
    for t in rec["tracks"]:
        key = re.sub(r"^\d+\s*", "", t["stem"]).lower()
        tid = tracks.get(key) if not dry else 0
        if tid is None:
            hits = [v for k, v in tracks.items() if key in k or k in key]
            tid = hits[0] if len(hits) == 1 else None
        if tid is None:
            out.append(f"- {t['stem']}: no track with that name in the project (name the track after the stem)")
            continue
        b = Builder(r, tid, dry)
        done = []
        for dev in t["live_devices"]:
            if dev["device"] == "EQ Eight" and dev["bands"]:
                b.reaeq([dict(type=LIVE_EQ_NAMES[x["type"]], freq=x["freq_hz"], gain=x["gain_db"], q=x["q"])
                         for x in dev["bands"]])
                done.append(f"ReaEQ ({len(dev['bands'])} bands)")
            elif dev["device"] == "Compressor":
                fx = b.add(REACOMP)
                b.shown(fx, "Threshold", dev["threshold_db"])
                b.shown(fx, "Ratio", dev["ratio"])
                b.shown(fx, "Attack", dev["attack_ms"])
                b.shown(fx, "Release", dev["release_ms"])
                b.shown(fx, "Knee", dev.get("knee_db", 6))
                done.append(f"ReaComp {dev['ratio']}:1 @ {dev['threshold_db']} dB")
            elif dev["device"] == "Utility" and not dry:
                r.set_track(tid, volume_db=dev["gain_db"])
                done.append(f"fader {dev['gain_db']:+.1f} dB")
        if not dry and isinstance(t["pan"], (int, float)):
            r.set_track(tid, pan=t["pan"])
        if t.get("send_a_db") is not None:
            b.notes.append(f"reverb send {t['send_a_db']} dB: add a send to your reverb track by hand")
        out.append(f"- {t['stem']}: " + ", ".join(done) + (f"; pan {t['pan']}" if isinstance(t["pan"], (int, float)) else "")
                   + "".join(f"\n  ! {n}" for n in b.notes))
    return out
