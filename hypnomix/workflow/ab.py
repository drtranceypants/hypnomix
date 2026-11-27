#!/usr/bin/env python3
"""Hear a proposed fix before you approve it: a short before / after pair for every finding that can be
previewed, at matched loudness (the louder one always sounds better, so the pair is level-matched).

  hypnomix ab SCAN_DIR [--ids ID,ID,...] [--pre 2] [--post 4]

Writes SCAN_DIR/ab/<id> A (now).wav and <id> B (fixed).wav, plus ab.json (which pairs exist, and why the
others don't). Nothing in the project or the source audio is changed: the "fixed" version is built in a
temporary copy of the set that is deleted afterwards. `hypnomix review` puts play buttons on each pair.

What can be previewed without Live:
  clip fixes (smooth)     clicks, cuts, spikes, steps: the track is rendered from the set with and without the
                          fix (clip gain, fades and the track's volume automation; no devices)
  vocal tuning (tune)     the rendered vocal against the tuned one, around the first flagged note. Tuning checks the
                          chord under every note first, as `fix` does: it needs the scan's instrumental (scan
                          --backing INSTRUMENTAL.wav) or mix (--ref); without one the pair says to scan again
  repaired recordings     de-hiss, clean-up, de-ess, breaths, prep steps: the file against the repaired copy
  timing nudges           the clip rendered along its warp markers (the markers the nudge writes, one on every onset
                          it holds and one on the hit it moves), stretched with Rubber Band so the pitch stays, the
                          same way before and after, around the nudge. Needs Rubber Band (brew install rubberband).
                          Not Live's own warp engine: the timing is exact, the stretched stretch can sound a little
                          different. A nudge of a MIDI note is refused (the instrument is not rendered offline).
  device changes          a change to a Compressor, Glue Compressor, Gate, EQ Eight, Utility or Limiter setting
                          (devices, sidechain, distortion fixes): the track played through HypnoMix's MODEL of the
                          device, in the set as it is and with only that fix applied. The pair is labelled "a model
                          of the device, not Live itself" in ab.json and on the review page.
  masking cuts            the two parts that fight, summed, with and without the cut (a model of an EQ Eight band)
What cannot (said in ab.json and on the review page, with the reason):
  a device with no model  Saturator, Reverb, Delay, racks, Max for Live devices, real plug-ins (without --plugins),
                          EQ Eight in L/R or M/S mode, a Gate listening to a sidechain: apply that one fix into a new
                          set (`hypnomix fix ... --approve ID`) and listen in Live.
  return tracks, sends    fixes whose effect is on a return track or a send are not rendered.
  REAPER projects         `ab` plays Live sets; for a project apply the one fix into a new .rpp and listen there.

  --plugins   also play the REAL plug-ins in the chain (VST3 / Audio Units), when pedalboard is installed (see
              `hypnomix plugrender`; no sends, so return tracks can't be previewed). Without it, plug-ins are left
              out of the chain and the pair says so.

Clip, tuning and timing previews are the track on its own, without effects; device previews are the track
through its chain, without sends. Either way a pair shows what the fix does, not the final sound.
"""
from hypnomix.core import atomic
from hypnomix.extras import hint as extra_hint
import argparse, json, re, shutil, subprocess, sys, tempfile
from pathlib import Path

import numpy as np
import soundfile as sf


def hx(*args, timeout=3600):
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def safe(s):
    return re.sub(r'[\\/:*?"<>|]', "-", str(s))


NEEDS_BACKING = ("tuning checks the chord under every note first, and this scan has no instrumental to read the chords "
                 "from: scan again with --backing INSTRUMENTAL.wav (the song without the vocals)")


def why_failed(txt, limit=160):
    """The last line a failed command said, as one plain phrase (never the tail of a path cut mid-word). The tune
    command's own advice is about flags `ab` does not have, so that one is turned into what to do here."""
    from hypnomix.workflow.fix import last_line
    if "without checking the chord" in (txt or ""):
        return NEEDS_BACKING
    return last_line(txt, limit) or "the command gave no reason"


def beats_of(where, bpb):
    """'33.3.00' (bar.beat.hundredths) -> beats from the start. None if it is not a bar position."""
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", where or "")
    if not m:
        return None
    return (int(m.group(1)) - 1) * bpb + (int(m.group(2)) - 1) + int(m.group(3)) / 100.0


def secs_of(text):
    m = re.match(r"^(\d+):(\d+(?:\.\d+)?)$", str(text or "").strip())
    return int(m.group(1)) * 60 + float(m.group(2)) if m else None


def render_tracks(als, names, sr=44100):
    """{track name: mono float array} from the set: clip gain, fades, straight warps and the track's VOLUME
    AUTOMATION (relative to its first point), no devices. Returns (audio, seconds per beat, beats per bar)."""
    from hypnomix.session import automation as aa
    from hypnomix.session import render as R
    tree = aa.load(als)
    root, bpb = tree.getroot(), aa.BPB
    spb = 60.0 / float(R.v(root, ".//Tempo/Manual"))
    want = {n for n in names}
    pick = [t for t in root.find(".//Tracks") if t.tag == "AudioTrack" and R.v(t, "./Name/EffectiveName") in want]
    ends = [float(R.v(c, "./CurrentEnd")) for t in pick for c in t.iter("AudioClip")]
    if not ends:
        return {}, spb, bpb
    n = int((max(ends) + 4) * spb * sr)
    out, warn = {}, []
    for t in pick:
        name = R.v(t, "./Name/EffectiveName")
        y = R.render_track(t, str(als), spb, n, sr, None, 0, warn)
        envs, _ = aa.envelopes(t)
        vol = next((env for lab, env, _ in envs if lab == "Volume"), None)
        if vol is not None:
            try:
                _, pts = aa.events(vol)
            except ValueError:
                pts = []
            if len(pts) > 1:
                step = int(sr * 0.005)
                tb = np.arange(0, n, step) / sr / spb
                g = np.array([aa.value_at(pts, b) for b in tb])
                base = pts[0][1] or 1.0
                y = y * np.interp(np.arange(n), np.arange(0, n, step), g / base)
        out[name] = y
    return out, spb, bpb


def cut(y, sr, centre_s, pre, post):
    a, b = max(0, int((centre_s - pre) * sr)), min(len(y), int((centre_s + post) * sr))
    seg = np.array(y[a:b], dtype=np.float32)
    k = min(len(seg) // 2, int(0.01 * sr))
    if k:
        ramp = np.linspace(0, 1, k, dtype=np.float32)
        if seg.ndim > 1:
            ramp = ramp[:, None]
        seg[:k] *= ramp
        seg[-k:] *= ramp[::-1]
    return seg


def rms_db(x):
    return 10 * np.log10(float(np.mean(np.square(x))) + 1e-12)


def write_pair(od, fid, a, b, sr, note="", model=False):
    """Level-match B to A (at most 3 dB, so a fix that IS a level change still sounds like one)."""
    g = float(np.clip(rms_db(a) - rms_db(b), -3, 3)) if len(a) and len(b) else 0.0
    b = b * 10 ** (g / 20)
    pk = max(float(np.abs(a).max(initial=0)), float(np.abs(b).max(initial=0)))
    if pk > 0.98:  # both down together, so the comparison stays fair
        a, b = a * 0.98 / pk, b * 0.98 / pk
    fa, fb = od / f"{safe(fid)} A (now).wav", od / f"{safe(fid)} B (fixed).wav"
    sf.write(str(fa), a, sr, subtype="PCM_24")
    sf.write(str(fb), b, sr, subtype="PCM_24")
    changed = float(np.max(np.abs(a[: len(b)] - b[: len(a)]))) if len(a) and len(b) else 0.0
    row = dict(a=fa.name, b=fb.name, matched_db=round(g, 1), seconds=round(len(a) / sr, 1), note=note)
    if model:
        row["model"] = True                  # played through hypnomix's model of the device: the review page says so
    if changed < 1e-4:
        row["note"] = (note + " " if note else "") + "the two files measure the same here: the fix may fall outside this window"
    return row


def loud_start(y, sr):
    """Seconds where the performance starts (first block within 30 dB of the loudest)."""
    m = y.mean(1) if y.ndim > 1 else y
    blk = int(sr * 0.05)
    n = len(m) // blk
    if not n:
        return 0.0
    db = 10 * np.log10((m[: n * blk] ** 2).reshape(n, blk).mean(1) + 1e-12)
    on = np.flatnonzero(db > db.max() - 30)
    return float(on[0] * 0.05) if len(on) else 0.0


def stale(scan, orig):
    """True when the set was saved again after the scan: ids from the scan may point at something else now."""
    was = scan.get("set_mtime")
    return bool(was and orig is not None and orig.exists() and abs(orig.stat().st_mtime - was) > 1)


def timing_args(sd, orig, tmp, ids, unroll):
    """The `timing` command that writes only these nudges into tmp, with the options the scan used."""
    tj = sd / "raw" / "timing.json"
    d = atomic.load_json(tj, {}) or {}
    args = ["timing", orig, "--apply", tmp, "--ids", ",".join(ids), "--list", "0"]
    for t in d.get("tracks", []):
        args += ["--track", t]
    for flag, key in (("--melodic", "melodic"), ("--bass", "bass"), ("--drums", "drums")):
        for t in d.get(key, []):
            args += [flag, t]
    if unroll:
        args += ["--unroll-loops"]
    return args


def preview_timing(tm, orig, scan, sd, pre, post, manifest, sr):
    """Pairs for timing nudges: the clip rendered along its warp markers with and without the nudges. Every nudge
    is applied in ONE temporary set (they sit far apart; when two fall into one window the note says so)."""
    from hypnomix.session import render as R
    todo = []
    for f in tm:
        if "MIDI note" in (f.get("problem") or ""):
            manifest[f["id"]] = dict(note="no offline preview: this moves a MIDI note, and the instrument that plays it "
                                          "is not rendered offline. Apply this one fix into a new set (fix --approve) "
                                          "and listen in Live.")
        else:
            todo.append(f)
    if not todo:
        return
    why = None
    if not shutil.which("rubberband"):
        why = ("no offline preview: nudges are heard by stretching the clip along its warp markers with Rubber Band, "
               "which is not installed (brew install rubberband)")
    elif stale(scan, orig):
        why = "no preview: the set was saved again after the scan, so its ids may point at something else: re-scan"
    if why:
        for f in todo:
            manifest[f["id"]] = dict(note=why)
        return
    tmp = orig.parent / f"{orig.stem} (ab preview timing, delete me).als"
    try:
        code, txt = hx(*timing_args(sd, orig, tmp, [f["id"] for f in todo], any(f.get("unroll") for f in todo)))
        if code != 0 or not tmp.exists():
            for f in todo:
                manifest[f["id"]] = dict(note="preview failed: the nudges could not be built (" + why_failed(txt, 120) + ")")
            return
        names = sorted({f["track"] for f in todo})
        print(f"rendering {len(names)} track(s) along their warp markers with and without {len(todo)} nudge(s) …")
        R.WARP_TIMEMAP[0] = True
        try:
            before, spb, bpb = render_tracks(orig, names, sr)
            after, _, _ = render_tracks(tmp, names, sr)
        finally:
            R.WARP_TIMEMAP[0] = False
    finally:
        if tmp.exists():
            tmp.unlink()
    for f in todo:
        b = beats_of(f.get("where"), bpb)
        y0, y1 = before.get(f["track"]), after.get(f["track"])
        if b is None or y0 is None or y1 is None:
            manifest[f["id"]] = dict(note="no preview: the spot or the track could not be rendered")
            continue
        if not np.any(y0):
            manifest[f["id"]] = dict(note="no preview: the track's audio file could not be read (moved or missing?)")
            continue
        t = b * spb
        near = [g["id"] for g in todo if g is not f and g["track"] == f["track"]
                and abs((beats_of(g.get("where"), bpb) or -1e9) * spb - t) < pre + post]
        note = ("the track alone, no effects; the clip is stretched along its warp markers with Rubber Band (pitch kept), "
                "the same way in A and B: the timing is exact, Live's own warp engine may sound a little different")
        if near:
            note += f"; the nudge(s) {', '.join(near)} on this track also fall in this window and are in B too"
        manifest[f["id"]] = write_pair(od_of(sd), f["id"], cut(y0, sr, t, pre, post), cut(y1, sr, t, pre, post), sr, note)


def od_of(sd):
    return Path(sd) / "ab"


def preview_masking(mk, orig, scan, pre, post, manifest, sd, sr):
    """Pairs for masking cuts: the part that gives way and the part that keeps the band, summed, with and without
    the cut (a bell on the giving part, from HypnoMix's model of an EQ Eight band)."""
    from scipy.signal import lfilter
    from hypnomix.session import devmodel, plugrender as PR
    if stale(scan, orig):
        for f in mk:
            manifest[f["id"]] = dict(note="no preview: the set was saved again after the scan: re-scan")
        return
    names = sorted({n for f in mk for n in (f["track"], f["eq"].get("keep")) if n})
    print(f"rendering {len(names)} track(s) with and without {len(mk)} cut(s) …")
    y, spb, bpb = render_tracks(orig, names, sr)
    for f in mk:
        e = f["eq"]
        g, k = y.get(f["track"]), y.get(e.get("keep"))
        if g is None or k is None:
            manifest[f["id"]] = dict(note="no preview: one of the two parts could not be rendered")
            continue
        n = min(len(g), len(k))
        b_, a_ = devmodel._biquad(3, sr, e["freq"], e["gain_db"], e["q"])
        before = g[:n] + k[:n]
        after = lfilter(b_, a_, g[:n]) + k[:n]
        t = PR.loudest_at(np.minimum(np.abs(g[:n]), np.abs(k[:n])), sr, pre + post)   # where both play
        manifest[f["id"]] = write_pair(od_of(sd), f["id"], cut(before, sr, t, pre, post), cut(after, sr, t, pre, post), sr,
                                       f"'{f['track']}' and '{e.get('keep')}' together, without effects: a model of an EQ "
                                       f"Eight band ({e['gain_db']:+.1f} dB at {e['freq']:.0f} Hz, Q {e['q']:g}) on "
                                       f"'{f['track']}', not Live itself; centred where both play", model=True)


def main():
    ap = argparse.ArgumentParser(prog="hypnomix ab", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scan_dir")
    ap.add_argument("--ids", default="", help="only these finding ids (default: every finding that changes something)")
    ap.add_argument("--pre", type=float, default=2.0, help="seconds before the spot (default 2)")
    ap.add_argument("--post", type=float, default=4.0, help="seconds after the spot (default 4)")
    ap.add_argument("--plugins", action="store_true",
                    help="also preview device changes through the track's plug-in chain (needs pedalboard)")
    a = ap.parse_args()
    sd = Path(a.scan_dir)
    if not sd.exists():
        sys.exit(f"{sd}: no such folder (looked in {Path.cwd()}): give the scan folder `hypnomix scan` wrote")
    data = atomic.load_json(sd / "findings.json", None)            # a cut-off file falls back to findings.json.bak
    if not isinstance(data, dict) or "findings" not in data:
        sys.exit(f"{sd / 'findings.json'} could not be read: scan again (or `hypnomix scan --merge {sd}`)")
    scan = atomic.load_json(sd / "scan.json", {}) or {}
    want = {x.strip() for x in a.ids.split(",") if x.strip()}
    unknown = sorted(want - {f.get("id") for f in data["findings"]})
    if unknown:                                    # the same wording as `fix --approve`
        sys.exit(f"unknown ids: {', '.join(unknown)}")
    findings = [f for f in data["findings"] if f.get("applies") in ("set", "audio") and (not want or f["id"] in want)]
    od = sd / "ab"
    od.mkdir(exist_ok=True)
    mp = od / "ab.json"
    from hypnomix.session import plugrender as PR
    manifest = atomic.load_json(mp, {}) or {}
    folder = scan.get("mode") == "folder"
    orig = Path(data["set"]) if data.get("set") and not folder else None
    sr = 44100

    # ---- clip fixes: one temporary set with every smooth fix, rendered once
    sm = [f for f in findings if f["tool"] == "smooth" and f.get("applies") == "set"]
    if sm and orig and orig.exists():
        tmp = orig.parent / f"{orig.stem} (ab preview, delete me).als"
        try:
            ids = sorted({i for f in sm for i in (f.get("ids") or [f["id"]])})
            code, txt = hx("smooth", orig, "--apply", tmp, "--ids", ",".join(ids))
            if code != 0 or not tmp.exists():
                for f in sm:
                    manifest[f["id"]] = dict(note="preview failed: the fix could not be built (" + why_failed(txt, 120) + ")")
            else:
                names = sorted({f["track"] for f in sm})
                print(f"rendering {len(names)} track(s) with and without {len(sm)} clip fix(es) …")
                before, spb, bpb = render_tracks(orig, names, sr)
                after, _, _ = render_tracks(tmp, names, sr)
                for f in sm:
                    b = beats_of(f.get("where"), bpb)
                    if b is None or f["track"] not in before or f["track"] not in after:
                        manifest[f["id"]] = dict(note="no preview: the spot or the track could not be rendered")
                        continue
                    t = b * spb
                    manifest[f["id"]] = write_pair(od, f["id"], cut(before[f["track"]], sr, t, a.pre, a.post),
                                                   cut(after[f["track"]], sr, t, a.pre, a.post), sr,
                                                   "the track alone, no effects")
        finally:
            if tmp.exists():
                tmp.unlink()

    # ---- device changes: the track through hypnomix's MODELS of Live's devices (and, with --plugins, real plug-ins)
    done = set()
    live_set = bool(orig and orig.exists() and orig.suffix.lower() == ".als")
    dev = [f for f in findings if f["tool"] in PR.DEVICE_TOOLS and f.get("applies") == "set"]
    if dev and live_set and a.plugins and not PR.have_pedalboard():
        print(f"--plugins: pedalboard is not installed ({extra_hint('plugins')}): real plug-ins are left out of the chain")
    if dev and live_set:
        cache = {}
        for f in dev:
            if stale(scan, orig):
                manifest[f["id"]] = dict(note="no preview: the set was saved again after the scan, so its ids may point "
                                              "at something else: re-scan")
                done.add(f["id"])
                continue
            print(f"rendering {f.get('host') or f.get('track')} through its chain for {f['id']} …")
            r = PR.device_preview(f, orig, scan, sd, sr, hx, cache, plugins=a.plugins)
            if r.get("before") is None:
                manifest[f["id"]] = dict(note=r["note"])
            else:
                t = PR.loudest_at(r["before"], sr, a.pre + a.post)
                manifest[f["id"]] = write_pair(od, f["id"], cut(r["before"], sr, t, a.pre, a.post),
                                               cut(r["after"], sr, t, a.pre, a.post), sr, r["note"], model=r["model"])
            done.add(f["id"])

    # ---- timing nudges: the clip rendered along its warp markers, with and without the nudges
    tm = [f for f in findings if f["tool"] == "timing" and f.get("applies") == "set"]
    if tm and live_set:
        preview_timing(tm, orig, scan, sd, a.pre, a.post, manifest, sr)
        done |= {f["id"] for f in tm}

    # ---- masking cuts: the two parts together, with and without the cut
    mk = [f for f in findings if f["tool"] == "masking" and f.get("eq") and f.get("applies") == "set"]
    if mk and live_set:
        preview_masking(mk, orig, scan, a.pre, a.post, manifest, sd, sr)
        done |= {f["id"] for f in mk}

    # ---- everything else
    for f in findings:
        fid = f["id"]
        if (f["tool"] == "smooth" and fid in manifest) or fid in done:
            continue
        if f.get("plan"):
            manifest[fid] = dict(note="no single preview: approve the moves you want, apply, then compare the result "
                                      "file with the original")
            continue
        if f.get("run"):
            with tempfile.TemporaryDirectory(prefix="hypnomix-work-") as td:
                code, txt = hx(*[str(x).replace("{out}", td) for x in f["run"]])
                made = sorted(Path(td).glob("*.wav"), key=lambda p: p.stat().st_mtime)
                src = next((Path(x) for x in f["run"][1:] if Path(str(x)).is_file()), None)
                if code != 0 or not made or src is None:
                    manifest[fid] = dict(note="preview failed: " + (why_failed(txt) if code != 0 else
                                         "the recording is gone (moved?)" if src is None else "the tool wrote no file"))
                    continue
                ya, sra = sf.read(str(src), dtype="float32", always_2d=True)
                yb, srb = sf.read(str(made[-1]), dtype="float32", always_2d=True)
                if yb.shape[1] != ya.shape[1]:
                    ya, yb = ya.mean(1, keepdims=True), yb.mean(1, keepdims=True)
                t = loud_start(ya, sra)
                manifest[fid] = write_pair(od, fid, cut(ya, sra, t, min(a.pre + 2, 4), a.post + 4),
                                           cut(yb, srb, t, min(a.pre + 2, 4), a.post + 4), sra)
            continue
        if f["tool"] == "tune" and orig:
            rendered = sd / "raw" / "renders" / f"{safe(f['track'])}.wav"
            key = scan.get("key") or f.get("key")
            if not rendered.exists() or not key:
                manifest[fid] = dict(note="no preview: the rendered vocal or the key is missing")
                continue
            backing = scan.get("backing")             # the chord check `fix` makes: the instrumental, else the mix
            if not backing and not scan.get("ref"):
                manifest[fid] = dict(note="no preview: " + NEEDS_BACKING)
                continue
            with tempfile.TemporaryDirectory(prefix="hypnomix-work-") as td:
                dest = Path(td) / "tuned.wav"
                args = ["tune", rendered, dest, "--key", key]
                if backing:
                    args += ["--chords", backing]
                if scan.get("ref"):
                    args += ["--ref", scan["ref"]]
                code, txt = hx(*args)
                if code != 0 or not dest.exists():
                    manifest[fid] = dict(note="preview failed: " + why_failed(txt))
                    continue
                ya, sra = sf.read(str(rendered), dtype="float32", always_2d=True)
                yb, srb = sf.read(str(dest), dtype="float32", always_2d=True)
                first = (f.get("flagged_notes") or [{}])[0].get("time")
                t = secs_of(first)
                t = loud_start(ya, sra) + 2 if t is None else t
                note = "" if scan.get("key") else f"uses the estimated key ({key}): confirm it before approving"
                manifest[fid] = write_pair(od, fid, cut(ya.mean(1), sra, t, 3, 7), cut(yb.mean(1), srb, t, 3, 7), sra, note)
            continue
        if orig is not None and orig.suffix.lower() == ".rpp":
            manifest[fid] = dict(note="no offline preview: `ab` plays Live sets. Apply this one fix into a new project "
                                      "(fix --approve) and listen there, or build the A/B project with `hypnomix abset`.")
        elif fid not in manifest:
            manifest[fid] = dict(note="no offline preview: this kind of fix has no model here. Apply this one fix into "
                                      "a new set (fix --approve) and listen there.")
    atomic.write_json(mp, manifest)
    pairs = sum(1 for v in manifest.values() if v.get("a"))
    print(f"{pairs} before/after pair(s) in {od}; {len(manifest) - pairs} finding(s) without a preview (see ab.json)")
    print(f"next: hypnomix review \"{sd}\"   (a page with play buttons and approve / skip)")


if __name__ == "__main__":
    main()
