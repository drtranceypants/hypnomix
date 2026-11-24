#!/usr/bin/env python3
"""Apply the findings you approved after `hypnomix scan`, and nothing else.

  hypnomix fix SCAN_DIR --approve ID,ID,...  --out "Song (fixed).als"
  hypnomix fix SCAN_DIR --approve ID --from "Song (fixed 1).als" --out "Song (fixed 2).als"
                                             (one fix at a time, each on top of the last, to hear each)
  hypnomix fix SCAN_DIR --list               (show every finding id)

What happens to each approved finding (see REVIEW.md for the ids):
  set     written into ONE new set next to the original, in this order: distortion parameter fixes,
          sidechain settings, clip fades / volume eases (smooth), warp-marker nudges (timing).
          The original set is never touched; temporary step files are removed at the end.
  audio   tune: the vocal is rendered from the set (clip gain, fades, warps baked in) and pitch-corrected
          into <project>/Samples/Tuned/. Put it on a new track at bar 1 and A/B against the original.
  manual  listed with what to do by hand.
  info    nothing to apply.

Close the set in Live first: Live would overwrite edits on its next save. Every run appends to
SCAN_DIR/fix-log.md (what was applied, what was skipped and why).
"""
import argparse, json, shutil, subprocess, sys, time
from pathlib import Path

ORDER = ["distortion", "sidechain", "smooth", "timing"]


def hx(*args):
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, "\n".join(l for l in out.splitlines() if "Warning" not in l and "warnings.warn" not in l)


def main():
    ap = argparse.ArgumentParser(prog="hypnomix fix", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scan_dir")
    ap.add_argument("--approve", default="", help="comma-separated finding ids (or item numbers) to apply")
    ap.add_argument("--out", help='new set to write, e.g. "Song (fixed).als" (same folder as the original)')
    ap.add_argument("--from", dest="from_set", help="start from this set instead of the scanned one (to apply "
                    "fixes one at a time, each on top of the last); must be in the same folder")
    ap.add_argument("--list", action="store_true", help="list findings and exit")
    a = ap.parse_args()
    sd = Path(a.scan_dir)
    data = json.loads((sd / "findings.json").read_text())
    scan = json.loads((sd / "scan.json").read_text()) if (sd / "scan.json").exists() else {}
    findings = data["findings"]
    if a.list:
        for f in findings:
            print(f"{f['n']:4d}  {f['id']:<22} [{f.get('severity')}] {f.get('applies'):<6} "
                  f"{f['tool']}: {f.get('track') or '-'} {f.get('where', '')}  {str(f.get('problem'))[:80]}")
        return
    want = {x.strip() for x in a.approve.split(",") if x.strip()}
    if not want:
        sys.exit("nothing approved: pass --approve ID,ID,... (see REVIEW.md or --list)")
    by_key = {f["id"]: f for f in findings}
    by_key.update({str(f["n"]): f for f in findings})
    unknown = sorted(w for w in want if w not in by_key)
    if unknown:
        sys.exit(f"unknown ids: {', '.join(unknown)}")
    chosen = {by_key[w]["id"]: by_key[w] for w in want}.values()

    orig = Path(data["set"])
    src = Path(a.from_set).resolve() if a.from_set else orig
    if src.parent != orig.resolve().parent:
        sys.exit(f"--from must be in the same folder as the scanned set ({orig.parent})")
    log = [f"\n## fix run {time.strftime('%Y-%m-%d %H:%M')}", "", f"approved: {', '.join(sorted(f['id'] for f in chosen))}", ""]
    set_items = [f for f in chosen if f.get("applies") == "set"]
    audio_items = [f for f in chosen if f.get("applies") == "audio"]
    manual_items = [f for f in chosen if f.get("applies") in ("manual", "info")]

    if set_items:
        if not a.out:
            sys.exit("approved set changes need --out NEW.als")
        out = Path(a.out)
        if not out.is_absolute():
            out = src.parent / out
        if out.resolve().parent != src.resolve().parent:
            sys.exit(f"--out must be in the same folder as the original ({src.parent})")
        if out.resolve() == src.resolve():
            sys.exit("refusing to overwrite the original set")
        cur, step, temps = src, 0, []
        for tool in ORDER:
            items = [f for f in set_items if f["tool"] == tool]
            if not items:
                continue
            step += 1
            nxt = src.parent / f"{src.stem} (fix step {step}).als"
            temps.append(nxt)
            if tool == "smooth":
                ids = sorted({i for f in items for i in f.get("ids", [f["id"]])})
                code, txt = hx("smooth", cur, "--apply", nxt, "--ids", ",".join(ids))
            elif tool == "timing":
                tj = json.loads((sd / "raw" / "timing.json").read_text())
                args = ["timing", cur, "--apply", nxt, "--ids", ",".join(f["id"] for f in items), "--list", "0"]
                for t in tj["tracks"]:
                    args += ["--track", t]
                code, txt = hx(*args)
            elif tool == "distortion":
                args = ["distortion", cur, "--apply", nxt, "--ids", ",".join(f["id"] for f in items)]
                if scan.get("mix"):
                    args += ["--mix", scan["mix"]]
                code, txt = hx(*args)
            else:  # sidechain: one host at a time
                code, txt, tmp = 0, "", cur
                for k, f in enumerate(items):
                    target = nxt if k == len(items) - 1 else src.parent / f"{src.stem} (fix step {step}.{k}).als"
                    if target != nxt:
                        temps.append(target)
                    extra = ["--glue-to-compressor"] if f.get("glue") else []
                    c, t = hx("sidechain", tmp, "--host", f["host"], "--apply", target, *extra)
                    code, txt, tmp = code or c, txt + t, target
            ok = code == 0 and nxt.exists()
            log += [f"### {tool}: {'applied' if ok else 'FAILED'} ({len(items)} findings)", "", "```",
                    txt.strip()[-2500:], "```", ""]
            print(f"{tool:<11} {'ok' if ok else 'FAILED'}  ({len(items)} findings)")
            if ok:
                cur = nxt
        if cur == src:
            print("no set changes could be applied; see fix-log.md")
        else:
            shutil.copyfile(cur, out)
            print(f"wrote {out}")
        for t in temps:
            if t.exists() and t.resolve() != out.resolve():
                t.unlink()

    for f in audio_items:  # tune: render the take from the set, correct it into the project
        proj = src.parent
        tdir = proj / "Samples" / "Tuned"
        tdir.mkdir(parents=True, exist_ok=True)
        rendered = sd / "raw" / "renders" / f"{f['track']}.wav"
        if not rendered.exists():
            code, txt = hx("render", src, "--tracks", f["track"], "--out", sd / "raw" / "renders")
        dest = tdir / f"{f['track']} (tuned).wav"
        args = ["tune", rendered, dest]
        if scan.get("ref"):
            args += ["--ref", scan["ref"]]
        if f.get("key"):
            args += ["--key", f["key"]]
        code, txt = hx(*args)
        ok = code == 0 and dest.exists()
        log += [f"### tune {f['track']}: {'written' if ok else 'FAILED'}", "", "```", txt.strip()[-1500:], "```", ""]
        print(f"tune       {'ok' if ok else 'FAILED'}  {dest if ok else f['track']}")
        if ok:
            print(f"           put it on a new audio track at bar 1 (warp off), mute the original, A/B")

    if manual_items:
        print("\nby hand (not changed automatically):")
        log += ["### by hand", ""]
        for f in manual_items:
            line = f"- {f['id']} {f.get('track') or ''} {f.get('where', '')}: {str(f.get('fix'))[:300]}"
            print(line)
            log.append(line)
    with open(sd / "fix-log.md", "a") as fh:
        fh.write("\n".join(log) + "\n")
    print(f"\nlog: {sd / 'fix-log.md'}. Close the original in Live, then open the new set.")


if __name__ == "__main__":
    main()
