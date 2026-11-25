"""`hypnomix fix` for a REAPER project: approved findings into ONE new .rpp next to the original.

Called by `fix` when the scan was of an .rpp. In one pass, on the parsed project:

  clicks  a short item fade (never shortens a fade that is there)
  cuts    short fades either side of the cut, and a volume ease on the track that takes part of the jump away and
          returns to normal (note `method=item` sets the item's volume instead; `amount=0.3`, `ease-ms=500`)
  spikes  a quick dip in the track's volume envelope over the burst (note `amount=` scales it)
  tune    each take file the track plays is pitch-corrected into <project>/Tuned/ (a new file, never over one) and
          added to its items as a NEW TAKE, made active. Your comp stays exactly as it was (positions, edges, fades,
          volumes); the original take is still on every item: switch takes to A/B.

Safety: every approved finding is found again in the project by its item (GUID, else track + position); if it is
not there it is skipped and reported. The new file is read back and checked (same tracks, folders, items, positions
and lengths; takes only added); a failing file is renamed "(BROKEN, do not open)". Afterwards the clip checks run
again on the new project and say which approved problems are no longer measured.

REAPER can stay open; open the new .rpp when it is written (File > Open, or drag it in).
"""
import json
import shutil
from pathlib import Path

from hypnomix import project as PJ
from hypnomix.project import rpp_edit as E


def _kv(dec, f):
    note = ((dec.get(f["id"]) or {}).get("note") or "")
    return dict(x.split("=", 1) for x in note.replace(",", " ").split() if "=" in x)


def apply_edits(p, items, dec, log, failed, skipped):
    """Apply each approved finding's edit to the loaded project p. Returns the ids applied."""
    done = []
    for f in sorted(items, key=lambda f: (f.get("edit", {}).get("op") != "fade", f["id"])):   # fades first
        ed = f.get("edit")
        if not ed:
            skipped.append((f, "no project edit recorded for this finding (manual)"))
            continue
        kv = _kv(dec, f)
        hit = E.locate(p, ed["item"]) if "item" in ed else None
        tr = hit[0] if hit else (p.track(f["track"]) if ed["op"] == "dip" else None)
        if tr is None or tr.name != f["track"]:
            tr = next((t for t in p.tracks if t.name == f["track"]), None)
        if tr is None or (ed["op"] in ("fade", "cut") and hit is None):
            skipped.append((f, "its item or track is no longer in the project (changed since the scan?)"))
            continue
        try:
            amount = float(kv.get("amount", ed.get("amount", 0.5)))
            if ed["op"] == "fade":
                ch = E.fade(hit[1], ed["which"], float(kv.get("fade-ms", ed["seconds"] * 1000)) / 1000)
                log.append(f"- {f['id']}: {tr.name} @ {hit[1].start:.3f} s: fade {ed['which']} "
                           + ("set" if ch else "already long enough, left as it was"))
            elif ed["op"] == "cut":
                prev = E.locate(p, ed["prev"]) if ed.get("prev") else None
                fs = float(kv.get("fade-ms", ed.get("fade", 0.005) * 1000)) / 1000
                if prev:
                    E.fade(prev[1], "out", fs)
                E.fade(hit[1], "in", fs)
                if kv.get("method") == "item":
                    E.item_volume(hit[1], -ed["size"] * amount)
                    log.append(f"- {f['id']}: {tr.name} @ {ed['t']:.3f} s: item volume {-ed['size'] * amount:+.1f} dB, "
                               f"{fs * 1000:.0f} ms fades at the cut")
                else:
                    ease_s = float(kv.get("ease-ms", ed.get("ease", 0.3) * 1000)) / 1000
                    E.ease(tr, ed["t"], ed["size"], amount, ease_s)
                    log.append(f"- {f['id']}: {tr.name} @ {ed['t']:.3f} s: ease of {-ed['size'] * amount:+.1f} dB back "
                               f"to normal over {ease_s * 1000:.0f} ms, {fs * 1000:.0f} ms fades at the cut")
            elif ed["op"] == "dip":
                db = float(ed["db"]) * (amount / 0.5)
                E.dip(tr, ed["t0"], ed["t1"], db, ed.get("ramp", 0.02))
                log.append(f"- {f['id']}: {tr.name} {ed['t0']:.3f}-{ed['t1']:.3f} s: volume dip {-db:.1f} dB")
            else:
                skipped.append((f, f"unknown edit {ed['op']}"))
                continue
            done.append(f["id"])
        except ValueError as e:
            failed.append(f"{f['id']}: {e}")
    return done


def tune_takes(p, f, key, scan, sd, log, failed):
    """Pitch-correct every take file this track's items play; add each as a new active take."""
    import soundfile as sf
    from hypnomix.studio import chords as CHD
    from hypnomix.workflow.fix import hx, safe_name
    tr = next((t for t in p.tracks if t.name == f["track"]), None)
    if tr is None:
        failed.append(f"{f['id']}: track {f['track']} is no longer in the project")
        return 0
    chord_src = scan.get("backing") or scan.get("ref")
    song_ch = CHD.chroma(chord_src) if chord_src and Path(chord_src).exists() else None
    if song_ch is None:
        failed.append(f"{f['id']}: not tuned: no instrumental or mix in the scan to read the chords from "
                      "(re-scan with --backing INSTRUMENTAL.wav)")
        print(f"tune       REFUSED  {f['track']}: no chord source (scan --backing INSTRUMENTAL.wav)")
        return 0
    by_file = {}
    for c in tr.clips:
        if c.muted or c.kind != "audio" or c.path is None:
            continue
        by_file.setdefault(Path(c.path), []).append(c)
    tdir = Path(p.path).parent / "Tuned"
    tdir.mkdir(exist_ok=True)
    n = 0
    for take, clips in by_file.items():
        if not take.exists():
            failed.append(f"{f['id']}: take file not found: {take.name}")
            continue
        dest, k = tdir / f"{safe_name(take.stem)} (tuned).wav", 1
        while dest.exists():
            k += 1
            dest = tdir / f"{safe_name(take.stem)} (tuned {k}).wav"
        sec0 = lambda c: (c.take.section[0] if c.take.section else 0.0)
        spans = [(c.start, c.end, sec0(c) + c.take.offset, sec0(c) + c.take.offset + c.length * c.take.rate) for c in clips]
        npz = tdir / f"{safe_name(take.stem)} (chords).npz"
        CHD.save(npz, CHD.take_time(song_ch, spans, int(sf.info(str(take)).duration / CHD.HOP_S) + 1))
        code, txt = hx("tune", take, dest, "--key", key, "--chords", npz, *(["--ref", scan["ref"]] if scan.get("ref") else []))
        ok = code == 0 and dest.exists()
        log += [f"### tune {f['track']}, take {take.name}: {'written ' + dest.name if ok else 'FAILED'}", "",
                "```", txt.strip()[-1200:], "```", ""]
        if not ok:
            failed.append(f"{f['id']}: tune failed on take {take.name}")
            continue
        for c in clips:
            E.add_take(c, dest, f"{take.stem} (tuned)")
        n += 1
        print(f"tune       ok  {f['track']}: {take.name} → {dest.name}, a new take on {len(clips)} item(s)")
    return n


def run(sd, scan, src, out, set_items, tune_items, dec, key, verify=True):
    """Returns (out or None, log lines, failed, skipped)."""
    log, failed, skipped = [], [], []
    p = PJ.load(src)
    done = apply_edits(p, set_items, dec, log, failed, skipped)
    print(f"edits      {len(done)} of {len(set_items)} approved written" if set_items else "", end="\n" if set_items else "")
    tuned = 0
    for f in tune_items:
        if not key:
            failed.append(f"{f['id']}: not tuned: confirm the key with the person, then pass --key \"<key>\" "
                          f"(the scan estimated {f.get('key')})")
            print(f"tune       REFUSED  {f['track']}: the key is not confirmed (--key)")
            continue
        if key == "sections":
            failed.append(f"{f['id']}: not tuned: tuning the takes needs one key (--key \"<key>\")")
            continue
        tuned += tune_takes(p, f, key, scan, sd, log, failed)
    if not done and not tuned:
        return None, log, failed, skipped
    E.save(p, out)
    errs = E.check(src, out)
    if errs:
        bad = out.with_name(out.stem + " (BROKEN, do not open).rpp")
        out.rename(bad)
        failed += [f"structure check: {e}" for e in errs]
        log += ["### structure check: FAILED", ""] + [f"- {e}" for e in errs] + [""]
        print(f"check      FAILED: the written project is not sound. Renamed to {bad.name}; keep using the original.")
        return None, log, failed, skipped
    print(f"check      structure OK; wrote {out}")
    log += ["### structure check: OK (same tracks, folders, items, positions and lengths)", ""]
    if verify and done:
        log += verify_clips(out, sd, [f for f in set_items if f["id"] in done])
    return out, log, failed, skipped


def verify_clips(out, sd, items):
    """Run the clip checks on the new project: which approved problems are no longer measured."""
    import argparse
    from hypnomix.workflow import scan_project as SP
    vd = Path(sd) / "raw" / "verify"
    if vd.exists():
        shutil.rmtree(vd)
    (vd / "raw").mkdir(parents=True)
    p = PJ.load(out)
    a = argparse.Namespace(jobs=4)
    R = SP.Renders(p, vd).build(4)
    import numpy as np
    import soundfile as sf
    for name, path in R.files.items():          # renders are raw clips: put the volume envelope on, as heard
        tr_ = p.track(name)
        env = tr_.envelopes.get("Volume")
        if env:
            from hypnomix.project.model import envelope_at
            y, sr = sf.read(str(path), dtype="float32")
            y = y * envelope_at(env, np.arange(len(y)) / sr, "Volume" in getattr(tr_, "fader_envelopes", ()))
            sf.write(str(path), y.astype(np.float32), sr, subtype="FLOAT")
    now, _ = SP.g_clips(p, R, vd, a)
    left = {(f["track"], f["kind"], f["where"]): f for f in now}
    still = [f for f in items if (f["track"], f["kind"], f["where"]) in left]
    sizes = []
    for f in still:
        g = left[(f["track"], f["kind"], f["where"])]
        old_ = next((float(x) for x in __import__("re").findall(r"([+-]?\d+(?:\.\d+)?) dB", f["problem"])), None)
        new_ = next((float(x) for x in __import__("re").findall(r"([+-]?\d+(?:\.\d+)?) dB", g["problem"])), None)
        sizes.append(f"{f['id']} {old_:+.1f} → {new_:+.1f} dB" if old_ is not None and new_ is not None else f["id"])
    line = (f"- clips: {len(items) - len(still)} of {len(items)} approved problems no longer measured"
            + (f"; smaller but still measured: {', '.join(sizes)} (a gentle fix by design: listen there, and approve "
               "again with a note like `amount=0.8` for more)" if still else ""))
    print("verify     " + line[2:])
    (Path(sd) / "raw" / "verify.json").write_text(json.dumps({"still": still, "found": now}, indent=1, default=str))
    return ["### verify (the new project, measured again)", "", line, ""]
