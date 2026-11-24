#!/usr/bin/env python3
"""Map the tempo of a recording that was played WITHOUT a click (a drum take, a strummed guitar).

  hypnomix tempomap TAKE.wav [--click CHECK.wav] [--json OUT.json]
  hypnomix tempomap SET.als --track "Drums" --conform --apply "SET (conformed).als" [--preview OUT.wav]
  hypnomix tempomap SET.als --track "Drums" --follow  --apply "SET (tempo map).als"

It follows the beat through the take (the tempo is allowed to wander), puts every beat on the start of
its hit, guesses which beat is "one" from the low end, and reports the tempo of every bar.

Check it by ear first: --click writes the take with a click on every beat it found (high click = bar
line). If the click is on the off-beat or at half / double speed, correct it with --downbeat SECONDS,
--double or --half, and look again. Nothing else is worth doing until the click sits right.

With a Live set (the take on its own audio track, one clip), there are two ways to use the map:

  --conform   the TAKE follows Live's grid. Warp markers go on every bar line (or every beat with
              --per beat), so the take plays at the set's steady tempo. Markers on bar lines only keep
              the feel inside each bar exactly as played; --per beat is tighter. Use this to build a
              song on a steady grid, or to cut loops from the take.
  --follow    Live's GRID follows the take. The take is left exactly as played (warp off) and the set
              gets tempo automation, one value per bar, so bar lines land on the drummer's bar lines.
              Use this to keep a live performance and overdub to it with a click that breathes.

Both write a NEW set in the same folder, start the take on a bar line at its first full bar, and run
`hypnomix check` on the result. --preview (with --conform) renders the conformed take with a click,
without Live, so you can hear the result first. Close the set in Live before --apply.

Limits: one time signature (--bpb, default 4 beats per bar). A long silence or a free-time passage
inside the take is bridged at the last tempo: check those spots. --follow changes the tempo of the
whole set: warped clips on other tracks will follow it, unwarped ones will not.
"""
import argparse, json, math, sys
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix.session import beats as B


def describe(m, name):
    bars = m["bars"]
    print(f"{name}: {len(m['beats'])} beats, {max(0, len(bars) - 1)} full bars, {m['duration']:.1f} s")
    print(f"  tempo: median {m['bpm']:.1f} BPM; bars range {m['lo']:.1f} to {m['hi']:.1f} "
          f"(wanders {m['wander_pct']:.1f}% between the slow and fast bars)")
    print(f"  {m['snapped'] * 100:.0f}% of beats sit on a real hit; the rest are filled in between hits")
    if m["snapped"] < 0.5:
        print("  !! fewer than half the beats sit on a hit: this map is mostly guesswork. The take may not be "
              "rhythmic enough to follow (sustained notes, a voice), or the tempo was read wrong: try --bpm, "
              "--half or --double, and check with --click before using it.")
    sure = m["downbeat_sure"]
    print(f"  first bar line at {bars[0]:.2f} s " + ("(given)" if sure == 1.0 else
          f"({'fairly sure' if sure > 0.5 else 'a GUESS'}: check with --click, correct with --downbeat SECONDS)"))
    if len(m["bar_bpm"]):
        n = len(m["bar_bpm"])
        step = max(1, n // 16)
        print("  bar: BPM   " + "  ".join(f"{i + 1}:{m['bar_bpm'][i]:.0f}" for i in range(0, n, step)))
        d = np.diff(m["bar_bpm"])
        if len(d):
            j = int(np.argmax(np.abs(d)))
            print(f"  biggest change between bars: {d[j]:+.1f} BPM going into bar {j + 2} "
                  f"({'a fill, a section change or a tracking slip: listen there' if abs(d[j]) > 0.06 * m['bpm'] else 'gentle'})")


def one_clip(root, track, which):
    from hypnomix.session import automation as aa, smooth as sm
    t = aa.find_track(root, track)
    clips = B.clips_of(t)
    if not clips:
        sys.exit(f"no audio clips in the Arrangement on {track!r}")
    if len(clips) > 1 and which is None:
        sys.exit(f"{track!r} has {len(clips)} clips: say which with --clip N (1 = first)")
    c = clips[(which or 1) - 1]
    return t, c, clips


def main():
    ap = argparse.ArgumentParser(prog="hypnomix tempomap", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="an audio file, or a Live set (.als) with --track")
    ap.add_argument("--track"); ap.add_argument("--clip", type=int)
    ap.add_argument("--bpb", type=int, default=4, help="beats per bar (default 4)")
    ap.add_argument("--bpm", type=float, help="a hint for the tempo")
    ap.add_argument("--downbeat", type=float, metavar="SECONDS", help="where a bar line is, in seconds into the file")
    ap.add_argument("--double", action="store_true", help="the beat is twice as fast as found")
    ap.add_argument("--half", action="store_true", help="the beat is half as fast as found")
    ap.add_argument("--click", metavar="OUT.wav", help="write the take with a click on the beats found")
    ap.add_argument("--json", metavar="OUT.json")
    ap.add_argument("--conform", action="store_true", help="warp the take onto the set's grid")
    ap.add_argument("--follow", action="store_true", help="make the set's tempo follow the take")
    ap.add_argument("--per", choices=("bar", "beat"), default="bar", help="one marker / tempo value per bar (default) or per beat")
    ap.add_argument("--set-tempo", action="store_true", help="with --conform: also set the set's tempo to the take's median")
    ap.add_argument("--replace-tempo", action="store_true", help="with --follow: replace tempo automation that is already there")
    ap.add_argument("--preview", metavar="OUT.wav", help="with --conform: render the conformed take with a click, without Live")
    ap.add_argument("--anyway", action="store_true", help="use a tempo map that looks unreliable")
    ap.add_argument("--apply", metavar="NEW.als")
    a = ap.parse_args()
    src = Path(a.source)
    mult = 2.0 if a.double else 0.5 if a.half else 1.0
    is_set = src.suffix.lower() == ".als"
    if is_set:
        from hypnomix.session import automation as aa, smooth as sm
        if not a.track:
            sys.exit("give the track the take is on: --track NAME")
        tree = aa.load(src)
        root = tree.getroot()
        tempo = B.set_tempo(root)
        t, clip, clips = one_clip(root, a.track, a.clip)
        ci = sm.clip_info(clip, src.parent, tempo)
        audio = ci["path"]
        if not audio.exists():
            sys.exit(f"audio file not found: {audio}")
    else:
        audio = src
    try:
        m = B.track(audio, bpb=a.bpb, bpm=a.bpm, downbeat=a.downbeat, mult=mult)
    except ValueError as e:
        sys.exit(str(e))
    describe(m, audio.name)
    beats, bpb = m["beats"], a.bpb
    if a.click:
        y, sr = B.load(audio)
        y = y + B.click_track(len(y), sr, beats, m["down"], bpb)[:, None]
        sf.write(a.click, y, sr, subtype="PCM_24")
        print(f"click check → {a.click}  (high click = bar line)")
    if a.json:
        Path(a.json).write_text(json.dumps(dict(file=str(audio), bpm=round(m["bpm"], 2), bpb=bpb,
            beats=[round(float(x), 4) for x in beats], bars=[round(float(x), 4) for x in m["bars"]],
            bar_bpm=[round(float(x), 2) for x in m["bar_bpm"]], wander_pct=round(m["wander_pct"], 2),
            downbeat_sure=round(m["downbeat_sure"], 2)), indent=1))
    if not is_set:
        if a.conform or a.follow or a.apply:
            sys.exit("--conform / --follow need a Live set with the take on a track")
        return
    if not (a.conform or a.follow):
        print("\nnothing written. Add --conform or --follow with --apply NEW.als (see -h).")
        return
    if a.conform and a.follow:
        sys.exit("choose one of --conform and --follow")
    if m["snapped"] < 0.5 and not a.anyway:
        sys.exit("not written: the tempo map is mostly guesswork (see above). Fix it with --bpm / --half / --double / "
                 "--downbeat, or add --anyway if the click check really sounds right.")

    # the part of the file the clip plays now: stay inside it
    f0, f1 = (float(x) for x in sm.file_seconds(ci, np.array([ci["start"], ci["end"] - 1e-6]), tempo))
    if ci["loop_on"]:
        f0, f1 = 0.0, m["duration"]
    down = [i for i in range(m["down"], len(beats), bpb)]
    inside = [i for i in down if beats[i] >= f0 - 0.02 and beats[i] <= f1 + 0.02]
    if len(inside) < 2:
        sys.exit("fewer than one full bar of the take lies inside the clip")
    d, e = inside[0], inside[-1]
    nbars = (e - d) // bpb
    S = math.ceil(ci["start"] / bpb - 1e-6) * bpb                    # start the take on a bar line
    E = S + nbars * bpb
    for o in clips:
        if o is clip:
            continue
        os_, oe = float(o.find("./CurrentStart").get("Value")), float(o.find("./CurrentEnd").get("Value"))
        if os_ < E - 1e-6 and oe > S + 1e-6:
            sys.exit(f"the take would run from beat {S:g} to {E:g} and overlap another clip on the track: "
                     "move the take to its own track first")
    played = bpb * 60.0 * nbars / (beats[e] - beats[d])
    print(f"\nthe take: {nbars} full bars from {beats[d]:.2f} s to {beats[e]:.2f} s of the file, played at "
          f"{played:.1f} BPM on average; the set is at {tempo:g} BPM")

    if a.conform:
        if a.set_tempo:
            new_t = round(m["bpm"], 1)
            B.main_track(root).find("./DeviceChain/Mixer/Tempo/Manual").set("Value", repr(new_t))
            if not B.tempo_points(root) and B.tempo_env(root) is not None:
                B.write_tempo_points(root, [(0.0, new_t)])
                ev = B.tempo_env(root).find("./Automation/Events")
                ev.remove(list(ev)[-1])                               # keep only the starting point
            print(f"set tempo {tempo:g} → {new_t:g} BPM")
            tempo = new_t
        period = float(np.median(np.diff(beats)))
        pre = bpb * math.ceil((d + beats[0] / period + 1) / bpb)       # so the file's start is not before beat 0
        step = bpb if a.per == "bar" else 1
        idx = [i for i in range(d % step, len(beats), step)]
        pairs = [(float(beats[i]), float(pre + (i - d))) for i in idx]
        B.set_markers(clip, pairs)
        was_warped = clip.find("./IsWarped").get("Value") == "true"
        clip.find("./IsWarped").set("Value", "true")
        if not was_warped:
            B.set_val(clip, "./WarpMode", "0")                        # Beats mode: right for drums
        B.set_region(clip, float(pre), float(pre + (e - d)))
        stretch = (tempo / played - 1) * 100
        print(f"conform: {len(pairs)} warp markers (one per {a.per}); the take plays {abs(stretch):.1f}% "
              f"{'faster' if stretch > 0 else 'slower'} than played"
              + ("" if abs(stretch) < 8 else "  ← a big stretch: consider --set-tempo so the set sits at the take's tempo"))
        if a.preview:
            y, sr = B.load(audio)
            spb = 60.0 / tempo
            out = B.warp_render(y, sr, [(s, b * spb) for s, b in pairs])   # clip beat b plays at b beats
            grid = np.arange(0, len(out) / sr, spb)
            out = out + B.click_track(len(out), sr, grid, 0, bpb)[:, None]
            sf.write(a.preview, out, sr, subtype="PCM_24")
            print(f"preview (take on a steady {tempo:g} BPM click) → {a.preview}")
    else:
        if len(B.tempo_points(root)) > 0 and not a.replace_tempo:
            sys.exit("the set already has tempo automation: add --replace-tempo to replace it")
        step = bpb if a.per == "bar" else 1
        idx = list(range(d, e + 1, step))
        pts = []
        for n, (i, j) in enumerate(zip(idx[:-1], idx[1:])):
            v = step * 60.0 / (beats[j] - beats[i])
            b0 = S + n * step
            if pts:
                pts.append((b0, pts[-1][1]))                           # a step: the old value, then the new one
            pts.append((b0, v))
            pts.append((b0 + step, v))
        try:
            B.write_tempo_points(root, pts)
        except ValueError as ex:
            sys.exit(str(ex))
        B.set_markers(clip, [(0.0, 0.0), (0.03125 * 60.0 / tempo, 0.03125)])
        clip.find("./IsWarped").set("Value", "false")
        B.set_region(clip, float(beats[d]), float(beats[e]))            # seconds: the clip is not warped
        got = B.beat_seconds(pts, tempo, S + np.arange(0, nbars + 1) * bpb)
        want = beats[d:e + 1:bpb] - beats[d]
        err = float(np.abs((got - got[0]) - want).max()) * 1000
        others = sum(len(B.clips_of(x)) for x in root.find(".//Tracks") if x.tag == "AudioTrack") - 1
        print(f"follow: tempo automation with one value per {a.per} over {nbars} bars "
              f"({min(v for _, v in pts):.1f} to {max(v for _, v in pts):.1f} BPM); bar lines land within "
              f"{err:.1f} ms of the take's")
        if others > 0:
            print(f"  note: {others} other audio clips are in this set. Warped ones will follow the new tempo; "
                  "unwarped ones keep their speed.")
    clip.find("./CurrentStart").set("Value", repr(float(S)))
    clip.find("./CurrentEnd").set("Value", repr(float(E)))
    clip.set("Time", repr(float(S)))
    ev = t.find("./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events")
    kids = sorted(ev, key=lambda c: float(c.get("Time") or 0))
    for k in list(ev):
        ev.remove(k)
    ev.extend(kids)
    print(f"the take now runs from bar {S // bpb + 1:g} to bar {E // bpb + 1:g}; audio before its first bar line "
          "is hidden, not deleted (drag the clip's left edge to get it back)")
    if not a.apply:
        print("\nnothing written: add --apply \"NEW.als\".")
        return
    B.finish(tree, src, a.apply)


if __name__ == "__main__":
    main()
