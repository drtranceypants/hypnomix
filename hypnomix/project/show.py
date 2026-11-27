"""Look inside a song project (REAPER .rpp, HypnoMix DAW .ardour or its session folder, Live .als) and render its tracks,
without opening the DAW.

  hypnomix project SONG.rpp                    tracks (folders, fader, pan, mute), items, plug-ins, automation
  hypnomix project SONG.rpp --items            also every item: position, length, take, file, volume, fades
  hypnomix project SONG.rpp --render [DIR]     every heard audio track to a full-length WAV from 0 s
                    [--tracks NAME ...] [--sr 44100]

Renders include item and take volume, fades, loops, sections and playrate (pitch kept when the take keeps it);
for HypnoMix DAW also region gain envelopes, stored fade curves and layering (an upper opaque region covers the ones
under it); not faders, plug-ins or automation. Output is 32-bit float, so nothing clips.
"""
import argparse
import sys

import numpy as np
import soundfile as sf

from hypnomix import project as PJ
from hypnomix.core.paths import out_at


def main():
    ap = argparse.ArgumentParser(prog="hypnomix project", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--items", action="store_true")
    ap.add_argument("--render", nargs="?", const="", metavar="DIR")
    ap.add_argument("--tracks", nargs="*")
    ap.add_argument("--sr", type=int, default=44100)
    a = ap.parse_args()
    p = PJ.load(a.project)
    print(f"{p.path.name}: {p.daw}, {p.tempo:g} BPM {p.meter_text}, {len(p.tracks)} tracks, {p.end():.1f} s")
    for w in getattr(p, "warnings", []):
        print("  !", w)
    for t in p.tracks:
        depth, par = 0, t.parent
        while par is not None:
            depth, par = depth + 1, par.parent
        flags = [f for f, on in (("MUTED", t.muted), ("solo", t.solo), ("polarity", t.polarity)) if on]
        print(f"{'  ' * depth}{t.name:<{32 - 2 * depth}} {t.kind:<6} {t.volume_db:+6.1f} dB pan {t.pan:+.2f} "
              f"{len(t.clips):3d} items {' '.join(flags)}")
        for d in t.devices:
            print(f"{'  ' * depth}    fx: {d.name} [{d.kind}]{'' if d.on else ' (off)'}{' preset ' + d.preset if d.preset else ''}")
        for lab, pts in t.envelopes.items():
            print(f"{'  ' * depth}    automation: {lab} ({len(pts)} points)")
        if a.items:
            for c in t.clips:
                tk = c.take
                print(f"{'  ' * depth}    {c.start:8.2f}-{c.end:8.2f} s  {c.name[:28]:<28} take {c.active + 1}/{len(c.takes)} "
                      f"{(tk.path.name if tk and tk.path else c.kind)}  {20 * np.log10(abs(c.level) + 1e-12):+.1f} dB"
                      f"  fades {c.fade_in * 1000:.0f}/{c.fade_out * 1000:.0f} ms{'  MUTED' if c.muted else ''}")
    missing = p.missing()
    if missing:
        print(f"\n{len(missing)} missing file(s):")
        for t, c, path in missing[:20]:
            print(f"  {t.name}: {path}")
    takes = p.missing_takes()
    if takes:
        print(f"\n{len(takes)} missing file(s) only take lanes use (not heard):")
        for t, lane, c, path in takes[:20]:
            print(f"  {t.name}, {lane.name}: {path}")
    if a.render is None:
        return
    od = out_at(a.render or None, "render", p.path.stem)
    want = {x.lower() for x in a.tracks} if a.tracks else None
    warn, L = [], p.end()
    for t in p.audio_tracks():
        if want and t.name.lower() not in want:
            continue
        y = p.render(t, a.sr, L, warn)
        if not np.any(y):
            continue
        sf.write(str(od / f"{t.safe_name}.wav"), y.astype(np.float32), a.sr, subtype="FLOAT")
        print(f"rendered {t.name:<30} peak {20 * np.log10(np.abs(y).max() + 1e-9):6.1f} dBFS")
    for w in sorted(set(warn)):
        print("  !", w, file=sys.stderr)
    print(f"→ {od}")


if __name__ == "__main__":
    main()
