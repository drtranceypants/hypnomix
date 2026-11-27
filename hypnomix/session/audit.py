#!/usr/bin/env python3
"""Offline mix audit of a Live set (no Live needed): flags chain problems and compares the bounce with
your profile (if you built one). Writes hypnomix-out/audit/<name>.md.

Flags:
  - EQ Eight bands with big moves (|gain| >= 3 dB), shelves set at odd frequencies (high shelf < 1.5 kHz,
    low shelf > 400 Hz), high-pass below 40 Hz on vocals/guitars (does little), bands with gain but turned off
  - limiters/maximizers on groups or tracks (stacked limiting), and how many in total
  - bypassed devices left in chains
  - duplicated dynamics (the same compressor or limiter on a group and on its children)
  - faders above +3 dB, sends at 0 dB
A HypnoMix DAW session (a .ardour file or its folder) gets the same audit from its saved plug-in controls
(`project/ardour.py`): ACE EQ's shelves and bells as EQ Eight's, its High Pass / Low Pass bands, ACE Compressor's
Range, Auto Release and Mix, and Hypnomix Saturator's curve and drive are shown in the chain; a plug-in whose Enable
control is off counts as bypassed; limiters, doubled dynamics on a group bus and its tracks, and faders are flagged
as for a Live set. Sends are not in the shared model, so they are not checked there.

Usage: hypnomix audit SET.als|SESSION.ardour [BOUNCE.wav] [--name NAME]
"""
import argparse, gzip, json, math, re, sys
from hypnomix.core.gz import read_gz
import xml.etree.ElementTree as ET
from pathlib import Path

from hypnomix.core.paths import out as out_dir
TYPES = {0: "LowCut48", 1: "LowCut12", 2: "LowShelf", 3: "Bell", 4: "Notch", 5: "HighShelf", 6: "HighCut12", 7: "HighCut48"}
LIMITERS = ("Limiter", "Maximizer", "LoudMax")
DYNAMICS = ("compressor", "glue", "limiter", "maximizer", "loudmax", "kotelnikov", "channel strip")


def val(n, p, d=None):
    e = n.find(p)
    return e.get("Value") if e is not None and e.get("Value") is not None else d


def dev_name(d):
    if d.tag in ("AuPluginDevice", "PluginDevice", "Vst3PluginDevice", "VstPluginDevice"):
        for p in (".//PluginDesc//Name", ".//PlugName", ".//Name"):
            v = val(d, p)
            if v:
                return re.sub(r"^[^:]{1,30}: ", "", v)          # drop a "Vendor: " prefix
    un = val(d, "./UserName")
    return f"{d.tag}{' [' + un + ']' if un else ''}"


def is_on(d):
    return val(d, "./On/Manual", "true") == "true"


def eq8(d):
    out = []
    for i in range(8):
        b = d.find(f"./Bands.{i}/ParameterA")
        if b is None:
            continue
        on = val(b, "./IsOn/Manual") == "true"
        mode = TYPES.get(int(float(val(b, "./Mode/Manual", 3))), "?")
        f = float(val(b, "./Freq/Manual", 0)); g = float(val(b, "./Gain/Manual", 0)); q = float(val(b, "./Q/Manual", 0.71))
        out.append((i + 1, on, mode, f, g, q))
    return out


VOCAL_GUITAR = ("vox", "vocal", "voc", "lead", "harmony", "choir", "guitar", "gtr")
HP_LOW_HZ = 40.0         # a high pass under this on a vocal or guitar does little (their own lows start higher)


def low_hp_flag(name, freq, where):
    """The flag for a high pass set so low on a vocal or guitar that it does little, else None."""
    low = name.lower()
    if freq < HP_LOW_HZ and any(w in low for w in VOCAL_GUITAR):
        return f"{name}: {where} high pass at {freq:.0f} Hz does little on this part (try 80-100 Hz, by ear)"
    return None


def audit(als):
    if _is_ardour(als):
        return audit_ardour(als)
    r = ET.fromstring(read_gz(als))
    tracks = list(r.find(".//Tracks"))
    master = r.find(".//MainTrack") if r.find(".//MainTrack") is not None else r.find(".//MasterTrack")
    flags, chains, limit_count = [], {}, 0
    ids = {}
    for t in tracks:
        ids[val(t, "./LinkedTrackGroupId", "-1")] = None
    group_of = {}
    for t in tracks:
        group_of[t.get("Id")] = val(t, "./TrackGroupId", "-1")
    name_of = {t.get("Id"): val(t, "./Name/EffectiveName") for t in tracks}
    for t in tracks + [master]:
        name = "Main" if t is master else val(t, "./Name/EffectiveName")
        mixer = t.find("./DeviceChain/Mixer")
        vol = float(val(mixer, "./Volume/Manual", 1)); vdb = 20 * math.log10(vol) if vol > 0 else -99
        muted = val(mixer, "./Speaker/Manual", "true") == "false"
        devs = t.find("./DeviceChain/DeviceChain/Devices")
        chain = []
        for d in (list(devs) if devs is not None else []):
            n = dev_name(d); on = is_on(d); chain.append(n + ("" if on else " (off)"))
            if not on:
                flags.append(f"{name}: bypassed `{n}` left in the chain")
            if on and any(x in n for x in LIMITERS) and t is not master:
                limit_count += 1
                flags.append(f"**{name}**: `{n}` on a {'group' if t.tag == 'GroupTrack' else 'track'}. Limiting before the master limiter (stacked)")
            if d.tag == "Eq8" and on:
                for i, bon, mode, f, g, q in eq8(d):
                    if bon and mode == "HighShelf" and f < 1500 and abs(g) >= 1:
                        flags.append(f"**{name}**: EQ Eight band {i} is a HIGH shelf at {f:.0f} Hz, {g:+.1f} dB. That tilts everything above it. Intended?")
                    if bon and mode == "LowShelf" and f > 400 and abs(g) >= 1:
                        flags.append(f"**{name}**: EQ Eight band {i} is a LOW shelf at {f:.0f} Hz, {g:+.1f} dB")
                    if bon and mode == "Bell" and abs(g) >= 3:
                        flags.append(f"{name}: EQ Eight band {i} bell {f:.0f} Hz {g:+.1f} dB (Q {q:.2f})")
                    if bon and mode in ("LowCut12", "LowCut48") and low_hp_flag(name, f, f"EQ Eight band {i}"):
                        flags.append(low_hp_flag(name, f, f"EQ Eight band {i}"))
        chains[name] = {"type": t.tag.replace("Track", ""), "fader_db": round(vdb, 1), "muted": muted, "chain": chain,
                        "group": name_of.get(group_of.get(t.get("Id"), "-1"))}
        if vdb > 3:
            flags.append(f"{name}: fader at {vdb:+.1f} dB (mix down rather than up)")
        for i, h in enumerate(mixer.findall("./Sends/TrackSendHolder")):
            s = float(val(h, "./Send/Manual", 0))
            if s >= 0.99:
                flags.append(f"{name}: send {chr(65 + i)} at 0 dB (full)")
    # duplicated processors: same plugin on a group and on its child
    for t in tracks:
        g = group_of.get(t.get("Id"))
        if g and g != "-1" and name_of.get(g):
            gc = {c.split(" (")[0] for c in chains[name_of[g]]["chain"]}
            tc = {c.split(" (")[0] for c in chains[name_of[t.get('Id')]]["chain"]}
            dup = [x for x in gc & tc if any(k in x.lower() for k in DYNAMICS)]
            if dup:
                flags.append(f"{name_of[t.get('Id')]} and its group {name_of[g]} both run `{dup[0]}` (double processing)")
    return chains, flags, limit_count


# ------------------------------------------------------------------ HypnoMix DAW sessions
SAT_CURVES = {0: "Soft Sine", 1: "Analog Clip", 2: "Hard Clip"}


def _is_ardour(path):
    pth = Path(path)
    return pth.suffix.lower() == ".ardour" or (pth.is_dir() and any(pth.glob("*.ardour")))


def _p(d, k, default):
    try:
        return float(d.params.get(k, default))
    except (TypeError, ValueError):
        return default


def ardour_on(d):
    """Switched on: the plug-in active and, when it has one, its Enable control on."""
    return d.on and _p(d, "Enable", 1.0) > 0.5


def is_ace_eq(d):
    return (d.uid or "").startswith("urn:ardour:a-eq") or d.name.lower().startswith("ace eq")


def is_ace_comp(d):
    return (d.uid or "").startswith("urn:ardour:a-comp") or "ace compressor" in d.name.lower()


def is_saturator(d):
    return (d.uid or "") == "urn:hypnomix:saturator" or d.name.lower().startswith("hypnomix saturator")


def ace_eq_bands(d):
    """ACE EQ's bands as EQ Eight's: [(label, on, mode, freq, gain, q)]; the cut bands only when the session has them
    (a session saved before ACE EQ had High Pass / Low Pass bands does not)."""
    out = []
    for k, mode in (("L", "LowShelf"), ("1", "Bell"), ("2", "Bell"), ("3", "Bell"), ("4", "Bell"), ("H", "HighShelf")):
        bw = _p(d, f"Bandwidth {k}", 1.0)
        q = math.sqrt(2 ** bw) / (2 ** bw - 1) if mode == "Bell" and bw > 0 else 0.71
        out.append((k, _p(d, f"Filter {k}", 1.0) > 0.5, mode, _p(d, f"Frequency {k}", 1000.0), _p(d, f"Gain {k}", 0.0), q))
    for word, mode in (("High Pass", "LowCut"), ("Low Pass", "HighCut")):
        if word in d.params:
            slope = int(round(_p(d, f"{word} Slope", 12)))
            out.append((word, _p(d, word, 0.0) > 0.5, f"{mode}{slope}", _p(d, f"{word} Frequency", 30.0), 0.0, 0.71))
    return out


def ardour_device_text(d):
    """A plug-in as the chain column shows it, with the settings that change what it does."""
    n = d.name
    if is_ace_eq(d):
        cuts = [f"{'high' if b[2].startswith('LowCut') else 'low'} pass {b[3]:.0f} Hz {b[2][-2:]} dB/oct"
                for b in ace_eq_bands(d) if b[1] and b[2].startswith(("LowCut", "HighCut"))]
        return n + (f" [{', '.join(cuts)}]" if cuts else "")
    if is_ace_comp(d):
        bits = []
        rng = _p(d, "Range", 60.0)
        if rng < 60.0 - 1e-6:
            bits.append(f"range {rng:g} dB")
        if _p(d, "Auto Release", 0.0) > 0.5:
            bits.append("auto release")
        mix = _p(d, "Mix", 100.0)
        if mix < 100.0 - 1e-6:
            bits.append(f"mix {mix:g}%")
        return n + (f" [{', '.join(bits)}]" if bits else "")
    if is_saturator(d):
        curve = SAT_CURVES.get(int(round(_p(d, "Curve", 0.0))), "curve ?")
        return (f"{n} [{curve}, drive {_p(d, 'Drive', 0.0):+g} dB, output {_p(d, 'Output', 0.0):+g} dB, "
                f"mix {_p(d, 'Mix', 100.0):g}%]")
    return n


def audit_ardour(path):
    """The same audit from a HypnoMix DAW session's saved plug-in controls. -> (chains, flags, limiter count)"""
    from hypnomix import project
    p = project.load(path)
    flags, chains, limit_count = [], {}, 0
    for t in p.tracks:
        if t.kind is None:
            continue
        name = t.name
        vdb = 20 * math.log10(t.volume) if t.volume > 0 else -99
        chain = []
        for d in t.devices:
            n, on = d.name, ardour_on(d)
            chain.append(ardour_device_text(d) + ("" if on else " (off)"))
            if not on:
                flags.append(f"{name}: bypassed `{n}` left in the chain")
            if on and any(x in n for x in LIMITERS) and t.kind != "master":
                limit_count += 1
                flags.append(f"**{name}**: `{n}` on a {'group' if t.kind == 'folder' else 'track'}. Limiting before "
                             "the master limiter (stacked)")
            if on and is_ace_eq(d):
                for k, bon, mode, f, g, q in ace_eq_bands(d):
                    if bon and mode == "HighShelf" and f < 1500 and abs(g) >= 1:
                        flags.append(f"**{name}**: ACE EQ's high shelf at {f:.0f} Hz, {g:+.1f} dB. That tilts "
                                     "everything above it. Intended?")
                    if bon and mode == "LowShelf" and f > 400 and abs(g) >= 1:
                        flags.append(f"**{name}**: ACE EQ's low shelf at {f:.0f} Hz, {g:+.1f} dB")
                    if bon and mode == "Bell" and abs(g) >= 3:
                        flags.append(f"{name}: ACE EQ band {k} bell {f:.0f} Hz {g:+.1f} dB (Q {q:.2f})")
                    if bon and mode.startswith("LowCut") and low_hp_flag(name, f, "ACE EQ's"):
                        flags.append(low_hp_flag(name, f, "ACE EQ's"))
        chains[name] = {"type": {"folder": "Group", "master": "Master", "return": "Return", "midi": "Midi"}.get(t.kind, "Audio"),
                        "fader_db": round(vdb, 1), "muted": t.muted, "chain": chain,
                        "group": t.parent.name if t.parent is not None else (t.group or None)}
        if vdb > 3:
            flags.append(f"{name}: fader at {vdb:+.1f} dB (mix down rather than up)")
    for t in p.tracks:                       # the same dynamics on a group bus and on a track it carries
        if t.parent is None or t.parent.name not in chains or t.name not in chains:
            continue
        strip = lambda c: c.split(" [")[0].split(" (")[0]
        gc = {strip(c) for c in chains[t.parent.name]["chain"] if not c.endswith("(off)")}
        tc = {strip(c) for c in chains[t.name]["chain"] if not c.endswith("(off)")}
        dup = [x for x in gc & tc if any(k in x.lower() for k in DYNAMICS)]
        if dup:
            flags.append(f"{t.name} and its group {t.parent.name} both run `{sorted(dup)[0]}` (double processing)")
    return chains, flags, limit_count


def bounce_vs_profile(bounce):
    from hypnomix.session.profile import audio_metrics, profile_ranges
    from hypnomix.ears.measure import measure
    a = audio_metrics(measure(bounce)); prof = profile_ranges()
    if not prof:
        print("no profile yet (`hypnomix profile build …`): showing the numbers without your ranges", file=sys.stderr)
    rows = []
    for k in ["integrated_lufs", "true_peak_dbtp", "lra_lu", "crest_factor_db", "band_sub_20_60", "band_bass_60_250",
              "band_lowmid_250_500", "band_mid_500_2k", "band_highmid_2k_6k", "band_air_6k_20k", "spectral_centroid_hz",
              "side_to_mid_db", "lr_corr_below_150hz"]:
        r = prof.get(k, {}); v = a[k]
        f = "▲ above" if r and v > r["p75"] else "▼ below" if r and v < r["p25"] else ""
        rows.append((k, v, r.get("p25"), r.get("p75"), f))
    return rows


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("set"); ap.add_argument("bounce", nargs="?"); ap.add_argument("--name")
    a = ap.parse_args()
    name = a.name or Path(a.set).stem
    chains, flags, nlim = audit(a.set)
    md = [f"# {name}: offline audit", f"{'Session' if _is_ardour(a.set) else 'Set'}: `{a.set}`", ""]
    if a.bounce:
        md += [f"## Bounce vs your profile (`{Path(a.bounce).name}`)", "| metric | song | your range | |", "|---|---|---|---|"]
        for k, v, lo, hi, f in bounce_vs_profile(a.bounce):
            md.append(f"| {k} | {v:.2f} | {lo}…{hi} | {f} |")
        md.append("")
    md += [f"## Flags ({len(flags)}; {nlim} limiter/maximizer instances before the master)", *[f"- {x}" for x in flags], "",
           "## Chains", "| track | type | group | fader | devices |", "|---|---|---|---|---|"]
    for n, c in chains.items():
        md.append(f"| {n}{' (muted)' if c['muted'] else ''} | {c['type']} | {c['group'] or ''} | {c['fader_db']} | {', '.join(c['chain'])} |")
    out = out_dir("audit") / f"{name}.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"{name}: {len(flags)} flags, {nlim} limiters before master -> {out}")
    for x in flags[:40]:
        print("  -", x)


if __name__ == "__main__":
    main()
