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
  vocal tuning (tune)     the rendered vocal against the tuned one, around the first flagged note
  repaired recordings     de-hiss, clean-up, de-ess, breaths, prep steps: the file against the repaired copy
What cannot (said in ab.json and on the review page):
  timing nudges           several warp markers in one clip are not rendered exactly offline
  device changes          distortion and sidechain fixes change effects, which only Live can play
For those, apply the one fix into a new set (`hypnomix fix ... --approve ID`) and listen in Live.

  --plugins   device changes too (devices, duck, sidechain, distortion), when pedalboard is installed: the
              track is rendered through its real plug-ins and hypnomix's models of Live's devices, in the set as
              it is and with only that fix applied (see `hypnomix plugrender`; no sends, so return tracks can't
              be previewed). Without pedalboard, or without --plugins, nothing changes.

The preview is the track on its own, without effects: it shows what the fix does, not the final sound.
"""
import argparse, json, re, shutil, subprocess, sys, tempfile
from pathlib import Path

import numpy as np
import soundfile as sf


def hx(*args, timeout=3600):
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True,
                       timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def safe(s):
    return re.sub(r'[\\/:*?"<>|]', "-", str(s))


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


def write_pair(od, fid, a, b, sr, note=""):
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
    data = json.loads((sd / "findings.json").read_text())
    scan = json.loads((sd / "scan.json").read_text()) if (sd / "scan.json").exists() else {}
    want = {x.strip() for x in a.ids.split(",") if x.strip()}
    findings = [f for f in data["findings"] if f.get("applies") in ("set", "audio") and (not want or f["id"] in want)]
    od = sd / "ab"
    od.mkdir(exist_ok=True)
    mp = od / "ab.json"
    manifest = json.loads(mp.read_text()) if mp.exists() else {}
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
                    manifest[f["id"]] = dict(note="preview failed: the fix could not be built (" + txt.strip()[-120:] + ")")
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

    # ---- device changes through the track's real chain (--plugins, needs pedalboard): hypnomix plugrender
    done = set()
    if a.plugins and orig and orig.exists():
        from hypnomix.session import plugrender as PR
        if not PR.have_pedalboard():
            print("--plugins: pedalboard is not installed (pip install pedalboard): device changes are not previewed")
        else:
            cache = {}
            for f in [f for f in findings if f["tool"] in PR.DEVICE_TOOLS and f.get("applies") == "set"]:
                print(f"rendering {f.get('host') or f.get('track')} through its chain for {f['id']} …")
                before, after, note = PR.device_preview(f, orig, scan, sd, sr, hx, cache)
                if before is None:
                    manifest[f["id"]] = dict(note=note)
                else:
                    t = PR.loudest_at(before, sr, a.pre + a.post)
                    manifest[f["id"]] = write_pair(od, f["id"], cut(before, sr, t, a.pre, a.post),
                                                   cut(after, sr, t, a.pre, a.post), sr, note)
                done.add(f["id"])

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
            with tempfile.TemporaryDirectory() as td:
                code, txt = hx(*[str(x).replace("{out}", td) for x in f["run"]])
                made = sorted(Path(td).glob("*.wav"), key=lambda p: p.stat().st_mtime)
                src = next((Path(x) for x in f["run"][1:] if Path(str(x)).is_file()), None)
                if code != 0 or not made or src is None:
                    manifest[fid] = dict(note="preview failed: " + txt.strip()[-160:])
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
            with tempfile.TemporaryDirectory() as td:
                dest = Path(td) / "tuned.wav"
                args = ["tune", rendered, dest, "--key", key]
                if scan.get("ref"):
                    args += ["--ref", scan["ref"]]
                code, txt = hx(*args)
                if code != 0 or not dest.exists():
                    manifest[fid] = dict(note="preview failed: " + txt.strip()[-160:])
                    continue
                ya, sra = sf.read(str(rendered), dtype="float32", always_2d=True)
                yb, srb = sf.read(str(dest), dtype="float32", always_2d=True)
                first = (f.get("flagged_notes") or [{}])[0].get("time")
                t = secs_of(first)
                t = loud_start(ya, sra) + 2 if t is None else t
                note = "" if scan.get("key") else f"uses the estimated key ({key}): confirm it before approving"
                manifest[fid] = write_pair(od, fid, cut(ya.mean(1), sra, t, 3, 7), cut(yb.mean(1), srb, t, 3, 7), sra, note)
            continue
        if f["tool"] == "timing":
            manifest[fid] = dict(note="no offline preview: warp nudges are not rendered exactly outside Live. Apply this "
                                      "one fix into a new set (fix --approve) and listen there.")
        elif fid not in manifest:
            manifest[fid] = dict(note="no offline preview: this changes an effect, which only Live can play. Apply this "
                                      "one fix into a new set (fix --approve) and listen there.")
    mp.write_text(json.dumps(manifest, indent=1))
    pairs = sum(1 for v in manifest.values() if v.get("a"))
    print(f"{pairs} before/after pair(s) in {od}; {len(manifest) - pairs} finding(s) without a preview (see ab.json)")
    print(f"next: hypnomix review \"{sd}\"   (a page with play buttons and approve / skip)")


if __name__ == "__main__":
    main()
