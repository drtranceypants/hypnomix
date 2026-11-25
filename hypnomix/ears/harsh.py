#!/usr/bin/env python3
"""Harshness report: the moments where the 2-6 kHz range builds up against the bands around it, with timestamps.

It measures the spectrum every ~12 ms (smoothed over 0.3 s). For each 2/3-octave band centred between --range it
compares the band with the bands an octave below and above (the local slope of the spectrum). That difference is
judged against the song's own usual value, so a song that is simply bright is not called harsh everywhere (that is
a tone choice: EQ, or `hypnomix tonal`). Only loud moments count (the mix within 15 dB of its loud part, the band
above its own median). A moment counts when a band sits more than --thresh dB over its usual place for at least
--min seconds. Lower --thresh finds more (3-4 dB: anything that stands out; 6: the default; 9+: only the worst).

Nothing is changed. To turn down only those moments when mastering: `hypnomix master MIX --harsh` (same options:
--harsh-range, --harsh-thresh, plus --harsh-depth and --harsh-max), ideally through `master --plan` first.

Usage:
    hypnomix harsh FILE.wav [--range 2000:6000] [--thresh 6] [--min 0.25] [--top 20] [--json OUT.json] [--out DIR]
"""
import argparse, json, sys
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.core.paths import out_at
from hypnomix.engineer import stages


def mmss(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def analyse(path, lo=2000.0, hi=6000.0, thresh=6.0, min_s=0.25):
    y, sr = dsp.load(path)
    over, info = stages.harsh_detect(dsp.stereo(y), sr, lo, hi, thresh, min_s)
    ev = stages.harsh_events(over, info)
    total = float((over.max(axis=1) > 0).mean() * 100) if over.size else 0.0
    findings = [dict(id=f"harsh-{i}", tool="harsh", kind=f"harsh-{e['freq_hz']}", severity="medium" if e["peak_db"] > 4 else "low",
                     track=Path(path).name, where=f"{mmss(e['start_s'])}-{mmss(e['end_s'])}",
                     problem=f"{e['freq_hz'] / 1000:.1f} kHz builds up {e['above_usual_db']:.1f} dB over its usual place against "
                             f"the bands around it, for {e['length_s']:.2f} s",
                     fix="listen there: if it bites, `master --harsh` turns down only these moments (or a dynamic EQ "
                         f"at {e['freq_hz']} Hz on the source track)", applies="manual", **e)
                for i, e in enumerate(sorted(ev, key=lambda e: e["start_s"]), 1)]
    return dict(file=str(path), range_hz=[lo, hi], thresh_db=thresh, pct_of_song=round(total, 2), findings=findings)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix harsh", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--range", default="2000:6000", help="lo:hi Hz")
    ap.add_argument("--thresh", type=float, default=6.0, help="dB over the song's usual balance")
    ap.add_argument("--min", type=float, default=0.25, dest="min_s", help="shortest moment that counts, s")
    ap.add_argument("--top", type=int, default=20, help="list this many (strongest first)")
    ap.add_argument("--json")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    lo, hi = (float(x) for x in a.range.split(":"))
    r = analyse(a.file, lo, hi, a.thresh, a.min_s)
    fs = sorted(r["findings"], key=lambda f: -f["peak_db"])[:a.top]
    lines = [f"| {f['where']} | {f['freq_hz'] / 1000:.1f} kHz | +{f['above_usual_db']:.1f} dB | {f['length_s']:.2f} s |"
             for f in sorted(fs, key=lambda f: f["start_s"])]
    text = (f"# Harshness: {Path(a.file).name}\n\n{lo / 1000:g}-{hi / 1000:g} kHz, more than {a.thresh:g} dB over the "
            f"song's usual balance for at least {a.min_s:g} s. {len(r['findings'])} moment(s), "
            f"{r['pct_of_song']:.1f}% of the song.\n\n"
            + ("| when | band | over its usual place | length |\n|---|---|---|---|\n" + "\n".join(lines) if lines else
               "No sustained build-ups (measured; still listen on bright earbuds at a high level).")
            + "\n\nMeasured, not heard: listen at each time before turning anything down.\n")
    od = out_at(a.out, "harsh")
    (od / f"{Path(a.file).stem} (harsh).md").write_text(text)
    if a.json:
        Path(a.json).write_text(json.dumps(r, indent=1))
    print(text)
    print(f"report: {od / (Path(a.file).stem + ' (harsh).md')}", file=sys.stderr)


if __name__ == "__main__":
    main()
