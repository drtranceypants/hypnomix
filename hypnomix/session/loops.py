#!/usr/bin/env python3
"""Find the stretches of a free-played take that would make good loops, and line them up to try.

  hypnomix loops TAKE.wav [--bars 1 2 4 8] [--top 8] [--out DIR]
  hypnomix loops SET.als --track "Drums" --apply "SET (loops).als" [--top 8]
  hypnomix loops SESSION.ardour --track "Drums" --cues [--engine URL]   (HypnoMix DAW: cue slots)
  hypnomix loops TAKE.wav --cues [--engine URL]

It maps the take's tempo (like `hypnomix tempomap`), then scores every 1, 2, 4 and 8 bar window:

  steady     how even the beats are inside the window (a loop that speeds up will lurch at the seam)
  seam       how well the end leads back into the start (the bar after the window starts like the window)
  groove     how alike its bars are (a settled pattern), or "fill": settled bars that end in a fill

Windows are grouped into grooves (A, B, C: bars that play the same pattern), and the best few of each
groove are offered, so you get different ideas, not eight copies of the same bar.

Output: each loop as a WAV cut from bar line to bar line (as played, tempo in the name), LOOPS.md and
loops.json. With a Live set, --apply writes a NEW set where each loop sits in a Session-view slot of the
take's track: warped to the set's tempo, looping, named. Launch them one after another in Session view
to compare; drag the one you like into the Arrangement. The Arrangement itself is not changed.

With --cues, the loops go into the cue slots (the Session view) of the session open in the HypnoMix engine, on a
track "<Track> loops" right after the take's track (made new, or the empty slots of one already there; while a
track's slot holds a clip, that track's Arrangement does not play, so never on the take's own track): looping,
launched on the bar, at the session's tempo. With a HypnoMix DAW session (.ardour) the take is the --track's region
(--clip N for another one); it must be the session the engine has open. --engine URL, else HYPNOMIX_ENGINE_URL, else
a HypnoMix DAW window on 127.0.0.1:4820. HypnoMix sees the change (the session shows as unsaved, and Stop, Open, New
and quit ask Save first): save the session to keep them.

Check the tempo map first (`hypnomix tempomap TAKE.wav --click CHECK.wav`): loops cut on wrong bar
lines are useless. Pass the same --downbeat / --double / --half here. Close the set before --apply.
"""
import argparse, copy, json, math, re, sys
from hypnomix.core import args as A
from pathlib import Path

import numpy as np
import soundfile as sf
import librosa

from hypnomix.session import beats as B

STEPS = 16     # pattern resolution: 16 steps per bar


def bar_patterns(mono, sr, beats, down, bpb):
    """One vector per bar: hit strength on each 16th in three bands (low / mid / high)."""
    y = librosa.resample(mono, orig_sr=sr, target_sr=B.SR_B) if sr != B.SR_B else mono
    S = np.abs(librosa.stft(y, n_fft=1024, hop_length=B.HOP))
    f = librosa.fft_frequencies(sr=B.SR_B, n_fft=1024)
    bands = [S[(f >= a) & (f < b)].sum(0) for a, b in ((20, 150), (150, 2500), (2500, 11000))]
    flux = [np.maximum(0, np.diff(b, prepend=b[:1])) for b in bands]
    lines = beats[down::bpb]
    pats, level = [], []
    for a, b in zip(lines[:-1], lines[1:]):
        edges = np.linspace(a, b, STEPS + 1)
        fr = np.clip((edges * B.SR_B / B.HOP).astype(int), 0, len(flux[0]) - 1)
        v = [fl[fr[i]: max(fr[i] + 1, fr[i + 1])].max() for fl in flux for i in range(STEPS)]
        pats.append(np.array(v))
        seg = mono[int(a * sr): int(b * sr)]
        level.append(10 * np.log10(np.mean(seg ** 2) + 1e-12))
    P = np.array(pats)
    P = P / (np.linalg.norm(P, axis=1, keepdims=True) + 1e-9)
    return P, np.array(level), lines


def grooves(P, thresh=0.8):
    """Label bars that play the same pattern with the same letter."""
    lab, cent = [], []
    for p in P:
        sims = [float(p @ c / (np.linalg.norm(c) + 1e-9)) for c in cent]
        if sims and max(sims) >= thresh:
            k = int(np.argmax(sims))
            cent[k] = cent[k] + p
        else:
            k = len(cent)
            cent.append(p.copy())
        lab.append(k)
    order = {k: n for n, (k, _) in enumerate(sorted(((k, lab.count(k)) for k in set(lab)), key=lambda x: -x[1]))}
    return [order[k] for k in lab]


def candidates(m, mono, sr, sizes, top):
    beats, bpb = m["beats"], m["bpb"]
    P, level, lines = bar_patterns(mono, sr, beats, m["down"], bpb)
    n = len(P)
    if n < 1:
        return [], lines
    lab = grooves(P)
    loud = level > (np.median(level) - 18)
    out = []
    for L in sizes:
        for i in range(0, n - L + 1):
            if not loud[i:i + L].all():
                continue
            k0 = m["down"] + i * bpb
            if m["on_hit"][k0: k0 + L * bpb].mean() < 0.6 or not m["on_hit"][k0]:
                continue                      # beats that were filled in, not played: no evidence this is a loop
            iv = np.diff(beats[k0: k0 + L * bpb + 1])
            if len(iv) < L * bpb:
                continue
            cv = float(np.std(iv) / np.mean(iv))
            steady = math.exp(-cv / 0.04)
            seam = float(P[i + L] @ P[i]) if i + L < n else 0.5      # the bar after it starts like its first bar
            body = P[i:i + L]
            if L == 1:
                alike, fill = 1.0, False
            else:
                sims = [float(body[a] @ body[b]) for a in range(L) for b in range(a + 1, L)]
                alike = float(np.mean(sims))
                head = [float(body[a] @ body[b]) for a in range(L - 1) for b in range(a + 1, L - 1)] or [1.0]
                last = float(np.mean([body[a] @ body[L - 1] for a in range(L - 1)]))
                fill = L >= 2 and np.mean(head) > 0.8 and last < 0.65
            groove = alike if not fill else float(np.mean(head))
            score = 0.4 * steady + 0.3 * max(0.0, seam) + 0.3 * max(0.0, groove)
            g = max(set(lab[i:i + L]), key=lab[i:i + L].count)
            bpm = bpb * 60.0 * L / (lines[i + L] - lines[i])
            out.append(dict(bar=i + 1, bars=L, start=float(lines[i]), end=float(lines[i + L]), bpm=round(bpm, 1),
                            score=round(score, 3), steady=round(steady, 2), seam=round(seam, 2),
                            groove="ABCDEFGHIJKLMNOPQRSTUVWXYZ"[g % 26], fill=bool(fill), beat_index=int(k0)))
    out.sort(key=lambda c: -c["score"])
    picked, per_groove = [], {}
    for round_cap in (1, 2, 99):                      # first one of each groove and size, then seconds, then the rest
        for c in out:
            if len(picked) >= top:
                break
            key = (c["groove"], c["bars"], c["fill"])
            if c in picked or per_groove.get(key, 0) >= round_cap:
                continue
            clash = any(min(c["end"], p["end"]) - max(c["start"], p["start"]) > 0.25 * (c["end"] - c["start"])
                        and p["bars"] == c["bars"] for p in picked)
            if clash:
                continue
            picked.append(c)
            per_groove[key] = per_groove.get(key, 0) + 1
    picked.sort(key=lambda c: (c["groove"], c["bars"], c["bar"]))
    for n_, c in enumerate(picked, 1):
        c["n"] = n_
        c["name"] = (f"{n_:02d} groove {c['groove']}{' + fill' if c['fill'] else ''}, {c['bars']} bar"
                     f"{'s' if c['bars'] > 1 else ''} from bar {c['bar']} ({c['bpm']:.1f} BPM)")
    return picked, lines


def cut(y, sr, c):
    a, b = int(max(0, c["start"] - 0.002) * sr), int((c["end"] - 0.002) * sr)
    seg = y[a:b].copy()
    k = min(len(seg), int(0.004 * sr))
    seg[-k:] *= np.linspace(1, 0, k)[:, None]
    return seg


def main():
    ap = argparse.ArgumentParser(prog="hypnomix loops", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source"); ap.add_argument("--track"); ap.add_argument("--clip", type=int)
    ap.add_argument("--bars", type=int, nargs="+", default=[1, 2, 4, 8]); ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--bpb", type=int, help="beats per bar (default: the session's own for a HypnoMix DAW session, else 4)")
    ap.add_argument("--bpm", type=A.number(20, 400))
    ap.add_argument("--downbeat", type=float); ap.add_argument("--double", action="store_true"); ap.add_argument("--half", action="store_true")
    ap.add_argument("--out"); ap.add_argument("--apply", metavar="NEW.als")
    ap.add_argument("--cues", action="store_true", help="put the loops into cue slots of the session open in the HypnoMix engine (with a session file, "
                         "that very file must be the one open). HypnoMix sees the change: the session shows as "
                         "unsaved, and Stop, Open, New and quit ask Save first; save in HypnoMix DAW to keep them")
    ap.add_argument("--engine", help="the engine's MCP URL (with --cues; it is in the DAW view's engine panel)")
    from hypnomix.session import liveversion as LV; LV.add_force_flag(ap)
    a = ap.parse_args()
    src = Path(a.source)
    is_set = src.suffix.lower() == ".als"
    is_ardour = src.suffix.lower() == ".ardour"
    if is_ardour and a.apply:
        sys.exit("--apply writes a Live set: for a HypnoMix DAW session use --cues (the engine's Session view)")
    if a.cues and a.apply:
        sys.exit("choose --apply (a new Live set) or --cues (the engine's cue slots), not both")
    eng = None
    if a.cues:
        from hypnomix.project import ardour_cues as AC
        try:
            eng = AC.connect(a.engine, session=src if is_ardour else None)
        except RuntimeError as e:
            sys.exit(str(e))
    tempo = None
    if is_ardour:
        from hypnomix import project as PJ
        if not a.track:
            sys.exit("give the track the take is on: --track NAME")
        p = PJ.load(src)
        t = p.track(a.track)
        clips = [c for c in (t.clips if t else []) if c.kind == "audio" and c.path is not None]
        if not clips:
            sys.exit(f"no track {a.track!r} with audio regions in {src.name}")
        if a.clip is not None and not 1 <= a.clip <= len(clips):
            sys.exit(f"{t.name} has {len(clips)} audio region(s): --clip 1 to {len(clips)}")
        clip = clips[a.clip - 1] if a.clip else max(clips, key=lambda c: c.length)
        audio, tempo = Path(clip.path), p.tempo
        if a.bpb is None:
            q = float(p.beats_per_bar or 4)
            if abs(q - round(q)) > 1e-6 or getattr(p, "meter_changes", 0):
                sys.exit(f"this session's bar is {q:g} quarter notes{' and its meter changes' if getattr(p, 'meter_changes', 0) else ''}: "
                         "say the beats per bar with --bpb")
            a.bpb = int(round(q))
        if not audio.exists():
            sys.exit(f"the region's recording is missing: {audio}")
    elif is_set:
        from hypnomix.session import automation as aa, smooth as sm
        from hypnomix.session.tempomap import one_clip
        if not a.track:
            sys.exit("give the track the take is on: --track NAME")
        tree = aa.load(src); root = tree.getroot()
        tempo = B.set_tempo(root)
        t, clip, _ = one_clip(root, a.track, a.clip)
        audio = sm.clip_info(clip, src.parent, tempo)["path"]
    else:
        audio = src
    a.bpb = a.bpb or 4
    try:
        m = B.track(audio, bpb=a.bpb, bpm=a.bpm, downbeat=a.downbeat, mult=2.0 if a.double else 0.5 if a.half else 1.0)
    except ValueError as e:
        sys.exit(str(e))
    y, sr = B.load(audio)
    picked, lines = candidates(m, y.mean(1), sr, sorted(set(a.bars)), a.top)
    if not picked:
        sys.exit("no loop candidates: too few full bars, the take is mostly silence, or its beat could not be "
                 f"followed ({m['snapped'] * 100:.0f}% of beats sit on a hit). Check `hypnomix tempomap FILE --click OUT.wav`; "
                 "try --bpm, --half or --double.")
    if m["snapped"] < 0.5:
        print("!! fewer than half the beats sit on a hit: the tempo map is shaky. Only windows where the beats "
              "were really played are offered; check them by ear.\n")
    from hypnomix.core.paths import out_at
    od = out_at(a.out, "loops", audio.stem)
    print(f"{audio.name}: {len(lines) - 1} bars at about {m['bpm']:.1f} BPM "
          f"(wanders {m['wander_pct']:.1f}%); first bar line {'given' if a.downbeat is not None else 'guessed'} at {lines[0]:.2f} s\n")
    print(f"{'#':>2}  {'groove':<10} {'bars':>4} {'from bar':>8} {'BPM':>6} {'steady':>6} {'seam':>5}  score")
    md = [f"# Loop candidates: {audio.name}", "",
          f"{len(lines) - 1} bars at about {m['bpm']:.1f} BPM. Loops are cut as played; the tempo of each is in its name.",
          "Measured, not heard: play each one and trust your ears over the score.", "",
          "| # | groove | bars | from bar | at | BPM | steady | seam | score |", "|---|---|---|---|---|---|---|---|---|"]
    for c in picked:
        sf.write(str(od / (re.sub(r'[\\/:*?"<>|]', "-", c["name"]) + ".wav")), cut(y, sr, c), sr, subtype="PCM_24")
        g = c["groove"] + (" + fill" if c["fill"] else "")
        print(f"{c['n']:>2}  {g:<10} {c['bars']:>4} {c['bar']:>8} {c['bpm']:>6.1f} {c['steady']:>6.2f} {c['seam']:>5.2f}  {c['score']:.2f}")
        md.append(f"| {c['n']} | {g} | {c['bars']} | {c['bar']} | {int(c['start'] // 60)}:{c['start'] % 60:04.1f} | {c['bpm']:.1f} | "
                  f"{c['steady']:.2f} | {c['seam']:.2f} | {c['score']:.2f} |")
    (od / "LOOPS.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (od / "loops.json").write_text(json.dumps(dict(file=str(audio), bpm=round(m["bpm"], 2), loops=picked), indent=1), encoding="utf-8")
    print(f"\n→ {od}")
    if a.cues:
        from hypnomix.project import ardour_cues as AC
        try:
            after, tname = AC.track_id(eng, a.track) if is_ardour else (None, None)
            name = f"{tname or audio.stem} loops"
            tid, _ = AC.clip_track(eng, name, after)
            placed = AC.fill(eng, tid, [dict(file=str(od / (re.sub(r'[\\/:*?"<>|]', "-", c["name"]) + ".wav")), name=c["name"],
                                             beats=c["bars"] * a.bpb) for c in picked])
        except (RuntimeError, AC.MCPError) as e:
            sys.exit(f"the cue slots were not filled: {e}")
        print(AC.report(placed, name))
        if AC.not_placed(placed):
            sys.exit(1)
        return
    if not a.apply:
        if is_set:
            print("add --apply \"NEW.als\" to put these in the track's Session slots.")
        elif is_ardour:
            print("add --cues to put these in cue slots of the session open in the HypnoMix engine.")
        return
    if not is_set:
        sys.exit("--apply needs a Live set with the take on a track")
    slots = [s.find("./ClipSlot/Value") for s in t.findall("./DeviceChain/MainSequencer/ClipSlotList/ClipSlot")]
    free = [v for v in slots if v is not None and len(v) == 0]
    if not free:
        sys.exit("no empty Session slots on that track: add scenes in Live, save, and run again")
    beats, bpb = m["beats"], a.bpb
    placed = 0
    for c, slot in zip(picked, free):
        k0, k1 = c["beat_index"], c["beat_index"] + c["bars"] * bpb
        lo, hi = max(0, k0 - bpb), min(len(beats) - 1, k1 + bpb)
        new = copy.deepcopy(clip)
        new.set("Id", "0"); new.set("Time", "0")
        B.set_markers(new, [(float(beats[k]), float(k - k0 + 2 * bpb)) for k in range(lo, hi + 1)])   # the loop starts at clip beat 2 bars
        new.find("./IsWarped").set("Value", "true")
        B.set_val(new, "./WarpMode", "0")
        B.set_region(new, 2.0 * bpb, 2.0 * bpb + c["bars"] * bpb, loop=True)
        new.find("./CurrentStart").set("Value", "0")
        new.find("./CurrentEnd").set("Value", repr(float(c["bars"] * bpb)))
        B.set_val(new, "./Name", c["name"])
        for tag in ("FadeInLength", "FadeOutLength"):
            B.set_val(new, f"./Fades/{tag}", 0.0)
        slot.append(new)
        placed += 1
    print(f"{placed} loops placed in the Session slots of {a.track!r}"
          + (f" ({len(picked) - placed} did not fit: only {len(free)} empty slots)" if placed < len(picked) else "")
          + f"; they play at the set's tempo ({tempo:g} BPM).")
    B.finish(tree, src, a.apply)


if __name__ == "__main__":
    main()
