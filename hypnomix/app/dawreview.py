"""The DAW view's Review: the HypnoMix loop (scan, review, apply) on the session open in the HypnoMix Studio engine.

  POST /api/dawreview/scan     {save?}: bounce the mix into the scan folder (session_export_mix + export_status), then
                               `hypnomix scan SESSION.ardour --mix` through the app's job runner (one job at a time;
                               GET /api/job shows its progress). The scan reads the SAVED session file, so with
                               unsaved changes in the engine the route answers 409 {"error": "unsaved", "dirty": true}
                               and does nothing, unless the body says "save": true (the person's own "Save and scan":
                               session_save first, in place, as a step the job log shows). A session with nothing
                               unsaved is not saved again. If the session is changed while the mix is bounced, the
                               scan stops with a sentence saying so (the findings would not match the mix).
  GET  /api/dawreview/state    the open session, its scan folder (if it was scanned) and what Apply would write
  GET  /api/dawreview/findings ?dir=   the scan's findings and decisions (as /api/review), each with where it is in
                               seconds (`at_s`), the engine track it is on (`engine_track`) and what Apply does with it
  GET  /api/dawreview/evidence ?dir=&id=   short-term level of the finding's track (the scan's render, or the
                               recording it names) and of the bounced mix around the spot
  POST /api/dawreview/decide   {dir, id, decision: approve|skip|change|clear, note, amount}: the same decisions.json
                               as `hypnomix fix --decide` and the Songs review
  POST /api/dawreview/apply    {dir}: `hypnomix fix SCAN --approved --out "<snapshot> (hypnomix).ardour"` in the
                               session folder (a new snapshot; the original is never written)
  POST /api/dawreview/abset    {dir}: `hypnomix abset SCAN --out "<snapshot> (A-B).ardour"` (workflow/abset_ardour.py): one
                               new snapshot with every proposed fix as a B the view switches over MCP; ab_ardour.json
  GET  /api/dawreview/abstate  ?dir=   that A/B session (its items, match_db) and whether the engine has it open
  POST /api/dawreview/blind    {dir, id, picked: X|Y, was: A|B}: one blind choice into the scan's blind.json
  POST /api/dawreview/ab       {dir, id}: `hypnomix ab SCAN --ids ID` (the before / after pair, where `ab` can build
                               one for a HypnoMix Studio session: repaired recordings; clip and mixer moves it cannot yet)

Opening the new snapshot is the engine supervisor's own `POST /api/daw/open`, after the person's click.
Nothing here changes or saves the open session without the person's click: a scan saves it only when its request says
"save": true, which the view sends only after asking. Apply writes ONE new snapshot file, whole or not at all.
"""
import json
import re
import time
from pathlib import Path

WRITTEN = ("fade", "cut", "dip", "mixer", "mpe-discrete")      # what fix_ardour writes into the new snapshot
MIX_NAME = "mix (engine bounce).wav"
_GRID = {}


def _tool(engine, name, args=None, timeout=8.0):
    """One engine tool call -> its structured result (RuntimeError with the engine's message on an error)."""
    r = engine.call("tools/call", {"name": name, "arguments": args or {}}, timeout=timeout) or {}
    if r.get("isError"):
        raise RuntimeError(((r.get("content") or [{}])[0].get("text")) or f"{name} failed")
    if "structuredContent" in r:
        return r["structuredContent"]
    try:
        return json.loads(r["content"][0]["text"])
    except Exception:
        return {}


def _engine():
    from hypnomix.app import daw as DW
    return DW.ENGINE


def open_session(engine=None):
    """The .ardour file the engine has open (asks the engine; falls back to what the app started it on)."""
    engine = engine or _engine()
    if not engine.connected():
        raise RuntimeError("the engine is not running: start it (Engine at the top right) and open a session")
    try:
        snaps = _tool(engine, "session_list_snapshots")
        cur = next((s for s in snaps.get("snapshots", []) if s.get("current")), None)
        if cur and cur.get("file"):
            return Path(cur["file"]), bool(snaps.get("dirty"))
    except RuntimeError:
        pass
    if engine.session:
        return Path(engine.session), False
    raise RuntimeError("the engine has no saved session open (press Save in the Studio tab once, then scan)")


def scan_folder(srv, session):
    return srv.work() / "scan" / srv.safe(f"{session.stem} (DAW)")


def out_for(session):
    """`<snapshot> (hypnomix).ardour` beside it; numbered when that exists (nothing is ever overwritten)."""
    base = re.sub(r" \(hypnomix(?: \d+)?\)$", "", session.stem)
    out = session.parent / f"{base} (hypnomix).ardour"
    n = 2
    while out.exists():
        out = session.parent / f"{base} (hypnomix {n}).ardour"
        n += 1
    return out


# ---------------------------------------------------------------- scan
class Unsaved(RuntimeError):
    """The session has changes that are not in its file: a scan would read a different song than the bounce plays."""


def start_scan(srv, save=True):
    """Start the scan job. A session with unsaved changes is saved first when `save` (the route passes only the
    person's explicit "save": true; the Assistant's scan_session passes the default, after its card, which says it saves,
    was approved); with save False it raises Unsaved and nothing is done."""
    engine = _engine()
    try:                                # a value the Assistant's Hear it is trying is put back first: never saved, never bounced
        from hypnomix.app import chat as _chat
        _chat.preview_end("the session is being scanned")
    except ImportError:
        pass
    session, reported = open_session(engine)
    dirty = bool(reported or getattr(engine, "dirty", False))
    if dirty and not save:
        raise Unsaved("unsaved")
    d = scan_folder(srv, session)
    mix = d / MIX_NAME
    job = srv.JOB
    seen = {}

    def say(line):                      # steps done here, not commands: they say what they did in the job's log
        job["log"].append(line)         # (looked up when said: run_job starts the job with a fresh log)

    def save():
        _tool(engine, "session_save", {}, timeout=60)
        say(f"saved {session.name} (you chose Save and scan)")
        seen["edits"] = getattr(engine, "_edits", None)

    def bounce():
        seen.setdefault("edits", getattr(engine, "_edits", None))
        d.mkdir(parents=True, exist_ok=True)
        r = _tool(engine, "session_export_mix", {"path": str(mix)}, timeout=30)
        jid, t0 = r.get("jobId"), time.time()
        while r.get("state") == "running":
            if time.time() - t0 > 1800:
                raise RuntimeError("the bounce took longer than 30 minutes")
            time.sleep(1.0)
            r = _tool(engine, "export_status", {"job_id": jid})
            job["step"] = f"Bouncing the mix · {round(100 * float(r.get('progress') or 0))}%"
        if r.get("state") != "done" or not mix.exists():
            raise RuntimeError(f"the bounce failed: {r.get('error') or r.get('state')}")
        if seen.get("edits") is not None and getattr(engine, "_edits", None) != seen["edits"]:
            mix.unlink()
            raise RuntimeError("the session was changed while the mix was bounced, so the scan would not match it: "
                               "scan again when you have finished editing")
        a = r.get("analysis") or {}
        say(f"bounced the mix → {mix.name} ({r.get('elapsedSeconds', 0):.0f} s; "
                   f"true peak {a.get('truePeakDb', '?')} dBTP, {a.get('integratedLufs', '?')} LUFS)")
        from hypnomix.core import atomic
        atomic.write_json(d / "daw-session.json", dict(session=str(session), mix=str(mix), when=time.time()))

    steps = ([("Saving the session", save, True)] if dirty else []) + [
             ("Bouncing the mix", bounce, True),
             ("Scanning (changes nothing)", ["scan", str(session), "--out", str(d), "--mix", str(mix)], True)]
    srv.run_job("scan", f"Review: {session.name}", steps, d)
    return {"job": job["id"], "dir": str(d), "session": str(session)}


# ---------------------------------------------------------------- findings
def _grid(source):
    """(tempo, beats per bar, track names) of a session, cached by its mtime."""
    p = Path(source)
    key = (str(p), p.stat().st_mtime if p.exists() else 0)
    if key not in _GRID:
        try:
            from hypnomix import project as PJ
            pr = PJ.load(p)
            _GRID[key] = (pr.tempo or 120.0, pr.beats_per_bar or 4, [t.name for t in pr.tracks])
        except Exception:
            _GRID[key] = (120.0, 4, [])
    return _GRID[key]


def _clock(s):
    """'0:22.37' or '1:02:03.5' -> seconds."""
    parts = str(s).split(":")
    try:
        return sum(float(x) * 60 ** i for i, x in enumerate(reversed(parts)))
    except ValueError:
        return None


def seconds_of(f, tempo, bpb):
    """Where a finding is, in seconds from the session start, or None (a whole-take or whole-song finding)."""
    e = f.get("edit") if isinstance(f.get("edit"), dict) else {}
    for k in ("t0", "t", "start"):
        if isinstance(e.get(k), (int, float)):
            return float(e[k])
    w = str(f.get("where") or "")
    m = re.search(r"\((-?\d+(?:\.\d+)?) s\)", w)
    if m:
        return float(m.group(1))
    m = re.match(r"\s*(\d+(?::\d{1,2}){1,2}(?:\.\d+)?)", w)    # a clock time ("5:42", "1:02:03.5"), not a bar
    if m:
        return _clock(m.group(1))
    m = re.match(r"\s*(?:bars?\s+)?(\d+)(?:\.(\d+))?", w)
    if m and not w.startswith("whole"):
        beats = (int(m.group(1)) - 1) * bpb + (int(m.group(2)) - 1 if m.group(2) else 0)
        return beats * 60.0 / tempo
    notes = f.get("flagged_notes") or []
    if notes and notes[0].get("time"):
        return _clock(notes[0]["time"])
    return None


def engine_track(name, names):
    """The session track a finding is on: its name, or the track a recording ("Vocals%L.wav") belongs to."""
    n = str(name or "")
    low = {x.lower(): x for x in names}
    if n.lower() in low:
        return low[n.lower()]
    stem = re.sub(r"%[LR]$|-[LR]$", "", Path(n).stem if Path(n).suffix else n)
    return low.get(stem.lower())


def handling(f, ardour=True):
    """What Apply does with a finding: (kind, words)."""
    a = f.get("applies")
    if a == "answer":
        return "question", "a question for you: answer it in Preferences or the Songs review"
    if a == "info":
        return "info", "for your information"
    if a == "manual":
        return "manual", "by hand: Apply does not change this"
    if f.get("tool") == "tune":
        return "blocked", "tuning is not written into a HypnoMix Studio session yet: tune by hand (Approve is off)"
    if a == "audio":
        return "file", "Apply makes a repaired copy of the recording beside it; put it in the session by hand"
    op = (f.get("edit") or {}).get("op")
    if op in WRITTEN:
        return "written", "Apply writes this into the new snapshot"
    return "manual", "a HypnoMix Studio session is written for fades, cuts, spikes, mixer moves and the MPE glide fix only: do this one by hand"


def applied_ids(log):
    """Finding ids a fix run wrote, from fix-log.md: the "- ID: ..." lines before a run's first ### section."""
    out, head = set(), False
    for line in (log or "").splitlines():
        if line.startswith("## fix run"):
            head = True
        elif line.startswith("###"):
            head = False
        elif head:
            m = re.match(r"- ([\w.-]+): ", line)
            if m:
                out.add(m.group(1))
    return sorted(out)


def findings(srv, d):
    p = srv.review_payload(d, light=True)
    tempo, bpb, names = _grid(p["source"]) if p.get("source") else (120.0, 4, [])
    for f in p["findings"]:
        f["at_s"] = seconds_of(f, tempo, bpb)
        f["engine_track"] = engine_track(f.get("track"), names)
        f["handling"], f["handling_text"] = handling(f)
        if f.get("default") == "approve" and f["id"] not in p["decisions"] and f["handling"] != "question":
            f["handling_text"] += " · on by default: Apply counts it as approved unless you skip it"
    from hypnomix.core import atomic
    meta = atomic.load_json(d / "daw-session.json", {}, warn=False)
    meta = meta if isinstance(meta, dict) else {}
    fl = d / "fix-log.md"                          # only runs after this scan count (a rescan starts afresh)
    log = fl.read_text(encoding="utf-8") if fl.exists() and fl.stat().st_mtime >= (d / "findings.json").stat().st_mtime else ""
    p.update(tempo=tempo, bpb=bpb, mix=meta.get("mix", ""), scanned=meta.get("when"), applied=applied_ids(log))
    return p


def _env(path, t0, t1, points=320):
    """Short-term level (dBFS, RMS) of an audio file between t0 and t1 seconds, as `points` values."""
    import numpy as np
    import soundfile as sf
    info = sf.info(str(path))
    sr = info.samplerate
    a, b = max(0, int(t0 * sr)), min(info.frames, int(t1 * sr))
    if b <= a:
        return []
    step = max(1, (b - a) // points)
    if b - a > sr * 60:                     # long spans: read in blocks, keep one window per point
        out = []
        with sf.SoundFile(str(path)) as fh:
            for i in range(points):
                s = a + i * (b - a) // points
                fh.seek(s)
                y = fh.read(min(step, 4096), dtype="float32", always_2d=True)
                out.append(float(20 * np.log10(np.sqrt(np.mean(np.square(y))) + 1e-9)) if len(y) else -120.0)
        return [round(max(-90.0, v), 1) for v in out]
    y, _ = sf.read(str(path), start=a, stop=b, dtype="float32", always_2d=True)
    y = y.mean(1)
    n = len(y) // step
    y = y[: n * step].reshape(n, step)
    v = 20 * np.log10(np.sqrt(np.mean(np.square(y), axis=1)) + 1e-9)
    return [round(max(-90.0, float(x)), 1) for x in v]


def evidence(srv, d, fid):
    p = findings(srv, d)
    f = next((x for x in p["findings"] if x["id"] == fid), None)
    if f is None:
        raise ValueError(f"unknown id: {fid}")
    src = None
    run = f.get("run") or []
    if len(run) > 1 and Path(str(run[1])).is_file():
        src = Path(run[1])
    elif f.get("input") and Path(f["input"]).is_file():
        src = Path(f["input"])
    elif f.get("track") not in (None, "", "mix"):
        r = d / "raw" / "renders" / f"{srv.safe(f['engine_track'] or f['track'])}.wav"
        src = r if r.exists() else None
    mix = Path(p["mix"]) if p.get("mix") and Path(p["mix"]).exists() else None
    import soundfile as sf
    ref = src or mix
    if ref is None:
        return dict(id=fid, curves=[], note="no audio to show for this finding")
    dur = sf.info(str(ref)).duration
    at = f.get("at_s")
    e = f.get("edit") or {}
    if at is None:
        t0, t1, span = 0.0, dur, None
    else:
        end = float(e["t1"]) if isinstance(e.get("t1"), (int, float)) else at
        t0, t1, span = max(0.0, at - 3.0), min(dur, end + 3.0), [at, end]
    curves = []
    if src:
        curves.append(dict(label=f.get("engine_track") or src.stem, values=_env(src, t0, t1)))
    if mix and f.get("track") != "mix":
        curves.append(dict(label="mix", values=_env(mix, t0, t1)))
    elif mix:
        curves.append(dict(label="mix", values=_env(mix, t0, t1)))
    return dict(id=fid, t0=round(t0, 3), t1=round(t1, 3), span=span, curves=curves,
                source=str(src or mix), note="short-term level (RMS, dBFS)")


# ---------------------------------------------------------------- routes
def handle_get(srv, path, q):
    if path == "/api/dawreview/state":
        try:
            session, dirty = open_session()
        except RuntimeError as e:
            return 200, dict(connected=False, error=str(e))
        d = scan_folder(srv, session)
        has = (d / "findings.json").exists()
        ab_of = ""
        if not has:                                   # the A/B snapshot of a scanned session: review that scan
            o = ab_original(srv, session)
            if o is not None:
                d, has, ab_of = o, True, str(session)
        return 200, dict(connected=True, session=str(session), dirty=dirty, dir=str(d) if has else "",
                         scanned=has, out=out_for(session).name, ab_session=ab_of)
    if path == "/api/dawreview/findings":
        return 200, findings(srv, srv.scan_dir(srv.need(q, "dir")))
    if path == "/api/dawreview/evidence":
        return 200, evidence(srv, srv.scan_dir(srv.need(q, "dir")), srv.need(q, "id"))
    if path == "/api/dawreview/abstate":
        return 200, ab_state(srv.scan_dir(srv.need(q, "dir")))
    return None


def ab_original(srv, session):
    """The scan folder whose A/B snapshot this session is ("Song (A-B).ardour" -> the scan of "Song"), or None."""
    m = re.match(r"(.*) \(A-B\)(?: \d+)?$", Path(session).stem)
    if not m:
        return None
    d = scan_folder(srv, Path(session).with_name(m.group(1) + ".ardour"))
    from hypnomix.workflow import abset_ardour as AA
    spec = AA.load(d, session) if (d / "findings.json").exists() else None
    return d if spec else None


def ab_state(d):
    """The scan's A/B session for HypnoMix Studio (ab_ardour.json), and whether the engine has it open."""
    from hypnomix.workflow import abset_ardour as AA
    spec = AA.load(d)
    if not spec:
        return dict(built=False)
    try:
        cur, _ = open_session()
        mine = AA.load(d, cur)                     # an earlier (numbered) build open in the engine: that one's switches
        if mine:
            spec = mine
        is_open = Path(cur).resolve() == Path(spec["session"]).resolve()
    except (RuntimeError, OSError, KeyError):
        is_open = False
    blind = {}
    try:
        from hypnomix.core import atomic
        blind = atomic.load_json(Path(d) / "blind.json", {}, warn=False) or {}
    except Exception:
        pass
    return dict(built=True, open=is_open, session=spec.get("session"), original=spec.get("original"),
                exists=Path(spec.get("session") or "").exists(), items=spec.get("items", {}),
                level_match=spec.get("level_match", ""), blind={k: v for k, v in blind.items() if isinstance(v, list)})


DECIDE = ("approve", "skip", "change", "clear")


def handle_post(srv, path, body):
    """The POST routes (the server has checked the page's token); every field is checked before anything is done."""
    if path == "/api/dawreview/scan":
        try:
            return 200, start_scan(srv, body.get("save") is True)
        except Unsaved:
            return 409, {"error": "unsaved", "dirty": True}
    if path == "/api/dawreview/decide":
        from hypnomix.workflow import review as R
        from hypnomix.workflow import oversight as O
        d = srv.scan_dir(srv.need(body, "dir"))
        fid, decision = srv.need(body, "id", "decision")
        if decision not in DECIDE:
            raise ValueError(f"decision must be one of {', '.join(DECIDE)}")
        note = body.get("note", "")
        if not isinstance(note, str):
            raise ValueError("note must be text")
        by = body.get("by") or None
        if by is not None and not isinstance(by, str):
            raise ValueError("by must be text")
        amt = body.get("amount")
        amt = None if amt in (None, "") else srv.whole(amt, "amount", 0, 100)
        srv.decisions_ok(d)
        from hypnomix.core import atomic
        with srv.DEC_LOCK, atomic.decisions_lock(d):         # the same lock as `fix --decide` and the review page
            data, dec, _ = R.load(d)
            f = next((x for x in data["findings"] if x["id"] == fid), None)
            if f is None:
                raise ValueError(f"unknown id: {fid}")
            if decision == "clear":
                if dec.pop(fid, None) is not None:
                    O.save_decisions(d, dec)                # through core/atomic.py, the last good copy kept
                return 200, {}
            if decision == "approve" and handling(f)[0] in ("blocked", "question", "info"):
                raise ValueError(handling(f)[1])
        return 200, srv.record_one(d, fid, decision, note[:2000], amount=amt, by=by, via="DAW view")
    if path == "/api/dawreview/apply":
        from hypnomix.core import atomic
        d = srv.scan_dir(srv.need(body, "dir"))
        meta = atomic.load_json(d / "findings.json", {}, warn=False) or {}
        source = Path(str(meta.get("set") or ""))
        if source.suffix.lower() != ".ardour":
            raise ValueError("this scan is not of a HypnoMix Studio session")
        out = out_for(source)
        argv = ["fix", str(d), "--approved", "--out", str(out)]
        srv.run_job("fix", f"Applying approved fixes: {source.name}", [("Writing a new snapshot", argv, True)], d, [source.parent])
        return 200, {"job": srv.JOB["id"], "out": str(out)}
    if path == "/api/dawreview/ab":
        d = srv.scan_dir(srv.need(body, "dir"))
        fid = srv.need(body, "id")
        if not re.fullmatch(r"[\w.:-]{1,200}", fid):
            raise ValueError("id is not a finding id")
        srv.run_job("abset", f"A/B: {fid}", [("Building the before / after pair", ["ab", str(d), "--ids", fid], True)], d)
        return 200, {"job": srv.JOB["id"]}
    if path == "/api/dawreview/abset":
        from hypnomix.core import atomic
        d = srv.scan_dir(srv.need(body, "dir"))
        meta = atomic.load_json(d / "findings.json", {}, warn=False) or {}
        source = Path(str(meta.get("set") or ""))
        if source.suffix.lower() != ".ardour":
            raise ValueError("this scan is not of a HypnoMix Studio session")
        out = ab_out_for(source)
        srv.run_job("abset", f"A/B session: {source.name}",
                    [("Building the A/B snapshot (every proposed fix as a B)", ["abset", str(d), "--out", str(out)], True)],
                    d, [source.parent])
        return 200, {"job": srv.JOB["id"], "out": str(out)}
    if path == "/api/dawreview/blind":
        from hypnomix.workflow import abset_ardour as AA
        d = srv.scan_dir(srv.need(body, "dir"))
        fid, picked, was = srv.need(body, "id", "picked", "was")
        if not all(isinstance(v, str) for v in (fid, picked, was)):
            raise ValueError("id, picked and was are text")
        if not re.fullmatch(r"[\w.:-]{1,200}", fid):
            raise ValueError("id is not a finding id")
        if picked not in ("X", "Y") or was not in ("A", "B"):
            raise ValueError("picked must be X or Y, and was A or B")
        spec = AA.load(d) or {}
        if fid not in (spec.get("items") or {}) and not any(fid in (b.get("items") or {}) for b in (spec.get("builds") or {}).values()
                                                            if isinstance(b, dict)):
            raise ValueError("that finding is not in this scan's A/B session")
        return 200, {"choices": AA.save_blind(d, fid, picked, was)}
    return None


def ab_out_for(session):
    """"<snapshot> (A-B).ardour" beside it, numbered when that name is taken (nothing is overwritten)."""
    s = Path(session)
    base = re.sub(r" \(A-B\)( \d+)?$", "", s.stem)
    out = s.with_name(f"{base} (A-B).ardour")
    n = 2
    while out.exists():
        out = s.with_name(f"{base} (A-B) {n}.ardour")
        n += 1
    return out
