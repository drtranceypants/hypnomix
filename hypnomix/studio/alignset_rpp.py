"""alignset on a REAPER project: the timing goes onto your own items as stretch markers, in a NEW project.

`hypnomix alignset Song.rpp --guide "Lead Vox" --parts "Double" "Harmony Hi" [--bars 33-49] [--apply]` takes every
option alignset takes on a Live set (presets, --protect, --sync, --strength, --pitch, --vibrato, --formant, ...).

1. Each track is rendered from the saved project as REAPER plays its items (item and take volume, fades, playrate,
   stretch markers already there), without the fader or plug-ins.
2. The same engine as `hypnomix vocalign` plans the moves, renders previews and checks them; a part that does not
   measure closer is left as it was.
3. With --apply, "Song (aligned).rpp" is written next to yours:
   - timing: **stretch markers on the active take of each part's own items**, the fewest that follow the plan within
     half a millisecond (existing stretch markers are followed and replaced by the combined ones). Drag or delete
     any of them in REAPER afterwards.
   - with --takes, the timing goes on new takes too (below) instead of stretch markers. Measured in REAPER 7.86:
     stretch markers land exactly on the plan in varispeed, but with pitch preserved REAPER's stretch engine plays
     the moved stretches about 4 ms late (90% within 9 ms); a new take plays the checked preview exactly.
   - pitch / formant (they can't be stretch markers): each item of that part gets a **new take**, made active, that
     plays a file rendered for that item (timing, then pitch, then formant). The original take stays on the item:
     switch takes to compare. The files go in "<project folder>/hypnomix aligned/".
   Nothing else in the project changes, and the new project is checked against yours (every track, item position
   and length, folder and send kept; only takes added) before it is kept.

Your project is never written. One tempo is assumed (a tempo map is refused). Items that loop their source and
MIDI items are left alone and listed.
"""
import json
import sys
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.core.paths import out_at
from hypnomix.studio import alignopts as AO
from hypnomix.studio import vocalign as V

SR = 44100
FR_S = V.FR_S
MIN_SPEED = 0.25          # stretch markers never play slower than this (and never backwards)
VOCAL_WORDS = r"vox|vocal|voice|harm|double|dbl|bgv|backing|choir|adlib|ad-lib"


# ---------------------------------------------------------------- the take's time map
def take_source(c, take_t):
    """Source seconds (within the section, offset included: the SM convention) the active take plays at take time
    take_t (seconds from the item start x rate)."""
    from hypnomix.project.model import stretch_map
    tk = c.take
    take_t = np.asarray(take_t, dtype=float)
    if tk.stretch:
        return stretch_map(tk, take_t)
    return tk.offset + take_t


def item_markers(c, plan, tol_s=0.0005):
    """New stretch markers [(take time, source seconds)] so the item plays, at timeline time T, the audio it played
    at T + plan(T) before. Returns (marks, max error ms), ([], 0) when nothing moves, or (None, why). Where the plan
    would play audio backwards (or slower than MIN_SPEED), or from before the start of the file, it is eased;
    item_markers.eased says by how many ms."""
    from hypnomix.studio.alignset import rdp
    from hypnomix.project.model import Take, stretch_map
    tk = c.take
    T = np.arange(c.start, c.end, 0.005)
    if len(T) < 4:
        return None, "item too short"
    T = np.r_[T, c.end]
    o = np.interp(T, np.arange(len(plan)) * FR_S, plan * FR_S, left=0.0, right=0.0)
    if np.abs(o).max() < 0.0005:
        return [], 0.0
    tau = (T - c.start) * tk.rate
    src = take_source(c, (T + o - c.start) * tk.rate)
    eased = 0.0
    d = MIN_SPEED * np.diff(take_source(c, tau))      # MIN_SPEED of the item's current (unmoved) speed
    if np.any(np.diff(src) <= d):
        # the move changes faster than audio can be slowed down (two neighbouring words moved opposite ways across a
        # short gap: the plan would play the gap backwards). Stretch markers can't, so the change is eased over a
        # little more time there: the mean of the closest forward and backward paths that never go slower than
        # MIN_SPEED (both follow the plan wherever it is not too steep)
        want = src.copy()
        fwd, bwd = src.copy(), src.copy()
        for i in range(1, len(fwd)):
            fwd[i] = max(fwd[i], fwd[i - 1] + d[i - 1])
        for i in range(len(bwd) - 2, -1, -1):
            bwd[i] = min(bwd[i], bwd[i + 1] - d[i])
        src = (fwd + bwd) / 2
        eased = float(np.abs(src - want).max() / tk.rate * 1000)
    if src[0] < 0:
        # the plan wants audio from before the file starts (an item that begins at the file's first sample, pulled
        # later): start at the first sample and catch up with the plan, never slower than MIN_SPEED (the same rule
        # as Live's alignset)
        want = src.copy()
        src[0] = 0.0
        for i in range(1, len(src)):
            src[i] = max(src[i], src[i - 1] + d[i - 1])
        eased = max(eased, float(np.abs(src - want).max() / tk.rate * 1000))
    keep = rdp(tau, src, tol_s * tk.rate)
    marks = [(float(a), float(b)) for a, b in zip(tau[keep], src[keep])]
    if any(b[0] <= a[0] + 1e-6 or b[1] <= a[1] + 1e-6 for a, b in zip(marks, marks[1:])):
        return None, "the stretch markers would cross: left as it was"
    chk = Take(name="", stretch=marks, rate=tk.rate)
    err = np.abs(stretch_map(chk, tau) - src).max() / tk.rate * 1000
    item_markers.eased = eased
    return marks, float(err)


def fixable(c):
    """None when this item can take stretch markers / a new take, else why not."""
    tk = c.take
    if tk is None or tk.kind != "audio" or tk.path is None:
        return "not an audio item"
    if not Path(tk.path).exists():
        return "its file is missing"
    if c.loop:
        import soundfile as sf
        try:
            dur = sf.info(str(tk.path)).duration
        except Exception:
            dur = len(dsp.load(tk.path)[0]) / SR
        end_src = float(take_source(c, [c.length * tk.rate])[0])
        top = (tk.section[1] if tk.section else dur - 0.0)
        if end_src > top + 1e-3:
            return "the item loops its source: unloop it (or glue it) first"
    return None


# ---------------------------------------------------------------- pitch / formant files for one item
def item_window(c, N, sr):
    """The item's gain over the timeline (item x take volume, fades), N samples from 0."""
    from hypnomix.project.model import fade_window
    w = np.zeros(N)
    i0, n = int(round(c.start * sr)), int(round(c.length * sr))
    seg = fade_window(c, n, sr) * c.level
    a, b = max(0, i0), min(N, i0 + n)
    if b > a:
        w[a:b] = seg[a - i0:b - i0]
    return w


def item_files(track, final, sr, out_dir, label):
    """Split a part's final render (timing + pitch / formant, as heard) into one file per item, so that a new take on
    each item, played through the item's own volume and fades, sums back to exactly that render. Returns
    {id(clip): path}. Where items overlap, each gets its share (w_i / sum of w^2), so crossfades still add up."""
    y = final.mean(1) if final.ndim > 1 else final
    N = len(y)
    items = [c for c in track.clips if not c.muted and fixable(c) is None]
    ws = {id(c): item_window(c, N, sr) for c in items}
    tot = sum((w ** 2 for w in ws.values()), np.zeros(N)) + 1e-4
    out = {}
    out_dir.mkdir(parents=True, exist_ok=True)
    for k, c in enumerate(sorted(items, key=lambda c: c.start), 1):
        a = max(0, int(round(c.start * sr)))
        b = min(N, a + int(round(c.length * sr)))
        seg = y[a:b] * ws[id(c)][a:b] / tot[a:b]
        if c.start < 0:
            seg = np.r_[np.zeros(int(round(-c.start * sr))), seg]
        path = out_dir / f"{track.safe_name} {k:03d} ({label}).wav"
        import soundfile as sf
        sf.write(str(path), seg.astype(np.float32), sr, subtype="FLOAT")   # float: a fade's edge can exceed 1
        out[id(c)] = path
    return out


# ---------------------------------------------------------------- the run
def run(a, defaults=None):
    from hypnomix.core import tmp as TMP
    with TMP.scope():                      # the renders it makes (hypnomix-alignset-…) are removed when it ends
        return _run(a, defaults)


def _run(a, defaults=None):
    from hypnomix import project
    from hypnomix.project import rpp_edit as E
    src = Path(a.set).expanduser().resolve()
    p = project.load(src)
    if p.tempo_changes:
        sys.exit("this project has a tempo map: alignset assumes one tempo (use vocalign on exported files instead)")
    tracks = p.audio_tracks(include_off=True)
    pick = lambda n: next((t for t in tracks if t.name.lower() == n.lower()), None) or \
        next((t for t in tracks if t.name.lower().startswith(n.lower())), None)
    guide = pick(a.guide)
    parts = []
    for t in (pick(n) for n in a.parts):
        if t is not None and t is not guide and all(t is not x for x in parts):
            parts.append(t)
    if guide is None or not parts:
        sys.exit(f"need a guide track and at least one other part (found guide {guide.name if guide else None!r}, "
                 f"parts {[t.name for t in parts]})")
    spb = 60.0 / p.tempo
    bpb = p.beats_per_bar
    end = max(c.end for t in [guide] + parts for c in t.clips)
    N = int((end + 1.0) * SR)
    od = out_at(a.out, "alignset")
    warn, files = [], {}
    from hypnomix.core import tmp as TMP
    tmp = TMP.scratch("alignset")
    for t in [guide] + parts:
        print(f"rendering {t.name} from the project …", file=sys.stderr)
        y = p.render(t, SR, end, warn)[:N]
        y = np.pad(y, (0, max(0, N - len(y))))
        files[t.name] = dsp.save(tmp / f"{t.safe_name}.wav", y[:, None], SR, 24)
    span = None
    if a.bars:
        b0, b1 = (float(x) for x in a.bars.split("-"))
        span = ((b0 - 1) * bpb * spb, b1 * bpb * spb)
    elif a.range:
        span = AO.ranges([a.range])[0]
    prot = AO.ranges(a.protect)
    if span:
        prot = sorted(AO.ranges([f"0-{span[0]:.3f}"] if span[0] > 0 else []) + prot + [(span[1], N / SR + 1)])
    a._protect, a._sync = prot, AO.syncs(a.sync)
    md_chords = ""
    if (a.pitch or a.vibrato) and not (a.chords or a.ref or a.no_chord_check):
        import re
        voc = re.compile(VOCAL_WORDS, re.I)
        inst = [t for t in p.audio_tracks() if not voc.search(t.name) and all(t is not x for x in [guide] + parts)]
        if not inst:
            sys.exit("pitch matching needs the chord under each note: this project has no instrument audio tracks to "
                     "read it from. Pass --chords INSTRUMENTAL.wav (or --no-chord-check)")
        print(f"rendering the instruments for the chord check ({len(inst)} tracks) …", file=sys.stderr)
        mix = np.zeros(N)
        for t in inst:
            y = p.render(t, SR, end, warn)[:N]
            mix[:len(y)] += y
        a.chords = str(dsp.save(tmp / "instruments.wav", mix[:, None] * 0.5, SR, 24))
        md_chords = (f"Chord check: the project's own instrument tracks ({', '.join(t.name for t in inst)}); "
                     "MIDI tracks are not heard.")
    a.lead, a.overdubs = str(files[guide.name]), [str(files[t.name]) for t in parts]
    md, outs = (["# Align in the project", "", "Timing step skipped (--no-timing)."], {}) if a.no_timing \
        else V.timing_stage(a, od)
    plans = dict(getattr(V, "_last_plans", {}))
    md[0] = f"# Align in the project: {src.name}"
    md[1:1] = ["", f"Guide: **{guide.name}**; parts: {', '.join(t.name for t in parts)}"
               + (f"; bars {a.bars}" if a.bars else "") + (f"; preset {a.preset}" if a.preset else "")
               + f". {p.tempo:g} BPM."] + (["", md_chords] if md_chords else [])
    result = dict(set=str(src), daw="reaper", guide=guide.name, parts=[], out_set=None, previews={}, rendered={},
                  takes={}, report=str(od / "ALIGNSET.md"))
    timing_outs = dict(outs)
    # pitch / formant after the timing (the final files: timing, then pitch, then formant)
    pf = V.pitch_and_formant(a, od, outs) if (a.pitch or a.vibrato or a.formant or a.transpose) else []
    edited = 0
    md += ["", "## Stretch markers and takes on your items", ""]
    files_dir = src.parent / "hypnomix aligned"
    for t in [guide] + parts:                    # in stack mode the guide is nudged toward the group too
        f = str(files[t.name])
        plan = plans.get(f)
        final = outs.get(f)
        rendered = final if final and (final != timing_outs.get(f) or getattr(a, "takes", False)) else None
        if t is guide and plan is None and rendered is None:
            continue
        row = dict(track=t.name, items=0, markers=0, takes=0, skipped=[], preview=timing_outs.get(f))
        result["previews"][t.name] = timing_outs.get(f)
        if plan is None and rendered is None:
            row["skipped"].append("not measurably closer (or nothing to move): its items are left as they are")
            md.append(f"- {t.name}: left as it was (the aligned version did not measure closer to the guide)")
            result["parts"].append(row)
            continue
        if rendered:                             # pitch / formant: a new take per item, playing its share of the file
            result["rendered"][t.name] = rendered
            if a.apply is not None:
                y, sr = dsp.load(rendered, SR)
                label = Path(rendered).stem.split("(", 1)[-1].rstrip(")")
                per = item_files(t, y, SR, files_dir, label)
                for c in t.clips:
                    if id(c) in per:
                        E.add_take(c, per[id(c)], f"{c.take.name or t.name} ({label})", offset=0.0, rate=1.0)
                        row["takes"] += 1
                for c in t.clips:
                    why = fixable(c) if not c.muted else None
                    if why:
                        row["skipped"].append(f"item at {c.start:.2f} s: {why}")
                result["takes"][t.name] = [str(x) for x in per.values()]
                edited += row["takes"]
            md.append(f"- {t.name}: " + (f"a new take on {row['takes']} item(s), playing the {label} render "
                                         "(the original take stays: switch takes to compare)" if a.apply is not None
                                         else f"rendered with {Path(rendered).stem.split('(', 1)[-1].rstrip(')')}: "
                                              "--apply puts it on the items as new takes")
                      + ("; skipped: " + "; ".join(row["skipped"]) if row["skipped"] else ""))
            result["parts"].append(row)
            continue
        for c in t.clips:
            if c.muted:
                continue
            seg = plan[max(0, int(c.start / FR_S)):int(c.end / FR_S) + 1]
            if not len(seg) or np.abs(seg).max() * FR_S < 0.0005:
                continue
            why = fixable(c)
            if why:
                row["skipped"].append(f"item at {c.start:.2f} s: {why}"); continue
            marks, info = item_markers(c, plan)
            if marks is None:
                row["skipped"].append(f"item at {c.start:.2f} s: {info}"); continue
            if not marks:
                continue
            E.set_stretch(c, marks)
            row["items"] += 1
            row["markers"] += len(marks)
            row["max_err_ms"] = max(row.get("max_err_ms", 0.0), info)
            if getattr(item_markers, "eased", 0.0) > 0.5:
                row["eased_ms"] = max(row.get("eased_ms", 0.0), item_markers.eased)
        edited += row["items"]
        md.append(f"- {t.name}: {row['markers']} stretch markers on {row['items']} item(s)"
                  + (f"; within {row['max_err_ms']:.2f} ms of the plan" if row.get("max_err_ms") is not None else "")
                  + (f" (eased by up to {row['eased_ms']:.0f} ms where the move changed faster than audio can be "
                     "slowed, or wanted audio from before the file starts)" if row.get("eased_ms") else "")
                  + ("; skipped: " + "; ".join(row["skipped"]) if row["skipped"] else ""))
        result["parts"].append(row)
    if pf:
        md += pf
    if a.apply is not None and edited:
        out = Path(a.apply) if a.apply else src.with_name(src.stem + " (aligned).rpp")
        k = 2
        while out.exists() or out.resolve() == src:
            out = src.with_name(src.stem + f" (aligned {k}).rpp"); k += 1
        if not out.is_absolute():
            out = src.parent / out
        E.save(p, out)
        errs = E.check(src, out)
        if errs:
            bad = out.with_name(out.stem + " (FAILED check).rpp")
            out.replace(bad)
            md += ["", f"The new project failed the structure check and was renamed `{bad.name}` (do not open it):",
                   *[f"- {e}" for e in errs]]
        else:
            result["out_set"] = str(out)
            md += ["", f"New project: `{out.name}` (next to yours; yours is unchanged). Open it in REAPER: the "
                       "stretch markers show on the items, and new takes are active (the originals are still there)."]
    elif edited or (a.apply is None and (plans or result["rendered"])):
        md += ["", "Measured only: run again with --apply to write the new project."]
    else:
        md += ["", "Nothing to write: every part is left as it was."]
    if warn:
        md += ["", "Warnings:", *[f"- {w}" for w in dict.fromkeys(warn)]]
    from hypnomix.studio.alignset import energy
    result["energy"] = energy([guide.name] + [t.name for t in parts], files, timing_outs if not result["rendered"]
                              else {k: v for k, v in outs.items()}, span or (0.0, N / SR))
    (od / "ALIGNSET.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    result["markdown"] = "\n".join(md)
    if a.json:
        Path(a.json).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print("\n".join(md))
    return result
