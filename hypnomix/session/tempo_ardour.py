"""`hypnomix tempomap --follow` and `hypnomix breathe` on a HypnoMix Studio session: the tempo map they make, written as
tempo points (project/ardour_automation.py) into the open engine (--engine [URL], tempo_set_points: one undo step)
or into a NEW .ardour snapshot in the session's folder (--apply NEW.ardour).

In HypnoMix Studio audio regions keep their time when the tempo map changes (audio that follows the tempo is not built
yet); MIDI and regions placed in music time follow the bars. So:
  tempomap --follow   the bar grid follows a take played without a click; the take stays exactly as played. One
                      tempo a bar (or a beat, --per beat), a bar or more of steady lead-in so the take's first bar line
                      lands on a bar line; bar lines then land on the take's within a millisecond or so
  breathe             the grid (and MIDI) breathe: each section a little faster or slower, a ramp into it (the
                      --glide beats, a HypnoMix Studio ramp: linear per beat, as the plan is). The recorded audio does NOT
                      breathe with it, so a session with audio regions needs --grid-only to say that is what you want
"""
import math
import sys
from pathlib import Path

import numpy as np

from hypnomix.project import ardour_automation as AA


def is_session(src):
    from hypnomix import project as PJ
    src = Path(src)
    return (src.is_dir() and PJ.ardour_session(src) is not None) or src.suffix.lower() == ".ardour"


def take(src, track, which):
    """(project, track, clip) for the take on `track`."""
    from hypnomix import project as PJ
    from hypnomix.workflow import vocallevel_project as VP
    p = PJ.load(src)
    if not track:
        sys.exit("give the track the take is on: --track NAME")
    t = VP.find_track(p, track, prefix=True)
    if t is None:
        sys.exit(f"no track called {track!r} (the tracks are: {', '.join(x.name for x in p.tracks)})")
    clips = [c for c in t.clips if c.take is not None and c.take.path is not None]
    if not clips:
        sys.exit(f"no audio regions on {t.name!r}")
    if len(clips) > 1 and which is None:
        sys.exit(f"{t.name!r} has {len(clips)} regions: say which with --clip N (1 = first)")
    c = clips[(which or 1) - 1]
    if not Path(c.take.path).exists():
        sys.exit(f"audio file not found: {c.take.path}")
    return p, t, c


def _writer(a, p):
    """'engine' (the open engine, checked to have this session) or the snapshot path to write."""
    if getattr(a, "engine", None) is not None and a.apply:
        sys.exit("choose one: --engine (into the open session) or --apply NEW.ardour (a new snapshot)")
    if getattr(a, "engine", None) is not None:
        return "engine"
    if not a.apply:
        return None
    out = Path(a.apply)
    if out.suffix.lower() != ".ardour":
        sys.exit("--apply writes a new snapshot of this session: give it a name ending in .ardour")
    if str(out.parent) in ("", "."):
        out = Path(p.path).parent / out.name
    if out.resolve().parent != Path(p.path).resolve().parent:
        sys.exit(f"--apply: a snapshot lives in its session's folder: give a name only, or a path in {Path(p.path).parent}")
    if out.exists():
        sys.exit(f"{out.name} already exists: choose a new name (nothing is ever overwritten)")
    return out


def write(a, p, pts, bpb, what):
    """The tempo points into the engine or a new snapshot; 0 when written."""
    where = _writer(a, p)
    if where is None:
        print("\nnothing written: add --engine (the open session) or --apply \"NEW.ardour\".")
        return 0
    moving = AA.music_time_regions(p)
    if moving:
        print(f"  note: {len(moving)} region(s) placed in music time follow the bars: "
              + ", ".join(f"{t} ({r})" for t, r in moving[:6]) + (" …" if len(moving) > 6 else ""))
    if where == "engine":
        from hypnomix.project import ardour_groups as AG
        try:
            eng = AG.Engine(a.engine or None)
            if not eng.has("tempo_get_map", "tempo_set_points"):
                sys.exit(f"the engine at {eng.url} does not answer, or has no tempo map tools (an older HypnoMix "
                         f"engine); {AG.WHERE_URL}")
            AG.require_open(eng, p.path)
            AA.write_tempo_engine(eng, pts, bpb)
            back = eng.call("tempo_get_map", {})
        except (AG.EngineError, ValueError) as e:
            sys.exit(f"nothing written: {e}")
        n = len(back.get("tempos") or [])
        print(f"wrote {what} into the open session: {n} tempo point(s), "
              f"{sum(1 for x in back.get('tempos') or [] if x.get('ramped'))} ramp(s), one undo step. {AG.APP_NOTICES}.")
        return 0
    from hypnomix.project import ardour_edit as AE
    try:
        AA.write_tempo_file(p, pts, bpb)
    except ValueError as e:
        sys.exit(f"nothing written: {e}")
    AE.save(p, where)
    errs = AE.check(p.path, where, tempo=True)
    if errs:
        bad = where.with_name(where.stem + " (BROKEN, do not open).ardour.txt")
        where.replace(bad)
        print(f"check FAILED: the written snapshot is not sound. Renamed to {bad.name}; keep using the original.")
        for e in errs:
            print(f"  {e}")
        return 1
    print(f"wrote {where}: {what}, {len(pts)} tempo point(s), "
          f"{sum(1 for x in pts if abs(x['bpm_end'] - x['bpm']) > 1e-6)} ramp(s); structure check OK")
    return 0


# ---------------------------------------------------------------- tempomap --follow
def follow(a, p, t, clip, m):
    """The bar grid follows the take (it stays as played)."""
    if a.conform:
        sys.exit("--conform warps the take onto the grid, and in HypnoMix Studio audio does not follow the tempo yet: "
                 "use --follow (the grid follows the take)")
    if not a.follow:
        print("\nnothing written. Add --follow with --engine or --apply NEW.ardour (see -h).")
        return 0
    if m["snapped"] < 0.5 and not a.anyway:
        sys.exit("not written: the tempo map is mostly guesswork (see above). Fix it with --bpm / --half / --double / "
                 "--downbeat, or add --anyway if the click check really sounds right.")
    if p.tempo_changes > 1 and not a.replace_tempo:
        sys.exit("the session already has a tempo map with changes: add --replace-tempo to replace it")
    bpb = a.bpb
    beats = np.asarray(m["beats"], dtype=float)
    T = clip.start + (beats - clip.take.offset)                       # where each beat plays in the session
    inside = [i for i in range(m["down"], len(beats), bpb) if clip.start - 0.02 <= T[i] <= clip.end + 0.02]
    if len(inside) < 2:
        sys.exit("fewer than one full bar of the take lies inside the region")
    d, e = inside[0], inside[-1]
    nbars = (e - d) // bpb
    step = bpb if a.per == "bar" else 1
    idx = list(range(d, e + 1, step))
    tempos = [step * 60.0 / (T[j] - T[i]) for i, j in zip(idx[:-1], idx[1:])]
    if not all(20 <= v <= 400 for v in tempos):
        sys.exit("a bar of the take reads outside 20-400 BPM: check the map with --click first")
    lead = float(T[d])
    K, bpm0 = 0, tempos[0]
    if lead > 0.01:
        K = max(1, int(round(lead / (bpb * 60.0 / tempos[0]))))
        while K > 1 and K * bpb * 60.0 / lead > 400:
            K -= 1
        bpm0 = K * bpb * 60.0 / lead
        while bpm0 < 20:
            K += 1
            bpm0 = K * bpb * 60.0 / lead
    line = [(0.0, bpm0)]
    for n, v in enumerate(tempos):
        b0 = K * bpb + n * step
        line += [(b0, line[-1][1]), (b0, v), (b0 + step, v)]
    pts = AA.from_beats(line, bpb)
    got = np.array(AA.seconds(pts, [K * bpb + k * bpb for k in range(nbars + 1)]))
    want = T[d:e + 1:bpb][:nbars + 1]
    err = float(np.abs(got - want).max()) * 1000
    print(f"\nfollow: one tempo a {a.per} over {nbars} bars ({min(tempos):.1f} to {max(tempos):.1f} BPM), "
          f"{K} bar(s) of lead-in at {bpm0:.2f} BPM; the take's first bar line is bar {K + 1}; bar lines land within "
          f"{err:.1f} ms of the take's. The take itself stays exactly as played")
    return write(a, p, pts, bpb, f"a tempo map that follows {t.name}")


# ---------------------------------------------------------------- breathe
def breathe(a, src):
    from hypnomix import project as PJ
    from hypnomix.session import breathe as BR
    from hypnomix.session import beats as B
    p = PJ.load(src)
    tempo, bpb = float(p.tempo), int(round(p.beats_per_bar or 4))
    if p.tempo_changes > 1 and not a.replace_tempo:
        sys.exit("this session already has a tempo map with changes: add --replace-tempo to replace it")
    end = float(np.ceil(p.end() * tempo / 60.0 / bpb) * bpb)
    if end <= 0:
        sys.exit("no regions in the session")
    if a.sections:
        secs, how = BR.from_text(a.sections, bpb), "the sections you gave"
    elif a.mix:
        secs, how = BR.from_mix(a.mix, tempo, bpb), "sections found in the mix (louder = pushed, quieter = relaxed)"
    else:
        secs, how = [], ""
    if not secs:
        sys.exit("no sections to work from: give --sections \"17-32:+1.5, ...\" or pass --mix")
    secs = [(b0, min(b1, end), round(float(np.clip(p_ * a.amount, BR.LO, BR.HI)), 2), n) for b0, b1, p_, n in secs if b0 < end]
    glide = max(1.0, float(round(a.glide)))                           # tempo points sit on beats
    line = BR.build_points(secs, tempo, end, glide, a.ritard, bpb)
    try:
        pts = AA.from_beats(line, bpb)
    except ValueError as e:
        sys.exit(str(e))
    old_len, new_len = end * 60.0 / tempo, AA.seconds(pts, [end])[0]
    print(f"{Path(p.path).name}: {tempo:g} BPM, {end / bpb:.0f} bars; from {how}\n")
    print(f"{'bars':>10}  {'change':>7}  {'tempo':>7}  section")
    for b0, b1, pc, n in secs:
        print(f"{b0 / bpb + 1:>4.0f}-{b1 / bpb:<5.0f}  {pc:>+6.1f}%  {tempo * (1 + pc / 100):>7.2f}  {n}")
    if a.ritard:
        print(f"{'last bar':>10}  {-a.ritard:>+6.1f}%  (slows into the ending)")
    print(f"\nramp into each section over {glide:g} beats; the grid becomes {abs(new_len - old_len):.1f} s "
          f"{'shorter' if new_len < old_len else 'longer'} ({old_len:.1f} → {new_len:.1f} s)")
    audio = sum(1 for t in p.tracks if t.kind == "audio" for c in t.clips if c.take is not None and c.take.path is not None)
    if a.preview:
        if not a.mix:
            sys.exit("--preview needs --mix (the bounce to bend)")
        import soundfile as sf
        y, sr = B.load(a.mix)
        grid = np.arange(0, min(end, len(y) / sr * tempo / 60.0) + 1e-9, 0.5)
        pairs = list(zip(grid * 60.0 / tempo, B.beat_seconds(line, tempo, grid)))
        sf.write(a.preview, B.warp_render(y, sr, pairs, crisp=False), sr, subtype="PCM_24")
        print(f"\npreview → {a.preview}\n  (the bounce bent along the new tempo: how it would breathe if the audio "
              "followed; in HypnoMix Studio today it does not)")
    if (a.apply or getattr(a, "engine", None) is not None) and audio and not a.grid_only:
        sys.exit(f"\nnot written: in HypnoMix Studio the {audio} audio region(s) keep their time when the tempo changes "
                 "(audio that follows the tempo map is not built yet), so the recording would not breathe; only the "
                 "bar grid and MIDI would. Add --grid-only to write the tempo map anyway.")
    return write(a, p, pts, bpb, "the breathing tempo map")
