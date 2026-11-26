#!/usr/bin/env python3
"""The hypnomix app: the whole first pass in a window, no terminal and no AI needed.

  hypnomix app                 start it and open it in your browser (http://127.0.0.1:8791)
  hypnomix app --no-open       just start it (the Mac app and the Max for Live device use this)

What you can do in it:
  first pass    choose a Live set (or a folder of recordings from any DAW), optionally a bounce of the mix and
                the key; it runs every check, builds the before / after clips and shows the review
  review        each finding with its A / B players and Approve / Skip / Change; decisions are saved as you click
  apply         writes only what you approved into ONE new set next to the original, then shows what changed
  preferences   the questions asked once: targets, protected tracks, what is deliberate
  tools         run any hypnomix command with a form, and read its report
  wiki          lessons, how-to guides, every command and the FAQ, offline and searchable: the same articles as the
                website's /wiki/ (source: hypnomix/app/wiki/articles/; Edit and Publish in a git checkout)
  assistant     chat with an AI (your own key: Claude, OpenAI, Gemini, OpenRouter, Groq, Mistral, or a free model
                in Ollama on this computer) that runs hypnomix for you; anything that writes a set waits for your
                click. Needs `pip install "hypnomix[assistant]"`
  Live          with the Max for Live device (`hypnomix device`) loaded in your set, "Show in Live" jumps Live
                to the finding: the track is selected, the playhead and the loop brace move to the spot, and
                the clip opens. The device also steps through the open questions from inside Live.

It is a small web server on this computer only (127.0.0.1). Nothing is sent anywhere. Songs you scan are kept
in ~/Documents/Hypnomix (change with --home or HYPNOMIX_APP_HOME). Everything it does is a hypnomix command
you could also type; the log shows each one.
"""
import argparse, json, os, re, secrets, shlex, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

TOKEN = secrets.token_urlsafe(18)
LOCK = threading.Lock()
JOB = {"id": 0, "status": "idle", "log": [], "title": "", "kind": "", "dir": "", "step": ""}
LIVE = {"seq": 0, "cmd": None, "seen": 0.0, "dir": "", "cursor": -1}
PROBE = {"hub": None, "error": ""}    # the probe hub (UDP from HypnomixProbe devices in Live)
AB = {"id": "", "state": "A", "since": 0.0, "last": 0.0, "match": True, "acc": {}, "skip": 0.6}
HIDDEN = {"app", "install"}            # not offered in the Tools tab (install asks questions; app is this)


def work():
    p = Path(os.environ.get("HYPNOMIX_APP_HOME", "~/Documents/Hypnomix")).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe(name):
    return re.sub(r'[\\/:*?"<>|]', "-", name).strip() or "song"


# ---------------------------------------------------------------- jobs
def run_job(kind, title, steps, sdir=""):
    """steps: [(label, argv, must_succeed)]. One job at a time."""
    with LOCK:
        if JOB["status"] == "running":
            raise RuntimeError("something is already running: wait for it to finish")
        JOB.update(id=JOB["id"] + 1, status="running", log=[], title=title, kind=kind, dir=str(sdir), step="")

    def go():
        ok = True
        for label, argv, must in steps:
            JOB["step"] = label
            JOB["log"].append(f"$ hypnomix {' '.join(shlex.quote(a) for a in argv)}")
            try:
                p = subprocess.Popen([sys.executable, "-u", "-m", "hypnomix.cli", *argv], cwd=str(work()), text=True,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                JOB["proc"] = p
                for line in p.stdout:
                    JOB["log"].append(line.rstrip("\n"))
                    if len(JOB["log"]) > 4000:
                        del JOB["log"][:1000]
                code = p.wait()
            except Exception as e:                      # the interpreter could not start the command
                JOB["log"].append(f"could not run: {e}")
                code = 1
            if code != 0:
                JOB["log"].append(f"({label}: exit code {code})")
                if must:
                    ok = False
                    break
        JOB.pop("proc", None)
        JOB["status"] = "done" if ok else "failed"

    threading.Thread(target=go, daemon=True).start()
    return JOB["id"]


# ---------------------------------------------------------------- scans and reviews
def scans():
    out = []
    root = work() / "scan"
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir(), key=lambda p: -p.stat().st_mtime):
        f = d / "findings.json"
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text())
            dec = json.loads((d / "decisions.json").read_text()) if (d / "decisions.json").exists() else {}
        except Exception:
            continue
        act = [x for x in data["findings"] if x.get("applies") not in ("info", "answer")]
        out.append(dict(dir=str(d), name=d.name, source=data.get("set", ""), findings=len(act),
                        decided=sum(1 for x in act if x["id"] in dec),
                        approved=sum(1 for x in act if dec.get(x["id"], {}).get("decision") == "approve"),
                        when=time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime)),
                        applied=(d / "fix-log.md").exists()))
    return out


def scan_dir(raw):
    """Only folders inside the app's own scan folder are ever read or written."""
    d = Path(raw).resolve()
    root = (work() / "scan").resolve()
    if root not in d.parents or not (d / "findings.json").exists():
        raise ValueError("not one of this app's scans")
    return d


def set_grid(source):
    """(tempo, beats per bar) of a set, or (None, 4)."""
    try:
        from hypnomix.session import automation as aa, beats as B
        tree = aa.load(source)
        return B.set_tempo(tree.getroot()), aa.BPB
    except Exception:
        return None, 4


def locate(f, tempo, bpb):
    """Where a finding is in the Arrangement, in beats: (start, end) or None. Reads the finding's `where`."""
    w = str(f.get("where") or "")
    m = re.search(r"bars?\s+(\d+)\s*(?:-|to|–)\s*(\d+)", w)
    if m:
        return (int(m[1]) - 1) * bpb, int(m[2]) * bpb
    m = re.search(r"(?<![\d:])(\d+)\.(\d+(?:\.\d+)?)", w)
    if m:
        b = (int(m[1]) - 1) * bpb + max(0.0, float(m[2]) - 1)
        return max(0.0, b - 1), b + 3
    m = re.search(r"bars?\s+(\d+)", w)
    if m:
        return (int(m[1]) - 1) * bpb, int(m[1]) * bpb
    m = re.search(r"(\d+):(\d\d(?:\.\d+)?)", w)
    if m and tempo:
        b = (int(m[1]) * 60 + float(m[2])) * tempo / 60.0
        return max(0.0, b - 1), b + 3
    return None


def review_payload(d):
    from hypnomix.workflow import review as R, prefs as P
    data, dec, ab = R.load(d)
    meta = json.loads((d / "scan.json").read_text()) if (d / "scan.json").exists() else {}
    source = data.get("set", "")
    is_set = str(source).lower().endswith(".als")
    tempo, bpb = set_grid(source) if is_set and Path(source).exists() else (None, 4)
    for f in data["findings"]:
        span = locate(f, tempo, bpb) if is_set else None
        if span and f.get("track") not in (None, "", "mix"):
            f["jump"] = dict(track=f["track"], start=round(span[0], 3), end=round(span[1], 3))
        elif is_set and f.get("track") not in (None, "", "mix"):
            f["jump"] = dict(track=f["track"])
    notes = data.get("notes", [])
    log = (d / "fix-log.md").read_text() if (d / "fix-log.md").exists() else ""
    return dict(dir=str(d), name=d.name, source=source, is_set=is_set, mode=meta.get("mode", "set" if is_set else "folder"),
                findings=data["findings"], decisions=dec, ab=ab, prefs=P.summary(P.load()),
                broken=[n for n in notes if "failed" in n or n.startswith("WARNING") or "did NOT run" in n],
                fix_log=log[-6000:], suggested_out=(Path(source).stem + " (fixed).als") if is_set else "",
                oversight=ov_payload(d, data["findings"]),
                ab_live=ab_spec(d), blind=json.loads((d / "blind.json").read_text()) if (d / "blind.json").exists() else [])


def ov_payload(d, findings):
    try:
        from hypnomix.workflow import review as R
        return R.oversight_payload(d, findings)
    except Exception as e:                     # the review still works without the extras
        return {"error": str(e)}


def actionable(d):
    from hypnomix.workflow import review as R
    data, dec, _ = R.load(d)
    return [f for f in data["findings"] if f.get("applies") not in ("info", "answer")], dec


# ---------------------------------------------------------------- the Live device link
def live_send(cmd):
    LIVE["seq"] += 1
    LIVE["cmd"] = cmd
    return LIVE["seq"]


def live_current():
    """The finding the Live device is looking at (for its display), or a short status."""
    if not LIVE["dir"]:
        return dict(text="Open a review in the hypnomix app first.", n=0, of=0)
    try:
        d = scan_dir(LIVE["dir"])
        act, dec = actionable(d)
        payload = {f["id"]: f for f in review_payload(d)["findings"]}
    except Exception:
        return dict(text="That review is no longer there.", n=0, of=0)
    left = sum(1 for f in act if f["id"] not in dec)
    if not act:
        return dict(text="Nothing to review in this scan.", n=0, of=0, left=0)
    i = max(0, min(len(act) - 1, LIVE["cursor"]))
    f = payload[act[i]["id"]]
    return dict(n=i + 1, of=len(act), left=left, id=f["id"], track=f.get("track") or f.get("tool"), where=f.get("where") or "",
                severity=f.get("severity"), problem=f.get("problem", ""), fix=str(f.get("fix", "")).split("\n")[0][:240],
                decision=dec.get(f["id"], {}).get("decision", ""), jump=f.get("jump"), song=d.name,
                ab=ab_spec(d, f["id"]), match=AB["match"])


def live_step(delta, undecided=False):
    d = scan_dir(LIVE["dir"])
    act, dec = actionable(d)
    if not act:
        return
    i = LIVE["cursor"]
    for _ in range(len(act)):
        i = (i + delta) % len(act)
        if not undecided or act[i]["id"] not in dec:
            break
    LIVE["cursor"] = i
    cur = live_current()
    if cur.get("jump"):
        live_send(dict(type="jump", **cur["jump"]))


# ---------------------------------------------------------------- probe and in-Live A/B
def ab_spec(d, fid=None):
    f = Path(d) / "ab_live.json"
    if not f.exists():
        return None
    spec = json.loads(f.read_text())
    if fid is None:
        return spec
    it = spec.get("items", {}).get(fid)
    if not it or not it.get("parts"):
        return None
    return dict(set=Path(spec["set"]).name, parts=it["parts"])


def ab_set_state(fid, state, match=None):
    if fid != AB["id"] or state != AB["state"]:
        AB.update(id=fid, state=state, since=time.time(), last=0.0)
    if match is not None:
        AB["match"] = bool(match)


def ab_gain():
    """Loudness of A and B on Main while each plays (measured before the probe's own gain); B is matched to A."""
    hub = PROBE["hub"]
    if not hub or not AB["id"]:
        return 0.0, None
    rows = hub.last_main(max(AB["since"] + AB["skip"], AB["last"]))       # skip the moment of switching
    acc = AB["acc"].setdefault(f"{AB['id']}|{AB['state']}", [0.0, 0])
    for r in rows:
        v = r[5]
        acc[0] += v[0] ** 2 + v[1] ** 2
        acc[1] += 1
        AB["last"] = r[0] + 1e-6
    a, b = AB["acc"].get(f"{AB['id']}|A"), AB["acc"].get(f"{AB['id']}|B")
    if not (a and b and a[1] >= 30 and b[1] >= 30 and a[0] > 0 and b[0] > 0):
        return 0.0, None
    import math
    diff = 10 * math.log10((a[0] / a[1]) / (b[0] / b[1]))          # A minus B, in dB
    diff = max(-12.0, min(12.0, diff))
    return (diff if AB["state"] == "B" and AB["match"] else 0.0), round(diff, 2)


def blind_record(d, body):
    f = Path(d) / "blind.json"
    rows = json.loads(f.read_text()) if f.exists() else []
    rows.append(dict(id=body["id"], chose=body["chose"], x=body.get("x", ""), at=time.strftime("%Y-%m-%d %H:%M"),
                     listens=body.get("listens", 0)))
    f.write_text(json.dumps(rows, indent=1))
    mine = [r for r in rows if r["id"] == body["id"]]
    return dict(n=len(mine), b=sum(1 for r in mine if r["chose"] == "B"))


def cards_file():
    return work() / "cards.json"


def card_save(sig, chords=None, params=None):
    f = cards_file()
    allc = json.loads(f.read_text()) if f.exists() else {}
    c = allc.setdefault(sig, {})
    if chords is not None:
        c["chords"] = chords
    if params:
        c["params"] = params
    c["updated"] = time.strftime("%Y-%m-%d %H:%M")
    f.write_text(json.dumps(allc, indent=1))
    return c


MASTER = {"path": "", "song": ""}


def master_record(body):
    """Main's Record and review: start → a file to record into (and the probes start listening); stop → the review."""
    hub = PROBE["hub"]
    if body.get("state") == "start":
        if JOB["status"] == "running":
            raise RuntimeError("the app is busy: wait for the current job")
        d = work() / "bounces"
        d.mkdir(parents=True, exist_ok=True)
        MASTER["path"] = str(d / f"master-{time.strftime('%Y%m%d-%H%M%S')}.wav")
        if hub:
            hub.begin("master")
        return {"path": MASTER["path"]}
    path = body.get("path") or MASTER["path"]
    cap = hub.end(work() / "captures", "master") if hub and hub.capture is not None else None
    sig = body.get("sig") or "song"
    name = safe(f"Pre-export {time.strftime('%Y-%m-%d %H%M')}")
    d = work() / "scan" / name
    pr = body.get("params") or {}
    steps = []
    if cap:
        steps.append(("Reading what the probes heard, and the recorded master", ["probe", "report", str(cap), "--out", str(d), "--mix", path], True))
    flags = []
    if isinstance(pr.get("target"), (int, float)):
        flags += ["--target", str(pr["target"])]
    if isinstance(pr.get("ceiling"), (int, float)):
        flags += ["--ceiling", str(pr["ceiling"])]
    if pr.get("mode") in ("clean", "punch", "loud"):
        flags += ["--limiter-mode", pr["mode"]]
    if isinstance(pr.get("amount"), (int, float)):
        flags += ["--amount", str(pr["amount"])]
    steps.append(("Release checks on the recorded master", ["qc", path] + (["--target", str(pr["target"])] if "target" in flags else []), False))
    steps.append(("How it translates (mono, phone, earbuds, car, codecs)", ["translate", path], False))
    steps.append(("Mastering moves, as proposals", ["master", path, "--plan", str(d)] + flags, False))
    run_job("probe", "Review before export", steps, d)
    return {"job": JOB["id"], "dir": str(d)}


def start_probe_hub():
    try:
        from hypnomix.app.probe import Hub
        PROBE["hub"] = Hub().start()
        PROBE["error"] = ""
    except Exception as e:                    # the port is taken (another app, or `hypnomix probe listen`)
        PROBE["error"] = f"UDP port 8792 is in use ({e}); close the other program using it: it is tried again every few seconds"
    PROBE["tried"] = time.time()


def probe_hub():
    """The hub, starting it again (at most every 5 s) if the port was taken when the app started."""
    if PROBE["hub"] is None and time.time() - PROBE.get("tried", 0) > 5:
        start_probe_hub()
    return PROBE["hub"]


# ---------------------------------------------------------------- native file dialogs (macOS)
def pick(kind):
    if sys.platform != "darwin":
        return ""
    script = {"set": 'POSIX path of (choose file with prompt "Choose a Live set" of type {"als"})',
              "audio": 'POSIX path of (choose file with prompt "Choose an audio file" of type {"wav","aif","aiff","flac","mp3","m4a"})',
              "folder": 'POSIX path of (choose folder with prompt "Choose a folder of recordings or stems")'}[kind]
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


# ---------------------------------------------------------------- http
def make_handler(port):
    from hypnomix.app.ui import PAGE
    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json", extra=None):
            if not isinstance(body, (bytes, bytearray)):
                body = json.dumps(body, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def local(self):
            host = (self.headers.get("Host") or "").split(":")[0]
            o = self.headers.get("Origin")
            return host in ("127.0.0.1", "localhost") and (o is None or o in origins)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if not self.local():
                return self.send(403, {"error": "this computer only"})
            try:
                if u.path == "/":
                    return self.send(200, PAGE.replace("__TOKEN__", TOKEN).encode(), "text/html; charset=utf-8")
                if u.path == "/api/state":
                    from hypnomix.workflow import prefs as P
                    from hypnomix import cli
                    pr = P.load()
                    return self.send(200, dict(
                        scans=scans(), prefs=P.summary(pr), unanswered=len(P.unanswered(pr)), home=str(work()),
                        job={k: JOB[k] for k in ("id", "status", "title", "kind", "dir", "step")},
                        live=time.time() - LIVE["seen"] < 3.0, mac=sys.platform == "darwin",
                        commands=[dict(group=g, name=n, about=d) for g, cmds in cli.GROUPS for n, _, d in cmds if n not in HIDDEN]))
                if u.path == "/api/job":
                    since = int(q.get("since", 0))
                    return self.send(200, dict(id=JOB["id"], status=JOB["status"], title=JOB["title"], kind=JOB["kind"],
                                               dir=JOB["dir"], step=JOB["step"], total=len(JOB["log"]), log=JOB["log"][since:]))
                if u.path == "/api/review":
                    d = scan_dir(q["dir"])
                    if LIVE["dir"] != str(d):
                        LIVE.update(dir=str(d), cursor=-1)
                    return self.send(200, review_payload(d))
                if u.path == "/api/prefs":
                    from hypnomix.workflow import prefs as P
                    pr = P.load()
                    return self.send(200, [dict(q_, value=P.get(pr, q_["key"])) for q_ in P.QUESTIONS])
                if u.path == "/api/help":
                    from hypnomix import cli
                    if q.get("cmd") not in cli.COMMANDS or q["cmd"] in HIDDEN:
                        return self.send(404, {"error": "unknown command"})
                    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", q["cmd"], "-h"], capture_output=True, text=True)
                    return self.send(200, {"help": (r.stdout + r.stderr)[-12000:]})
                if u.path.startswith("/api/align/"):       # the Align device (hypnomix aligndevice)
                    from hypnomix.app import align as AL
                    r = AL.handle_get(u.path, q)
                    if r:
                        return self.send(*r)
                if u.path in ("/wiki.js", "/api/wiki", "/api/wiki/article") or u.path.startswith("/wiki/assets/"):
                    from hypnomix.app import wiki as WK             # the Wiki tab: the site's articles, offline
                    r = WK.handle_get(u.path, q, self.headers)
                    if r:
                        return self.send(*r)
                if u.path.startswith("/api/chat/") or u.path == "/chat.js":   # the Assistant tab
                    from hypnomix.app import chat as CH
                    r = CH.handle_get(u.path, q)
                    if r:
                        return self.send(*r)
                if u.path == "/api/live/poll":            # the Max for Live device asks a few times a second
                    LIVE["seen"] = time.time()
                    since = int(q.get("since", -1))
                    cmd = LIVE["cmd"] if LIVE["seq"] > since >= 0 else None
                    return self.send(200, dict(seq=LIVE["seq"], cmd=cmd, current=live_current()))
                if u.path == "/api/probe/status":
                    hub = probe_hub()
                    return self.send(200, dict(tracks=hub.status() if hub else [], error=PROBE["error"],
                                               recording=bool(hub and hub.capture is not None)))
                if u.path == "/api/probe/cmd":            # each probe asks twice a second: its gain (A/B loudness match)
                    g, diff = ab_gain() if q.get("main") == "1" else (0.0, None)
                    return self.send(200, dict(gain_db=round(g, 2), ab_diff=diff))
                if u.path == "/api/probe/card":
                    f = cards_file()
                    return self.send(200, (json.loads(f.read_text()) if f.exists() else {}).get(q.get("sig", ""), {}))
                if u.path == "/api/probe/song":            # what the devices say right now (song card + track roles)
                    return self.send(200, PROBE["hub"].song_card() if PROBE["hub"] else {})
                if u.path == "/audio":
                    d = scan_dir(q["dir"])
                    f = d / "ab" / Path(unquote(q["f"])).name
                    if not (f.is_file() and f.suffix == ".wav"):
                        return self.send(404, {"error": "no such clip"})
                    data = f.read_bytes()
                    rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
                    if rng:                                # browsers ask for parts of an audio file
                        a = int(rng[1]) if rng[1] else 0
                        b = min(int(rng[2]) if rng[2] else len(data) - 1, len(data) - 1)
                        return self.send(206, data[a:b + 1], "audio/wav",
                                         {"Content-Range": f"bytes {a}-{b}/{len(data)}", "Accept-Ranges": "bytes"})
                    return self.send(200, data, "audio/wav", {"Accept-Ranges": "bytes"})
                self.send(404, {"error": "not found"})
            except (KeyError, ValueError) as e:
                self.send(400, {"error": str(e)})

        def do_POST(self):
            u = urlparse(self.path)
            if not self.local():
                return self.send(403, {"error": "this computer only"})
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 200000)) or b"{}")
            except ValueError:
                return self.send(400, {"error": "bad request"})
            try:
                # the device (inside Live) may step through findings and record decisions; nothing is applied by these
                if u.path == "/api/live/step":
                    live_step(int(body.get("delta", 1)), bool(body.get("undecided")))
                    return self.send(200, live_current())
                if u.path == "/api/live/decide":
                    from hypnomix.workflow import review as R
                    cur = live_current()
                    if cur.get("id"):
                        R.record(scan_dir(LIVE["dir"]), cur["id"], body["decision"], "from the Live device")
                    return self.send(200, live_current())
                if u.path.startswith("/api/align/"):       # the Align device: always writes a NEW set, never overwrites
                    from hypnomix.app import align as AL
                    r = AL.handle_post(u.path, body)
                    if r:
                        return self.send(*r)
                if u.path == "/api/ab/state":            # the device switched A / B (or loudness matching)
                    ab_set_state(body["id"], body.get("state", "A"), body.get("match"))
                    g, diff = ab_gain()
                    return self.send(200, dict(state=AB["state"], match=AB["match"], diff=diff))
                if u.path == "/api/ab/blind":
                    return self.send(200, blind_record(scan_dir(LIVE["dir"]), body))
                if u.path == "/api/probe/card":
                    return self.send(200, card_save(str(body["sig"]), body.get("chords"), body.get("params")))
                if u.path == "/api/master/record":
                    return self.send(200, master_record(body))
                if u.path == "/api/probe/start":
                    if not probe_hub():
                        return self.send(409, {"error": "the probe receiver is not running: " + PROBE["error"]})
                    PROBE["hub"].begin(body.get("label", ""))
                    return self.send(200, {"recording": True})
                if u.path == "/api/probe/stop":
                    f = PROBE["hub"].end(work() / "captures", body.get("song", ""))
                    return self.send(200, {"capture": str(f)})
                if self.headers.get("X-Hypnomix") != TOKEN:
                    return self.send(403, {"error": "open the app's own page to do this"})
                if u.path.startswith("/api/wiki/"):        # the Wiki tab: edit, publish, live copy on or off
                    from hypnomix.app import wiki as WK
                    r = WK.handle_post(u.path, body)
                    if r:
                        return self.send(*r)
                if u.path.startswith("/api/chat/"):        # the Assistant tab (needs the page's token, like the rest)
                    from hypnomix.app import chat as CH
                    r = CH.handle_post(u.path, body)
                    if r:
                        return self.send(*r)
                if u.path == "/api/pick":
                    return self.send(200, {"path": pick(body["kind"])})
                if u.path == "/api/decide":
                    from hypnomix.workflow import review as R
                    amt = body.get("amount")
                    R.record(scan_dir(body["dir"]), body["id"], body["decision"], body.get("note", ""),
                             amount=None if amt is None else int(amt), by=body.get("by") or None)
                    return self.send(200, {})
                if u.path == "/api/decide-like":
                    from hypnomix.workflow import review as R
                    ids = R.record_like(scan_dir(body["dir"]), body["id"], body["decision"], amount=body.get("amount"),
                                        by=body.get("by") or None)
                    return self.send(200, {"ids": ids})
                if u.path == "/api/note":
                    from hypnomix.workflow import oversight as O
                    O.add_note(scan_dir(body["dir"]), body["id"], body["text"], body.get("at") or None, body.get("by") or None)
                    return self.send(200, {})
                if u.path == "/api/prefs":
                    from hypnomix.workflow import prefs as P
                    pr = P.load()
                    keys = {q_["key"] for q_ in P.QUESTIONS}
                    for k, v in body.items():
                        if k in keys:
                            P.put(pr, k, P.parse(k, str(v)))
                    P.save(pr)
                    return self.send(200, {"saved": True})
                if u.path == "/api/scan":
                    src = Path(body["source"]).expanduser()
                    if not src.exists():
                        return self.send(400, {"error": f"not found: {src}"})
                    d = work() / "scan" / safe(src.stem if src.is_file() else src.name)
                    argv = ["scan", str(src), "--out", str(d)]
                    for k in ("mix", "ref", "key", "like"):
                        if body.get(k):
                            argv += [f"--{k}", str(body[k])]
                    if body.get("deep"):
                        argv.append("--deep")
                    run_job("scan", f"First pass: {src.name}", [("Scanning (changes nothing)", argv, True),
                                                               ("Building before / after clips", ["ab", str(d)], False)], d)
                    return self.send(200, {"job": JOB["id"], "dir": str(d)})
                if u.path == "/api/fix":
                    d = scan_dir(body["dir"])
                    p = review_payload(d)
                    argv = ["fix", str(d), "--approved"]
                    out = ""
                    if p["is_set"]:
                        name = safe(body.get("out") or p["suggested_out"])
                        name = name if name.lower().endswith(".als") else name + ".als"
                        out = str(Path(p["source"]).parent / name)
                        argv += ["--out", out]
                    if body.get("key"):
                        argv += ["--key", str(body["key"])]
                    for flag in ("allow_protected", "stale_ok"):
                        if body.get(flag):
                            argv.append("--" + flag.replace("_", "-"))
                    run_job("fix", f"Applying approved fixes: {d.name}", [("Applying only what you approved", argv, True)], d)
                    return self.send(200, {"job": JOB["id"], "out": out})
                if u.path == "/api/ab/build":
                    d = scan_dir(body["dir"])
                    argv = ["abset", str(d)] + (["--key", str(body["key"])] if body.get("key") else [])
                    run_job("abset", f"A/B set for Live: {d.name}", [("Building every fix as a switch (changes nothing)", argv, True)], d)
                    return self.send(200, {"job": JOB["id"]})
                if u.path == "/api/probe/report":
                    cap = Path(body["capture"])
                    d = work() / "scan" / safe((body.get("name") or cap.stem) + " (live)")
                    argv = ["probe", "report", str(cap), "--out", str(d)] + (["--set", body["set"]] if body.get("set") else [])
                    run_job("probe", f"Live check: {d.name}", [("Reading what the probes heard", argv, True)], d)
                    return self.send(200, {"job": JOB["id"], "dir": str(d)})
                if u.path == "/api/tool":
                    from hypnomix import cli
                    if body.get("cmd") not in cli.COMMANDS or body["cmd"] in HIDDEN:
                        return self.send(400, {"error": "unknown command"})
                    argv = [body["cmd"]] + shlex.split(body.get("args", ""))
                    run_job("tool", f"hypnomix {body['cmd']}", [(body["cmd"], argv, True)])
                    return self.send(200, {"job": JOB["id"]})
                if u.path == "/api/stop":
                    p = JOB.get("proc")
                    if p:
                        p.terminate()
                    return self.send(200, {})
                if u.path == "/api/reveal":
                    target = Path(body["path"]).expanduser()
                    if sys.platform == "darwin" and target.exists():
                        subprocess.run(["open", "-R", str(target)])
                    return self.send(200, {})
                if u.path == "/api/live/jump":
                    d = scan_dir(body["dir"])
                    f = next((x for x in review_payload(d)["findings"] if x["id"] == body["id"]), None)
                    if not f or not f.get("jump"):
                        return self.send(400, {"error": "this finding has no place in the set to jump to"})
                    act, _ = actionable(d)
                    LIVE.update(dir=str(d), cursor=next((i for i, x in enumerate(act) if x["id"] == f["id"]), LIVE["cursor"]))
                    live_send(dict(type="jump", **f["jump"]))
                    return self.send(200, {"sent": True, "device": time.time() - LIVE["seen"] < 3.0})
                self.send(404, {"error": "not found"})
            except RuntimeError as e:
                self.send(409, {"error": str(e)})
            except (KeyError, ValueError) as e:
                self.send(400, {"error": str(e)})

    return H


def main():
    ap = argparse.ArgumentParser(prog="hypnomix app", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--no-open", action="store_true", help="do not open the browser")
    ap.add_argument("--home", help="where scans are kept (default ~/Documents/Hypnomix)")
    a = ap.parse_args()
    if a.home:
        os.environ["HYPNOMIX_APP_HOME"] = a.home
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(a.port))
    except OSError:
        sys.exit(f"port {a.port} is in use: is the hypnomix app already running? (http://127.0.0.1:{a.port})")
    start_probe_hub()
    url = f"http://127.0.0.1:{a.port}/"
    print(f"hypnomix app: {url}   (this computer only; Ctrl-C to stop)\nsongs are kept in {work()}", flush=True)
    if not a.no_open:
        import webbrowser
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
