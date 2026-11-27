#!/usr/bin/env python3
"""Your mix engineer: turn a folder of unmixed stems into a balanced mix and a master, and explain
every decision so you can learn from it or redo it by hand in Live.

First the prep pass (`hypnomix prep`): clicks, clipping, plosives, breaths, noise, silence, fades.
Then, per stem:
  1. works out what it is (name first, then the sound): lead vocal, kick, bass, guitar, …
  2. clean-up EQ: high-pass where the part has nothing useful, cuts ringing resonances, mud and harshness
  3. tone EQ: the classic role moves (kick weight, vocal air, bass definition) only where the audio needs them
  4. compression set by gain reduction, not by a fixed threshold; de-essing on vocals
  5. level, by loudness while the part plays, against a role-based balance (lead vocal on top)
  6. panning: low end and lead in the centre, doubles and pairs spread, stereo stems kept
  7. a shared plate reverb with role-based sends; a glued drum bus
Then it finds frequency fights between stems (see `hypnomix masking`), carves the less important part,
and masters the result (see `hypnomix master`).

Usage:
    hypnomix automix STEMS_DIR --plan [SCAN_DIR]   change nothing: every move becomes a finding to review
    hypnomix automix STEMS_DIR [--name Song] [--target -14] [--reference ref.wav] [--no-master]
                    [--stems-out] [--dry] [--out DIR]

Writes <Song> (automix).wav, <Song> (master).wav, MIX NOTES.md and recipe.json (the same settings in
EQ Eight / Compressor / Utility terms, so Claude can rebuild the mix in Live with the Ableton MCP), into
hypnomix-out/automix/<Song>, or "<Song> (2)", "(3)" ... when that folder already holds an earlier run. Nothing earlier
is overwritten: an --out folder that already holds an earlier automix (any name) is refused (exit code 2).
"""
from hypnomix.core.paths import out_at
from hypnomix.core import args as A
import argparse, json, sys, time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.core.paths import out as out_dir
from hypnomix.engineer import roles, masking
from hypnomix.engineer import master as mastering

DRUM_ROLES = {"kick", "snare", "hats", "toms", "overheads", "drums"}
ANCHOR_LUFS = -20.0             # where the most important part sits before the master


# ---------------------------------------------------------------- analysis helpers
def smooth_spectrum(y, sr, n=16384, segments=8):
    """Average spectrum while the stem plays, plus per-segment spectra (to tell resonances from notes)."""
    m = y.mean(axis=1)
    if len(m) < n:
        m = np.pad(m, (0, n - len(m)))
    b = dsp.block_rms_db(y, sr, n / sr / 2)
    fr = np.lib.stride_tricks.sliding_window_view(m, n)[:: n // 2]
    keep = b[: len(fr)] > b.max() - 30                       # only where the stem is playing
    fr = fr[keep[: len(fr)]] if keep[: len(fr)].any() else fr
    S = np.abs(np.fft.rfft(fr * np.hanning(n), axis=1)) ** 2
    f = np.fft.rfftfreq(n, 1 / sr)
    P = 10 * np.log10(S.mean(axis=0) + 1e-20)
    segs = [10 * np.log10(c.mean(axis=0) + 1e-20) for c in np.array_split(S, min(segments, len(S))) if len(c)]
    return f, P, segs


def octave_smooth(f, P, frac):
    lf = np.log2(np.maximum(f, 1))
    out = np.empty_like(P)
    c = np.cumsum(np.concatenate([[0], 10 ** (P / 10)]))
    for i in range(len(f)):
        lo, hi = np.searchsorted(lf, lf[i] - frac / 2), np.searchsorted(lf, lf[i] + frac / 2)
        hi = max(hi, lo + 1)
        out[i] = 10 * np.log10((c[hi] - c[lo]) / (hi - lo) + 1e-20)
    return out


def band_db(f, P, lo, hi):
    m = (f >= lo) & (f < hi)
    return 10 * np.log10(np.sum(10 ** (P[m] / 10)) + 1e-20)


def resonances(f, P, segs, lo=150, hi=8000, min_excess=6.0, max_n=2):
    """Narrow peaks that stand out in (nearly) every part of the song: rooms, rings, a cheap mic.
    A peak that only shows up in some segments is a note being played, not a resonance."""
    def excess(Q):
        return octave_smooth(f, Q, 1 / 12) - octave_smooth(f, Q, 1.0)
    ex = excess(P)
    per = np.array([excess(q) for q in segs]) if len(segs) >= 3 else ex[None, :]
    steady = np.percentile(per, 25, axis=0)                  # must hold in 3 out of 4 segments
    m = (f >= lo) & (f <= hi)
    found = []
    idx = np.flatnonzero(m)
    order = idx[np.argsort(-np.minimum(ex[idx], steady[idx]))]
    for i in order:
        v = min(ex[i], steady[i])
        if v < min_excess or len(found) >= max_n:
            break
        if all(abs(np.log2(f[i] / g)) > 1 / 3 for g, _ in found):
            found.append((float(f[i]), float(v)))
    return found


# ---------------------------------------------------------------- per-stem engineer
def eq_for(role, f, P, segs, sr):
    eq, p = dsp.EQ(), roles.preset(role)
    if p["hpf"] and role not in ("drums",):
        eq.add("highpass", p["hpf"], why=f"nothing useful below {p['hpf']} Hz on this {role.replace('_', ' ').replace('other', 'part')}; "
                                          "removing it clears room for kick and bass")
    lowmid = band_db(f, P, 200, 500) - band_db(f, P, 500, 4000)
    harsh = band_db(f, P, 2500, 5000) - band_db(f, P, 1000, 2500)
    air = band_db(f, P, 8000, 16000) - band_db(f, P, 2000, 5000)
    if role in ("lead_vocal", "backing_vocal", "guitar", "keys", "strings", "snare", "toms", "overheads", "synth", "brass", "other") and lowmid > 3:
        g = -min(4.0, 1.0 + (lowmid - 3) * 0.5)
        eq.add("bell", 300, g, 1.0, why=f"200–500 Hz sits {lowmid:.1f} dB above its mids: that's the 'mud' or "
                                         "'cardboard' region; a wide cut opens the part up")
    for hz, ex in resonances(f, P, segs, 150, 8000 if role not in ("hats",) else 12000):
        eq.add("bell", hz, -min(4.0, ex - 3), 4.0, why=f"a narrow ring {ex:.1f} dB above its neighbours at {hz:.0f} Hz "
                                                       "(room mode, drum ring or a harsh note); narrow cuts remove it without dulling the part")
    if role in ("lead_vocal", "backing_vocal", "guitar", "strings", "synth", "brass", "overheads") and harsh > 1.5:
        eq.add("bell", 3500, -min(3.0, harsh - 0.5), 2.0, why=f"2.5–5 kHz is {harsh:.1f} dB hot against 1–2.5 kHz: "
                                                             "the ear is most sensitive here, so it reads as harsh")
    if role == "lead_vocal":
        if air < -14:
            eq.add("highshelf", 10000, 2.0, why="little air above 8 kHz: a gentle shelf brings the voice forward "
                                                "without making it louder")
        if harsh < -2:
            eq.add("bell", 3000, 1.5, 1.2, why="presence (3 kHz) is low; a small lift helps the words cut through")
    if role == "kick":
        if band_db(f, P, 40, 90) - band_db(f, P, 90, 250) < 2:
            eq.add("bell", 60, 2.5, 1.2, why="adds weight at 60 Hz, the 'thump' you feel")
        if band_db(f, P, 300, 500) - band_db(f, P, 60, 250) > -12:
            eq.add("bell", 380, -3.0, 1.6, why="350–400 Hz is the boxy 'cardboard' part of a kick")
        eq.add("bell", 4000, 2.0, 1.5, why="a little 3–5 kHz click lets the kick be heard on phones")
    if role == "bass" and band_db(f, P, 600, 1500) - band_db(f, P, 60, 250) < -18:
        eq.add("bell", 800, 2.5, 1.0, why="bass harmonics around 800 Hz make the bass line audible on small speakers")
    if role == "snare" and band_db(f, P, 150, 250) - band_db(f, P, 1000, 4000) < -6:
        eq.add("bell", 200, 2.0, 1.4, why="the snare's body lives around 200 Hz; this gives it some weight")
    if role in ("hats", "overheads") and band_db(f, P, 8000, 14000) - band_db(f, P, 2000, 5000) < -6:
        eq.add("highshelf", 9000, 1.5, why="a little sheen on cymbals")
    if role == "pad":
        eq.add("bell", 2500, -2.0, 0.8, why="pads fill the 2–3 kHz range the vocal needs; tuck them under it")
    return eq


def is_mono(y):
    return y.shape[1] == 1 or dsp.correlation(y) > 0.995


def process_stem(name, y, sr, role, log, allow=None):
    """allow: the approved move keys of a plan ("eq:<stem>", "comp:<stem>", "deess:<stem>" …); None = every move."""
    ok = lambda k: allow is None or f"{k}:{name}" in allow
    p = roles.preset(role)
    steps = []
    f, P, segs = smooth_spectrum(y, sr)
    eq = eq_for(role, f, P, segs, sr)
    if ok("eq"):
        y = eq.apply(y, sr)
        for b in eq.bands:
            steps.append(("EQ", b))
    comp = None
    if p["comp"] and ok("comp"):
        ratio, gr, att, rel = p["comp"]
        th = dsp.threshold_for_gr(y, sr, gr, ratio, att, rel)
        y, g = dsp.compress(y, sr, th, ratio, att, rel, 6)
        play = np.max(np.abs(y), axis=1) > dsp.undb(dsp.sample_peak(y) - 40)
        avg = float(-np.mean(g[play])) if play.any() else 0
        comp = dict(threshold=round(th, 1), ratio=ratio, attack=att, release=rel, avg_gr=round(avg, 1), max_gr=round(float(-g.min()), 1))
        steps.append(("Compressor", dict(**comp, why=_comp_why(role, ratio, att))))
    if role in ("lead_vocal", "backing_vocal") and ok("deess"):
        sc = dsp.filt(y, dsp.butter(4, [5000, min(10000, sr * 0.45)], "bandpass", fs=sr, output="sos"))
        lvl = dsp.db(np.max(np.abs(sc), axis=1))
        th = float(np.percentile(lvl[lvl > lvl.max() - 40], 97)) - 4
        y, g = dsp.deess(y, sr, 6500, th, 4, 8)
        steps.append(("De-esser", dict(freq=6500, threshold=round(th, 1), max_gr=round(float(-g.min()), 1),
                                       why="tames 's' and 't' peaks that compression and air EQ make louder")))
    log[name] = dict(role=role, steps=steps)
    return y


def _comp_why(role, ratio, att):
    return {
        "lead_vocal": "evens out loud and quiet words so the vocal sits on top of the mix the whole song",
        "backing_vocal": "holds the backing vocals steady so they support rather than poke out",
        "kick": f"{att} ms attack lets the beater click through, then the body is controlled: punch with consistency",
        "snare": "a medium attack keeps the crack and evens the hits",
        "bass": "bass notes vary a lot in level by string and fret; compression keeps the low end solid",
        "drums": "light bus-style compression holds the kit together",
    }.get(role, f"gentle {ratio}:1 to keep the part steady in the mix")


# ---------------------------------------------------------------- the mix
def plan_pans(items):
    """items: [(name, role, mono)] -> {name: pan}. Spread same-role mono parts alternately."""
    counts = Counter(r for _, r, m in items if m)
    seen = defaultdict(int)
    pans = {}
    for name, role, mono in items:
        base = roles.preset(role)["pan"]
        if not mono:
            pans[name] = 0.0
            continue
        side = roles.side_from_name(name)
        if role in ("overheads",) and side:
            pans[name] = 0.85 * side
        elif side:
            pans[name] = max(base, 0.5) * side
        elif base == 0:
            pans[name] = 0.0
        else:
            k = seen[role]; seen[role] += 1
            sign = -1 if k % 2 == 0 else 1
            spread = base if counts[role] > 1 else base * 0.5
            pans[name] = sign * spread * (1 - 0.25 * (k // 2))
    return pans


def automix(folder, name=None, target=-14.0, reference=None, do_master=True, stems_out=False, outdir=None, prep_first=True,
            allow=None):
    """allow: a set of approved move keys (see `plan_findings`); only those moves are made. None = every move."""
    t0 = time.time()
    ok = lambda key: allow is None or key in allow
    if not outdir:                              # the default place: a new numbered folder, never over an earlier run
        from hypnomix.core import paths as _paths
        name = name or Path(folder).resolve().name
        base = _paths.OUT / "automix" / name
        cand, k = base, 1
        while cand.exists() and any(cand.iterdir()):
            k += 1
            cand = base.with_name(f"{base.name} ({k})")
        outdir = str(cand)
    if prep_first:
        from hypnomix.studio.prep import prep
        pod = (out_at(outdir, "automix", name or Path(folder).resolve().name)) / "prepped stems"
        print("prep pass (clicks, clipping, plosives, breaths, noise, silence, fades) …", file=sys.stderr)
        name = name or Path(folder).resolve().name
        folder, _, _ = prep(folder, pod)
    stems, sr = masking.load_stems(folder)
    if not stems:
        sys.exit(f"no audio files in {folder}")
    name = name or Path(folder).resolve().name
    od = out_at(outdir, "automix", name)
    od.mkdir(parents=True, exist_ok=True)
    print(f"{len(stems)} stems at {sr} Hz → {od}", file=sys.stderr)

    log, role_of, how = {}, {}, {}
    for n, (r, h) in roles.classify_all(stems, sr).items():
        role_of[n], how[n] = r, h
    has_vocal = any(r == "lead_vocal" for r in role_of.values())
    anchor_role = "lead_vocal" if has_vocal else max(role_of.values(), key=lambda r: roles.preset(r)["prio"])
    anchor_level = roles.preset(anchor_role)["level"]

    processed = {}
    for n, y in stems:
        print(f"  {n:<28} {role_of[n]:<14} (by {how[n]})", file=sys.stderr)
        processed[n] = process_stem(n, y, sr, role_of[n], log, allow)

    # level: loudness while playing, against the role balance
    for n, y in processed.items():
        want = ANCHOR_LUFS + roles.preset(role_of[n])["level"] - anchor_level
        have = dsp.active_lufs(y, sr)
        gain = float(np.clip(want - have, -40, 30)) if ok(f"level:{n}") else 0.0
        processed[n] = y * dsp.undb(gain)
        log[n]["gain_db"] = round(gain, 1)
        log[n]["level"] = dict(target_lufs_while_playing=round(want, 1), measured=round(have, 1))

    # pan
    pans = plan_pans([(n, role_of[n], is_mono(y)) for n, y in processed.items()])
    pans = {n: (v if ok(f"pan:{n}") else 0.0) for n, v in pans.items()}
    placed = {}
    for n, y in processed.items():
        mono = is_mono(y)
        z = y[:, :1] if mono and y.shape[1] > 1 else y
        z = dsp.pan(z, pans[n]) if mono else dsp.stereo(z)
        if role_of[n] in ("bass", "kick") and not mono:
            z = dsp.mono_below(z, sr, 150)
        placed[n] = z
        log[n]["pan"] = round(pans[n], 2) if mono else "stereo (kept)"

    # masking: carve the less important part of the worst fights
    collisions, _ = masking.analyse(list(placed.items()), sr, role_of)
    fixed = []
    done = set()
    for c in collisions:
        key = (c["give"], c["band"])
        if key in done or len(fixed) >= 5 or c["band"] == 0 or role_of[c["give"]] == "lead_vocal" \
                or sum(1 for x in fixed if x["give"] == c["give"]) >= 2 or not ok(f"mask:{c['give']}:{c['band']}"):
            continue
        done.add(key)
        cut = -2.0 if c["frac"] < 0.5 else -3.0
        q = 1.4 if c["band"] >= 2 else 1.0
        placed[c["give"]] = dsp.filt(placed[c["give"]], dsp.peaking(c["center"], cut, q, sr))
        b = dict(kind="bell", freq=round(c["center"], 1), gain=cut, q=q, mask_band=c["band"],
                 why=f"masking fix: makes room for {c['keep']} in {c['band_name']} (they collided {int(c['frac'] * 100)}% of the time both play)")
        log[c["give"]]["steps"].append(("EQ", b))
        fixed.append(c)

    # drum bus glue
    drum_names = [n for n in placed if role_of[n] in DRUM_ROLES]
    bus_note = None
    if len(drum_names) >= 2 and ok("drumbus"):
        bus = sum(placed[n] for n in drum_names)
        th = dsp.threshold_for_gr(bus, sr, 2.0, 2.0, 30, 100)
        bus2, g = dsp.compress(bus, sr, th, 2.0, 30, 100, 6)
        gain_curve = bus2 / np.where(np.abs(bus) < 1e-9, 1, bus)
        for n in drum_names:                                     # apply the bus gain to each member (keeps stems)
            placed[n] = placed[n] * np.clip(gain_curve, 0, 1.5)
        bus_note = dict(members=drum_names, threshold=round(th, 1), ratio=2.0, attack=30, release=100,
                        avg_gr=round(float(-np.mean(g)), 1))

    # reverb sends into one plate
    ir = dsp.reverb_ir(sr, decay_s=1.8, predelay_ms=25, damp_hz=7000)
    send_sum = np.zeros((len(next(iter(placed.values()))), 2))
    for n, z in placed.items():
        s = roles.preset(role_of[n])["reverb"] if ok(f"reverb:{n}") else None
        if s is None:
            log[n]["reverb_send_db"] = None
            continue
        send_sum += z * dsp.undb(s)
        log[n]["reverb_send_db"] = s
    ret = dsp.convolve(send_sum, ir)

    mix = sum(placed.values()) + ret
    # gain-stage the mix for the master: about -18 LUFS, peaks well below 0
    g = -18.0 - dsp.lufs(mix, sr)
    mix *= dsp.undb(g)
    pk = dsp.sample_peak(mix)
    if pk > -3:
        mix *= dsp.undb(-3 - pk)
    files = [dsp.save(od / f"{name} (automix).wav", mix, sr, 24)]
    if stems_out:
        sd = od / "processed stems"
        for n, z in placed.items():
            dsp.save(sd / f"{n}.wav", z * dsp.undb(g), sr, 24)
        files.append(sd)

    master_info = None
    if do_master:
        mlog = []
        out, before, after, mlog = mastering.master(mix, sr, target, -1.0, reference, log=mlog)
        files.append(dsp.save(od / f"{name} (master).wav", out, sr, 24))
        (od / f"{name} (master notes).md").write_text(mastering.notes(name, before, after, mlog, target, files[-1:]), encoding="utf-8")
        master_info = dict(before=before, after=after)

    notes = mix_notes(name, role_of, how, log, pans, fixed, bus_note, master_info, files, time.time() - t0)
    (od / "MIX NOTES.md").write_text(notes, encoding="utf-8")
    (od / "recipe.json").write_text(json.dumps(recipe(name, sr, role_of, log, bus_note), indent=1), encoding="utf-8")
    return od, notes, dict(log=log, role_of=role_of, bus=bus_note, pans=pans)


def mix_notes(name, role_of, how, log, pans, fixed, bus, master_info, files, secs):
    md = [f"# Mix notes: {name}", "",
          f"Automixed {len(role_of)} stems in {secs:.0f} s. Treat this as an engineer's first pass: listen, then "
          "change what your ears disagree with. Every setting is in recipe.json so it can be rebuilt in Live.", "",
          "## Balance", "", "| stem | role | gain | pan | reverb send |", "|---|---|---|---|---|"]
    for n in role_of:
        L = log[n]
        send = "–" if L.get("reverb_send_db") is None else f"{L['reverb_send_db']} dB"
        md.append(f"| {n} | {role_of[n].replace('_', ' ')} ({how[n]}) | {L['gain_db']:+.1f} dB | {L['pan']} | {send} |")
    md += ["", "## What was done to each stem, and why", ""]
    for n in role_of:
        md.append(f"### {n} ({role_of[n].replace('_', ' ')})")
        for kind, s in log[n]["steps"]:
            if kind == "EQ":
                g = f" {s['gain']:+.1f} dB" if s["kind"] not in ("highpass", "lowpass") else ""
                q = f", Q {s['q']}" if s["kind"] == "bell" else ""
                md.append(f"- **EQ {s['kind']}** {s['freq']:.0f} Hz{g}{q}: {s['why']}")
            elif kind == "Compressor":
                md.append(f"- **Compressor** {s['ratio']}:1, attack {s['attack']} ms, release {s['release']} ms, "
                          f"threshold {s['threshold']} dB → avg {s['avg_gr']} dB reduction: {s['why']}")
            elif kind == "De-esser":
                md.append(f"- **De-esser** above {s['freq']} Hz, up to {s['max_gr']} dB: {s['why']}")
        md.append(f"- **Level** {log[n]['gain_db']:+.1f} dB, so it plays at {log[n]['level']['target_lufs_while_playing']} LUFS "
                  "while it's playing (balance by loudness, not by peak)")
        md.append("")
    if fixed:
        md += ["## Frequency fights resolved", ""]
        md += [f"- {c['give']} gave way to {c['keep']} in {c['band_name']}" for c in fixed]
        md.append("")
    if bus:
        md += ["## Drum bus", f"- {', '.join(bus['members'])} glued with 2:1, 30 ms attack, 100 ms release, "
                              f"avg {bus['avg_gr']} dB: the kit moves as one instrument instead of separate mics", ""]
    md += ["## Space", "- One shared plate (1.8 s, 25 ms pre-delay, 180 Hz–7 kHz). One reverb for most parts puts "
           "everything in the same room; the pre-delay keeps the vocal's words clear of the tail.", ""]
    if master_info:
        a = master_info["after"]
        md += ["## Master", f"- {a['lufs']:.1f} LUFS, {a['tp']:.1f} dBTP, limiter avg {a['avg_gr']:.1f} dB. "
                            "See the master notes for the chain.", ""]
    md += ["## Files", *[f"- `{f}`" for f in files], "",
           "## Next", "- Listen on two systems (headphones and a phone).",
           "- `hypnomix masking \"<processed stems>\"` shows what still collides.",
           "- `hypnomix translate` and `hypnomix qc` on the master before release.",
           "- Ask Claude to rebuild this in Live from recipe.json if you want to tweak it with your own plugins."]
    return "\n".join(md) + "\n"


def band_text(b):
    g = f" {b['gain']:+.1f} dB" if b.get("gain") else ""
    return f"{b['kind']} {b['freq']:g} Hz{g}"


def plan_findings(folder, info):
    """One finding per move automix made in its trial run, each with the key that re-applies it."""
    F = []
    src = str(Path(folder).resolve())

    def add(key, kind, stem, problem, fix, sev="low"):
        F.append(dict(kind=kind, severity=sev, track=stem, problem=problem, fix=fix,
                      plan=dict(tool="automix", file=src, key=key)))
    for n, L in info["log"].items():
        role = info["role_of"][n].replace("_", " ")
        eq = [b for k, b in L["steps"] if k == "EQ" and "mask_band" not in b]
        if eq:
            add(f"eq:{n}", "eq", n, f"EQ for a {role}: " + "; ".join(band_text(b) for b in eq),
                "; ".join(dict.fromkeys(b["why"] for b in eq if b.get("why"))) or "tone shaping for this role")
        for b in (b for k, b in L["steps"] if k == "EQ" and "mask_band" in b):
            add(f"mask:{n}:{b['mask_band']}", "masking", n, f"cut {band_text(b)} (Q {b['q']})", b.get("why", ""))
        c = next((x for k, x in L["steps"] if k == "Compressor"), None)
        if c:
            add(f"comp:{n}", "compressor", n, f"compressor {c['ratio']}:1, attack {c['attack']} ms, release "
                f"{c['release']} ms, threshold {c['threshold']} dB: about {c['avg_gr']} dB reduction (max {c['max_gr']})",
                c.get("why", ""))
        d = next((x for k, x in L["steps"] if k == "De-esser"), None)
        if d:
            add(f"deess:{n}", "de-esser", n, f"de-esser around {d['freq']} Hz, up to {d['max_gr']} dB", d.get("why", ""))
        if abs(L.get("gain_db", 0)) >= 0.5:
            lv = L.get("level", {})
            add(f"level:{n}", "level", n, f"level {L['gain_db']:+.1f} dB (it plays at {lv.get('measured')} LUFS; a {role} "
                f"sits at about {lv.get('target_lufs_while_playing')} against the lead part)",
                "a starting balance by role. This is taste: move the fader until it feels right.")
        if isinstance(L.get("pan"), (int, float)) and abs(L["pan"]) > 0.01:
            add(f"pan:{n}", "pan", n, f"pan {abs(L['pan']) * 100:.0f}% {'right' if L['pan'] > 0 else 'left'}",
                "spreads parts that share a register so they stop sitting on top of each other; bass and lead stay centred")
        if L.get("reverb_send_db") is not None:
            add(f"reverb:{n}", "reverb", n, f"send to a shared plate reverb (1.8 s) at {L['reverb_send_db']} dB",
                "one shared room glues the parts into the same space. Taste: skip it for a dry sound.")
    if info.get("bus"):
        b = info["bus"]
        add("drumbus", "drum bus", ", ".join(b["members"]), f"drum bus compression 2:1, attack 30 ms, release 100 ms: "
            f"about {b['avg_gr']} dB", "makes the kit move as one instrument")
    return F


def recipe(name, sr, role_of, log, bus):
    tracks = []
    for n in role_of:
        L = log[n]
        eq = [s for k, s in L["steps"] if k == "EQ"]
        comp = next((s for k, s in L["steps"] if k == "Compressor"), None)
        de = next((s for k, s in L["steps"] if k == "De-esser"), None)
        tracks.append(dict(stem=n, role=role_of[n], live_devices=[
            dict(device="EQ Eight", bands=[dict(type={"highpass": "Low Cut 12", "lowpass": "High Cut 12", "bell": "Bell",
                                                       "lowshelf": "Low Shelf", "highshelf": "High Shelf", "notch": "Notch"}[b["kind"]],
                                                freq_hz=b["freq"], gain_db=b["gain"], q=b["q"]) for b in eq[:8]]),
            *([dict(device="Compressor", threshold_db=comp["threshold"], ratio=comp["ratio"], attack_ms=comp["attack"],
                    release_ms=comp["release"], knee_db=6)] if comp else []),
            *([dict(device="Multiband Dynamics or a de-esser plug-in", band_hz=de["freq"], max_reduction_db=de["max_gr"])] if de else []),
            dict(device="Utility", gain_db=L["gain_db"])],
            pan=L["pan"], send_a_db=L.get("reverb_send_db")))
    return dict(song=name, sample_rate=sr, tracks=tracks,
                returns=[dict(name="A-Plate", device="Hybrid Reverb or Reverb", decay_s=1.8, predelay_ms=25, lowcut_hz=180, highcut_hz=7000)],
                drum_bus=bus, note="Recreate with the Ableton MCP (create tracks, load devices) and `hypnomix live` (exact dB, params).")


def _holds_automix(d):
    """True when this folder already holds an automix's files (any song's mix or master, the notes or the recipe)."""
    if not d.is_dir():
        return False
    return (d / "MIX NOTES.md").exists() or (d / "recipe.json").exists() or any(d.glob("* (automix).wav")) \
        or any(d.glob("* (master).wav"))


def main():
    ap = argparse.ArgumentParser(prog="hypnomix automix", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--name")
    ap.add_argument("--target", type=A.number(-70, 0), default=-14.0, help="loudness to aim for, LUFS (-70 to 0)")
    ap.add_argument("--reference")
    ap.add_argument("--no-master", action="store_true")
    ap.add_argument("--no-prep", action="store_true", help="skip the prep pass (stems are already edited)")
    ap.add_argument("--stems-out", action="store_true", help="also write each processed stem")
    ap.add_argument("--out")
    ap.add_argument("--plan", nargs="?", const=True, metavar="SCAN_DIR",
                    help="change nothing in your files: list every move (EQ, compressor, level, pan, reverb per stem) "
                         "as a finding for review, with a trial mix to listen to")
    ap.add_argument("--only", metavar="KEYS.json", help="a JSON list of approved move keys: make only those moves")
    a = ap.parse_args()
    if a.plan:
        from hypnomix.workflow import plan as PL
        t0 = time.time()
        sd = PL.scan_dir(a.plan, a.folder)
        od, notes, info = automix(a.folder, a.name, a.target, a.reference, False, False, str(sd / "raw" / "automix-plan"), False)
        mixf = next(iter(sorted(od.glob("*(automix).wav"))), None)
        note = [f"automix plan: a trial mix with EVERY move is at {mixf} (listen to it against the stems)",
                "prep is not part of this plan: run `hypnomix prep FOLDER --plan` for the clean-up moves",
                "approved moves are mixed into fixed/automix/ (no master: `hypnomix master --plan` is its own review)"]
        PL.write(sd, "automix", a.folder, plan_findings(a.folder, info), note, time.time() - t0)
        return
    allow = set(json.loads(Path(a.only).read_text(encoding="utf-8", errors="replace"))) if a.only else None
    if a.out and _holds_automix(Path(a.out).expanduser()):
        print(f"{a.out} already holds an earlier automix and nothing is overwritten: choose another folder with --out, "
              "or leave --out off to get a new numbered folder.", file=sys.stderr)
        sys.exit(2)
    od, notes, _ = automix(a.folder, a.name, a.target, a.reference, not a.no_master, a.stems_out, a.out, not a.no_prep,
                           allow)
    print(notes)
    print(f"→ {od}")


if __name__ == "__main__":
    main()
