#!/usr/bin/env python3
"""The other versions of a song a release asks for, made from your own exported stems: an instrumental, an
a cappella, a TV mix and a radio edit. No separation model: you say which stems are vocals, and the rest is
arithmetic on files you exported yourself.

  instrumental   the stems that are not vocals, added up
  a cappella     the vocal stems, added up
  TV mix         the instrumental plus the vocals at --tv dB (only when you give --tv; 0 = the full song)
  radio edit     the song with the ranges you give in --cut taken out, joined with short equal-power
                 crossfades (--fade ms, default 30). It is cut from your --mix when you give one (so it keeps
                 the master exactly as it is), otherwise from all the stems added up. With --bpm each edge
                 snaps to the nearest bar line, and the plan says where it landed.

With --mix it first runs a NULL TEST: all the stems added up against your mix, the leftover in dB below the
mix. If the leftover is tiny, the stems really are the mix. If it is not (master-bus compression, EQ or a
limiter, or a stem you left out), it says so plainly, and that the versions are built from the stems, not carved
out of the mix: they will not carry what your master bus does. It also says when the only difference is a
level, or when the two start at different points.

With --mix each version is then gain-matched to the mix's loudness (gain only: no limiter, no EQ). If matching
would push a true peak over the lower of the mix's own peak and -1 dBTP, the gain stops there and the report says
how far short of the mix's loudness it landed. Without --mix nothing is gain-matched; the sums are written as they
add up (and turned down only if they would clip).

`hypnomix qc` runs on every file written, and VERSIONS.md has the results. Only new files, in a new folder
"<name> (versions)/" (it refuses if that exists). Your stems and mix are only read.

Usage:
    hypnomix versions --stems DIR --vocals "Lead*,Harm*" [--mix MIX.wav] [--tv -6]
                      [--cut 1:12-1:40 ...] [--bpm N] [--fade 30] [--name SONG] [--target -14] [--out DIR] [--check]

    --stems    folder of exported stems: same start point, same sample rate, processing as you want it heard
    --vocals   which stems are vocals: file names or patterns, comma separated (case does not matter; * ? work);
               matched against the name with and without its extension
    --cut      a range to remove, m:ss-m:ss (or seconds, 72-100); "2:50-" means to the end (for the start, write 0:00-0:08);
               give --cut more than once, or several ranges after one --cut, for several
    --out      the folder to create the "<name> (versions)" folder in (default hypnomix-out/versions)
    --check    read-only: runs the null test and prints the plan (which stems, the gains, the cuts); writes nothing
"""
import argparse, datetime, fnmatch, json, re, shutil, sys
from pathlib import Path

import numpy as np

from hypnomix.core import args as A, dsp, paths
from hypnomix.engineer import qc


def _tp(y, sr):
    """True peak in dBTP, one stretch at a time (a long song does not need four copies of itself in memory)."""
    from hypnomix.ears.compare import true_peak
    return true_peak(y, sr)


class VersionsError(Exception):
    """Something the person has to fix. The message is plain words."""


def safe_name(s):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", str(s)).strip().strip(".").strip()
    return s or "song"


def mmss(sec):
    sec = max(0.0, float(sec))
    return f"{int(sec // 60)}:{sec % 60:05.2f}"


# ---------------------------------------------------------------- the stems
def list_stems(folder, exclude=()):
    d = Path(folder).expanduser()
    if not d.exists():
        raise VersionsError(f"{d}: no such folder (looked in {Path.cwd()}); check the spelling of --stems")
    if not d.is_dir():
        raise VersionsError(f"{d} is a file, not a folder of stems")
    skip = {Path(x).resolve() for x in exclude if x}
    files = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in dsp.AUDIO_EXT and not p.name.startswith(".")
                   and p.resolve() not in skip)
    if len(files) < 2:
        raise VersionsError(f"found {len(files)} audio file(s) in {d}: you need at least two stems (a vocal and the rest)")
    return files


def split_stems(files, patterns):
    """(vocal files, other files, patterns that matched nothing). Patterns match the name with or without extension."""
    pats = [p.strip().lower() for p in re.split(r"\s*,\s*", str(patterns or "")) if p.strip()]
    if not pats:
        raise VersionsError('say which stems are the vocals with --vocals "Lead*,Harm*" (names or patterns, comma separated)')
    vocal, other, hit = [], [], set()
    for f in files:
        names = (f.stem.lower(), f.name.lower())
        m = [p for p in pats if any(fnmatch.fnmatchcase(n, p) for n in names)]
        hit.update(m)
        (vocal if m else other).append(f)
    miss = [p for p in pats if p not in hit]
    if not vocal:
        raise VersionsError("no stem matches --vocals " + repr(patterns) + ". The stems are: " + ", ".join(f.name for f in files))
    if not other:
        raise VersionsError("every stem matches --vocals, so there is nothing left for an instrumental. The stems are: "
                            + ", ".join(f.name for f in files))
    return vocal, other, miss


def _read(path):
    try:
        y, sr = dsp.load(path)
    except Exception as e:
        reason = str(e).split("as audio: ", 1)[-1] if isinstance(e, dsp.AudioReadError) else "not an audio file HypnoMix can read"
        raise VersionsError(f"can't read {Path(path).name} as audio: {reason}")
    return dsp.stereo(y), sr


def sum_stems(files):
    """The files added up (mono stems placed in the centre). Returns (sum, sr, longest_s, shortest_s). Holds one stem
    in memory at a time besides the sum."""
    acc, sr0, lens = None, None, []
    for f in files:
        y, sr = _read(f)
        if sr0 is None:
            sr0 = sr
        elif sr != sr0:
            raise VersionsError(f"{Path(f).name} is {sr} Hz but {Path(files[0]).name} is {sr0} Hz: export every stem at the same sample rate")
        lens.append(len(y) / sr)
        if acc is None:
            acc = y.copy()
        else:
            if len(y) > len(acc):
                acc = np.pad(acc, ((0, len(y) - len(acc)), (0, 0)))
            acc[:len(y)] += y
    return acc, sr0, max(lens), min(lens)


# ---------------------------------------------------------------- the null test
VERDICTS = [(-50.0, "add up", "The stems add up to the mix: the leftover is rounding-sized. The versions below are the same audio, rearranged."),
            (-30.0, "nearly", "The stems nearly add up to the mix. Something small sits on the master bus (a gentle EQ or glue "
                              "compressor), or a stem was exported with a slightly different effect setting."),
            (-15.0, "not quite", "The stems do not add up cleanly to the mix. Something real happens after the stems: master-bus "
                                 "compression, limiting or EQ, or a stem is missing from the folder."),
            (99.0, "no", "The stems and the mix are different audio: a stem is missing or extra, the two start at different points, "
                         "or the mix is a different version.")]


def db_text(x):
    return "140 dB or more" if x <= -139.9 else f"{abs(x):.1f} dB"


def null_test(total, mix, sr):
    """Stems added up against the mix. residual_db: how far the leftover sits below the mix (more negative is better)."""
    n = min(len(total), len(mix))
    t, m = total[:n], mix[:n]
    res = m - t
    mr = float(np.sqrt(np.mean(m ** 2)) + 1e-20)
    rdb = max(-140.0, float(20 * np.log10(np.sqrt(np.mean(res ** 2)) / mr + 1e-20)))
    g = float(np.sum(m * t) / (np.sum(t * t) + 1e-20))
    gdb = float(20 * np.log10(abs(g) + 1e-20))
    res_g = m - g * t
    rgdb = max(-140.0, float(20 * np.log10(np.sqrt(np.mean(res_g ** 2)) / mr + 1e-20)))
    verdict = next(v for lim, v, _ in VERDICTS if rdb <= lim)
    text = next(t_ for lim, v, t_ in VERDICTS if v == verdict)
    if verdict != "add up" and abs(gdb) >= 0.1 and rgdb <= -50.0:
        verdict = "level"
        text = (f"The stems add up to the mix apart from level: the stems are {abs(gdb):.1f} dB {'quieter' if gdb > 0 else 'louder'} "
                f"than the mix, and with that one gain the leftover is {db_text(rgdb)} below it. Something after the stems "
                "(a master fader or gain) changes the level; nothing else does.")
    out = dict(residual_db=round(rdb, 1), verdict=verdict, text=text, adds_up=verdict in ("add up", "level"),
               compared_s=round(n / sr, 2), length_stems_s=round(len(total) / sr, 2), length_mix_s=round(len(mix) / sr, 2),
               best_gain_db=round(gdb, 2), residual_with_gain_db=round(rgdb, 1), offset_s=None)
    extra = []
    if verdict != "add up":
        if verdict != "level" and abs(gdb) >= 0.1 and rgdb < rdb - 6:
            extra.append(f"The stems are {abs(gdb):.1f} dB {'quieter' if gdb > 0 else 'louder'} than the mix; with that one gain the "
                         f"leftover drops to {rgdb:.1f} dB below the mix, so the main difference is level (a fader or gain after the stems).")
        try:
            from hypnomix.ears import compare
            lag, conf = compare.find_lag(total[:n], mix[:n], sr)
            if conf >= 0.5 and lag != 0:
                out["offset_s"] = round(lag / sr, 4)
                extra.append(f"The mix runs {abs(lag) / sr:.3f} s {'later' if lag > 0 else 'earlier'} than the stems: export both from the "
                             "same start point and run this again.")
        except Exception:
            pass
        extra.append("The versions are therefore built from the stems, not carved out of the mix: they will not carry what your "
                     "master bus does (limiting, glue, EQ).")
    else:
        extra.append("They are still built from the stems.")
    if abs(len(total) - len(mix)) / sr > 0.05:
        extra.append(f"The stems run {len(total) / sr:.2f} s and the mix {len(mix) / sr:.2f} s; only the first {n / sr:.2f} s were compared.")
    out["notes"] = extra
    return out


# ---------------------------------------------------------------- cuts and the radio edit
def parse_time(text):
    t = str(text).strip()
    if not t:
        return None
    m = re.fullmatch(r"(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)", t)
    if m:
        return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.fullmatch(r"(\d+(?:\.\d+)?)", t)
    if m:
        return float(m.group(1))
    raise VersionsError(f"can't read the time {text!r}: write it as m:ss (1:12), h:mm:ss or seconds (72)")


def parse_cuts(items):
    """['1:12-1:40', '2:50-'] -> [(72.0, 100.0), (170.0, None)] (None: the start or end of the song)."""
    out = []
    for item in items or []:
        for part in re.split(r"[,\s]+", str(item).strip()):
            if not part:
                continue
            m = re.fullmatch(r"([^-]*)-([^-]*)", part)
            if not m:
                raise VersionsError(f"can't read the cut {part!r}: write it like 1:12-1:40")
            a, b = parse_time(m.group(1)), parse_time(m.group(2))
            if a is None and b is None:
                raise VersionsError(f"the cut {part!r} has no times")
            out.append((a, b))
    return out


def bar_lines(y, sr, bpm):
    """Bar start times in seconds, 4 beats to a bar, from the same grid `hypnomix sections` uses."""
    try:
        import librosa
        from hypnomix.ears import sections as S
        mono = y.mean(axis=1)
        mono = librosa.resample(mono, orig_sr=sr, target_sr=S.FEAT_SR) if sr != S.FEAT_SR else mono
        bars, _ = S.bar_grid(mono, S.FEAT_SR, bpm)
        if len(bars) >= 2:
            return np.asarray(bars, float), "found from the audio"
    except Exception:
        pass
    return np.arange(0, len(y) / sr, 4 * 60.0 / bpm), "counted from 0:00 (the audio's own grid could not be found)"


REFINE_WINDOW = 0.05                 # the bar grid is found from the audio to a few tens of ms: look this far either side


def refine_to_onset(y, sr, t, window=REFINE_WINDOW):
    """Move t to the start of the clearest hit (a sudden rise in level) within `window` seconds either side, or
    return t unchanged when nothing stands out (a pad, a sustained chord: there is no hit to land on)."""
    mono = np.abs(np.diff(y.mean(axis=1), prepend=0.0))
    c0, c1 = max(0, int((t - 0.5) * sr)), min(len(mono), int((t + 0.5) * sr))
    if c1 - c0 < int(0.2 * sr):
        return t
    hop = max(1, sr // 1000)                                 # 1 ms
    seg = mono[c0:c1]
    n = len(seg) // hop
    if n < 20:
        return t
    env = np.convolve(seg[: n * hop].reshape(n, hop).mean(axis=1), np.ones(3) / 3, mode="same")
    flux = np.maximum(np.diff(env, prepend=env[0]), 0.0)
    centre = int(round((t - c0 / sr) * 1000))
    lo, hi = max(1, centre - int(window * 1000)), min(n - 1, centre + int(window * 1000) + 1)
    if hi <= lo:
        return t
    k = lo + int(np.argmax(flux[lo:hi]))
    typical = float(np.percentile(flux, 90))
    if flux[k] <= 0 or flux[k] < 4.0 * max(typical, 1e-12):
        return t                                             # no hit stands out from its surroundings
    j = k
    while j > lo and flux[j - 1] > 0.2 * flux[k]:
        j -= 1
    return float(c0 / sr + j / 1000.0)


def plan_cuts(cuts, dur, bpm=None, bars=None, fade_s=0.03, refine=None):
    """Resolve the ranges: open ends filled, snapped to bar lines when `bars` is given (and then moved onto the
    nearest hit within 50 ms when `refine` is given), sorted, checked.
    Returns [dict(asked=(a, b), start, end, snapped, refined)]."""
    rows = []
    for a, b in cuts:
        s = 0.0 if a is None else a
        e = dur if b is None else b
        if s < 0 or e <= s:
            raise VersionsError(f"the cut {mmss(s)} to {mmss(e)} is backwards or empty")
        if s >= dur:
            raise VersionsError(f"the cut starts at {mmss(s)} but the song is only {mmss(dur)} long")
        if e > dur + 0.5:
            raise VersionsError(f"the cut ends at {mmss(e)} but the song is only {mmss(dur)} long")
        e = min(e, dur)
        s0, e0 = s, e
        refined = False
        if bars is not None:
            if a is not None and s > 0.5:
                s = float(bars[int(np.argmin(np.abs(bars - s)))])
                if refine:
                    s2 = min(max(float(refine(s)), 0.0), dur)
                    refined, s = refined or abs(s2 - s) > 1e-6, s2
            if b is not None and e < dur - 0.5:
                e = float(bars[int(np.argmin(np.abs(bars - e)))])
                if refine:
                    e2 = min(max(float(refine(e)), 0.0), dur)
                    refined, e = refined or abs(e2 - e) > 1e-6, e2
            if e <= s:
                raise VersionsError(f"the cut {mmss(s0)} to {mmss(e0)} is shorter than a bar: both ends snap to the same bar line")
        rows.append(dict(asked=(a, b), start=s, end=e, snapped=(abs(s - s0) > 1e-6 or abs(e - e0) > 1e-6), refined=refined))
    rows.sort(key=lambda r: r["start"])
    for p, q in zip(rows, rows[1:]):
        if q["start"] < p["end"]:
            raise VersionsError(f"the cuts {mmss(p['start'])}-{mmss(p['end'])} and {mmss(q['start'])}-{mmss(q['end'])} overlap")
    keeps, pos = [], 0.0
    for r in rows:
        keeps.append(r["start"] - pos)
        pos = r["end"]
    keeps.append(dur - pos)
    if not any(ln > 1e-9 for ln in keeps):
        raise VersionsError("the cuts remove the whole song: leave some of it in, or give a shorter range")
    for k, ln in enumerate(keeps):
        if ln <= 1e-9:
            continue
        edge = (k == 0 and rows and rows[0]["start"] <= 0) or (k == len(keeps) - 1 and rows and rows[-1]["end"] >= dur)
        if edge:
            continue
        if ln < 2 * fade_s:
            raise VersionsError(f"after the cuts, a part of the song is only {ln * 1000:.0f} ms long, shorter than the crossfades "
                                f"({fade_s * 1000:.0f} ms): widen the gap between two cuts or use a shorter --fade")
    return rows


def apply_cuts(y, sr, rows, fade_s=0.03):
    """Remove each row's range; join with a centred equal-power crossfade of `fade_s`. The length is exactly the song
    minus the cut time. A cut at the very start or end gets a fade of half that length instead of a join."""
    n = len(y)
    h = max(1, int(round(fade_s * sr / 2)))
    cuts = [(int(round(r["start"] * sr)), min(n, int(round(r["end"] * sr)))) for r in rows]
    pieces, pos = [], 0
    u = np.linspace(0.0, 1.0, 2 * h)[:, None]
    fin, fout = np.sin(0.5 * np.pi * u), np.cos(0.5 * np.pi * u)
    keeps = []
    for c0, c1 in cuts:
        keeps.append((pos, c0))
        pos = c1
    keeps.append((pos, n))
    keeps = [(a, b) for a, b in keeps if b > a]
    cut_after_first = cuts[0][0] <= 0 if cuts else False
    cut_to_end = cuts[-1][1] >= n if cuts else False
    out = []
    for i, (a, b) in enumerate(keeps):
        lo = a if (i == 0) else a + h
        hi = b if (i == len(keeps) - 1) else b - h
        seg = y[lo:hi].copy()
        if i == 0 and cut_after_first and len(seg) > h:
            seg[:h] *= np.linspace(0.0, 1.0, h)[:, None]
        if i == len(keeps) - 1 and cut_to_end and len(seg) > h:
            seg[-h:] *= np.linspace(1.0, 0.0, h)[:, None]
        out.append(seg)
        if i < len(keeps) - 1:
            na = keeps[i + 1][0]
            tail = y[b - h:b + h]
            head = y[na - h:na + h]
            out.append(tail * fout + head * fin)
    return np.concatenate(out, axis=0)


# ---------------------------------------------------------------- gain
def match_to_mix(v, sr, mix_lufs, ceiling):
    """Gain only: bring `v` to the mix's loudness without its true peak passing `ceiling` dBTP.
    Returns (audio, dict(gain_db, wanted_db, capped, note, lufs, true_peak)) with the measurements after the gain."""
    lv, tp = dsp.lufs(v, sr), _tp(v, sr)
    if lv <= -60:
        return v, dict(gain_db=0.0, wanted_db=0.0, capped=False, note="too quiet to measure: no gain applied", lufs=lv, true_peak=tp)
    want = mix_lufs - lv
    g = min(want, ceiling - tp)
    return v * dsp.undb(g), dict(gain_db=round(float(g), 2), wanted_db=round(float(want), 2), capped=bool(g < want - 0.2),
                                 note="", lufs=lv + g, true_peak=tp + g)


def safe_peak(v, sr):
    """No gain unless the sum would clip: then turn it down to -1 dBTP. Returns (audio, gain_db, lufs, true_peak)."""
    lv, tp = dsp.lufs(v, sr), _tp(v, sr)
    if tp > -0.1:
        g = -1.0 - tp
        return v * dsp.undb(g), round(float(g), 2), lv + g, tp + g
    return v, 0.0, lv, tp


# ---------------------------------------------------------------- the whole job
def build(stems_dir, vocals, mix=None, tv=None, cuts=None, bpm=None, fade_ms=30.0, name=None, log=print):
    """Read everything and build the versions in memory. Returns a dict (nothing is written)."""
    if cuts and fade_ms <= 0:
        raise VersionsError("--fade must be more than 0 ms")
    mixp = Path(mix).expanduser() if mix else None
    if mixp is not None and not mixp.is_file():
        raise VersionsError(f"{mixp} not found")
    parsed = parse_cuts(cuts) if cuts else []
    files = list_stems(stems_dir, exclude=[mixp] if mixp else [])
    vocal, other, miss = split_stems(files, vocals)
    log(f"adding up {len(other)} instrumental and {len(vocal)} vocal stem(s) …")
    inst, sr, long_o, short_o = sum_stems(other)
    voc, srv, long_v, short_v = sum_stems(vocal)
    if sr != srv:
        raise VersionsError(f"the vocal stems are {srv} Hz and the others {sr} Hz: export every stem at the same sample rate")
    n = max(len(inst), len(voc))
    inst, voc = np.pad(inst, ((0, n - len(inst)), (0, 0))), np.pad(voc, ((0, n - len(voc)), (0, 0)))
    spread = max(long_o, long_v) - min(short_o, short_v)
    r = dict(sr=sr, stems_dir=str(stems_dir), vocal=[f.name for f in vocal], other=[f.name for f in other], unmatched=miss,
             length_s=n / sr, length_spread_s=spread, notes=[], versions=[], null=None, mix=None, cuts=[])
    if spread > 0.1:
        r["notes"].append(f"The stems differ in length by up to {spread:.2f} s (the shorter ones are padded with silence at the end). "
                          "If they were exported from different start points, they will not line up: export them all from the same start.")
    mix_y = None
    if mixp is not None:
        mix_y, msr = _read(mixp)
        if msr != sr:
            raise VersionsError(f"the mix is {msr} Hz and the stems are {sr} Hz: export them at the same sample rate")
        r["mix"] = dict(file=mixp.name, lufs=round(dsp.lufs(mix_y, sr), 2), true_peak=round(_tp(mix_y, sr), 2))
        log("null test: stems added up against the mix …")
        r["null"] = null_test(inst + voc, mix_y, sr)
    base = name or (mixp.stem if mixp else Path(stems_dir).expanduser().resolve().name)
    r["name"] = safe_name(base)
    tvg = None if tv is None else float(tv)
    items = [("instrumental", f"{r['name']} (instrumental).wav", "the non-vocal stems added up", inst),
             ("a cappella", f"{r['name']} (a cappella).wav", "the vocal stems added up", voc)]
    if tvg is not None:
        items.append(("TV mix", f"{r['name']} (TV mix).wav", f"the instrumental plus the vocals at {tvg:+g} dB", inst + voc * dsp.undb(tvg)))
    ceiling = min(r["mix"]["true_peak"], -1.0) if mixp else None
    for kind, fname, how, y in items:
        if mixp:
            y, g = match_to_mix(y, sr, r["mix"]["lufs"], ceiling)
            gnote = (f"gain {g['gain_db']:+.2f} dB to match the mix's {r['mix']['lufs']:.1f} LUFS (gain only)"
                     + (f"; it stops {g['wanted_db'] - g['gain_db']:.1f} dB short of the mix's loudness because its true peak would pass {ceiling:.1f} dBTP "
                        "(matching it fully needs a limiter, which this command does not use: run `hypnomix master` on it if you want that)" if g["capped"] else "")
                     + (f"; {g['note']}" if g["note"] else ""))
            gain, lv, tp = g["gain_db"], g["lufs"], g["true_peak"]
        else:
            y, gain, lv, tp = safe_peak(y, sr)
            gnote = ("no gain change (give --mix to match the mix's loudness)" if gain == 0 else
                     f"turned down {abs(gain):.1f} dB because the sum would clip (to -1 dBTP); no other gain change")
        r["versions"].append(dict(kind=kind, file=fname, how=how, gain_db=gain, gain_note=gnote, audio=y, dither="tpdf",
                                  lufs=round(float(lv), 2), true_peak=round(float(tp), 2)))
    if parsed:
        src = mix_y if mix_y is not None else inst + voc
        srcname = f"your mix ({mixp.name})" if mixp else "all the stems added up"
        dur = len(src) / sr
        bars, bar_note = (None, None)
        if bpm:
            bars, bar_note = bar_lines(src, sr, bpm)
        rows = plan_cuts(parsed, dur, bpm, bars, fade_ms / 1000.0, refine=(lambda t: refine_to_onset(src, sr, t)) if bars is not None else None)
        r["cuts"] = rows
        edit = apply_cuts(src, sr, rows, fade_ms / 1000.0)
        if mixp is None:
            edit, gedit, lv, tp = safe_peak(edit, sr)
        else:
            gedit, lv, tp = 0.0, dsp.lufs(edit, sr), _tp(edit, sr)
        how = f"cut from {srcname}: " + ", ".join(f"{mmss(x['start'])}-{mmss(x['end'])}" for x in rows) + f", {fade_ms:g} ms equal-power crossfades"
        r["versions"].append(dict(kind="radio edit", file=f"{r['name']} (radio edit).wav", how=how, gain_db=gedit,
                                  gain_note=("no gain change: this is the mix itself, minus the cuts" if mixp else
                                             "no gain change" if gedit == 0 else f"turned down {abs(gedit):.1f} dB because the sum would clip"),
                                  audio=edit, dither="off" if mixp else "tpdf", lufs=round(float(lv), 2), true_peak=round(float(tp), 2)))
        r["bar_note"] = f"bar lines {bar_note}" if bar_note else None
        r["removed_s"] = sum(x["end"] - x["start"] for x in rows)
        r["edit_length_s"] = len(edit) / sr
        r["source_length_s"] = dur
    elif bpm:
        r["notes"].append("--bpm only matters with --cut (it snaps the cut edges to bar lines): it was not used.")
    return r


def print_plan(r, check=True):
    print(f"\nVersions of {r['name']}   ({'read-only: nothing is written' if check else 'plan'})\n")
    print(f"vocal stems ({len(r['vocal'])}): " + ", ".join(r["vocal"]))
    print(f"other stems ({len(r['other'])}): " + ", ".join(r["other"]))
    for p in r["unmatched"]:
        print(f"  ! the pattern {p!r} matched no stem")
    for n in r["notes"]:
        print(f"  ! {n}")
    if r["null"]:
        n = r["null"]
        print(f"\nnull test (stems added up against {r['mix']['file']}): leftover {db_text(n['residual_db'])} below the mix: {n['verdict'].upper()}")
        print("  " + n["text"])
        for t in n["notes"]:
            print("  " + t)
    print("\nwould write:" if check else "\nwrote:")
    for v in r["versions"]:
        print(f"  {v['file']}\n      {v['how']}\n      {v['gain_note']}\n      {v['lufs']:.1f} LUFS, {v['true_peak']:+.2f} dBTP")
    if r["cuts"]:
        print(f"\nradio edit plan ({r.get('bar_note') or 'edges as given'}):")
        for x in r["cuts"]:
            a, b = x["asked"]
            asked = f"{mmss(a) if a is not None else 'start'}-{mmss(b) if b is not None else 'end'}"
            print(f"  remove {mmss(x['start'])} to {mmss(x['end'])}" + (f"  (asked {asked}; snapped to the bar line" + (", then moved onto the nearest hit" if x.get("refined") else "") + ")" if x["snapped"] else ""))
        print(f"  {mmss(r['source_length_s'])} becomes {mmss(r['edit_length_s'])} ({r['removed_s']:.2f} s removed)")
    if check:
        print("\nWith the files written, `hypnomix qc` runs on each one and VERSIONS.md holds the results.")


def report_text(r, results, target):
    L = [f"# Versions: {r['name']}", "",
         f"Written {datetime.datetime.now():%Y-%m-%d %H:%M} by `hypnomix versions` from the stems in `{Path(r['stems_dir']).name}`"
         + (f" and the mix `{r['mix']['file']}`" if r["mix"] else "") + ". Your stems and mix were only read. "
         "The numbers are measured, not heard: listen to each file once.", "",
         "## Which stems went where", "",
         "- **Vocals** (the a cappella, and the vocal part of the TV mix): " + ", ".join(f"`{x}`" for x in r["vocal"]),
         "- **Everything else** (the instrumental): " + ", ".join(f"`{x}`" for x in r["other"]), ""]
    for p in r["unmatched"]:
        L.append(f"- The pattern `{p}` in --vocals matched no stem.")
    for n in r["notes"]:
        L.append(f"- {n}")
    if r["null"]:
        n = r["null"]
        L += ["", "## Do the stems add up to the mix?", "",
              f"Null test: the stems added up, subtracted from `{r['mix']['file']}`, leave **{db_text(n['residual_db'])}** below the mix "
              f"(compared over {n['compared_s']:.1f} s). **{n['verdict'].upper()}.** {n['text']}", ""]
        L += [f"- {t}" for t in n["notes"]]
    L += ["", "## The files", "", "| file | how it was made | gain | loudness | true peak | release checks |", "|---|---|---|---|---|---|"]
    for v in r["versions"]:
        q = results[v["file"]]
        L.append(f"| {v['file']} | {v['how']} | {v['gain_db']:+.2f} dB | {v['lufs']:.1f} LUFS | {v['true_peak']:+.2f} dBTP | {q['status']} |")
    L += ["", "Gain is gain only: no limiter, EQ or other processing was added. " + (
        f"Each version was matched to the mix's {r['mix']['lufs']:.1f} LUFS." if r["mix"] else
        "No --mix was given, so no version was matched to a loudness."), ""]
    for v in r["versions"]:
        L.append(f"- **{v['file']}**: {v['gain_note']}.")
    if r["cuts"]:
        L += ["", "## The radio edit", "", (f"Edges snapped to the nearest bar line ({r['bar_note']}); the bar grid is only found to within about 30 ms, so an edge close to a drum hit or other sudden hit (within 50 ms) is moved onto the start of that hit. " if r.get("bar_note") else "The edges are exactly as you gave them. ")
              + "Crossfades are equal-power; a cut at the very start or end gets a short fade instead.", ""]
        for x in r["cuts"]:
            a, b = x["asked"]
            asked = f"{mmss(a) if a is not None else 'start'}-{mmss(b) if b is not None else 'end'}"
            L.append(f"- removed {mmss(x['start'])} to {mmss(x['end'])}" + (f" (you asked for {asked}; snapped to the nearest bar line" + (", then moved onto the nearest hit" if x.get("refined") else "") + ")" if x["snapped"] else ""))
        L += ["", f"{mmss(r['source_length_s'])} becomes {mmss(r['edit_length_s'])}: {r['removed_s']:.2f} s removed.", ""]
    L += ["", "## What each check found", ""]
    for v in r["versions"]:
        q = results[v["file"]]
        L.append(f"### {v['file']}: {q['status']}")
        if not q["fails"] and not q["warns"]:
            L.append("Nothing to flag.")
        L += [f"- FAIL {t}" for t in q["fails"]] + [f"- WARN {t}" for t in q["warns"]]
        L.append("")
    L += ["A cappella and instrumental files will often warn about leading silence, a cut-off ending or loudness against "
          f"{target:g} LUFS: that is what stems are like. Read the warnings as information, not as faults.", ""]
    return "\n".join(L)


def write_package(r, out_parent=None, target=None, log=print):
    parent = Path(out_parent).expanduser() if out_parent else paths.OUT / "versions"
    final = parent / f"{r['name']} (versions)"
    if final.exists():
        raise VersionsError(f"{final} already exists. Nothing was written: pick another --out, or move that folder away.")
    parent.mkdir(parents=True, exist_ok=True)
    partial = final.with_name(final.name + f".partial-{datetime.datetime.now():%H%M%S%f}")
    partial.mkdir()
    try:
        results = {}
        tgt = target if target is not None else (r["mix"]["lufs"] if r["mix"] else -14.0)
        for v in r["versions"]:
            log(f"writing {v['file']} …")
            dest = dsp.save(partial / v["file"], v["audio"], r["sr"], 24, dither=v["dither"])
            log(f"  checking {v['file']} …")
            res = qc.check(dest, tgt, "streaming")
            results[v["file"]] = dict(status="FAIL" if any(s == "FAIL" for _, s, _ in res) else "WARN" if any(s == "WARN" for _, s, _ in res) else "PASS",
                                      fails=[f"{n}: {d}" for n, s, d in res if s == "FAIL"], warns=[f"{n}: {d}" for n, s, d in res if s == "WARN"])
        (partial / "VERSIONS.md").write_text(report_text(r, results, tgt), encoding="utf-8")
        slim = {k: v for k, v in r.items() if k not in ("versions", "cuts")}
        slim["versions"] = [{k: v for k, v in x.items() if k != "audio"} | dict(qc=results[x["file"]]) for x in r["versions"]]
        slim["cuts"] = [dict(x, asked=list(x["asked"])) for x in r["cuts"]]
        (partial / "versions.json").write_text(json.dumps(slim, indent=1, default=str), encoding="utf-8")
        partial.rename(final)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return final, results


def main():
    ap = argparse.ArgumentParser(prog="hypnomix versions", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stems", required=True, help="folder of exported stems")
    ap.add_argument("--vocals", required=True, help='which stems are vocals, like "Lead*,Harm*"')
    ap.add_argument("--mix", help="the finished mix: runs the null test and matches each version to its loudness")
    ap.add_argument("--tv", type=A.number(-80, 24), metavar="DB", help="also write a TV mix: the instrumental plus the vocals at this many dB (0 = full song)")
    ap.add_argument("--cut", action="append", nargs="+", metavar="RANGE", help="a range to remove for the radio edit, like 1:12-1:40")
    ap.add_argument("--bpm", type=A.number(20, 400), help="snap the cut edges to the nearest bar line at this tempo (20 to 400)")
    ap.add_argument("--fade", type=A.number(0, 1000), default=30.0, metavar="MS", help="crossfade length in ms (default 30, at most 1000)")
    ap.add_argument("--name", help="the song's name for the file names (default: the mix's, or the stems folder's)")
    ap.add_argument("--target", type=A.number(-70, 0), help="loudness the release checks compare with (default: the mix's, or -14)")
    ap.add_argument("--out", help="folder to create the versions folder in (default hypnomix-out/versions)")
    ap.add_argument("--check", action="store_true", help="read-only: run the null test and print the plan")
    a = ap.parse_args()
    cuts = [x for group in (a.cut or []) for x in group]
    try:
        r = build(a.stems, a.vocals, a.mix, a.tv, cuts, a.bpm, a.fade, a.name, log=lambda s: print(s, file=sys.stderr))
        if a.check:
            print_plan(r, True)
            return
        final, results = write_package(r, a.out, a.target, log=lambda s: print(s, file=sys.stderr))
    except VersionsError as e:
        sys.exit(f"hypnomix versions: {e}")
    print_plan(r, False)
    print(f"\nrelease checks: " + ", ".join(f"{k}: {v['status']}" for k, v in results.items()))
    print(f"report: {final / 'VERSIONS.md'}")


if __name__ == "__main__":
    main()
