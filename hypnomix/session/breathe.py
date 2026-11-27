#!/usr/bin/env python3
"""Let a song recorded to a rigid click breathe: small tempo changes between sections, after the fact.

  hypnomix breathe SET.als --mix "Song mix.wav" [--preview "Song (breathing).wav"]
  hypnomix breathe SET.als --sections "17-32:+1.5, 49-64:+1.5, 65-72:-1" --apply "SET (breathing).als"
  hypnomix breathe SESSION.ardour --sections "..." --grid-only (--engine [URL] | --apply "SESSION (breathing).ardour")

A band without a click pushes the choruses a little and relaxes in the verses. This writes that as tempo
automation: each section gets a tempo a little above or below the set's, with a short glide into it.

Where the sections come from, in this order:
  --sections   you say: "BARS:PERCENT, ..." (bars count from 1, the end bar is included; + is faster)
  locators     the set's own locators, when they are named (chorus, verse, bridge, intro, outro, drop, break)
  --mix        a bounce of the song: sections are found from it, and the louder a section is against the
               song's median, the more it is pushed (quieter ones are relaxed)

  --amount 1.0     scale every change (0.5 = half as much). Changes stay within -2% and +2.5%.
  --glide 2        beats over which the tempo slides into the next section (the last beats before it)
  --ritard 4       slow the last bar of the song by this many percent, as a band would land the ending

--preview (needs --mix) stretches the bounce along the new tempo curve, pitch unchanged, so you can hear
the idea without Live. It is the old mix bent in time: close to, not identical to, what Live will play.

--apply writes a NEW set. Tempo automation only moves audio that is WARPED: every unwarped clip would
stay at the old speed and drift out of time, so they are listed and nothing is written unless you add
--warp-clips (switch warp on for them: they play the same at the set's tempo, and follow it from then on;
drums in Beats mode, everything else in Complex Pro). Listen for warp artefacts on exposed vocals.
The song's length changes slightly: a video cut to the old audio will no longer line up.
Close the set in Live before --apply. `hypnomix check` runs on the result.

A HypnoMix Studio session (.ardour, or its folder; sections from --sections or --mix): the same plan becomes tempo points,
each glide a tempo ramp (the glide rounded to whole beats), written into the open session (--engine: one undo step)
or a new snapshot in the session's folder (--apply NEW.ardour). In HypnoMix Studio audio regions keep their time when the
tempo changes (audio that follows the tempo map is not built yet): the bar grid and MIDI breathe, the recorded audio
does not, so a session with audio needs --grid-only to write it.
"""
import argparse, re, sys
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix.session import beats as B

LO, HI = -2.0, 2.5
WORDS = {"chorus": 1.2, "hook": 1.2, "drop": 1.5, "refrain": 1.0, "solo": 0.8, "verse": 0.0, "pre": 0.5,
         "bridge": -0.8, "break": -1.0, "intro": -0.5, "outro": -0.8, "interlude": -0.6}


def from_text(text, bpb):
    out = []
    for part in text.split(","):
        m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*:\s*([+-]?\d+(?:\.\d+)?)\s*%?\s*", part)
        if not m:
            sys.exit(f"could not read {part.strip()!r}: write sections like \"17-32:+1.5, 49-64:-1\"")
        a, b, p = int(m[1]), int(m[2]), float(m[3])
        if b < a:
            sys.exit(f"{part.strip()!r}: the end bar is before the start bar")
        out.append(((a - 1) * bpb, b * bpb, p, f"bars {a}-{b}"))
    return sorted(out)


def from_locators(root, end):
    locs = sorted((float(l.find("./Time").get("Value")), (l.find("./Name").get("Value") or "")) for l in root.iter("Locator")
                  if l.find("./Time") is not None and l.find("./Name") is not None)
    out = []
    for (t0, name), (t1, _) in zip(locs, locs[1:] + [(end, "")]):
        hit = [v for w, v in WORDS.items() if w in name.lower()]
        if hit and t1 > t0:
            out.append((t0, t1, hit[0], name))
    return out


def from_mix(mix, tempo, bpb):
    from hypnomix.ears import sections
    r = sections.analyse(mix, bpm=tempo)
    secs = r["sections"]
    if len(secs) < 2:
        return []
    med = float(np.median([s["lufs"] for s in secs]))
    spb = 60.0 / tempo
    out = []
    for s in secs:
        b0 = round(s["start"] / spb / bpb) * bpb
        b1 = round(s["end"] / spb / bpb) * bpb
        p = round(float(np.clip(0.45 * (s["lufs"] - med), -1.0, 1.5)), 1)
        if b1 > b0:
            out.append((float(b0), float(b1), p, f"section {s['label']}{' (chorus-like)' if s.get('role') == 'chorus-like' else ''}, {s['lufs']:.1f} LUFS"))
    return out


def build_points(secs, tempo, end, glide, ritard, bpb):
    """Tempo points for [(beat0, beat1, percent, name)] over a song `end` beats long."""
    line = []                                   # (beat, percent) steps covering the whole song
    pos = 0.0
    for b0, b1, p, _ in secs:
        if b0 > pos:
            line.append((pos, 0.0))
        line.append((max(b0, pos), p))
        pos = max(pos, b1)
    if pos < end:
        line.append((pos, 0.0))
    merged = []
    for b, p in line:
        if merged and abs(merged[-1][1] - p) < 1e-9:
            continue
        merged.append((b, p))
    pts = [(0.0, tempo * (1 + merged[0][1] / 100))]
    for (b_prev, p_prev), (b, p) in zip(merged, merged[1:]):
        g = min(glide, (b - b_prev) / 2)
        pts.append((b - g, tempo * (1 + p_prev / 100)))
        pts.append((b, tempo * (1 + p / 100)))
    if ritard:
        last = pts[-1][1]
        pts.append((end - bpb, last))
        pts.append((end, last * (1 - ritard / 100)))
    return pts


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix breathe", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als"); ap.add_argument("--mix"); ap.add_argument("--sections")
    ap.add_argument("--amount", type=float, default=1.0); ap.add_argument("--glide", type=float, default=2.0)
    ap.add_argument("--ritard", type=float, default=0.0)
    ap.add_argument("--preview", metavar="OUT.wav"); ap.add_argument("--warp-clips", action="store_true")
    ap.add_argument("--replace-tempo", action="store_true"); ap.add_argument("--apply", metavar="NEW.als")
    ap.add_argument("--engine", nargs="?", const="", metavar="URL",
                    help="HypnoMix Studio: write the tempo map into the open HypnoMix engine (it must have this very "
                         "session open; one undo step; save in HypnoMix Studio to keep it)")
    ap.add_argument("--grid-only", action="store_true",
                    help="HypnoMix Studio: write the tempo map although the session's audio keeps its time (only the grid "
                         "and MIDI breathe)")
    from hypnomix.session import liveversion as LV; LV.add_force_flag(ap)
    a = ap.parse_args(argv)
    if a.preview and Path(a.preview).exists():           # before anything is read or rendered
        sys.exit(f"{Path(a.preview).name} already exists: choose a new name for --preview (nothing is ever overwritten)")
    from hypnomix.session import tempo_ardour as TA
    if TA.is_session(a.als):
        rc = TA.breathe(a, a.als)
        if rc:
            sys.exit(rc)                      # (the command line ignores what main returns)
        return rc
    from hypnomix.session import automation as aa
    src = Path(a.als)
    tree = aa.load(src); root = tree.getroot()
    bpb = aa.BPB
    tempo = B.set_tempo(root)
    if B.tempo_points(root) and not a.replace_tempo:
        sys.exit("this set already has tempo automation: add --replace-tempo to replace it")
    ends = [float(c.find("./CurrentEnd").get("Value")) for t in root.find(".//Tracks") for c in t.iter()
            if c.tag in ("AudioClip", "MidiClip") and c.find("./CurrentEnd") is not None and c.get("Time") is not None]
    arr = [float(c.find("./CurrentEnd").get("Value")) for c in root.findall(".//ArrangerAutomation/Events/*")
           if c.find("./CurrentEnd") is not None]
    end = max(arr or ends or [0.0])
    if end <= 0:
        sys.exit("no clips in the Arrangement")
    end = float(np.ceil(end / bpb) * bpb)
    if a.sections:
        secs, how = from_text(a.sections, bpb), "the sections you gave"
    else:
        secs, how = from_locators(root, end), "the set's locators"
        if not secs and a.mix:
            secs, how = from_mix(a.mix, tempo, bpb), "sections found in the mix (louder = pushed, quieter = relaxed)"
    if not secs:
        sys.exit("no sections to work from: give --sections \"17-32:+1.5, ...\", name locators in the set, or pass --mix")
    secs = [(b0, min(b1, end), round(float(np.clip(p * a.amount, LO, HI)), 2), n) for b0, b1, p, n in secs if b0 < end]
    try:
        pts = build_points(secs, tempo, end, a.glide, a.ritard, bpb)
    except Exception as e:
        sys.exit(str(e))
    old_len = end * 60.0 / tempo
    new_len = float(B.beat_seconds(pts, tempo, [end])[0])
    print(f"{src.name}: {tempo:g} BPM, {end / bpb:.0f} bars; from {how}\n")
    print(f"{'bars':>10}  {'change':>7}  {'tempo':>7}  section")
    for b0, b1, p, n in secs:
        print(f"{b0 / bpb + 1:>4.0f}-{b1 / bpb:<5.0f}  {p:>+6.1f}%  {tempo * (1 + p / 100):>7.2f}  {n}")
    if a.ritard:
        print(f"{'last bar':>10}  {-a.ritard:>+6.1f}%  (slows into the ending)")
    print(f"\nglide into each section over {a.glide:g} beats; the song becomes {abs(new_len - old_len):.1f} s "
          f"{'shorter' if new_len < old_len else 'longer'} ({old_len:.1f} → {new_len:.1f} s)")

    unwarped = []
    for t in root.find(".//Tracks"):
        if t.tag != "AudioTrack":
            continue
        name = t.find("./Name/EffectiveName").get("Value")
        n = [c for c in B.clips_of(t) if c.find("./IsWarped").get("Value") != "true"]
        if n:
            unwarped.append((name, n))
    n_un = sum(len(n) for _, n in unwarped)
    if n_un:
        print(f"\n{n_un} audio clips are NOT warped and would drift out of time: "
              + ", ".join(f"{name} ({len(n)})" for name, n in unwarped[:12]) + (" …" if len(unwarped) > 12 else ""))

    if a.preview:
        if not a.mix:
            sys.exit("--preview needs --mix (the bounce to bend)")
        y, sr = B.load(a.mix)
        grid = np.arange(0, min(end, len(y) / sr * tempo / 60.0) + 1e-9, 0.5)
        pairs = list(zip(grid * 60.0 / tempo, B.beat_seconds(pts, tempo, grid)))
        out = B.warp_render(y, sr, pairs, crisp=False)
        sf.write(a.preview, out, sr, subtype="PCM_24")
        print(f"\npreview → {a.preview}\n  (the bounce bent along the new tempo; it assumes the bounce starts at bar 1)")
    if not a.apply:
        print("\nnothing written: add --apply \"NEW.als\".")
        return
    if n_un and not a.warp_clips:
        sys.exit("\nnot written: add --warp-clips to switch warp on for those clips (they play the same at "
                 f"{tempo:g} BPM and follow the tempo from then on), or warp them yourself in Live first.")
    done = 0
    for name, cl in unwarped:
        drums = any(w in name.lower() for w in ("drum", "kick", "snare", "hat", "perc", "kit", "beat"))
        for c in cl:
            done += B.straight_warp(c, tempo, drums=drums)
    if done:
        print(f"warp switched on for {done} clips (Beats mode on drum tracks, Complex Pro elsewhere)")
    B.write_tempo_points(root, pts)
    B.finish(tree, src, a.apply)


if __name__ == "__main__":
    main()
