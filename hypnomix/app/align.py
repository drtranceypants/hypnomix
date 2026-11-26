"""The app's side of the Hypnomix Align device (`hypnomix aligndevice`): runs `hypnomix alignset` for it.

The device (inside Live) chooses the guide and the parts from the tracks you select, the bars from the loop brace,
protected areas and sync points from the brace and the playhead, and the amounts from its dials. It sends them here;
this runs alignset on the saved set and hands back the result: the report, the parts' loudness shapes before and
after (the device draws them), the previews, the new set, and any rendered pitch / formant files.

  GET  /api/align/state         the chosen set, the job, the last result
  POST /api/align/choose        {path?}: the Live set (or REAPER project) to work on (no path: a file dialog)
  POST /api/align/run           {guide, parts, start_s?, end_s?, protect:[[a,b]], sync:[t], preset?, tightness?,
                                 pitch?, vibrato?, formant?, apply?}
  POST /api/align/open          open the new set in Live with the system's own opener (macOS `open`, Windows the program
                                registered for .als, Linux `xdg-open`); Live asks to save the current one first. When nothing
                                could be started the answer is {error}, which the device shows, never {opened}

The REAPER panel (`hypnomix reaper align`) uses the same endpoints with a saved .rpp: the result is a NEW project
with stretch markers and new takes on the parts' own items.

Local only, like the rest of the app. Nothing is overwritten: alignset always writes a NEW set.
"""
import json, os, shutil, subprocess, sys
from pathlib import Path

ALIGN = {"set": "", "result": None, "job": 0, "error": ""}


def open_file(target):
    """Open a file with the program this computer has for it. "" when it was started, else one plain sentence."""
    try:
        if sys.platform == "darwin":
            if subprocess.run(["open", str(target)], capture_output=True).returncode != 0:
                return f"the system could not open it: open {target} in Live yourself"
        elif sys.platform == "win32":
            os.startfile(str(target))
        else:
            opener = shutil.which("xdg-open")
            if not opener:
                return f"this computer has no opener (xdg-open): open {target} in Live yourself"
            subprocess.Popen([opener, str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        return f"the set could not be opened ({e}): open {target} in Live yourself"
    return ""


def _work():
    from hypnomix.app import server as S
    d = S.work() / "align"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state():
    from hypnomix.app import server as S
    res = ALIGN["result"]
    rp = _work() / "result.json"
    running = S.JOB["status"] == "running" and S.JOB.get("kind") == "align"
    if ALIGN["job"] and S.JOB["id"] == ALIGN["job"] and S.JOB["status"] in ("done", "failed") and rp.exists():
        try:
            res = ALIGN["result"] = json.loads(rp.read_text(encoding="utf-8"))
        except ValueError:
            pass
    st = S.JOB["status"] if S.JOB["id"] == ALIGN["job"] else "idle"
    return dict(set=ALIGN["set"], set_name=Path(ALIGN["set"]).name if ALIGN["set"] else "", status=st,
                running=running, step=S.JOB.get("step", "") if running else "",
                log_tail=S.JOB["log"][-6:] if S.JOB["id"] == ALIGN["job"] else [], result=res)


def _num(body, k, lo, hi):
    if body.get(k) is None or body.get(k) == "":
        return None
    v = float(body[k])
    if not lo <= v <= hi:
        raise ValueError(f"{k} must be between {lo} and {hi}")
    return v


def set_file(raw):
    """A Live set or REAPER project that exists: the same check as Choose set. -> its full path, or ValueError."""
    try:
        f = Path(str(raw)).expanduser().resolve()          # follow links first: what it points at must be a set
        ok = f.is_file() and f.suffix.lower() in (".als", ".rpp")
    except (OSError, RuntimeError, ValueError):
        ok = False
    if not ok:
        raise ValueError(f"not a Live set or REAPER project: {raw} (save the set in Live first, then Choose set)")
    return str(f)


def _name(v, what):
    v = str(v).strip()
    if v.startswith("-"):                  # it would be read as an option of the command, not as a track name
        raise ValueError(f"{what} \"{v}\": a track name cannot start with a dash here; rename the track")
    return v


def _secs(v):
    t = float(v)
    if not 0 <= t <= 36000:
        raise ValueError("a time must be between 0 and 36000 seconds")
    return t


def track_names(body):
    """-> (guide, parts) from a request: track names (text), the parts without the guide. ValueError when they are not."""
    raw_parts = body.get("parts") or []
    if not isinstance(body.get("guide"), str) or not isinstance(raw_parts, list) or not all(isinstance(p, str) for p in raw_parts):
        raise ValueError("guide is a track name and parts is a list of track names")
    guide = _name(body["guide"], "guide")
    parts = [_name(p, "part") for p in raw_parts if p.strip() and p.strip() != guide]
    if not guide or not parts:
        raise ValueError("choose a guide track and at least one part")
    return guide, parts


def argv_for(body, set_path, out_dir):
    """The alignset command line for a device request (also used by the tests)."""
    guide, parts = track_names(body)
    argv = ["alignset", str(set_path), "--guide", guide, "--parts", *parts, "--out", str(out_dir),
            "--json", str(Path(out_dir) / "result.json")]
    s0, s1 = _num(body, "start_s", 0, 36000), _num(body, "end_s", 0, 36000)
    if s0 is not None and s1 is not None and s1 > s0 + 0.5:
        argv += ["--range", f"{s0:.3f}-{s1:.3f}"]
    try:
        for a, b in body.get("protect") or []:
            if _secs(b) > _secs(a):
                argv += ["--protect", f"{float(a):.3f}-{float(b):.3f}"]
        for t in body.get("sync") or []:
            argv += ["--sync", f"{_secs(t):.3f}"]
    except TypeError:
        raise ValueError("protect is a list of [start, end] seconds and sync a list of seconds")
    from hypnomix.studio import alignopts as AO
    if body.get("preset"):
        if body["preset"] not in AO.PRESETS:
            raise ValueError("unknown preset")
        argv += ["--preset", body["preset"]]
    t = _num(body, "tightness", 0, 1)
    if t is not None:                       # one dial for both modes: the guide mode's strength, the stack's nudge
        argv += ["--strength", f"{t:.2f}", "--stack-strength", f"{0.3 * t:.2f}", "--fix-strength", f"{min(1.0, 0.3 + 0.7 * t):.2f}"]
    for k, flag, lo, hi in (("pitch", "--pitch", 0, 1), ("vibrato", "--vibrato", 0, 1), ("formant", "--formant", -3, 3),
                            ("bpm", "--bpm", 20, 999)):
        v = _num(body, k, lo, hi)
        if v:
            argv += [flag, f"{v:g}"]
    if body.get("no_chord_check"):          # only when the person asked; otherwise alignset checks the chords
        argv.append("--no-chord-check")     # against the set's own instrument tracks
    if body.get("chords"):
        argv += ["--chords", _name(body["chords"], "chords")]
    if body.get("takes"):                   # REAPER: timing as new takes instead of stretch markers
        argv.append("--takes")
    if body.get("apply"):
        argv.append("--apply")
    return argv


def handle_get(path, q):
    if path == "/api/align/state":
        return 200, state()
    return None


def handle_post(path, body):
    from hypnomix.app import server as S
    if path == "/api/align/choose":
        p = body.get("path") or S.pick("set")
        if p:
            if not Path(p).expanduser().is_file() or not str(p).lower().endswith((".als", ".rpp")):
                return 400, {"error": f"not a Live set or REAPER project: {p}"}
            ALIGN["set"] = str(Path(p).expanduser())
        return 200, state()
    if path == "/api/align/run":
        sp = body.get("set") or ALIGN["set"]
        if not sp:
            return 400, {"error": "choose the Live set first (save it in Live, then Choose set)"}
        try:
            sp = set_file(sp)                      # a path in the request gets the same check as Choose set
            out = _work()
            argv = argv_for(body, sp, out)
            guide, parts = track_names(body)
        except (ValueError, KeyError, TypeError) as e:
            return 400, {"error": str(e) or "bad request"}
        ALIGN["set"] = sp                          # remembered only once the whole request is good
        (out / "result.json").unlink(missing_ok=True)
        ALIGN["job"] = S.run_job("align", f"Align: {', '.join(parts)} to {guide}",
                                 [("Aligning (writes a new " + ("project" if str(sp).lower().endswith(".rpp") else "set") + ", changes nothing in yours)", argv, True)], out)
        ALIGN["result"] = None
        return 200, {"job": ALIGN["job"], "argv": argv}
    if path == "/api/align/open":
        res = ALIGN["result"] or {}
        target = res.get("out_set")
        if not target or not Path(target).exists():
            return 400, {"error": "no aligned set yet: run Align with Write set on"}
        if target.lower().endswith(".rpp"):           # REAPER: the panel opens it in a new tab through the bridge
            return 200, {"opened": target, "reaper": True}
        why = open_file(target)
        if why:
            return 400, {"error": why, "set": target}
        return 200, {"opened": target}
    return None
