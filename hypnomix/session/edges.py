#!/usr/bin/env python3
"""Clip edges and fades that cut into a sung (or played) sound: the first consonant of a word lost at a comp
edit ("sorrow" heard as "orrow"), a long fade-in that ducks the start of a word, a fade-out or clip end that
clips a tail.

Every enabled arrangement clip on the chosen tracks is rendered twice from its source file (the same warp
mapping as `hypnomix render`): as Live plays it, and with its edges opened by --look ms and no fades. Then:

  fade-in / fade-out   a sound that STARTS inside the fade (a rise of 10+ dB within 30 ms, within --range dB of
                       the clip's peak) is turned down by more than --loss dB. A natural tail dying away inside a
                       fade-out is fine. Fades over --swell-s (2 s) are deliberate swells: skipped.
                       A sound with most of its energy under 150 Hz and almost none in 300-3000 Hz is a thump
                       (a mic bump, a breath pop): the fade may be hiding it on purpose, so it is only listed.
  start cut / end cut  sound within --cut-range dB of the peak runs right across the edge and no other clip on the
                       track covers it: the start (or end) of a sound is missing. Listen first: past an edge can be
                       a breath, a thump or the next take (most end cuts are comp switches).

Fixes (only approved items, written to a NEW set): a fade-in or fade-out shortened to --fix-fade-ms (10 ms).
Clear-cut fade-ins (a word starting within 150 ms of the edge, ducked 10 dB or more, not a thump) are marked
recommended; the others say "listen first". Edge moves are never automatic.

It checks the ORIGINAL comp tracks too, switched-off ones included: a cleaned or aligned copy inherits the
problem from them.

Usage:
  hypnomix edges SET.als [--tracks NAME ...] [--names names.json] [--all-tracks] [--json OUT.json]
  hypnomix edges SET.als --apply NEW.als --ids edges-1,edges-4
"""
import argparse, copy, gzip, json, re, sys
from hypnomix.core.gz import read_gz
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt

from hypnomix.session.render import render_track, v

SR = 22050
LP = butter(4, 150, "lp", fs=SR, output="sos")
BP = butter(4, [300, 3000], "bp", fs=SR, output="sos")
HF = butter(4, [3500, 10000], "bp", fs=SR, output="sos")      # where "s", "sh", "t" live
HOP = int(0.005 * SR)
VOCAL_WORDS = ("vocal", "harmony", "lead", "vox", "voice", "choir", "bv", "backing")


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12) if len(x) else -240.0


def env_db(x, win):
    k = max(1, win)
    e = np.sqrt(np.maximum(np.convolve(x ** 2, np.ones(k) / k, "same"), 0))
    return 20 * np.log10(e + 1e-12)


def open_clip(c, ext_beats, spb):
    """Copy of clip c placed at beat 0, edges opened by ext_beats on both sides, no fades (loop-off clips).
    Only the start values move (Time, CurrentStart, LoopStart): StartRelative stays, or the audio shifts twice."""
    d = copy.deepcopy(c)
    s, e = float(v(c, "./CurrentStart")), float(v(c, "./CurrentEnd"))
    d.set("Time", "0")
    d.find("./CurrentStart").set("Value", "0")
    d.find("./CurrentEnd").set("Value", repr(e - s + 2 * ext_beats))
    per = 1.0 if v(c, "./IsWarped") == "true" else spb      # loop values: beats when warped, seconds when not
    ls = float(v(c, "./Loop/LoopStart"))
    d.find("./Loop/LoopStart").set("Value", repr(ls - ext_beats * per))
    le = d.find("./Loop/LoopEnd")
    le.set("Value", repr(float(le.get("Value")) + ext_beats * per))
    for k in ("FadeInLength", "FadeOutLength"):
        if d.find(f"./Fades/{k}") is not None:
            d.find(f"./Fades/{k}").set("Value", "0")
    for k in ("IsDefaultFadeIn", "IsDefaultFadeOut"):
        if d.find(f"./Fades/{k}") is not None:
            d.find(f"./Fades/{k}").set("Value", "false")
    if d.find("./Disabled") is not None:
        d.find("./Disabled").set("Value", "false")
    return d


def render_one(clip, als, spb, n):
    t = ET.Element("AudioTrack")
    ET.SubElement(ET.SubElement(t, "Name"), "EffectiveName").set("Value", "edge")
    ET.SubElement(ET.SubElement(ET.SubElement(t, "X"), "ArrangerAutomation"), "Events").append(clip)
    return render_track(t, als, spb, n, SR, None, None, [])


def thump_share(seg):
    """Share of energy under 150 Hz, counted only when there is almost nothing in the vowel band (a low sung
    vowel has its fundamental down there too, but carries harmonics at 300-3000 Hz)."""
    if len(seg) <= 30:
        return 0.0
    tot = float(np.sum(seg ** 2)) + 1e-12
    low = float(np.sum(sosfiltfilt(LP, seg) ** 2) / tot)
    mid = float(np.sum(sosfiltfilt(BP, seg) ** 2) / tot)
    return low if mid < 0.05 else 0.0


def ducked_onsets(reg, ramp, floor, loss):
    """[(dB ducked, seconds into reg, thump share)] for sounds that start inside a fade and lose more than `loss`."""
    h = int(0.005 * SR)
    ed = env_db(reg, int(0.01 * SR))[::h]
    out, last = [], -99
    for i in range(6, len(ed)):
        if ed[i] > floor and ed[i] - ed[i - 6:i].min() >= 10 and i - last > 30:
            last = i
            a0 = i * h
            a1 = min(len(reg), a0 + int(0.06 * SR))
            g = float(np.mean(ramp[a0:a1])) if a1 > a0 else 1.0
            d = -20 * np.log10(max(g, 1e-4))
            if d > loss:
                out.append((d, a0 / SR, thump_share(reg[a0:a0 + int(0.04 * SR)])))
    return out


def pick_tracks(root, names=None, explicit=(), all_tracks=False):
    labels = {}
    if names and Path(names).exists():
        for r in json.loads(Path(names).read_text(encoding="utf-8", errors="replace")).get("tracks", []):
            labels[r["old"]] = str(r.get("final") or r.get("label") or "")
    out = []
    for t in root.find(".//Tracks"):
        if t.tag != "AudioTrack":
            continue
        nm = v(t, "./Name/EffectiveName")
        if explicit:
            if nm in explicit:
                out.append(t)
            continue
        lab = (labels.get(nm) or "").lower()
        if all_tracks or any(k in nm.lower() for k in VOCAL_WORDS) or any(k in lab for k in VOCAL_WORDS):
            out.append(t)                    # switched-off comp originals included on purpose
    return out


def bar(b):
    return f"{int(b // 4) + 1}.{int(b % 4) + 1}"


def consonant_hits(op, X, L, s, e, spb, fi, fo, peak, comp_hf, comp_bb, base, look, cons_range=25, cons_loss=6):
    """Consonants ("s", "sh", "t") the take sings at this clip's edges that the comp, as it plays, turns down.
    A consonant: a 30-300 ms run where the 3.5-10 kHz band is within cons_range dB of the take's own high-band
    peak AND no more than 8 dB under the full band (breaths and hiss are broader and weaker). It counts only when
    the comp continues the word right after it (full band within 30 dB of the peak within 150 ms): where the comp
    leaves a word out, adding its first consonant would leave a stray "s"."""
    op_hf = env_db(sosfiltfilt(HF, op), int(0.01 * SR))[::HOP]
    op_bb = env_db(op, int(0.01 * SR))[::HOP]
    X5, L5 = X // HOP, L // HOP
    if L5 <= 0:
        return []
    hf_peak = float(np.percentile(op_hf[X5:X5 + L5], 99.5))
    sib = (op_hf > hf_peak - cons_range) & (op_hf - op_bb > -8)
    runs, i = [], 0
    while i < len(sib):
        if sib[i]:
            j = i
            while j < len(sib) and sib[j]:
                j += 1
            if 6 <= j - i <= 60:
                runs.append((i, j))
            i = j
        else:
            i += 1
    origin = int(round((s * spb - look / 1000) * SR)) // HOP          # comp frame of the take's frame 0
    fi5, fo5 = int(max(fi, 0.03) * SR) // HOP, int(max(fo, 0.03) * SR) // HOP
    out = []
    for i0, i1 in runs:
        at_start = i0 <= X5 + fi5 and i1 >= X5 - 2
        at_end = i1 > X5 + L5 - fo5 and i0 <= X5 + L5 + 2
        if not (at_start or at_end):
            continue
        if origin + i0 < 0 or origin + i1 > len(comp_hf):
            continue
        lost = float(np.median(op_hf[i0:i1] - np.maximum(comp_hf[origin + i0:origin + i1], hf_peak - 60)))
        if lost < cons_loss:
            continue
        v0, v1 = origin + i1, origin + i1 + int(0.15 * SR) // HOP
        if v1 > len(comp_bb) or np.max(comp_bb[v0:v1]) < peak - 30:
            continue                              # the comp leaves this word out on purpose
        c0, c1 = (i0 - X5) * HOP / SR, (i1 - X5) * HOP / SR                # seconds from the clip start
        if at_start:
            out.append(dict(base, kind="consonant", edge="in", beat=s, lost=lost, c0=c0, c1=c1,
                            move_s=min(0.0, c0 - 0.01), sure=True))
        else:
            ln = (e - s) * spb
            out.append(dict(base, kind="consonant", edge="out", beat=e, lost=lost, c0=c0 - ln, c1=c1 - ln,
                            move_s=max(0.0, c1 - ln + 0.015), sure=True))
    return out


def scan(als, root, tracks, look=150, rng=25, max_fade_ms=40, loss=6, cut_range=15, swell_s=2.0,
         fix_within_ms=150, fix_min_db=10, log=print, consonants=True, cons_range=25, cons_loss=6):
    tempo = float(v(root, ".//Tempo/Manual"))
    spb = 60 / tempo
    ext = look / 1000 / spb
    X = int(look / 1000 * SR)
    w = int(0.02 * SR)
    found = []
    for t in tracks:
        name = v(t, "./Name/EffectiveName")
        off = v(t, "./DeviceChain/Mixer/Speaker/Manual") == "false"
        lane = t.find("./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events")
        clips = [c for c in (list(lane) if lane is not None else []) if c.tag == "AudioClip" and v(c, "./Disabled") != "true"]
        spans = [(float(v(c, "./CurrentStart")), float(v(c, "./CurrentEnd"))) for c in clips]
        comp_hf = comp_bb = None
        if clips and consonants:                 # the track as it plays (every clip, fade and edge)
            try:
                N = int((max(e for _, e in spans) * spb + 2) * SR)
                comp = render_track(t, als, spb, N, SR, None, None, [])
                comp_hf = env_db(sosfiltfilt(HF, comp), int(0.01 * SR))[::HOP]
                comp_bb = env_db(comp, int(0.01 * SR))[::HOP]
            except Exception as ex:
                log(f"  ({name}: consonants not checked, {type(ex).__name__})")
        for ci, c in enumerate(clips):
            if v(c, "./Loop/LoopOn") == "true":
                continue
            s, e = spans[ci]
            L = int((e - s) * spb * SR)
            try:
                op = render_one(open_clip(c, ext, spb), als, spb, L + 2 * X + SR)
            except Exception as ex:
                log(f"  ({name} @ bar {bar(s)}: not checked, {type(ex).__name__})")
                continue
            body = op[X:X + L]
            if not len(body) or np.max(np.abs(body)) < 1e-6:
                continue
            peak = float(np.max(env_db(body, int(0.05 * SR))))
            floor = peak - rng
            fi = float(v(c, "./Fades/FadeInLength") or 0) * spb
            fo = float(v(c, "./Fades/FadeOutLength") or 0) * spb
            base = dict(track=name, clip=c.get("Id"), off=off)

            def covered(t0, t1):
                return any(j != ci and a0 <= t0 + 1e-9 and a1 >= t1 - 1e-9 for j, (a0, a1) in enumerate(spans))

            def quiet(lo, hi):
                seg = op[max(0, lo):max(0, hi)]
                if len(seg) < w:
                    return None
                ed = env_db(seg, int(0.005 * SR))
                i = int(np.argmin(ed))
                return (max(0, lo) + i - X) / SR, float(ed[i]) - peak

            if comp_hf is not None:
                found += consonant_hits(op, X, L, s, e, spb, fi, fo, peak, comp_hf, comp_bb, base, look,
                                        cons_range, cons_loss)
            pre, post = op[X - w:X], op[X:X + w]
            if rms_db(pre) > peak - cut_range and rms_db(post) > floor and not covered(s - ext, s):
                q = quiet(0, X)
                found.append(dict(base, kind="start-cut", beat=s, edge="in", level=rms_db(pre) - peak,
                                  quiet_ms=q[0] * 1000 if q else None, quiet_db=q[1] if q else None))
            if max_fade_ms < fi * 1000 < swell_s * 1000:
                n = min(L, int(fi * SR))
                lead = int(0.03 * SR)
                reg = op[X - lead:X + n]
                ramp = np.concatenate([np.zeros(lead), np.linspace(0, 1, n)])
                hits = ducked_onsets(reg, ramp, floor, loss)
                if hits:
                    d, tt, lo = max(hits)
                    at_ms = tt * 1000 - 30
                    thump = lo > 0.6
                    found.append(dict(base, kind="fade-in", beat=s, edge="in", fade_ms=fi * 1000, at_ms=at_ms, duck=d,
                                      thump=thump, sure=(not thump) and at_ms <= fix_within_ms and d >= fix_min_db))
            pre, post = op[X + L - w:X + L], op[X + L:X + L + w]
            if rms_db(pre) > floor and rms_db(post) > peak - cut_range and not covered(e, e + ext):
                q = quiet(X + L, X + L + X)
                found.append(dict(base, kind="end-cut", beat=e, edge="out", level=rms_db(post) - peak,
                                  quiet_ms=(q[0] - (e - s) * spb) * 1000 if q else None, quiet_db=q[1] if q else None))
            if max_fade_ms < fo * 1000 < swell_s * 1000:
                n = min(L, int(fo * SR))
                hits = ducked_onsets(body[L - n:], np.linspace(1, 0, n), floor, loss)
                if hits:
                    d, tt, lo = max(hits)
                    found.append(dict(base, kind="fade-out", beat=e, edge="out", fade_ms=fo * 1000,
                                      at_ms=(tt - n / SR) * 1000, duck=d, thump=lo > 0.6, sure=False))
    best = {}                                     # one consonant treatment per clip edge: the widest move
    for f in [f for f in found if f["kind"] == "consonant"]:
        k = (f["track"], f["clip"], f["edge"])
        if k not in best or abs(f["move_s"]) > abs(best[k]["move_s"]) or (f["move_s"] == best[k]["move_s"] and f["lost"] > best[k]["lost"]):
            best[k] = f
    found = [f for f in found if f["kind"] != "consonant"] + list(best.values())
    found.sort(key=lambda f: (f["beat"], f["track"]))
    return found


OFF = " (switched-off comp track: copies made from it carry the same problem)"


def consonant_item(f, fix_fade_ms=10):
    off = OFF if f["off"] else ""
    if f["edge"] == "in":
        act = (f"move the clip start {abs(f['move_s']) * 1000:.0f} ms earlier (10 ms before the consonant; a clip "
               "ending right there is trimmed to match)" if f["move_s"] < 0 else "") or ""
        fix = "; ".join(x for x in (f"a {fix_fade_ms:g} ms fade-in", act) if x)
        where_ = f"{f['c0'] * 1000:+.0f} to {f['c1'] * 1000:+.0f} ms from the clip start"
    else:
        act = (f"end {f['move_s'] * 1000:.0f} ms later (into empty space, or by moving the comp switch when the "
               "next take starts after the consonant)" if f["move_s"] > 0 else "")
        fix = "; ".join(x for x in (f"a {fix_fade_ms:g} ms fade-out", act) if x)
        where_ = f"{f['c0'] * 1000:+.0f} to {f['c1'] * 1000:+.0f} ms from the clip end"
    return dict(tool="edges", kind="consonant", severity="medium", track=f["track"], where=f"bar {bar(f['beat'])}",
                problem=(f"the take sings a consonant (an \"s\", \"sh\" or \"t\") at {where_} that the comp plays "
                         f"{f['lost']:.0f} dB down, and the word goes on right after it: the word is heard without "
                         f"its first sound" + off),
                fix=fix + " (recommended). Re-checked after the fix; undone if the track there plays more than 2.5 dB "
                          "above the take's own audio (two takes doubling)",
                applies="set", targets=[[f["clip"], f["edge"], "consonant", f["move_s"]]], recommended=True,
                expect_db=round(f["lost"], 1))


def one(f, fix_fade_ms=10):
    """A single edge as its own item (for `--tracks`: pick exactly which fades to shorten)."""
    if f["kind"] == "consonant":
        return consonant_item(f, fix_fade_ms)
    off = OFF if f["off"] else ""
    if f["kind"] in ("fade-in", "fade-out"):
        side = "from the clip start" if f["kind"] == "fade-in" else "before the clip end"
        return dict(tool="edges", kind=f["kind"], severity="medium" if f.get("sure") else "low", track=f["track"],
                    where=f"bar {bar(f['beat'])}",
                    problem=(f"a {f['fade_ms']:.0f} ms {f['kind']} turns down a sound that starts {abs(f['at_ms']):.0f} ms "
                             f"{side} by {f['duck']:.0f} dB" + (". It is a low thump: the fade may be hiding it on "
                                                                "purpose" if f["thump"] else "") + off),
                    fix=f"shorten the {f['kind']} to {fix_fade_ms:g} ms" + (" (recommended: clear-cut)" if f.get("sure")
                                                                             else ": listen first"),
                    applies="set", targets=[[f["clip"], f["edge"]]], recommended=bool(f.get("sure")),
                    expect_db=round(f["duck"], 1))
    q = (f"; the nearest quiet point is {f['quiet_ms']:+.0f} ms away ({f['quiet_db']:+.0f} dB)"
         if f.get("quiet_ms") is not None else "")
    return dict(tool="edges", kind=f["kind"], severity="low", track=f["track"], where=f"bar {bar(f['beat'])}",
                problem=(f"sound runs across the clip {'start' if f['kind'] == 'start-cut' else 'end'} "
                         f"({f['level']:+.0f} dB against the clip's peak) and no other clip covers it" + off),
                fix="listen first: if a sound is cut, move the edge in Live to the quiet point" + q,
                applies="manual", targets=[[f["clip"], f["edge"]]], recommended=False)


def findings(found, fix_fade_ms=10):
    """One item per clear-cut fade (recommended); per track, one item for its listen-first fades and one
    listen-only item for its possible cuts, so a song with many comp edits stays reviewable."""
    out = []
    add = lambda **k: out.append(dict(id=f"edges-{len(out) + 1}", tool="edges", **k))
    for f in [f for f in found if f["kind"] == "consonant"]:
        out.append(dict(consonant_item(f, fix_fade_ms), id=f"edges-{len(out) + 1}"))
    for f in [f for f in found if f.get("sure") and f["kind"] != "consonant"]:
        add(kind=f["kind"], severity="medium", track=f["track"], where=f"bar {bar(f['beat'])}",
            problem=(f"a {f['fade_ms']:.0f} ms {f['kind']} turns down a word that starts {abs(f['at_ms']):.0f} ms from "
                     f"the clip start by {f['duck']:.0f} dB: its first sound is ducked" + (OFF if f["off"] else "")),
            fix=f"shorten the fade-in to {fix_fade_ms:g} ms (recommended: clear-cut)", applies="set",
            targets=[[f["clip"], f["edge"]]], recommended=True, expect_db=round(f["duck"], 1))
    by = {}
    for f in found:
        if f.get("sure") or f["kind"] == "consonant":
            continue
        grp = "fades" if f["kind"] in ("fade-in", "fade-out") else "cuts"
        by.setdefault((f["track"], grp), []).append(f)
    for (trk, grp), fs in sorted(by.items(), key=lambda kv: kv[1][0]["beat"]):
        off = OFF if fs[0]["off"] else ""
        bars = ", ".join(bar(f["beat"]) for f in fs[:12]) + ("…" if len(fs) > 12 else "")
        if grp == "fades":
            th = sum(f["thump"] for f in fs)
            add(kind="fades", severity="low", track=trk, where=f"{len(fs)} fade(s): bars {bars}",
                problem=(f"{len(fs)} fade(s) turn down a sound that starts inside them (up to "
                         f"{max(f['duck'] for f in fs):.0f} dB)" + (f"; {th} of them are low thumps the fade may be "
                                                                     "hiding on purpose" if th else "") + off),
                fix=(f"listen first; approving shortens all {len(fs)} to {fix_fade_ms:g} ms. To pick some, run "
                     f"`hypnomix edges SET --tracks \"{trk}\"` and apply those ids"),
                applies="set", targets=[[f["clip"], f["edge"]] for f in fs], recommended=False,
                expect_db=round(max(f["duck"] for f in fs), 1))
        else:
            ns, ne = sum(f["kind"] == "start-cut" for f in fs), sum(f["kind"] == "end-cut" for f in fs)
            add(kind="cuts", severity="low", track=trk, where=f"{len(fs)} edge(s): bars {bars}",
                problem=(f"sound runs across {ns} clip start(s) and {ne} clip end(s) with no other clip covering "
                         "it: part of a sound may be missing" + off),
                fix=("listen first; if a sound is cut, move that edge in Live to a quiet point (`hypnomix edges` "
                     "lists each with its nearest quiet point). Most end cuts are comp switches between takes"),
                applies="manual", targets=[[f["clip"], f["edge"]] for f in fs], recommended=False)
    return out


def _f(c, p):
    return float(v(c, p) or 0)


def _setf(c, p, val):
    if c.find(p) is not None:
        c.find(p).set("Value", repr(float(val)))


def _per(c, spb):
    """Content units per beat: loop/start values are beats for warped clips, seconds for unwarped ones."""
    return 1.0 if v(c, "./IsWarped") == "true" else spb


def _fade(c, edge, beats):
    k, d = ("FadeInLength", "IsDefaultFadeIn") if edge == "in" else ("FadeOutLength", "IsDefaultFadeOut")
    if c.find(f"./Fades/{k}") is None:
        return False
    c.find(f"./Fades/{k}").set("Value", repr(beats))
    if c.find(f"./Fades/{d}") is not None:
        c.find(f"./Fades/{d}").set("Value", "false")
    return True


def _set_start(c, ns, spb):
    """Move a loop-off clip's start, keeping what plays at every other moment: Time, CurrentStart and LoopStart
    move together (StartRelative stays, or the audio would shift twice)."""
    d = ns - _f(c, "./CurrentStart")
    c.set("Time", repr(float(ns)))
    _setf(c, "./CurrentStart", ns)
    _setf(c, "./Loop/LoopStart", _f(c, "./Loop/LoopStart") + d * _per(c, spb))


def _set_end(c, ne, spb):
    d = ne - _f(c, "./CurrentEnd")
    _setf(c, "./CurrentEnd", ne)
    _setf(c, "./Loop/LoopEnd", _f(c, "./Loop/LoopEnd") + d * _per(c, spb))


def fix_consonant(lane, c, edge, move_s, spb, fix_fade_ms=10):
    """The consonant fixes, in order: shorten the fade that eats it; move the start to 10 ms before it (trimming a
    clip that ends right there and any muted clip under it); at an end, extend into empty space or move a comp
    switch later when the next take starts after the consonant. Returns (what was done, clips touched)."""
    fb = fix_fade_ms / 1000 / spb
    sib = [x for x in lane if x.tag == "AudioClip" and v(x, "./Disabled") != "true" and x is not c]
    muted = [x for x in lane if x.tag == "AudioClip" and v(x, "./Disabled") == "true"]
    cs, ce = _f(c, "./CurrentStart"), _f(c, "./CurrentEnd")
    if edge == "in":
        _fade(c, "in", fb)
        d = -move_s / spb
        if d * spb < 0.001:                       # under a millisecond: nothing to move
            return "fade-in shortened", [c]
        ns = cs - d
        if _f(c, "./Loop/LoopStart") - d * _per(c, spb) < 0:
            return "fade-in shortened (the take starts too late to move the edge earlier)", [c]
        over = [x for x in sib if _f(x, "./CurrentStart") < cs and _f(x, "./CurrentEnd") > ns]
        if not all(abs(_f(x, "./CurrentEnd") - cs) < 1e-4 and _f(x, "./CurrentStart") < ns - 1e-4 for x in over):
            return "fade-in shortened; start NOT moved (another clip plays there): listen", [c]
        for x in over:                            # contiguous: hand it the space
            _set_end(x, ns, spb)
            fo = _f(x, "./Fades/FadeOutLength")
            _fade(x, "out", min(fb, fo) if fo > 0 else fb)
        for x in muted:                           # muted clips under the new start: trimmed too
            xs, xe = _f(x, "./CurrentStart"), _f(x, "./CurrentEnd")
            if xs < ns < xe <= cs + 1e-4:
                _set_end(x, ns, spb)
        _set_start(c, ns, spb)
        return f"fade-in shortened, start moved {-move_s * 1000:.0f} ms earlier", [c] + over
    long_fade = _f(c, "./Fades/FadeOutLength") > fb * 1.5
    _fade(c, "out", fb)
    d = move_s / spb
    if d * spb < 0.001:
        return "fade-out shortened", [c]
    ne = ce + d
    over = [x for x in sib if _f(x, "./CurrentStart") < ne and _f(x, "./CurrentEnd") > ce]
    if not over:
        _set_end(c, ne, spb)
        return f"fade-out shortened, end moved {move_s * 1000:.0f} ms later", [c]
    if long_fade:
        return "fade-out shortened (edge kept)", [c]
    x = over[0]
    if len(over) == 1 and abs(_f(x, "./CurrentStart") - ce) < 1e-4 and _f(x, "./CurrentEnd") - ne > 1.0 \
            and v(x, "./Loop/LoopOn") != "true":
        _set_end(c, ne, spb)                      # this take finishes the consonant, then the next takes over
        _set_start(x, ne, spb)
        _fade(x, "in", fb)
        return f"comp switch moved {move_s * 1000:.0f} ms later", [c, x]
    return "fade-out shortened; end NOT moved (the next clip plays there): listen", [c]


def _peaks_jump(before, after, t0, t1, limit=2.5):
    i0, i1 = max(0, int(t0 * SR)), int(t1 * SR)
    pb = np.max(env_db(before[i0:i1], int(0.01 * SR))) if i1 > i0 else -240
    pa = np.max(env_db(after[i0:i1], int(0.01 * SR))) if i1 > i0 else -240
    return float(pa - pb) > limit, float(pa - pb)


def apply(root, items, fix_fade_ms=10, als=None, passes=3, log=print):
    """Apply approved items. Consonant fixes are re-checked (up to `passes` rounds, only on the clips the
    approved fixes touched), then the track is rendered before and after: where its peak jumps over 2.5 dB at a
    changed spot (two takes doubling), that change is undone."""
    tempo = float(v(root, ".//Tempo/Manual"))
    spb = 60 / tempo
    beats = fix_fade_ms / 1000 / spb
    tracks = {v(t, "./Name/EffectiveName"): t for t in root.find(".//Tracks") if t.tag == "AudioTrack"}
    before = {}                                   # track name -> its element before any change (for the compare)
    edits = []                                    # (track, spot seconds, [(lane, index, original clip)], what)
    done = 0

    def lane_of(name):
        return tracks[name].find("./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events")

    def run(f, cid, edge, kind=None, move=0.0, expect=0.0):
        nonlocal done
        lane = lane_of(f["track"])
        c = next((x for x in lane if x.get("Id") == cid), None) if lane is not None else None
        if c is None:
            return None
        before.setdefault(f["track"], copy.deepcopy(tracks[f["track"]]))
        snap = [(i, copy.deepcopy(x)) for i, x in enumerate(lane) if x.tag == "AudioClip"]
        spot = (_f(c, "./CurrentStart") if edge == "in" else _f(c, "./CurrentEnd")) * spb
        if kind == "consonant":
            what, touched = fix_consonant(lane, c, edge, move, spb, fix_fade_ms)
        else:
            what, touched = ("fade shortened", [c]) if _fade(c, edge, beats) else (None, [])
        if what is None:
            return None
        ids = {x.get("Id") for x in touched}
        edits.append((f["track"], spot, [(i, o) for i, o in snap if o.get("Id") in ids], what, expect))
        done += 1
        return ids

    touched = {}
    for f in items:
        if f["applies"] != "set" or f["track"] not in tracks:
            continue
        for tg in f.get("targets", []):
            ids = run(f, *tg, expect=float(f.get("expect_db") or 0)) if len(tg) > 2 else \
                run(f, *tg, None, 0.0, float(f.get("expect_db") or 0))
            if ids and len(tg) > 2:
                touched.setdefault(f["track"], set()).update(ids)
    # re-run until clean, on the clips the approved consonant fixes touched
    for _ in range(max(0, passes - 1) if als else 0):
        more = 0
        for name, ids in list(touched.items()):
            again = [g for g in scan(als, root, [tracks[name]], log=lambda *_: None)
                     if g["kind"] == "consonant" and g["clip"] in ids]
            for g in again:
                new = run(dict(track=name), g["clip"], g["edge"], "consonant", g["move_s"], g["lost"])
                if new:
                    ids |= new
                    more += 1
        if not more:
            break
    # render-compare each changed spot: a peak jump means two takes now play at once there
    undone = []
    if als:
        for name in {e[0] for e in edits}:
            try:
                n = int((max(_f(c, "./CurrentEnd") for c in lane_of(name) if c.tag == "AudioClip") * spb + 2) * SR)
                rb = render_track(before[name], als, spb, n, SR, None, None, [])
                ra = render_track(tracks[name], als, spb, n, SR, None, None, [])
            except Exception as ex:
                log(f"  ({name}: not render-checked, {type(ex).__name__})")
                continue
            for tr, spot, snap, what, expect in reversed([e for e in edits if e[0] == name]):
                # a fix may bring a ducked sound back up to the take's own level, never above it: louder than both
                # the old render and the clips' own unfaded audio means something else now plays there (two
                # takes doubling, or audio shifted onto the wrong spot)
                ids = {o.get("Id") for _, o in snap}
                own = ET.Element("AudioTrack")
                ET.SubElement(ET.SubElement(own, "Name"), "EffectiveName").set("Value", "own")
                ev = ET.SubElement(ET.SubElement(ET.SubElement(own, "X"), "ArrangerAutomation"), "Events")
                for x in lane_of(name):
                    if x.tag == "AudioClip" and x.get("Id") in ids:
                        y = copy.deepcopy(x)
                        _fade(y, "in", 0.0); _fade(y, "out", 0.0)
                        if y.find("./Disabled") is not None:
                            y.find("./Disabled").set("Value", "false")
                        ev.append(y)
                try:
                    ro = render_track(own, als, spb, n, SR, None, None, [])
                except Exception:
                    ro = rb
                ref = np.maximum(np.abs(rb), np.abs(ro))
                bad, jump = _peaks_jump(ref, ra, spot - 0.1, spot + 0.25, limit=2.5)
                if bad:
                    lane = lane_of(name)
                    for i, orig in snap:              # put those clips back as they were
                        cur = next((x for x in lane if x.get("Id") == orig.get("Id")), None)
                        if cur is not None:
                            k = list(lane).index(cur)
                            lane.remove(cur)
                            lane.insert(k, orig)
                    undone.append(f"{name} at {int(spot // 60)}:{spot % 60:05.2f}: undone ({what}; the peak there "
                                  f"is {jump:+.1f} dB above both the old render and the take's own audio: two takes doubling)")
                    done -= 1
    for u in undone:
        log("  " + u)
    return max(0, done)


def main():
    ap = argparse.ArgumentParser(prog="hypnomix edges", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    from hypnomix.session import liveversion as LV; LV.add_force_flag(ap)
    ap.add_argument("als"); ap.add_argument("--tracks", nargs="*", default=[])
    ap.add_argument("--names", help="names.json from `hypnomix name` (finds vocal tracks by what they are)")
    ap.add_argument("--all-tracks", action="store_true", help="every audio track (default: vocal tracks)")
    ap.add_argument("--look", type=float, default=150, help="ms looked at past each edge")
    ap.add_argument("--range", type=float, default=25, help="dB under the clip peak that still counts as sound")
    ap.add_argument("--max-fade-ms", type=float, default=40, help="fades shorter than this are never flagged")
    ap.add_argument("--loss", type=float, default=6, help="dB a sound's start must be ducked by to count")
    ap.add_argument("--cut-range", type=float, default=15, help="sound past an edge within this many dB of the peak counts as cut")
    ap.add_argument("--swell-s", type=float, default=2.0, help="fades longer than this are deliberate swells: skipped")
    ap.add_argument("--fix-fade-ms", type=float, default=10)
    ap.add_argument("--json"); ap.add_argument("--apply", metavar="NEW.als"); ap.add_argument("--ids")
    a = ap.parse_args()
    src = Path(a.als)
    root = ET.fromstring(read_gz(src))
    tracks = pick_tracks(root, a.names, set(a.tracks), a.all_tracks)
    found = scan(str(src), root, tracks, a.look, a.range, a.max_fade_ms, a.loss, a.cut_range, a.swell_s)
    fs = findings(found, a.fix_fade_ms)
    print(f"{src.name}: {len(tracks)} track(s) checked, {len(fs)} edge finding(s)")
    if a.tracks:                              # tracks asked for by name: every edge on its own line, own id
        fs = [dict(one(g, a.fix_fade_ms), id=f"edges-{n}") for n, g in enumerate(found, 1)]
    for f in fs:
        print(f"  {f['id']:<9} {f['track']:<24} {f['kind']:<9} {f['where']}\n            {f['problem']}\n            → {f['fix']}")
    if a.json:
        Path(a.json).write_text(json.dumps({"tool": "edges", "set": str(src), "findings": fs}, indent=1), encoding="utf-8")
    if a.apply:
        if Path(a.apply).resolve() == src.resolve():
            sys.exit("refusing to overwrite the set; give a new file name")
        if Path(a.apply).resolve().parent != src.resolve().parent:
            sys.exit(f"write the new set in the same folder as the original ({src.resolve().parent})")
        want = {x.strip() for x in (a.ids or "").split(",") if x.strip()}
        if not want:
            sys.exit("say which: --ids edges-1,… (nothing is changed by default)")
        n = apply(root, [f for f in fs if f["id"] in want], a.fix_fade_ms, als=str(src))
        data = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")
        from hypnomix.session import liveversion as LV
        LV.guard_write(root)                # refuses a set saved by a Live newer than the newest tested
        with gzip.open(a.apply, "wb") as fh:
            fh.write(data)
        print(f"wrote {a.apply}: {n} edge fix(es) (fades {a.fix_fade_ms:g} ms; consonant edges moved where asked)")


if __name__ == "__main__":
    main()
