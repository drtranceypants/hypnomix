"""The app's side of problem reports and crash records (the text itself is made by hypnomix/core/report.py).

Routes (GET answers are for this computer's own page; every POST needs the page's X-Hypnomix token, checked by the server):

  GET  /report.js                  the dialog's and the crash banner's script
  GET  /api/report/preview         the exact report text for the choices in the address: what, expected, names, log,
                                   crash, scan (each 0 or 1), kind (bug or crash), crash_id, dir (the open scan)
  POST /api/report/preview         the same as the GET (what the dialog uses: long text travels in the body, not the address)
  POST /api/report/preview         the same as the GET, in the body (the dialog uses it: two long text boxes do not fit an address)
  POST /api/report/save            the same choices (and the digest of the text that was shown) -> a NEW file in the
                                   app's work folder, reports/
  POST /api/report/open            the same -> the text is copied, then the project's new-issue page is opened with
                                   the template name only in its address (the address is fixed in core/report.py)
  GET  /api/crashes                every crash record (newest first) with its state; ?id=ID gives one with its text
  POST /api/crashes/dismiss        {id} or {all: true}, and {offered: true} to mark "shown once" only
  POST /api/crashes/page           a script error from the page: recorded like a crash, a few a minute at most

When the text changed between the preview and the click (a job moved on), save and open answer 409 with the new text and
do nothing: what is saved or copied is always what the person was shown. Nothing here sends anything anywhere.
"""
import calendar
import os
import sys
import threading
import time
from pathlib import Path

from hypnomix.core import report as R

MAX_TEXT = 4000
STARTED = time.time()
TEXT_KEYS = ("what", "expected")


def _flag(v, default):
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def job_info(S):
    """The app's current (or last) job as the report wants it, or None when no job has run."""
    j = S.JOB
    if j.get("status") in (None, "idle") or str(j.get("title", "")).startswith("hypnomix report"):
        return None                               # no job yet, or the Tools tab's own `report` (its log would be a report)
    with S.LOG_LOCK:
        log = list(j.get("log") or [])[-R.LOG_LINES:]
    status = {"done": "finished", "failed": "failed", "running": "still running"}.get(j.get("status"), j.get("status"))
    if j.get("stopped"):
        status = "stopped by the person"
    return dict(title=j.get("title", ""), kind=j.get("kind", ""), status=status, reason=j.get("reason", ""),
                dir=j.get("dir", ""), log=log)


def choices(S, src):
    """What the person chose, checked: a dict for core.report.compose. A plain sentence (ValueError) when it is not valid."""
    kw = {}
    for k in TEXT_KEYS:
        v = src.get(k, "")
        if v is None:
            v = ""
        if not isinstance(v, str):
            raise ValueError(f"\"{k}\" must be text")
        if len(v) > MAX_TEXT:
            raise ValueError(f"\"{k}\" is too long: {MAX_TEXT} characters at most")
        kw[k] = v
    kind = src.get("kind", "bug") or "bug"
    if kind not in ("bug", "crash"):
        raise ValueError("kind is bug or crash")
    cid = src.get("crash_id") or None
    if cid is not None and (not isinstance(cid, str) or not R._ID_RE.match(cid)):
        raise ValueError("that is not a crash record's name")
    scan = None
    raw = src.get("dir")
    if raw:
        scan = S.scan_dir(raw)                      # only one of the app's own scans
    return dict(kind=kind, what_happened=kw["what"], expected=kw["expected"],
                include=[p for p in R.PART_NAMES if _flag(src.get(p), True)], names=_flag(src.get("names"), False),
                scan_dir=scan, job=job_info(S), crash_id=cid)


def preview(S, src):
    r = R.compose(**choices(S, src))
    return dict(text=r["text"], digest=r["digest"], parts=r["parts"], crash=r["crash"], issues=R.ISSUES)


def crash_row(r):
    return dict(id=r["id"], when=r.get("when", ""), where=r.get("where", ""), command=r.get("command", ""),
                exception=r.get("exception", ""), message=r.get("message", ""), state=r.get("state", "new"),
                earlier=_earlier(r))


def _earlier(r):
    try:
        t = calendar.timegm(time.strptime(r.get("when", ""), "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, OverflowError):
        return False
    return t < STARTED - 1


def folder_view():
    d = R.crash_dir()
    n = size = 0
    try:
        for p in d.iterdir():
            if p.is_file():
                n += 1
                size += p.stat().st_size
    except OSError:
        pass
    return dict(folder=R.home_short(str(d)), files=n, bytes=size, keeps=R.KEEP)


def handle_get(S, path, q):
    if path == "/report.js":
        return 200, Path(__file__).with_name("report.js").read_bytes(), "text/javascript; charset=utf-8"
    if path == "/api/report/preview":
        return 200, preview(S, q)
    if path == "/api/crashes":
        if q.get("id"):
            rec = R.crash_by_id(str(q["id"])) if R._ID_RE.match(str(q["id"])) else None
            if not rec:
                return 404, {"error": "there is no such crash record"}
            return 200, dict(record=crash_row(rec), text=R.crash_text(rec))
        return 200, dict(records=[crash_row(r) for r in R.crashes()], started=STARTED, **folder_view())
    return None


def _stale(r, body):
    d = body.get("digest")
    if isinstance(d, str) and d and d != r["digest"]:
        return 409, {"error": "the report changed since you looked at it (a job moved on). Look at it again, then click once more: "
                              "nothing was saved, copied or opened.", "text": r["text"], "digest": r["digest"], "parts": r["parts"]}
    return None


def handle_post(S, path, body):
    if path == "/api/report/preview":                 # the dialog's own form of the preview: two long text boxes do not fit an address
        return 200, preview(S, body)
    if path == "/api/report/save":
        r = R.compose(**choices(S, body))
        stale = _stale(r, body)
        if stale:
            return stale
        p = R.save_report(r["text"], S.work() / "reports")
        return 200, dict(path=str(p), name=p.name, folder=str(p.parent), digest=r["digest"])
    if path == "/api/report/open":
        r = R.compose(**choices(S, body))
        stale = _stale(r, body)
        if stale:
            return stale
        done, how = R.copy_text(r["text"])
        opened = R.open_issue_page(S.open_web)
        return 200, dict(copied=done, how=how if done else "", why="" if done else how, opened=opened, url=R.ISSUE_URL, digest=r["digest"])
    if path == "/api/crashes/dismiss":
        state = "offered" if _flag(body.get("offered"), False) else "dismissed"
        if _flag(body.get("all"), False):
            R.mark([x["id"] for x in R.crashes()], state)
        else:
            i = body.get("id")
            if not isinstance(i, str) or not R._ID_RE.match(i):
                raise ValueError("this needs \"id\" (a crash record's name) or \"all\"")
            R.mark([i], state)
        return 200, {"ok": True}
    if path == "/api/crashes/page":
        m = body.get("message")
        if not isinstance(m, str) or not m.strip():
            raise ValueError("this needs \"message\" (text)")
        for k in ("source", "stack", "page"):
            if body.get(k) is not None and not isinstance(body.get(k), str):
                raise ValueError(f"\"{k}\" must be text")
        line = body.get("line", 0)
        info = R.page_error(m[:500], body.get("source") or "", line if isinstance(line, int) and not isinstance(line, bool) else 0,
                            (body.get("stack") or "")[:2000], (body.get("page") or "")[:40])
        if info is None:
            return 429, {"error": "too many page errors a minute: this one was not recorded"}
        return 200, {"recorded": bool(info.get("id")), "id": info.get("id", "")}
    return None


# ---------------------------------------------------------------- what the server calls when something breaks
SAID = "HypnoMix hit a bug. A report was saved on this computer; nothing was sent."


def request_crash(where, command, exc):
    """An unhandled exception in a request handler: record it; the answer for the page (a 500) says so in one sentence."""
    info = R.write_crash(where, command, exc=exc)
    return 500, dict(error=SAID if info.get("id") else "HypnoMix hit a bug. A report could not be saved; nothing was sent.",
                     crash=info.get("id", ""))


def own_bug(exc):
    """True when a KeyError / TypeError / AttributeError that a request handler caught was raised inside HypnoMix's own code
    (a helper module: a bug), not by the handler reading the request's fields (a missing or wrong-kind field: a plain 400).
    ValueError and RuntimeError are the app's own plain sentences (409 and 400); they are never recorded."""
    tb = getattr(exc, "__traceback__", None)
    last = None
    while tb is not None:
        last, tb = tb, tb.tb_next
    if last is None:
        return False
    import hypnomix
    pkg = os.path.dirname(os.path.abspath(hypnomix.__file__))
    f = os.path.abspath(last.tb_frame.f_code.co_filename)
    return f.startswith(pkg + os.sep) and os.path.basename(f) not in ("server.py", "reporting.py")


def job_crash(S, kind, exc):
    """An unhandled exception in a job's own thread: record it, say so in the job's log, and end the job as failed."""
    info = R.write_crash("app-job", kind or "job", exc=exc)
    try:
        S.JOB["log"].append(SAID)
        S.JOB["reason"] = SAID
        S.JOB["status"] = "failed"
        S.JOB.pop("proc", None)
    except Exception:
        pass
    return info


def job_ended(S):
    """Remember the job that just ended (title, how it ended, the end of its log) for the next report."""
    j = job_info(S)
    if j and j["status"] != "still running":
        R.record_last("app", j["title"], j["status"], reason=j["reason"], log=j["log"], kind=j["kind"])


def thread_hook(args):
    """threading.excepthook for the app: a thread that died with an unhandled exception leaves a crash record."""
    try:
        if args.exc_type is not SystemExit:
            R.write_crash("app-thread", getattr(args.thread, "name", "") or "thread",
                          exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    finally:
        _OLD_HOOK[0](args)


_OLD_HOOK = [threading.excepthook]


_OLD_SYS_HOOK = [sys.excepthook]


def main_hook(etype, value, tb):
    """sys.excepthook for the app's own process: a failure while it starts (or any error nothing else caught) leaves a crash
    record, and the one plain sentence is printed before the usual traceback."""
    try:
        if issubclass(etype, Exception) and not issubclass(etype, (BrokenPipeError, ConnectionError)):
            info = R.write_crash("app-server", "start", exc_info=(etype, value, tb))
            print(R.crash_sentence(info), file=sys.stderr)
    except Exception:
        pass
    _OLD_SYS_HOOK[0](etype, value, tb)


def install_hooks():
    _OLD_HOOK[0] = threading.excepthook
    threading.excepthook = thread_hook
    _OLD_SYS_HOOK[0] = sys.excepthook
    sys.excepthook = main_hook
