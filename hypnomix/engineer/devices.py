#!/usr/bin/env python3
"""Check the settings of Live's own devices on every track by what they actually do, and suggest better ones.

Every track's clips are rendered from the set (no Live needed) and played through its chain of Live devices in
order, so each device is judged on the signal it really gets:

  Compressor, Glue   how much it turns the part down while it plays (median and loud moments), how much of the time
                     it works. Flagged when it barely touches the part, squashes it, releases faster than two cycles
                     of the bass notes (it bends the waveform), or clamps drum transients with a near-zero attack.
                     The suggestion keeps your ratio (unless it is limiting) and fits the threshold to a sensible
                     amount of reduction for that kind of part, with attack and release for the part and the tempo:
                       lead vocal 3-6 dB · harmonies 2-5 · bass 3-6 · drums 2-4 · keys, guitar, other 2-4 ·
                       groups 1-3 · Main 0.5-2
  Gate               threshold against the track's own noise floor and phrase level: above the phrases it chops
                     words, below the noise it does nothing
  Limiter            on a track: how hard it works (more than ~3 dB on the loud moments = turn its Gain down)
  EQ Eight           a part that isn't bass or kick with real energy under 80 Hz and no low cut: suggest one

Glue's Range and Release Auto (as a 300 ms release) and both compressors' Dry/Wet are modelled: Range caps the
reduction, and Dry/Wet mixes the dry signal back in, so what is measured is what is heard. A compressor with Dry/Wet under 97 % (parallel
compression) is listed with what it does, not judged (the targets above are for a compressor on the whole signal),
and the level after it is still modelled.

Third-party plug-ins are skipped (their settings aren't readable from the set); after one, the level reaching the
devices is unknown, so those devices are listed but not judged. Compressors with an external sidechain are
ducking, not compressing their own track: see `hypnomix duck` / `hypnomix sidechain`. MIDI tracks need their
audio exported (--stems DIR, files named like the tracks).

Every suggestion is an option; --apply writes a NEW set. The compressor is a model of Live's (see `hypnomix
sidechain`): check by ear.

The renders it listens to are a scratch copy of the tracks (about 10 MB per track-minute, so a 60-track, 5-minute set
is about 3 GB). They are written to a folder named hypnomix-render-… under ~/.hypnomix/cache/tmp, announced in one line
when it is over about 1 GB, and removed when the command ends (an error or Ctrl-C too). Nothing is left in the temp folder.

Usage:
  hypnomix devices SET.als [--names names.json] [--stems DIR] [--track NAME …] [--json OUT.json]
  hypnomix devices SET.als --apply NEW.als --ids devices-2,devices-5
  hypnomix devices SET.als --json OUT.json --focus "Lead Vocal" --focus Bass

--apply --ids judges only the tracks that own those ids (the other tracks are numbered, not judged), and --focus does the
same for a check: the ids and the findings of the tracks it names are exactly the whole-set run's. `fix` and `ab` use them,
so one approved fix costs one track's analysis instead of every track's.
"""
import argparse, gzip, json, math, os, re, subprocess, sys, tempfile
from hypnomix.core.gz import read_gz
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from hypnomix.engineer import sidechain as SC

v = lambda n, p: (n.find(p).get("Value") if n.find(p) is not None else None)
safe = lambda n: re.sub(r'[\\/:*?"<>|]', "-", n)
PLUGINS = ("AuPluginDevice", "PluginDevice", "VstPluginDevice", "Vst3PluginDevice")
NEW_COMP = dict(kind="compressor", model=0, ratio=4.0, knee=6.0, attack=10.0, release=100.0, lookahead=0, sc_gain_db=0.0,
                eq_on=False, eq_mode=5, eq_freq=100.0, eq_q=0.707, eq_gain=0.0, dry_wet=1.0, range_db=None, threshold_db=-20.0)
FULL_WET = 0.97          # Dry/Wet (Mix) at or over this is a compressor on the whole signal (dry under -30 dB)
TARGET = {"lead": (3, 6), "harmony": (2, 5), "bass": (3, 6), "drums": (2, 4), "other": (2, 4), "group": (1, 3),
          "main": (0.5, 2)}


def hx(*args):
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def role_of(name, label, t):
    lab = label or ""
    if lab.startswith("Lead Vocal"):
        return "lead"
    if re.match(r"(Harmony|Backing Vocal|Vocal)\b", lab):
        return "harmony"
    if lab.startswith("Bass") or re.search(r"\bbass|808(?! kit)|\bsub\b", name, re.I):
        return "bass"
    if re.match(r"(Drums|Kick|Snare|Hats|Perc)", lab) or any(d.tag == "DrumGroupDevice" for d in t.iter()) \
            or re.search(r"drum|kit|kick|snare|perc", name, re.I):
        return "drums"
    return "other"


def manual(d, name, default=None):
    e = d.find(f"./{name}/Manual")
    return float(e.get("Value")) if e is not None and e.get("Value") not in (None, "true", "false") else default


RANGES = {  # usual attack / release (ms) per kind of part: outside them, a suggestion
    "lead": ((3, 30), (40, 300)), "harmony": ((3, 30), (40, 300)), "bass": ((5, 40), (80, 400)),
    "drums": ((5, 40), (40, 250)), "other": ((1, 50), (30, 500)), "group": ((1, 50), (50, 800)), "main": ((1, 50), (50, 800))}


def active(y, floor_rel=25):
    blk = int(0.05 * SC.SR)
    n = len(y) // blk
    if n < 4:
        return np.zeros(len(y), bool), -120.0, -120.0
    r = 20 * np.log10(np.sqrt((y[: n * blk].reshape(n, blk) ** 2).mean(1)) + 1e-9)
    act = r > r.max() - floor_rel
    noise = float(np.percentile(r, 10))
    phrase = float(np.median(r[act])) if act.any() else -120.0
    m = np.repeat(act, blk)
    return np.pad(m, (0, len(y) - len(m))), noise, phrase


def comp_settings(d):
    c = SC.read_glue(d) if d.tag == "GlueCompressor" else SC.read_compressor(d)
    c["sc_gain_db"] = 0.0                                      # its own signal: no external sidechain gain
    if d.tag == "GlueCompressor":
        out = manual(d, "Makeup", 0.0)
    else:
        out = manual(d, "Gain", 0.0)
        if v(d, "./GainCompensation/Manual") == "true":
            out += (-c["threshold_db"]) * (1 - 1 / max(c["ratio"], 1.0)) / 2
    return c, out


def measure_comp(x, act, c):
    """(gain heard per sample in dB, measures): the reduction with Range and the release model, and then Dry/Wet (Mix)
    mixing the dry signal back in, so a parallel compressor is judged on what is really heard."""
    gr = SC.heard(SC.gain_reduction(SC.detector(x, c), c), c)
    a = gr[act] if act.any() else gr
    return gr, dict(median=float(-np.median(a)), loud=float(-np.percentile(a, 5)), working=float(np.mean(a < -1.0)))


def parallel_text(label, c, m):
    """The line for a compressor whose Dry/Wet (Mix) mixes the dry signal back in: what is heard, not judged."""
    pct = 100 * float(c.get("dry_wet", 1.0))
    if pct < 0.05:
        return f"'{label}' has Dry/Wet at 0 %, so none of its compression is heard: it isn't judged"
    return (f"'{label}' mixes {100 - pct:.0f} % dry signal back in (Dry/Wet {pct:.0f} %): parallel compression, heard as "
            f"{m['median']:.1f} dB while the part plays ({m['loud']:.0f} dB on loud moments). Its usual ranges are for a "
            "fully wet compressor, so it isn't judged and nothing is changed; the level after it is modelled")


def fit_threshold(x, act, c, target):
    lvl = SC.detector(x, c)
    lo, hi = float(np.percentile(lvl[act], 5)) - 30 if act.any() else -60.0, float(lvl.max()) + 1
    for _ in range(16):
        c["threshold_db"] = (lo + hi) / 2
        g = SC.heard(SC.gain_reduction(lvl, c), c)
        dmed = float(-np.median(g[act])) if act.any() else 0.0
        if dmed > target:
            lo = c["threshold_db"]
        else:
            hi = c["threshold_db"]
    c["threshold_db"] = (lo + hi) / 2
    return c


def times_for(role, tempo, f0):
    """(attack ms, release ms) suggestions for a part: transients through on drums and bass, release in time."""
    beat = 60000.0 / tempo
    sixteenth = beat / 4
    if role == "drums":
        att, rel = 15.0, float(np.clip(sixteenth, 50, 150))
    elif role == "bass":
        att, rel = 15.0, float(np.clip(beat / 2, 100, 250))
    elif role in ("lead", "harmony"):
        att, rel = 8.0, float(np.clip(sixteenth * 1.5, 60, 150))
    elif role in ("group", "main"):
        att, rel = 10.0, float(np.clip(beat / 2, 100, 400))
    else:
        att, rel = 10.0, float(np.clip(sixteenth * 2, 80, 200))
    if f0:
        rel = max(rel, 2 * 1000.0 / f0)                       # never faster than two cycles of the lowest note
    return att, rel


def id_numbers(ids):
    """{12, 15} for "devices-12,devices-15" (a set or list of ids too); an empty set when there is nothing to go by (no ids,
    or one that is not a devices id): the whole set is then judged, as it always was."""
    nums = set()
    for i in ([x for x in ids.split(",")] if isinstance(ids, str) else list(ids or [])):
        m = re.fullmatch(r"\s*devices-(\d+)\s*", str(i))
        if not m:
            if str(i).strip():
                return set()
            continue
        nums.add(int(m.group(1)))
    return nums


def count_items(name, role, t, wav, tempo):
    """(how many items review_track will make for this track, its notes), without judging it: the same walk over the
    chain on a few seconds of noise. When the count depends on the audio itself (an EQ Eight with no low cut gets one more
    item when the part has rumble) the walk is made again on the track's own audio (`wav`, its render), with the
    judging left out: only its path through the chain. None when the walk fails: the track is then judged for real.
    Used to number the tracks that own none of the ids being applied or re-checked."""
    try:
        probe = {"light": True, "noise": True}
        x = np.random.default_rng(0).normal(0.0, 0.05, SC.SR * 3) if wav is not None else None
        items, notes = review_track(name, role, t, x, tempo, probe=probe)
        if probe.get("audio_decides"):
            probe = {"light": True}                             # the track's own audio this time, still no judging
            items, notes = review_track(name, role, t, SC.load_mono(str(wav)), tempo, probe=probe)
    except Exception:
        return None
    return len(items), notes


def judge_compressor(x, act, c, role, tempo, f0):
    """A compressor's settings `c` judged on the signal `x` it gets (`act`: where the part plays): (gain reduction
    per sample, measured now, suggested settings, measured with them, problems, (target low, high) dB). Shared by
    the Live check and the REAPER one (ReaComp, `workflow/devices_project.py`)."""
    gr, m = measure_comp(x, act, c)
    lo, hi = TARGET[role]
    problems = []
    if m["median"] < 0.5 * lo:
        problems.append(f"it barely works ({m['median']:.1f} dB while the part plays; threshold above the signal)")
    elif m["median"] > 1.5 * hi:
        problems.append(f"it squashes the part ({m['median']:.1f} dB while it plays, {m['loud']:.0f} dB on loud moments)")
    if f0 and not c.get("auto_release") and c["release"] < 2 * 1000.0 / f0:
        problems.append(f"its release ({c['release']:.0f} ms) is faster than two cycles of the lowest note "
                        f"({2000 / f0:.0f} ms): it bends the waveform (distortion on the low end)")
    if role == "drums" and c["attack"] < 3 and m["median"] > 1:
        problems.append(f"its attack ({c['attack']:g} ms) clamps every transient")
    new = dict(c)
    att, rel = times_for(role, tempo, f0)
    (alo, ahi), (rlo, rhi) = RANGES[role]
    if not (alo <= new["attack"] <= ahi):
        problems.append(f"its attack ({new['attack']:g} ms) is outside the usual {alo}-{ahi} ms for this kind of part")
        new["attack"] = att
    if c.get("auto_release"):
        pass
    elif not (rlo <= new["release"] <= rhi):
        problems.append(f"its release ({new['release']:.0f} ms) is outside the usual {rlo}-{rhi} ms for this kind of part")
        new["release"] = rel
    if f0 and new["release"] < 2 * 1000.0 / f0:
        new["release"] = max(rel, 2 * 1000.0 / f0)
    if new["ratio"] > 8 and role not in ("main",):
        new["ratio"] = 4.0
    new = fit_threshold(x, act, new, (lo + hi) / 2)
    _, m2 = measure_comp(x, act, new)
    return gr, m, new, m2, problems, (lo, hi)


def review_track(name, role, t, x, tempo, root_tag="AudioTrack", probe=None):
    """Walk the track's devices in order on its signal; return (findings, notes)."""
    from hypnomix.core import dsp
    out, notes = [], []
    if x is None:
        return out, [f"{name}: no audio (MIDI: export it and pass --stems)"]
    devs = t.find("./DeviceChain/DeviceChain/Devices")
    known = True
    f0 = SC.lowest_note(x) if role in ("bass", "drums") else None
    lo_cut_seen = False
    for d in (list(devs) if devs is not None else []):
        if v(d, "./On/Manual") == "false":
            continue
        label = v(d, "./UserName") or d.tag
        if d.tag in PLUGINS:
            known = False
            continue
        if d.tag == "StereoGain":
            x = x * float(manual(d, "Gain", 1.0) or 1.0)       # Utility gain is linear
            continue
        if d.tag == "Eq8":
            for b in d.iter():
                if b.tag.startswith("Bands.") and v(b, "./ParameterA/IsOn/Manual") == "true" and \
                        int(float(v(b, "./ParameterA/Mode/Manual") or 3)) in (0, 1):
                    lo_cut_seen = True
            continue
        act, noise, phrase = active(x)
        if d.tag in ("Compressor2", "GlueCompressor"):
            c, outgain = comp_settings(d)
            if c.get("sc_on") and c.get("source_target") and "Track." in c["source_target"]:
                notes.append(f"{name}: '{label}' is fed by another track (ducking): see `hypnomix duck` / `sidechain`")
                gr, _ = measure_comp(x, act, dict(c, sc_on=False))
                continue
            if not known:
                out.append(dict(kind="unknown", device=label, el=d, problem=f"after a plug-in: the level reaching "
                                f"'{label}' is unknown, so it isn't judged"))
                continue
            if c.get("dry_wet", 1.0) < FULL_WET:          # parallel: what is heard is modelled, the targets don't apply
                gr, m = measure_comp(x, act, c)
                out.append(dict(kind="unknown", device=label, el=d, problem=parallel_text(label, c, m)))
                x = x * dsp.undb(gr) * dsp.undb(outgain)
                continue
            if probe is not None and probe.get("light"):     # counting on the real audio: its path through the chain, no judging
                gr, _ = measure_comp(x, act, c)
                out.append(dict(kind="compressor"))
                x = x * dsp.undb(gr) * dsp.undb(outgain)
                continue
            gr, m, new, m2, problems, (lo, hi) = judge_compressor(x, act, c, role, tempo, f0)
            out.append(dict(kind="compressor", device=label, el=d, cur=c, new=new, m=m, m2=m2, problems=problems,
                            target=(lo, hi)))
            x = x * dsp.undb(gr) * dsp.undb(outgain)
            continue
        if d.tag == "Gate" and known:
            thr = 20 * math.log10(max(1e-9, manual(d, "Threshold", 0.001)))
            problems, new_thr = [], None
            if thr > phrase - 6:
                problems.append(f"its threshold ({thr:.0f} dB) is near the phrases ({phrase:.0f} dB): it chops words")
            elif thr < noise + 3:
                problems.append(f"its threshold ({thr:.0f} dB) is under the noise floor ({noise:.0f} dB): it never closes")
            if problems:
                new_thr = float(np.clip(noise + 0.4 * (phrase - noise), noise + 6, phrase - 12))
            out.append(dict(kind="gate", device=label, el=d, thr=thr, noise=noise, phrase=phrase, problems=problems,
                            new_thr=new_thr))
            continue
        if d.tag == "Limiter" and known:
            gain, ceil = manual(d, "Gain", 0.0), manual(d, "Ceiling", -0.3)
            blk = int(0.01 * SC.SR); n = len(x) // blk
            pk = 20 * np.log10(np.abs(x[: n * blk]).reshape(n, blk).max(1) + 1e-9) + gain
            red = np.maximum(0.0, pk - ceil)
            a_ = red[np.repeat(act, 1)[: n * blk].reshape(n, blk).any(1)] if act.any() else red
            loud = float(np.percentile(a_, 95)) if len(a_) else 0.0
            problems, new_gain = [], None
            if loud > 3 and role not in ("main",):
                problems.append(f"it takes {loud:.1f} dB off the loud moments: on a track that is crushing, not catching peaks")
                new_gain = gain - (loud - 1.5)
            out.append(dict(kind="limiter", device=label, el=d, loud=loud, gain=gain, problems=problems, new_gain=new_gain))
            x = np.clip(x * dsp.undb(gain), -dsp.undb(ceil), dsp.undb(ceil))
            continue
    if role not in ("bass", "drums") and not lo_cut_seen and devs is not None and any(d.tag == "Eq8" for d in devs):
        if probe is not None and probe.get("noise"):        # counting on noise: one more item follows or not by the audio
            probe["audio_decides"] = True
            return out, notes
        spec = np.abs(np.fft.rfft(x[: SC.SR * 60] if len(x) > SC.SR else x))
        f = np.fft.rfftfreq(min(len(x), SC.SR * 60), 1 / SC.SR)
        e_low = 10 * math.log10(max(1e-12, (spec[f < 80] ** 2).sum() / max(1e-12, (spec ** 2).sum())))
        if e_low > -25:
            out.append(dict(kind="eq-lowcut", device="EQ Eight", el=None, e_low=e_low,
                            problems=[f"{e_low:.0f} dB of its energy is under 80 Hz with no low cut: rumble under the bass"]))
    return out, notes


def propose(set_path, names_json=None, stems=None, tracks=None, ids=None, focus=None):
    """(items, notes, root, tempo). With `ids` (--apply --ids) or `focus` (the tracks of the approved findings, for the
    checks before and after a fix) only the tracks that matter are judged; the others are still numbered (their items are
    None in the list) so every id is the one the whole-set run gives."""
    set_path = Path(set_path)
    root = ET.fromstring(read_gz(set_path))
    tempo = float(v(root, ".//Tempo/Manual"))
    labels = {}
    if names_json and Path(names_json).exists():
        labels = {r["old"]: str(r.get("final") or r.get("label") or "") for r in json.loads(Path(names_json).read_text(encoding="utf-8", errors="replace"))["tracks"]
                  if float(r.get("confidence") or 0) >= 0.5}
    pick = [t for t in root.find(".//Tracks") if t.tag in ("AudioTrack", "MidiTrack")
            and v(t, "./DeviceChain/Mixer/Speaker/Manual") != "false"
            and (not tracks or v(t, "./Name/EffectiveName") in tracks)
            and t.find("./DeviceChain/DeviceChain/Devices") is not None and len(t.find("./DeviceChain/DeviceChain/Devices"))]
    audio_names = [v(t, "./Name/EffectiveName") for t in pick if t.tag == "AudioTrack"]
    from hypnomix.core import tmp as TMP
    # the renders live in a folder that is removed when this ends (an error or Ctrl-C too), named hypnomix-render-…
    with TMP.workdir("render", expect_bytes=TMP.render_bytes(root, len(audio_names))) as rd:
        if audio_names:
            hx("render", set_path, "--tracks", *audio_names, "--out", rd)
        out, notes = [], []
        want_n = id_numbers(ids)                       # the numbers of the ids asked for: only their tracks are judged
        focus = set(focus or ())                       # tracks to judge whatever their ids (ids stay those of the whole set)
        restricted = bool(want_n or focus)
        last_focus = max((i for i, t in enumerate(pick) if v(t, "./Name/EffectiveName") in focus), default=-1)
        for ti, t in enumerate(pick):
            if restricted and ti > last_focus and (not want_n or len(out) >= max(want_n)):
                break                                  # every id from here on is past the ones asked for
            nm = v(t, "./Name/EffectiveName")
            f = rd / f"{safe(nm)}.wav"
            if t.tag == "MidiTrack" and stems:
                cand = [p for p in Path(stems).glob("*.wav") if SC.norm(p.stem) == SC.norm(nm)]
                f = cand[0] if cand else f
            role = role_of(nm, labels.get(nm, ""), t)
            if restricted:
                counted = count_items(nm, role, t, f if f.exists() else None, tempo)
                if counted is not None and nm not in focus and not any(len(out) < k <= len(out) + counted[0] for k in want_n):
                    out += [None] * counted[0]         # owns none of the ids: numbered like the others, not judged
                    notes += counted[1]
                    continue
            x = SC.load_mono(str(f)) if f.exists() else None
            fs, ns = review_track(nm, role, t, x, tempo)
            for it in fs:
                it.update(track=nm, role=role)
            out += fs; notes += ns
    return out, notes, root, tempo


def findings(items):
    fs = []
    for n, it in enumerate(items, 1):
        if it is None:                                  # numbered but not judged (see propose): no finding, the id is kept
            continue
        base = dict(id=f"devices-{n}", tool="devices", track=it["track"], where="", device=it["device"])
        if it["kind"] == "compressor":
            c, w, m, m2 = it["cur"], it["new"], it["m"], it["m2"]
            lo, hi = it["target"]
            cur = f"threshold {c['threshold_db']:.1f} dB, ratio {c['ratio']:g}, attack {c['attack']:g} ms, release {c['release']:.0f} ms"
            sug = f"threshold {w['threshold_db']:.1f} dB, ratio {w['ratio']:g}, attack {w['attack']:g} ms, release {w['release']:.0f} ms"
            ok = not it["problems"] and lo <= m["median"] <= hi * 1.25
            fs.append(dict(base, kind="compressor", severity="info" if ok else ("medium" if len(it["problems"]) > 1 else "low"),
                           problem=(f"'{it['device']}' ({it['role']}): turns the part down {m['median']:.1f} dB while it plays "
                                    f"({m['loud']:.0f} dB on loud moments, working {m['working']:.0%} of the time); now {cur}"
                                    + ("; " + "; ".join(it["problems"]) if it["problems"] else
                                       ("; within the usual range for this kind of part" if ok else ""))),
                           fix=(f"fine as it is (a suggestion for {lo}-{hi} dB anyway: {sug})" if ok else
                                f"try {sug}: about {m2['median']:.1f} dB while it plays ({lo}-{hi} dB is usual for this "
                                "kind of part). An option"),
                           applies="info" if ok else "set", settings={k: w[k] for k in ("threshold_db", "ratio", "attack", "release")},
                           dev_tag=it["el"].tag))
        elif it["kind"] == "gate":
            fs.append(dict(base, kind="gate", severity="low" if it["problems"] else "info",
                           problem=f"'{it['device']}': threshold {it['thr']:.0f} dB; noise floor {it['noise']:.0f} dB, phrases "
                                   f"{it['phrase']:.0f} dB" + ("; " + "; ".join(it["problems"]) if it["problems"] else ""),
                           fix=(f"set the threshold to {it['new_thr']:.0f} dB (between the noise and the quiet phrases). An option"
                                if it["new_thr"] is not None else "fine as it is"),
                           applies="set" if it["new_thr"] is not None else "info", threshold_db=it["new_thr"]))
        elif it["kind"] == "limiter":
            fs.append(dict(base, kind="limiter", severity="low" if it["problems"] else "info",
                           problem=f"'{it['device']}': takes {it['loud']:.1f} dB off the loud moments" +
                                   ("; " + "; ".join(it["problems"]) if it["problems"] else ""),
                           fix=(f"turn its Gain down to {it['new_gain']:.1f} dB (catch peaks, about 1-2 dB). An option"
                                if it["new_gain"] is not None else "fine as it is"),
                           applies="set" if it["new_gain"] is not None else "info", gain_db=it["new_gain"]))
        elif it["kind"] == "eq-lowcut":
            fs.append(dict(base, kind="eq-lowcut", severity="low", problem="; ".join(it["problems"]),
                           fix="add a low cut (EQ Eight band 1, 48 dB/oct) around 80-100 Hz, by ear: it clears room for the bass",
                           applies="manual"))
        elif it["kind"] == "unknown":
            fs.append(dict(base, kind="unknown-level", severity="info", problem=it["problem"], fix="check it by ear",
                           applies="info"))
    return fs


def apply_settings(root, items, fs, want):
    done = 0
    for f, it in zip(fs, items):
        if f["id"] not in want or f["applies"] != "set":
            continue
        d = it["el"]
        if it["kind"] == "compressor":
            c = dict(it["cur"]); c.update(f["settings"])
            SC.write_settings(d, c); done += 1
        elif it["kind"] == "gate":
            d.find("./Threshold/Manual").set("Value", repr(10 ** (f["threshold_db"] / 20))); done += 1
        elif it["kind"] == "limiter":
            d.find("./Gain/Manual").set("Value", repr(float(f["gain_db"]))); done += 1
    return done


def main():
    ap = argparse.ArgumentParser(prog="hypnomix devices", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    from hypnomix.session import liveversion as LV; LV.add_force_flag(ap)
    ap.add_argument("als"); ap.add_argument("--names"); ap.add_argument("--stems"); ap.add_argument("--track", action="append")
    ap.add_argument("--json"); ap.add_argument("--apply", metavar="NEW.als"); ap.add_argument("--ids")
    ap.add_argument("--focus", action="append", metavar="TRACK",
                    help="judge only this track (repeatable); ids stay those of the whole set. Used by `fix` to re-check "
                         "just the tracks it changes")
    a = ap.parse_args()
    src = Path(a.als)
    # applying ids judges only the tracks that own them; every id is still the one the whole-set run gives
    items, notes, root, tempo = propose(src, a.names, a.stems, a.track, ids=a.ids if a.apply else None, focus=a.focus)
    narrowed = bool(a.focus) or bool(a.apply and id_numbers(a.ids))
    fs = findings(items)
    items = [it for it in items if it is not None]
    print(f"{src.name}: {len(fs)} device(s) checked on {len({f['track'] for f in fs})} track(s)"
          + (" (only the tracks asked about; the ids are those of the whole set)" if narrowed else ""))
    for f in fs:
        flag = "  " if f["applies"] == "info" else "! "
        print(f"{flag}{f['id']:<11} {f['track'][:22]:<22} {f['problem'][:150]}")
        if f["applies"] != "info":
            print(f"{'':16}→ {f['fix'][:150]}")
    for n_ in notes:
        print("  note: " + n_)
    if a.json:
        Path(a.json).write_text(json.dumps({"tool": "devices", "set": str(src), "findings": fs, "notes": notes, **({"narrowed": True} if narrowed else {})},
                                         indent=1, default=float), encoding="utf-8")
    if a.apply:
        if Path(a.apply).resolve() == src.resolve():
            sys.exit("refusing to overwrite the set; give a new file name")
        if not os.environ.get("HYPNOMIX_ALLOW_TMP_SET") and Path(a.apply).resolve().parent != src.resolve().parent:
            sys.exit(f"write the new set in the same folder as the original ({src.resolve().parent})")
        want = {x.strip() for x in (a.ids or "").split(",") if x.strip()}
        if not want:
            sys.exit("say which: --ids devices-2,… (nothing is changed by default)")
        done = apply_settings(root, items, fs, want)
        data = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")
        from hypnomix.session import liveversion as LV
        LV.guard_write(root)                # refuses a set saved by a Live newer than the newest tested
        with gzip.open(a.apply, "wb") as fh:
            fh.write(data)
        print(f"wrote {a.apply}: {done} device(s) changed")


if __name__ == "__main__":
    main()
