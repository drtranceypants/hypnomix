#!/usr/bin/env python3
"""Every version `fix` wrote for a song, what went into it, and a way back. Never deletes or overwrites anything.

  hypnomix history SONG_OR_DIR                 list the versions (a scan folder, a song name or its .als)
  hypnomix history SONG_OR_DIR --diff N M      what changed between version N and version M (0 = what v1 started from)
  hypnomix history SONG_OR_DIR --undo N        write a NEW set equal to version N's input (what it started from)
  hypnomix history SONG_OR_DIR --undo-item ID  rebuild the latest version without one approved item: `fix` runs
                                               again with that id left out, into a NEW set
  hypnomix history SONG_OR_DIR --json          the log as JSON

Each `fix` run that applies something is logged in SCAN_DIR/history/history.json: the scan folder, the set it
started from and the new set it wrote, the approved ids with their amounts, the plain-words list of changes
(`hypnomix diff`), and the time. A copy of both sets is kept next to the log (history/vN-input.als,
history/vN-output.als), so `--diff` and `--undo` still work after the files were saved again in Live.
Undo and undo-item are logged as versions too. New sets go next to the original set (its samples are found
from there), with a new name; nothing is ever written over.
"""
import argparse, json, shutil, subprocess, sys, time
from pathlib import Path

from hypnomix.core import atomic
from hypnomix.core.paths import OUT


def hist_dir(sd):
    return Path(sd) / "history"


def load(sd):
    p = hist_dir(sd) / "history.json"
    h = atomic.load_json(p, None)               # a cut-off log falls back to history.json.bak
    return h if isinstance(h, dict) and isinstance(h.get("versions"), list) else {"versions": []}


def save(sd, h):
    hist_dir(sd).mkdir(parents=True, exist_ok=True)
    atomic.write_json(hist_dir(sd) / "history.json", h, default=str)


def free_name(path):
    """path, or 'stem 2.als', 'stem 3.als'... whichever does not exist yet."""
    path = Path(path)
    k, cand = 1, path
    while cand.exists():
        k += 1
        cand = path.with_name(f"{path.stem} {k}{path.suffix}")
    return cand


def log_run(sd, scan, src, out, approved, kind="fix", failed=(), extra=None):
    """Record one run. approved: [{id, amount, tool, kind, track, where}]. Returns the version number."""
    sd = Path(sd)
    h = load(sd)
    n = len(h["versions"]) + 1
    hd = hist_dir(sd)
    hd.mkdir(parents=True, exist_ok=True)
    row = dict(n=n, kind=kind, at=time.strftime("%Y-%m-%d %H:%M:%S"), scan_dir=str(sd.resolve()),
               input=str(src) if src else None, output=str(out) if out else None,
               approved=list(approved), failed=list(failed), changes=None, diff="")
    if src and Path(src).exists() and str(src).endswith(".als"):
        snap = hd / f"v{n}-input.als"
        shutil.copyfile(src, snap)
        row["input_snapshot"] = snap.name
    if out and Path(out).exists() and str(out).endswith(".als"):
        snap = hd / f"v{n}-output.als"
        shutil.copyfile(out, snap)
        row["output_snapshot"] = snap.name
        if src and Path(src).exists():
            try:
                from hypnomix.session import diff as D
                rows = D.diff(src, out)
                row["changes"] = len(rows)
                row["diff"] = D.text(rows)[:20000]
            except Exception as e:
                row["diff"] = f"diff failed: {e}"
    if extra:
        row.update(extra)
    h["versions"].append(row)
    save(sd, h)
    return n


def resolve(arg):
    """A scan folder, a song name (hypnomix-out/scan/<name>) or a set (.als → hypnomix-out/scan/<stem>)."""
    p = Path(arg).expanduser()
    if p.is_dir() and ((p / "history").exists() or (p / "findings.json").exists()):
        return p
    if p.suffix == ".als":
        p = OUT / "scan" / p.stem
    elif not p.is_dir():
        p = OUT / "scan" / arg
    if not p.is_dir():
        sys.exit(f"no scan folder for {arg!r} (looked in {p})")
    return p


def snapshot(sd, v, which):
    name = v.get(f"{which}_snapshot")
    if not name:
        return None
    p = hist_dir(sd) / name
    return p if p.exists() else None


def version_set(sd, h, n):
    """The set of version n (its output); 0 = the input of version 1."""
    vs = h["versions"]
    if n == 0:
        if not vs:
            sys.exit("no versions yet")
        return snapshot(sd, vs[0], "input")
    if not 1 <= n <= len(vs):
        sys.exit(f"no version {n} (versions 1-{len(vs)})")
    return snapshot(sd, vs[n - 1], "output")


def listing(sd, h):
    L = [f"history of {sd}", ""]
    if not h["versions"]:
        return "\n".join(L + ["no versions yet: `hypnomix fix DIR --approved --out NEW.als` logs each run here"])
    for v in h["versions"]:
        items = ", ".join(f"{a['id']}" + (f"@{a['amount']}" if a.get("amount", 100) != 100 else "")
                          for a in v.get("approved", []))
        out = Path(v["output"]).name if v.get("output") else "(no new set)"
        L.append(f"v{v['n']}  {v['at']}  {v['kind']:<9} → {out}")
        L.append(f"     from {Path(v['input']).name if v.get('input') else '-'}"
                 + (f"; {v['changes']} change(s)" if v.get("changes") is not None else ""))
        if items:
            L.append(f"     approved: {items[:400]}")
        if v.get("failed"):
            L.append(f"     FAILED: {'; '.join(v['failed'])[:300]}")
    return "\n".join(L)


def undo(sd, h, n):
    """A new set equal to version n's input, next to the original set."""
    vs = h["versions"]
    if not 1 <= n <= len(vs):
        sys.exit(f"no version {n} (versions 1-{len(vs)})")
    v = vs[n - 1]
    snap = snapshot(sd, v, "input")
    if snap is None:
        sys.exit(f"version {n} kept no copy of its input set; nothing to go back to")
    scan = atomic.load_json(Path(sd) / "scan.json", {}) or {}
    orig = Path(scan.get("set") or v["input"])
    dest = free_name(orig.with_name(f"{orig.stem} (back to v{n} input).als"))
    shutil.copyfile(snap, dest)
    m = log_run(sd, scan, Path(v["input"]) if Path(v["input"]).exists() else snap, dest, [], kind="undo",
                extra={"undo_of": n})
    return dest, m


def undo_item(sd, h, fid, extra_args=()):
    """Re-run fix for the latest version with one approved id left out."""
    vs = [v for v in h["versions"] if v["kind"] in ("fix", "undo-item") and v.get("approved")]
    if not vs:
        sys.exit("no fix run with approved items in this history")
    v = vs[-1]
    ids = [a["id"] for a in v["approved"]]
    if fid not in ids:
        sys.exit(f"{fid} was not approved in v{v['n']} (approved: {', '.join(ids)})")
    keep = [i for i in ids if i != fid]
    if not keep:
        sys.exit(f"v{v['n']} has only {fid}: to go back to before it, use --undo {v['n']}")
    scan = atomic.load_json(Path(sd) / "scan.json", {}) or {}
    orig = Path(scan.get("set") or v["input"])
    dest = free_name(orig.with_name(f"{orig.stem} (v{v['n']} without {fid}).als"))
    args = [sys.executable, "-m", "hypnomix.workflow.fix", str(sd), "--approve", ",".join(keep), "--out", str(dest)]
    inp = Path(v["input"]) if v.get("input") else None
    if inp and inp.resolve() != orig.resolve():
        if not inp.exists():
            sys.exit(f"v{v['n']} started from {inp}, which is gone; undo it with --undo first")
        args += ["--from", str(inp)]
    if v.get("allow_protected"):
        args.append("--allow-protected")
    if v.get("key"):
        args += ["--key", v["key"]]
    args += list(extra_args)
    r = subprocess.run(args, text=True, capture_output=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    h2 = load(sd)
    if h2["versions"] and h2["versions"][-1].get("output") == str(dest):
        h2["versions"][-1]["kind"] = "undo-item"
        h2["versions"][-1]["without"] = fid
        h2["versions"][-1]["rebuilt_from"] = v["n"]
        save(sd, h2)
    return r.returncode, dest


def main():
    ap = argparse.ArgumentParser(prog="hypnomix history", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", metavar="SONG_OR_DIR")
    ap.add_argument("--diff", nargs=2, type=int, metavar=("N", "M"))
    ap.add_argument("--undo", type=int, metavar="N")
    ap.add_argument("--undo-item", metavar="ID")
    ap.add_argument("--stale-ok", action="store_true", help="with --undo-item: passed on to fix")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    sd = resolve(a.target)
    h = load(sd)
    if a.json:
        print(json.dumps(h, indent=1)); return
    if a.diff:
        from hypnomix.session import diff as D
        x, y = (version_set(sd, h, n) for n in a.diff)
        if x is None or y is None:
            sys.exit("one of those versions kept no copy of its set")
        rows = D.diff(x, y)
        print(f"v{a.diff[0]} → v{a.diff[1]}: {len(rows)} change(s)\n")
        print(D.text(rows))
        return
    if a.undo is not None:
        dest, m = undo(sd, h, a.undo)
        print(f"wrote {dest}\n  equal to what v{a.undo} started from; logged as v{m}. Nothing was deleted or "
              "overwritten. Close the other set in Live before opening this one.")
        return
    if a.undo_item:
        code, dest = undo_item(sd, h, a.undo_item, ["--stale-ok"] if a.stale_ok else [])
        if code == 0:
            print(f"\nrebuilt without {a.undo_item}: {dest}")
        sys.exit(code)
    print(listing(sd, h))


if __name__ == "__main__":
    main()
