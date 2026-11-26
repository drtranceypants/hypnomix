"""Sidechain compression in a REAPER project: Live's `sidechain` check on ReaComp, read and written in the .rpp.

A REAPER sidechain is a ReaComp whose detector listens to a channel pair that sends land on (usually channels 3/4
of a 4-channel track, fed by the kick). For each one this measures, with the same simulation as the Live check,
what it does to the music hit by hit (depth, recovery before the next hit, consistency, low-end distortion) and
suggests settings for the style (clarity for drum triggers, vocal-duck for a vocal feeding a reverb or delay).

Reading ReaComp from the file (measured in REAPER 7.86): its saved state is a header, then its parameters as
32-bit floats in order, then a short tail. Raw values: threshold = amplitude; ratio = 1 + 99 x raw (1 = inf);
attack ms = 500 x raw; release ms = 5000 x raw; pre-comp (lookahead) ms = 250 x raw; low-pass and high-pass on the
detector Hz = 20000 x raw (1 and 0 = off); RMS size ms = 100 x raw (0 = peak); knee dB = 24 x raw; the detector's
first channel (0-based) = 1084 x raw: 0 is the track itself, 2 is channels 3/4. A send (AUXRECV) lands on the
channel pair its field 9 names (2 = 3/4).

A fix rewrites only those floats in the new .rpp; everything else in the plug-in's state stays byte for byte.
"""
import base64
import math
import struct

import numpy as np

from hypnomix.engineer import sidechain as SC

REACOMP = "ReaComp"
P = dict(thresh=0, ratio=1, attack=2, release=3, precomp=4, lowpass=6, hipass=7, detector=8, dry=10, wet=11,
         rms=13, knee=14, auto_makeup=15, auto_release=16)


# ---------------------------------------------------------------- ReaComp state in the .rpp
class State:
    """A VST chunk's base64 lines, split into header / parameter floats / tail, re-encodable line by line."""

    def __init__(self, vst):
        from hypnomix.project import rpp
        self.vst = vst
        self.lines = [c for c in vst.children if isinstance(c, rpp.Line)]
        self.raw = [base64.b64decode(l.raw.strip()) for l in self.lines]
        blob = b"".join(self.raw)
        ints = struct.unpack_from("<3i", blob, 0)
        n_in = ints[2]
        off = 12 + 8 * n_in
        n_out = struct.unpack_from("<i", blob, off)[0]
        off += 4 + 8 * n_out
        size = struct.unpack_from("<i", blob, off)[0]
        self.start = off + 12                          # size, then two more ints, then the plug-in's own state
        state = blob[self.start:self.start + size]
        if state[:8] != bytes.fromhex("efbeadde0df0adde"):
            raise ValueError("not a ReaComp state this reader knows")
        self.n = (size - 8) // 4
        self.vals = list(struct.unpack_from(f"<{self.n}f", state, 8))
        self.blob = blob

    def write(self):
        """Put the (changed) floats back, keeping every line's byte length, so the chunk keeps REAPER's layout."""
        b = bytearray(self.blob)
        struct.pack_into(f"<{self.n}f", b, self.start + 8, *self.vals)
        pos = 0
        for ln, old in zip(self.lines, self.raw):
            piece = bytes(b[pos:pos + len(old)])
            pos += len(old)
            ln.raw = ln.indent + base64.b64encode(piece).decode()
            ln.tokens = [ln.raw.strip()]


def settings(vals):
    """ReaComp's raw floats -> the settings the Live simulation uses."""
    g = lambda k: vals[P[k]] if P[k] < len(vals) else 0.0
    rms_ms = 100.0 * g("rms")
    ratio = 1000.0 if g("ratio") >= 0.9999 else 1.0 + 99.0 * g("ratio")
    lp, hp = 20000.0 * g("lowpass"), 20000.0 * g("hipass")
    return dict(kind="reacomp", on=True, threshold_db=20 * math.log10(max(g("thresh"), 1e-9)), ratio=ratio,
                attack=500.0 * g("attack"), release=5000.0 * g("release"), knee=24.0 * g("knee"),
                model=1 if rms_ms >= 1.0 else 0, rms_ms=max(rms_ms, 1.0), lookahead=0, lookahead_ms=250.0 * g("precomp"),
                lp_hz=lp if 0 < lp < 19999 else None, hp_hz=hp if hp > 1 else None,
                eq_on=False, eq_mode=SC.LOWPASS, eq_freq=150.0, eq_q=0.707, eq_gain=0.0, sc_gain_db=0.0, dry_wet=1.0,
                auto_release=g("auto_release") > 0.5, channel=int(round(1084 * g("detector"))))


def to_vals(vals, c, new_eq=None):
    """Settings -> ReaComp floats (only the ones the suggestion sets)."""
    out = list(vals)
    out[P["thresh"]] = float(10 ** (c["threshold_db"] / 20))
    out[P["ratio"]] = 1.0 if c["ratio"] >= 999 else float(min(1.0, max(0.0, (c["ratio"] - 1) / 99)))
    out[P["attack"]] = float(min(1.0, c["attack"] / 500))
    out[P["release"]] = float(min(1.0, c["release"] / 5000))
    out[P["knee"]] = float(min(1.0, c["knee"] / 24))
    out[P["rms"]] = float(c.get("rms_ms", 10.0) / 100) if c.get("model") == 1 else 0.0
    la = c["lookahead_ms"] if c.get("lookahead_ms") is not None else SC.LOOKAHEAD_MS[min(max(c.get("lookahead", 0), 0), 2)]
    out[P["precomp"]] = float(min(1.0, la / 250))
    if new_eq and new_eq.get("eq_mode") == SC.LOWPASS:   # a drum-bus trigger: listen to the kick only
        out[P["lowpass"]] = float(new_eq["eq_freq"] / 20000)
    if c.get("auto_release") is False and len(out) > P["auto_release"]:
        out[P["auto_release"]] = 0.0
    return out


def describe(c):
    la = c["lookahead_ms"] if c.get("lookahead_ms") is not None else SC.LOOKAHEAD_MS[min(max(c.get("lookahead", 0), 0), 2)]
    f = [f"low-pass {c['lp_hz']:.0f} Hz" if c.get("lp_hz") else "", f"high-pass {c['hp_hz']:.0f} Hz" if c.get("hp_hz") else ""]
    f = ", ".join(x for x in f if x) or "off"
    return (f"threshold {c['threshold_db']:.1f} dB, ratio {c['ratio']:.1f}:1, attack {c['attack']:.3g} ms, release "
            f"{c['release']:.0f} ms, knee {c['knee']:.0f} dB, {'RMS ' + format(c.get('rms_ms', 10), '.0f') + ' ms' if c['model'] == 1 else 'peak'}, "
            f"pre-comp {la:.0f} ms, detector filters {f}")


# ---------------------------------------------------------------- finding them
def find(p):
    """[dict(track, fx index, device, state, settings, sources [(track, send gain, post-fader?)])]."""
    from hypnomix.project.rpp import Line
    out = []
    for t in p.tracks:
        for k, d in enumerate(t.devices):
            if REACOMP.lower() not in d.name.lower() or not d.on:
                continue
            try:
                st = State(d.native)
            except Exception:
                continue
            c = settings(st.vals)
            if c["channel"] < 1:
                continue                                  # listens to its own track: ordinary compression
            srcs = []
            for ln in t.native.lines("AUXRECV"):
                tk = ln.tokens
                if len(tk) < 10 or not tk[1].lstrip("-").isdigit():
                    continue
                dst = int(float(tk[9])) & 0x3FF          # the low bits: the first destination channel (0-based)
                if dst not in (c["channel"], c["channel"] - 1) or int(tk[1]) >= len(p.tracks):
                    continue
                if len(tk) > 5 and tk[5] == "1":
                    continue                              # a muted send
                srcs.append((p.tracks[int(tk[1])], float(tk[3]), tk[2] == "0"))
            out.append(dict(track=t, fx=k, device=d, state=st, c=c, sources=srcs))
    return out


def trigger_audio(p, srcs, length):
    """What the detector hears: each send's track (its items, without plug-ins) at the send level and, for a
    post-fader send, the sending track's fader. Resampled to the simulation's rate."""
    from hypnomix.engineer.sidechain import to_sr
    acc = None
    for tr, vol, post in srcs:
        y = p.render(tr, 44100, length)
        g = vol * (tr.volume if post else 1.0)
        acc = y * g if acc is None else acc[: len(y)] + y[: len(acc)] * g
    return to_sr(acc, 44100) if acc is not None else None


def analyse(p, style="auto"):
    """[(sidechain, result or None, why)] for every ReaComp sidechain in the project."""
    from hypnomix.engineer.sidechain import to_sr
    beat_ms = 60000.0 / p.tempo
    L = p.end()
    out = []
    for s in find(p):
        if not s["sources"]:
            out.append((s, None, f"its detector listens to channels {s['c']['channel'] + 1}/{s['c']['channel'] + 2}, "
                                 "but no send lands there: it never ducks"))
            continue
        if any(tr is s["track"] for tr, _, _ in s["sources"]):
            out.append((s, None, "the compressor listens to its own track: ordinary compression, not ducking"))
            continue
        trig = trigger_audio(p, s["sources"], L)
        if trig is None or not np.any(trig):
            out.append((s, None, "the sending track has no audio to trigger it (a MIDI or empty track)"))
            continue
        target = to_sr(p.render(s["track"], 44100, L), 44100) if s["track"].clips else None
        exact = all(not tr.devices for tr, _, _ in s["sources"])   # the render IS what the send carries
        r = SC.analyse(dict(s["c"]), trig, target, beat_ms, style, exact)
        out.append((s, r, None))
    return out


def findings(p, results, W):
    from hypnomix.project.rpp_edit import locator    # noqa: F401 (locators are by track + plug-in position)
    out = []
    for n, (s, r, why) in enumerate(results, 1):
        t = s["track"]
        src = ", ".join(tr.name for tr, _, _ in s["sources"]) or "nothing"
        head = f"ReaComp on '{t.name}' ducked by {src}"
        if r is None:
            out.append(dict(id=f"sidechain-{n}", tool="sidechain", kind="sidechain", severity="info", track=t.name,
                            where="", problem=f"{head}: {why}", fix="check its routing in REAPER", applies="info"))
            continue
        problems = SC.verdict(r["m_cur"], r["style"], r["f0"], s["c"], r["decay"], r["exact"]) \
            if r["style"] != "vocal-duck" else []
        now = SC.fmt_m(r["m_cur"], r["style"]) if r["exact"] else "(level not judged: the sending track has plug-ins)"
        fix = (f"suggested ({r['style']}): {describe(r['sug'])}" + (", detector low-pass 150 Hz (listen to the kick only)"
                                                                  if r["new_eq"] else "")
               + f" -> {SC.fmt_m(r['m_new'], r['style'])}" + "".join(f"; {x}" for x in r["notes"]))
        f = dict(id=f"sidechain-{n}", tool="sidechain", kind="sidechain", severity="medium" if problems else "low",
                 track=t.name, where="", host=t.name,
                 problem=f"{head}. Now: {describe(s['c'])}; it does {now}" + ("".join(f"; {x}" for x in problems)),
                 fix=fix, applies="set" if p.daw == "reaper" else "manual")
        if p.daw == "reaper":
            f["edit"] = dict(op="sidechain", track=t.name, index=t.index, fx=s["fx"],
                             vals=to_vals(s["state"].vals, r["sug"], r["new_eq"]))
        out.append(f)
    return out


def apply(p, f, ed):
    """Write one approved suggestion into the ReaComp in the loaded project. Returns a log line."""
    t = next((x for x in p.tracks if x.name == ed["track"]), None)
    if t is None or ed["fx"] >= len(t.devices) or REACOMP.lower() not in t.devices[ed["fx"]].name.lower():
        raise ValueError(f"the ReaComp on '{ed['track']}' is no longer where the scan found it")
    st = State(t.devices[ed["fx"]].native)
    if len(st.vals) != len(ed["vals"]):
        raise ValueError(f"the ReaComp on '{ed['track']}' has a different version of its settings")
    st.vals = [float(x) for x in ed["vals"]]
    st.write()
    return f"- {f['id']}: ReaComp on {t.name}: {describe(settings(st.vals))}"
