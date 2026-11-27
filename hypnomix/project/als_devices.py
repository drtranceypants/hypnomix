"""Live devices carried into a HypnoMix Studio session by `als2ardour` (and `hypnomix import` of a .als): the three
stock devices that HypnoMix Studio's own plug-ins can take with their settings.

    Live device        HypnoMix Studio              carried
    EQ Eight           ACE EQ (one per channel)     low cut on the High Pass band, high cut on the Low Pass band
                                                    (12 or 48 dB/oct, as Live's 12 / 48), low shelf (L), up to four
                                                    bells (1-4, width in octaves from Q), high shelf (H), Gain (as
                                                    Master Gain); band gains times Scale. More than four bells: a
                                                    second ACE EQ after it for the rest
    Glue Compressor    ACE Compressor (stereo)      Threshold, Ratio, Attack, Release (Auto as Auto Release), Range
                                                    (Off at 60 dB and over), Makeup, Dry/Wet (as Mix); knee 4 dB
                                                    (Knee 0.67), the soft knee HypnoMix's compressor model gives Glue
    Saturator          Hypnomix Saturator           Drive, Output, Dry/Wet (as Mix) and the curve: Analog Clip, Soft
                                                    Sine, and (in a Live 12 set) Digital Clip as Hard Clip

Never guessed: whatever a device has that the plug-in cannot do is listed with the device in IMPORT-REPORT.md
(EQ Eight: notches, a second cut or shelf, a cut or shelf Q other than 0.71, Adaptive Q, values outside ACE EQ's
ranges, L/R and M/S modes, which are not carried at all; Glue: its sidechain EQ, Soft clip, an external sidechain,
which is not carried at all; Saturator: the Color filter, the output Soft Clip, the other curves, which are not
carried at all). A value outside the plug-in's range is set to the nearest it has and listed. A device switched off
in Live comes across switched off (the plug-in deactivated). Automation of a carried device's controls is not
carried (its own setting is), and says so. Devices inside racks, every other device and third-party plug-ins are
not carried: listed as before.

The plug-ins' controls are written by their port symbols and numbers (the LV2 descriptions in HypnoMix Studio's
`libs/plugins`), together with the values the session reader (`project/ardour.py`) reads. The new controls (ACE EQ's
High Pass / Low Pass, ACE Compressor's Range / Auto Release / Mix) are written only when a device needs them, so a
HypnoMix Studio from before them loads the rest as it is (and ignores those, which the report says).
"""
import math
import xml.etree.ElementTree as ET

# (index, symbol, name, default, low, high, toggle): the LV2 control inputs, as the .ttl files describe them
ACE_EQ_PORTS = [
    (0, "freql", "Frequency L", 160.0, 20.0, 20000.0, False), (1, "gl", "Gain L", 0.0, -20.0, 20.0, False),
    (2, "freq1", "Frequency 1", 300.0, 20.0, 20000.0, False), (3, "g1", "Gain 1", 0.0, -20.0, 20.0, False),
    (4, "bw1", "Bandwidth 1", 1.0, 0.1, 4.0, False),
    (5, "freq2", "Frequency 2", 1000.0, 20.0, 20000.0, False), (6, "g2", "Gain 2", 0.0, -20.0, 20.0, False),
    (7, "bw2", "Bandwidth 2", 1.0, 0.1, 4.0, False),
    (8, "freq3", "Frequency 3", 2500.0, 20.0, 20000.0, False), (9, "g3", "Gain 3", 0.0, -20.0, 20.0, False),
    (10, "bw3", "Bandwidth 3", 1.0, 0.1, 4.0, False),
    (11, "freq4", "Frequency 4", 6000.0, 20.0, 20000.0, False), (12, "g4", "Gain 4", 0.0, -20.0, 20.0, False),
    (13, "bw4", "Bandwidth 4", 1.0, 0.1, 4.0, False),
    (14, "freqh", "Frequency H", 9000.0, 20.0, 20000.0, False), (15, "gh", "Gain H", 0.0, -20.0, 20.0, False),
    (16, "master", "Master Gain", 0.0, -20.0, 20.0, False),
    (17, "filtogl", "Filter L", 1, 0, 1, True), (18, "filtog1", "Filter 1", 1, 0, 1, True),
    (19, "filtog2", "Filter 2", 1, 0, 1, True), (20, "filtog3", "Filter 3", 1, 0, 1, True),
    (21, "filtog4", "Filter 4", 1, 0, 1, True), (22, "filtogh", "Filter H", 1, 0, 1, True),
    (23, "enable", "Enable", 1, 0, 1, True),
    (26, "hpon", "High Pass", 0, 0, 1, True), (27, "hpfreq", "High Pass Frequency", 30.0, 10.0, 20000.0, False),
    (28, "hpslope", "High Pass Slope", 12, 12, 48, False),
    (29, "lpon", "Low Pass", 0, 0, 1, True), (30, "lpfreq", "Low Pass Frequency", 18000.0, 10.0, 20000.0, False),
    (31, "lpslope", "Low Pass Slope", 12, 12, 48, False),
]
ACE_COMP_PORTS = [
    (0, "att", "Attack", 10.0, 0.1, 100.0, False), (1, "rel", "Release", 80.0, 1.0, 2000.0, False),
    (2, "kn", "Knee", 0.0, 0.0, 8.0, False), (3, "rat", "Ratio", 4.0, 1.0, 20.0, False),
    (4, "thr", "Threshold", 0.0, -60.0, 0.0, False), (5, "mak", "Makeup", 0.0, 0.0, 30.0, False),
    (9, "sidech", "Sidechain", 0, 0, 1, True), (10, "enable", "Enable", 1, 0, 1, True),
    (16, "range", "Range", 60.0, 0.0, 60.0, False), (17, "autorel", "Auto Release", 0, 0, 1, True),
    (18, "mix", "Mix", 100.0, 0.0, 100.0, False),
]
SATURATOR_PORTS = [
    (0, "drive", "Drive", 0.0, -12.0, 36.0, False), (1, "curve", "Curve", 0, 0, 2, False),
    (2, "output", "Output", 0.0, -36.0, 12.0, False), (3, "mix", "Mix", 100.0, 0.0, 100.0, False),
    (4, "enable", "Enable", 1, 0, 1, True),
]
# the controls a HypnoMix Studio from before ACE EQ's cuts and ACE Compressor's extras does not have: written only when used
NEW_CONTROLS = {"High Pass", "High Pass Frequency", "High Pass Slope", "Low Pass", "Low Pass Frequency",
                "Low Pass Slope", "Range", "Auto Release", "Mix"}
PLUGINS = {
    "ACE EQ": ("urn:ardour:a-eq", ACE_EQ_PORTS, 1),                     # mono: one instance per channel
    "ACE Compressor (stereo)": ("urn:ardour:a-comp#stereo", ACE_COMP_PORTS, 2),
    "Hypnomix Saturator": ("urn:hypnomix:saturator", SATURATOR_PORTS, 2),
}

GLUE_ATTACK = [0.01, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0]                 # ms, Live's steps (as `engineer/sidechain.py`)
GLUE_RELEASE = [100.0, 200.0, 400.0, 600.0, 800.0, 1200.0, None]     # ms; None = Auto
GLUE_RATIO = [2.0, 4.0, 10.0]
GLUE_KNEE_DB = 4.0                   # HypnoMix's compressor model gives Glue a 4 dB soft knee (`read_glue`)
ACE_RANGE_OFF = 60.0
BUTTERWORTH_Q = 0.7071
# Saturator's Type: Analog Clip and Soft Sine are 0 and 1 in every Live; Live 12 has Bass Shaper at 2, which moved the
# rest up (checked against Live 12's own presets). An older set's other numbers are not carried
SAT_TYPES_12 = {0: "Analog Clip", 1: "Soft Sine", 2: "Bass Shaper", 3: "Medium Curve", 4: "Hard Curve",
                5: "Sinoid Fold", 6: "Digital Clip", 7: "Waveshaper"}
SAT_TYPES_OLD = {0: "Analog Clip", 1: "Soft Sine"}
SAT_CURVE = {"Soft Sine": 0, "Analog Clip": 1, "Digital Clip": 2}      # Hypnomix Saturator's Curve
SAT_CURVE_NAMES = {0: "Soft Sine", 1: "Analog Clip", 2: "Hard Clip"}


# ---------------------------------------------------------------- Live XML
def _v(el, path, default=None):
    e = el.find(path) if el is not None else None
    return e.get("Value") if e is not None and e.get("Value") is not None else default


def _num(el, path, default):
    try:
        x = float(_v(el, path, default))
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


def _man(el, name, default):
    return _num(el, f"./{name}/Manual", default)


def _on(el, name="On", default=True):
    x = _v(el, f"./{name}/Manual")
    return default if x is None else str(x).lower() == "true"


def _aid(el, name):
    """The automation target id of a device's parameter (to tell whether Live automates it)."""
    t = el.find(f"./{name}/AutomationTarget") if el is not None else None
    return t.get("Id") if t is not None else None


def q_to_octaves(q):
    """A bell's Q as a width in octaves (the same formula `engineer/chain_reaper.py` uses for ReaEQ and ACE EQ)."""
    return 2 / math.log(2) * math.asinh(1 / (2 * max(q, 0.05)))


class Plan:
    """One plug-in to write: its catalogue name, the values by control name, on/off, and what it says."""

    def __init__(self, name, values, active=True):
        self.name, self.values, self.active = name, dict(values), active

    @property
    def uses_new(self):
        return sorted(k for k in self.values if k in NEW_CONTROLS)


def _clamp(v, lo, hi, what, notes, fmt="{:g}"):
    if v < lo or v > hi:
        c = min(hi, max(lo, v))
        notes.append(f"{what} {fmt.format(v)} is outside the plug-in's range: set to {fmt.format(c)}")
        return c
    return v


# ---------------------------------------------------------------- the three devices
def eq8(d):
    """EQ Eight -> ([Plan], summary, [notes]) or (None, None, [why not carried])."""
    mode = int(_num(d, "./Mode", 0))
    if mode != 0:
        return None, None, ["it is in " + ("L/R" if mode == 1 else "M/S") + " mode (each side its own bands): ACE EQ "
                            "works on both channels alike"]
    notes = []
    scale = _man(d, "Scale", 1.0)
    gain = _man(d, "GlobalGain", 0.0)
    if _v(d, "./Live8ShelfScaleLegacyMode") == "true":
        notes.append("its Live 8 shelf scaling is not carried")
    bands, off = [], 0
    for i in range(8):
        b = d.find(f"./Bands.{i}/ParameterA")
        if b is None:
            continue
        if not _on(b, "IsOn", False):
            off += 1
            continue
        bands.append(dict(n=i + 1, mode=int(_man(b, "Mode", 3)), freq=_man(b, "Freq", 1000.0),
                          gain=_man(b, "Gain", 0.0) * scale, q=_man(b, "Q", 0.71)))
    if off:
        notes.append(f"{off} switched-off band(s) left out")
    hp = [b for b in bands if b["mode"] in (0, 1)]
    lp = [b for b in bands if b["mode"] in (6, 7)]
    ls = [b for b in bands if b["mode"] == 2]
    hs = [b for b in bands if b["mode"] == 5]
    bells = [b for b in bands if b["mode"] == 3]
    for b in [b for b in bands if b["mode"] == 4]:
        notes.append(f"band {b['n']}, a notch at {b['freq']:.0f} Hz, is not carried: ACE EQ has no notch")
    for kind, lst in (("low cut", hp), ("high cut", lp), ("low shelf", ls), ("high shelf", hs)):
        for b in lst[1:]:
            notes.append(f"band {b['n']}, a second {kind} at {b['freq']:.0f} Hz, is not carried: ACE EQ has one")
    if bells and _on(d, "AdaptiveQ", True) and any(abs(b["gain"]) > 0.1 for b in bells):
        notes.append("Adaptive Q is not carried: the bells keep the Q they are set to at any gain")
    v = {"Master Gain": _clamp(gain, -20.0, 20.0, "Gain", notes, "{:+.1f} dB"), "Enable": 1}
    summary = []
    for word, lst, slope in (("High Pass", hp, {0: 48, 1: 12}), ("Low Pass", lp, {6: 12, 7: 48})):
        if lst:
            b = lst[0]
            v[word] = 1
            v[f"{word} Frequency"] = _clamp(b["freq"], 10.0, 20000.0, f"band {b['n']}'s frequency", notes, "{:.0f} Hz")
            v[f"{word} Slope"] = slope[b["mode"]]
            summary.append(f"{'low' if word == 'High Pass' else 'high'} cut {b['freq']:.0f} Hz {slope[b['mode']]} dB/oct")
            if abs(b["q"] - BUTTERWORTH_Q) > 0.05:
                notes.append(f"band {b['n']}'s Q {b['q']:.2f} is not carried: ACE EQ's cut is Butterworth (Q 0.71, "
                             "no resonance peak)")
    for k, lst, word in (("L", ls, "low shelf"), ("H", hs, "high shelf")):
        if lst:
            b = lst[0]
            v[f"Filter {k}"] = 1
            v[f"Frequency {k}"] = _clamp(b["freq"], 20.0, 20000.0, f"band {b['n']}'s frequency", notes, "{:.0f} Hz")
            v[f"Gain {k}"] = _clamp(b["gain"], -20.0, 20.0, f"band {b['n']}'s gain", notes, "{:+.1f} dB")
            summary.append(f"{word} {b['freq']:.0f} Hz {b['gain']:+.1f} dB")
            if abs(b["q"] - BUTTERWORTH_Q) > 0.05:
                notes.append(f"band {b['n']}'s shelf Q {b['q']:.2f} is not carried: ACE EQ's shelves have one shape")
        else:
            v[f"Filter {k}"] = 0
    plans = []
    for k in range(0, max(1, len(bells)), 4):
        part = bells[k:k + 4]
        pv = dict(v) if k == 0 else {"Filter L": 0, "Filter H": 0, "Master Gain": 0.0, "Enable": 1}
        for n in range(1, 5):
            if n <= len(part):
                b = part[n - 1]
                pv[f"Filter {n}"] = 1
                pv[f"Frequency {n}"] = _clamp(b["freq"], 20.0, 20000.0, f"band {b['n']}'s frequency", notes, "{:.0f} Hz")
                pv[f"Gain {n}"] = _clamp(b["gain"], -20.0, 20.0, f"band {b['n']}'s gain", notes, "{:+.1f} dB")
                pv[f"Bandwidth {n}"] = round(_clamp(q_to_octaves(b["q"]), 0.1, 4.0, f"band {b['n']}'s width (Q {b['q']:.2f})",
                                                    notes, "{:.2f} octaves"), 4)
                summary.append(f"bell {b['freq']:.0f} Hz {b['gain']:+.1f} dB Q {b['q']:.2f}")
            else:
                pv[f"Filter {n}"] = 0
        plans.append(Plan("ACE EQ", pv, _on(d)))
    if len(plans) > 1:
        notes.append(f"{len(bells)} bells: the ones after the fourth are on a second ACE EQ right after it")
    if abs(gain) > 1e-6:
        summary.append(f"gain {gain:+.1f} dB")
    return plans, ", ".join(summary) or "no band switched on", notes


def glue(d):
    """Glue Compressor -> ([Plan], summary, [notes]) or (None, None, [why not carried])."""
    if _on(d.find("./SideChain"), "OnOff", False):
        return None, None, ["it is keyed from another track (an external sidechain): set it up by hand on an ACE "
                            "Compressor's sidechain input"]
    notes = []
    pick = lambda table, i: table[min(max(int(i), 0), len(table) - 1)]
    thr, ratio = _man(d, "Threshold", -10.0), pick(GLUE_RATIO, _man(d, "Ratio", 1))
    att, rel = pick(GLUE_ATTACK, _man(d, "Attack", 2)), pick(GLUE_RELEASE, _man(d, "Release", 2))
    rng, makeup, mix = _man(d, "Range", 70.0), _man(d, "Makeup", 0.0), _man(d, "DryWet", 1.0)
    v = {"Threshold": _clamp(thr, -60.0, 0.0, "Threshold", notes, "{:.1f} dB"), "Ratio": ratio,
         "Attack": _clamp(att, 0.1, 100.0, "Attack", notes, "{:g} ms"), "Knee": round(GLUE_KNEE_DB / 6.0, 4),
         "Makeup": _clamp(makeup, 0.0, 30.0, "Makeup", notes, "{:+.1f} dB"), "Sidechain": 0, "Enable": 1}
    summary = [f"threshold {thr:.1f} dB", f"{ratio:g}:1", f"attack {att:g} ms"]
    if rel is None:
        v["Release"], v["Auto Release"] = 400.0, 1
        summary.append("release Auto")
    else:
        v["Release"] = rel
        summary.append(f"release {rel:g} ms")
    if rng < ACE_RANGE_OFF:
        v["Range"] = max(0.0, rng)
        summary.append(f"range {rng:g} dB")
    if mix < 0.9995:
        v["Mix"] = round(100 * min(1.0, max(0.0, mix)), 2)
        summary.append(f"dry/wet {100 * mix:.0f}%")
    if abs(makeup) > 1e-6:
        summary.append(f"makeup {makeup:+.1f} dB")
    if _on(d, "PeakClipIn", False):
        notes.append("its Soft clip is not carried (ACE Compressor has none)")
    eq = d.find("./SideChainEq")
    if eq is not None and _on(eq, "On", False):
        notes.append("its sidechain EQ is not carried: ACE Compressor's detector hears the whole signal")
    return [Plan("ACE Compressor (stereo)", v, _on(d))], ", ".join(summary), notes


def saturator(d, live_major):
    """Saturator -> ([Plan], summary, [notes]) or (None, None, [why not carried])."""
    typ = int(_man(d, "Type", 0))
    table = SAT_TYPES_12 if (live_major or 0) >= 12 else SAT_TYPES_OLD
    name = table.get(typ)
    if name not in SAT_CURVE:
        return None, None, [f"its curve ({name or f'number {typ} in a set from before Live 12'}) is not one Hypnomix "
                            "Saturator has (Soft Sine, Analog Clip, Hard Clip)"]
    notes = []
    drive, out, mix = _man(d, "PreDrive", 0.0), _man(d, "PostDrive", 0.0), _man(d, "DryWet", 1.0)
    curve = SAT_CURVE[name]
    v = {"Drive": _clamp(drive, -12.0, 36.0, "Drive", notes, "{:+.1f} dB"), "Curve": curve,
         "Output": _clamp(out, -36.0, 12.0, "Output", notes, "{:+.1f} dB"),
         "Mix": round(100 * min(1.0, max(0.0, mix)), 2), "Enable": 1}
    if _on(d, "ColorOn", True) and (abs(_man(d, "BaseDrive", 0.0)) > 0.01 or abs(_man(d, "ColorDepth", 0.0)) > 0.01):
        notes.append(f"its Color filter (Base {_man(d, 'BaseDrive', 0.0):+.1f} dB, Depth {_man(d, 'ColorDepth', 0.0):+.1f} "
                     f"dB at {_man(d, 'ColorFrequency', 1000.0):.0f} Hz) is not carried")
    if _man(d, "PostClip", 0.0) > 0.5:
        notes.append("its output Soft Clip is not carried")
    notes.append(f"{name} is Hypnomix Saturator's own {SAT_CURVE_NAMES[curve]} curve: close to Live's, not the same "
                 "sound (not compared by ear)")
    summary = (f"{name}{' as Hard Clip' if name == 'Digital Clip' else ''}, drive {drive:+.1f} dB, output {out:+.1f} dB, "
               f"dry/wet {100 * mix:.0f}%")
    return [Plan("Hypnomix Saturator", v, _on(d))], summary, notes


CARRIERS = {"Eq8": ("EQ Eight", lambda d, live: eq8(d)), "GlueCompressor": ("Glue Compressor", lambda d, live: glue(d)),
            "Saturator": ("Saturator", saturator)}
AUTOMATABLE = {"Eq8": ("GlobalGain", "Scale"), "GlueCompressor": ("Threshold", "Ratio", "Attack", "Release", "Range",
                                                                   "Makeup", "DryWet"),
               "Saturator": ("PreDrive", "PostDrive", "DryWet", "Type")}


def chain(track_el, live_major=None, automated=()):
    """A Live track's device chain -> (plans in chain order, report entries). Each entry is a dict: label (the
    device's name in the set), carried (bool), to (the plug-in(s)), summary, notes."""
    from hypnomix.project.als2ardour import device_label
    devs = track_el.find("./DeviceChain/DeviceChain/Devices") if track_el is not None else None
    plans, entries = [], []
    automated = set(automated or ())
    for d in (list(devs) if devs is not None else []):
        label = device_label(d)
        if d.tag not in CARRIERS:
            entries.append(dict(label=label, carried=False, to="", summary="", notes=[]))
            continue
        _, fn = CARRIERS[d.tag]
        ps, summary, notes = fn(d, live_major)
        if ps is None:
            entries.append(dict(label=label, carried=False, to="", summary="", notes=notes, why=True))
            continue
        auto = [p for p in AUTOMATABLE[d.tag] if _aid(d, p) in automated]
        if d.tag == "Eq8":
            for i in range(8):
                for p in ("Freq", "Gain", "Q", "IsOn"):
                    if _aid(d.find(f"./Bands.{i}/ParameterA"), p) in automated:
                        auto.append(f"band {i + 1} {p}")
        if _aid(d, "On") in automated:
            auto.append("On")
        if auto:
            notes = notes + [f"its automation ({', '.join(auto)}) is not carried: the plug-in keeps the device's "
                             "own setting"]
        if not _on(d):
            notes = ["switched off in Live: carried switched off"] + notes
        plans += ps
        new = sorted({k for p in ps for k in p.uses_new})
        if new:
            notes = notes + ["needs a HypnoMix Studio whose plug-in has " + ", ".join(new) + " (an older one ignores them)"]
        entries.append(dict(label=label, carried=True, to=" + ".join(p.name for p in ps), summary=summary, notes=notes))
    return plans, entries


# ---------------------------------------------------------------- the session XML
def write(rt, plan, ids, channels=2):
    """The plug-in as a session Processor under route element `rt` (appended). The engine configures its inputs and
    outputs when it loads the session (no saved port maps), as it does for a plug-in added from the menu."""
    uri, ports, width = PLUGINS[plan.name]
    p = ET.SubElement(rt, "Processor", {"id": str(ids()), "name": plan.name, "active": "1" if plan.active else "0",
                                        "user-latency": "0", "use-user-latency": "0", "type": "lv2", "unique-id": uri,
                                        "count": str(max(1, channels // width)), "custom": "0"})
    lv2 = ET.SubElement(p, "lv2", {"last-preset-uri": "", "last-preset-label": "",
                                   "parameter-changed-since-last-preset": "1"})
    rows = []
    for idx, sym, name, dflt, lo, hi, toggle in ports:
        if name in NEW_CONTROLS and name not in plan.values:
            continue                                     # not needed: an older plug-in without it loads cleanly
        val = plan.values.get(name, dflt)
        val = min(hi, max(lo, float(val)))
        txt = str(int(round(val))) if toggle or float(val).is_integer() else f"{val:.6g}"
        ET.SubElement(lv2, "Port", {"symbol": sym, "value": txt})
        rows.append((idx, sym, name, txt, toggle))
    for idx, sym, name, txt, toggle in rows:
        ET.SubElement(p, "Controllable", {"name": name, "id": str(ids()), "flags": "Toggle" if toggle else "",
                                          "value": txt, "parameter": str(idx), "symbol": sym})
    return p
