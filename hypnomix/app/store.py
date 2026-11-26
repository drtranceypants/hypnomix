"""The app's Store tab: search, install, update and uninstall free plug-ins, instruments, drum kits and sample packs.

The catalogue and the installer live in hypnomix/store/ (`hypnomix store` does the same from a terminal). This file
runs one install or uninstall at a time in the background, reports its progress to the page, and after a plug-in
is installed asks the Hypnomix engine (if one is connected over MCP) to rescan its plug-ins, when the engine has a
tool for that. Ardour 9.9's MCP surface has none yet, so the page says to rescan in the DAW (or restart it).

macOS only for now: on another system the page says so (state() carries supported and platform_note) and installs
nothing. A download with no sha256 to check it against is not installed until the page sends "unverified": true,
which it does only after the person confirms, in plain words, that it is not verified. A running job can be cancelled.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from hypnomix.store import catalogue as C, install as I

JOBS = {}                       # item id -> dict(action, phase, got, total, error, result, started, ended)
_jl = threading.Lock()
RESCAN_TOOL = re.compile(r"(plugin.*(rescan|refresh|scan))|((rescan|refresh|scan).*plugin)", re.I)
MCP_URL = "http://127.0.0.1:4820/mcp"


# ---------------------------------------------------------------- the engine (MCP)
def _mcp_url():
    """The engine the app is using (DAW mode), else HYPNOMIX_ENGINE_URL, else a Hypnomix window on 4820."""
    try:
        from hypnomix.app import daw as D                     # present once the DAW view is part of the app
        u = D.ENGINE.url() if D.ENGINE.connected() else None
        if u:
            return u
    except Exception:
        pass
    return os.environ.get("HYPNOMIX_ENGINE_URL") or MCP_URL


def _rpc(url, method, params=None, timeout=3.0):
    body = {"jsonrpc": "2.0", "id": int(time.time() * 1000) % 1000000, "method": method, "params": params or {}}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    from hypnomix.core import loopback                        # the engine is on this computer: never through a proxy
    with loopback.urlopen(req, timeout=timeout) as r:
        msg = json.loads(r.read() or b"{}")
    if msg.get("error"):
        raise RuntimeError(str(msg["error"].get("message") or msg["error"]))
    return msg.get("result") or {}


def rescan():
    """Ask a connected engine to rescan plug-ins -> dict(connected, tool, ok, message)."""
    url = _mcp_url()
    try:
        _rpc(url, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                 "clientInfo": {"name": "hypnomix-store", "version": "1"}}, timeout=1.5)
        tools = [t.get("name", "") for t in (_rpc(url, "tools/list").get("tools") or [])]
    except Exception:
        return dict(connected=False, tool=None, ok=False,
                    message="No Hypnomix engine is connected, so nothing was rescanned: your DAW finds new plug-ins "
                            "when it next starts or rescans.")
    tool = next((t for t in tools if RESCAN_TOOL.search(t)), None)
    if not tool:
        return dict(connected=True, tool=None, ok=False,
                    message="The Hypnomix engine is connected but has no plug-in rescan tool over MCP yet: rescan "
                            "plug-ins in the DAW (its Plugin Manager), or restart it, to see the new ones.")
    try:
        _rpc(url, "tools/call", {"name": tool, "arguments": {}}, timeout=120)
        return dict(connected=True, tool=tool, ok=True, message=f"The Hypnomix engine rescanned its plug-ins ({tool}).")
    except Exception as e:
        return dict(connected=True, tool=tool, ok=False, message=f"The engine's {tool} failed: {e}")


# ---------------------------------------------------------------- jobs
def _job(item_id, action, fn):
    with _jl:
        j = JOBS.get(item_id)
        if j and not j.get("ended"):
            raise I.StoreError(f"{item_id} is already being {j['action']}ed")
        if any(not x.get("ended") for x in JOBS.values()):
            raise I.StoreError("one thing at a time: wait for the install that is running")
        JOBS[item_id] = j = dict(action=action, phase="starting", got=0, total=0, error=None, result=None,
                                 confirm=None, unverified=None, unverified_ok=False, cancel=False,
                                 started=time.time(), ended=None)

    def prog(phase, got=0, total=0):
        j.update(phase=phase, got=got, total=total or j["total"])

    def run():
        try:
            j["result"] = fn(prog, lambda: bool(j["cancel"]))
        except I.NeedsConfirm as e:
            j["confirm"] = e.paths
            j["error"] = str(e)
        except I.NotVerified as e:
            j["unverified"] = str(e)                         # the page asks, in these words, before trying again
            j["error"] = str(e)
        except Exception as e:                                # everything ends up on the page
            j["error"] = str(e)
        finally:
            j["ended"] = time.time()
    threading.Thread(target=run, daemon=True).start()
    return j


def start_install(item_id, replace=False, unverified=False):
    it = C.get(item_id)
    I.check_platform()

    def go(prog, cancel):
        e = I.install(it, confirm_overwrite=replace, progress=prog, confirm_unverified=unverified, cancel=cancel)
        out = dict(entry=e)
        if e["method"] == "bundles":
            prog("rescan")
            out["rescan"] = rescan()
        return out
    j = _job(item_id, "install", go)
    j["unverified_ok"] = bool(unverified)
    return j


def start_uninstall(item_id):
    return _job(item_id, "uninstall", lambda prog, cancel: dict(removed=I.uninstall(item_id)))


def cancel(item_id):
    """Ask a running job to stop (checked while downloading and unpacking). -> True when there was one."""
    with _jl:
        j = JOBS.get(item_id)
        if j and not j.get("ended"):
            j["cancel"] = True
            return True
    return False


# ---------------------------------------------------------------- state for the page
def state():
    data = C.load()
    st = I.status(data["items"])
    items = [dict(it, verification=C.verification(it)) for it in data["items"]]    # pinned / github / none
    return dict(version=data["version"], left_out=data.get("left_out", []), items=items, status=st,
                supported=I.supported(), platform_note="" if I.supported() else I.PLATFORM_NOTE,
                kinds=list(C.KINDS), formats=sorted({f for it in data["items"] for f in it["formats"]}),
                licences=sorted({it["licence"] for it in data["items"]}), jobs=JOBS,
                targets=dict(plugins=str(I.plugins_dir()), library=str(I.library_dir()),
                             test_root=str(I.root()) if I.root() else ""))


def updates():
    """Installed items with a newer release (asks GitHub once per item, cached 10 minutes)."""
    out = {}
    for iid, s in I.status().items():
        if s.get("installed"):
            try:
                out[iid] = I.check_update(C.get(iid))
            except Exception as e:
                out[iid] = dict(error=str(e))
    return out


def _reveal(p):
    p = Path(p)
    if not I._inside_targets(p) or not p.exists():
        return False
    if sys.platform == "darwin":
        return subprocess.run(["open", "-R", str(p)]).returncode == 0
    return False


def handle_get(path, q):
    if path == "/store.js":
        return 200, Path(__file__).with_name("store.js").read_bytes(), "text/javascript; charset=utf-8"
    if path == "/api/store/state":
        try:
            return 200, state()
        except C.CatalogueError as e:
            return 500, dict(error=str(e))
    if path == "/api/store/jobs":
        return 200, dict(jobs=JOBS, status=I.status())
    if path == "/api/store/updates":
        return 200, updates()
    if path == "/api/store/resolve":
        try:
            return 200, I.resolve(C.get(q.get("id", "")))
        except (KeyError, I.StoreError) as e:
            return 400, dict(error=str(e).strip('"'))
    return None


def handle_post(path, body):
    try:
        if path == "/api/store/install":
            return 200, start_install(str(body.get("id", "")), bool(body.get("replace")), bool(body.get("unverified")))
        if path == "/api/store/uninstall":
            return 200, start_uninstall(str(body.get("id", "")))
        if path == "/api/store/open-installer":
            e = I.manifest()["items"].get(str(body.get("id", "")))
            if not e or not e.get("installer"):
                return 404, dict(error="no installer kept for that item")
            inst = Path(e["installer"])
            if not I._inside_targets(inst) or not inst.exists():          # the same check as reveal and uninstall
                return 404, dict(error="the kept installer is gone (disk care clears old ones): install the item again to get it")
            return 200, dict(opened=I._open_pkg(inst))
        if path == "/api/store/reveal":
            return 200, dict(ok=_reveal(str(body.get("path", ""))))
        if path == "/api/store/rescan":
            return 200, rescan()
        if path == "/api/store/cancel":
            return 200, dict(cancelled=cancel(str(body.get("id", ""))))
        if path == "/api/store/forget":                       # drop a finished job's message
            JOBS.pop(str(body.get("id", "")), None)
            return 200, dict(ok=True)
    except (KeyError, I.StoreError, C.CatalogueError) as e:
        return 400, dict(error=str(e).strip('"'))
    return None
