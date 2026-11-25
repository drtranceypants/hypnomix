#!/usr/bin/env python3
"""Watch a Live set while you work: on every save, a quick incremental scan runs in the background and says
what is new. Read-only: it never writes to the set.

  hypnomix watch SET.als [--out DIR] [--every 2] [--full] [--once]

  --out    scan folder (default hypnomix-out/scan/<song>)
  --every  how often to look at the file, in seconds (default 2)
  --full   run every group on each save, not only the quick ones (slower; incremental all the same)
  --once   scan once now (incremental if the folder has an earlier scan) and stop

Each save (the file's modification time changes and its size holds still for a moment) runs
`hypnomix scan SET --quick --since DIR --out DIR`: only the groups the changes can affect run again. New findings
are printed and appended to DIR/WATCH.md; REVIEW.md, findings.json and the review page stay current. Ctrl-C stops.
Polling only (no extra packages).
"""
import argparse, json, os, subprocess, sys, threading, time
from pathlib import Path

from hypnomix.core.paths import out_at


def scan_once(als, od, full=False, log=print):
    """One incremental scan into od. Returns (exit code, [new findings], seconds)."""
    args = [sys.executable, "-m", "hypnomix.cli", "scan", str(als), "--out", str(od)]
    if not full:
        args.append("--quick")
    if (Path(od) / "findings.json").exists():
        args += ["--since", str(od)]
    t0 = time.time()
    r = subprocess.run(args, capture_output=True, text=True)
    secs = time.time() - t0
    new = []
    fj = Path(od) / "findings.json"
    if r.returncode == 0 and fj.exists():
        new = [f for f in json.loads(fj.read_text())["findings"] if f.get("new")]
    elif r.returncode != 0:
        log(f"scan failed ({r.returncode}): {(r.stdout + r.stderr).strip()[-400:]}")
    return r.returncode, new, secs


def report(od, new, secs, log=print):
    stamp = time.strftime("%H:%M:%S")
    if new:
        log(f"[{stamp}] {len(new)} new ({secs:.1f} s):")
        for f in new[:20]:
            log(f"  [{f.get('severity')}] {f['id']}: {f.get('track') or '-'} {f.get('where', '')}  "
                f"{str(f.get('problem'))[:90]}")
    else:
        log(f"[{stamp}] nothing new ({secs:.1f} s)")
    with open(Path(od) / "WATCH.md", "a") as fh:
        fh.write(f"\n## {time.strftime('%Y-%m-%d %H:%M:%S')}: {len(new)} new\n\n"
                 + "".join(f"- [{f.get('severity')}] `{f['id']}` {f.get('track') or '-'} {f.get('where', '')}: "
                           f"{f.get('problem')}\n" for f in new))


def settled(p, wait=0.6):
    """True once the file's size and mtime hold still (Live writes a set in one go, but not instantly)."""
    try:
        a = p.stat()
        time.sleep(wait)
        b = p.stat()
    except OSError:
        return False
    return (a.st_size, a.st_mtime) == (b.st_size, b.st_mtime)


def watch(als, od, every=2.0, full=False, stop=None, log=print, max_runs=None):
    """Poll als; on each save, run the incremental scan in a background thread. stop: a threading.Event."""
    als = Path(als)
    stop = stop or threading.Event()
    last = None
    runs = 0
    busy = threading.Lock()
    pending = [False]

    def job():
        nonlocal runs
        with busy:
            while True:
                pending[0] = False
                code, new, secs = scan_once(als, od, full, log)
                if code == 0:
                    report(od, new, secs, log)
                runs += 1
                if not pending[0]:
                    break
    threads = []
    while not stop.is_set():
        try:
            m = als.stat().st_mtime
        except OSError:
            log(f"{als} is not there (moved or being saved?); waiting")
            stop.wait(every)
            continue
        if m != last and settled(als):
            last = als.stat().st_mtime
            if busy.locked():
                pending[0] = True          # one more run when the current one ends
            else:
                th = threading.Thread(target=job, daemon=True)
                th.start()
                threads.append(th)
        if max_runs is not None and runs >= max_runs and not busy.locked():
            break
        stop.wait(every)
    for th in threads:
        th.join(timeout=600)
    return runs


def main():
    ap = argparse.ArgumentParser(prog="hypnomix watch", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als", metavar="SET.als")
    ap.add_argument("--out")
    ap.add_argument("--every", type=float, default=2.0)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    als = Path(a.als).expanduser().resolve()
    if not als.is_file() or als.suffix != ".als":
        sys.exit(f"not a Live set: {als}")
    od = out_at(a.out, "scan", als.stem)
    if a.once:
        code, new, secs = scan_once(als, od, a.full)
        if code == 0:
            report(od, new, secs)
        sys.exit(code)
    print(f"watching {als.name} (every {a.every:g} s; read-only) → {od}\nCtrl-C to stop")
    stop = threading.Event()
    try:
        watch(als, od, a.every, a.full, stop)
    except KeyboardInterrupt:
        stop.set()
        print("\nstopped")


if __name__ == "__main__":
    main()
