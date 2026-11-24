#!/usr/bin/env python3
"""Vocal harmonies: balance the parts around one YOU choose, or split them into voice tracks by pitch.

Nothing is decided for you. Run it with the vocal stems first: it lists the parts (where each usually sits,
how loud, how many bars it sings with others) as a QUESTION and changes nothing. Then choose:

  --anchor TRACK|lead|lowest|highest   the part to prioritise; it is left exactly as it is ("lead" = the shared
                                       lead rule: among the parts, the one that sings longest of those whose
                                       vowels move most)
  --reduce above|below|both            which side of it to make quieter, in pitch (default above)
  --above-db DB  --below-db DB         how much quieter than the anchor, per step (0 = leave that side alone);
                                       e.g. 0, 1, 1.5, 3, 4.5 or 6 dB, or any value
  --spread ladder|flat                 ladder: each part further away is quieter again by the step;
                                       flat: every part on that side sits one step under the anchor
  --max-cut DB                         never turn any part down by more than this in any bar (default 6)
  --window S | --bpm BPM [--bar-beats 4]   judge it bar by bar (default 2 s windows)

  --tame                               the gentle default: harmonies sit at least 1.5 dB under the lead
                                       (--lead-margin), and a part louder than the part below it by more than
                                       --tolerance (1.5 dB) comes down to exactly that edge; no further. It also
                                       reports where the harmonies sit at the same level (no space between them)
  --tolerance DB                       only act where a part is louder than its limit by more than this

Wherever two or more parts sing together, parts are only ever turned DOWN, and only where they are louder
than their target; a part already quiet enough, and every bar where the anchor isn't singing, is left alone.
Writes "<stem> (balanced).wav" per stem (gain moves with 250 ms ramps; pitch, timing and tone untouched) and
balance.json (per bar: each part's note, level, target, cut). --dry-run reports without writing audio.

  --split   (the other tool) re-arranges the stems into Voice 1 (lowest) ... Voice N (highest): every phrase
            goes to the voice matching its pitch rank among the parts singing with it, so one fader per voice
            sets each step of the stack, at whatever balance you want. The voices add up to the inputs exactly
            (5 ms complementary crossfades in quiet spots). Writes Voice N.wav and voices.json.

Use POST-CHAIN stems (Live: Export > Rendered Track: All Individual Tracks) so levels are judged as heard.

Usage:
  hypnomix voices STEM.wav [STEM.wav ...]                                  # the question: which part, how much
  hypnomix voices STEMS... --anchor lead --reduce above --above-db 1.5 --spread flat [--out DIR]
  hypnomix voices STEMS... --split [--min-gap 0.25] [--overlap 0.3]
"""
import argparse, json, os, re
import numpy as np, soundfile as sf, librosa

from pathlib import Path
from hypnomix.core.paths import out_at
from concurrent.futures import ProcessPoolExecutor

AN = 22050
FADE = 0.005


def phrases_of(path, min_gap, min_len):
    """Phrases = stretches where the stem is within 40 dB of its own loud level; gaps >= min_gap split them."""
    y, sr = sf.read(path, always_2d=True); m = y.mean(1)
    hop = int(0.01 * sr)
    e = np.sqrt(np.convolve(m ** 2, np.ones(hop * 3) / (hop * 3), "same")[::hop])
    edb = 20 * np.log10(e + 1e-12)
    loud = np.percentile(edb[edb > -100], 95) if (edb > -100).any() else -100
    act = edb > loud - 40
    segs, i, n = [], 0, len(act)
    while i < n:
        if not act[i]: i += 1; continue
        j = i
        while j < n:
            if act[j]: j += 1; continue
            k = j
            while k < n and not act[k]: k += 1
            if (k - j) * 0.01 >= min_gap or k == n: break
            j = k
        if (j - i) * 0.01 >= min_len: segs.append((i * 0.01, j * 0.01))
        i = j + 1
    # pitch per phrase
    from hypnomix.core import pitch
    t, f0, _ = pitch.track(path, fmin=65, fmax=1000, sr=AN, hop=256)     # fast, cached, active parts only
    out = []
    for a, b in segs:
        f = f0[(t >= a) & (t < b)]; f = f[~np.isnan(f)]
        out.append({"start": round(a, 3), "end": round(b, 3), "hz": float(np.median(f)) if len(f) >= 5 else None})
    return os.path.basename(path)[:-4], out, sr, len(m)


# ---------------------------------------------------------------- balance around a chosen part
STEP_CHOICES = (0, 1, 1.5, 3, 4.5, 6)


def kweight(x, sr):
    """ITU-R BS.1770 K-weighting (the 48 kHz coefficients: close enough to rank parts at 44.1 kHz)."""
    from scipy.signal import lfilter
    b1, a1 = [1.53512485958697, -2.69169618940638, 1.19839281085285], [1, -1.69065929318241, 0.73248077421585]
    b2, a2 = [1.0, -2.0, 1.0], [1, -1.99004745483398, 0.99007225036621]
    return lfilter(b2, a2, lfilter(b1, a1, x))


def measure(path, win_s):
    """Per window: level as heard (K-weighted, over the sung part only) and median pitch, or NaN if not singing."""
    y, sr = sf.read(path, always_2d=True); m = y.mean(1)
    from hypnomix.core import pitch
    pt, f0, _ = pitch.track(path, fmin=70, fmax=1000, sr=AN, hop=512)      # fast, cached, active parts only
    hop_s = 512 / AN
    kx = kweight(m, sr); win = int(win_s * sr); nwin = int(np.ceil(len(m) / win))
    lvl, pit = np.full(nwin, np.nan), np.full(nwin, np.nan)
    blk = max(1, sr // 100)
    for w in range(nwin):
        seg = kx[w * win:(w + 1) * win]
        if len(seg) < sr // 4:
            continue
        fr = np.sqrt(np.convolve(seg ** 2, np.ones(sr // 20) / (sr // 20), "valid")[::blk] + 1e-20)
        fdb = 20 * np.log10(fr); sung = fdb > -50
        if not len(fdb) or sung.mean() < 0.15:
            continue                                                  # not really singing in this window
        lvl[w] = 10 * np.log10(np.mean(10 ** (fdb[sung] / 10)))
        fw = f0[int(w * win_s / hop_s): int((w + 1) * win_s / hop_s)]; fw = fw[~np.isnan(fw)]
        if len(fw) > 5:
            pit[w] = float(np.median(fw))
    return os.path.basename(path)[:-4], lvl, pit, sr, len(m)


def plan(levels, pitches, anchor, reduce="above", above_db=1.5, below_db=1.5, spread="ladder", max_cut=6.0, tolerance=0.0,
         lead=None, lead_margin=0.0, same_db=1.0):
    """Gains in dB per part per window (pure). levels/pitches: {part: array per window (NaN = not singing)}.
    anchor: a part name, 'lowest' or 'highest'. Only turns parts down, never more than max_cut."""
    names = list(levels)
    nwin = len(next(iter(levels.values())))
    gains = {n: np.zeros(nwin) for n in names}
    rows = []
    for w in range(nwin):
        parts = [n for n in names if np.isfinite(levels[n][w]) and np.isfinite(pitches[n][w])]
        if len(parts) < 2:
            continue
        parts.sort(key=lambda n: pitches[n][w])
        if anchor == "lowest":
            ai = 0
        elif anchor == "highest":
            ai = len(parts) - 1
        elif anchor in parts:
            ai = parts.index(anchor)
        else:
            continue                                                  # the chosen part isn't singing here
        tgt = {parts[ai]: levels[parts[ai]][w]}
        for side, idxs, step in (("above", range(ai + 1, len(parts)), above_db),
                                 ("below", range(ai - 1, -1, -1), below_db)):
            if reduce not in (side, "both") or step < 0:
                continue
            if step == 0 and tolerance <= 0:
                continue                                              # nothing asked for on this side
            prev = tgt[parts[ai]]
            for i in idxs:
                n = parts[i]
                cap = prev - step
                if step == 0:      # taming only: bring an overshadowing part down to the edge of the tolerance, no further
                    want = cap + tolerance if levels[n][w] > cap + tolerance else levels[n][w]
                else:              # a step the person asked for: down to the cap, if it is over it by more than the tolerance
                    want = cap if levels[n][w] > cap + tolerance else levels[n][w]
                tgt[n] = max(want, levels[n][w] - abs(max_cut))                  # where it really lands
                if spread == "ladder":
                    prev = tgt[n]          # the next part steps down from this one
        if lead in parts and lead_margin > 0:          # every harmony sits at least lead_margin under the lead
            top = levels[lead][w] - lead_margin
            for n in parts:
                if n != lead and min(tgt.get(n, levels[n][w]), levels[n][w]) > top:
                    tgt[n] = max(top, levels[n][w] - abs(max_cut))
        harm = [tgt.get(n, levels[n][w]) for n in parts if n != lead]
        same = len(harm) >= 2 and (max(harm) - min(harm)) < same_db   # no space between the harmonies here
        if lead in parts:
            tgt[lead] = levels[lead][w]                # the lead is never turned down
        row = []
        for n in parts:
            cur = levels[n][w]; t = tgt.get(n, cur)
            gains[n][w] = max(min(0.0, t - cur), -abs(max_cut))
            row.append(dict(part=n, note=librosa.hz_to_note(pitches[n][w]), level=round(float(cur), 1),
                            target=round(float(t), 1), cut=round(float(gains[n][w]), 1), anchor=bool(n == parts[ai])))
        rows.append(dict(window=w + 1, parts=row, harmonies_same_level=bool(same)))
    return gains, rows


def question(names, levels, pitches, win_s):
    print("QUESTION: these vocal parts sing together. Which one should be prioritised (--anchor)?")
    order = sorted(names, key=lambda n: np.nanmedian(pitches[n]) if np.isfinite(pitches[n]).any() else 0)
    for n in order:
        together = sum(1 for w in range(len(levels[n])) if np.isfinite(levels[n][w]) and
                       sum(np.isfinite(levels[m][w]) for m in names if m != n) >= 1)
        note = librosa.hz_to_note(np.nanmedian(pitches[n])) if np.isfinite(pitches[n]).any() else "?"
        lv = np.nanmedian(levels[n]) if np.isfinite(levels[n]).any() else float("nan")
        print(f"  {n:30s} usually {note:5s}  level {lv:6.1f} dB  sings with others in {together} windows of {win_s:g} s")
    print("  Recommended: --tame (harmonies kept a little under the lead, at least 1.5 dB; a higher part more "
          "than 1.5 dB louder than the part below it comes down to that edge; no further; reports harmonies at one level).")
    print("  Or choose: --anchor PART|lead|lowest|highest, --reduce above|below|both, --above-db/--below-db per step "
          f"({' / '.join(f'{x:g}' for x in STEP_CHOICES)} dB, or any value), --spread ladder|flat, --max-cut, --tolerance.")
    print("Nothing was changed.")


# ---------------------------------------------------------------- learn the person's own harmony spacing
STYLE = Path.home() / ".hypnomix" / "harmony-style.json"
CACHE = Path.home() / ".hypnomix" / "cache"
VOCAL = ("Lead Vocal", "Vocal", "Harmony", "Backing Vocal")


def _hx(*args):
    import subprocess, sys as _s
    r = subprocess.run([_s.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def song_spacing(set_path, win_s=2.0):
    """How one finished song balances its vocals: per window where the lead and harmonies sing together, how far
    each harmony sits under the lead and how far each higher harmony sits from the one below it (dB, after faders;
    same measurement as the balancing itself). Returns a dict, or None if the song has no lead + harmony."""
    import gzip, hashlib, math, os, xml.etree.ElementTree as ET
    set_path = Path(set_path)
    st = os.stat(set_path)
    key = hashlib.sha1(f"{set_path.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16]
    nd, rd = CACHE / "names" / key, CACHE / "renders" / key
    nj = nd / "names.json"
    if not nj.exists():
        code, out = _hx("name", set_path, "--out", nd)
        if not nj.exists():
            return dict(song=set_path.stem, skipped=f"naming failed: {out.strip()[-160:]}")
    rows = json.loads(nj.read_text())["tracks"]
    voc = [r for r in rows if r.get("kind") == "Audio" and r.get("on", True) and float(r.get("confidence") or 0) >= 0.5
           and any(str(r.get("final") or r.get("label") or "").startswith(x) for x in VOCAL)]
    if len(voc) < 2:
        return dict(song=set_path.stem, skipped="fewer than two playing vocal tracks")
    dup = sorted({r["old"] for r in voc if sum(1 for x in voc if x["old"] == r["old"]) > 1})
    if dup:
        return dict(song=set_path.stem, skipped=f"several vocal tracks share one name ({', '.join(dup)}): rename them to "
                                                "tell the parts apart")
    lead_row = next((r for r in voc if str(r.get("final") or r.get("label")).startswith("Lead Vocal")), None)
    names = [r["old"] for r in voc]
    safe = lambda n: re.sub(r'[\\/:*?"<>|]', "-", n)
    missing = [n for n in names if not (rd / f"{safe(n)}.wav").exists()]
    if missing:
        _hx("render", set_path, "--tracks", *missing, "--out", rd)
    files = {n: rd / f"{safe(n)}.wav" for n in names if (rd / f"{safe(n)}.wav").exists()}
    if len(files) < 2:
        return dict(song=set_path.stem, skipped="could not render the vocals")
    root = ET.fromstring(gzip.open(set_path).read())
    fader = {}
    for t in root.find(".//Tracks"):
        nm = t.find("./Name/EffectiveName").get("Value")
        vol = t.find("./DeviceChain/Mixer/Volume/Manual")
        if nm in files and vol is not None and float(vol.get("Value")) > 0:
            fader[nm] = 20 * math.log10(float(vol.get("Value")))
    res = {n: measure(str(p), win_s) for n, p in files.items()}
    nwin = max(len(r[1]) for r in res.values())
    pad = lambda x: np.pad(x, (0, nwin - len(x)), constant_values=np.nan)
    lv = {n: pad(r[1]) + fader.get(n, 0.0) for n, r in res.items()}
    pt = {n: pad(r[2]) for n, r in res.items()}
    lead = lead_row["old"] if lead_row and lead_row["old"] in files else None
    if lead is None:
        from hypnomix.core import dsp
        from hypnomix.engineer.roles import pick_lead
        lead = pick_lead([(n, dsp.load(p, 22050)[0]) for n, p in files.items()], 22050)
    margins, steps, doubles = [], [], []
    st_ = lambda f1, f2: abs(12 * math.log2(f1 / f2))
    lead_ok = lv[lead][np.isfinite(lv[lead])]
    lead_floor = float(np.median(lead_ok)) - 6.0 if len(lead_ok) else -np.inf   # the lead singing at its normal level
    for w in range(nwin):
        if not (np.isfinite(lv[lead][w]) and np.isfinite(pt[lead][w])) or lv[lead][w] < lead_floor:
            continue                    # not where the lead sings out (word tails and breaths would skew the margin)
        sing = [n for n in files if n != lead and np.isfinite(lv[n][w]) and np.isfinite(pt[n][w])]
        # a part on the lead's own note (within a semitone) is a double or a comp piece, not a harmony
        dbl = [n for n in sing if st_(pt[n][w], pt[lead][w]) < 1.0]
        doubles += [float(lv[lead][w] - lv[n][w]) for n in dbl]
        harm = [n for n in sing if n not in dbl]
        if not harm:
            continue
        margins += [float(lv[lead][w] - lv[n][w]) for n in harm]
        harm.sort(key=lambda n: pt[n][w])
        steps += [float(lv[b][w] - lv[a][w]) for a, b in zip(harm, harm[1:])
                  if st_(pt[b][w], pt[a][w]) >= 1.0]                          # higher minus lower, different notes
    if len(margins) < 5:
        return dict(song=set_path.stem, skipped="the lead and harmonies hardly sing together")
    q = lambda x, p: round(float(np.percentile(x, p)), 1)
    out = dict(song=set_path.stem, set=str(set_path), lead=lead, harmonies=[n for n in files if n != lead],
               windows=len(margins), lead_margin=dict(p10=q(margins, 10), p25=q(margins, 25), median=q(margins, 50),
                                                       p75=q(margins, 75)))
    if len(steps) >= 5:
        out["higher_minus_lower"] = dict(p10=q(steps, 10), median=q(steps, 50), p90=q(steps, 90),
                                         abs_median=q(np.abs(steps), 50), pairs=len(steps))
    if len(doubles) >= 5:
        out["doubles_under_lead"] = dict(median=q(doubles, 50), readings=len(doubles))
    return out


def learn_style(sets):
    songs = []
    for sp in sets:
        r = song_spacing(sp)
        songs.append(r)
        if r.get("skipped"):
            print(f"  {r['song']}: skipped ({r['skipped']})")
        else:
            lm = r["lead_margin"]; hl = r.get("higher_minus_lower")
            print(f"  {r['song']}: lead {r['lead']} vs {len(r['harmonies'])} harmonies, {r['windows']} readings: harmonies sit "
                  f"{lm['median']:+.1f} dB under the lead (middle half {lm['p25']:+.1f} to {lm['p75']:+.1f})"
                  + (f"; a higher harmony vs the one below: median {hl['median']:+.1f} dB (90% at or under "
                     f"{hl['p90']:+.1f}), typical gap {hl['abs_median']:.1f} dB" if hl else ""))
    ok = [r for r in songs if not r.get("skipped")]
    if not ok:
        raise SystemExit("no song with a lead and harmonies singing together: nothing learned")
    med = lambda xs: round(float(np.median(xs)), 1)          # each song counts once
    lm25 = med([r["lead_margin"]["p25"] for r in ok])
    hl = [r["higher_minus_lower"] for r in ok if r.get("higher_minus_lower")]
    style = dict(
        songs=songs,
        lead_margin=max(0.0, lm25),                              # 3 in 4 of your readings already sit at least this far under
        lead_margin_median=med([r["lead_margin"]["median"] for r in ok]),
        tolerance=max(0.5, med([h["p90"] for h in hl])) if hl else 1.5,   # a higher harmony louder than this over the one below is unusual for you
        higher_minus_lower_median=med([h["median"] for h in hl]) if hl else None,
        same_db=min(1.0, max(0.3, med([h["abs_median"] for h in hl]) / 2)) if hl else 1.0,
        note="lead_margin = the 25th percentile of how far your harmonies sit under the lead (per song, then the median "
             "song); tolerance = the 90th percentile of how much louder a higher harmony is than the one below it. "
             "Balancing only moves what falls outside your own habits.")
    return style


def style_defaults():
    if STYLE.exists():
        try:
            return json.loads(STYLE.read_text())
        except Exception:
            return None
    return None


def balance(a):
    win_s = a.window or ((60.0 / a.bpm) * a.bar_beats if a.bpm else 2.0)
    with ProcessPoolExecutor(min(8, len(a.stems))) as ex:
        res = list(ex.map(measure, a.stems, [win_s] * len(a.stems)))
    names = [r[0] for r in res]
    nwin = max(len(r[1]) for r in res)
    pad = lambda x: np.pad(x, (0, nwin - len(x)), constant_values=np.nan)
    levels = {r[0]: pad(r[1]) for r in res}; pitches = {r[0]: pad(r[2]) for r in res}
    for item in a.fader or []:                   # raw clips: add each track's fader so levels compare as heard
        nm, _, db = item.rpartition("=")
        if nm in levels:
            levels[nm] = levels[nm] + float(db)
    if not a.anchor:
        question(names, levels, pitches, win_s)
        return
    anchor = a.anchor
    if anchor == "lead":
        from hypnomix.core import dsp
        from hypnomix.engineer.roles import pick_lead
        anchor = pick_lead([(n, dsp.load(p, 22050)[0]) for n, p in zip(names, a.stems)], 22050)
        print(f"lead (shared rule): {anchor}")
    elif anchor not in ("lowest", "highest") and anchor not in names:
        raise SystemExit(f"--anchor {anchor!r}: not one of the parts ({', '.join(names)}), lead, lowest or highest")
    lead = None
    if a.lead_margin > 0:
        lead = a.lead if a.lead in names else None
        if lead is None:
            from hypnomix.core import dsp
            from hypnomix.engineer.roles import pick_lead
            lead = pick_lead([(n, dsp.load(p, 22050)[0]) for n, p in zip(names, a.stems)], 22050)
        print(f"lead: {lead} (every other part kept at least {a.lead_margin:g} dB under it where both sing)")
    gains, rows = plan(levels, pitches, anchor, a.reduce, a.above_db, a.below_db, a.spread, a.max_cut, a.tolerance,
                       lead, a.lead_margin)
    od = out_at(a.out, "voices", "balance")
    summary = {}
    for (n, _, _, sr, L), path in zip(res, a.stems):
        g = gains[n]
        summary[n] = dict(windows_lowered=int((g < -0.05).sum()), max_cut_db=round(float(g.min()), 1) if len(g) else 0.0)
        if a.dry_run:
            continue
        win = int(win_s * sr)
        env = np.repeat(10 ** (g / 20), win)[:L]
        env = np.pad(env, (0, max(0, L - len(env))), constant_values=1.0)
        k = int(0.25 * sr)
        env = np.convolve(np.pad(env, (k, k), mode="edge"), np.ones(k) / k, "same")[k:k + L]
        y, _ = sf.read(path, always_2d=True)
        sf.write(str(od / f"{n} (balanced).wav"), (y * env[:len(y), None]).astype(np.float32), sr, subtype="FLOAT")
    settings = dict(anchor=anchor, reduce=a.reduce, above_db=a.above_db, below_db=a.below_db, spread=a.spread,
                    max_cut=a.max_cut, tolerance=a.tolerance, lead=lead, lead_margin=a.lead_margin, window_s=win_s)
    json.dump(dict(settings=settings, summary=summary, windows=rows), open(str(od / "balance.json"), "w"), indent=1)
    fixed = sum(1 for r in rows if any(p["cut"] < -0.05 for p in r["parts"]))
    same = sum(1 for r in rows if r.get("harmonies_same_level"))
    if same:
        print(f"no space between the harmonies (within 1 dB of each other) in {same} of {len(rows)} windows: a gentle "
              "spread is your choice (e.g. --anchor lowest --above-db 1 --spread ladder, or name the part to step down)")
    print(json.dumps(settings))
    for n, sm_ in summary.items():
        print(f"  {n:30s} lowered in {sm_['windows_lowered']} windows, at most {sm_['max_cut_db']:+.1f} dB")
    print(f"{len(rows)} windows with the anchor singing with others; {fixed} turned something down"
          + (" (dry run: no audio written)" if a.dry_run else f" → {od}"))


def main():
    ap = argparse.ArgumentParser(prog="hypnomix voices", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stems", nargs="*"); ap.add_argument("--out")
    ap.add_argument("--learn", nargs="+", metavar="SONG.als",
                    help="learn how YOU space harmonies from finished songs; --tame then uses your numbers")
    ap.add_argument("--anchor", help="part to prioritise: a stem name, lead, lowest or highest (without it: the question)")
    ap.add_argument("--reduce", choices=["above", "below", "both"], default="above")
    ap.add_argument("--above-db", type=float, default=0.0, help="dB quieter per step above the anchor (you choose)")
    ap.add_argument("--below-db", type=float, default=0.0, help="dB quieter per step below the anchor (you choose)")
    ap.add_argument("--spread", choices=["ladder", "flat"], default="ladder")
    ap.add_argument("--max-cut", type=float, default=6.0)
    ap.add_argument("--tolerance", type=float, default=None,
                    help="only turn a part down where it is louder than its limit by more than this many dB (default 1.5); "
                         "with --tame it comes down to exactly this far above the part below, no further")
    ap.add_argument("--lead", help="the lead part (default: the shared lead rule)")
    ap.add_argument("--fader", action="append", metavar="NAME=DB",
                    help="raw (pre-fader) renders: the track's fader in dB, so parts compare as heard (repeatable)")
    ap.add_argument("--lead-margin", type=float, default=None,
                    help="keep every other part at least this many dB under the lead where both sing (--tame: 1.5)")
    ap.add_argument("--tame", action="store_true",
                    help="the gentle default: only tame overshadowing parts (anchor lowest, above, 0 dB step): a higher "
                         "part is turned down only where it is louder than the part below it by more than --tolerance, and only to that edge")
    ap.add_argument("--window", type=float, help="seconds per judged window (default: one bar with --bpm, else 2 s)")
    ap.add_argument("--bpm", type=float); ap.add_argument("--bar-beats", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--split", action="store_true", help="split into Voice 1..N by pitch instead (no level changes)")
    ap.add_argument("--min-gap", type=float, default=0.25); ap.add_argument("--min-len", type=float, default=0.2)
    ap.add_argument("--overlap", type=float, default=0.3, help="fraction of a phrase two parts must share to count as singing together")
    a = ap.parse_args()
    a.tolerance_given = a.tolerance is not None
    if a.tolerance is None:
        a.tolerance = 1.5
    if a.learn:
        print(f"learning how you balance harmonies from {len(a.learn)} song(s)…")
        st = learn_style(a.learn)
        STYLE.parent.mkdir(parents=True, exist_ok=True)
        STYLE.write_text(json.dumps(st, indent=1))
        print(f"\nyour pattern: harmonies sit about {st['lead_margin_median']:.1f} dB under the lead (3 in 4 at least "
              f"{st['lead_margin']:.1f} dB); a higher harmony is at most {st['tolerance']:.1f} dB louder than the one below it "
              f"in 9 of 10 readings" + (f" (median {st['higher_minus_lower_median']:+.1f} dB)" if st.get('higher_minus_lower_median') is not None else "")
              + f"\n→ --tame now uses: lead margin {st['lead_margin']:.1f} dB, tolerance {st['tolerance']:.1f} dB.  Saved: {STYLE}")
        if not a.stems:
            return
    if not a.stems:
        ap.error("give the vocal stems (or --learn SONG.als …)")
    if not a.split:
        if a.tame:
            a.anchor, a.reduce, a.above_db = a.anchor or "lowest", "above", 0.0
            st = style_defaults()
            if st and a.lead_margin is None:
                a.lead_margin = float(st["lead_margin"])
            if st and a.tolerance_given is False:
                a.tolerance = float(st["tolerance"])
            if st:
                print(f"your own spacing (from {sum(1 for x in st['songs'] if not x.get('skipped'))} songs): "
                      f"lead margin {a.lead_margin:.1f} dB, tolerance {a.tolerance:.1f} dB")
            if a.lead_margin is None:
                a.lead_margin = 1.5
        if a.lead_margin is None:
            a.lead_margin = 0.0
        steps = {"above": [a.above_db], "below": [a.below_db], "both": [a.above_db, a.below_db]}[a.reduce]
        if a.anchor and max(steps) <= 0:
            print(f"only taming overshadowing parts: a part is turned down only where it is louder than the part "
                  f"{'below' if a.reduce != 'below' else 'above'} it by more than {a.tolerance:g} dB, and only down to "
                  f"that edge (no step asked for)")
        balance(a)
        return
    with ProcessPoolExecutor(min(8, len(a.stems))) as ex:
        res = list(ex.map(phrases_of, a.stems, [a.min_gap] * len(a.stems), [a.min_len] * len(a.stems)))
    sr = res[0][2]; L = max(r[3] for r in res)
    P = [dict(p, src=name) for name, ph, _, _ in res for p in ph if p["hz"]]
    # rank: how many simultaneous phrases (overlap >= a.overlap of this phrase) are lower in pitch
    for p in P:
        dur = p["end"] - p["start"]
        p["with"] = [q for q in P if q is not p and q["src"] != p["src"] and
                     min(p["end"], q["end"]) - max(p["start"], q["start"]) >= a.overlap * min(dur, q["end"] - q["start"])]
        # rank = number of OTHER PARTS (each counted once) singing lower at the same time
        p["rank"] = len({q["src"] for q in p["with"] if q["hz"] < p["hz"]})
    # assign voices greedily in time order; bump up if the wanted voice is busy with an overlapping phrase
    P.sort(key=lambda p: (p["start"], p["hz"]))
    nsrc = len({p["src"] for p in P}); busy = []
    for p in P:
        taken = {b["voice"] for b in busy if min(b["end"], p["end"]) - max(b["start"], p["start"]) > 0.05}
        free = [v for v in range(nsrc) if v not in taken] or [p["rank"]]
        p["voice"] = min(free, key=lambda v: (abs(v - p["rank"]), v))   # nearest free voice to its rank
        busy.append(p)
    nv = max(p["voice"] for p in P) + 1
    # per stem: label every sample with a voice (gaps go to the nearest phrase's voice), complementary fades
    voices = np.zeros((nv, L, 2), np.float32)
    for name, ph, _, _ in res:
        path = next(s for s in a.stems if os.path.basename(s)[:-4] == name)
        y, _ = sf.read(path, always_2d=True)
        if y.shape[1] == 1: y = np.repeat(y, 2, 1)
        y = np.pad(y, ((0, L - len(y)), (0, 0)))
        mine = sorted([p for p in P if p["src"] == name], key=lambda p: p["start"])
        if not mine:
            voices[0] += y; continue
        # boundaries halfway between consecutive phrases
        cuts = [0] + [int((mine[i]["end"] + mine[i + 1]["start"]) / 2 * sr) for i in range(len(mine) - 1)] + [L]
        labels = [p["voice"] for p in mine]
        w = np.zeros((nv, L), np.float32)
        for i, v in enumerate(labels):
            w[v, cuts[i]:cuts[i + 1]] = 1
        f = int(FADE * sr)
        for i in range(1, len(labels)):
            if labels[i] == labels[i - 1]: continue
            c = cuts[i]; s0, s1 = max(0, c - f), min(L, c + f); r = np.linspace(0, 1, s1 - s0)
            w[:, s0:s1] = 0; w[labels[i - 1], s0:s1] = 1 - r; w[labels[i], s0:s1] = r
        voices += w[:, :, None] * y[None]
    od = out_at(a.out, "voices", os.path.basename(os.path.dirname(os.path.abspath(a.stems[0]))) or "stems")
    for v in range(nv):
        sf.write(str(od / f"Voice {v + 1}.wav"), voices[v], sr, subtype="FLOAT")
    # exactness check: voices sum == stems sum
    tot = np.zeros((L, 2), np.float32)
    for s in a.stems:
        y, _ = sf.read(s, always_2d=True); y = np.repeat(y, 2, 1) if y.shape[1] == 1 else y
        tot[:len(y)] += y
    err = np.abs(voices.sum(0) - tot).max()
    rep = [{"start": p["start"], "end": p["end"], "src": p["src"], "note": librosa.hz_to_note(p["hz"]),
            "voice": p["voice"] + 1, "sings_with": len(p["with"])} for p in P]
    json.dump({"voices": nv, "phrases": rep, "max_sum_error": float(err)}, open(str(od / "voices.json"), "w"), indent=1)
    print(f"{len(P)} phrases -> {nv} voices; voices sum to the original within {20 * np.log10(err + 1e-12):.0f} dBFS")
    for v in range(nv):
        ps = [p for p in P if p["voice"] == v]
        if ps:
            hz = np.median([p["hz"] for p in ps]); srcs = sorted({p["src"] for p in ps})
            print(f"  Voice {v + 1}: {len(ps)} phrases, median {librosa.hz_to_note(hz)}, from {', '.join(srcs)}")
    print(f"→ {od}")


if __name__ == "__main__":
    main()
