#!/usr/bin/env python3
"""Build a mastering chain or channel strips in your Live set from Live's own devices: no paid plug-ins.
With --reaper, the same chain in the REAPER that is open, from REAPER's stock plug-ins (see chain_reaper.py).

  master   Analyses a bounce of your mix with `hypnomix master`, then builds the same chain on the Main
           track from stock devices and dials in every value:
               EQ Eight (sub clean-up + reference tone)  →  Glue Compressor  →  Utility (bass mono, width)
               →  Saturator (optional warmth)  →  Limiter (gain to the LUFS target, codec-safe ceiling)
           With --verify (needs BlackHole) it then records the loudest bars from Live, measures them, and
           trims the Limiter's gain until Live's output lands on the target.

  strips   Builds a channel strip on every track from an automix recipe.json: EQ Eight, Compressor,
           Utility (gain), plus pan and send A, matching stems to tracks by name.

Usage:
    hypnomix chain master BOUNCE.wav [--target -14] [--reference ref.wav] [--warmth 0.3] [--verify]
                         [--existing bypass|keep] [--dry-run]
    hypnomix chain strips recipe.json [--dry-run]
    hypnomix chain master BOUNCE.wav --reaper [--verify]   (and `strips … --reaper`)

The bounce must start at bar 1 of the set (export the whole song). Existing devices on Main are never
deleted: with --existing bypass they are switched off (a third-party limiter, for example), with keep the new chain goes after them.
Take a snapshot or save a copy of the set first; hypnomix changes devices in the open set.
"""
import argparse, sys, time
from pathlib import Path

import numpy as np

from hypnomix.core import dsp

EQ_TYPES = {"lowcut48": 0, "lowcut12": 1, "lowshelf": 2, "bell": 3, "notch": 4, "highshelf": 5, "highcut12": 6, "highcut48": 7}
GLUE_RATIOS = [2, 4, 10]
GLUE_ATTACKS = [0.01, 0.1, 0.3, 1, 3, 10, 30]
GLUE_RELEASES = [0.1, 0.2, 0.4, 0.6, 0.8, 1.2]


# ---------------------------------------------------------------- plan (pure, testable without Live)
def eq_from_curve(f, curve, max_bands=6):
    """Fit a smooth correction curve with a low shelf, up to four bells and a high shelf (EQ Eight bands 2–7)."""
    at = lambda hz: float(np.interp(hz, f, curve))
    bands = []
    lo, hi = at(70), at(12000)
    if abs(lo) >= 0.4:
        bands.append(dict(type="lowshelf", freq=90, gain=round(lo, 1), q=0.71))
    for hz, q in ((220, 0.9), (550, 0.9), (1400, 0.9), (3500, 0.9)):
        g = at(hz) - (lo if hz < 400 else 0) * 0.5 - (hi if hz > 2500 else 0) * 0.5
        if abs(g) >= 0.4:
            bands.append(dict(type="bell", freq=hz, gain=round(g, 1), q=q))
    if abs(hi) >= 0.4:
        bands.append(dict(type="highshelf", freq=9000, gain=round(hi, 1), q=0.71))
    return bands[:max_bands]


def plan_master(bounce, target=-14.0, ceiling=-1.0, reference=None, match=0.6, warmth=0.0, width=1.0):
    from hypnomix.engineer import master as mastering
    y, sr = dsp.load(bounce)
    out, before, after, log = mastering.master(y, sr, target, ceiling, reference, match, 1.5, warmth, width)
    st = after["settings"]
    plan = []
    eq = [dict(type="lowcut12", freq=st["hpf_hz"], gain=0, q=0.71)]
    if "eq_curve" in st:
        eq += eq_from_curve(*st["eq_curve"])
    plan.append(dict(device="EQ Eight", bands=eq, why="sub clean-up" + (" + tone toward the reference" if len(eq) > 1 else "")))
    if "glue" in st:
        # Glue Compressor's gentlest ratio is 2:1: find the threshold for the same gain reduction at 2:1
        y2 = dsp.filt(dsp.stereo(y), dsp.highpass(22, sr, 2))
        th = dsp.threshold_for_gr(y2, sr, st["glue"]["target_gr_db"], 2.0, 30, 200, 6, detector="rms")
        plan.append(dict(device="Glue Compressor", threshold_db=round(th, 1), ratio=2, attack_ms=30, release_s=0.2,
                         makeup_db=0.0, why=f"glue, about {st['glue']['target_gr_db']} dB of gain reduction"))
    if st.get("bass_mono_hz") or st.get("width", 1.0) != 1.0:
        plan.append(dict(device="Utility", bass_mono_hz=st.get("bass_mono_hz"), width_pct=round(st.get("width", 1.0) * 100),
                         why="mono low end below 120 Hz" if st.get("bass_mono_hz") else "stereo width"))
    if "saturation" in st:
        plan.append(dict(device="Saturator", drive_db=round(st["saturation"]["drive_db"], 1), dry_wet_pct=35,
                         why="gentle harmonics for small speakers"))
    lim = st["limiter"]
    plan.append(dict(device="Limiter", gain_db=round(lim["gain_db"], 1), ceiling_db=lim["ceiling_dbtp"], release_ms=lim["release_ms"],
                     why=f"loudness to {target} LUFS, codec-safe ceiling"))
    return plan, dict(target=target, offline=after, sr=sr, master_audio=out)


# ---------------------------------------------------------------- build in Live
class Builder:
    def __init__(self, live, track, dry=False):
        self.live, self.track, self.dry, self.notes = live, track, dry, []

    def device(self, name):
        if self.dry:
            return None
        return self.live.load_stock_device(self.track, name)

    def disp(self, did, cands, value, label=None):
        if self.dry:
            return
        p = self.live.find_param(self.track, did, cands)
        if not p:
            self.notes.append(f"{label or cands[0]}: not found on this Live version (set it by hand: {value})")
            return
        v = self.live.set_param_display(self.track, did, p["id"], value)
        return v[1]

    def raw(self, did, cands, value, label=None):
        if self.dry:
            return
        p = self.live.find_param(self.track, did, cands)
        if not p:
            self.notes.append(f"{label or cands[0]}: not found on this Live version")
            return
        return self.live.set_param(self.track, did, p["id"], value)[1]

    def eq_eight(self, bands):
        did = self.device("EQ Eight")
        for i, b in enumerate(bands[:8], 1):
            self.raw(did, [f"{i} Filter On A"], 1)
            self.raw(did, [f"{i} Filter Type A"], EQ_TYPES[b["type"]])
            self.disp(did, [f"{i} Frequency A"], b["freq"])
            if b["type"] in ("bell", "lowshelf", "highshelf"):
                self.raw(did, [f"{i} Gain A"], b["gain"])
            self.disp(did, [f"{i} Q A"], b["q"])
        for i in range(len(bands) + 1, 9):                    # the default EQ Eight has some bands on: switch them off
            self.raw(did, [f"{i} Filter On A"], 0)
        return did


def build_master(live, plan, existing="bypass", dry=False):
    tid = -1
    have = live.devices(tid) if not dry else []
    if have and not dry:
        if existing == "bypass":
            for i, n in enumerate(have):
                p = live.find_param(tid, i, ["Device On"])
                if p:
                    live.set_param(tid, i, p["id"], 0)
        elif existing != "keep":
            sys.exit(f"Main already has devices {have}; use --existing bypass or --existing keep")
    b = Builder(live, tid, dry)
    rows = []
    for step in plan:
        d = step["device"]
        if d == "EQ Eight":
            b.eq_eight(step["bands"])
            rows.append((d, "; ".join(f"{x['type']} {x['freq']:g} Hz" + (f" {x['gain']:+.1f} dB" if x["type"] in ("bell", "lowshelf", "highshelf") else "")
                                      for x in step["bands"]), step["why"]))
        elif d == "Glue Compressor":
            did = b.device(d)
            b.disp(did, ["Threshold"], step["threshold_db"])
            b.disp(did, ["Ratio"], step["ratio"])
            b.disp(did, ["Attack"], step["attack_ms"])
            b.disp(did, ["Release"], step["release_s"] * 1000)          # Live shows seconds; hypnomix compares in ms
            b.disp(did, ["Makeup"], step["makeup_db"])
            rows.append((d, f"threshold {step['threshold_db']} dB, ratio {step['ratio']}:1, attack {step['attack_ms']} ms, "
                            f"release {step['release_s']} s", step["why"]))
        elif d == "Utility":
            did = b.device(d)
            if step.get("bass_mono_hz"):
                b.raw(did, ["Bass Mono"], 1)
                b.disp(did, ["Bass Freq", "Bass Mono Freq", "Bass Frequency"], step["bass_mono_hz"], "Bass Mono frequency")
            if step.get("width_pct", 100) != 100:
                b.disp(did, ["Stereo Width", "Width"], step["width_pct"])
            rows.append((d, (f"bass mono below {step['bass_mono_hz']} Hz" if step.get("bass_mono_hz") else "") +
                            (f", width {step['width_pct']}%" if step.get("width_pct", 100) != 100 else ""), step["why"]))
        elif d == "Saturator":
            did = b.device(d)
            b.disp(did, ["Drive"], step["drive_db"])
            b.disp(did, ["Dry/Wet"], step["dry_wet_pct"])
            b.disp(did, ["Output"], -step["drive_db"] * 0.6)
            rows.append((d, f"drive {step['drive_db']} dB, {step['dry_wet_pct']}% wet", step["why"]))
        elif d == "Limiter":
            did = b.device(d)
            b.disp(did, ["Gain", "Input Gain"], step["gain_db"], "Limiter gain")
            b.disp(did, ["Ceiling"], step["ceiling_db"])
            if not dry and live.find_param(tid, did, ["True Peak"]):
                b.raw(did, ["True Peak"], 1)
            rows.append((d, f"gain +{step['gain_db']} dB, ceiling {step['ceiling_db']} dB", step["why"]))
            step["_did"] = did
    return rows, b.notes


def loudest_bars(audio, sr, tempo, bpb, bars=8):
    m = audio.mean(axis=1) if audio.ndim == 2 else audio
    bar_s = bpb * 60 / tempo
    rms = np.convolve(m ** 2, np.ones(int(sr)) / sr, "valid")[:: int(sr)]
    k = max(1, int(bars * bar_s))
    best = int(np.argmax(np.convolve(rms, np.ones(k), "valid"))) if len(rms) > k else 0
    return int(best / bar_s) + 1


def verify(live, plan, ctx, bars=8, rounds=2):
    """Record the loudest bars from Live and nudge the Limiter gain until they match the offline master's loudness."""
    from hypnomix.live.loop import record as rec_start
    import tempfile, soundfile as sf
    tempo, bpb = live.tempo(), live.beats_per_bar()
    bar = loudest_bars(ctx["master_audio"], ctx["sr"], tempo, bpb, bars)
    secs = bars * bpb * 60 / tempo
    a = int((bar - 1) * bpb * 60 / tempo * ctx["sr"])
    want = dsp.lufs(ctx["master_audio"][a:a + int(secs * ctx["sr"])], ctx["sr"])
    lim = next(s for s in plan if s["device"] == "Limiter")
    did = lim["_did"]
    p = live.find_param(-1, did, ["Gain", "Input Gain"])
    lines = [f"Calibrating on bars {bar}–{bar + bars - 1}: the offline master measures {want:.1f} LUFS there."]
    gain = lim["gain_db"]
    for r in range(rounds):
        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "cap.wav"
            live.stop(); time.sleep(0.3)
            rc = rec_start(secs + 3, wav)
            time.sleep(0.3)
            live.play_from(bar)
            rc.wait(); live.stop()
            y, sr = sf.read(str(wav), always_2d=True)
            on = np.flatnonzero(np.abs(y).max(axis=1) > 1e-3)
            if not len(on):
                lines.append("Nothing was recorded: is Live's output the Multi-Output Device with BlackHole?")
                return lines
            y = y[on[0]: on[0] + int(secs * sr)]
            got = dsp.lufs(y, sr)
            tp = dsp.true_peak(y, sr)
        d = want - got
        lines.append(f"  pass {r + 1}: Live plays {got:.1f} LUFS (true peak {tp:+.1f} dBTP), {d:+.1f} LU from target")
        if abs(d) < 0.3 or not p:
            break
        gain += d
        live.set_param_display(-1, did, p["id"], gain)
    lines.append(f"Limiter gain set to {gain:+.1f} dB.")
    return lines


# ---------------------------------------------------------------- strips from an automix recipe
def build_strips(live, recipe, dry=False):
    import re, json
    r = json.loads(Path(recipe).read_text())
    names = {re.sub(r"^\d+\s*", "", n).lower(): tid for tid, n in live.tracks() if tid >= 0} if not dry else {}
    out = []
    for t in r["tracks"]:
        key = re.sub(r"^\d+\s*", "", t["stem"]).lower()
        tid = names.get(key) if not dry else 0
        if tid is None:
            hits = [v for k, v in names.items() if key in k or k in key]
            tid = hits[0] if len(hits) == 1 else None
        if tid is None:
            out.append(f"- {t['stem']}: no track with that name in the set (name the track after the stem)")
            continue
        b = Builder(live, tid, dry)
        done = []
        for dev in t["live_devices"]:
            if dev["device"] == "EQ Eight" and dev["bands"]:
                kind = {"Low Cut 12": "lowcut12", "High Cut 12": "highcut12", "Bell": "bell", "Low Shelf": "lowshelf",
                        "High Shelf": "highshelf", "Notch": "notch"}
                b.eq_eight([dict(type=kind[x["type"]], freq=x["freq_hz"], gain=x["gain_db"], q=x["q"]) for x in dev["bands"]])
                done.append(f"EQ Eight ({len(dev['bands'])} bands)")
            elif dev["device"] == "Compressor":
                did = b.device("Compressor")
                b.disp(did, ["Threshold"], dev["threshold_db"])
                b.disp(did, ["Ratio"], dev["ratio"])
                b.disp(did, ["Attack"], dev["attack_ms"])
                b.disp(did, ["Release"], dev["release_ms"])
                b.raw(did, ["Knee"], dev.get("knee_db", 6))
                done.append(f"Compressor {dev['ratio']}:1 @ {dev['threshold_db']} dB")
            elif dev["device"] == "Utility":
                did = b.device("Utility")
                b.disp(did, ["Gain"], dev["gain_db"])
                done.append(f"Utility {dev['gain_db']:+.1f} dB")
        if not dry:
            if isinstance(t["pan"], (int, float)):
                live.set_pan(tid, t["pan"])
            if t.get("send_a_db") is not None:
                try:
                    live.set_send_db(tid, 0, t["send_a_db"])
                except Exception as e:
                    b.notes.append(f"send A: {e}")
        out.append(f"- {t['stem']}: " + ", ".join(done) + (f"; pan {t['pan']}" if isinstance(t["pan"], (int, float)) else "")
                   + (f"; send A {t['send_a_db']} dB" if t.get("send_a_db") is not None else "")
                   + ("".join(f"\n  ! {n}" for n in b.notes)))
    return out


def main():
    ap = argparse.ArgumentParser(prog="hypnomix chain", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("master"); m.add_argument("bounce")
    m.add_argument("--target", type=float, default=-14.0); m.add_argument("--ceiling", type=float, default=-1.0)
    m.add_argument("--reference"); m.add_argument("--match", type=float, default=0.6)
    m.add_argument("--warmth", type=float, default=0.0); m.add_argument("--width", type=float, default=1.0)
    m.add_argument("--existing", choices=["bypass", "keep", "refuse"], default="refuse")
    m.add_argument("--verify", action="store_true"); m.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("strips"); s.add_argument("recipe"); s.add_argument("--dry-run", action="store_true")
    for p_ in (m, s):
        p_.add_argument("--reaper", action="store_true", help="build it in the REAPER that is open (stock ReaEQ, "
                        "ReaComp, ReaLimit and JS plug-ins) instead of Live")
    a = ap.parse_args()

    if a.reaper:
        return main_reaper(a)
    live = None
    if not a.dry_run:
        from hypnomix.live.osc import Live
        live = Live(timeout=4.0)
        if not live.ping():
            sys.exit("Live isn't answering. Run: hypnomix doctor")
        snap = live.snapshot()
        from hypnomix.core.paths import out
        import json
        sp = out("snapshots") / f"before-chain-{time.strftime('%Y%m%d-%H%M%S')}.json"
        sp.write_text(json.dumps(snap, indent=1))
        print(f"mixer snapshot saved: {sp}", file=sys.stderr)

    if a.cmd == "master":
        print(f"analysing {Path(a.bounce).name} …", file=sys.stderr)
        plan, ctx = plan_master(a.bounce, a.target, a.ceiling, a.reference, a.match, a.warmth, a.width)
        rows, notes = build_master(live, plan, a.existing, a.dry_run)
        md = [f"# Mastering chain on Main{' (plan only)' if a.dry_run else ''}", "",
              "| device | settings | why |", "|---|---|---|", *[f"| {d} | {s} | {w} |" for d, s, w in rows]]
        if notes:
            md += ["", "Set by hand:", *[f"- {n}" for n in notes]]
        if a.verify and not a.dry_run:
            md += ["", *verify(live, plan, ctx)]
        elif not a.dry_run:
            md += ["", "Run with --verify to measure Live's output and fine-tune the Limiter gain (needs BlackHole)."]
        print("\n".join(md))
    else:
        print("\n".join(build_strips(live, a.recipe, a.dry_run)))
    if live:
        live.close()


def main_reaper(a):
    from hypnomix.engineer import chain_reaper as CR
    from hypnomix.reaper.client import Reaper, ReaperError
    r = None
    if not a.dry_run:
        r = Reaper()
        try:
            r.start()
            info = r.ping()
        except ReaperError as e:
            sys.exit(str(e))
        print(f"REAPER {info['reaper']}: {info['project'] or '(unsaved project)'}. Every change is an undo step "
              "(Edit > Undo).", file=sys.stderr)
    if a.cmd == "master":
        print(f"analysing {Path(a.bounce).name} …", file=sys.stderr)
        plan, ctx = plan_master(a.bounce, a.target, a.ceiling, a.reference, a.match, a.warmth, a.width)
        rows, notes = CR.build_master(r, plan, a.existing, a.dry_run)
        md = [f"# Mastering chain on REAPER's master{' (plan only)' if a.dry_run else ''}", "",
              "| plug-in | settings | why |", "|---|---|---|", *[f"| {d} | {s_} | {w} |" for d, s_, w in rows]]
        if notes:
            md += ["", "Set by hand:", *[f"- {n}" for n in notes]]
        if a.verify and not a.dry_run:
            md += ["", *CR.verify(r, plan, ctx)]
        elif not a.dry_run:
            md += ["", "Run with --verify: REAPER renders the loudest bars, and ReaLimit is trimmed to the target."]
        print("\n".join(md))
    else:
        print("\n".join(CR.build_strips(r, a.recipe, a.dry_run)))


if __name__ == "__main__":
    main()
