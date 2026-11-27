"""Fill the cue slots (Session view clips) of the session open in the HypnoMix engine, over MCP.

Used by `hypnomix loops ... --cues` and `hypnomix variations SESSION.ardour --cues`. Every track of the engine has
16 cue slots (the DAW's Cue page); while any slot of a track holds a clip (launched or not), that track's
Arrangement regions do not play (the engine's default; clearing the track's last clip brings them back), so the clips go on a
track of their own next to the part ("Drums loops": a new one, or the empty slots of one already there), never onto
the part itself. Each clip goes in from its WAV file
(`cue_set_clip file`: the engine copies it into the session like an import), named, looping, launched on the bar,
and with its length in beats so it plays at the session's tempo (`stretchable`). Nothing in the Arrangement changes;
the clips stay until you clear them (save the session to keep them).

Which engine: `--engine URL`, else HYPNOMIX_ENGINE_URL, else a HypnoMix DAW window on http://127.0.0.1:4820/mcp. The
session given must be the one the engine has open, by its full path (`ardour_groups.open_problem`: a session of the
same name in another folder, or an engine that names no saved file, is refused), so the clips land in the right song.
Afterwards HypnoMix sees the change (the session shows as unsaved); save in HypnoMix DAW to keep it.
"""
import json, os, urllib.error, urllib.request
from pathlib import Path

from hypnomix.core import loopback

from hypnomix.engineer.chain_ardour import MCPError

URL = "http://127.0.0.1:4820/mcp"
SLOTS = 16


class MCP:
    """JSON-RPC tools/call over HTTP, to this computer only (core/loopback.py: no proxy, no redirect, a URL that is not
    on 127.0.0.1, localhost or [::1] is refused). The tool is the first positional argument (`_tool`), so a tool
    argument may be called `name` (tracks_add, cue_set_clip)."""

    def __init__(self, url, timeout=120):
        self.url, self.timeout, self.n = url, timeout, 0

    def call(self, _tool, **args):
        self.n += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self.n, "method": "tools/call",
                           "params": {"name": _tool, "arguments": args}}).encode()
        req = urllib.request.Request(self.url, body, {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        try:
            with loopback.urlopen(req, timeout=self.timeout) as r:
                raw = r.read().decode()
        except ValueError as e:                           # not this computer: refused before anything is sent
            raise MCPError(f"{_tool}: {e}") from e
        except (urllib.error.URLError, OSError) as e:
            raise MCPError(f"{_tool}: no answer from {self.url} ({e})") from e
        if raw.lstrip().startswith(("event:", "data:")):
            raw = "".join(ln[5:] for ln in raw.splitlines() if ln.startswith("data:"))
        try:
            d = json.loads(raw)
        except ValueError:
            d = None
        if not isinstance(d, dict) or not isinstance(d.get("result", {}), dict):
            raise MCPError(f"{_tool}: the engine at {self.url} answered with something that is not an MCP reply")
        if "error" in d:
            raise MCPError(f"{_tool}: {d['error'].get('message')}")
        res = d.get("result", {})
        if res.get("isError"):
            raise MCPError(f"{_tool}: {(res.get('content') or [{}])[0].get('text')}")
        if "structuredContent" in res:
            return res["structuredContent"]
        try:
            return json.loads((res.get("content") or [{}])[0].get("text", ""))
        except ValueError:
            return {}


def engine_url(arg=None):
    return arg or os.environ.get("HYPNOMIX_ENGINE_URL") or URL


def connect(url=None, session=None):
    """An MCP client on the engine; with `session`, checks that it is the session the engine has open."""
    m = MCP(engine_url(url), timeout=120)
    try:
        snaps = m.call("session_list_snapshots")
    except MCPError as e:
        raise RuntimeError(f"no HypnoMix engine answers at {m.url}: start it (hypnomix app --daw) or pass --engine URL; "
                           f"the engine's address is in the DAW view's engine panel ({e})")
    if session is not None:
        from hypnomix.project.ardour_groups import open_problem
        why = open_problem(snaps, session)
        if why:
            raise RuntimeError(why)
    if "cue_set_clip" not in tool_names(m):
        raise RuntimeError("this engine has no cue tools (cue_set_clip): it is older than the Session view on the engine")
    return m


def tool_names(m):
    try:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode()
        req = urllib.request.Request(m.url, body, {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        with loopback.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())
        return {t["name"] for t in d.get("result", {}).get("tools", [])}
    except Exception:
        return set()


def tracks(m):
    r = m.call("tracks_list", includeHidden=False)
    return r.get("tracks", r) if isinstance(r, dict) else r


def track_id(m, name):
    low = name.lower()
    ts = tracks(m)
    t = next((t for t in ts if t["name"].lower() == low), None) or next((t for t in ts if t["name"].lower().startswith(low)), None)
    return (t["id"], t["name"]) if t else (None, None)


def clip_track(m, name, after=None):
    """The track the clips go on: an existing track of that name (its empty slots are used), else a new stereo
    audio track right after `after` (a track id)."""
    tid, _ = track_id(m, name)
    if tid and next((t for t in tracks(m) if t["id"] == tid and t["name"] == name), None):
        return tid, False
    args = dict(type="audio", name=name, count=1, inputChannels=2, outputChannels=2)
    if after:
        args.update(insert="after", relativeToId=after)
    m.call("tracks_add", **args)
    tid = next((t["id"] for t in tracks(m) if t["name"] == name), None)
    if not tid:
        raise RuntimeError(f"the engine did not add the track {name!r}")
    return tid, True


def free_slots(m, tid):
    c = m.call("cue_list", track_id=tid, all_slots=True)
    return [s["slot"] for s in c["tracks"][0]["slots"] if s["empty"]]


def fill(m, tid, clips):
    """clips: [dict(file, name, beats)] -> [(clip, slot or None, error)]. Empty slots in order; settings: loop
    (follow again), launch on the bar, stretchable at `beats`."""
    free = free_slots(m, tid)
    out = []
    for c in clips:
        if not free:
            out.append((c, None, "no empty slot left on this track"))
            continue
        s = free.pop(0)
        try:
            args = dict(track_id=tid, slot=s, file=str(Path(c["file"]).resolve()), name=c["name"][:60],
                        quantize="bar", follow_action="again", launch_style="oneshot")
            if c.get("beats"):
                args.update(beats=float(c["beats"]), stretchable=True)
            m.call("cue_set_clip", **args)
            out.append((c, s, None))
        except MCPError as e:
            out.append((c, None, str(e)))
    return out


def report(placed, track_name):
    ok = [(c, s) for c, s, e in placed if e is None]
    lines = [f"{len(ok)} clip(s) in the cue slots of {track_name!r} (Session view):"]
    lines += [f"  slot {s + 1}: {c['name']}" for c, s in ok]
    lines += [f"  not placed: {c['name']} ({e})" for c, s, e in placed if e is not None]
    from hypnomix.project.ardour_groups import APP_NOTICES
    if ok:
        lines.append(f"Launch them in the DAW view's Session view (they switch on the bar). {APP_NOTICES}.")
    return "\n".join(lines)


def not_placed(placed):
    """How many clips did not go in (the command then exits 1)."""
    return sum(1 for _, _, e in placed if e is not None)
