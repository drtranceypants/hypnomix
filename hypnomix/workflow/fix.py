#!/usr/bin/env python3
"""Apply the findings a person approved after `hypnomix scan`, and nothing else.

  hypnomix fix SCAN_DIR --list                              every finding id, with its recorded decision
  hypnomix fix SCAN_DIR --list --undecided --top 15         the next 15 findings nobody has decided yet
  hypnomix fix SCAN_DIR --list --severity high --tool tune  narrow the list (--severity, --tool, --undecided,
                                                            --top N, --offset N: page through a long scan)
  hypnomix fix SCAN_DIR --show smooth-3                     one finding in full: everything REVIEW.md says about
                                                            it, plus the explanation of its kind of fix
  hypnomix fix SCAN_DIR --decide ID=approve,ID=skip [--note "why"]
                                                            record the person's decisions (decisions.json)
  hypnomix fix SCAN_DIR --approved --out "Song (fixed).als" apply everything recorded as approved
  hypnomix fix SCAN_DIR --approve ID,ID,... --out "Song (fixed).als"
                                                            same, naming the ids here (also recorded). --approve and
                                                            --decide can be repeated and each takes a comma list
  hypnomix fix SCAN_DIR --approved --no-defaults --out ...  only what was approved by name: leave out the clean-ups
                                                            that are on by default (track order, switched-off tracks)
  hypnomix fix SCAN_DIR --approve ID --from "Song (fixed 1).als" --out "Song (fixed 2).als"
                                                            one fix at a time, each on top of the last
  hypnomix fix SCAN_DIR --approved --out "Song (fixed).rpp"  a REAPER project: see workflow/fix_project.py
  hypnomix fix SCAN_DIR --approved --out "Song (fixed).ardour"  a HypnoMix Studio session: see workflow/fix_ardour.py
  hypnomix fix SCAN_DIR --decide smooth-3=approve@60        approve 60% of the proposed move (default 100)
  hypnomix fix SCAN_DIR --decide-like smooth-3=approve@60 [--dry-run] [--band 50]
                                                            the same decision for every undecided finding like
                                                            smooth-3 (same tool, kind and track role, size within
                                                            +-50%); lists the matches first
  hypnomix fix SCAN_DIR --approved --out "Song (fixed).als" --dry-run
                                                            print every file it would create and what it would
                                                            apply, and write nothing (no set, log, history, decision)
  --as NAME                                                 who is deciding (default: prefs review.name)

Before anything is written, fix prints every file it is about to create (the new set, the archive copy that
tidy keeps, repaired audio, the log) and lists the clean-ups that are on by default: they are applied by
--approved unless you skipped them, so skip them first or pass --no-defaults to opt out. At the end it prints
"Not applied": every finding decided as "change" (with the note), every approved finding that has to be done by
hand, every approved finding that was no longer found, and every approved id that is not in this scan any more,
each with what to do next. A vocal-level move is a "by hand" finding in a fresh scan: if you approve it, fix lists it
under "approved, but by hand", writes nothing for it and exits 0 (to write the vocal-level fixes, run hypnomix vocallevel
--apply). An approved finding that no step of fix can write (a kind of fix this version does not know, or a vocal-level
move in a scan made by an older version) is listed under FAILED with what to do, and the run exits with 1.

Amounts: tools with a strength control get it scaled (smooth: share of each jump eased and fade length; timing:
strength of each nudge; duck: ducking depth; tune: correction strength); device, sidechain, clip-gain and edge
fixes move each changed value that share of the way toward the proposed one (gains in dB). Kinds that can't be
scaled (renames, track order, tidy, plans, borrowed loops, motion moves) say so and apply in full for any amount
above 0; amount 0 applies nothing. Every run that wrote something is logged for `hypnomix history` (versions,
diff, undo); a run that wrote nothing is not a version.

HypnoMix Studio: the approved region fades (with their curve), region gain, gain-envelope dips over spikes, and the eased
level at a comp cut are written into ONE new .ardour snapshot, saved next to the original inside the same session
folder (that is where HypnoMix Studio keeps its own snapshots, and where it looks for the session's audio, so the new file
finds the same recordings; nothing is copied or moved). The original is never touched; the new file is read back and
checked, and what changed is listed. Track names and order, vocal stacks, timing, sidechain and tuning stay by hand
(harmony balance becomes balanced copies of the parts in SCAN_DIR/fixed/voices, not automation in the session).
Written and re-read by HypnoMix; NOT YET OPENED IN A RELEASED DAW (HypnoMix Studio is new and not every step has been tried in it; see the HypnoMix Studio wiki article for what to check there).

What happens to each approved finding (see REVIEW.md for the ids):
  set     written into ONE new set next to the original, in this order: distortion parameter fixes,
          sidechain settings, clip fades / volume eases (smooth), warp-marker nudges (timing).
          The original set is never touched; temporary step files are removed at the end.
  audio   a new audio file. tune: each take the comp clips play is pitch-corrected into <project>/Samples/Tuned/
          (a REAPER project: <project>/Tuned/), with its notes, a picture and the chords it was checked against
          beside it, never over an existing file. Folder scans: the repaired copy goes to SCAN_DIR/fixed/, and a
          name that is taken gets a number ("Harmony (dehiss 2).wav"), never over an earlier copy. Source audio is
          never changed. Harmony balance: balanced copies in SCAN_DIR/fixed/voices (in a Live set, volume
          automation in the new set).
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
  - timing is checked again by pairing each approved hit with the nearest one still measured on its track (a
    nudge moves the hit, so its position is not the same any more)

Close the set in Live first: Live would overwrite edits on its next save, and changes you have not saved
in Live are not in the file this reads. Every run appends to SCAN_DIR/fix-log.md. Decisions, findings and the log are written whole or not at
all; the version before is kept next to each as <name>.bak.
"""
import argparse, contextlib, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

from hypnomix.core import atomic as AT
from hypnomix.workflow import oversight as O

ORDER = ["distortion", "devices", "sidechain", "duck", "masking", "smooth", "edges", "cliplevel", "timing", "motion", "borrow", "colour", "tidy", "order"]   # track names come last, after all of these
DECISIONS = ("approve", "skip", "change")
# `fix` has no step that writes vocal-level moves (they are volume automation, made from renders of the vocal tracks)
VOCALLEVEL_HINT = (' (or, to write every vocal-level fix at once, not only the approved ones, into a NEW set: '
                   'hypnomix vocallevel "SET.als" --heard SOLO_EXPORTS_FOLDER --apply "NEW.als")')


def hx(*args, timeout=7200):
    try:
        r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return 1, f"timed out after {timeout} s: HypnoMix {' '.join(map(str, args[:2]))}"
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, "\n".join(l for l in out.splitlines() if "Warning" not in l and "warnings.warn" not in l)


def safe_name(track):
    return re.sub(r'[\\/:*?"<>|]', "-", track)


def fingerprint(f):
    """What a finding IS, independent of its number in the list."""
    return (f.get("tool"), f.get("track") or "", f.get("kind") or "", f.get("where") or "", f.get("device") or "")


def load_decisions(sd):
    return AT.load_json(Path(sd) / "decisions.json", {})


def save_decisions(sd, dec):
    AT.write_json(Path(sd) / "decisions.json", dec)


decisions_lock = AT.decisions_lock        # the one lock for decisions.json (core/atomic.py): the app and the review use it too


def record(sd, changes, keep_existing=False):
    """Merge `changes` ({id: entry}) into decisions.json. It is read again under the lock, so a decision another
    process recorded a moment ago is kept (with keep_existing, an id that already has a decision is left alone).
    Returns the decisions as saved."""
    with decisions_lock(sd):
        cur = load_decisions(sd)
        for k, v in changes.items():
            if not (keep_existing and k in cur):
                cur[k] = v
        if changes:
            save_decisions(sd, cur)
    return cur


def no_step(f):
    """One plain sentence for an approved finding that `fix` has no step for, ending in what to do next."""
    tool, applies = f.get("tool") or "?", f.get("applies")
    if tool == "vocallevel":
        return ("fix does not write vocal-level moves: make the change yourself in your DAW" + VOCALLEVEL_HINT)
    if not applies:
        return "this finding does not say how it is applied (no 'applies'): make the change by hand, or re-scan"
    return f"fix has no step for '{tool}' findings (applies: {applies}): make the change by hand, or re-scan"


def last_line(text, limit=200):
    """The last line of a command's output that says something (not a log pointer), cut to one plain sentence."""
    for l in reversed([x.strip() for x in str(text or "").splitlines()]):
        if l and not re.match(r"^(log|history):", l):
            return short_line(l, limit)
    return ""


def short_line(line, limit=200):
    """A line cut to `limit` characters without losing its end, where the reason usually is: a long path inside it
    shrinks to its file name first, and only then is the middle replaced by '...'."""
    if len(line) <= limit:
        return line
    line = re.sub(r"(['\"])((?:[A-Za-z]:)?[\\/][^'\"]*[\\/])([^'\"\\/]+)\1", r"\1\3\1", line)
    line = re.sub(r"(?<![\w.])(?:[A-Za-z]:)?[\\/](?:[^\\/\s'\"]+[\\/])+([^\\/\s'\"]+)", r"\1", line)
    if len(line) <= limit:
        return line
    keep = limit - 3
    head = keep // 3
    return line[:head] + "..." + line[len(line) - (keep - head):]


def free_dest(folder, name):
    """folder/name, or 'stem (clean 2).wav', 'stem (clean 3).wav' ...: the first name that does not exist yet."""
    folder, name = Path(folder), Path(name)
    cand, k = folder / name.name, 1
    while cand.exists():
        k += 1
        stem = name.stem
        stem = f"{stem[:-1]} {k})" if stem.endswith(")") else f"{stem} {k}"
        cand = folder / f"{stem}{name.suffix}"
    return cand


def move_new(tmp, folder):
    """Move everything a repair tool wrote into `tmp` to `folder`, never over a file that is already there (a taken
    name gets a number). Returns the new paths."""
    Path(folder).mkdir(parents=True, exist_ok=True)
    made = []
    for p in sorted(Path(tmp).iterdir()):
        dest = free_dest(folder, p.name)
        shutil.move(str(p), str(dest))
        made.append(dest)
    return made


def where_beats(where):
    """'13.3.09' (bar.beat.fraction, as the timing check prints it) -> beats from the start, or None."""
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", str(where or ""))
    return (int(m.group(1)) - 1) * 4 + (int(m.group(2)) - 1) + int(m.group(3)) / 100.0 if m else None


def timing_still(items, left, tol=0.2):
    """Which approved timing items are still measured after the fix. A nudge moves the hit, so its position text is
    not the same any more: each approved item is paired with the nearest remaining issue on its track (within `tol`
    beats), one to one. items: [(id, track, beat)]; left: [(track, beat)]. Returns the ids still measured."""
    pairs = sorted((abs(b - lb), i, j) for i, (_, tr, b) in enumerate(items) for j, (lt, lb) in enumerate(left)
                   if tr == lt and b is not None and lb is not None and abs(b - lb) <= tol)
    used_i, used_j, still = set(), set(), []
    for _, i, j in pairs:
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        still.append(items[i][0])
    return still


def flat(values):
    """Repeated options, each maybe a comma list, as one list: ["a,b", "c"] -> ["a", "b", "c"]."""
    out = []
    for v in [values] if isinstance(values, str) else (values or []):
        out += [x.strip() for x in str(v).split(",") if x.strip()]
    return out


def decision_of(dec, fid):
    d = dec.get(fid)
    return d.get("decision") if isinstance(d, dict) else d


def live_running():
    try:
        return subprocess.run(["pgrep", "-x", "Live"], capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


def recheck(tool, als, sd, scan, timing_tracks, tag, focus=None):
    """Analyse `als` again with `tool` (read-only) and return its findings in the scan's shape, or None.
    `focus`: the tracks the approved findings are on. `devices` then judges only those (its ids stay the whole set's), so
    the checks before and after a fix cost the tracks that changed, not every track of the set."""
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
        tjd_ = json.loads(tj.read_text(encoding="utf-8")) if tj.exists() else {}
        for t in tjd_.get("melodic", []):
            args += ["--melodic", t]
        for t in tjd_.get("bass", []):
            args += ["--bass", t]
        for t in tjd_.get("drums", []):
            args += ["--drums", t]
    if tool == "distortion" and scan.get("mix"):
        args += ["--mix", scan["mix"]]
    if tool in ("order", "tidy", "edges", "cliplevel", "duck", "devices"):
        args += ["--names", sd / "raw" / "names" / "names.json"]
    if tool == "devices" and focus and all(focus):
        for t in sorted(set(focus)):
            args += ["--focus", t]
    if tool == "motion":
        args += motion_args(sd, scan)
    if tool == "borrow":
        args += borrow_args(scan)
    if tool == "colour":
        args += colour_args(scan)
    hx(*args)
    if not j.exists():
        return None
    rows = json.loads(j.read_text(encoding="utf-8")).get("findings", [])
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


def colour_args(scan):
    """The options the colour proposals were made with, so a later run finds the same ones (ids are positions)."""
    return (["--mix", scan["mix"]] if scan.get("mix") else []) + [str(x) for x in scan.get("colour_args") or []]


def added_tracks(items):
    """Names of the tracks borrow and colour add on purpose (the structure check allows exactly these)."""
    from hypnomix.session import colour as CO
    return [f"{f['borrow']['track']} (from original)" for f in items if f["tool"] == "borrow"] + \
           [CO.track_name(f["colour"]) for f in items if f["tool"] == "colour"]


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


def apply_args(tool, cur, nxt, ids, items, sd, scan, dec, src, timing_tracks, timing_melodic, timing_low):
    """The command that applies these ids with `tool` from cur into nxt."""
    args = [tool, cur, "--apply", nxt, "--ids", ",".join(ids)]
    if tool == "timing":
        args += ["--list", "0"]
        for t in timing_tracks:
            args += ["--track", t]
        for t in timing_melodic:
            args += ["--melodic", t]
        for flag, t in timing_low:
            args += [flag, t]
        if any(f.get("unroll") for f in items):     # approved looped-clip items: unroll, then nudge
            args += ["--unroll-loops"]
    if tool == "distortion" and scan.get("mix"):
        args += ["--mix", scan["mix"]]
    if tool in ("order", "tidy", "edges", "cliplevel", "duck", "devices"):
        args += ["--names", sd / "raw" / "names" / "names.json"]
    if tool == "masking":           # the cuts come from the scan's own findings: no re-measuring (that would re-render everything)
        args += ["--findings", sd / "findings.json"]
    if tool == "tidy":              # archive the set as it was before this run, then tidy
        args += ["--archive-from", src]
        for f in items:
            note = ((dec.get(f["id"]) or {}).get("note") or "").strip()
            if note and f["id"] in ids:
                args += ["--tweak", f"{f['id']}:{note}"]
    if tool in ("motion", "borrow", "colour"):   # the person's fine controls from the review notes
        args += motion_args(sd, scan) if tool == "motion" else (borrow_args(scan) if tool == "borrow" else colour_args(scan))
        for f in items:
            note = ((dec.get(f["id"]) or {}).get("note") or "").strip()
            if note and f["id"] in ids:
                args += ["--tweak", f"{f['id']}:{note}"]
    return args


def take_scales(key_json, spans, out):
    """The scan's section-by-section key map, laid out in one take file's own time.

    The map says which scale each stretch of the SONG is in; a take is tuned as a file, in its own seconds. `spans`
    ([(song_t0, song_t1, take_t0, take_t1)], from the comp clips that play the take) say which part of the take
    sounds where in the song, so each played part of the take gets the scale of the section it is heard in. Parts
    of the take no clip plays keep the map's overall key."""
    d = json.loads(Path(key_json).read_text(encoding="utf-8"))
    rows = []
    for s0, s1, r0, r1 in spans:
        if s1 <= s0 or r1 <= r0:
            continue
        for sec in d.get("sections") or []:
            a, b = max(s0, sec["t0"]), min(s1, sec["t1"])
            if b <= a:
                continue
            to_take = lambda t: r0 + (t - s0) * (r1 - r0) / (s1 - s0)
            rows.append(dict(sec, t0=round(to_take(a), 4), t1=round(to_take(b), 4)))
    rows.sort(key=lambda x: x["t0"])
    merged = []
    for r in rows:                                            # a warped clip arrives in many small pieces
        if merged and merged[-1]["bars"] == r["bars"] and r["t0"] - merged[-1]["t1"] < 0.05:
            merged[-1]["t1"] = max(merged[-1]["t1"], r["t1"])
        else:
            merged.append(r)
    Path(out).write_text(json.dumps(dict(d, sections=merged), indent=1), encoding="utf-8")
    return merged


SEVERITIES = ("high", "medium", "low", "info")


def list_rows(findings, dec, severity=None, tool=None, undecided=False, offset=0, top=None):
    """The findings `--list` shows: filtered, then paged. Returns (rows, total matching)."""
    rows = [f for f in findings
            if (not severity or f.get("severity") == severity)
            and (not tool or f.get("tool") == tool)
            and (not undecided or (f["id"] not in dec and f.get("applies") not in ("info", "answer")))]
    total = len(rows)
    rows = rows[max(0, offset):]
    return (rows[:top] if top else rows), total


def list_line(f, dec):
    e = dec.get(f["id"]) if isinstance(dec.get(f["id"]), dict) else {}
    dd = (decision_of(dec, f["id"]) or "-") + (f"@{O.amount_of(e)}" if e.get("amount") is not None else "")
    who = f" by {e['by']}" if e.get("by") else ""
    conf = " CONFLICT" if e.get("conflicts") else ""
    return (f"{f['n']:4d}  {f['id']:<22} [{f.get('severity')}] {f.get('applies'):<6} "
            f"{dd:<12}{who}{conf} {'PROTECTED ' if f.get('protected') else ''}"
            f"{f['tool']}: {f.get('track') or '-'} {f.get('where', '')}  {str(f.get('problem'))[:80]}")


def describe_default(f, src):
    """One plain phrase for a finding that is applied because it is on by default."""
    kind = f.get("kind")
    if kind == "track-order":
        return "track order"
    if kind == "retire-off":
        n = len(f.get("retire") or [])
        try:
            from hypnomix.session import tidy as TD
            arch = TD.archive_path(src).name if src else "<name> (archive, all takes).als"
        except Exception:
            arch = "<name> (archive, all takes).als"
        return f"removes {n} switched-off track{'s' if n != 1 else ''}; a full copy is kept as '{arch}'"
    if kind == "consolidate":
        return f"puts one instrument's clips on one track: {f.get('track')}"
    if kind == "vocal-stack":
        return f"moves {f.get('where') or 'clips'} onto the track for their pitch"
    return f"{f.get('tool')} {kind}"


def planned_files(chosen, sd, src, out, orig, reaper_, verify=True):
    """Every file this run is about to create: [(path, what it is)]. Nothing is overwritten: all are new."""
    sd = Path(sd)
    rows = []
    if out is not None:
        rows.append((out, "the new project" if reaper_ else "the new set (the original is never touched)"))
    if src and not reaper_ and any(f.get("tool") == "tidy" for f in chosen):
        try:
            from hypnomix.session import tidy as TD
            rows.append((TD.archive_path(src), "a full copy of the set as it is now, written first so every take "
                                               "stays reachable (when the tidy step runs)"))
        except Exception:
            pass
    audio = [f for f in chosen if f.get("applies") == "audio"]
    for tool in sorted({f["plan"]["tool"] for f in audio if f.get("plan")}):
        rows.append((sd / "fixed" / tool, f"new audio files from the approved {tool} moves (a numbered folder if it exists)"))
    if any(f.get("tool") == "voices" and not f.get("plan") for f in audio):
        rows.append((sd / "fixed" / "voices", "balanced copies of the vocal parts (a numbered folder if it exists)"))
    if any(f.get("run") for f in audio):
        rows.append((sd / "fixed", "repaired copies of the recordings (the sources are never changed; a name that is "
                                   "taken gets a number)"))
    if any(f.get("tool") == "tune" for f in audio) and src:
        tdir = Path(src).parent / "Tuned" if reaper_ else Path(src).parent / "Samples" / "Tuned"
        rows.append((tdir, "one new tuned file per take (never over an existing one), with its notes (.notes.txt), "
                           "a picture (.png) and the chords it was checked against (.npz) beside it"))
    suffix = Path(src).suffix.lower() if src else ""
    set_tools = {f.get("tool") for f in chosen if f.get("applies") == "set"}
    if suffix not in (".rpp", ".ardour") and (set_tools & (set(ORDER) - {"masking"})):   # a Live set: its steps measure it again
        rows.append((sd / "raw" / "recheck-*.json", "the measurements taken before and after, to check the result"))
    if verify and suffix in (".rpp", ".ardour") and (set_tools & {"clips", "edges"}):
        rows.append((sd / "raw" / "verify.json", "the clip checks, run again on the new project to check the result"))
    rows.append((sd / "fix-log.md", "this run's log (added to the end)"))
    rows.append((sd / "decisions.json", "the decisions (the version before is kept as decisions.json.bak)"))
    if suffix in (".als", ".rpp", ".ardour") and (out is not None or any(f.get("applies") == "set" for f in chosen)):
        rows.append((sd / "history", "copies of the set before and after this run (for `hypnomix history`, undo)"))
    seen, uniq = set(), []
    for pth, what in rows:
        if str(pth) not in seen:
            seen.add(str(pth))
            uniq.append((pth, what))
    return uniq


def not_applied(sd, findings, dec, manual_items, skipped, zero, default_ids=(), gone=()):
    """The "Not applied" section: what fix did NOT do, and what the person should do next. Returns lines.
    gone: ids recorded as approved that are not in this scan's findings (an older scan's decisions)."""
    q = f'"{sd}"'
    changed = [f for f in findings if decision_of(dec, f["id"]) == "change"]
    L = []
    if changed:
        L += ["", f"  decided as \"change\" ({len(changed)}): HypnoMix changes nothing for these until you decide again"]
        for f in changed:
            note = ((dec.get(f["id"]) or {}).get("note") or "").strip()
            L.append(f"  - {f['id']} {f.get('track') or ''} {f.get('where', '')}: "
                     + (f'your note: "{note}"' if note else "no note recorded"))
            L.append(f"      next: agree what the change is, then record it: hypnomix fix {q} --decide {f['id']}=approve "
                     f'--note "..." (or {f["id"]}=skip to leave it)')
    hand = [f for f in manual_items if f.get("applies") == "manual"]
    info = [f for f in manual_items if f.get("applies") != "manual"]
    if hand:
        L += ["", f"  approved, but by hand ({len(hand)}): HypnoMix cannot make these changes"]
        for f in hand:
            L.append(f"  - {f['id']} {f.get('track') or ''} {f.get('where', '')}: {str(f.get('fix'))[:300]}")
            L.append("      next: make this change yourself in your DAW, then re-scan to check it is gone"
                     + (VOCALLEVEL_HINT if f.get("tool") == "vocallevel" else ""))
    if info:
        L += ["", f"  approved, but there is nothing to apply ({len(info)}): a measurement, or a question to answer"]
        for f in info:
            L.append(f"  - {f['id']} {f.get('track') or ''} {f.get('where', '')}: {str(f.get('fix'))[:300]}")
    if skipped:
        L += ["", f"  no longer found ({len(skipped)}): not applied, and never swapped for a neighbour"]
        for f, why in skipped:
            if f.get("id") in default_ids and why.startswith("no longer found"):
                # an on-by-default clean-up that an earlier clean-up already did: say so, not "no longer found"
                why = "nothing left to change here after the earlier clean-ups in this run"
            L.append(f"  - {f['id']} {f.get('track') or ''} {f.get('where', '')}: {why}")
        L.append(f"      next: re-scan the set (`hypnomix scan ...`), then decide again on what it finds now")
    if zero:
        L += ["", f"  approved at amount 0 ({len(zero)}): applies nothing"]
        for f in zero:
            L.append(f"  - {f['id']} {f.get('track') or ''} {f.get('where', '')}")
        L.append(f"      next: record an amount above 0 (hypnomix fix {q} --decide ID=approve@50), or skip it")
    if gone:
        L += ["", f"  approved, but not in this scan any more ({len(gone)}): not applied"]
        for g in gone:
            L.append(f"  - {g}: its id is not in findings.json (decided on an older scan?)")
        L.append(f"      next: re-scan, then decide again on what it finds now (hypnomix fix {q} --list --undecided)")
    n = len(changed) + len(manual_items) + len(skipped) + len(zero) + len(gone)
    return ([f"Not applied ({n}):"] + L) if n else []


def main():
    ap = argparse.ArgumentParser(prog="hypnomix fix", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    from hypnomix.session import liveversion as LV; LV.add_force_flag(ap)
    ap.add_argument("scan_dir")
    ap.add_argument("--approve", action="append", default=[], metavar="ID[,ID...]",
                    help="finding ids (or item numbers) to apply; repeatable, each may be a comma list")
    ap.add_argument("--approved", action="store_true", help="apply every finding recorded as approved in decisions.json")
    ap.add_argument("--decide", action="append", default=[], metavar="ID=DECISION[,ID=...]",
                    help="record decisions and exit: ID=approve|skip|change; repeatable, each may be a comma list")
    ap.add_argument("--note", default="", help="with --decide: the person's reason or requested change")
    ap.add_argument("--out", help='new set to write, e.g. "Song (fixed).als", "Song (fixed).rpp" or "Song (fixed).ardour" (same folder as the original)')
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
    ap.add_argument("--severity", choices=SEVERITIES, help="with --list: only this severity")
    ap.add_argument("--tool", help="with --list: only findings of this tool (smooth, timing, tune ...)")
    ap.add_argument("--undecided", action="store_true", help="with --list: only findings with no decision yet")
    from hypnomix.core import args as A
    ap.add_argument("--top", type=A.whole(1), metavar="N", help="with --list: show only N findings")
    ap.add_argument("--offset", type=A.whole(0), default=0, metavar="N", help="with --list: skip the first N (to page)")
    ap.add_argument("--show", metavar="ID", help="print one finding in full (id or item number) and exit")
    ap.add_argument("--no-defaults", action="store_true", help="with --approved: apply only what was approved by "
                    "name; leave out the clean-ups that are on by default (track order, switched-off tracks)")
    ap.add_argument("--decide-like", default="", metavar="ID=approve[@AMOUNT]",
                    help="the same decision for every undecided finding like ID (lists them first)")
    ap.add_argument("--band", type=float, default=50.0, help="with --decide-like: how close in size (percent, default 50)")
    ap.add_argument("--dry-run", action="store_true", help="write nothing: with --decide-like list the matches, with "
                    "--decide say what would be recorded, with --approve / --approved print what would be written")
    ap.add_argument("--as", dest="by", metavar="NAME", help="who is deciding (default: prefs review.name)")
    a = ap.parse_args()
    sd = Path(a.scan_dir)
    data = AT.load_json(sd / "findings.json")
    if not data or "findings" not in data:
        sys.exit(f"no findings.json in {sd}: run `hypnomix scan` first")
    scan = AT.load_json(sd / "scan.json", {})
    findings = data["findings"]
    dec = load_decisions(sd)
    by_key = {f["id"]: f for f in findings}
    by_key.update({str(f["n"]): f for f in findings})

    if a.show:
        if a.show not in by_key:
            sys.exit(f"unknown id: {a.show}")
        from hypnomix.workflow import scan as SC
        print(SC.show_item(sd, by_key[a.show], findings, dec))
        return

    if a.list:
        rows, total = list_rows(findings, dec, a.severity, a.tool, a.undecided, a.offset, a.top)
        for f in rows:
            print(list_line(f, dec))
        if a.severity or a.tool or a.undecided or a.top or a.offset:
            nxt = a.offset + len(rows)
            print(f"-- {len(rows)} of {total} matching finding(s)" + (f"; next page: --offset {nxt}" if nxt < total else "")
                  + (f"; {len(findings)} in the scan" if total != len(findings) else ""))
        return

    key_json = sd / "raw" / "key.json"
    if a.answer:
        if not key_json.exists():
            sys.exit("this scan has no key map (raw/key.json): re-scan the vocals group")
        from hypnomix.studio.tune import load_scales
        answers = scan.get("answers", []) + a.answer
        _, open_q = load_scales(key_json, answers)          # checks every answer against its question
        scan["answers"] = answers
        if not a.dry_run:
            AT.write_json(sd / "scan.json", scan)
        print(f"answers {'checked, not saved (dry run)' if a.dry_run else 'saved'}: {', '.join(answers)}")
        print("still open: " + "; ".join(open_q) if open_q else "every key question is answered: tune with --key sections")
        if not (a.approve or a.approved):
            return

    if a.decide_like:
        if "=" not in a.decide_like:
            sys.exit(f"expected ID=decision[@amount], got {a.decide_like!r}")
        k, v = (x.strip() for x in a.decide_like.split("=", 1))
        if k not in by_key:
            sys.exit(f"unknown id: {k}")
        try:
            what, amt = O.parse_decision(v)
        except ValueError as e:
            sys.exit(str(e))
        ex = by_key[k]
        matched = O.like(findings, dec, ex, band=a.band / 100.0, role_of=O.roles(sd))
        sz = O.size(ex)
        print(f"like {ex['id']} ({ex['tool']} {ex.get('kind')}" + (f", size {sz:g}" if sz is not None else "")
              + f", band +-{a.band:g}%): {len(matched)} undecided finding(s)")
        for f in matched:
            s_ = O.size(f)
            print(f"  {f['id']:<22} [{f.get('severity')}] {f.get('track') or '-'} {f.get('where', '')}"
                  + (f"  size {s_:g}" if s_ is not None else "") + f"  {str(f.get('problem'))[:70]}")
        if amt is not None and amt not in (0, 100) and not O.scalable(ex)[0]:
            print(f"note: {ex['tool']} {ex.get('kind')} can't be scaled ({O.scalable(ex)[1]}): any amount above 0 applies it in full")
        if a.dry_run:
            print("dry run: nothing recorded")
            return
        targets = ([ex] if not decision_of(dec, ex["id"]) else []) + matched
        record(sd, {f["id"]: O.entry(what, a.note, amt, by=a.by, via=None if f is ex else f"like:{ex['id']}")
                    for f in targets})
        print(f"recorded {what}" + (f"@{amt}" if amt is not None else "") + f" for {len(targets)} finding(s); "
              "a decision made on one of them later wins")
        return

    if a.decide:
        changes = {}
        for item in flat(a.decide):
            if "=" not in item:
                sys.exit(f"expected ID=decision, got {item!r}")
            k, v = (x.strip() for x in item.split("=", 1))
            if k not in by_key:
                sys.exit(f"unknown id: {k}")
            try:
                what, amt = O.parse_decision(v)
            except ValueError as e:
                sys.exit(str(e))
            f = by_key[k]
            if amt is not None and amt not in (0, 100) and what != "skip" and not O.scalable(f)[0]:
                print(f"note: {f['id']} ({f['tool']} {f.get('kind')}) can't be scaled ({O.scalable(f)[1]}): "
                      "any amount above 0 applies it in full")
            changes[f["id"]] = O.entry(what, a.note, amt, by=a.by)
        if a.dry_run:
            print("dry run: would record " + ", ".join(f"{k}={decision_of(changes, k)}" for k in changes) + "; nothing recorded")
            return
        dec = record(sd, changes)
        n = {d: sum(1 for k in dec if decision_of(dec, k) == d) for d in DECISIONS}
        left = sum(1 for f in findings if f.get("applies") not in ("info", "answer") and f["id"] not in dec)
        print(f"recorded. approve {n['approve']}, skip {n['skip']}, change {n['change']}; {left} still undecided")
        return

    want = set(flat(a.approve))
    unknown = sorted(w for w in want if w not in by_key)
    if unknown:
        sys.exit(f"unknown ids: {', '.join(unknown)}")
    want = {by_key[w]["id"] for w in want}
    dflt, gone = set(), []
    if a.approved:
        want |= {k for k in dec if decision_of(dec, k) == "approve" and k in by_key}
        gone = sorted(k for k in dec if decision_of(dec, k) == "approve" and k not in by_key)   # an older scan's ids
        # on-by-default clean-up (track order, vocal stacks): included unless the person skipped it
        dflt = {f["id"] for f in findings if f.get("default") == "approve" and f["id"] not in dec}
        if a.no_defaults:
            if dflt:
                print(f"--no-defaults: left out the clean-ups that are on by default: {', '.join(sorted(dflt))}")
            dflt = set()
        want |= dflt
    if not want:
        waiting = [f for f in findings if decision_of(dec, f["id"]) == "change"]
        if waiting:
            print("Not applied: " + ", ".join(f["id"] for f in waiting) + " (decided as \"change\"): agree the change, "
                  "then record it with --decide ID=approve --note \"...\" (or ID=skip)")
        sys.exit("nothing approved: pass --approve ID,ID,... or record decisions with --decide and use --approved")
    refused = sorted(w for w in want if decision_of(dec, w) in ("skip", "change"))
    if refused:
        sys.exit(f"these were recorded as skip/change, not approve: {', '.join(refused)}. "
                 "Record the new decision with --decide first.")
    chosen = [by_key[w] for w in sorted(want)]
    amounts = {f["id"]: O.effective_amount(f, dec.get(f["id"])) for f in chosen}
    zero = [f for f in chosen if amounts[f["id"]] == 0]
    chosen = [f for f in chosen if amounts[f["id"]] > 0]
    for f in chosen:
        raw_amt = O.amount_of(dec.get(f["id"]))
        if raw_amt != amounts[f["id"]] and not O.scalable(f)[0]:
            print(f"note: {f['id']} can't be scaled ({O.scalable(f)[1]}); applying it in full, not {raw_amt}%")
    if zero:
        print(f"amount 0, not applied: {', '.join(f['id'] for f in zero)}")
    if not chosen:
        sys.exit("nothing to apply: every approved item has amount 0")
    prot = [f["id"] for f in chosen if f.get("protected")]
    if prot and not a.allow_protected:
        sys.exit(f"on protected tracks: {', '.join(prot)}. Ask the person again, then add --allow-protected.")

    name_items = [f for f in chosen if f.get("tool") == "name"]       # renamed last: every other step finds tracks by name
    set_items = [f for f in chosen if f.get("applies") == "set" and f.get("tool") != "name"]
    audio_items = [f for f in chosen if f.get("applies") == "audio"]
    manual_items = [f for f in chosen if f.get("applies") in ("manual", "info", "answer")]   # nothing for fix to write
    folder_mode = scan.get("mode") in ("folder", "file")
    orig = Path(data["set"]) if data.get("set") and not folder_mode else None
    if folder_mode and a.out:
        print(f"note: --out is not used for a scan of a folder or a file: repaired copies go to {sd / 'fixed'}")
    src = Path(a.from_set).resolve() if a.from_set else orig
    out = None
    # an approved finding no step of this command can write (a kind this version does not know, a hand-made entry
    # with no 'applies'): never dropped quietly. It is reported as not done, and the run exits with 1.
    known = {id(f) for f in name_items + set_items + audio_items + manual_items}
    stuck = [(f, no_step(f)) for f in chosen if id(f) not in known]
    if not (orig is not None and orig.suffix.lower() in (".rpp", ".ardour")):    # REAPER / Ardour: their writers say it themselves
        stuck += [(f, no_step(f)) for f in set_items if f.get("tool") not in ORDER]
        set_items = [f for f in set_items if f.get("tool") in ORDER]

    if orig and (set_items or audio_items or name_items):
        if not orig.exists():
            sys.exit(f"the scanned set is gone: {orig}")
        if src.resolve().parent != orig.resolve().parent:
            sys.exit(f"--from must be in the same folder as the scanned set ({orig.parent})")
        was = scan.get("set_mtime")
        if was and not a.from_set and abs(orig.stat().st_mtime - was) > 1 and not a.stale_ok:
            sys.exit("the set was saved again after the scan, so the findings may not match it any more.\n"
                     "Re-scan it (recommended), or pass --stale-ok if the change cannot affect these findings.")
    reaper_ = orig is not None and orig.suffix.lower() == ".rpp"
    ardour_ = orig is not None and orig.suffix.lower() == ".ardour"
    if ardour_ and any(f.get("tool") == "tune" for f in audio_items):
        sys.exit("tuning is not written into a HypnoMix Studio session yet: untick the tune items (the other fixes can go ahead)")
    # harmony balance is written as volume automation into a LIVE set only; in a REAPER project or an Ardour session
    # it is balanced copies of the parts (SCAN_DIR/fixed/voices) like in a folder of stems
    voices_in_set = bool(orig) and not reaper_ and not ardour_ and any(f.get("tool") == "voices" for f in audio_items)
    if folder_mode and any(f.get("run") for f in audio_items) and not Path(data.get("set") or "").exists():
        sys.exit(f"the scanned folder is gone: {data.get('set')}. Move it back, or scan it again where it is now.")
    tune_rpp = reaper_ and any(f.get("tool") == "tune" for f in audio_items)
    # tuning in a Live set also writes a new set (the comp clips play the tuned takes), so it needs --out too
    tune_als = orig is not None and not reaper_ and any(f.get("tool") == "tune" for f in audio_items)
    if set_items or name_items or voices_in_set or tune_rpp or tune_als:
        if not orig:
            sys.exit("this scan has no Live set: set changes cannot be applied")
        if not a.out:
            sys.exit("approved set changes need --out NEW" + (".rpp" if reaper_ else ".ardour" if ardour_ else ".als"))
        out = Path(a.out)
        if not out.is_absolute():
            here = out.resolve()                  # a path from where you are that already points into the project's folder
            out = here if here.parent == src.resolve().parent else src.parent / out    # else a name beside the project
        out = Path(os.path.normpath(str(out)))    # "a/../b.als" is "b.als"
        if out.resolve().parent != src.resolve().parent:
            sys.exit(f"--out must be in the same folder as the original ({src.parent}); {a.out!r} points at {out.parent}")
        if out.resolve() in (src.resolve(), orig.resolve()):
            sys.exit("refusing to overwrite the original set")
        if out.exists():
            sys.exit(f"{out.name} already exists: choose a new name (nothing is ever overwritten)")
    name_out = out
    if reaper_ and out is not None and out.suffix.lower() != ".rpp":
        sys.exit("a REAPER project is written as a new .rpp: give --out \"<Song> (fixed).rpp\"")
    if out is not None and not reaper_ and not ardour_ and out.suffix.lower() != ".als":
        sys.exit("a Live set is written as a new .als: give --out \"<Song> (fixed).als\"")
    if ardour_ and out is not None and out.suffix.lower() != ".ardour":
        sys.exit("a HypnoMix Studio session is written as a new snapshot: give --out \"<Session> (fixed).ardour\" "
                 "(it is saved next to the original, inside the session folder)")
    if orig and not reaper_ and not ardour_ and (set_items or audio_items or name_items) and live_running():
        print("NOTE: Live is running. Changes not saved in Live are not in the file being read, and the set "
              "must be closed in Live before the new one is opened.\n")

    # say what is about to be written, and which clean-ups are only here because they are on by default
    defaults_used = [f for f in chosen if f["id"] in dflt]
    if defaults_used:
        print("Also applied because they are on by default (skip them to opt out, or pass --no-defaults): "
              + ", ".join(f"{f['id']} ({describe_default(f, src)})" for f in defaults_used))
    doing = [f for f in chosen if id(f) not in {id(s) for s, _ in stuck}]
    files = planned_files(doing, sd, src, out, orig, reaper_, verify=not a.no_verify)
    print("About to write (all new; nothing existing is overwritten):")
    for pth, what in files:
        print(f"  {pth}  <- {what}")
    print()
    if a.dry_run:
        print("Would try to apply: " + (", ".join(f["id"] for f in doing) or "nothing")
              + " (a step can still refuse when it runs, for example a tune with no chord source)")
        for f, why in stuck:
            print(f"Would not apply {f['id']}: {why}")
        print("dry run: nothing was written (no set, no log, no history, no decisions)")
        return

    new_dec = {f["id"]: O.entry("approve", "via --approve", by=a.by) for f in chosen if f["id"] not in dec}
    dec.update(record(sd, new_dec, keep_existing=True))      # an explicit --approve is a decision too
    tag = lambda f: f["id"] + (f"@{amounts[f['id']]}" if amounts[f["id"]] != 100 else "")
    log = [f"\n## fix run {time.strftime('%Y-%m-%d %H:%M')}", "",
           "approved: " + ", ".join(tag(f) for f in chosen), ""]
    failed, skipped_all = [f"{f['id']}: {why}" for f, why in stuck], []
    wrote_any = False            # set true by every step that really wrote something: only then is the run a version in history

    if reaper_ and (set_items or name_items or tune_rpp):   # REAPER: one pass into one new .rpp (fix_project.py)
        from hypnomix.workflow import fix_project as FP
        tune_items = [f for f in audio_items if f.get("tool") == "tune"]
        wrote, l2, f2, s2 = FP.run(sd, scan, src, out, set_items + name_items, tune_items, dec,
                                   a.key or scan.get("key"), verify=not a.no_verify)
        name_items = []
        log += l2
        failed += f2
        skipped_all += s2
        audio_items = [f for f in audio_items if f.get("tool") != "tune"]
        set_items = []
        out = wrote
        wrote_any = wrote_any or bool(wrote)
    if ardour_ and (set_items or name_items):    # Ardour: one pass into one new .ardour (fix_ardour.py)
        from hypnomix.workflow import fix_ardour as FA
        wrote, l2, f2, s2 = FA.run(sd, scan, src, out, set_items + name_items, dec, verify=not a.no_verify)
        name_items = []
        log += l2
        failed += f2
        skipped_all += s2
        set_items = []
        out = wrote
        wrote_any = wrote_any or bool(wrote)
    if set_items:
        tj = sd / "raw" / "timing.json"
        tjd = json.loads(tj.read_text(encoding="utf-8")) if tj.exists() else {}
        timing_tracks, timing_melodic = tjd.get("tracks", []), tjd.get("melodic", [])
        timing_low = [("--bass", t) for t in tjd.get("bass", [])] + [("--drums", t) for t in tjd.get("drums", [])]
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
                        amt = amounts[f["id"]]
                        made = target if amt >= 100 else target.with_name(target.stem + " full.als")
                        temps.append(made)
                        c, t = hx("sidechain", tmp, "--host", f["host"], "--apply", made, *extra)
                        txt += t + "\n"
                        if c == 0 and made.exists() and made != target:
                            ns, nk = O.blend(tmp, made, target, amt / 100.0)
                            txt += f"amount {amt}%: {ns} value(s) moved {amt}% of the way, {nk} kept as written\n"
                        if c == 0 and target.exists():
                            tmp = target
                        else:
                            failed.append(f"{f['id']}: sidechain on {f['host']} failed")
                    ok = tmp != cur
                    if ok:
                        shutil.copyfile(tmp, nxt)
                else:
                    # one pass per amount (most items are 100%): each pass is re-checked on the set as it now is,
                    # so ids from an earlier pass are never reused
                    groups = {}
                    for f in items:
                        groups.setdefault(amounts[f["id"]], []).append(f)
                    gcur, any_ids, n_skip, broke = cur, False, 0, False
                    for gi, (amt, gitems) in enumerate(sorted(groups.items(), key=lambda kv: -kv[0])):
                        if tool == "masking":    # the finding IS the cut: the writer checks the track and an equal cut itself
                            ids, skipped = [f["id"] for f in gitems], []
                        else:
                            now = recheck(tool, gcur, sd, scan, timing_tracks, f"pre{step}" + (f".{gi}" if gi else ""),
                                          focus=[f.get("track") for f in gitems])
                            if now is None:
                                failed += [f"{f['id']}: could not re-check the set with {tool}" for f in gitems]
                                broke = True
                                continue
                            ids, skipped = rematch(gitems, now)
                        skipped_all += skipped
                        n_skip += len(skipped)
                        if not ids:
                            continue
                        any_ids = True
                        gnxt = src.parent / f"{src.stem} (fix step {step}.{gi}).als"
                        temps.append(gnxt)
                        mode = (O.SCALING.get(tool) or (None,))[0] if amt < 100 else None
                        made = gnxt
                        if mode == "blend":
                            made = src.parent / f"{src.stem} (fix step {step}.{gi} full).als"
                            temps.append(made)
                        args = apply_args(tool, gcur, made, ids, gitems, sd, scan, dec, src, timing_tracks,
                                          timing_melodic, timing_low)
                        if mode == "flags":
                            args += O.amount_flags(tool, amt)
                        code, t_ = hx(*args)
                        txt += t_ + "\n"
                        if tool == "masking":
                            for m_ in re.finditer(r"^- (\S+): not written: (.*)$", t_, re.M):   # what the writer left out
                                skipped_all += [(f, m_.group(2)) for f in gitems if f["id"] == m_.group(1)]
                            if code == 0 and not made.exists():      # every cut was already there: nothing to write
                                any_ids, n_skip = gcur != cur, n_skip + len(gitems)
                                continue
                        if code != 0 or not made.exists():
                            why_ = next((l.strip() for l in t_.splitlines() if l.startswith("this set was saved by Live")), "")
                            failed += [f"{f['id']}: {tool} --apply failed" + (f": {why_}" if why_ else "") for f in gitems]
                            continue
                        if mode == "blend":
                            ns, nk = O.blend(gcur, made, gnxt, amt / 100.0)
                            txt += f"amount {amt}%: {ns} value(s) moved {amt}% of the way, {nk} kept as written\n"
                            print(f"{tool:<11} amount {amt}%: {ns} value(s) scaled"
                                  + (f", {nk} kept in full (added or switches)" if nk else ""))
                        elif mode == "flags":
                            txt += f"amount {amt}%: {' '.join(O.amount_flags(tool, amt))}\n"
                        gcur = gnxt
                    if not any_ids and not broke:
                        log += [f"### {tool}: nothing to apply (see skipped)", ""]
                        print(f"{tool:<11} nothing to apply ({n_skip} skipped)")
                        continue
                    if broke and gcur == cur:
                        log += [f"### {tool}: FAILED (re-check did not run)", ""]
                        print(f"{tool:<11} FAILED  (re-check did not run)")
                        continue
                    ok = gcur != cur          # a pass that failed is listed under FAILED; the others still apply
                    if ok:
                        shutil.copyfile(gcur, nxt)
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
            added = added_tracks(set_items)
            errs, warns, _ = C.check(out, src, reordered="order" in applied_tools, added=added,
                                   allow_removed="tidy" in applied_tools)
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
                if tool == "masking":
                    line = ("- masking: the cuts are written as EQ bands (listed above); a frequency fight is only measured "
                            "again by a new `scan --deep` (it renders every track): listen to each part that gave way")
                    print("verify     " + line[2:])
                    log.append(line)
                    continue
                if tool in ("motion", "borrow", "colour"):   # options, not problems: report what was written instead of re-measuring
                    line = (f"- {tool}: approved " + ("moves written as automation / clip edits" if tool == "motion" else
                            "loops added on new switched-off tracks" if tool == "borrow" else
                            "colour chains added on new switched-off tracks") + " (listed above); listen to each")
                    print("verify     " + line[2:])
                    log.append(line)
                    continue
                items = [f for f in set_items if f["tool"] == tool]
                now = recheck(tool, out, sd, scan, timing_tracks, "post", focus=[f.get("track") for f in items])
                if now is None:
                    line = f"- {tool}: could not be re-checked"
                else:
                    if tool == "timing":      # a nudge moves the hit, so its position text changes: pair by nearest hit
                        still = timing_still([(f["id"], f.get("track") or "", where_beats(f.get("where"))) for f in items],
                                             [(r.get("track") or "", where_beats(r.get("where"))) for r in now])
                    else:
                        left = {fingerprint(r) for r in now}
                        still = [f["id"] for f in items if fingerprint(f) in left]
                    line = (f"- {tool}: {len(items) - len(still)} of {len(items)} approved problems no longer measured"
                            + (f"; still measured: {', '.join(still)} (listen there: a gentle fix can leave a "
                               f"smaller version of the problem)" if still else ""))
                print("verify     " + line[2:])
                log.append(line)
            log.append("")

    # ---- harmony balance from a set: written as track volume automation (after each chain), before the renames
    voices_set = [f for f in audio_items if f.get("tool") == "voices" and orig is not None and not reaper_ and not ardour_]
    if voices_set:
        if not a.out:
            failed += [f"{f['id']}: harmony balance into the set needs --out NEW.als" for f in voices_set]
        else:
            target = name_out                              # validated above: new, next to the original
            base = target if target.exists() else src     # it exists only if this run's set steps wrote it
            for f in voices_set:
                note = ((dec.get(f["id"]) or {}).get("note") or "")
                kv = dict(x.split("=", 1) for x in note.replace(",", " ").split() if "=" in x)
                tmp = target.with_name(target.stem + " (voices step).als")
                args = ["voices", *f["stems"], "--tame", "--set", base, "--apply-set", tmp, "--out", sd / "fixed" / "voices"]
                for key_ in ("tolerance", "lead-margin", "max-cut", "root-raise", "root-step", "upper-step"):
                    if key_ in kv:
                        args += [f"--{key_}", kv[key_]]
                if f.get("lead"):
                    args += ["--lead", f["lead"]]
                if scan.get("tempo"):
                    args += ["--bpm", scan["tempo"]]
                code, txt = hx(*args)
                ok = code == 0 and tmp.exists()
                if ok:
                    shutil.move(str(tmp), str(target))
                    base = target
                    from hypnomix.session import check as C
                    errs, _, _ = C.check(target, src)
                    if errs:
                        bad = target.with_name(target.stem + " (BROKEN, do not open).als")
                        target.rename(bad)
                        failed += [f"structure check after harmony balance: {e}" for e in errs]
                        print(f"check      FAILED after harmony balance: renamed to {bad.name}; keep using the original.")
                        ok = False
                    else:
                        print(f"check      structure OK after harmony balance")
                log += [f"### {f['id']} harmony balance (volume automation): {'written' if ok else 'FAILED'}", "",
                        "```", txt.strip()[-1500:], "```", ""]
                spacing = next((l for l in txt.splitlines() if l.startswith("spacing")), "")
                print(f"voices     {'ok' if ok else 'FAILED'}  volume automation in {target.name}" + (f"\n           {spacing}" if spacing else ""))
                if not ok:
                    failed.append(f"{f['id']}: voices failed")
        audio_items = [f for f in audio_items if f not in voices_set]

    # ---- track names, last (into the new set, or a new set of their own)
    if name_items:
        from hypnomix.session.names import rename_set
        mapping = {}
        if "tidy" in (locals().get("applied_tools") or []):   # tracks the clean-up retired or merged away
            kept_n = {x.strip() for f in set_items if f.get("id") == "retire-1"
                      for x in re.split(r"[:,]", ((dec.get(f["id"]) or {}).get("note") or ""))[1:]}
            gone_n = {n for f in set_items if f.get("id") == "retire-1" for n in f.get("retire", []) if n not in kept_n}
            gone_n |= {f["track"].split(" → ")[0] for f in set_items if f.get("kind") == "consolidate" and f.get("removes")}
            name_items = [f for f in name_items if f["old"] not in gone_n]
        for f in name_items:
            note = ((dec.get(f["id"]) or {}).get("note") or "").strip()
            mapping[f["old"]] = note or f["new"]
            if f.get("kind") == "track-name-question" and not note:
                print(f"name       {f['old']}: approved without a name from the person; using the guess {f['new']!r}")
        target = name_out
        base = target if Path(target).exists() else src            # build on what this run already wrote
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
                                 allow_removed=any(f["tool"] == "tidy" for f in set_items),
                                 added=added_tracks(set_items))
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
            kf.write_text(json.dumps(sorted(f["plan"]["key"] for f in items)), encoding="utf-8")
            code, txt = hx("automix", source, "--no-prep", "--no-master", "--only", kf, "--out", dest)
        elif tool == "balance":
            kf = sd / "raw" / "approved-balance.json"
            kf.parent.mkdir(parents=True, exist_ok=True)
            kf.write_text(json.dumps({f["track"]: f["plan"]["gain_db"] for f in items}), encoding="utf-8")
            code, txt = hx("balance", source, "--only", kf, "--out", dest)
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
            failed.append(f"{ids}: {tool} failed on {Path(source).name}: {last_line(txt)}")
        else:
            wrote_any = True

    for f in audio_items:
        if f.get("tool") == "voices":  # harmony balance: only with the settings the person chose
            note = ((dec.get(f["id"]) or {}).get("note") or "")
            kv = dict(x.split("=", 1) for x in note.replace(",", " ").split() if "=" in x)
            dest = sd / "fixed" / "voices"
            k = 1
            while dest.exists():
                k += 1
                dest = sd / "fixed" / f"voices {k}"
            if "anchor" not in kv:      # approved as suggested: the person's own spacing (voices --learn), else 1.5 dB
                args = ["voices", *f["stems"], "--tame", "--out", dest]
                for key_ in ("tolerance", "lead-margin", "max-cut"):
                    if key_ in kv:
                        args += [f"--{key_}", kv[key_]]
            else:
                args = ["voices", *f["stems"], "--anchor", kv["anchor"] if kv["anchor"] != "lead" or not f.get("lead") else f["lead"],
                        "--reduce", kv.get("reduce", "above"), "--above-db", kv.get("above", "0"),
                        "--below-db", kv.get("below", "0"), "--spread", kv.get("spread", "ladder"),
                        "--max-cut", kv.get("max-cut", "6"), "--tolerance", kv.get("tolerance", "1.5"),
                        "--lead-margin", kv.get("lead-margin", "0"), "--out", dest]
            if f.get("lead"):
                args += ["--lead", f["lead"]]
            for nm, db in (f.get("faders") or {}).items():   # renders are raw clips: compare levels as heard
                args += ["--fader", f"{nm}={db}"]
            if scan.get("tempo"):
                args += ["--bpm", scan["tempo"]]
            code, txt = hx(*args)
            ok = code == 0
            log += [f"### {f['id']} harmony balance ({note}): {'written to ' + str(dest) if ok else 'FAILED'}", "",
                    "```", txt.strip()[-1500:], "```", ""]
            print(f"voices     {'ok' if ok else 'FAILED'}  {note}" + (f"  → {dest}" if ok else ""))
            if ok:
                wrote_any = True
                print("           balanced copies of each part: put them on new tracks, mute the originals, A/B")
            else:
                failed.append(f"{f['id']}: voices failed")
            continue
        if f.get("run"):  # folder scan: a repaired copy into SCAN_DIR/fixed, never over a file that is already there
            fixed = sd / "fixed"
            fixed.mkdir(exist_ok=True)
            # album keeps a steps file in its output folder (a later move builds on the file the last one wrote) and
            # numbers its own files; every other repair tool writes into a fresh folder, and names are chosen after
            direct = f.get("tool") == "album"
            before = {p.name for p in fixed.iterdir()}
            work = fixed if direct else Path(tempfile.mkdtemp(prefix=".new-", dir=str(fixed)))
            try:
                code, txt = hx(*[str(x).replace("{out}", str(work)) for x in f["run"]])
                if code != 0:
                    made = []
                elif direct:
                    made = sorted(p for p in fixed.iterdir() if p.name not in before and not p.name.startswith("."))
                else:
                    made = move_new(work, fixed)
            finally:
                if not direct:
                    shutil.rmtree(work, ignore_errors=True)
            ok = code == 0 and (bool(made) or direct)         # album says "already applied" and writes nothing new
            why = last_line(txt) if code != 0 else "the tool ran but wrote no file"
            log += [f"### {f['id']} {f.get('track')}: {'written to ' + str(fixed) if ok else 'FAILED'}", "", "```",
                    txt.replace(str(work), str(fixed)).strip()[-1200:], "```", ""]
            if ok and made:
                log.append("files: " + ", ".join(m.name for m in made))
                log.append("")
            print(f"{f['tool']:<11} {'ok' if ok else 'FAILED'}  {f.get('track')}"
                  + (f"  → {', '.join(str(m) for m in made) if made else fixed}" if ok else f": {why}"))
            if not ok:
                failed.append(f"{f['id']}: {f['tool']} failed: {why}")
            elif made:
                wrote_any = True
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
        # pitch correction goes on the TAKES under the comp clips: each take file is tuned into a new file of the
        # same length and, in the new set, this track's comp clips play it. The comp stays exactly as it was
        # (positions, edges, fades, warp, gain); no rendered copy of the track is made or swapped in
        by_section = "--scales" in [str(x) for x in tune_key]    # the key map is in song time: laid out per take below
        import gzip as _gz, xml.etree.ElementTree as _ET
        from hypnomix.core.gz import read_gz
        from hypnomix.session import sources as SRC, check as C
        target = name_out
        base = target if Path(target).exists() else src
        root_t = _ET.fromstring(read_gz(base))
        from hypnomix.session import liveversion as LV
        try:
            LV.check_write(root_t)                # refuse before any take is tuned: no files are left behind
        except LV.NewerLive as e:
            failed.append(f"{f['id']}: not tuned: {e}")
            print(f"tune       REFUSED  {f['track']}: this set was saved by a newer Live than HypnoMix has been tested with")
            continue
        tname = f["track"]
        if SRC.find_track(root_t, tname) is None:            # renamed earlier in this run
            tname = next((n_ for o_, n_ in (locals().get("done_n") or []) if o_ == tname), tname)
        takes = SRC.track_sources(root_t, tname, base)
        if not takes:
            failed.append(f"{f['id']}: {f['track']} has no enabled clips to tune")
            continue
        tdir = src.parent / "Samples" / "Tuned"
        tdir.mkdir(parents=True, exist_ok=True)
        done_files = 0
        # the chord check: the chord under every note, read in song time from the instrumental (else the mix) and
        # laid out in each take's own time through the comp clips, so tune can ask instead of moving a note
        # toward a pitch that clashes with the chord underneath
        from hypnomix.studio import chords as CHD
        chord_src = scan.get("backing") or scan.get("ref")
        song_ch = CHD.chroma(chord_src) if chord_src and Path(chord_src).exists() else None
        tempo_el = root_t.find(".//Tempo/Manual")
        tempo = float(tempo_el.get("Value")) if tempo_el is not None else 120.0
        if song_ch is None:
            failed.append(f"{f['id']}: not tuned: no instrumental or mix in the scan to read the chords from "
                          "(re-scan with --backing INSTRUMENTAL.wav)")
            print(f"tune       REFUSED  {f['track']}: no chord source (scan --backing INSTRUMENTAL.wav)")
            continue
        for take, clips in takes.items():
            if not take.exists():
                failed.append(f"{f['id']}: take file not found: {take.name}")
                continue
            dest, k = tdir / f"{safe_name(take.stem)} (tuned).wav", 1
            while dest.exists():
                k += 1
                dest = tdir / f"{safe_name(take.stem)} (tuned {k}).wav"
            import soundfile as _sf
            spans = [sp for c_ in clips for sp in SRC.song_spans(c_, tempo)]
            take_ch = CHD.take_time(song_ch, spans, int(_sf.info(str(take)).duration / CHD.HOP_S) + 1)
            sfx = "" if k == 1 else f" {k}"                  # the side files follow the tuned file's number: none is overwritten
            chord_npz = tdir / f"{safe_name(take.stem)} (chords{sfx}).npz"
            CHD.save(chord_npz, take_ch)
            take_key = tune_key
            if by_section:
                tk = tdir / f"{safe_name(take.stem)} (key map{sfx}).json"
                secs_t = take_scales(key_json, spans, tk)
                # only the answers that are about a section this take is heard in (tune refuses any other)
                from hypnomix.studio.tune import _pc
                uns = [x for x in secs_t if x.get("unsure") and x.get("disputed")]
                def about(ans):
                    bars, _, note = ans.rpartition("=")
                    if bars:
                        return any(x["bars"] == bars.strip() for x in uns)
                    if note.strip().lower() == "both":
                        return bool(uns)
                    return any(_pc(note.strip()) in {_pc(n) for d_ in x["disputed"] for n in d_.split(",")} for x in uns)
                take_key = ["--scales", tk] + [y for ans in answers if about(ans) for y in ("--answer", ans)]
            args = ["tune", take, dest, *take_key, "--chords", chord_npz] + (["--ref", scan["ref"]] if scan.get("ref") else []) \
                + O.amount_flags("tune", amounts[f["id"]])
            code, txt = hx(*args)
            ok = code == 0 and dest.exists()
            log += [f"### tune {f['track']}, take {take.name}: {'written ' + dest.name if ok else 'FAILED'}", "",
                    "```", txt.strip()[-1200:], "```", ""]
            if ok:
                SRC.repoint(clips, dest, src.parent)
                done_files += 1
                print(f"tune       ok  {f['track']}: take {take.name} → {dest.name} ({len(clips)} comp clip(s))")
            else:
                failed.append(f"{f['id']}: tune failed on take {take.name}: {last_line(txt)}")
        if done_files:
            from hypnomix.session import liveversion as LV
            try:
                LV.check_write(root_t)            # a set from a newer Live than the newest tested is not written
            except LV.NewerLive as e:
                failed.append(f"tune: the tuned takes were not put into the set: {e}")
                done_files = 0
        if done_files:
            tmp = Path(target).with_name(Path(target).stem + " (tune step).als")
            with _gz.open(tmp, "wb") as fh:
                fh.write(b'<?xml version="1.0" encoding="UTF-8"?>\n' + _ET.tostring(root_t, encoding="utf-8"))
            shutil.move(str(tmp), str(target))
            errs, _, _ = C.check(target, src, allow_removed=True)
            if errs:
                bad = Path(target).with_name(Path(target).stem + " (BROKEN, do not open).als")
                Path(target).rename(bad)
                failed += [f"structure check after tuning: {e}" for e in errs]
                print(f"check      FAILED after tuning: renamed to {bad.name}; keep using the original.")
            else:
                print(f"           {f['track']}'s comp clips now play the tuned takes in {Path(target).name}; "
                      "the original take files are untouched (A/B against the original set)")

    na = not_applied(sd, findings, dec, manual_items, skipped_all, zero,
                     default_ids={f["id"] for f in defaults_used}, gone=gone)
    if na:
        print("\n" + "\n".join(na))
        log += ["### Not applied", "", "```"] + na + ["```", ""]
    if failed:
        print("\nFAILED (not done):")
        log += ["### FAILED (not done)", ""] + [f"- {x}" for x in failed] + [""]
        for x in failed:
            print(f"- {x}")
    final = name_out if name_out and Path(name_out).exists() else None
    if not (final or wrote_any):
        log.append("history: nothing was written, so this run is not a version")
        print("\nnothing was written: no new set and no repaired file.")
    try:  # every run that wrote something is a version in the song's history (hypnomix history: list, diff, undo)
        if final or wrote_any:
            from hypnomix.workflow import history as H
            v = H.log_run(sd, scan, src, final, [dict(id=f["id"], amount=amounts[f["id"]], tool=f.get("tool"),
                                                       kind=f.get("kind"), track=f.get("track"), where=f.get("where", ""))
                                                  for f in chosen], kind="fix", failed=failed,
                          extra=dict(allow_protected=bool(a.allow_protected), key=a.key, by=O.reviewer(a.by)))
            log.append(f"history: logged as v{v} (`hypnomix history \"{sd}\"`)")
            if folder_mode:   # a folder of recordings has no set to compare or go back to: the repaired copies stay in fixed/
                print(f"\nhistory: v{v} (`hypnomix history \"{sd}\"` lists every version)")
            else:
                print(f"\nhistory: v{v} (`hypnomix history \"{sd}\"` lists every version; --undo N, --undo-item ID)")
    except Exception as e:
        log.append(f"history: could not log this run ({e})")
        print(f"history: could not log this run ({e})")
    AT.append_text(sd / "fix-log.md", "\n".join(log) + "\n")
    print(f"\nlog: {sd / 'fix-log.md'}")
    if a.out and wrote_any and not final and not folder_mode:
        print(f"note: no new project was written, so {Path(a.out).name} was not used: only the repaired copies above were written")
    if final and str(out).lower().endswith(".rpp"):
        print("Open the new project in REAPER and A/B the changed spots against the original (tuned parts: switch "
              "takes on the items).")
    elif final and str(out).lower().endswith(".ardour"):
        print("Written and re-read by HypnoMix; not yet opened in HypnoMix Studio. Open the new snapshot (Session > Open, or "
              "Session > Snapshot list) and check: it opens without a warning, the audio is found, fades and gain are "
              "as listed, the pan is the way round you expect, and the trim.")
    elif final:
        print("Close the original in Live, open the new set, and A/B the changed spots against the original.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
