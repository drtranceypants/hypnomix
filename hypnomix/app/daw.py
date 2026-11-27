"""DAW mode: the HypnoMix Studio engine under the app, and the DAW view on top of it.

  hypnomix app --daw                    open the DAW view first, and start (or find) the engine on the session
                                        it had open last time (daw.json "last"; none: File → New / Open Session)
  hypnomix app --daw --session S.ardour  ... and open that session in it

The engine is HypnoMix Studio's audio engine (headless) with its MCP surface. The app finds it:

  1. HYPNOMIX_ENGINE, or "engine" in daw.json in the HypnoMix home (~/.hypnomix, or HYPNOMIX_HOME): the path of a `hypnomix-engine` program
  2. the add-on: <HypnoMix home>/engine/<the version engine_addon.json names>/bin/hypnomix-engine, put there from Setup
     (hypnomix/app/engine_addon.py: fetched once, on a click, checked against a SHA-256 before it is used). There is one
     app for everyone; the engine is not inside it
  3. `hypnomix-engine` inside the app bundle (Contents/Resources/engine, a test build made with the old --daw option:
     found for one more version so such a build still works; nothing depends on it), or next to Python
  4. for developers only: a source build of the engine, named by HYPNOMIX_ENGINE_SRC (the folder of the checkout;
     hypnomix/engine/engine-dev there, once build/hypnomix/engine/hypnomix-engine is built). Nothing is guessed.

and runs it as `hypnomix-engine --port N [ARGS] -- SESSION_DIR SNAPSHOT` (or `--new -- SESSION_DIR/NAME NAME` for a
new session; after the `--` a name can never be taken for an option) on a free port N, so it never collides with a
HypnoMix Studio window on 4820, in a minimal environment (none of the app's own keys or tokens) and with the session's
folder as its working folder. ARGS: HYPNOMIX_ENGINE_ARGS, or
"args" in daw.json (e.g. `-b "None (Dummy)"` with no audio interface). Without a `-b` there, the engine uses CoreAudio
(on a Mac); if it cannot start any audio device, the supervisor starts it once more on the Dummy backend (no sound:
the session, edits, peaks and exports all work) and says so in plain words (`notice`); Restart tries the device
again. The engine prints
`HYPNOMIX-ENGINE READY port=N ...` once its MCP surface answers at http://127.0.0.1:N/mcp, or
`HYPNOMIX-ENGINE ERROR <message>` and stops. Only whole lines of that form, on the engine's standard output, count
(its log, on standard error, is only kept for the engine panel), and the port must be the one it was given. A
start that is not ready within READY_TIMEOUT seconds is stopped and reported (state "failed"). The supervisor keeps
it running: if it stops without being asked
(a crash, or exit status 3: the audio engine halted), it is started again on the same session, at most 3 times a
minute. An ERROR before READY (no such session, the port is taken, bad arguments) is reported and not retried.
Stopping it is SIGTERM: it saves nothing unless the session was saved (the DAW view's Save, or MCP session_save).

Unsaved work. Every changing tool call that goes through the app (from the page or from the Assistant) marks the
session dirty, every successful session_save clears it (a call is changing unless its tool is on READ_ONLY_TOOLS: an
unknown tool counts as changing), and a new or newly opened session starts clean. `GET /api/daw/state` carries
`dirty`; `POST /api/daw/save` saves through the engine and answers {ok, dirty}; stop, restart, open and new answer
HTTP 409 {"error": "unsaved", "dirty": true} while dirty, unless the body says "discard": true (go on without
saving) or "save": true (save, then go on). `dirty()` and `save()` are the same for the updater and the native app.
A change that reaches the engine WITHOUT the app (`hypnomix tidy|order|duck --engine`, `loops|variations --cues`, a
script on the engine's port) counts too: the engine keeps its own unsaved flag (Session::dirty(), the "dirty" of its
read-only session_list_snapshots), and the app reads it, before every stop, restart, open, new and `dirty()` and for
`GET /api/daw/state` (one reading shared by all of them, at most every ENGINE_DIRTY_TTL seconds). Unsaved is the app's count OR the engine's flag;
a save clears both. An engine that does not answer keeps the last answer it gave.
One program is started, stopped or replaced at a time: a second request meanwhile is answered "busy" (409).

Until the engine program exists, the app **attaches** to a HypnoMix Studio window that is already running
with its MCP surface on (http://127.0.0.1:4820/mcp, HYPNOMIX_ENGINE_URL to change it). Attached, the app never
stops or restarts that window, and opening a session is done in its own window.

The browser talks to the engine only through the app (POST /mcp, same origin, the page's token), and the
Assistant uses the engine's own tools through the same path, asking before anything that changes the session.
"""
import contextlib, json, os, re, secrets, shlex, shutil, signal, socket, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from pathlib import Path

from hypnomix.core import loopback

READY = re.compile(r"^HYPNOMIX-ENGINE READY port=(\d+)(?: .*)?$")       # whole lines only, from the engine's stdout
ERROR = re.compile(r"^HYPNOMIX-ENGINE ERROR (.*)$")
LOST_NOTICE = ("The engine stopped and was started again: the changes you made since your last save were lost. "
               "Save the session (Ctrl/Cmd+S) as you go.")
ATTACH_URL = "http://127.0.0.1:4820/mcp"
NAME = "hypnomix-engine"
MAX_RESTARTS = 3                 # within RESTART_WINDOW seconds; then it stays stopped and says why
RESTART_WINDOW = 60.0
READY_TIMEOUT = 120.0            # a big session can take a while to load
RPC_TIMEOUT = 8.0
ENGINE_DIRTY_TTL = 2.0         # how old the engine's own unsaved flag may be (the page polls GET /api/daw/state; Stop and quit read it too)
ENGINE_DIRTY_TIMEOUT = 3.0     # how long a look at it may take (an engine busy exporting keeps the last answer)


def conf_path():
    """daw.json in the HypnoMix home (HYPNOMIX_HOME, read now so a test or a second copy has its own)."""
    return Path(os.environ.get("HYPNOMIX_HOME") or "~/.hypnomix").expanduser() / "daw.json"


def _conf():
    from hypnomix.core import atomic
    c = atomic.load_json(conf_path(), {}, warn=False)
    return c if isinstance(c, dict) else {}


def candidates():
    """Where the engine program is looked for, in order."""
    out = []
    env = os.environ.get("HYPNOMIX_ENGINE") or _conf().get("engine")
    if env:
        out.append(Path(env).expanduser())
    try:
        from hypnomix.app import engine_addon
        add = engine_addon.find()                        # the version this app names (else the newest other one, kept until the new one ran)
        if add:
            out.append(add)
    except Exception:
        pass
    exe = Path(sys.executable).resolve()
    contents = app_contents()
    if contents:                                         # inside Hypnomix.app: …/Contents/Resources/python/bin/python3
        out.append(contents / "Resources" / "engine" / "bin" / NAME)      # a test build's kit: found for one more version, then this line goes
    if not contents:                                                     # a venv or install: next to Python (never inside an app)
        out.append(exe.parent / NAME)
    src = os.environ.get("HYPNOMIX_ENGINE_SRC")                          # a developer's source build: run it with its env script
    if src:
        out.append(Path(src).expanduser() / "hypnomix" / "engine" / "engine-dev")
    return out


def app_contents():
    """The Contents folder of the Hypnomix.app this Python runs in, or None (a source checkout)."""
    for p in Path(sys.executable).resolve().parents:
        if p.name == "Contents" and p.parent.suffix == ".app":
            return p
    return None


# The engine's own words when it cannot start an audio device (hypnomix_engine.cc start_backend): then the supervisor
# tries the Dummy backend once, unless the arguments chose a backend themselves.
NO_AUDIO = re.compile(r"cannot (use backend|start the audio engine|use device|use input device|use output device|"
                      r"set sample rate|set buffer size)|^no backend", re.I)
DUMMY = "None (Dummy)"


def chose_backend(args):
    return any(a in ("-b", "--backend") or a.startswith("--backend=") or (a.startswith("-b") and len(a) > 2) for a in args)


def _chose(args, *opts):
    return any(a in opts or any(a.startswith(o + "=") for o in opts if o.startswith("--")) for a in args)


def without_devices(args):
    """The arguments without the device choices (-d, --input-device, --output-device): the Dummy backend has none."""
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in ("-d", "--device", "--input-device", "--output-device"):
            skip = True
        elif not any(a.startswith(o + "=") for o in ("--device", "--input-device", "--output-device")):
            out.append(a)
    return out


def default_output():
    """The Mac's default output device (System Settings → Sound → Output), or "" when it can't be read.
    The engine's CoreAudio backend otherwise takes the first device in its list, which may be a virtual one (a
    loopback driver) that never answers, and then the engine hangs before it is ready."""
    if sys.platform != "darwin":
        return ""
    try:
        r = subprocess.run(["/usr/sbin/system_profiler", "SPAudioDataType", "-json"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=15, stdin=subprocess.DEVNULL)
        for group in json.loads(r.stdout or "{}").get("SPAudioDataType", []):
            for dev in group.get("_items", []):
                if dev.get("coreaudio_default_audio_output_device") == "spaudio_yes" and dev.get("_name"):
                    return str(dev["_name"])
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
        pass
    return ""


def audio_args(args):
    """What the supervisor adds for the default CoreAudio backend when the arguments don't say: the Mac's default
    output, and no input device. With no input the engine never asks for the microphone (macOS holds the engine's
    start until someone answers that question); to record, choose one in "args" (`--input-device NAME`)."""
    if sys.platform != "darwin" or chose_backend(args) or _chose(args, "-d", "--device"):
        return []
    out = []
    if not _chose(args, "--output-device"):
        dev = default_output()
        out += ["--output-device", dev] if dev else []
    if not _chose(args, "--input-device"):
        out += ["--input-device", "None"]
    return out


def find_engine():
    for c in candidates():
        if c.name == "engine-dev" and not (c.parents[2] / "build" / "hypnomix" / "engine" / NAME).is_file():
            continue                                                    # the script is there, the build is not
        if c.is_file() and os.access(c, os.X_OK):
            return c
    return None


def last_session():
    """The session the engine last opened (daw.json "last"), if it is still there."""
    p = _conf().get("last")
    try:
        return snapshot(p) if isinstance(p, str) and p else None
    except ValueError:
        return None


def remember(path):
    """Keep the open session in daw.json ("last"), so the next start of the app opens it again."""
    from hypnomix.core import atomic
    try:
        c = _conf()
        if c.get("last") != str(path):
            c["last"] = str(path)
            conf_path().parent.mkdir(parents=True, exist_ok=True)
            atomic.write_json(conf_path(), c)
    except OSError:
        pass


NO_SESSION = ("no session is open yet: make one (File → New Session…, or New in the engine panel) or open one "
              "(File → Open Session…, or Open)")


def extra_args():
    raw = os.environ.get("HYPNOMIX_ENGINE_ARGS")
    if raw is None:
        raw = _conf().get("args") or ""
    return shlex.split(raw) if isinstance(raw, str) else [str(x) for x in raw]


def _fits(path):
    """ValueError when a part of this path is longer than any file system holds (255 characters). A Mac says so by itself;
    Windows answers "not found" for such a name, which would read as an ordinary missing folder."""
    if any(len(part) > 255 for part in re.split(r"[\\/]", str(path))):
        raise ValueError("not a usable path (a name in it is longer than a file system allows)")


def snapshot(path):
    """A session as given (its .ardour file, or its folder) -> the .ardour file (ValueError when it is neither)."""
    _fits(path)
    try:
        p = Path(str(path)).expanduser().absolute()      # the engine runs in the session's folder: a relative path would not be found
        if p.is_dir():
            snaps = sorted(p.glob("*.ardour"))
            p = next((s for s in snaps if s.stem == p.name), snaps[0] if snaps else p)
        if p.suffix != ".ardour" or not p.is_file():
            raise ValueError(f"not a HypnoMix Studio session: {p}")
    except (OSError, RuntimeError) as e:                        # a name too long for the disk, a home that cannot be found
        raise ValueError(f"not a usable session path ({getattr(e, 'strerror', None) or e})") from None
    return p


def free_port():
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


def post_json(url, payload, timeout=RPC_TIMEOUT):
    """POST bytes or a dict to an MCP endpoint -> (HTTP status, reply bytes). Never raises on HTTP errors."""
    data = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    try:
        with loopback.urlopen(req, timeout=timeout) as r:        # this computer only, never through a proxy
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def answers(url, timeout=1.5):
    """True when an MCP surface answers `initialize` at url."""
    try:
        code, raw = post_json(url, {"jsonrpc": "2.0", "id": 0, "method": "initialize",
                                    "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                               "clientInfo": {"name": "hypnomix-app", "version": "1"}}}, timeout)
        return code == 200 and "result" in json.loads(raw or b"{}")
    except Exception:
        return False


SERVER_NAME = "ardour-mcp-http"       # what the engine's own surface calls itself in its `initialize` reply
CORE_TOOLS = ("session_get_info", "tracks_list", "track_get_info")   # an engine always has these


def is_engine(url, timeout=1.5):
    """True when what answers at url is the engine: it calls itself by the engine's name and has its core tools. A window
    this app only attaches to listens on a fixed port that any program can take, so a listener that does not pass is
    not attached to (the name is no proof of who it is, but a stranger that is not even imitating it is turned away)."""
    try:
        code, raw = post_json(url, {"jsonrpc": "2.0", "id": 0, "method": "initialize",
                                    "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                               "clientInfo": {"name": "hypnomix-app", "version": "1"}}}, timeout)
        r = (json.loads(raw or b"{}") or {}).get("result") if code == 200 else None
        if not isinstance(r, dict) or str((r.get("serverInfo") or {}).get("name") or "") != SERVER_NAME:
            return False
        code, raw = post_json(url, {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, timeout)
        tl = ((json.loads(raw or b"{}") or {}).get("result") or {}).get("tools") if code == 200 else None
        return isinstance(tl, list) and set(CORE_TOOLS) <= {str(t.get("name")) for t in tl if isinstance(t, dict)}
    except Exception:
        return False


# Tools that only read, or move the playhead: every other tool counts as a CHANGE to the session (so does one this list
# has never heard of), and a change makes the session "dirty" until it is saved. Launching or stopping a cue slot is
# playback, like transport_play: it changes nothing the session file keeps. Names are the engine's own
# (`/` is read as `_`). session_quick_snapshot writes another snapshot and leaves the open session as it was.
# meters_get is a read, but its ensure_rms switches every route's meter type, which the session file keeps: on a clean
# session rpc() takes that argument out and sends it with the first change (_without_meter_switch), the Assistant never
# sends it (daw_assist STRIP_ARGS), and anything else that sends it is seen by the engine's own flag (engine_dirty).
# MIDI inputs and MPE (an engine that has them): the port list and a track's MPE setting are reads, and the per-note
# monitor attaches a tap to a MIDI input PORT and detaches it again (midi_monitor_get / midi_monitor_stop): nothing the
# session file keeps, and the engine does not mark its session dirty for it. Port flags (kept in the user's port
# settings, not the session), track input connections (saved with the session) and track_set_mpe are changes.
# Automation and the tempo map: automation_list, automation_get and tempo_get_map only read; a write, a clear, a state
# change, a tempo or meter change are kept in the session file.
READ_ONLY_TOOLS = frozenset("""
    hello_world session_get_info session_list_snapshots session_quick_snapshot session_export_mix export_status
    meters_get markers_list midi_note_get_json midi_note_list plugin_get_description plugin_list_available
    region_get_info region_get_peaks region_get_warp track_get_fader track_get_info track_get_regions tracks_list
    transport_get_state transport_play transport_stop transport_goto_start transport_goto_end transport_locate_bbt
    transport_locate_sample transport_next_marker transport_prev_marker transport_set_speed
    playlist_list take_list plugin_get_sidechain group_list meters_stream_info session_get_card track_bounce
    cue_list ab_list cue_launch cue_stop scene_launch
    midi_ports_list track_get_mpe midi_monitor_get midi_monitor_stop
    automation_list automation_get tempo_get_map
""".split())
# Tools the page may not call through POST /mcp: the meter stream's address and token are the app's (daw_meters.py
# relays the stream on the app's own origin), so neither reaches a page or the Assistant.
APP_ONLY_TOOLS = frozenset({"meters_stream_info"})
NEUTRAL_METHODS = ("initialize", "ping", "tools/list", "notifications/", "resources/", "prompts/")


def _events(payload):
    """What a JSON-RPC body (bytes, dict or list) does to the session: [(id, "change" | "save")], in order. A message
    that only reads gives nothing; a body that is not JSON-RPC at all counts as one change."""
    try:
        msg = json.loads(payload) if isinstance(payload, (bytes, bytearray, str)) else payload
    except ValueError:
        return [(None, "change")]
    out = []
    for m in (msg if isinstance(msg, list) else [msg]):
        if not isinstance(m, dict):
            out.append((None, "change"))
            continue
        method = str(m.get("method") or "")
        if method == "tools/call":
            pr = m.get("params") if isinstance(m.get("params"), dict) else {}
            name = str(pr.get("name") or "").replace("/", "_")
            args = pr.get("arguments") if isinstance(pr.get("arguments"), dict) else {}
            if name == "session_save":                     # a save as another snapshot, staying on this one, saves nothing of it
                other = bool(args.get("snapshotName")) and args.get("switchToSnapshot") is not True
                if not other:
                    out.append((m.get("id"), "save"))
            elif name not in READ_ONLY_TOOLS:
                out.append((m.get("id"), "change"))
        elif not any(method == n or (n.endswith("/") and method.startswith(n)) for n in NEUTRAL_METHODS):
            out.append((m.get("id"), "change"))
    return out


METER_SWITCH = ("ensure_rms", "ensureRms")


def _auto_writes(payload, tool="automation_write"):
    """The automation_write (or automation_clear) calls in a JSON-RPC body (bytes, dict or list): [(id, arguments)].
    Every name the engine takes for it counts (automation_write, automation/write, automation.write); a body that
    names no automation tool in plain text and has no escape is not parsed."""
    if isinstance(payload, (bytes, bytearray, str)):
        raw = payload if isinstance(payload, (bytes, bytearray)) else payload.encode("utf-8", "replace")
        if b"automation" not in raw and b"\\u" not in raw:
            return []
        try:
            payload = json.loads(payload)
        except ValueError:
            return []
    out = []
    for m in (payload if isinstance(payload, list) else [payload]):
        pr = m.get("params") if isinstance(m, dict) and m.get("method") == "tools/call" else None
        if isinstance(pr, dict) and str(pr.get("name") or "").replace("/", "_").replace(".", "_") == tool:
            out.append((m.get("id"), pr.get("arguments") if isinstance(pr.get("arguments"), dict) else {}))
    return out


def _refused(payload, text):
    """The reply to a body that is not sent: each tools/call answered as a tool error with `text` (nothing reached
    the engine, so nothing became unsaved)."""
    if isinstance(payload, (bytes, bytearray, str)):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = {}
    one = lambda m: {"jsonrpc": "2.0", "id": m.get("id") if isinstance(m, dict) else None,
                     "result": {"isError": True, "content": [{"type": "text", "text": text}]}}
    body = [one(m) for m in payload] if isinstance(payload, list) else one(payload)
    return json.dumps(body).encode()


def _without_meter_switch(payload):
    """A body that asks meters_get to switch every route's meter type to one with RMS (the view does once as it
    connects) -> (the same body without that argument, True); any other body -> (it, False). The switch is kept in the
    session file, so on a clean session the engine would call it unsaved though the person changed nothing."""
    if isinstance(payload, (bytes, bytearray, str)):
        if not any(k in (payload if isinstance(payload, str) else payload.decode("utf-8", "replace")) for k in METER_SWITCH):
            return payload, False
        try:
            msg = json.loads(payload)
        except ValueError:
            return payload, False
    else:
        try:
            msg = json.loads(json.dumps(payload))                # a copy: the caller's body is never changed
        except (TypeError, ValueError):
            return payload, False
    found = False
    for m in (msg if isinstance(msg, list) else [msg]):
        pr = m.get("params") if isinstance(m, dict) and m.get("method") == "tools/call" else None
        args = pr.get("arguments") if isinstance(pr, dict) and str(pr.get("name") or "") == "meters_get" else None
        if isinstance(args, dict) and any(args.get(k) for k in METER_SWITCH):
            for k in METER_SWITCH:
                args.pop(k, None)
            found = True
    if not found:
        return payload, False
    return (json.dumps(msg).encode() if isinstance(payload, (bytes, bytearray, str)) else msg), True


def end_preview(why):
    """Put the Assistant's live 'Hear it' back (nothing happens when none is live). Called before any save or scan."""
    try:
        from hypnomix.app import chat as _chat
        _chat.preview_end(why)
    except ImportError:
        pass


def _failed_ids(code, raw):
    """The ids of the messages in an engine reply that failed (a JSON-RPC error, or a tool result with isError);
    None when the reply cannot be read (taken as: it worked)."""
    if code != 200:
        return True
    try:
        text = (raw or b"").decode("utf-8", "replace")
        if text.lstrip().startswith(("event:", "data:")):                       # SSE framing
            text = "".join(ln[5:] for ln in text.splitlines() if ln.startswith("data:"))
        msg = json.loads(text) if text.strip() else None
    except ValueError:
        return None
    bad = set()
    for m in (msg if isinstance(msg, list) else [msg]):
        if isinstance(m, dict) and (m.get("error") or (isinstance(m.get("result"), dict) and m["result"].get("isError"))):
            bad.add(m.get("id"))
    return bad


# What the engine is given of the app's environment: no keys, tokens or passwords (the engine loads other people's
# plug-ins in its own process), whatever else the app's shell had.
ENV_KEEP = frozenset("""PATH HOME USER LOGNAME LANG LANGUAGE TZ TMPDIR TMP TEMP SHELL TERM __CF_USER_TEXT_ENCODING
                        SYSTEMROOT WINDIR COMSPEC PATHEXT USERPROFILE APPDATA LOCALAPPDATA""".split())
ENV_PREFIXES = ("LC_", "HYPNOMIX_", "ARDOUR_", "JACK_", "PIPEWIRE_", "PULSE_", "XDG_")
ENV_SECRET = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH", re.I)


def engine_env():
    out = {k: v for k, v in os.environ.items()
           if (k in ENV_KEEP or k.startswith(ENV_PREFIXES)) and not ENV_SECRET.search(k)}
    out.setdefault("PATH", os.defpath)
    return out


class Busy(RuntimeError):
    """Another start, stop, restart or open is in progress (HTTP 409)."""


class Engine:
    """One engine process (or one attached window), started, watched and stopped by the app."""

    def __init__(self, binary=None, attach_url=None):
        self._binary = binary                      # None: look it up each time (it may be installed later)
        self.attach_url = attach_url or os.environ.get("HYPNOMIX_ENGINE_URL") or ATTACH_URL
        self.lock = threading.RLock()
        self._op = threading.Lock()                # held while a process is stopped and the next one started: one at a time
        self.proc = None
        self.mode = None                           # "engine" (ours) | "attached" (someone else's window) | None
        self.state = "stopped"                     # stopped | starting | running | attached | crashed | exited | failed
        self.port = None
        self.session = None                        # what the engine was asked to open (a path), or a new one
        self.new = None                            # (folder, name) for a new session
        self.error = ""
        self.log = []
        self.restarts = []                         # times of automatic restarts
        self.started = 0.0
        self._stopping = False
        self._gen = 0                              # which process a watcher thread belongs to
        self._failed = ""                          # the engine's own ERROR line, if it printed one
        self._want = None                          # the port this process was told to listen on: READY must name it
        self._tools = (0.0, None)
        self.dummy = False                         # started on the Dummy backend because no audio device would start
        self.notice = ""                           # a plain note for the DAW view (why there is no sound)
        self.backend = ""                          # the backend the engine said it runs on (its READY line)
        self.dirty = False                         # a changing call went through since the last save (or since it started)
        self._edits = 0                            # changes so far: a save only clears what it saw
        self.edirty = False                        # the engine's OWN unsaved flag, as last read (changes made without the app)
        self._eseen = 0.0                          # when it was last read (or last tried)
        self._saves = 0                            # saves so far: a look that started before a save is older than it
        self._meters_wanted = False                # the view's RMS meter switch, held back while the session is clean

    # ---------------------------------------------------------------- where
    def binary(self):
        return Path(self._binary) if self._binary else find_engine()

    def url(self):
        if self.mode == "engine" and self.port:
            return f"http://127.0.0.1:{self.port}/mcp"
        if self.mode == "attached":
            return self.attach_url
        return None

    def connected(self):
        return self.state in ("running", "attached") and bool(self.url())

    # ---------------------------------------------------------------- start / stop
    @contextlib.contextmanager
    def _transition(self):
        """One program is started, stopped or replaced at a time; a second request is told so, not queued."""
        if not self._op.acquire(blocking=False):
            raise Busy("the engine is being started, stopped or opened on a session right now: wait a moment and try again")
        try:
            yield
        finally:
            self._op.release()

    def start(self, session=None, new=None, wait=True, _restart_gen=None):
        """Start our engine (on a session, a new one, or none). Without an engine program, attach instead."""
        if session:
            session = snapshot(session)                # a folder works too (`--session DIR`, /api/daw/start)
        try:
            with self._transition():
                spawned = self._spawn(session, new, _restart_gen)
        except Busy:
            if _restart_gen is not None:               # the watcher's own restart: the person's request does it instead
                return self.status()
            raise
        return self._await(spawned, wait)

    def _cwd(self):
        """The engine's working folder: the session's own (never the app's)."""
        c = Path(self.new[0]) if self.new else Path(self.session).parent if self.session else None
        return str(c) if c is not None and c.is_dir() else tempfile.gettempdir()

    def _spawn(self, session=None, new=None, _restart_gen=None):
        """Start the process (the caller holds the transition) -> (generation, process), or None when nothing was started
        (attached, already running, no session yet, the program would not start): the status says which."""
        with self.lock:
            if _restart_gen is not None and (self._stopping or _restart_gen != self._gen):
                return None                            # stopped (or opened elsewhere) while the crash was handled
            b = self.binary()
            if b is None:
                self.attach()
                return None
            if self.proc and self.proc.poll() is None:
                if session is not None and str(session) != self.session:
                    raise RuntimeError(f"the engine is running on {Path(self.session or '').name or 'another session'}: "
                                       "use Open to change the session")
                return None
            if session is not None or new is not None:   # only a start that spawns changes what a restart would reopen
                self.session, self.new = (str(session) if session else None), (tuple(new) if new else None)
            if not self.session and not self.new:      # the engine needs a session to run: wait for New / Open
                self.mode, self.state, self.port, self.error = None, "stopped", None, NO_SESSION
                return None
            self.mode, self.state, self.port, self.error = "engine", "starting", None, ""
            self._stopping = False
            self._failed = ""
            lost = bool(_restart_gen is not None and (self.dirty or self.edirty))   # the engine died with changes the file does not have
            if _restart_gen is None and (session is not None or new is not None) and self.notice == LOST_NOTICE:
                self.notice = ""                       # another session was opened on purpose: the note is about the old one
            self._clean()                              # a session just loaded has nothing unsaved
            if lost:
                self.notice = LOST_NOTICE              # kept until the next Save or Restart: never lose work silently
            args = extra_args()
            port = free_port()
            argv = [str(b), "--port", str(port), "--parent-pid", str(os.getpid()), *args]   # stops if the app dies
            if self.dummy and not chose_backend(args):
                argv = argv[:5] + without_devices(args) + ["-b", DUMMY]   # no sound; everything else works
            elif not self.dummy:
                argv += audio_args(args)
            if self.new:                               # after "--" a name is a name, never an option
                argv += ["--new", "--", str(Path(self.new[0]) / self.new[1]), self.new[1]]
            elif self.session:
                sp = Path(self.session)
                argv += ["--", str(sp.parent), sp.stem]
            self._say("$ " + " ".join(shlex.quote(a) for a in argv))
            try:
                self.proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                             encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                                             start_new_session=True, env=engine_env(), cwd=self._cwd())
            except OSError as e:
                self.state, self.error, self.mode = "failed", f"could not start {b.name}: {e}", None
                return None
            self.started = time.time()
            self._gen += 1
            self._want = port
            gen, proc = self._gen, self.proc
            try:
                from hypnomix.app import engine_addon
                engine_addon.mark_running(b, proc.pid)   # so another process (the command line, the Assistant) can see it runs
            except Exception:
                pass
        for target in (self._read, self._drain, self._deadline):
            threading.Thread(target=target, args=(proc, gen), daemon=True).start()
        return gen, proc

    def _await(self, spawned, wait):
        if spawned is not None and wait:
            t = time.time()
            while time.time() - t < READY_TIMEOUT * 2 + 15 and self.state == "starting":   # (a second try on the Dummy backend)
                time.sleep(0.05)
            if self.state == "starting":
                self.error = f"the engine did not say it was ready within {READY_TIMEOUT:.0f} s"
        return self.status()

    def _deadline(self, proc, gen):
        """A start that is not ready within READY_TIMEOUT: killed, then once more on the Dummy backend if the audio
        device may be what hangs (nothing in the arguments chose a backend), else reported as failed."""
        t = time.time()
        while time.time() - t < READY_TIMEOUT:
            time.sleep(0.1)
            with self.lock:
                if gen != self._gen or self.state != "starting" or proc.poll() is not None:
                    return
        with self.lock:
            if gen != self._gen or self.state != "starting":
                return
            self._gen += 1                             # its reader lets go: ending it now is not a crash
            new_gen = self._gen
            fallback = not self.dummy and not chose_backend(extra_args())
            if fallback:
                self.dummy = True
                self.notice = (f"The audio device did not answer within {READY_TIMEOUT:.0f} s, so the engine runs "
                               "without sound (the Dummy backend): the session, edits, waveforms and exports all "
                               "work. Choose another output in System Settings → Sound, then press Restart.")
                self._say("(the audio device did not answer: starting the engine again on the Dummy backend)")
            else:
                # no process is the engine's any more in the same moment the state says "failed" (the status of a start that
                # was waiting would otherwise name the pid of a process that is being killed); it is killed just below
                self.state, self.mode, self.port, self.proc = "failed", None, None, None
                self.error = (f"the engine was not ready within {READY_TIMEOUT:.0f} s, so it was stopped: press Restart "
                              "to try again (a different audio device or backend may help)")
                self._say("(the engine was not ready in time: stopped)")
        self._signal(proc, getattr(signal, "SIGKILL", 9))
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
        with self.lock:
            if self.proc is proc:
                self.proc = None
        if fallback:
            self.start(wait=False, _restart_gen=new_gen)

    def attach(self):
        """Use a HypnoMix Studio window that is already running (its MCP surface on), without owning it."""
        with self.lock:
            if self.mode == "engine" and self.proc and self.proc.poll() is None:
                return self.status()
            if is_engine(self.attach_url):
                if self.mode != "attached":
                    self._clean()
                self.mode, self.state, self.error = "attached", "attached", ""
            else:
                self.mode, self.state = None, "stopped"
                self.error = (f"no engine program found ({NAME}), and no HypnoMix Studio engine answers at {self.attach_url} "
                              + ("(something else does, and it was left alone)" if answers(self.attach_url, timeout=0.4) else "")
                              + ": open a HypnoMix Studio window and switch on Preferences → Control Surfaces → MCPHttp, or add HypnoMix Studio in Setup")
            return self.status()

    def stop(self, timeout=8.0):
        with self._transition():
            return self._stop(timeout)

    def shutdown(self):
        """The app is quitting: stop the engine whether or not another request is in the middle of something. It is
        quick (4 s at the most: the updater's helper waits 10 s for the app before it ends it)."""
        got = self._op.acquire(timeout=1.0)
        try:
            self._stop(2.0, kill_wait=1.0)
        finally:
            if got:
                self._op.release()

    def _stop(self, timeout=8.0, kill_wait=5.0):
        with self.lock:
            if self.mode == "attached":
                self.mode, self.state = None, "stopped"   # we let go of it; the window itself keeps running
                self._clean()
                return self.status()
            self._stopping = True
            p = self.proc
        if p and p.poll() is None:
            self._signal(p, signal.SIGTERM)            # its own process group (start_new_session): it and what it started
            try:
                p.wait(timeout)
            except subprocess.TimeoutExpired:
                self._signal(p, getattr(signal, "SIGKILL", 9))
                try:
                    p.wait(kill_wait)
                except subprocess.TimeoutExpired:
                    pass
        if p and os.name != "nt":                      # whatever of its group is still there (a launcher script ended
            self._signal(p, getattr(signal, "SIGKILL", 9))   # first, an engine hung while shutting down) goes too
        if p:
            try:
                from hypnomix.app import engine_addon
                engine_addon.clear_running(p.pid)
            except Exception:
                pass
        with self.lock:
            if self.proc is p:                         # (not a newer one: only the process that was signalled is let go)
                self.proc, self.mode, self.port, self.state = None, None, None, "stopped"
                self._clean()
        return self.status()

    @staticmethod
    def _signal(p, sig):
        try:
            if os.name == "nt":
                p.kill() if sig == getattr(signal, "SIGKILL", 9) else p.terminate()
            else:
                os.killpg(p.pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def restart(self):
        if self.mode == "attached":
            raise RuntimeError("attached to a HypnoMix Studio window the app did not start: restart it there")
        with self._transition():
            self._stop()
            self.dummy, self.notice = False, ""        # Restart tries the audio device again
            spawned = self._spawn()
        return self._await(spawned, True)

    def open(self, path):
        """Open a session: start the engine on it (restarting ours if it runs another one)."""
        p = snapshot(path)
        if self.binary() is None:
            self.attach()
            raise RuntimeError("attached to a HypnoMix Studio window: open the session in that window (Session → Open)")
        prev = self.session if self.mode == "engine" else None
        with self._transition():
            self._stop()
            spawned = self._spawn(session=p)
        st = self._await(spawned, True)
        if st["state"] == "failed" and prev and prev != str(p) and Path(prev).is_file():
            # the engine refused the new session: the one that was open is opened again, and the refusal is said
            why = st["error"]
            with self._transition():
                self._stop()
                spawned = self._spawn(session=Path(prev))
            st = self._await(spawned, True)
            if st["state"] == "running":
                with self.lock:
                    self.notice = f"Could not open {p.name} ({why}): {Path(prev).name} is open again."
                st = self.status()
        return st

    @staticmethod
    def check_new(folder, name):
        """The (folder, name) of a new session, or ValueError saying what is wrong with them (nothing is touched)."""
        name = str(name).strip()
        if not name or re.search(r'[\\/:*?"<>|\x00-\x1f]', name) or name.startswith(("-", ".")):
            raise ValueError("give the new session a name without / \\ : * ? \" < > |, that does not start with - or .")
        if len(name.encode("utf-8")) > 200:
            raise ValueError("that session name is too long (200 characters at most)")
        _fits(folder)
        try:
            d = Path(str(folder)).expanduser().absolute()     # absolute: the engine starts inside this folder
            if (d / name).exists():
                raise ValueError(f"{d / name} already exists: open it instead, or choose another name")
            if d.exists() and not d.is_dir():
                raise ValueError(f"{d} is not a folder")
        except (OSError, RuntimeError) as e:           # a folder name too long for the disk, a home that cannot be found
            raise ValueError(f"not a usable folder ({getattr(e, 'strerror', None) or e})") from None
        return str(d), name

    def new_session(self, folder, name):
        new = self.check_new(folder, name)
        if self.binary() is None:
            self.attach()
            if self.mode != "attached":              # nothing answered either: there is no engine at all, so say that
                try:
                    from hypnomix.app import engine_addon
                    s = engine_addon.state()
                    how = "the Add HypnoMix Studio button is in Setup" if s["available"] else s["message"]
                except Exception:
                    how = "see Setup"
                raise RuntimeError("no engine is installed on this computer, so there is nothing to make a new session in "
                                   f"(HypnoMix Studio: {how})")
            raise RuntimeError("attached to a HypnoMix Studio window: make the new session in that window (Session → New)")
        with self._transition():
            self._stop()
            spawned = self._spawn(new=new)
        return self._await(spawned, True)

    # ---------------------------------------------------------------- unsaved work
    def unsaved(self):
        """Is there work in the engine this app started that Stop, Restart, Open or New would lose? The app's own count,
        or the engine's own flag (a change a command made over the engine's port never passed the app), read at most
        every ENGINE_DIRTY_TTL seconds like the page poll's. Never for a window the app only attached to (it is not
        the app's to protect)."""
        if not (self.mode == "engine" and self.state in ("running", "starting")):
            return False
        return bool(self.dirty or self.engine_dirty())

    def _clean(self):
        """Nothing unsaved: a session just started or opened, or one let go of (the app's count and the engine's flag)."""
        self.dirty, self._edits = False, 0
        self.edirty, self._eseen = False, 0.0
        self._meters_wanted = False

    def engine_dirty(self, max_age=ENGINE_DIRTY_TTL):
        """The engine's own unsaved flag (session_list_snapshots "dirty": its Session::dirty()), read when the last
        reading is older than max_age seconds (0: now). Read-only on the engine. When it does not answer, or is an
        older engine that does not say, the last reading stands (False for a session just opened): an error is no
        information, never a reason to block or to clear. Only for an engine this app started (never an attached
        window); the engine's flag never clears the app's own count. Read only by unsaved() and GET /api/daw/state."""
        if not (self.mode == "engine" and self.state == "running" and self.url()):
            return False
        if max_age and time.time() - self._eseen < max_age:
            return self.edirty
        saves = self._saves
        value = None
        try:
            r = self.call("tools/call", {"name": "session_list_snapshots", "arguments": {}}, timeout=ENGINE_DIRTY_TIMEOUT) or {}
            sc = r.get("structuredContent") if isinstance(r, dict) and not r.get("isError") else None
            value = sc.get("dirty") if isinstance(sc, dict) else None
        except Exception:
            pass
        with self.lock:
            self._eseen = time.time()
            if isinstance(value, bool) and saves == self._saves:   # a save that went through meanwhile is newer than this
                self.edirty = value
            out = self.edirty
        return out

    def _switch_meters(self):
        """The view's RMS meter switch, held back while the session was clean, goes in once there is unsaved work anyway
        (the next save keeps it with the person's changes)."""
        with self.lock:
            if not self._meters_wanted:
                return
            self._meters_wanted = False
        try:
            self.call("tools/call", {"name": "meters_get", "arguments": {"ensure_rms": True}}, timeout=ENGINE_DIRTY_TIMEOUT)
        except Exception:
            pass

    def save(self):
        """Save the open session through the engine (session_save) -> the status. RuntimeError when it did not work."""
        if not self.connected():
            raise RuntimeError("the engine is not running: there is nothing to save")
        end_preview("the session is being saved")       # a value the Assistant's Hear it is trying must not be written into the person's file
        r = self.call("tools/call", {"name": "session_save", "arguments": {}}, timeout=60) or {}
        if r.get("isError"):
            raise RuntimeError(((r.get("content") or [{}])[0].get("text")) or "the engine could not save the session")
        with self.lock:
            if self.notice == LOST_NOTICE:
                self.notice = ""
        return self.status()

    def _track(self, payload, edits0, code, raw):
        """After a call went through: what it did to 'unsaved'. code None: no answer (a timeout may still have applied
        the change: it counts); a refused connection never reached the engine."""
        events = _events(payload)
        if not events:
            return
        bad = _failed_ids(code, raw) if code is not None else set()
        with self.lock:
            mine = 0
            for rid, kind in events:
                if bad is True or (isinstance(bad, set) and rid in bad and rid is not None):
                    continue                           # it said no: nothing changed (or nothing was saved)
                if kind == "change":
                    mine += 1
                    self._edits += 1
                    self.dirty = True
                else:
                    self._saves += 1
                    self.edirty, self._eseen = False, time.time()   # the engine's own flag: a save clears it
                    if self._edits - mine == edits0:   # a save clears what it saw, not an edit that came in meanwhile
                        self.dirty = False

    # ---------------------------------------------------------------- the process
    def _say(self, line):
        self.log.append(line)
        if len(self.log) > 400:
            del self.log[:100]

    def _drain(self, proc, gen):
        """The engine's own log (standard error): kept for the engine panel, never read for READY or ERROR."""
        try:
            for line in proc.stderr:
                self._say(line.rstrip("\r\n"))
        except Exception:
            pass
        finally:
            try:
                proc.stderr.close()
            except Exception:
                pass

    def _read(self, proc, gen):
        try:
            for line in proc.stdout:
                line = line.rstrip("\r\n")
                self._say(line)
                m, e = READY.match(line), ERROR.match(line)
                if not (m or e):
                    continue
                ran = None
                with self.lock:
                    if gen != self._gen or self.state != "starting":
                        continue                       # only the first READY (or ERROR) of this process counts
                    if m and int(m.group(1)) == self._want:   # the port it was told to use, nothing else
                        self.port, self.state = int(m.group(1)), "running"
                        ran = proc.args[0] if isinstance(proc.args, (list, tuple)) and proc.args else None
                        b = re.search(r'backend="([^"]*)"', line)
                        self.backend = b.group(1) if b else ""
                        if self.new:                   # made: from now on (a restart too) it is opened, not made again
                            made = Path(self.new[0]) / self.new[1] / f"{self.new[1]}.ardour"
                            if made.is_file():
                                self.session, self.new = str(made), None
                        if self.session:
                            remember(self.session)
                    elif e:
                        self._failed = e.group(1).strip()
                if ran:                                # the add-on's engine has run: its older versions are not needed any more
                    try:
                        from hypnomix.app import engine_addon
                        threading.Thread(target=engine_addon.note_ran, args=(ran,), daemon=True).start()   # removing old versions can take a moment
                    except Exception:
                        pass
        except Exception as ex:                        # whatever happens to the pipe, the exit below is still handled
            self._say(f"(reading the engine's output stopped: {ex})")
            try:
                for _ in proc.stdout:                  # and it is still emptied, so the engine never blocks on it
                    pass
            except Exception:
                pass
        code = proc.wait()
        try:
            from hypnomix.app import engine_addon
            engine_addon.clear_running(proc.pid)
        except Exception:
            pass
        try:
            proc.stdout.close()
        except Exception:
            pass
        with self.lock:
            if gen != self._gen:
                return
            if self._stopping:
                return
            self._say(f"(the engine stopped: exit code {code})")
            self.port, self.proc = None, None
            if code == 0 and not self._failed:        # it ended by itself, without the app asking: say so, keep the session
                self.state, self.mode = "exited", None
                name = Path(self.session).name if self.session else (self.new[1] if self.new else "the session")
                self.error = (f"the engine stopped unexpectedly (it exited by itself): press Start to open {name} again; "
                              "what was not saved before it stopped is not in the session file")
                return
            if (self._failed and self.state == "starting" and not self.dummy and NO_AUDIO.search(self._failed)
                    and not chose_backend(extra_args())):
                # no audio device would start (none plugged in, or it is busy): once more on the Dummy backend
                self.dummy = True
                self.notice = ("No audio device could be started, so the engine runs without sound (the Dummy backend): "
                               "the session, edits, waveforms and exports all work. Plug in or choose an output in "
                               f"System Settings → Sound, then press Restart. (The engine said: {self._failed})")
                self._say("(no audio device: starting the engine again on the Dummy backend)")
                self._failed = ""                      # still "starting": a start() that waits keeps waiting
                fallback = True
            elif self._failed or code == 2:           # it said why, or the arguments were wrong
                self.state, self.mode = "failed", None
                self.error = self._failed or f"the engine refused its arguments (exit code {code})"
                return
            else:
                fallback = False
        if fallback:
            self.start(wait=False, _restart_gen=gen)
            return
        with self.lock:
            if gen != self._gen or self._stopping:     # stopped or opened elsewhere in the meantime
                return
            now = time.time()
            self.restarts = [t for t in self.restarts if now - t < RESTART_WINDOW]
            if len(self.restarts) >= MAX_RESTARTS:
                self.state, self.mode = "failed", None
                self.error = (f"the engine stopped {MAX_RESTARTS + 1} times within a minute (last exit code {code}); "
                              "it was not started again: see its log")
                return
            self.restarts.append(now)
            self.state = "crashed"
            self.error = f"the engine stopped (exit code {code}); starting it again on the same session"
        self.start(wait=False, _restart_gen=gen)

    # ---------------------------------------------------------------- talking to it
    def rpc(self, payload, timeout=RPC_TIMEOUT):
        """Forward one JSON-RPC request (bytes or dict) -> (HTTP status, reply bytes). A changing call marks the session
        unsaved; a successful session_save clears it."""
        url = self.url()
        if self.mode is None and self.binary() is None:       # nothing yet: a window may have been opened since
            self.attach()
            url = self.url()
        if not url:
            return 503, _err(None, -32000, "the engine is not running" + (f" ({self.state})" if self.state != "stopped" else ""))
        if any(kind == "save" for _, kind in _events(payload)):   # however a save arrives (the page's proxy, the Assistant, a script):
            end_preview("the session is being saved")               # a value Hear it is trying is put back first, never written to the file
        why = self.automation_refusal(payload, url)
        if why:                                            # the smooth-automation rules: refused here, never sent
            return 200, _refused(payload, why)
        held, switch = _without_meter_switch(payload)
        if switch and not self.dirty and not self.edirty:          # (the last reading: a call is never held up by a look)
            payload, self._meters_wanted = held, True          # a clean session stays clean: the switch waits for a change
        edits0 = self._edits
        try:
            code, raw = post_json(url, payload, timeout)
        except Exception as e:
            refused = isinstance(e, (ConnectionRefusedError, ValueError)) or isinstance(getattr(e, "reason", None), ConnectionRefusedError)
            if not refused:                                    # it may have got there: count the change
                self._track(payload, edits0, None, None)
            if self.mode == "attached":
                self.mode, self.state = None, "stopped"
                self.error = f"the HypnoMix Studio window at {url} stopped answering"
            return 502, _err(None, -32000, f"engine unreachable at {url}: {e}")
        self._track(payload, edits0, code, raw)
        if self._meters_wanted and self.dirty:
            self._switch_meters()
        return code, raw

    def _read_tool(self, url, tool, args):
        """One read sent straight to the engine (no unsaved tracking: it only reads) -> its structured reply, or None."""
        try:
            code, raw = post_json(url, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                        "params": {"name": tool, "arguments": args}}, RPC_TIMEOUT)
            res = (json.loads(raw or b"{}") or {}).get("result") or {}
        except Exception:
            return None
        if code != 200 or res.get("isError"):
            return None
        sc = res.get("structuredContent")
        if sc is None:
            try:
                sc = json.loads("".join(c.get("text", "") for c in res.get("content") or [] if isinstance(c, dict)))
            except ValueError:
                return None
        return sc if isinstance(sc, dict) else None

    def automation_refusal(self, payload, url):
        """Why a body's automation_write must not reach the engine (hypnomix's smooth-automation rules,
        engineer/automation_rules.py), or "". Level controls and plug-in parameters (a plug-in only to the mixed-bus
        rule): the route's facts (is it a bus, what it carries) are read from the engine first, and for a level control
        the line as it is now. A clear on a plug-in lane is never refused (it removes movement)."""
        from hypnomix.engineer import automation_rules as AR
        for _, a in _auto_writes(payload):
            if not AR.checked(a.get("control")):
                continue
            rid, ctl = str(a.get("track_id") or ""), str(a.get("control") or "")
            facts = self._read_tool(url, "automation_list", {"track_id": rid})
            if facts is None:
                return AR.sentence([f"what route {rid} carries could not be read from the engine (automation_list)"])
            cur = next((c.get("current") for c in facts.get("controls") or [] if c.get("control") == ctl), None)
            line = None
            if AR.kind(ctl) in AR.LEVEL_KINDS and str(a.get("mode") or "replace-range") != "replace-all":
                line = AR.line_from(self._read_tool(url, "automation_get", {"track_id": rid, "control": ctl}), cur)
            problems = AR.check(a, facts, line, read=lambda tool, args: self._read_tool(url, tool, args))
            if problems:
                return AR.sentence(problems)
        for _, a in _auto_writes(payload, "automation_clear"):
            if AR.kind(a.get("control")) not in AR.LEVEL_KINDS or (a.get("start") is None and a.get("end") is None):
                continue
            now = self._read_tool(url, "automation_get", {"track_id": str(a.get("track_id") or ""), "control": str(a.get("control") or "")})
            problems = AR.check_clear(a, now) if now is not None else ["the lane could not be read from the engine (automation_get)"]
            if problems:
                return AR.sentence(problems)
        return ""

    def call(self, method, params=None, timeout=RPC_TIMEOUT):
        """One request -> its result (raises RuntimeError with the engine's message on an error)."""
        body = {"jsonrpc": "2.0", "id": int(time.time() * 1000) % 1000000, "method": method}
        if params is not None:
            body["params"] = params
        code, raw = self.rpc(body, timeout)
        try:
            msg = json.loads(raw or b"{}")
        except ValueError:
            raise RuntimeError(f"the engine replied with something that is not JSON (HTTP {code})")
        if msg.get("error"):
            raise RuntimeError(str(msg["error"].get("message") or msg["error"]))
        return msg.get("result")

    def tools(self, ttl=30.0):
        """The engine's tools/list (cached for ttl seconds), or [] when it is not connected."""
        if not self.connected():
            return []
        t, cached = self._tools
        if cached is not None and time.time() - t < ttl and cached[0] == self.url():
            return cached[1]
        try:
            self.call("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                     "clientInfo": {"name": "hypnomix-assistant", "version": "1"}})
            tl = (self.call("tools/list", {}) or {}).get("tools") or []
        except Exception:
            return []
        self._tools = (time.time(), (self.url(), tl))
        return tl

    def status(self):
        b = self.binary()
        with self.lock:
            if b and self.mode is None and self.error.startswith("no engine program found"):
                self.error = ""                           # HypnoMix Studio was added since that was said: it is no longer true
            pid = self.proc.pid if self.proc and self.proc.poll() is None else None
            return dict(state=self.state, mode=self.mode, connected=self.connected(), url=self.url(),
                        binary=str(b) if b else None, attach_url=self.attach_url, pid=pid, port=self.port,
                        session=self.session, new=list(self.new) if self.new else None, error=self.error,
                        restarts=len([t for t in self.restarts if time.time() - t < RESTART_WINDOW]),
                        backend=self.backend if pid else "", dummy=self.dummy, notice=self.notice,
                        dirty=bool((self.dirty or (self.edirty and self.mode == "engine"))
                                   and self.state in ("running", "attached")),
                        log=self.log[-40:], uptime=round(time.time() - self.started, 1) if pid else 0)


def _err(rid, code, message):
    return json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}).encode()


ENGINE = Engine()
STATE = {"daw": False}            # the app was started in DAW mode (`hypnomix app --daw`)


# ---------------------------------------------------------------- the DAW view's files
ROOT = Path(__file__).with_name("daw")
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".svg": "image/svg+xml", ".png": "image/png"}


def page(token, nonce):
    """The DAW view's page: the token in, and the nonce on each of its inline scripts (the CSP lets nothing else
    inline run; its other scripts are files of this folder)."""
    from hypnomix.app import update as UP
    html = (ROOT / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", token).replace("__VERSION__", UP.current())
    return html.replace("<script>", f'<script nonce="{nonce}">').encode()


def static(rel):
    """A file of the DAW view, only from inside its folder, only known types, and never its page raw (the page is
    only served with the token and the nonce put in: see page())."""
    f = (ROOT / rel).resolve()
    if ROOT.resolve() not in f.parents or not f.is_file() or f.suffix not in TYPES or f.suffix == ".html":
        return None
    return 200, f.read_bytes(), TYPES[f.suffix]


def available(probe=False):
    """Is DAW mode usable here: the app was started with --daw, or an engine program is found, or one is running or
    attached? (With probe, a HypnoMix Studio window answering on the attach address counts too: a short look.) An app
    that has not added HypnoMix Studio (Setup → Extras) and has no engine says no, so its page shows no Studio tab."""
    if STATE["daw"] or ENGINE.mode in ("engine", "attached") or find_engine() is not None:
        return True
    return bool(probe and is_engine(ENGINE.attach_url, timeout=0.4))


def dirty():
    """True while the engine this app started holds changes that were not saved (for the updater and the native app:
    ask the person before quitting or restarting)."""
    return ENGINE.unsaved()


def save():
    """Save the open session through the engine (session_save): the status, or RuntimeError."""
    return ENGINE.save()


# ---------------------------------------------------------------- the server's routes
def handle_get(path, q, token):
    if path in ("/daw", "/daw/index.html"):           # the page's assets are relative to /daw/: always go there
        return 302, b"", TYPES[".html"], {"Location": "/daw/"}
    if path == "/daw/":
        nonce = secrets.token_urlsafe(16)
        return 200, page(token, nonce), TYPES[".html"], None, nonce
    if path.startswith("/daw/"):
        return static(path[len("/daw/"):]) or (404, {"error": "not found"})
    if path == "/api/daw/state":
        if ENGINE.engine_dirty():                         # the engine's own unsaved flag: a change made without the app counts
            ENGINE._switch_meters()                       # unsaved anyway: the view's held-back RMS switch goes in now
        st = ENGINE.status()
        if st["mode"] is None and not st["binary"] and st["state"] == "stopped":
            st = ENGINE.attach()                          # a window may have been opened since: look again
        try:
            from hypnomix.app import engine_addon
            addon = engine_addon.brief()                  # the add-on: added, or a newer one wanted (the view says so)
        except Exception:
            addon = {}
        return 200, dict(st, daw_mode=STATE["daw"], available=available(), addon=addon)
    if path == "/api/daw/import":
        return 200, import_status(str(q.get("job") or ""))
    return None


def _text(body, key, required=True):
    v = body.get(key)
    if v in (None, "") and not required:
        return None
    if not isinstance(v, str) or not v.strip() or len(v) > 4096 or "\x00" in v:
        raise ValueError(f"this request needs \"{key}\" (text)")
    return v


def _unsaved(body):
    """None when the request may go on, else the answer: stop, restart, open and new would lose work the person has not
    saved (HTTP 409 {"error": "unsaved", "dirty": true}) unless the body says "discard": true, or "save": true (save
    first: a save that fails is the answer, and nothing is lost)."""
    if not ENGINE.unsaved() or body.get("discard") is True:
        return None
    if body.get("save") is True:
        try:
            ENGINE.save()
        except RuntimeError as e:
            return 409, {"error": f"could not save the session first, so nothing was stopped: {e}", "dirty": True}
        return None
    return 409, {"error": "unsaved", "dirty": True}


def carries(track_id):
    """POST /api/daw/carries {track_id}: what the route carries that is not a vocal (automation_rules.non_vocal, a bus
    that feeds it read in turn), so the page's automation lanes can refuse a level or plug-in write on a mixed bus
    before sending it, in the same words: {trackName, others, level, plugin} (the two refusals, "" when allowed). The
    engine connection checks every write again as it is sent; this only reads."""
    from hypnomix.engineer import automation_rules as AR
    url = ENGINE.url()
    if not url:
        return 503, {"error": "the engine is not running"}
    facts = ENGINE._read_tool(url, "automation_list", {"track_id": str(track_id)})
    if facts is None:
        return 404, {"error": f"what route {track_id} carries could not be read from the engine (automation_list)"}
    others = AR.non_vocal(facts, read=lambda tool, args: ENGINE._read_tool(url, tool, args))
    say = lambda k: AR.sentence([AR.mixed_bus(facts, others, k)]) if others else ""
    return 200, {"trackName": facts.get("trackName"), "others": others, "level": say("gain"), "plugin": say("plugin")}


def handle_post(path, body):
    """The POST routes (the server has checked the page's token); each field is checked before the engine is touched."""
    if path == "/api/daw/start":
        return 200, ENGINE.start(session=_text(body, "session", required=False))
    if path == "/api/daw/save":
        st = ENGINE.save()
        return 200, dict(ok=True, dirty=st["dirty"])
    if path == "/api/daw/stop":
        return _unsaved(body) or (200, ENGINE.stop())
    if path == "/api/daw/restart":
        return _unsaved(body) or (200, ENGINE.restart())
    if path == "/api/daw/open":
        target = _text(body, "path")
        snapshot(target)                              # a path that is not a session is refused before anything is asked or saved
        return _unsaved(body) or (200, ENGINE.open(target))
    if path == "/api/daw/new":
        folder, name = _text(body, "folder"), _text(body, "name")
        ENGINE.check_new(folder, name)                # a name that cannot be used is refused before anything is asked or saved
        return _unsaved(body) or (200, ENGINE.new_session(folder, name))
    if path == "/api/daw/import":                     # another DAW's project -> a new session (a job; the page polls)
        return 200, import_start(_text(body, "path"), _text(body, "out", required=False),
                                 allow_outside=body.get("allow_outside") is True)
    if path == "/api/daw/carries":                    # what a route carries that is not a vocal: the page's lanes refuse early
        return carries(_text(body, "track_id"))
    if path == "/api/daw/meta":                       # time signature + track colours from the saved session file
        from hypnomix.app import daw_meta
        s = ENGINE.session or (str(Path(ENGINE.new[0]) / ENGINE.new[1]) if ENGINE.new else None)
        if not s:
            return 404, {"error": "no session file known (attached to a window, or no session open)"}
        try:
            return 200, daw_meta.read(s)
        except (ValueError, OSError) as e:
            return 404, {"error": str(e)}
        except Exception as e:                        # a damaged file: say so, never break the page
            return 500, {"error": f"could not read the session file: {e}"}
    return None


# ---------------------------------------------------------------- importing another DAW's project
# POST /api/daw/import {path, out?, allow_outside?} reads a .als, .logicx, .ptx, .dawproject, .rpp or .aaf project and writes a NEW
# session folder (hypnomix.project.import_project); the project is only read. It runs as a job (a big project takes
# minutes): the answer is {job}, and GET /api/daw/import?job=ID answers {state: running | done | failed, session,
# report, summary, error}. The page then opens the new session with the usual POST /api/daw/open (which asks about
# unsaved work first). One import runs at a time; one still running after IMPORT_STUCK seconds no longer blocks the
# next (it is marked failed: its thread cannot be stopped, so the app should be restarted when convenient).
IMPORT_JOBS = {}
IMPORT_LOCK = threading.Lock()
IMPORT_KEEP = 20
IMPORT_STUCK = 3600


def import_out(project):
    """Where a new session goes when the person names no folder (import_project.default_out: beside the project, or
    beside its folder for a project that owns its folder, so it is never inside what the import guards)."""
    from hypnomix.project import import_project
    return import_project.default_out(project)


def import_start(project, out=None, allow_outside=False):
    from hypnomix.project import import_project
    p = Path(project).expanduser()
    if not p.exists():
        raise ValueError(f"{project}: no such project")
    if import_project.kind_of(p) is None:
        raise ValueError(f"{p.name}: not a project HypnoMix can import (.als, .logicx, .ptx, .dawproject, .rpp or "
                         f".aaf)")
    target = Path(out).expanduser() if out else import_out(p)
    with IMPORT_LOCK:
        for j in IMPORT_JOBS.values():
            if j["state"] == "running" and time.time() - j["started"] > IMPORT_STUCK:
                j.update(state="failed", error=f"still running after {IMPORT_STUCK // 60} minutes: given up (restart "
                                               f"the app to stop it for good)")
        if any(j["state"] == "running" for j in IMPORT_JOBS.values()):
            raise ValueError("an import is already running: wait for it to finish")
        job = secrets.token_hex(6)
        IMPORT_JOBS[job] = dict(state="running", project=str(p), out=str(target), started=time.time())
        for old in sorted(IMPORT_JOBS, key=lambda k: IMPORT_JOBS[k]["started"])[:-IMPORT_KEEP]:
            IMPORT_JOBS.pop(old, None)

    def run():
        try:
            f, rep, summary = import_project.convert(p, target, log=lambda *a: None, allow_outside=allow_outside)
            IMPORT_JOBS[job].update(state="done", session=str(f), report=str(rep), summary=summary, error=None)
        except SystemExit as e:
            if IMPORT_JOBS[job]["state"] == "running":
                IMPORT_JOBS[job].update(state="failed", error=str(e))
        except Exception as e:                             # never leave the job "running" for ever
            if IMPORT_JOBS[job]["state"] == "running":
                IMPORT_JOBS[job].update(state="failed", error=f"{type(e).__name__}: {e}")
    threading.Thread(target=run, name="hypnomix-import", daemon=True).start()
    return dict(job=job, state="running", out=str(target))


def import_status(job):
    j = IMPORT_JOBS.get(job or "")
    if j is None:
        return dict(state="unknown", error="no such import")
    out = {k: j.get(k) for k in ("state", "out", "session", "summary", "error")}
    if j.get("report") and j["state"] == "done":
        try:
            out["report"] = Path(j["report"]).read_text(encoding="utf-8")[:20000]
        except OSError:
            out["report"] = ""
    return out


# ---------------------------------------------------------------- files dropped on the DAW view
# A browser page cannot give the path of a file dropped on it, so the DAW view sends the file here (POST
# /api/daw/upload?name=..., the raw bytes, with the page's token); it is saved in a temp folder and the page then
# asks the engine to import that path (session_import_audio), which copies it into the session's own folder.
UPLOAD_TYPES = {".wav", ".wave", ".bwf", ".aif", ".aiff", ".aifc", ".flac", ".mp3", ".ogg", ".oga", ".caf", ".w64", ".rf64"}
UPLOAD_MAX = 4 << 30              # 4 GB: a long multitrack stem is a few hundred MB
UPLOAD_KEEP = 24 * 3600           # uploads are only needed until the engine has copied them; older ones are removed


UPLOAD_SUB = re.compile(r"[0-9a-f]{12}")           # the folders save_upload makes (secrets.token_hex(6)): the only ones it ever removes
UPLOAD_SPARE = 512 << 20          # free space kept beyond the file itself


def upload_dir():
    """Where dropped files wait for the engine: the app's work folder (HYPNOMIX_APP_HOME) / daw-uploads, or
    HYPNOMIX_DAW_UPLOADS."""
    env = os.environ.get("HYPNOMIX_DAW_UPLOADS")
    if env:
        return Path(env).expanduser()
    from hypnomix.app import server
    return server.work() / "daw-uploads"


def tidy_uploads(root=None):
    """Remove the upload folders this app made that are older than UPLOAD_KEEP. Nothing else in the folder is touched,
    whatever HYPNOMIX_DAW_UPLOADS points at."""
    root = root or upload_dir()
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for old in entries:
        try:
            if (UPLOAD_SUB.fullmatch(old.name) and old.is_dir() and not old.is_symlink()
                    and time.time() - old.stat().st_mtime > UPLOAD_KEEP):
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass


def check_upload(name, length):
    """The name an upload is saved as, or ValueError (checked before a byte of it is read)."""
    name = Path(str(name or "").replace("\\", "/")).name.strip()
    if not name or name.startswith(".") or len(name) > 255 or "\x00" in name or Path(name).suffix.lower() not in UPLOAD_TYPES:
        raise ValueError("drop an audio file (wav, aiff, flac, mp3, ogg, caf, w64)")
    if length <= 0 or length > UPLOAD_MAX:
        raise ValueError("the file is empty or larger than 4 GB" if length else "the file is empty")
    return name


def save_upload(rfile, length, name):
    """Save one dropped audio file (length bytes from rfile) -> {path, name, bytes}. ValueError when refused."""
    name = check_upload(name, length)
    root = upload_dir()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    tidy_uploads(root)                             # what the engine copied long ago
    if shutil.disk_usage(root).free < length + UPLOAD_SPARE:
        raise ValueError("there is not enough free space on this computer for that file")
    sub = root / secrets.token_hex(6)              # its own folder, so the file keeps its name (the track is named after it)
    sub.mkdir(mode=0o700)
    f, left = sub / name, length
    try:
        with open(f, "wb") as out:
            while left > 0:
                chunk = rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                out.write(chunk)
                left -= len(chunk)
        if left:
            raise ValueError("the upload was cut short")
    except BaseException:                          # cut short, stalled, disk full: no half file is left behind
        shutil.rmtree(sub, ignore_errors=True)
        raise
    return {"path": str(f), "name": name, "bytes": length}


class _Repeated(ValueError):
    pass


def _no_repeats(pairs):
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise _Repeated(k)
        seen[k] = v
    return seen


def _no_constant(name):
    raise ValueError(f"{name} is not JSON")


def _finite(text):
    """A number too big for a double (1e999) is read as infinity, and written out again it would not be JSON."""
    value = float(text)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"{text} is not a finite number")
    return value


def parse_rpc(raw):
    """A body for POST /mcp -> (the message, "") or (None, why it is refused). Strict, so what the app checks is what the
    engine gets: UTF-8 only (no BOM, no UTF-16), no NaN / Infinity, and no name given twice in one object at any depth
    (Python keeps the last of a repeated name and the engine's parser the first: {"name": "a", "name": "b"} would be
    checked as one tool and run as another), and no number too big to write back as JSON (1e999). The proxy sends
    json.dumps of this message, never the bytes it came as."""
    try:
        text = (raw or b"").decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
    except UnicodeDecodeError:
        return None, "bad request: the body is not UTF-8 JSON"
    if text.startswith("\ufeff"):
        return None, "bad request: the body is not JSON"
    try:
        msg = json.loads(text, object_pairs_hook=_no_repeats, parse_constant=_no_constant, parse_float=_finite)
    except _Repeated:
        return None, "bad request: repeated name in the message"
    except ValueError:
        return None, "bad request: the body is not JSON"
    why = check_rpc(msg)
    return (None, why) if why else (msg, "")


def check_rpc(raw):
    """Why a body for POST /mcp is refused, or "" when it is a JSON-RPC message (or a batch) the engine may get:
    each one an object with "jsonrpc": "2.0" and a method name; tools/call with a tool name and object arguments.
    raw is the body's bytes or an already parsed message (parse_rpc)."""
    if raw is not None and not isinstance(raw, (bytes, bytearray, str)):
        msg = raw
    else:
        try:
            msg = json.loads(raw or b"")
        except ValueError:
            return "bad request: the body is not JSON"
    msgs = msg if isinstance(msg, list) else [msg]
    if not msgs or len(msgs) > 50:
        return "bad request: send one JSON-RPC message (or a batch of at most 50)"
    for m in msgs:
        if not isinstance(m, dict) or m.get("jsonrpc") != "2.0" or not isinstance(m.get("method"), str) \
                or not re.fullmatch(r"[\w./-]{1,64}", m["method"]):
            return "bad request: each message needs \"jsonrpc\": \"2.0\" and a method name"
        if "params" in m and not isinstance(m["params"], (dict, list)):
            return "bad request: params must be an object"
        if m["method"] == "tools/call":
            pr = m.get("params") if isinstance(m.get("params"), dict) else {}
            if not isinstance(pr.get("name"), str) or not re.fullmatch(r"[\w.-]{1,64}", pr["name"]):
                return "bad request: tools/call needs the tool's name"
            if not isinstance(pr.get("arguments", {}), dict):
                return "bad request: a tool's arguments are an object"
            if pr["name"].replace("/", "_") in APP_ONLY_TOOLS:
                return f"bad request: {pr['name']} is the app's own (the meter stream is at /api/daw/meters)"
    return ""


def rpc_timeout(raw):
    """Import blocks until every file is copied: give it minutes, not the usual seconds. A clip put into a cue slot
    (cue_set_clip) is copied and loaded before the engine answers: up to a minute and a half."""
    raw = raw or b""
    if isinstance(raw, (dict, list)):
        raw = json.dumps(raw).encode()
    if b"session_import_audio" in raw:
        return 600.0
    if b"cue_set_clip" in raw:
        return max(RPC_TIMEOUT, 90.0)
    return RPC_TIMEOUT


def start_for_app(session=None):
    """`hypnomix app --daw`: start (or attach to) the engine in the background, so the page opens at once."""
    STATE["daw"] = True
    def run():
        try:
            tidy_uploads()                             # what an earlier run left
        except Exception:
            pass
        try:
            ENGINE.start(session=session or last_session())   # no --session: the one open when the app last quit
        except ValueError as e:                        # a --session that is not a session: say so in the DAW view
            with ENGINE.lock:
                ENGINE.state, ENGINE.error = "failed", str(e)
    threading.Thread(target=run, daemon=True).start()
