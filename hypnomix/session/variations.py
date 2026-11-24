#!/usr/bin/env python3
"""Add variety to repetitive parts from audio you already recorded but never used.

  hypnomix variations SET.als [--out DIR]                     report + audition clips, nothing written
  hypnomix variations SET.als --apply "SET (variations).als"  add the variation tracks, switched OFF

What it looks for:
  repeats   on each audio track, the same stretch of the same recording played again and again
            (a looped clip, or a clip pasted many times): "Guitar plays the same 4 bars 12 times"
  unused    parts of those same recordings that never appear anywhere in the Arrangement
  a match   an unused stretch of the same length, on the recording's own bar lines, that fits the loop
            it would join (same harmony, similar level) but is played differently

For each repetitive part it proposes a few of the repeats (by default every 4th: the turnaround, where
a player would vary it) and one unused stretch for each. Then:

  report    VARIATIONS.md and variations.json; for every proposal two audition files, "A (the loop)"
            and "B (unused take)", cut straight from the recording
  --apply   a NEW set where each part gets a new track right after it, in the same group, with the
            same devices and sends: "<Track> (variation)". It holds only the proposed clips and it is
            switched OFF. Nothing sounds different until you turn a variation track on.

  --mode layer     (default) the variation plays on top of the original part
  --mode replace   the variation track is a full copy of the part with the proposals swapped in:
                   turn it on and the original off. Best for drums and bass.
  --every 4        vary one repeat in this many      --min-repeats 4   what counts as repetitive
  --track NAME     only these parts (repeatable)     --max 3           different unused stretches per part

It also lists recordings in the project's Samples folder that the set does not use at all: try
`hypnomix loops FILE` on the long ones.

Measured, not heard: "fits" means the notes and level line up on paper. Your ears decide. Works on
clips at a constant tempo; clips with bent timing (several warp markers) are skipped.
Close the set in Live before --apply. `hypnomix check` runs on the result.
"""
import argparse, copy, json, re, sys
from pathlib import Path

import numpy as np
import soundfile as sf
import librosa

from hypnomix.session import beats as B

AUDIO_EXT = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".m4a"}
DRUM_WORDS = ("drum", "kick", "snare", "hat", "perc", "kit", "beat", "clap", "tom", "cymbal")


def plays(track, als_dir, tempo, bpb):
    """Every time a stretch of a file sounds on this track: dicts with start/len (beats), file, f0/f1 (seconds)."""
    from hypnomix.session import smooth as sm
    out = []
    for c in B.clips_of(track):
        ci = sm.clip_info(c, als_dir, tempo)
        if ci["disabled"] or not ci["path"].exists():
            continue
        if ci["warped"] and len(ci["markers"]) > 2:
            b, s = (np.array(x) for x in zip(*ci["markers"]))
            slope = np.diff(s) / np.diff(b)
            if slope.max() - slope.min() > 0.002 * abs(slope.mean()):     # bent timing: leave it alone
                continue
        per = 1.0 if ci["warped"] else tempo / 60.0                       # clip units -> beats
        if ci["loop_on"] and ci["le"] > ci["ls"]:
            span = (ci["le"] - ci["ls"]) * per
            pos = ci["start"] + (ci["le"] - ci["ls"] - ci["rel"]) * per     # first pass may start mid-loop
            starts = [ci["start"]] if ci["rel"] > 1e-6 else []
            first = ci["start"] if ci["rel"] <= 1e-6 else pos
            n = first
            while n < ci["end"] - 1e-6:
                starts.append(n)
                n += span
            for st in starts:
                ln = min(span, ci["end"] - st) if st != ci["start"] or ci["rel"] <= 1e-6 else pos - ci["start"]
                if ln <= 1e-6:
                    continue
                f = sm.file_seconds(ci, np.array([st + 1e-9, st + ln - 1e-9]), tempo)
                out.append(dict(start=float(st), len=float(ln), file=ci["path"], f0=float(f[0]), f1=float(f[1]), ci=ci))
        else:
            f = sm.file_seconds(ci, np.array([ci["start"], ci["end"]]), tempo)
            out.append(dict(start=ci["start"], len=ci["end"] - ci["start"], file=ci["path"],
                            f0=float(f[0]), f1=float(f[1]), ci=ci))
    return out


def repeats(pl, bpb, min_repeats):
    groups = {}
    for p in pl:
        nb = p["len"] / bpb
        if p["len"] < bpb - 1e-3 or p["f1"] <= p["f0"] or abs(nb - round(nb)) > 0.03:   # whole bars: loops, not phrases
            continue
        key = (str(p["file"]), round(p["f0"], 2), round(p["len"], 2))
        groups.setdefault(key, []).append(p)
    return [sorted(g, key=lambda p: p["start"]) for g in groups.values() if len(g) >= min_repeats]


_feat = {}


def features(path):
    """Per-file: mono audio at 22.05 kHz, chroma and onset strength (frames), loudness per frame."""
    if path not in _feat:
        y, sr = B.load(path)
        m = librosa.resample(y.mean(1), orig_sr=sr, target_sr=B.SR_B) if sr != B.SR_B else y.mean(1)
        hop = 512
        chroma = librosa.feature.chroma_cqt(y=m, sr=B.SR_B, hop_length=hop) if len(m) > 4096 else np.zeros((12, 1))
        env = librosa.onset.onset_strength(y=m, sr=B.SR_B, hop_length=hop)
        rms = librosa.feature.rms(y=m, frame_length=2048, hop_length=hop)[0]
        _feat[path] = dict(dur=len(m) / B.SR_B, chroma=chroma, env=env, rms=rms, fps=B.SR_B / hop)
    return _feat[path]


def window(F, a, b, steps):
    """Chroma (12 x steps), onset pattern (steps) and level (dB) of file seconds a..b, on a fixed grid."""
    fr = np.clip((np.linspace(a, b, steps + 1) * F["fps"]).astype(int), 0, F["chroma"].shape[1] - 1)
    ch = np.stack([F["chroma"][:, fr[i]: max(fr[i] + 1, fr[i + 1])].mean(1) for i in range(steps)], 1)
    n = min(len(F["env"]), len(F["rms"]))
    fr2 = np.clip(fr, 0, n - 1)
    on = np.array([F["env"][fr2[i]: max(fr2[i] + 1, fr2[i + 1])].max() for i in range(steps)])
    seg = F["rms"][fr2[0]: max(fr2[0] + 1, fr2[-1])]
    return ch, on, 20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9)


def corr(a, b):
    a, b = a.ravel() - a.mean(), b.ravel() - b.mean()
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def used_map(all_plays):
    used = {}
    for p in all_plays:
        used.setdefault(str(p["file"]), []).append((min(p["f0"], p["f1"]), max(p["f0"], p["f1"])))
    return used


def overlap(iv, a, b):
    return sum(max(0.0, min(b, y) - max(a, x)) for x, y in iv)


def candidates(group, used, bpb, drums, max_n):
    """Unused stretches of the same recording, on its own bar lines, that fit the loop."""
    p = group[0]
    F = features(p["file"])
    D = p["f1"] - p["f0"]
    bars = max(1, int(round(p["len"] / bpb)))
    bar_s = D / (p["len"] / bpb)
    steps = 8 * bars
    ch0, on0, lv0 = window(F, p["f0"], p["f1"], steps)
    iv = used.get(str(p["file"]), [])
    out = []
    k_lo, k_hi = -int(p["f0"] // bar_s), int((F["dur"] - p["f1"]) // bar_s)
    for k in range(k_lo, k_hi + 1):
        a, b = p["f0"] + k * bar_s, p["f1"] + k * bar_s
        if k == 0 or a < 0 or b > F["dur"] or overlap(iv, a, b) > 0.05 * D:
            continue
        ch, on, lv = window(F, a, b, steps)
        if lv < lv0 - 12 or lv < -55:                    # silence, or much quieter than the loop
            continue
        fit = 1.0 if drums else corr(ch, ch0)
        same = corr(on, on0)
        if fit < 0.45:
            continue
        new = 1.0 - max(0.0, same)
        score = 0.6 * fit + 0.4 * min(new, 0.7) / 0.7
        out.append(dict(shift_bars=k, f0=float(a), f1=float(b), fit=round(fit, 2), different=round(new, 2),
                        level_db=round(lv - lv0, 1), score=round(score, 3)))
    out.sort(key=lambda c: -c["score"])
    picked = []
    for c in out:                                          # spread the picks: not three neighbouring bars
        if all(abs(c["shift_bars"] - q["shift_bars"]) >= bars for q in picked):
            picked.append(c)
        if len(picked) >= max_n:
            break
    return picked, len(out)


def prefix(name):
    """Live names recordings "<track> 0007 [date]": the part before the take number."""
    return re.sub(r"\s+\d{4}\s*\[.*$", "", Path(name).stem)


def grid16(F, period, n_fft_hop=512):
    """Lock a 16th-note grid at the song's tempo onto a recording. Returns (phase seconds, contrast):
    contrast is how much stronger the hits are on the grid than off it (about 1 = not at this tempo)."""
    env, fps = F["env"], F["fps"]
    step = period / 4
    best, phase = 0.0, 0.0
    base = float(env.mean()) + 1e-9
    for ph in np.arange(0, step, 0.006):
        idx = np.round((ph + np.arange(0, F["dur"] - ph, step)) * fps).astype(int)
        idx = idx[idx < len(env)]
        if len(idx) < 16:
            continue
        v = float(env[idx].mean()) / base
        if v > best:
            best, phase = v, float(ph)
    return phase, best


def spare_candidates(group, files, tempo, bpb, drums, max_n):
    """Stretches of OTHER recordings of the same part (not used in the set) that fit the loop: found by
    sliding the loop's length along the recording on a 16th grid at the song's tempo."""
    p = group[0]
    F0 = features(p["file"])
    bars = max(1, int(round(p["len"] / bpb)))
    L = 16 * bars
    ch0, on0, lv0 = window(F0, p["f0"], p["f1"], L)
    period = 60.0 / tempo
    out, skipped = [], []
    for f in files:
        F = features(f)
        if F["dur"] < bars * bpb * period + 1:
            continue
        phase, contrast = grid16(F, period)
        if contrast < 1.25:
            skipped.append(f.name)
            continue
        n16 = int((F["dur"] - phase) / (period / 4))
        if n16 <= L:
            continue
        edges = phase + np.arange(n16 + 1) * period / 4
        fr = np.clip((edges * F["fps"]).astype(int), 0, min(F["chroma"].shape[1], len(F["env"]), len(F["rms"])) - 1)
        ch = np.stack([F["chroma"][:, fr[i]: max(fr[i] + 1, fr[i + 1])].mean(1) for i in range(n16)], 1)
        on = np.array([F["env"][fr[i]: max(fr[i] + 1, fr[i + 1])].max() for i in range(n16)])
        pw = np.array([np.mean(F["rms"][fr[i]: max(fr[i] + 1, fr[i + 1])] ** 2) for i in range(n16)])
        W = np.lib.stride_tricks.sliding_window_view
        cw = W(ch, L, axis=1).transpose(1, 0, 2).reshape(n16 - L + 1, -1)          # windows x (12*L)
        ow = W(on, L)
        lv = 10 * np.log10(W(pw, L).mean(1) + 1e-12)

        def rows_corr(M, v):
            M = M - M.mean(1, keepdims=True); v = v.ravel() - v.mean()
            return (M @ v) / (np.linalg.norm(M, axis=1) * np.linalg.norm(v) + 1e-9)

        fit = np.ones(len(lv)) if drums else rows_corr(cw, ch0)
        same = rows_corr(ow, on0)
        ok = (lv > lv0 - 14) & (lv > -55) & (fit >= 0.5) & (same >= 0.15)          # in step with the loop, in its harmony
        score = 0.55 * fit + 0.25 * np.clip(same, 0, 1) + 0.2 * np.clip(1 - same, 0, 0.6) / 0.6
        score[~ok] = -1
        order = np.argsort(-score)
        took = []
        for i in order[:400]:
            if score[i] < 0 or len(took) >= max_n:
                break
            if all(abs(i - j) >= L for j in took):
                took.append(int(i))
                a = float(edges[i])
                out.append(dict(file=f, f0=a, f1=a + L * period / 4, fit=round(float(fit[i]), 2),
                                different=round(float(1 - max(0.0, same[i])), 2),
                                level_db=round(float(lv[i] - lv0), 1), score=round(float(score[i]), 3),
                                grid=round(contrast, 2)))
    out.sort(key=lambda c: -c["score"])
    picked = []
    for c in out:
        if sum(1 for q in picked if q["file"] == c["file"]) < 2:
            picked.append(c)
        if len(picked) >= max_n:
            break
    return picked, len(out), skipped


def unused_files(root, als):
    ref = set()
    for fr in root.iter("FileRef"):
        for tag in ("Path", "RelativePath"):
            e = fr.find(tag)
            if e is not None and e.get("Value"):
                ref.add(Path(e.get("Value")).name)
    out = []
    samples = Path(als).parent / "Samples"
    if samples.is_dir():
        for f in sorted(samples.rglob("*")):
            if f.suffix.lower() in AUDIO_EXT and f.name not in ref and "Recorded" in f.parts:
                try:
                    d = sf.info(str(f)).duration
                except Exception:
                    continue
                if d >= 4:
                    out.append((f, d))
    return out


# ---------------------------------------------------------------- writing
def new_clip(p, f0, f1, at, tempo):
    """A copy of the play's clip that plays file seconds f0..f1 once, at arrangement beat `at`."""
    ci = p["ci"]
    c = copy.deepcopy(ci["el"])
    if ci["warped"]:
        if len(ci["markers"]) >= 2:
            b, s = (np.array(x) for x in zip(*ci["markers"]))
            slope = (b[-1] - b[0]) / (s[-1] - s[0])
            to_b = lambda x: float(b[0] + (x - s[0]) * slope)
        else:
            to_b = lambda x: float(x * tempo / 60.0)
        a_, b_ = to_b(f0), to_b(f1)
    else:
        a_, b_ = f0, f1
    B.set_region(c, a_, b_)
    c.find("./CurrentStart").set("Value", repr(float(at)))
    c.find("./CurrentEnd").set("Value", repr(float(at + p["len"])))
    c.set("Time", repr(float(at)))
    return c


def spare_clip(p, c, at, tempo):
    """A clip that plays seconds f0..f1 of ANOTHER recording at arrangement beat `at`: warp off (no stretching),
    level matched to the loop it joins."""
    ci = p["ci"]
    clip = copy.deepcopy(ci["el"])
    f = Path(c["file"])
    fr = clip.find("./SampleRef/FileRef")
    info = sf.info(str(f))
    B.set_val(fr, "./Path", str(f))
    rel = fr.find("./RelativePath")
    if rel is not None:
        rel.set("Value", "/".join(f.parts[-3:]) if "Samples" in f.parts[-3:] else str(f))
    B.set_val(fr, "./OriginalFileSize", str(f.stat().st_size))
    B.set_val(fr, "./OriginalCrc", "0")
    B.set_val(clip, "./SampleRef/DefaultDuration", str(info.frames))
    B.set_val(clip, "./SampleRef/DefaultSampleRate", str(info.samplerate))
    B.set_val(clip, "./SampleRef/LastModDate", str(int(f.stat().st_mtime)))
    clip.find("./IsWarped").set("Value", "false")
    B.set_markers(clip, [(0.0, 0.0), (0.03125 * 60.0 / tempo, 0.03125)])
    B.set_region(clip, c["f0"], c["f1"])
    gain = float(np.clip(10 ** (-c["level_db"] / 20), 0.25, 4.0)) * (ci["gain"] or 1.0)
    B.set_val(clip, "./SampleVolume", gain)
    B.set_val(clip, "./Name", f"spare take {int(c['f0'] // 60)}:{c['f0'] % 60:04.1f}")
    for tag in ("FadeInLength", "FadeOutLength"):
        B.set_val(clip, f"./Fades/{tag}", 0.0)
    clip.find("./CurrentStart").set("Value", repr(float(at)))
    clip.find("./CurrentEnd").set("Value", repr(float(at + p["len"])))
    clip.set("Time", repr(float(at)))
    return clip


def clone_track(root, track, name):
    """A copy of a track (devices, sends, routing, group) with no clips, switched off, with fresh ids."""
    tracks = root.find(".//Tracks")
    new = copy.deepcopy(track)
    new.set("Id", str(max(int(t.get("Id")) for t in tracks) + 1))
    npi = root.find(".//NextPointeeId")
    nxt = int(npi.get("Value"))
    remap = {}
    for e in new.iter():
        if (e.tag.endswith("Target") or e.tag == "Pointee") and (e.get("Id") or "").isdigit():
            remap[e.get("Id")] = str(nxt)
            e.set("Id", str(nxt))
            nxt += 1
    for e in new.iter("PointeeId"):
        if e.get("Value") in remap:
            e.set("Value", remap[e.get("Value")])
    npi.set("Value", str(nxt))
    ev = new.find("./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events")
    for c in list(ev):
        ev.remove(c)
    for v in new.findall("./DeviceChain/MainSequencer/ClipSlotList/ClipSlot/ClipSlot/Value"):
        for c in list(v):
            v.remove(c)
    for tag in ("EffectiveName", "UserName"):
        e = new.find(f"./Name/{tag}")
        if e is not None:
            e.set("Value", name)
    sp = new.find("./DeviceChain/Mixer/Speaker/Manual")
    if sp is not None:
        sp.set("Value", "false")
    tracks.insert(list(tracks).index(track) + 1, new)
    return new, ev


def main():
    ap = argparse.ArgumentParser(prog="hypnomix variations", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als"); ap.add_argument("--track", action="append", default=[])
    ap.add_argument("--min-repeats", type=int, default=4); ap.add_argument("--every", type=int, default=4)
    ap.add_argument("--max", type=int, default=3); ap.add_argument("--mode", choices=("layer", "replace"), default="layer")
    ap.add_argument("--takes", action="append", default=[], metavar="DIR", help="another folder of spare takes to search (repeatable)")
    ap.add_argument("--out"); ap.add_argument("--no-clips", action="store_true", help="skip the audition files")
    ap.add_argument("--apply", metavar="NEW.als")
    a = ap.parse_args()
    from hypnomix.session import automation as aa
    from hypnomix.core.paths import out_at
    src = Path(a.als)
    tree = aa.load(src); root = tree.getroot()
    bpb = aa.BPB
    tempo = B.set_tempo(root)
    if B.tempo_points(root):
        sys.exit("this set has tempo automation: variations needs a constant tempo")
    tracks = [t for t in root.find(".//Tracks") if t.tag == "AudioTrack"]
    per_track = [(t.find("./Name/EffectiveName").get("Value"), t, plays(t, src.parent, tempo, bpb)) for t in tracks]
    used = used_map([p for _, _, pl in per_track for p in pl])
    od = out_at(a.out, "variations", src.stem)
    props, report = [], []
    loose = unused_files(root, src)
    extra = [Path(x) for d in a.takes for x in ([Path(d)] if Path(d).is_file() else sorted(Path(d).rglob("*")))
             if x.suffix.lower() in AUDIO_EXT]
    off_tempo = set()
    for name, t, pl in per_track:
        if a.track and not any(name.lower().startswith(x.lower()) for x in a.track):
            continue
        drums = any(w in name.lower() for w in DRUM_WORDS)
        for g in repeats(pl, bpb, a.min_repeats):
            p = g[0]
            bars = p["len"] / bpb
            cands, n_all = candidates(g, used, bpb, drums, a.max)
            mine = {prefix(q["file"].name) for q in pl}
            spare = [f for f, d in loose if prefix(f.name) in mine] + extra
            sc, n_sp, skipped = spare_candidates(g, spare, tempo, bpb, drums, a.max) if spare else ([], 0, [])
            off_tempo.update(skipped)
            cands = sorted(cands + sc, key=lambda c: -c["score"])[: a.max]
            n_all += n_sp
            F = features(p["file"])
            free = F["dur"] - min(F["dur"], sum(y - x for x, y in used.get(str(p["file"]), [])))
            row = dict(track=name, file=p["file"].name, bars=round(bars, 2), repeats=len(g),
                       first_bar=int(g[0]["start"] // bpb) + 1, last_bar=int((g[-1]["start"] + g[-1]["len"]) // bpb),
                       file_len=round(F["dur"], 1), unused_s=round(free, 1), spare_takes=len(spare), fits=n_all, picked=cands)
            report.append(row)
            if not cands:
                continue
            spots = g[a.every - 1::a.every]
            for n, sp in enumerate(spots):
                c = cands[n % len(cands)]
                props.append(dict(id=f"variation-{len(props) + 1}", track=name, play=sp, group=g, cand=c, drums=drums,
                                  bar=int(sp["start"] // bpb) + 1, bars=round(bars, 2), t=t))
    report.sort(key=lambda r: -r["repeats"] * r["bars"])
    print(f"{src.name}: {tempo:g} BPM, {len(tracks)} audio tracks\n")
    if not report:
        print(f"no part repeats the same stretch of a recording {a.min_repeats} times or more.")
    else:
        print(f"{'track':<22} {'loop':>7} {'×':>3}  {'bars':<9} {'spare takes':>11}  fits  proposals")
        for r in report:
            mine = sum(1 for q in props if q["track"] == r["track"] and q["group"][0]["file"].name == r["file"]
                       and abs(q["bars"] - r["bars"]) < 1e-6)
            print(f"{r['track'][:22]:<22} {r['bars']:>4g} bar {r['repeats']:>3}  {r['first_bar']}-{r['last_bar']:<6} "
                  f"{r['spare_takes']:>11}  {r['fits']:>4}  {mine or '-'}")
    md = [f"# Variations: {src.name}", "",
          "Repetitive parts, and unused stretches of the same recordings that could vary them. Measured, not heard.",
          "Each proposal has two audition files in this folder: A (the loop as it is) and B (the unused take).", "",
          "| id | track | at bar | bars | unused take from | fits harmony | how different | level |", "|---|---|---|---|---|---|---|---|"]
    out_json = []
    for q in props:
        sp, c = q["play"], q["cand"]
        cf = Path(c.get("file") or sp["file"])
        md.append(f"| {q['id']} | {q['track']} | {q['bar']} | {q['bars']:g} | {int(c['f0'] // 60)}:{c['f0'] % 60:04.1f} of {cf.name} | "
                  f"{'n/a (drums)' if q['drums'] else c['fit']} | {c['different']} | {c['level_db']:+.1f} dB |")
        out_json.append(dict(id=q["id"], tool="variations", kind="variation", severity="info", track=q["track"],
                             where=f"bar {q['bar']}", applies="set",
                             problem=f"{q['track']} plays the same {q['bars']:g} bars {len(q['group'])} times",
                             fix=f"an unused {q['bars']:g}-bar stretch of {cf.name} (from {c['f0']:.1f} s) on a new, "
                                 f"switched-off track at bar {q['bar']}",
                             file=str(cf), file_from=c["f0"], file_to=c["f1"], fit=c["fit"], different=c["different"]))
        if not a.no_clips:
            safe = re.sub(r'[\\/:*?"<>|]', "-", f"{q['id']} {q['track']} bar {q['bar']}")
            ya, sra = B.load(sp["file"])
            yb, srb = B.load(cf)
            A_ = ya[int(sp["f0"] * sra): int(sp["f1"] * sra)]
            B_ = yb[int(c["f0"] * srb): int(c["f1"] * srb)] * float(np.clip(10 ** (-c["level_db"] / 20), 0.25, 4.0))
            sf.write(str(od / f"{safe} A (the loop).wav"), A_, sra, subtype="PCM_24")
            sf.write(str(od / f"{safe} B (unused take).wav"), B_, srb, subtype="FLOAT")
            if sra == srb and A_.shape[1] == B_.shape[1]:
                n = min(len(A_), len(B_))
                sf.write(str(od / f"{safe} A+B (together).wav"), A_[:n] + B_[:n], sra, subtype="FLOAT")
    if loose:
        md += ["", "## Recordings in the project folder that this set does not use", "",
               "Try `hypnomix loops FILE` on the long ones.", "", "| file | length |", "|---|---|"]
        md += [f"| {f.relative_to(src.parent)} | {int(d // 60)}:{d % 60:02.0f} |" for f, d in sorted(loose, key=lambda x: -x[1])[:60]]
        print(f"\n{len(loose)} recordings in the project folder are not used by this set at all "
              f"(longest {max(d for _, d in loose) / 60:.1f} min): listed in VARIATIONS.md")
    if off_tempo:
        print(f"{len(off_tempo)} spare takes do not lock to {tempo:g} BPM (free-played, or another tempo) and were not "
              "searched: try `hypnomix loops FILE` on them")
    (od / "VARIATIONS.md").write_text("\n".join(md) + "\n")
    (od / "variations.json").write_text(json.dumps(dict(set=str(src), tempo=tempo, parts=[
        {k: v for k, v in r.items()} for r in report], findings=out_json), indent=1, default=str))
    print(f"\n{len(props)} proposals on {len({q['track'] for q in props})} parts → {od}")
    if not a.apply:
        if props:
            print("listen to the A / B files, then add --apply \"NEW.als\" (variation tracks arrive switched off).")
        return
    if not props:
        sys.exit("nothing to add")
    def make(q, p):
        c = q["cand"]
        return spare_clip(p, c, p["start"], tempo) if c.get("file") else new_clip(p, c["f0"], c["f1"], p["start"], tempo)

    by_track, added = {}, []
    for q in props:
        by_track.setdefault(q["track"], []).append(q)
    for name, qs in by_track.items():
        t = qs[0]["t"]
        label = f"{name} (variation)" if a.mode == "layer" else f"{name} (alt part)"
        _, ev = clone_track(root, t, label)
        added.append(label)
        swap = {id(q["play"]): q for q in qs}
        clips = []
        if a.mode == "replace":
            src_plays = next(pl for n_, _, pl in per_track if n_ == name)
            for p in src_plays:
                q = swap.get(id(p))
                clips.append(make(q, p) if q else new_clip(p, p["f0"], p["f1"], p["start"], tempo))
        else:
            clips = [make(q, q["play"]) for q in qs]
        clips.sort(key=lambda c: float(c.get("Time")))
        for n, c in enumerate(clips):
            c.set("Id", str(n))
            ev.append(c)
        print(f"  + {label!r}: {len(clips)} clips, switched off, next to {name!r}")
    B.finish(tree, src, a.apply, added=added)


if __name__ == "__main__":
    main()
