#!/usr/bin/env python3
"""Vocal level consistency: does the vocal stay at an even level from line to line, and do the upper parts sit under
the main melody? Run it in the first scan and again before every final export (edits made since the scan, such as
restored comps, re-tuned notes or fader moves, can change it).

Two checks, line by line (a line = a phrase of the whole vocal stack, any part singing, split at gaps of 0.3 s or
more, long phrases cut at about 9 s; --lines-from takes the lines from one track instead):
  upper   a part pitched above the melody is louder than the melody minus --upper-under dB on a line (default 1.5:
          upper harmonies sit slightly under the melody). Parts below the melody are never flagged. Lines where the
          melody is silent or more than 6 dB under its usual level are skipped: the harmonies carry those lines.
  jump    the whole stack's loudness on a line (every part summed, as heard) differs from the lines around it (median
          of up to three either side) by --jump dB or more: a line that drops away or jumps out (judged after the
          upper fixes).

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
               over (at most 4 dB), then the stack's lines evened out (at most 3 dB either way) on the vocal group's
               volume (--group; default the melody's group track). A group that also holds non-vocal tracks (strings
               in a "Vocals" group) is never automated: those moves go on each vocal track instead. Every change is
               a smooth S-curve about 1.2 s long (raised cosine, a point every 0.1 s), centred in the gap between
               lines, so close lines blend instead of stepping; the steepest move is reported in dB/s. Existing
               automation is kept and offset. In a scan these are findings to make by hand: `hypnomix fix` does not
               write them (it lists an approved one under "Not applied"); --apply writes all of them at once.
  --keep-ending  the song's last N lines are never raised (an ending that dies away is usually on purpose).

Track names default to every file in the folder. The pitch order (which parts are above the melody) comes from
--order (a list low to high, or scan's order.json), else it is measured from the audio (median pitch: rough).
"""
import argparse
import gzip
from hypnomix.core.gz import read_gz
import json
import re
import sys
from pathlib import Path

import numpy as np

HOP_S = 0.05
VOL_MAX = 1.99526            # Live's +6 dB
RAMP_S = 1.2                 # every automated change is an S-curve this long
STEP_S = 0.1                 # automation point spacing
MAX_LINE_DB = 3.0            # line evening never moves a line more than this either way
MAX_TRIM_DB = 4.0            # an upper part is never lowered more than this on a line
MELODY_QUIET_DB = 6.0        # melody this far under its median: harmonies carry the line, upper rule skipped


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


def _stack(sig, n, gains=None):
    """Every part summed (with per-part dB gains): the stack as heard."""
    gains = gains or {}
    return sum(v[:n] * np.float32(10 ** (gains.get(k, 0.0) / 20)) for k, v in sig.items())


def plan(sig, sr, melody=None, order=None, jump=1.5, upper_under=1.5, keep_ending=2, lines_from=None,
         max_line=MAX_LINE_DB, max_trim=MAX_TRIM_DB, melody_quiet=MELODY_QUIET_DB):
    """Measure and decide. Returns (rows, findings, gains) where gains = {track: [(t0, t1, dB)]} with the group's
    line evening under the key "__group__". Lines come from the whole stack (or --lines-from), and the stack's
    level on each line is every part summed, so a line where the melody rests and the harmonies sing reads at the
    harmonies' level, not as a silent melody."""
    n = min(len(v) for v in sig.values())
    grp = _stack(sig, n)
    split = lines(sig[lines_from][:n], sr, gap_s=0.3) if lines_from in sig else lines(grp, sr, gap_s=0.3)
    rows = [dict(t0=t0, t1=t1, group=loudness(grp, sr, t0, t1),
                 parts={k: loudness(v[:n], sr, t0, t1) for k, v in sig.items()}) for t0, t1 in split]
    findings, gains = [], {}
    upper = order[order.index(melody) + 1:] if melody and order and melody in order else []
    mel = [r["parts"].get(melody, -np.inf) for r in rows]
    mel = [v for v in mel if np.isfinite(v) and v > -50]
    mel_med = float(np.median(mel)) if mel else -np.inf
    for r in rows:
        r["gain"] = {}
        ld = r["parts"].get(melody, -np.inf)
        r["melody_resting"] = bool(upper) and (not np.isfinite(ld) or ld < -50 or ld < mel_med - melody_quiet)
        if r["melody_resting"]:
            continue
        for u in upper:
            v = r["parts"].get(u, -np.inf)
            if np.isfinite(v) and v > -50 and v > ld - upper_under:
                over = v - (ld - upper_under)
                trim = min(over, max_trim)
                r["gain"][u] = -trim
                findings.append(dict(
                    kind="upper-over-melody", severity="medium" if over >= 3 else "low", track=u,
                    where=f"{_mmss(r['t0'])}-{_mmss(r['t1'])}", t0=r["t0"], t1=r["t1"], change_db=round(-trim, 1),
                    problem=f"{u} (above {melody}) sits {v - ld:+.1f} dB against it here ({v:.1f} vs {ld:.1f} LUFS); "
                            f"upper parts sit {upper_under:g} dB under the melody",
                    fix=f"lower {u} by {trim:.1f} dB on this line" +
                        (f" (capped at {max_trim:g} dB: {over - trim:.1f} dB more by ear if it still sticks out)"
                         if over > trim else "") + "; the melody and the parts below it are not touched"))
    for u in upper:
        gains[u] = [(r["t0"], r["t1"], r["gain"].get(u, 0.0)) for r in rows]
    # the whole stack per line after the upper fixes (volume automation is after the devices: exact)
    after = []
    for r in rows:
        if r["gain"]:
            after.append(loudness(_stack(sig, n, r["gain"]), sr, r["t0"], r["t1"]))
        else:
            after.append(r["group"])
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
                g = float(np.clip(-d[i], -max_line, max_line))
            capped = g != 0 and abs(d[i]) > max_line
            findings.append(dict(
                kind="vocal-line-jump", severity="medium" if abs(d[i]) >= jump + 1.5 else "low",
                where=f"{_mmss(r['t0'])}-{_mmss(r['t1'])}", t0=r["t0"], t1=r["t1"], change_db=round(g, 1),
                problem=f"the vocals on this line are {abs(d[i]):.1f} dB {'quieter' if d[i] < 0 else 'louder'} than "
                        f"the lines around it" + (" (the song's ending: left, it dies away on purpose)" if g == 0 else ""),
                fix=("left as it is" if g == 0 else
                     f"{'raise' if g > 0 else 'lower'} the vocals by {abs(g):.1f} dB over this line" +
                     (f" (capped at {max_line:g} dB: a gap this big is usually an arrangement choice or a comp "
                      f"problem, check it by ear)" if capped else ""))))
        ggain.append((r["t0"], r["t1"], g))
    gains["__group__"] = ggain
    for i, f in enumerate(findings, 1):
        f.update(id=f"vocallevel-{i}", tool="vocallevel", applies="manual")   # `fix` has no step for these: --apply here writes them all
        f.setdefault("track", "vocals")
    return rows, findings, gains


def _steps(segs, ramp=RAMP_S):
    """Per-line gains as a step: each gain held over its line, the change placed at the middle of the gap to the
    next line; before the first and after the last line it returns to 0 half a ramp out."""
    segs = sorted(segs)
    out = []
    for i, (t0, t1, g) in enumerate(segs):
        a = (segs[i - 1][1] + t0) / 2 if i else t0 - ramp / 2
        b = (t1 + segs[i + 1][0]) / 2 if i + 1 < len(segs) else t1 + ramp / 2
        out.append((a, b, g))
    return out


def smooth_db(segs, ts, ramp=RAMP_S):
    """dB at times ts (s): the step of per-line gains smoothed with a Hann window `ramp` s long, so every change
    is a raised-cosine S-curve and close edges blend instead of jumping. 0 well away from every line."""
    ts = np.asarray(ts, dtype=np.float64)
    if not segs or not len(ts):
        return np.zeros_like(ts)
    st = _steps(segs, ramp)
    dt = 0.01
    lo = min(st[0][0], ts.min()) - ramp
    hi = max(st[-1][1], ts.max()) + ramp
    grid = lo + dt * np.arange(int(np.ceil((hi - lo) / dt)) + 1)
    step = np.zeros_like(grid)
    for a, b, g in st:
        step[(grid >= a) & (grid < b)] = g
    w = np.hanning(int(round(ramp / dt)) + 2)[1:-1]
    sm = np.convolve(step, w / w.sum(), mode="same")
    return np.interp(ts, grid, sm)


def steepest(segs, ramp=RAMP_S):
    """The steepest change of the smoothed curve, in dB per second."""
    segs = [s for s in segs if s[1] > s[0]]
    if not any(abs(g) > 1e-3 for _, _, g in segs):
        return 0.0
    ts = np.arange(max(0.0, min(s[0] for s in segs) - 2 * ramp), max(s[1] for s in segs) + 2 * ramp, 0.01)
    return float(np.max(np.abs(np.diff(smooth_db(segs, ts, ramp)))) / 0.01)


def write_gains(x, name, segs, ramp=RAMP_S, step=STEP_S):
    """Multiply the track's volume (fader or automation) by the per-line gains as smooth S-curves (smooth_db):
    a point every `step` s wherever the curve moves, plus every existing point, so the existing curve is kept
    and only offset. Never a step."""
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

    secs = {round(b / bps, 4) for b, _ in ex if b >= 0}
    for a, b, _ in _steps(segs, ramp):        # every change sits on a step edge: sample its whole S-curve
        for e in (a, b):
            secs.update(round(float(q), 4) for q in np.arange(e - ramp / 2 - step, e + ramp / 2 + step + 1e-9, step))
    secs = sorted(q for q in secs if q >= 0)
    if not secs or secs[0] > 0:
        secs = [0.0] + secs
    db = smooth_db(segs, secs, ramp)
    vals = [min(VOL_MAX, existing(q * bps) * 10 ** (d / 20)) for q, d in zip(secs, db)]
    evs = '<FloatEvent Id="0" Time="-63072000" Value="%r" />' % float(vals[0])
    for i, (q, v) in enumerate(zip(secs, vals)):
        evs += '<FloatEvent Id="%d" Time="%r" Value="%r" />' % (i + 1, float(q * bps), float(v))
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


def _tracks(x):
    """(kind, Id, name, parent group Id) of every track in the set."""
    out = []
    for m in re.finditer(r'<(AudioTrack|MidiTrack|GroupTrack) Id="(\d+)"[^>]*>.*?</\1>', x, re.S):
        nm = re.search(r'<EffectiveName Value="([^"]*)" />', m.group(0))
        pg = re.search(r'<TrackGroupId Value="(-?\d+)"', m.group(0))
        out.append((m.group(1), m.group(2), nm.group(1) if nm else "", pg.group(1) if pg else "-1"))
    return out


def group_members(x, name):
    """Names of the audio/MIDI tracks inside group `name`, nested groups included; None when it's no group."""
    ts = _tracks(x)
    gid = next((i for k, i, n, _ in ts if k == "GroupTrack" and n == name), None)
    if gid is None:
        return None
    ids, out, grew = {gid}, [], True
    while grew:
        grew = False
        for k, i, n, p in ts:
            if p in ids and i not in ids and k == "GroupTrack":
                ids.add(i)
                grew = True
    return [n for k, i, n, p in ts if k != "GroupTrack" and p in ids]


def non_vocal_members(x, group, vocals):
    """Tracks in `group` that are not among the vocal tracks: automating that group would ride them too."""
    m = group_members(x, group)
    return [] if m is None else [t for t in m if t not in set(vocals)]


def apply_gains(x, gains, group, vocals, log=print):
    """Write the plan's gains into the set text. The line evening goes on `group` only when every track in it is
    a vocal; otherwise (or with no group) it goes on each vocal track, added to that track's own trims. Returns
    (x, done lines, steepest dB/s)."""
    gains = {k: list(v) for k, v in gains.items()}
    gg = gains.pop("__group__", [])
    if any(abs(g) > 1e-3 for _, _, g in gg):
        other = non_vocal_members(x, group, vocals) if group else None
        if not group or other:
            if other:
                log(f"  {group} also holds {', '.join(other)}: not automating the group (it would ride them with "
                    f"every vocal line); the line evening goes on the vocal tracks instead")
            for v in vocals:
                own = {(a, b): g for a, b, g in gains.get(v, [])}
                gains[v] = [(a, b, own.get((a, b), 0.0) + g) for a, b, g in gg]
        else:
            gains[group] = gg
    done, worst = [], 0.0
    for name, segs in gains.items():
        x, k = write_gains(x, name, segs)
        if k:
            sl = steepest(segs)
            worst = max(worst, sl)
            done.append(f"{name}: {k} line(s), steepest {sl:.1f} dB/s")
    return x, done, worst


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
    from hypnomix.session import liveversion as LV; LV.add_force_flag(ap)
    ap.add_argument("als")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--renders", help="`hypnomix render` output: fader and volume automation are applied")
    src.add_argument("--heard", help="files already as heard (solo exports): used as they are")
    ap.add_argument("--tracks", nargs="*")
    ap.add_argument("--melody", "--lead", dest="melody", help="the part the upper parts sit under (the lead as heard)")
    ap.add_argument("--order", help="vocal tracks low to high, comma-separated, or scan's order.json (else measured)")
    ap.add_argument("--lines-from", help="take the lines from this track's phrases (default: the whole vocal "
                                         "stack, so lines where only the harmonies sing count too)")
    from hypnomix.core import args as A
    ap.add_argument("--jump", type=A.number(above=0, hi=24), default=1.5)
    ap.add_argument("--upper-under", type=A.number(0, 24), default=1.5)
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
    for opt, val in (("--melody", a.melody), ("--lines-from", a.lines_from)):
        if val and val not in tracks:             # a misspelt name used to be accepted and measured as silence
            sys.exit(f"{opt}: no track called {val!r} (the tracks are: {', '.join(tracks)})")
    melody = a.melody or next((t for t in tracks if t.lower().startswith("lead")), None)
    x = read_gz(a.als).decode()
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
        for f in json.loads(Path(a.order).read_text(encoding="utf-8", errors="replace")).get("findings", []):
            if f.get("kind") == "vocal-stack":
                order = [t.strip() for t in f["track"].split(",")]
    elif a.order:
        order = [t.strip() for t in a.order.split(",")]
    if not order:
        pitch = {t: median_pitch(v, sr) for t, v in sig.items()}
        order = [t for t, _ in sorted(((t, p) for t, p in pitch.items() if np.isfinite(p)), key=lambda q: q[1])]
    order = [t for t in order if t in sig]
    rows, findings, gains = plan(sig, sr, melody, order, a.jump, a.upper_under, a.keep_ending, a.lines_from)
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
                                           default=float, indent=1), encoding="utf-8")
    if a.apply:
        if Path(a.apply).resolve() == Path(a.als).resolve():
            sys.exit("refusing to overwrite the source set: give a new file name")
        grp_name = a.group or group_of(x, melody)
        x, done, worst = apply_gains(x, gains, grp_name, tracks)
        from hypnomix.session import liveversion as LV
        LV.guard_write_text(x)                # refuses a set saved by a Live newer than the newest tested
        with gzip.open(a.apply, "wb") as f:
            f.write(x.encode())
        print(f"wrote {a.apply}: " + ("; ".join(done) if done else "nothing to change"))
        if done:
            print(f"  smooth S-curves ({RAMP_S:g} s, a point every {STEP_S:g} s); steepest move {worst:.1f} dB/s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
