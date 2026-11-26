#!/usr/bin/env python3
"""Vocal level consistency: does the vocal stay at an even level from line to line, and do the upper parts sit under
the main melody? Run it in the first scan and again before every final export (edits made since the scan, such as
restored comps, re-tuned notes or fader moves, can change it).

Two checks, line by line (a line = one lyric line: a phrase of the lead singer's track, split at gaps of 0.3 s or
more, long phrases cut at about 9 s; --lines-from picks the track):
  upper   a part pitched above the melody is louder than the melody minus --upper-under dB on a line (default 1.5:
          upper harmonies sit slightly under the melody). Parts below the melody are never flagged.
  jump    the whole stack's loudness on a line differs from the lines around it (median of up to three either side) by
          --jump dB or more: a line that drops away or jumps out (judged after the upper fixes).

--melody is the part the others are measured against: the lead as heard. When the track called "Lead" has been
turned well down and a lower harmony carries the tune, name that harmony (the "lower lead").

Levels are measured as heard where possible:
  --heard DIR    one file per vocal track, already as heard (Live: solo each track and export)
  --renders DIR  `hypnomix render` output (raw clips): the track's fader and volume automation from the set are
                 applied here. Track compressors are not, so differences read larger than heard: a first look.
Volume automation acts after a track's devices, so the fixes below change the heard level exactly by their dB.

  hypnomix vocallevel SET.als (--heard DIR | --renders DIR) [--tracks ...] [--melody TRACK] [--order ORDER]
                      [--jump 1.5] [--upper-under 1.5] [--keep-ending 2] [--json OUT.json]
                      [--apply NEW.als [--group "Vocals"]]

  --apply      write the fixes as volume automation on a NEW set: each upper part lowered on the lines where it is
               over, then the stack's lines evened out on the vocal group's volume (--group; default the melody's
               group track). Changes ramp in the gaps between lines; existing automation is kept and offset.
  --keep-ending  the song's last N lines are never raised (an ending that dies away is usually on purpose).

Track names default to every file in the folder. The pitch order (which parts are above the melody) comes from
--order (a list low to high, or scan's order.json), else it is measured from the audio (median pitch: rough).
"""
import argparse
import gzip
import json
import re
import sys
from pathlib import Path

import numpy as np

HOP_S = 0.05
VOL_MAX = 1.99526            # Live's +6 dB


def _tempo(x):
    m = re.search(r'<Tempo>.*?<Manual Value="([^"]*)"', x, re.S)
    return float(m.group(1)) if m else 120.0


def _track(x, name):
    for m in re.finditer(r'<(AudioTrack|MidiTrack|GroupTrack) Id="(\d+)"[^>]*>.*?</\1>', x, re.S):
        if re.search(r'<EffectiveName Value="%s" />' % re.escape(name), m.group(0)):
            return m
    return None


def _volume(t):
    mx = t[t.rfind("<Mixer>"):]
    vol = re.search(r'<Volume>.*?<Manual Value="([^"]*)".*?<AutomationTarget Id="(\d+)"', mx, re.S)
    if not vol:
        return None, None, None
    tid = vol.group(2)
    env = re.search(r'<AutomationEnvelope Id="\d+">\s*<EnvelopeTarget>\s*<PointeeId Value="%s" />.*?'
                    r'</AutomationEnvelope>' % tid, t, re.S)
    return float(vol.group(1)), tid, env


def _points(env):
    return sorted((float(a), float(b)) for a, b in
                  re.findall(r'<FloatEvent Id="\d+" Time="([^"]+)" Value="([^"]+)"', env.group(0)))


def volume_curve(x, name, n, sr):
    """The track's volume over time (linear): its fader, or its volume automation where it has one."""
    m = _track(x, name)
    if m is None:
        return None
    fader, _, env = _volume(m.group(0))
    if fader is None:
        return np.ones(n, dtype=np.float32)
    if env is None:
        return np.full(n, fader, dtype=np.float32)
    bps = _tempo(x) / 60
    pts = [(max(b, 0.0) / bps, v) for b, v in _points(env)]
    ts = np.arange(n, dtype=np.float64) / sr
    return np.interp(ts, [p[0] for p in pts], [p[1] for p in pts]).astype(np.float32)


def _load(p):
    import soundfile as sf
    y, sr = sf.read(str(p), dtype="float32", always_2d=True)
    return y.mean(1), sr


def lines(y, sr, floor_db=-45.0, gap_s=0.35, min_s=1.0, max_s=9.0):
    """Sung phrases: (t0, t1) in seconds. A part that hardly stops would give one long "line": phrases longer than
    max_s are cut into equal stretches of about max_s/1.5 at their quietest 50 ms near each cut."""
    h = int(HOP_S * sr)
    k = len(y) // h
    if k == 0:
        return []
    e = np.sqrt(np.mean(y[:k * h].reshape(k, h) ** 2, axis=1))
    on = e > 10 ** (floor_db / 20)
    g = int(round(gap_s / HOP_S))
    out, i = [], 0
    while i < k:
        if on[i]:
            j = i
            while j < k and (on[j] or on[j:j + g].any()):
                j += 1
            if (j - i) * HOP_S >= min_s:
                L = (j - i) * HOP_S
                if max_s and L > max_s:
                    k_ = int(np.ceil(L / (max_s / 1.5)))
                    cuts = [i]
                    for c in range(1, k_):
                        c0 = i + int(round((j - i) * c / k_))
                        w = max(1, int(0.4 / HOP_S))
                        lo, hi = max(cuts[-1] + 1, c0 - w), min(j - 1, c0 + w)
                        cuts.append(lo + int(np.argmin(e[lo:hi + 1])) if hi >= lo else c0)
                    cuts.append(j)
                    out += [(a_ * HOP_S, b_ * HOP_S) for a_, b_ in zip(cuts, cuts[1:]) if b_ > a_]
                else:
                    out.append((i * HOP_S, j * HOP_S))
            i = j
        else:
            i += 1
    return out


def loudness(y, sr, t0, t1):
    """K-weighted loudness of a stretch (LUFS); -inf when silent or too short."""
    import pyloudnorm as pl
    seg = y[int(t0 * sr):int(t1 * sr)]
    if len(seg) < int(0.45 * sr) or np.abs(seg).max() < 1e-5:
        return -np.inf
    return float(pl.Meter(sr, block_size=0.4).integrated_loudness(seg))


def median_pitch(y, sr):
    """Median sung pitch (MIDI) where the part is active; nan when unclear."""
    import librosa
    if sr != 22050:
        y = librosa.resample(y, orig_sr=sr, target_sr=22050)
    f0 = librosa.yin(y, fmin=70, fmax=1000, sr=22050, frame_length=2048, hop_length=1024)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=1024)[0][:len(f0)]
    ok = rms > max(1e-4, np.percentile(rms, 90) * 0.1)
    return float(np.median(librosa.hz_to_midi(f0[ok]))) if ok.sum() > 20 else float("nan")


def _mmss(t):
    return f"{int(t // 60)}:{t % 60:05.2f}"


def _jumps(g, keep_ending=0):
    """Per line: dB the stack sits off the median of up to three lines either side (nan with fewer than three): one
    odd line next door can't make its neighbour look odd too."""
    out = np.full(len(g), np.nan)
    for i in range(len(g)):
        nb = [g[j] for j in range(i - 3, i + 4) if j != i and 0 <= j < len(g) and np.isfinite(g[j])]
        if len(nb) >= 3 and np.isfinite(g[i]):
            out[i] = g[i] - float(np.median(nb))
    return out


def plan(sig, sr, melody=None, order=None, jump=1.5, upper_under=1.5, keep_ending=2, lines_from=None):
    """Measure and decide. Returns (rows, findings, gains) where gains = {track: [(t0, t1, dB)]} with the group's
    line evening under the key "__group__"."""
    n = min(len(v) for v in sig.values())
    grp = sum(v[:n] for v in sig.values())
    src = lines_from if lines_from in sig else melody
    split = lines(sig[src][:n], sr, gap_s=0.3) if src in sig else lines(grp, sr)
    rows = [dict(t0=t0, t1=t1, group=loudness(grp, sr, t0, t1),
                 parts={k: loudness(v[:n], sr, t0, t1) for k, v in sig.items()}) for t0, t1 in split]
    findings, gains = [], {}
    upper = order[order.index(melody) + 1:] if melody and order and melody in order else []
    for r in rows:
        r["gain"] = {}
        ld = r["parts"].get(melody, -np.inf)
        if not np.isfinite(ld) or ld < -50:
            continue
        for u in upper:
            v = r["parts"].get(u, -np.inf)
            if np.isfinite(v) and v > -50 and v > ld - upper_under:
                over = v - (ld - upper_under)
                r["gain"][u] = -over
                findings.append(dict(
                    kind="upper-over-melody", severity="medium" if over >= 3 else "low", track=u,
                    where=f"{_mmss(r['t0'])}-{_mmss(r['t1'])}", t0=r["t0"], t1=r["t1"], change_db=round(-over, 1),
                    problem=f"{u} (above {melody}) sits {v - ld:+.1f} dB against it here ({v:.1f} vs {ld:.1f} LUFS); "
                            f"upper parts sit {upper_under:g} dB under the melody",
                    fix=f"lower {u} by {over:.1f} dB on this line; the melody and the parts below it are not touched"))
    for u in upper:
        gains[u] = [(r["t0"], r["t1"], r["gain"].get(u, 0.0)) for r in rows]
    # the stack per line after the upper fixes (volume automation is after the devices: exact)
    after = []
    for r in rows:
        tot = sum(10 ** (v / 10) * 10 ** (r["gain"].get(k, 0.0) / 10) for k, v in r["parts"].items() if np.isfinite(v))
        after.append(10 * np.log10(tot) if tot > 0 else -np.inf)
    after = np.array(after)
    d = _jumps(after)
    ggain = []
    for i, r in enumerate(rows):
        r["group_after"] = float(after[i])
        r["vs_neighbours"] = None if not np.isfinite(d[i]) else round(float(d[i]), 2)
        g = 0.0
        if np.isfinite(d[i]) and abs(d[i]) >= jump:
            ending = i >= len(rows) - keep_ending
            if not (ending and d[i] < 0):
                g = float(-d[i])
            findings.append(dict(
                kind="vocal-line-jump", severity="medium" if abs(d[i]) >= jump + 1.5 else "low",
                where=f"{_mmss(r['t0'])}-{_mmss(r['t1'])}", t0=r["t0"], t1=r["t1"], change_db=round(g, 1),
                problem=f"the vocals on this line are {abs(d[i]):.1f} dB {'quieter' if d[i] < 0 else 'louder'} than "
                        f"the lines around it" + (" (the song's ending: left, it dies away on purpose)" if g == 0 else ""),
                fix=("left as it is" if g == 0 else
                     f"{'raise' if g > 0 else 'lower'} the vocal group by {abs(g):.1f} dB over this line")))
        ggain.append((r["t0"], r["t1"], g))
    gains["__group__"] = ggain
    for i, f in enumerate(findings, 1):
        f.update(id=f"vocallevel-{i}", tool="vocallevel", applies="set")
        f.setdefault("track", "vocals")
    return rows, findings, gains


def _gain_at(segs, t, ramp=0.15):
    """dB at time t (s) from per-line gains: held over each line, ramped across the gaps, 0 outside."""
    if not segs:
        return 0.0
    if t < segs[0][0]:
        return segs[0][2] * max(0.0, 1 - (segs[0][0] - t) / ramp)
    for (a0, a1, ga), (b0, b1, gb) in zip(segs, segs[1:]):
        if a0 <= t <= a1:
            return ga
        if a1 < t < b0:
            return ga + (gb - ga) * (t - a1) / (b0 - a1)
    s0, s1, gl = segs[-1]
    if t <= s1:
        return gl
    return gl * max(0.0, 1 - (t - s1) / ramp)


def write_gains(x, name, segs, ramp=0.15):
    """Multiply the track's volume (fader or automation) by the per-line gains: new automation points at every line
    edge and every existing point, so the existing curve is kept and only offset."""
    segs = [s for s in sorted(segs)]
    if not any(abs(g) > 1e-3 for _, _, g in segs):
        return x, 0
    m = _track(x, name)
    if m is None:
        raise SystemExit(f"no track {name}")
    t = m.group(0)
    fader, tid, env = _volume(t)
    bps = _tempo(x) / 60
    ex = _points(env) if env else []

    def existing(b):
        if not ex:
            return fader
        if b <= ex[0][0]:
            return ex[0][1]
        if b >= ex[-1][0]:
            return ex[-1][1]
        bs = [p[0] for p in ex]
        return float(np.interp(b, bs, [p[1] for p in ex]))

    times = {b for b, _ in ex if b >= 0}
    for t0, t1, _ in segs:
        times.update([max(0.0, t0 - ramp) * bps, t0 * bps, t1 * bps, (t1 + ramp) * bps])
    times = sorted(times)
    val = lambda b: min(VOL_MAX, existing(b) * 10 ** (_gain_at(segs, b / bps, ramp) / 20))
    evs = '<FloatEvent Id="0" Time="-63072000" Value="%r" />' % val(0.0)
    for i, b in enumerate(times):
        evs += '<FloatEvent Id="%d" Time="%r" Value="%r" />' % (i + 1, float(b), float(val(b)))
    if env:
        eid = re.match(r'<AutomationEnvelope Id="(\d+)"', env.group(0)).group(1)
    else:                                   # a new envelope: an Id no sibling has
        ids = [int(i) for i in re.findall(r'<AutomationEnvelope Id="(\d+)"', t)]
        eid = str(max(ids) + 1 if ids else 0)
    newenv = ('<AutomationEnvelope Id="%s"><EnvelopeTarget><PointeeId Value="%s" /></EnvelopeTarget><Automation><Events>'
              '%s</Events><AutomationTransformViewState><IsTransformPending Value="false" /><TimeAndValueTransforms />'
              '</AutomationTransformViewState></Automation></AutomationEnvelope>') % (eid, tid, evs)
    if env:
        t = t[:env.start()] + newenv + t[env.end():]
    else:
        e = re.search(r'<AutomationEnvelopes>\s*<Envelopes>', t)
        if e:
            t = t[:e.end()] + newenv + t[e.end():]
        else:
            e = re.search(r'<AutomationEnvelopes>\s*<Envelopes />', t)
            t = t[:e.start()] + '<AutomationEnvelopes><Envelopes>' + newenv + '</Envelopes>' + t[e.end():]
    return x[:m.start()] + t + x[m.end():], sum(1 for _, _, g in segs if abs(g) > 1e-3)


def group_of(x, name):
    m = _track(x, name)
    if m is None:
        return None
    gid = re.search(r'<TrackGroupId Value="(-?\d+)"', m.group(0)).group(1)
    g = re.search(r'<GroupTrack Id="%s"[^>]*>.*?<EffectiveName Value="([^"]*)" />' % gid, x, re.S)
    return g.group(1) if g else None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix vocallevel", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--renders", help="`hypnomix render` output: fader and volume automation are applied")
    src.add_argument("--heard", help="files already as heard (solo exports): used as they are")
    ap.add_argument("--tracks", nargs="*")
    ap.add_argument("--melody", "--lead", dest="melody", help="the part the upper parts sit under (the lead as heard)")
    ap.add_argument("--order", help="vocal tracks low to high, comma-separated, or scan's order.json (else measured)")
    ap.add_argument("--lines-from", help="the track whose phrases are the lyric lines (default: the track called "
                                         "Lead…, else the melody)")
    ap.add_argument("--jump", type=float, default=1.5)
    ap.add_argument("--upper-under", type=float, default=1.5)
    ap.add_argument("--keep-ending", type=int, default=2)
    ap.add_argument("--json")
    ap.add_argument("--apply", help="write the fixes to this NEW set")
    ap.add_argument("--group", help="the vocal group track for line evening (default: the melody's group)")
    a = ap.parse_args(argv)
    folder = Path(a.renders or a.heard)
    tracks = a.tracks or sorted(p.stem for p in folder.glob("*.wav"))
    tracks = [t for t in tracks if (folder / f"{t}.wav").exists()]
    if not tracks:
        sys.exit("no vocal files found")
    melody = a.melody or next((t for t in tracks if t.lower().startswith("lead")), None)
    x = gzip.open(a.als).read().decode()
    sig, sr = {}, None
    for t in tracks:
        y, sr = _load(folder / f"{t}.wav")
        if a.renders:
            c = volume_curve(x, t, len(y), sr)
            if c is not None:
                y = y * c
        sig[t] = y
    order = None
    if a.order and Path(a.order).exists():
        for f in json.loads(Path(a.order).read_text()).get("findings", []):
            if f.get("kind") == "vocal-stack":
                order = [t.strip() for t in f["track"].split(",")]
    elif a.order:
        order = [t.strip() for t in a.order.split(",")]
    if not order:
        pitch = {t: median_pitch(v, sr) for t, v in sig.items()}
        order = [t for t, _ in sorted(((t, p) for t, p in pitch.items() if np.isfinite(p)), key=lambda q: q[1])]
    order = [t for t in order if t in sig]
    lf = a.lines_from or next((t for t in tracks if t.lower().startswith("lead")), None)
    rows, findings, gains = plan(sig, sr, melody, order, a.jump, a.upper_under, a.keep_ending, lf)
    how = "as heard (solo exports)" if a.heard else "renders x fader x volume automation (compressors not modelled)"
    g = np.array([r["group"] for r in rows if np.isfinite(r["group"])])
    print(f"{Path(a.als).name}: {len(tracks)} vocal track(s), {len(rows)} lines, {how}")
    print(f"  pitch order, low to high: {', '.join(order)}; melody: {melody or '?'}")
    if len(g):
        print(f"  vocal level per line: median {np.median(g):.1f} LUFS, spread (10-90%) {np.percentile(g, 10):.1f} "
              f"to {np.percentile(g, 90):.1f}")
    for f in findings:
        print(f"  {f['id']:<14} {f['kind']:<17} {f['where']:<17} {f['problem']}")
        print(f"  {'':<14} → {f['fix']}")
    if not findings:
        print("  even: no line jumps, no upper part over the melody")
    if a.json:
        Path(a.json).write_text(json.dumps(dict(tool="vocallevel", set=str(a.als), measured=how, order=order,
                                                melody=melody, lines=rows, findings=findings, gains=gains),
                                           default=float, indent=1))
    if a.apply:
        if Path(a.apply).resolve() == Path(a.als).resolve():
            sys.exit("refusing to overwrite the source set: give a new file name")
        grp_name = a.group or group_of(x, melody)
        done = []
        for t, segs in gains.items():
            name = grp_name if t == "__group__" else t
            if not name:
                continue
            x, k = write_gains(x, name, segs)
            if k:
                done.append(f"{name}: {k} line(s)")
        with gzip.open(a.apply, "wb") as f:
            f.write(x.encode())
        print(f"wrote {a.apply}: " + ("; ".join(done) if done else "nothing to change"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
