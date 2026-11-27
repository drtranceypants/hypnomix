#!/usr/bin/env python3
"""Align vocal parts inside a saved Live set (or REAPER project): the timing goes onto your own clips as warp markers.

Nothing is rendered over your comp. Each part's clips get warp markers that move its words toward the guide (or the
group), written into a NEW set next to the original; every marker can be dragged or deleted in Live afterwards.
Pitch matching and formant can't be warp markers: those parts are rendered as files that start at bar 1, for a new
track next to the original (the Align device places them for you; or drag them in at 1.1.1).

Usage:
  hypnomix alignset SET.als --guide "Lead Vox" --parts "Double" "Harmony Hi" --to-average | --to-lead
           [--bars 33-49] [--apply]
           [every vocalign option: --preset, --protect, --sync, --strength, --stack-strength, --pitch, --formant ...]

  --to-average every part is nudged toward the group's average timing (the guide is the ruler and moves a little too)
  --to-lead    the parts follow the lead, which is never moved; the lead is --guide, or --lead "TRACK" (then the
               --guide track, if it is another one, is lined up like the other parts)
               With 2+ parts one of the two is needed: a flag, or your saved answer (`hypnomix prefs set
               harmony.reference=average` or `=lead`). Nothing is assumed. One part alone follows its guide.
  --guide      the track the others are measured against
  --parts      the tracks to move (names, or the start of names)
  --bars       only this part of the song (bars, 4/4: 33-49); --range 62-90 does the same in seconds
  --apply      write "SET (aligned).als" next to the original (without it: measure, write previews and a report)
  --keep-unwarped  leave clips that are not warped alone (default: warp is switched on for them, Complex Pro, playing
               exactly as before, so they can take the markers)
  --json FILE  the result for the app / device

Every part is first rendered from the set exactly as Live plays it (clip gain, fades, warps), aligned with the same
engine as `hypnomix vocalign`, checked independently, and only parts that measured closer are written. Times for
--protect and --sync are song seconds (the device sends them from the loop brace and the playhead).
Close the set in Live before opening the new one. Assumes a constant tempo.

A REAPER project (SONG.rpp) works the same way: stretch markers on the parts' own items, pitch / formant as new
takes on those items, in "SONG (aligned).rpp" (see hypnomix/studio/alignset_rpp.py).
"""
import argparse, json, sys, tempfile
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.core.paths import out_at
from hypnomix.studio import alignopts as AO
from hypnomix.studio import vocalign as V

SR = 44100
FR_S = V.FR_S
MIN_SPEED = 0.25          # warp markers never play slower than this (and never backwards)


def rdp(t, y, tol):
    """Indices of the fewest points whose straight-line joins stay within tol of (t, y) (Ramer-Douglas-Peucker)."""
    keep = np.zeros(len(t), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(t) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        seg = y[a] + (y[b] - y[a]) * (t[a + 1:b] - t[a]) / max(1e-12, t[b] - t[a])
        err = np.abs(y[a + 1:b] - seg)
        k = int(np.argmax(err))
        if err[k] > tol:
            m = a + 1 + k
            keep[m] = True
            stack += [(a, m), (m, b)]
    return np.flatnonzero(keep)


def markers_for_clip(ci, plan, tempo, tol_s=0.0005):
    """New warp markers [(file seconds, clip beats)] so the clip plays, at song time T, the audio it used to play at
    T + plan(T). Returns (pairs, max error in ms) or (None, reason). Where the plan would play audio backwards (or
    slower than MIN_SPEED), it is eased; markers_for_clip.eased says by how many ms (0 when nothing was eased)."""
    from hypnomix.session import smooth as sm, timing as tm
    spb = 60.0 / tempo
    cs, ce = ci["start"] * spb, ci["end"] * spb
    T = np.arange(cs, ce, 0.005)
    if len(T) < 4:
        return None, "clip too short"
    T = np.r_[T, ce]
    o = np.interp(T, np.arange(len(plan)) * FR_S, plan * FR_S, left=0.0, right=0.0)
    markers_for_clip.eased = 0.0
    if np.abs(o).max() < 0.0005:
        return [], 0.0
    src = sm.file_seconds(ci, (T + o) / spb, tempo)          # the audio that should now play at T (current map)
    d = MIN_SPEED * np.diff(sm.file_seconds(ci, T / spb, tempo))   # a quarter of the speed the clip plays at now
    if np.any(np.diff(src) <= d):
        # the move changes faster than audio can be slowed down (two neighbouring words moved opposite ways across a
        # short gap: the plan would play the gap backwards). Warp markers can't, so the change is eased over a little
        # more time there: the mean of the closest forward and backward paths that never go slower than MIN_SPEED
        # (both follow the plan wherever it is not too steep), as REAPER's alignset_rpp.item_markers does
        want = src.copy()
        fwd, bwd = src.copy(), src.copy()
        for i in range(1, len(fwd)):
            fwd[i] = max(fwd[i], fwd[i - 1] + d[i - 1])
        for i in range(len(bwd) - 2, -1, -1):
            bwd[i] = min(bwd[i], bwd[i + 1] - d[i])
        src = (fwd + bwd) / 2
        markers_for_clip.eased = float(np.abs(src - want).max() * 1000)
    if src[0] < 0:
        # a clip that starts at its file's first sample, asked to play a little earlier: there is no audio before the
        # file, so it starts there and catches up with the plan (never slower than MIN_SPEED)
        want = src.copy()
        src[0] = 0.0
        for i in range(1, len(src)):
            src[i] = max(src[i], src[i - 1] + d[i - 1])
        markers_for_clip.eased = max(markers_for_clip.eased, float(np.abs(src - want).max() * 1000))
    keep = rdp(T, src, tol_s)
    Tk, sk = T[keep], src[keep]
    beats = tm.arr_to_clipbeat(dict(ci, warped=True), Tk / spb)
    # guard markers one beat outside the clip's playing span, on the clip's current timing
    gb = [tm.arr_to_clipbeat(dict(ci, warped=True), x / spb) for x in (cs - spb, ce + spb)]
    gs = sm.file_seconds(ci, np.array([cs - spb, ce + spb]) / spb, tempo)
    pairs = [(float(gs[0]), float(gb[0]))] if gs[0] >= 0 and gs[0] < sk[0] - 1e-4 else []
    pairs += [(float(s), float(b)) for s, b in zip(sk, beats)]
    if gs[1] > sk[-1] + 1e-4:
        pairs.append((float(gs[1]), float(gb[1])))
    ok = all(s2 > s1 + 1e-6 and b2 > b1 + 1e-6 for (s1, b1), (s2, b2) in zip(pairs, pairs[1:]))
    if not ok:
        return None, "markers would cross: left as it was"
    new = dict(ci, warped=True, markers=[(b, s) for s, b in pairs])
    err = np.abs(sm.file_seconds(new, T / spb, tempo) - src).max() * 1000
    return pairs, float(err)


def write_markers(ci, pairs):
    from hypnomix.session import beats as B
    B.set_markers(ci["el"], pairs)
    ci["markers"] = sorted((b, s) for s, b in pairs)


def shape(y, sr, t0, t1, points=360):
    """Loudness (dB, -60..0 relative to the clip's own peak) at `points` steps across [t0, t1): what the device draws."""
    y = (y.mean(1) if y.ndim > 1 else y)[max(0, int(t0 * sr)):int(t1 * sr)]
    if not len(y):
        return [-60.0] * points
    edges = np.linspace(0, len(y), points + 1).astype(int)
    r = np.array([np.sqrt(np.mean(y[a:b] ** 2)) if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])])
    d = 20 * np.log10(r + 1e-9) - 20 * np.log10(r.max() + 1e-9)
    return [round(float(x), 1) for x in np.clip(d, -60, 0)]


def energy(names, files, outs, span):
    """For the device: each track's loudness shape before and after over the aligned span."""
    t0, t1 = span
    t1 = min(t1, t0 + 600)
    rows = []
    for n in names:
        y, sr = dsp.load(files[n])
        after = outs.get(str(files[n]))
        rows.append(dict(name=n, before=shape(y, sr, t0, t1),
                         after=shape(dsp.load(after, sr)[0], sr, t0, t1) if after else None))
    return dict(t0=t0, t1=t1, tracks=rows)


def main():
    from hypnomix.core import tmp as TMP
    with TMP.scope():                      # the renders it makes (hypnomix-alignset-…) are removed when it ends
        return _main()


def lead_and_guide(a):
    """Settle what the parts line up to before anything is rendered (a stack with no answer ends here, in one
    sentence), and who the lead is: --lead TRACK takes the guide's place, and the --guide track joins the parts."""
    if not a.guide and not a.lead_name:
        sys.exit("name the track the others are measured against: --guide \"TRACK\" (or --to-lead --lead \"TRACK\")")
    low = lambda s_: str(s_).strip().lower()
    parts = [p for p in a.parts if low(p) not in (low(a.guide or ""), low(a.lead_name or ""))]
    if a.lead_name and a.guide and low(a.lead_name) != low(a.guide):
        parts = [a.guide] + parts
    if not a.no_timing:
        AO.reference(a, len(parts))
    if a.lead_name:
        a.guide, a.parts = a.lead_name, parts


def _main():
    if "--list-presets" in sys.argv:
        print("\n".join(AO.describe(k) for k in AO.PRESETS))
        return
    ap = V.build_parser()
    ap.prog = "hypnomix alignset"
    ap.description = __doc__
    for act in list(ap._actions):                      # the file arguments are replaced by --guide / --parts
        if act.dest in ("lead", "overdubs"):
            ap._remove_action(act)
            ap._positionals._group_actions.remove(act)
    ap.add_argument("set")
    ap.add_argument("--guide")
    ap.add_argument("--parts", nargs="+", required=True)
    ap.add_argument("--bars")
    ap.add_argument("--range")
    ap.add_argument("--apply", nargs="?", const="", default=None, metavar="NEW.als|NEW.rpp")
    ap.add_argument("--keep-unwarped", action="store_true")
    ap.add_argument("--takes", action="store_true",
                    help="REAPER: the timing goes onto the items as new takes too (playing the checked preview exactly) "
                         "instead of stretch markers")
    ap.add_argument("--json")
    from hypnomix.session import liveversion as LV; LV.add_force_flag(ap)
    defaults = {k: ap.get_default(k) for k in vars(ap.parse_args(["x", "--guide", "g", "--parts", "p"]))}
    a = ap.parse_args()
    if a.list_presets:
        print("\n".join(AO.describe(k) for k in AO.PRESETS)); return
    AO.apply_preset(a, a.preset, defaults)
    lead_and_guide(a)
    if a.set.lower().endswith(".rpp"):
        from hypnomix.studio import alignset_rpp
        alignset_rpp.run(a)
        return
    from hypnomix.session import automation as aa, beats as B, render as R, smooth as sm, timing as tm
    src = Path(a.set).expanduser().resolve()
    tree = aa.load(src)
    root = tree.getroot()
    tempo = B.set_tempo(root)
    if B.tempo_points(root):
        sys.exit("this set has tempo automation: alignset assumes one tempo (use vocalign on exported files instead)")
    spb = 60.0 / tempo
    bpb = aa.BPB
    tracks = dict(sm.audio_tracks(root, [a.guide] + a.parts, include_off=True))
    pick = lambda n: next((k for k in tracks if k.lower() == n.lower()), None) or \
        next((k for k in tracks if k.lower().startswith(n.lower())), None)
    guide = pick(a.guide)
    parts = [p for p in dict.fromkeys(pick(n) for n in a.parts) if p and p != guide]
    if not guide or not parts:
        sys.exit(f"need a guide track and at least one other part (found guide {guide!r}, parts {parts})")
    end_b = max(float(c.find("./CurrentEnd").get("Value")) for n in [guide] + parts
                for c in tracks[n].findall(".//ArrangerAutomation/Events/AudioClip"))
    N = int((end_b * spb + 1.0) * SR)
    od = out_at(a.out, "alignset")
    warn = []
    files = {}
    from hypnomix.core import tmp as TMP
    tmp = TMP.scratch("alignset")
    for n in [guide] + parts:
        print(f"rendering {n} from the set …", file=sys.stderr)
        y = R.render_track(tracks[n], src, spb, N, SR, None, 0, warn)
        files[n] = dsp.save(tmp / f"{n.replace('/', '-')}.wav", y[:, None], SR, 24)
    # only inside --bars / --range: everything outside is protected
    span = None
    if a.bars:
        b0, b1 = (float(x) for x in a.bars.split("-"))
        span = ((b0 - 1) * bpb * spb, b1 * bpb * spb)
    elif a.range:
        span = AO.ranges([a.range])[0]
    prot = AO.ranges(a.protect)
    if span:
        prot = AO.ranges([f"0-{span[0]:.3f}"] if span[0] > 0 else []) + prot + [(span[1], N / SR + 1)]
        prot = sorted(prot)
    a._protect, a._sync = prot, AO.syncs(a.sync)
    if (a.pitch or a.vibrato) and not (a.chords or a.ref or a.no_chord_check):
        # the chord check needs the instruments: render the set's other audio tracks (not the vocals) and use that
        import re
        voc = re.compile(r"vox|vocal|voice|harm|double|dbl|bgv|backing|choir|adlib|ad-lib", re.I)
        inst = [(n, t) for n, t in sm.audio_tracks(root, [], include_off=False) if not voc.search(n)]
        if not inst:
            sys.exit("pitch matching needs the chord under each note: this set has no instrument audio tracks to read "
                     "it from. Pass --chords INSTRUMENTAL.wav (or --no-chord-check)")
        print(f"rendering the instruments for the chord check ({len(inst)} tracks) …", file=sys.stderr)
        mix = np.zeros(N)
        for n, t in inst:
            mix += R.render_track(t, src, spb, N, SR, None, 0, warn)
        a.chords = str(dsp.save(tmp / "instruments.wav", mix[:, None] * 0.5, SR, 24))
        md_chords = f"Chord check: the set's own instrument tracks ({', '.join(n for n, _ in inst)}); MIDI tracks are not heard."
    else:
        md_chords = ""
    a.lead, a.overdubs = str(files[guide]), [str(files[p]) for p in parts]
    md, outs = (["# Align in the set", "", "Timing step skipped (--no-timing)."], {}) if a.no_timing else V.timing_stage(a, od)
    # the plans, per part (the timing step put them in its rows)
    plans = getattr(V, "_last_plans", {})
    md[0] = f"# Align in the set: {src.name}"
    md[1:1] = ["", f"Guide: **{guide}**; parts: {', '.join(parts)}" + (f"; bars {a.bars}" if a.bars else "")
               + (f"; preset {a.preset}" if a.preset else "") + f". {tempo:g} BPM."] \
        + (["", AO.reference_line(a)] if AO.reference_line(a) else []) + (["", md_chords] if md_chords else [])
    result = dict(set=str(src), guide=guide, parts=[], out_set=None, previews={}, rendered={}, report=str(od / "ALIGNSET.md"),
                  reference=getattr(a, "_reference", None), reference_from=getattr(a, "_reference_from", None))
    edited = 0
    md += ["", "## Warp markers on your clips", ""]
    for p_ in [guide] + parts:                  # in stack mode the guide is nudged toward the group too
        f = str(files[p_])
        plan = plans.get(f)
        if p_ == guide and plan is None:
            continue
        row = dict(track=p_, clips=0, markers=0, skipped=[], preview=outs.get(f))
        result["previews"][p_] = outs.get(f)
        if plan is None or not outs.get(f):
            row["skipped"].append("not measurably closer (or nothing to move): its clips are left as they are")
            md.append(f"- {p_}: left as it was (the aligned version did not measure closer to the guide)")
            result["parts"].append(row)
            continue
        for c in tracks[p_].findall(".//ArrangerAutomation/Events/AudioClip"):
            ci = sm.clip_info(c, src.parent, tempo)
            if ci["disabled"]:
                continue
            T0, T1 = ci["start"] * spb, ci["end"] * spb
            seg = plan[int(T0 / FR_S):int(T1 / FR_S) + 1]
            if not len(seg) or np.abs(seg).max() * FR_S < 0.0005:
                continue
            if ci["loop_on"]:
                row["skipped"].append(f"{ci['name']}: looped clip (unroll it first: hypnomix unroll)"); continue
            if not ci["warped"]:
                if a.keep_unwarped:
                    row["skipped"].append(f"{ci['name']}: not warped (--keep-unwarped)"); continue
                if not tm.warp_on(ci, tempo):
                    row["skipped"].append(f"{ci['name']}: could not switch warp on"); continue
                B.set_val(ci["el"], "./WarpMode", "6")             # Complex Pro: the mode for voices
                row.setdefault("warp_switched_on", []).append(ci["name"])
            pairs, info = markers_for_clip(ci, plan, tempo)
            if pairs is None:
                row["skipped"].append(f"{ci['name']}: {info}"); continue
            if not pairs:
                continue
            write_markers(ci, pairs)
            row["clips"] += 1
            row["markers"] += len(pairs)
            row["max_err_ms"] = max(row.get("max_err_ms", 0.0), info)
            if markers_for_clip.eased > 0.5:
                row["eased_ms"] = max(row.get("eased_ms", 0.0), markers_for_clip.eased)
        edited += row["clips"]
        md.append(f"- {p_}: {row['markers']} warp markers on {row['clips']} clip(s)"
                  + (f" (warp switched on, Complex Pro, for {', '.join(row['warp_switched_on'])})" if row.get("warp_switched_on") else "")
                  + (f"; within {row['max_err_ms']:.2f} ms of the plan" if row.get("max_err_ms") is not None else "")
                  + (f" (eased by up to {row['eased_ms']:.0f} ms where the move changed faster than audio can be "
                     "slowed, between words, or reached before the start of a file)" if row.get("eased_ms") else "")
                  + ("; skipped: " + "; ".join(row["skipped"]) if row["skipped"] else ""))
        result["parts"].append(row)
    # pitch / formant: rendered files from bar 1, for a new track next to the original
    pf = V.pitch_and_formant(a, od, outs) if (a.pitch or a.vibrato or a.formant or a.transpose) else []
    if pf:
        md += pf + ["", "These start at bar 1 (1.1.1): put each on a new audio track next to its original and mute the "
                        "original (the Align device does this for you)."]
        for p_ in parts:
            v = outs.get(str(files[p_]))
            if v and (" pitch" in v or "formant" in v or "transpose" in v):
                final = od / f"{p_.replace('/', '-')} ({Path(v).stem.split('(', 1)[-1].rstrip(')')}).wav"
                Path(v).replace(final)
                result["rendered"][p_] = str(final)
    if a.apply is not None and edited:
        out = Path(a.apply) if a.apply else src.with_name(src.stem + " (aligned).als")
        k = 2
        while out.exists():
            out = src.with_name(src.stem + f" (aligned {k}).als"); k += 1
        if not out.is_absolute():
            out = src.parent / out
        ok = B.finish(tree, src, out)
        result["out_set"] = str(out) if ok else None
        md += ["", f"New set: `{out.name}`" + ("" if ok else " (FAILED the structural check: do not open)")]
    elif edited:
        md += ["", "Measured only: run again with --apply to write the new set."]
    else:
        md += ["", "Nothing to write: every part is left as it was."]
    if warn:
        md += ["", "Warnings:", *[f"- {w}" for w in warn]]
    result["energy"] = energy([guide] + parts, files, outs, span or (0.0, N / SR))
    (od / "ALIGNSET.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    result["markdown"] = "\n".join(md)
    if a.json:
        Path(a.json).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
