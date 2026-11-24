#!/usr/bin/env python3
"""Even out clips on one track that were recorded on different days, with different preamp gain or
a different mic position: same loudness, same tone, so the part sounds like one performance.

Two ways in:
  Files:  hypnomix clipmatch take1.wav take2.wav … [--ref take1.wav] [--tone 0.7] [--out DIR]
          → loudness- and tone-matched copies plus a table of what changed.
  Live:   hypnomix clipmatch --als SET.als --track "Lead Vox" [--ref 3] [--apply]
          → reads every audio clip on that track from the set, measures the part of the file each clip
            actually plays, and (with --apply) sets each clip's Clip Gain in the open Live set through
            AbletonOSC. Tone differences are reported as EQ Eight moves, and --render writes matched copies.

Loudness is measured only while the clip is sounding (silence between phrases doesn't count).
Tone: the average spectrum is compared with the reference after removing loudness; the difference is
smoothed to half-octaves and capped (±4 dB), which covers proximity effect and on/off-axis changes.
"""
from hypnomix.core.paths import out_at
import argparse, gzip, sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.core.paths import out as out_dir

SHOW_HZ = [(80, "80 Hz"), (250, "250 Hz"), (800, "800 Hz"), (2500, "2.5 kHz"), (6000, "6 kHz"), (12000, "12 kHz")]


def tone_curve(y, ref, sr, amount):
    h, (f, curve) = dsp.matching_fir(y, ref, sr, max_db=4.0, smooth_oct=0.5)
    if amount < 1:
        from scipy.signal import firwin2
        pts = np.unique(np.concatenate([[0], np.geomspace(20, sr / 2 * 0.999, 200), [sr / 2]]))
        h = firwin2(4097, pts, dsp.undb(np.interp(pts, f, curve * amount)), fs=sr)
    return h, f, curve * amount


def eq_suggestion(f, curve):
    """Turn a smooth correction curve into up to 3 EQ Eight bells/shelves."""
    out = []
    lo = float(np.interp(100, f, curve))
    hi = float(np.interp(10000, f, curve))
    if abs(lo) >= 1:
        out.append(f"low shelf 150 Hz {lo:+.1f} dB" + (" (closer mic: proximity effect)" if lo < 0 and hi < 1 else ""))
    for hz, q in ((400, 1.2), (2500, 1.0)):
        g = float(np.interp(hz, f, curve)) - lo * 0.3
        if abs(g) >= 1:
            out.append(f"bell {hz} Hz {g:+.1f} dB Q {q}")
    if abs(hi) >= 1:
        out.append(f"high shelf 8 kHz {hi:+.1f} dB" + (" (it was darker: further away or off-axis)" if hi > 0 else ""))
    return out or ["no tone change needed"]


def analyse(clips, sr, ref_idx, tone):
    """clips: [(label, y)]. Returns rows with gain and tone suggestions relative to the reference."""
    loud = [dsp.active_lufs(y, sr) if len(y) else -70.0 for _, y in clips]
    ok = [i for i, (_, y) in enumerate(clips) if loud[i] > -69 and len(y) > 0.3 * sr]
    if not ok:
        sys.exit("no clip has enough audio to measure")
    if ref_idx is None or ref_idx not in ok:
        ref_idx = sorted(ok, key=lambda i: loud[i])[len(ok) // 2]   # the median-loudness clip
    ref = clips[ref_idx][1]
    rows = []
    for i, (label, y) in enumerate(clips):
        if i not in ok:
            rows.append(dict(i=i, label=label, lufs=-70.0, gain=0.0, ref=False, fir=None, curve=(None, None),
                             eq=["silent or under 0.3 s: left alone"], floor=-120.0, skip=True))
            continue
        h, f, curve = tone_curve(y, ref, sr, tone) if i != ref_idx and tone > 0 else (None, None, None)
        after_tone = dsp.active_lufs(dsp.apply_fir(y, h), sr) if h is not None else loud[i]   # tone fix changes loudness too
        rows.append(dict(i=i, label=label, lufs=loud[i], gain=loud[ref_idx] - after_tone, ref=i == ref_idx,
                         fir=h, curve=(f, curve), eq=eq_suggestion(f, curve) if h is not None else ["reference"],
                         floor=dsp.noise_floor_db(y, sr)))
    return rows, ref_idx


def table(rows):
    md = ["| clip | loudness while sounding | gain change | tone | noise floor |", "|---|---|---|---|---|"]
    for r in rows:
        if r.get("skip"):
            md.append(f"| {r['label']} | – | – | {r['eq'][0]} | – |"); continue
        md.append(f"| {r['label']}{' (ref)' if r['ref'] else ''} | {r['lufs']:.1f} LUFS | {r['gain']:+.1f} dB | "
                  f"{'; '.join(r['eq'])} | {r['floor']:.0f} dBFS |")
    floors = [r["floor"] for r in rows if not r.get("skip")]
    if max(floors) - min(floors) > 8:
        md += ["", f"Noise floors differ by {max(floors) - min(floors):.0f} dB: after matching, the quiet-recorded clips bring "
               "their hiss up with them. Consider `hypnomix cleanup` on those clips first."]
    return md


# ---------------------------------------------------------------- Live set
def warp_map(clip):
    """beat-in-clip -> seconds-in-file, from the clip's warp markers."""
    ms = [(float(w.get("BeatTime")), float(w.get("SecTime"))) for w in clip.iter("WarpMarker")]
    if len(ms) >= 2:
        b, s = zip(*sorted(ms))
        return lambda beat: float(np.interp(beat, b, s, left=s[0] + (beat - b[0]) * (s[1] - s[0]) / max(1e-9, b[1] - b[0]),
                                            right=s[-1] + (beat - b[-1]) * (s[-1] - s[-2]) / max(1e-9, b[-1] - b[-2])))
    return None


def als_clips(als, track_name):
    root = ET.fromstring(gzip.open(als).read())
    tempo = float(root.find(".//Tempo/Manual").get("Value"))
    tracks = [t for t in root.find(".//Tracks") if t.tag == "AudioTrack"]
    pick = [t for t in tracks if t.find("./Name/EffectiveName").get("Value").lower() == track_name.lower()] or \
           [t for t in tracks if track_name.lower() in t.find("./Name/EffectiveName").get("Value").lower()]
    if len(pick) != 1:
        sys.exit(f"audio track {track_name!r} {'ambiguous' if pick else 'not found'}; audio tracks: "
                 f"{[t.find('./Name/EffectiveName').get('Value') for t in tracks]}")
    t = pick[0]
    out = []
    for c in t.iter("AudioClip"):
        fr = c.find(".//SampleRef/FileRef")
        p = fr.find("./Path").get("Value") if fr is not None and fr.find("./Path") is not None else ""
        rel = fr.find("./RelativePath").get("Value") if fr is not None and fr.find("./RelativePath") is not None else ""
        path = Path(p) if p and Path(p).exists() else (Path(als).parent / rel)
        start, end = float(c.find("./CurrentStart").get("Value")), float(c.find("./CurrentEnd").get("Value"))
        ls = float(c.find("./Loop/LoopStart").get("Value"))
        wm = warp_map(c)
        length_beats = end - start
        if wm:
            s0, s1 = wm(ls), wm(ls + length_beats)
        else:
            s0, s1 = ls, ls + length_beats * 60 / tempo
        vol = c.find("./SampleVolume")
        gain_lin = float(vol.get("Value")) if vol is not None else 1.0
        out.append(dict(name=c.find("./Name").get("Value") or path.stem, path=path, start=start, s0=s0, s1=s1, gain_lin=gain_lin))
    return sorted(out, key=lambda d: d["start"]), tempo, t.find("./Name/EffectiveName").get("Value")


def set_clip_gain_db(live, tid, idx, target_db):
    """Bisect Live's clip gain (0…1) until its display string reads target_db."""
    lo, hi = 0.0, 1.0
    for _ in range(18):
        mid = (lo + hi) / 2
        r = live.query("/live/track/set/arrangement_clip/gain", tid, idx, float(mid))
        v = live._parse_db(r[-1])
        if v < target_db:
            lo = mid
        else:
            hi = mid
    r = live.query("/live/track/set/arrangement_clip/gain", tid, idx, float(hi))
    return r[-1]


def main():
    ap = argparse.ArgumentParser(prog="hypnomix clipmatch", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--ref", help="reference clip: a file name (files mode) or clip number (Live mode, 1 = first)")
    ap.add_argument("--tone", type=float, default=0.7, help="how much of the tone difference to correct (0 = loudness only)")
    ap.add_argument("--als"); ap.add_argument("--track")
    ap.add_argument("--apply", action="store_true", help="Live mode: set the Clip Gains in the open set")
    ap.add_argument("--render", action="store_true", help="Live mode: also write matched copies of each clip")
    ap.add_argument("--out")
    a = ap.parse_args()
    od = out_at(a.out, "clipmatch")

    if a.als:
        if not a.track:
            sys.exit("--als needs --track")
        cl, tempo, tname = als_clips(a.als, a.track)
        if not cl:
            sys.exit(f"no audio clips on {tname}")
        sr = None
        clips = []
        for c in cl:
            y, s = dsp.load(c["path"], sr)
            sr = sr or s
            seg = y[max(0, int(c["s0"] * sr)): int(c["s1"] * sr)] * c["gain_lin"]
            clips.append((f"{len(clips) + 1}. {c['name']} @ bar {c['start'] / 4 + 1:.0f}", seg))
        ref = int(a.ref) - 1 if a.ref else None
        rows, ref = analyse(clips, sr, ref, a.tone)
        md = [f"# Clip match: {tname} ({len(rows)} clips)", "", *table(rows)]
        if a.apply:
            from hypnomix.live.osc import Live
            live = Live()
            if not live.ping():
                sys.exit("Live isn't answering. Run: hypnomix doctor")
            tid = live.tid(tname)
            starts = list(live.query("/live/track/get/arrangement_clips/start_time", tid)[1:])
            md += ["", "## Applied in Live"]
            for r, c in zip(rows, cl):
                if r.get("skip"):
                    continue
                hits = [i for i, s in enumerate(starts) if abs(s - c["start"]) < 1e-3]
                if not hits:
                    md.append(f"- {r['label']}: not found in the open set (save the set and re-run?)"); continue
                cur = 20 * np.log10(max(c["gain_lin"], 1e-9))
                shown = set_clip_gain_db(live, tid, hits[0], float(np.clip(cur + r["gain"], -70, 24)))
                md.append(f"- {r['label']}: clip gain {cur:+.1f} → {shown}")
            live.close()
        if a.render:
            for r, (label, y) in zip(rows, clips):
                z = y * dsp.undb(r["gain"])
                if r["fir"] is not None:
                    z = dsp.apply_fir(z, r["fir"])
                dsp.save(od / f"{label.replace('/', '-')} (matched).wav", z, sr, 24)
    else:
        if len(a.files) < 2:
            sys.exit("give two or more clips (or --als SET.als --track NAME)")
        sr = None
        clips = []
        for f in a.files:
            y, s = dsp.load(f, sr)
            sr = sr or s
            clips.append((Path(f).stem, y))
        ref = next((i for i, f in enumerate(a.files) if a.ref and Path(f).name == Path(a.ref).name), None)
        rows, ref = analyse(clips, sr, ref, a.tone)
        for r, (label, y) in zip(rows, clips):
            z = y * dsp.undb(r["gain"])
            if r["fir"] is not None:
                z = dsp.apply_fir(z, r["fir"])
            pk = dsp.sample_peak(z)
            if pk > -0.3:
                r["eq"].append(f"peaks at {pk:+.1f} dBFS after matching: lower the whole track instead of clipping")
                z *= dsp.undb(-0.3 - pk)
            dsp.save(od / f"{label} (matched).wav", z, sr, 24)
        md = [f"# Clip match ({len(rows)} clips, reference: {rows[ref]['label']})", "", *table(rows), "",
              f"Matched copies in `{od}`."]
    text = "\n".join(md) + "\n"
    (od / "CLIPMATCH.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
