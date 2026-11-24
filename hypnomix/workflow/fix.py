#!/usr/bin/env python3
"""Apply the findings a person approved after `hypnomix scan`, and nothing else.

  hypnomix fix SCAN_DIR --list                              every finding id, with its recorded decision
  hypnomix fix SCAN_DIR --decide ID=approve,ID=skip [--note "why"]
                                                            record the person's decisions (decisions.json)
  hypnomix fix SCAN_DIR --approved --out "Song (fixed).als" apply everything recorded as approved
  hypnomix fix SCAN_DIR --approve ID,ID,... --out "Song (fixed).als"
                                                            same, naming the ids here (also recorded)
  hypnomix fix SCAN_DIR --approve ID --from "Song (fixed 1).als" --out "Song (fixed 2).als"
                                                            one fix at a time, each on top of the last

What happens to each approved finding (see REVIEW.md for the ids):
  set     written into ONE new set next to the original, in this order: distortion parameter fixes,
          sidechain settings, clip fades / volume eases (smooth), warp-marker nudges (timing).
          The original set is never touched; temporary step files are removed at the end.
  audio   a new audio file. tune: the vocal is rendered from the set (clip gain, fades, warps baked in) and
          pitch-corrected into <project>/Samples/Tuned/ (never over an existing file). Folder scans: the
          repaired copy goes to SCAN_DIR/fixed/. Source audio is never changed.
  manual  listed with what to do by hand.
  info    nothing to apply.

Safety checks made here, in code (they stop the run rather than guess):
  - the scanned set must not have changed since the scan (re-scan, or --stale-ok if you know why)
  - every approved finding is looked up again in the set being written, by track + kind + position, because
    ids are only numbers in a list: if it is no longer there (already fixed, or the set changed) it is
    skipped and reported, never swapped for its neighbour
  - findings on tracks you protected (`hypnomix prefs`) need --allow-protected
  - vocal tuning needs a confirmed key: `scan --key` or `fix --key "F# major"`
  - after writing, the new set is checked again: the log says which approved problems are gone and which
    are still measured (--no-verify to skip)
  - any failed step makes the exit code 1 and is listed under FAILED; nothing is reported as done that wasn't

Close the set in Live first: Live would overwrite edits on its next save, and changes you have not saved
in Live are not in the file this reads. Every run appends to SCAN_DIR/fix-log.md.
"""
import argparse, json, re, shutil, subprocess, sys, time
from pathlib import Path

ORDER = ["distortion", "sidechain", "smooth", "timing", "motion", "borrow", "order"]   # track names come last, after all of these
DECISIONS = ("approve", "skip", "change")


def hx(*args, timeout=7200):
    try:
        r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return 1, f"timed out after {timeout} s: hypnomix {' '.join(map(str, args[:2]))}"
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, "\n".join(l for l in out.splitlines() if "Warning" not in l and "warnings.warn" not in l)


def safe_name(track):
    return re.sub(r'[\\/:*?"<>|]', "-", track)


def fingerprint(f):
    """What a finding IS, independent of its number in the list."""
    return (f.get("tool"), f.get("track") or "", f.get("kind") or "", f.get("where") or "", f.get("device") or "")


def load_decisions(sd):
    p = sd / "decisions.json"
    return json.loads(p.read_text()) if p.exists() else {}


def save_decisions(sd, dec):
    (sd / "decisions.json").write_text(json.dumps(dec, indent=1))


def decision_of(dec, fid):
    d = dec.get(fid)
    return d.get("decision") if isinstance(d, dict) else d


def live_running():
    try:
        return subprocess.run(["pgrep", "-x", "Live"], capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


def recheck(tool, als, sd, scan, timing_tracks, tag):
    """Analyse `als` again with `tool` (read-only) and return its findings in the scan's shape, or None."""
    j = sd / "raw" / f"recheck-{tool}-{tag}.json"
    j.parent.mkdir(parents=True, exist_ok=True)
    if j.exists():
        j.unlink()
    args = [tool, als, "--json", j]
    if tool == "timing":
        args += ["--list", "0"]
        for t in timing_tracks:
            args += ["--track", t]
        tj = sd / "raw" / "timing.json"
        for t in (json.loads(tj.read_text()).get("melodic", []) if tj.exists() else []):
            args += ["--melodic", t]
    if tool == "distortion" and scan.get("mix"):
        args += ["--mix", scan["mix"]]
    if tool == "order":
        args += ["--names", sd / "raw" / "names" / "names.json"]
    if tool == "motion":
        args += motion_args(sd, scan)
    if tool == "borrow":
        args += borrow_args(scan)
    hx(*args)
    if not j.exists():
        return None
    rows = json.loads(j.read_text()).get("findings", [])
    if tool == "distortion":
        rows = [dict(id=(r.get("evidence") or {}).get("id"), tool="distortion", kind=r.get("kind"),
                     track=r.get("track"), where=r.get("where", ""), device=r.get("device", "")) for r in rows]
    for r in rows:
        r.setdefault("tool", tool)
    return rows


def motion_args(sd, scan):
    out = []
    if scan.get("mix"):
        out += ["--mix", scan["mix"]]
    nj = sd / "raw" / "names" / "names.json"
    if nj.exists():
        out += ["--names", nj]
    if scan.get("motion_style"):
        out += ["--style", scan["motion_style"]]
    return out


def borrow_args(scan):
    out = ["--mix", scan["mix"]] if scan.get("mix") else []
    for o in scan.get("borrow_from") or []:
        out += ["--from", o]
    return out


def rematch(items, now):
    """Pair approved findings with the same findings in the current set. Returns (ids to apply, skipped)."""
    by_fp, old_fp = {}, {}
    for r in now:
        by_fp.setdefault(fingerprint(r), []).append(r)
    for f in items:
        old_fp.setdefault(fingerprint(f), []).append(f)
    ids, skipped = [], []
    for fp, olds in old_fp.items():
        news = by_fp.get(fp, [])
        if not news:
            skipped += [(f, "no longer found in this set (already fixed, or the set changed)") for f in olds]
        elif len(news) != len(olds):
            skipped += [(f, f"ambiguous: {len(news)} findings now match where {len(olds)} did; re-scan") for f in olds]
        else:
            for r in news:
                ids += r.get("ids") or [r["id"]]
    return sorted(set(ids)), skipped


def main():
    ap = argparse.ArgumentParser(prog="hypnomix fix", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scan_dir")
    ap.add_argument("--approve", default="", help="comma-separated finding ids (or item numbers) to apply")
    ap.add_argument("--approved", action="store_true", help="apply every finding recorded as approved in decisions.json")
    ap.add_argument("--decide", default="", help="record decisions and exit: ID=approve|skip|change[,ID=...]")
    ap.add_argument("--note", default="", help="with --decide: the person's reason or requested change")
    ap.add_argument("--out", help='new set to write, e.g. "Song (fixed).als" (same folder as the original)')
    ap.add_argument("--from", dest="from_set", help="start from this set instead of the scanned one (to apply "
                    "fixes one at a time, each on top of the last); must be in the same folder")
    ap.add_argument("--key", help='confirmed song key for vocal tuning, e.g. "F# major", or "sections" to tune '
                    "with the scan's section-by-section key map (every key question answered)")
    ap.add_argument("--answer", action="append", default=[], metavar="NOTE|BARS=NOTE|both",
                    help="the person's answer to a key question (key-N), e.g. F#, \"17-24=F\", both; saved in the scan")
    ap.add_argument("--allow-protected", action="store_true", help="the person re-confirmed changes on protected tracks")
    ap.add_argument("--stale-ok", action="store_true", help="apply although the set changed since the scan")
    ap.add_argument("--no-verify", action="store_true", help="skip the check of the new set after writing")
    ap.add_argument("--list", action="store_true", help="list findings and exit")
    a = ap.parse_args()
    sd = Path(a.scan_dir)
    data = json.loads((sd / "findings.json").read_text())
    scan = json.loads((sd / "scan.json").read_text()) if (sd / "scan.json").exists() else {}
    findings = data["findings"]
    dec = load_decisions(sd)
    by_key = {f["id"]: f for f in findings}
    by_key.update({str(f["n"]): f for f in findings})

    if a.list:
        for f in findings:
            print(f"{f['n']:4d}  {f['id']:<22} [{f.get('severity')}] {f.get('applies'):<6} "
                  f"{decision_of(dec, f['id']) or '-':<8}{'PROTECTED ' if f.get('protected') else ''}"
                  f"{f['tool']}: {f.get('track') or '-'} {f.get('where', '')}  {str(f.get('problem'))[:80]}")
        return

    key_json = sd / "raw" / "key.json"
    if a.answer:
        if not key_json.exists():
            sys.exit("this scan has no key map (raw/key.json): re-scan the vocals group")
        from hypnomix.studio.tune import load_scales
        answers = scan.get("answers", []) + a.answer
        _, open_q = load_scales(key_json, answers)          # checks every answer against its question
        scan["answers"] = answers
        (sd / "scan.json").write_text(json.dumps(scan, indent=1))
        print(f"answers saved: {', '.join(answers)}")
        print("still open: " + "; ".join(open_q) if open_q else "every key question is answered: tune with --key sections")
        if not (a.approve or a.approved):
            return

    if a.decide:
        for item in a.decide.split(","):
            if "=" not in item:
                sys.exit(f"expected ID=decision, got {item!r}")
            k, v = (x.strip() for x in item.split("=", 1))
            if k not in by_key:
                sys.exit(f"unknown id: {k}")
            if v not in DECISIONS:
                sys.exit(f"decision must be one of {', '.join(DECISIONS)} (got {v!r})")
            dec[by_key[k]["id"]] = {"decision": v, "note": a.note, "at": time.strftime("%Y-%m-%d %H:%M")}
        save_decisions(sd, dec)
        n = {d: sum(1 for k in dec if decision_of(dec, k) == d) for d in DECISIONS}
        left = sum(1 for f in findings if f.get("applies") not in ("info", "answer") and f["id"] not in dec)
        print(f"recorded. approve {n['approve']}, skip {n['skip']}, change {n['change']}; {left} still undecided")
        return

    want = {x.strip() for x in a.approve.split(",") if x.strip()}
    unknown = sorted(w for w in want if w not in by_key)
    if unknown:
        sys.exit(f"unknown ids: {', '.join(unknown)}")
    want = {by_key[w]["id"] for w in want}
    if a.approved:
        want |= {k for k in dec if decision_of(dec, k) == "approve" and k in by_key}
        # on-by-default clean-up (track order, vocal stacks): included unless the person skipped it
        dflt = {f["id"] for f in findings if f.get("default") == "approve" and f["id"] not in dec}
        if dflt:
            print(f"on by default (skip them to opt out): {', '.join(sorted(dflt))}")
        want |= dflt
    if not want:
        sys.exit("nothing approved: pass --approve ID,ID,... or record decisions with --decide and use --approved")
    refused = sorted(w for w in want if decision_of(dec, w) in ("skip", "change"))
    if refused:
        sys.exit(f"these were recorded as skip/change, not approve: {', '.join(refused)}. "
                 "Record the new decision with --decide first.")
    chosen = [by_key[w] for w in sorted(want)]
    prot = [f["id"] for f in chosen if f.get("protected")]
    if prot and not a.allow_protected:
        sys.exit(f"on protected tracks: {', '.join(prot)}. Ask the person again, then add --allow-protected.")

    name_items = [f for f in chosen if f.get("tool") == "name"]       # renamed last: every other step finds tracks by name
    set_items = [f for f in chosen if f.get("applies") == "set" and f.get("tool") != "name"]
    audio_items = [f for f in chosen if f.get("applies") == "audio"]
    manual_items = [f for f in chosen if f.get("applies") in ("manual", "info")]
    folder_mode = scan.get("mode") in ("folder", "file")
    orig = Path(data["set"]) if data.get("set") and not folder_mode else None
    src = Path(a.from_set).resolve() if a.from_set else orig
    out = None

    if orig and (set_items or audio_items or name_items):
        if not orig.exists():
            sys.exit(f"the scanned set is gone: {orig}")
        if src.resolve().parent != orig.resolve().parent:
            sys.exit(f"--from must be in the same folder as the scanned set ({orig.parent})")
        was = scan.get("set_mtime")
        if was and not a.from_set and abs(orig.stat().st_mtime - was) > 1 and not a.stale_ok:
            sys.exit("the set was saved again after the scan, so the findings may not match it any more.\n"
                     "Re-scan it (recommended), or pass --stale-ok if the change cannot affect these findings.")
    if set_items or name_items:
        if not orig:
            sys.exit("this scan has no Live set: set changes cannot be applied")
        if not a.out:
            sys.exit("approved set changes need --out NEW.als")
        out = Path(a.out)
        if not out.is_absolute():
            out = src.parent / out
        if out.resolve().parent != src.resolve().parent:
            sys.exit(f"--out must be in the same folder as the original ({src.parent})")
        if out.resolve() in (src.resolve(), orig.resolve()):
            sys.exit("refusing to overwrite the original set")
        if out.exists():
            sys.exit(f"{out.name} already exists: choose a new name (nothing is ever overwritten)")
    name_out = out
    if orig and (set_items or audio_items or name_items) and live_running():
        print("NOTE: Live is running. Changes not saved in Live are not in the file being read, and the set "
              "must be closed in Live before the new one is opened.\n")

    for f in chosen:  # an explicit --approve is a decision too
        if f["id"] not in dec:
            dec[f["id"]] = {"decision": "approve", "note": "via --approve", "at": time.strftime("%Y-%m-%d %H:%M")}
    save_decisions(sd, dec)
    log = [f"\n## fix run {time.strftime('%Y-%m-%d %H:%M')}", "",
           f"approved: {', '.join(f['id'] for f in chosen)}", ""]
    failed, skipped_all = [], []

    if set_items:
        tj = sd / "raw" / "timing.json"
        tjd = json.loads(tj.read_text()) if tj.exists() else {}
        timing_tracks, timing_melodic = tjd.get("tracks", []), tjd.get("melodic", [])
        cur, step, temps, applied_tools = src, 0, [], []
        try:
            for tool in ORDER:
                items = [f for f in set_items if f["tool"] == tool]
                if not items:
                    continue
                step += 1
                nxt = src.parent / f"{src.stem} (fix step {step}).als"
                temps.append(nxt)
                txt = ""
                if tool == "sidechain":  # addressed by host track, one at a time
                    tmp = cur
                    for k, f in enumerate(items):
                        target = src.parent / f"{src.stem} (fix step {step}.{k}).als"
                        temps.append(target)
                        extra = ["--glue-to-compressor"] if f.get("glue") else []
                        c, t = hx("sidechain", tmp, "--host", f["host"], "--apply", target, *extra)
                        txt += t + "\n"
                        if c == 0 and target.exists():
                            tmp = target
                        else:
                            failed.append(f"{f['id']}: sidechain on {f['host']} failed")
                    ok = tmp != cur
                    if ok:
                        shutil.copyfile(tmp, nxt)
                else:
                    now = recheck(tool, cur, sd, scan, timing_tracks, f"pre{step}")
                    if now is None:
                        failed += [f"{f['id']}: could not re-check the set with {tool}" for f in items]
                        log += [f"### {tool}: FAILED (re-check did not run)", ""]
                        print(f"{tool:<11} FAILED  (re-check did not run)")
                        continue
                    ids, skipped = rematch(items, now)
                    skipped_all += skipped
                    if not ids:
                        log += [f"### {tool}: nothing to apply (see skipped)", ""]
                        print(f"{tool:<11} nothing to apply ({len(skipped)} skipped)")
                        continue
                    args = [tool, cur, "--apply", nxt, "--ids", ",".join(ids)]
                    if tool == "timing":
                        args += ["--list", "0"]
                        for t in timing_tracks:
                            args += ["--track", t]
                        for t in timing_melodic:
                            args += ["--melodic", t]
                    if tool == "distortion" and scan.get("mix"):
                        args += ["--mix", scan["mix"]]
                    if tool == "order":
                        args += ["--names", sd / "raw" / "names" / "names.json"]
                    if tool in ("motion", "borrow"):   # the person's fine controls from the review notes
                        args += motion_args(sd, scan) if tool == "motion" else borrow_args(scan)
                        for f in items:
                            note = ((dec.get(f["id"]) or {}).get("note") or "").strip()
                            if note and f["id"] in ids:
                                args += ["--tweak", f"{f['id']}:{note}"]
                    code, txt = hx(*args)
                    ok = code == 0 and nxt.exists()
                    if not ok:
                        failed += [f"{f['id']}: {tool} --apply failed" for f in items]
                log += [f"### {tool}: {'applied' if ok else 'FAILED'} ({len(items)} approved)", "", "```",
                        txt.strip()[-2500:], "```", ""]
                print(f"{tool:<11} {'ok' if ok else 'FAILED'}  ({len(items)} approved)")
                if ok:
                    cur = nxt
                    applied_tools.append(tool)
            if cur == src:
                print("no set changes could be applied; see fix-log.md")
                out = None
            else:
                shutil.copyfile(cur, out)
                print(f"wrote {out}")
        finally:
            for t in temps:
                if t.exists():
                    t.unlink()

        if out:  # structure first: a broken set must never be opened
            from hypnomix.session import check as C, diff as D
            added = [f"{f['borrow']['track']} (from original)" for f in set_items if f["tool"] == "borrow"]
            errs, warns, _ = C.check(out, src, reordered="order" in applied_tools, added=added)
            if errs:
                bad = out.with_name(out.stem + " (BROKEN, do not open).als")
                out.rename(bad)
                failed += [f"structure check: {e}" for e in errs]
                log += ["### structure check: FAILED", ""] + [f"- {e}" for e in errs] + [""]
                print(f"check      FAILED: the written set is not sound. Renamed to {bad.name}; keep using the original.")
                out = None
            else:
                rows = D.diff(src, out)
                log += ["### what changed (old set → new set)", "", "```", D.text(rows), "```", ""]
                print(f"check      structure OK; {len(rows)} change(s) written (listed in fix-log.md; `hypnomix diff` shows them)")
        if out and not a.no_verify:  # measure the new set: are the approved problems gone?
            log += ["### verify (the new set, measured again)", ""]
            for tool in applied_tools:
                if tool == "sidechain":
                    continue
                if tool in ("motion", "borrow"):   # options, not problems: report what was written instead of re-measuring
                    line = (f"- {tool}: approved " + ("moves written as automation / clip edits" if tool == "motion" else
                            "loops added on new switched-off tracks") + " (listed above); listen to each")
                    print("verify     " + line[2:])
                    log.append(line)
                    continue
                items = [f for f in set_items if f["tool"] == tool]
                now = recheck(tool, out, sd, scan, timing_tracks, "post")
                if now is None:
                    line = f"- {tool}: could not be re-checked"
                else:
                    left = {fingerprint(r) for r in now}
                    still = [f["id"] for f in items if fingerprint(f) in left]
                    line = (f"- {tool}: {len(items) - len(still)} of {len(items)} approved problems no longer measured"
                            + (f"; still measured: {', '.join(still)} (listen there: a gentle fix can leave a "
                               f"smaller version of the problem)" if still else ""))
                print("verify     " + line[2:])
                log.append(line)
            log.append("")

    # ---- track names, last (into the new set, or a new set of their own)
    if name_items:
        from hypnomix.session.names import rename_set
        mapping = {}
        for f in name_items:
            note = ((dec.get(f["id"]) or {}).get("note") or "").strip()
            mapping[f["old"]] = note or f["new"]
            if f.get("kind") == "track-name-question" and not note:
                print(f"name       {f['old']}: approved without a name from the person; using the guess {f['new']!r}")
        target = name_out
        base = out if (set_items and out and Path(out).exists()) else src
        if base != src or not Path(target).exists():
            done_n, skipped_n = rename_set(base, target, mapping, inplace=(base != src))
            for old, new in done_n:
                print(f"name       {old} → {new}")
            for old, why in skipped_n:
                print(f"name       skipped {old}: {why}")
                skipped_all.append(({"id": next(f['id'] for f in name_items if f['old'] == old), "tool": "name",
                                     "track": old}, why))
            log += ["### track names", ""] + [f"- {o_} → {n_}" for o_, n_ in done_n] + \
                   [f"- skipped {o_}: {w}" for o_, w in skipped_n] + [""]
            from hypnomix.session import check as C
            errs, _, _ = C.check(target, src, renamed=dict(done_n), reordered=any(f["tool"] == "order" for f in set_items),
                                 added=[f"{f['borrow']['track']} (from original)" for f in set_items if f["tool"] == "borrow"])
            if errs:
                bad = Path(target).with_name(Path(target).stem + " (BROKEN, do not open).als")
                Path(target).rename(bad)
                failed += [f"structure check after renaming: {e}" for e in errs]
                print(f"check      FAILED after renaming: renamed to {bad.name}; keep using the original.")
            else:
                print(f"check      structure OK after renaming; wrote {target}")

    # ---- approved moves of a plan (prep / automix / master --plan): run the tool with only those moves
    planned = [f for f in audio_items if f.get("plan")]
    audio_items = [f for f in audio_items if not f.get("plan")]
    jobs = {}
    for f in planned:
        pl = f["plan"]
        jobs.setdefault((pl["tool"], pl["file"]), []).append(f)
    for (tool, source), items in jobs.items():
        dest = sd / "fixed" / tool
        k = 1
        while tool != "prep" and dest.exists():       # one folder per run, never over an earlier result
            k += 1
            dest = sd / "fixed" / f"{tool} {k}"
        if tool == "prep":
            steps = sorted({f["plan"]["step"] for f in items})
            code, txt = hx("prep", source, "--steps", ",".join(steps), "--out", dest)
        elif tool == "automix":
            kf = sd / "raw" / "approved-automix.json"
            kf.parent.mkdir(parents=True, exist_ok=True)
            kf.write_text(json.dumps(sorted(f["plan"]["key"] for f in items)))
            code, txt = hx("automix", source, "--no-prep", "--no-master", "--only", kf, "--out", dest)
        elif tool == "master":
            pl = items[0]["plan"]
            args = ["master", source, "--only", ",".join(sorted({f["plan"]["key"] for f in items})), "--out", dest,
                    "--target", pl.get("target", -14), "--ceiling", pl.get("ceiling", -1), "--match", pl.get("match", 0.6),
                    "--glue", pl.get("glue", 1.5), "--warmth", pl.get("warmth", 0), "--width", pl.get("width", 1)]
            if pl.get("reference"):
                args += ["--reference", pl["reference"]]
            code, txt = hx(*args)
        else:
            code, txt = 1, f"unknown plan tool {tool}"
        ok = code == 0
        ids = ", ".join(f["id"] for f in items)
        log += [f"### {tool} ({Path(source).name}): {'written to ' + str(dest) if ok else 'FAILED'}", "",
                f"approved moves: {ids}", "", "```", txt.strip()[-1500:], "```", ""]
        print(f"{tool:<11} {'ok' if ok else 'FAILED'}  {Path(source).name}: {len(items)} approved move(s)"
              + (f"  → {dest}" if ok else ""))
        if not ok:
            failed.append(f"{ids}: {tool} failed on {Path(source).name}")

    for f in audio_items:
        if f.get("tool") == "voices":  # harmony balance: only with the settings the person chose
            note = ((dec.get(f["id"]) or {}).get("note") or "")
            kv = dict(x.split("=", 1) for x in note.replace(",", " ").split() if "=" in x)
            if "anchor" not in kv or not any(float(kv.get(k, 0) or 0) > 0 for k in ("above", "below")):
                failed.append(f"{f['id']}: harmony balance needs the person's choices in the note, e.g. --decide "
                              f"{f['id']}=approve --note \"anchor=lead reduce=above above=1.5 spread=flat\"")
                print(f"voices     REFUSED  no anchor / dB chosen (there is no default)")
                continue
            dest = sd / "fixed" / "voices"
            k = 1
            while dest.exists():
                k += 1
                dest = sd / "fixed" / f"voices {k}"
            args = ["voices", *f["stems"], "--anchor", kv["anchor"] if kv["anchor"] != "lead" or not f.get("lead") else f["lead"],
                    "--reduce", kv.get("reduce", "above"), "--above-db", kv.get("above", "0"),
                    "--below-db", kv.get("below", "0"), "--spread", kv.get("spread", "ladder"),
                    "--max-cut", kv.get("max-cut", "6"), "--out", dest]
            if scan.get("tempo"):
                args += ["--bpm", scan["tempo"]]
            code, txt = hx(*args)
            ok = code == 0
            log += [f"### {f['id']} harmony balance ({note}): {'written to ' + str(dest) if ok else 'FAILED'}", "",
                    "```", txt.strip()[-1500:], "```", ""]
            print(f"voices     {'ok' if ok else 'FAILED'}  {note}" + (f"  → {dest}" if ok else ""))
            if ok:
                print("           balanced copies of each part: put them on new tracks, mute the originals, A/B")
            else:
                failed.append(f"{f['id']}: voices failed")
            continue
        if f.get("run"):  # folder scan: a repaired copy into SCAN_DIR/fixed
            fixed = sd / "fixed"
            fixed.mkdir(exist_ok=True)
            code, txt = hx(*[str(x).replace("{out}", str(fixed)) for x in f["run"]])
            ok = code == 0
            log += [f"### {f['id']} {f.get('track')}: {'written to ' + str(fixed) if ok else 'FAILED'}", "", "```",
                    txt.strip()[-1200:], "```", ""]
            print(f"{f['tool']:<11} {'ok' if ok else 'FAILED'}  {f.get('track')}" + (f"  → {fixed}" if ok else ""))
            if not ok:
                failed.append(f"{f['id']}: {f['tool']} failed")
            continue
        if not orig:
            failed.append(f"{f['id']}: no Live set in this scan")
            continue
        key = a.key or scan.get("key")  # tune
        tune_key = ["--key", key] if key else []
        if key == "sections":
            from hypnomix.studio.tune import load_scales
            if not key_json.exists():
                failed.append(f"{f['id']}: not tuned: this scan has no key map; re-scan or pass --key \"<key>\"")
                print(f"tune       REFUSED  {f['track']}: no key map in the scan")
                continue
            answers = scan.get("answers", []) + a.answer
            _, open_q = load_scales(key_json, answers)
            if open_q:   # the person's rule: where the key is unsure, leave the disputed notes exactly as sung
                print(f"tune       {f['track']}: {len(open_q)} key question(s) open; the disputed notes there are "
                      "left as sung (answer them with --answer to tune those too)")
                log.append(f"- {f['id']}: key questions open, disputed notes left as sung: {'; '.join(open_q)}")
            tune_key = ["--scales", key_json] + [x for ans in answers for x in ("--answer", ans)]
        elif not key:
            hint = " or --key sections after answering its questions" if key_json.exists() else ""
            failed.append(f"{f['id']}: not tuned: confirm the key with the person, then pass --key \"<key>\"{hint} "
                          f"(the scan estimated {f.get('key')})")
            print(f"tune       REFUSED  {f['track']}: the key is not confirmed (--key)")
            continue
        rdir = sd / "raw" / ("renders" if not a.from_set else f"renders-{safe_name(src.stem)}")
        rendered = rdir / f"{safe_name(f['track'])}.wav"
        if not rendered.exists():
            hx("render", src, "--tracks", f["track"], "--out", rdir)
        if not rendered.exists():
            failed.append(f"{f['id']}: could not render {f['track']} from the set")
            print(f"tune       FAILED  {f['track']}: render failed")
            continue
        tdir = src.parent / "Samples" / "Tuned"
        tdir.mkdir(parents=True, exist_ok=True)
        dest, k = tdir / f"{safe_name(f['track'])} (tuned).wav", 1
        while dest.exists():
            k += 1
            dest = tdir / f"{safe_name(f['track'])} (tuned {k}).wav"
        args = ["tune", rendered, dest, *tune_key]
        lead = scan.get("lead")
        if lead and lead != f["track"]:      # a harmony: settle in-between notes against the same lead as the scan
            lrend = rdir / f"{safe_name(lead)}.wav"
            if not lrend.exists():
                hx("render", src, "--tracks", lead, "--out", rdir)
            if lrend.exists():
                args += ["--guide", lrend]
        if scan.get("ref"):
            args += ["--ref", scan["ref"]]
        code, txt = hx(*args)
        ok = code == 0 and dest.exists()
        log += [f"### tune {f['track']}: {'written' if ok else 'FAILED'}", "", "```", txt.strip()[-1500:], "```", ""]
        print(f"tune       {'ok' if ok else 'FAILED'}  {dest if ok else f['track']}")
        if ok:
            print("           put it on a new audio track at bar 1 (warp off), mute the original, A/B")
        else:
            failed.append(f"{f['id']}: tune failed on {f['track']}")

    if skipped_all:
        print("\nskipped (not applied):")
        log += ["### skipped (not applied)", ""]
        for f, why in skipped_all:
            line = f"- {f['id']} {f.get('track') or ''} {f.get('where', '')}: {why}"
            print(line)
            log.append(line)
        log.append("")
    if manual_items:
        print("\nby hand (not changed automatically):")
        log += ["### by hand", ""]
        for f in manual_items:
            line = f"- {f['id']} {f.get('track') or ''} {f.get('where', '')}: {str(f.get('fix'))[:300]}"
            print(line)
            log.append(line)
        log.append("")
    if failed:
        print("\nFAILED (not done):")
        log += ["### FAILED (not done)", ""] + [f"- {x}" for x in failed] + [""]
        for x in failed:
            print(f"- {x}")
    with open(sd / "fix-log.md", "a") as fh:
        fh.write("\n".join(log) + "\n")
    print(f"\nlog: {sd / 'fix-log.md'}")
    if out:
        print("Close the original in Live, open the new set, and A/B the changed spots against the original.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
