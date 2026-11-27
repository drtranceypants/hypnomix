"""Group tracks and sidechains in a HypnoMix Studio session, written straight into the open HypnoMix engine over MCP.

A Live group track is, in HypnoMix Studio, a route group plus its subgroup bus, made together by the
engine's `group_create` (the members' outputs go to the bus, the bus fader is the group fader). This module:

  plan_old_takes(p)          `tidy` on a HypnoMix Studio session: switched-off (inactive) tracks not in a group yet ->
                             one "Old takes" group, folded (what `tidy` could not do before: "a group needs Live")
  plan_families(p, labels)   `order` on a HypnoMix Studio session: the "similar instruments always grouped" rule. Two or more
                             ungrouped tracks of one family (drums, bass, keys/guitar/synth, vocals, strings/brass)
                             -> a group named after the family; one more track of a family that already has a group
                             -> added to it. Families come from names.json labels when given, else from track names
  findings(plans, tool)      review items (`group-N`), each one an option: nothing is written unless approved
  apply(engine, p, plans, ids)  the approved ones over MCP (group_create / group_add / group_set), by route id,
                             each read back with group_list. The engine must have THIS session open
  require_open(engine, path) the check every command-line engine writer makes first (tidy, order, duck, and loops /
                             variations --cues through open_problem): the engine's current snapshot file is this very
                             file, by its full path. No answer, no file or another file is a refusal (fails closed)
  Engine(url)                a small MCP client (JSON-RPC tools/call over HTTP, localhost)

None of it is in the engine's undo history: group_delete (or group_remove) puts it back, and the reply says so. The
session file itself is not written here; the engine saves it when the person saves (or `session_save`).
"""
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from hypnomix.core import loopback

DEFAULT_URL = "http://127.0.0.1:4820/mcp"
# Said in the help of every command that writes into the open engine, and after it writes.
APP_NOTICES = ("HypnoMix sees the change: the session shows as unsaved, and Stop, Open, New and quit ask Save first. "
               "Save in HypnoMix Studio to keep it")
WHERE_URL = "the engine's address is in the DAW view's engine panel; pass it as --engine URL"
FAMILIES = ["Drums", "Bass", "Instruments", "Vocals", "Strings & Brass"]   # order.py's categories 0-4
OLD_TAKES = "Old takes"


class EngineError(RuntimeError):
    pass


def engine_url(url=None):
    return url or os.environ.get("HYPNOMIX_ENGINE_URL") or DEFAULT_URL


class Engine:
    """tools/call on the HypnoMix engine's MCP surface. Only loopback URLs (the surface has no auth), through
    core/loopback.py: no proxy, no redirect followed."""

    def __init__(self, url=None, timeout=60):
        self.url = engine_url(url)
        if not re.match(r"^http://(127\.0\.0\.1|localhost|\[::1\]):\d+/mcp$", self.url):
            raise EngineError(f"not a local engine URL: {self.url} (expected http://127.0.0.1:PORT/mcp)")
        self.timeout = timeout
        self.n = 0

    def call(self, name, args=None):
        self.n += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self.n, "method": "tools/call",
                           "params": {"name": name, "arguments": args or {}}}).encode()
        req = urllib.request.Request(self.url, body, {"Content-Type": "application/json"})
        try:
            with loopback.urlopen(req, timeout=self.timeout) as r:      # this computer only: no proxy, no redirect
                res = json.loads(r.read())
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise EngineError(f"the engine at {self.url} did not answer ({e}): is it running? ({WHERE_URL})")
        if not isinstance(res, dict):
            raise EngineError(f"the engine at {self.url} answered with something that is not an MCP reply")
        if "error" in res:
            raise EngineError(f"{name}: {res['error'].get('message', res['error'])}")
        out = res.get("result", {})
        if not isinstance(out, dict):
            raise EngineError(f"{name}: the engine at {self.url} answered with something that is not an MCP reply")
        if out.get("isError"):
            raise EngineError(f"{name}: {(out.get('content') or [{}])[0].get('text', 'error')}")
        return out.get("structuredContent", out)

    def has(self, *tools):
        """True when the engine offers these tools (an older engine has no group_* tools)."""
        self.n += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self.n, "method": "tools/list"}).encode()
        req = urllib.request.Request(self.url, body, {"Content-Type": "application/json"})
        try:
            with loopback.urlopen(req, timeout=self.timeout) as r:      # this computer only: no proxy, no redirect
                names = {t.get("name") for t in json.loads(r.read()).get("result", {}).get("tools", [])}
        except (urllib.error.URLError, OSError, ValueError, AttributeError, TypeError):
            return False
        return all(t in names for t in tools)


def open_problem(snaps, session):
    """None when the engine's current snapshot (a session_list_snapshots answer) is this session file, by its full
    path; else one sentence why not. A missing answer, snapshot or file is a refusal too: the route ids, plug-in
    indexes and slots in a scan only mean something in the session it read."""
    want = Path(session).resolve()
    rows = snaps.get("snapshots") if isinstance(snaps, dict) else None
    cur = next((s for s in rows if isinstance(s, dict) and s.get("current")), None) if isinstance(rows, list) else None
    if not cur or not cur.get("file"):
        return (f"could not tell which session the engine has open (it names no saved session file), so nothing was "
                f"written: open {want.name} in HypnoMix Studio (and save it once) first")
    have = Path(str(cur["file"])).resolve()
    if have == want:
        return None
    same = have.name == want.name
    return (f"the engine has {have if same else have.name} open, not {want if same else want.name}, so nothing was "
            "written: open that session in HypnoMix Studio first")


def require_open(engine, session):
    """Stops (one sentence) unless the engine has this very session file open. Returns True when the engine says
    the open session has unsaved changes (the saved file is then behind the engine)."""
    try:
        snaps = engine.call("session_list_snapshots")
    except EngineError as e:
        raise SystemExit(f"could not ask the engine which session it has open, so nothing was written: {e}")
    why = open_problem(snaps, session)
    if why:
        raise SystemExit(why)
    return bool(snaps.get("dirty"))


def wanted(fs, ids, example):
    """The --ids asked for, checked against the options listed: an id that is not one of them (a typo, or a scan
    that no longer proposes it) stops with one sentence before the engine is asked anything, instead of writing
    nothing and exiting 0."""
    want = [x.strip() for x in (ids or "").split(",") if x.strip()]
    if not want:
        raise SystemExit(f"say which: --ids {example},… (nothing is written by default)")
    have = [f["id"] for f in fs]
    unknown = [x for x in want if x not in have]
    if unknown:
        raise SystemExit(f"{', '.join(unknown)} is not among the options listed "
                         f"({', '.join(have) if have else 'there are none'}), so nothing was written")
    return want


def daw_flags(a, example):
    """The flags a HypnoMix Studio session takes on tidy / order / duck: --apply (a new Live set) is refused, and --ids
    alone (without --engine) would silently write nothing, so it is refused too."""
    if getattr(a, "apply", None):
        raise SystemExit("a HypnoMix Studio session is changed in the open HypnoMix engine, not written to a new file: "
                         f"use --engine --ids {example},…")
    if getattr(a, "ids", None) and getattr(a, "engine", None) is None:
        raise SystemExit(f"--ids needs --engine: the options are written into the open HypnoMix engine "
                         f"(--engine [URL] --ids {example},…); without it nothing is written")


def connected(url=None):
    try:
        return Engine(url, timeout=2).has("group_create", "group_list")
    except EngineError:
        return False


# ---------------------------------------------------------------- planning (pure: the model only)
def _outs(t):
    """Audio output channels of a route (from its saved output IO)."""
    rt = t.native
    if rt is None:
        return None
    for io in rt.findall("IO"):
        if io.get("direction") == "Output":
            return sum(1 for p in io.findall("Port") if p.get("type", "audio") == "audio")
    return None


def _groupable(t, buses):
    return t.kind in ("audio", "midi", "folder") and not t.group and t.parent is None and id(t) not in buses


def _buses(p):
    return {id(g.bus) for g in p.groups if g.bus is not None}


def _same_outs(tracks):
    n = {_outs(t) for t in tracks}
    return len(n) <= 1


def plan_old_takes(p):
    """Switched-off tracks (inactive routes) not in a group yet -> [plan]. One plan, or none."""
    buses = _buses(p)
    off = [t for t in p.tracks if t.kind in ("audio", "midi") and not t.active and _groupable(t, buses)]
    if not off:
        return []
    existing = next((g for g in p.groups if g.name.lower() == OLD_TAKES.lower()), None)
    if existing is not None:
        return [dict(op="add", group=existing.name, group_id=existing.id, tracks=[t.name for t in off],
                     why="switched off")]
    return [dict(op="create", group=OLD_TAKES, tracks=[t.name for t in off], fold=True, why="switched off",
                 mixed=not _same_outs(off))]


# Instrument words for a track's own name, singular (a trailing "s" is tried off too). The instrument is the
# rightmost word that names one ("Bass Drum" is a drum, "Synth Bass" a bass); two-word names are tried first.
FAMILY_PHRASES = {
    ("bass", "drum"): 0, ("kick", "drum"): 0, ("snare", "drum"): 0, ("hi", "hat"): 0, ("drum", "kit"): 0,
    ("floor", "tom"): 0, ("kick", "sub"): 0, ("bass", "guitar"): 1, ("bass", "synth"): 1, ("synth", "bass"): 1, ("double", "bass"): 1, ("upright", "bass"): 1,
    ("lead", "vocal"): 3, ("backing", "vocal"): 3, ("lead", "vox"): 3,
}
FAMILY_WORDS = {
    **dict.fromkeys(("drum", "kick", "snare", "hat", "hihat", "tom", "percussion", "perc", "overhead", "oh", "cymbal",
                     "ride", "crash", "clap", "shaker", "tambourine", "conga", "bongo", "kit"), 0),
    **dict.fromkeys(("bass", "sub"), 1),
    **dict.fromkeys(("keys", "piano", "guitar", "gtr", "synth", "pad", "organ", "pluck", "rhodes", "wurli",
                     "keyboard", "arp"), 2),
    **dict.fromkeys(("vocal", "vox", "voice", "harmony", "harm", "harmonies", "bv", "bvs", "bgv", "choir", "adlib"), 3),
    **dict.fromkeys(("string", "strings", "violin", "viola", "cello", "brass", "trumpet", "trombone", "horn", "sax",
                     "woodwind", "flute", "clarinet"), 4),
}


def _word(w):
    if w in FAMILY_WORDS:
        return FAMILY_WORDS[w]
    if len(w) > 3 and w.endswith("s") and w[:-1] in FAMILY_WORDS:
        return FAMILY_WORDS[w[:-1]]
    return None


def _sing(w):
    return w[:-1] if len(w) > 3 and w.endswith("s") and w not in FAMILY_WORDS else w


def family_of(t, labels=None):
    """0-4 (order.py's categories) or None, from the names.json label, else from the track's own name: the rightmost
    instrument word wins ("Bass Drum" -> drums, "Bass Guitar" and "Synth Bass" -> bass); no instrument word -> None."""
    from hypnomix.session import order as OR
    lab = (labels or {}).get(t.name)
    if lab:
        c = OR.category(lab.get("label"), float(lab.get("confidence") or 0))
        return c if c < 5 else None
    words = re.sub(r"[^a-z]+", " ", t.name.lower()).split()
    for i in range(len(words) - 1, -1, -1):
        if i > 0:
            c = FAMILY_PHRASES.get((_sing(words[i - 1]), _sing(words[i])))
            if c is not None:
                return c
        c = _word(words[i])
        if c is not None:
            return c
    return None


def plan_families(p, labels=None):
    """Ungrouped tracks of one family (>= 2), or one more of a family that has a group -> [plan]."""
    buses = _buses(p)
    fam = {}
    for t in p.tracks:
        if t.kind not in ("audio", "midi") or not t.active or not _groupable(t, buses):
            continue
        c = family_of(t, labels)
        if c is not None:
            fam.setdefault(c, []).append(t)
    plans = []
    for c, ts in sorted(fam.items()):
        name = FAMILIES[c]
        existing = next((g for g in p.groups if g.name.lower() == name.lower()), None)
        if existing is not None:
            plans.append(dict(op="add", group=existing.name, group_id=existing.id, tracks=[t.name for t in ts],
                              why=f"{name.lower()} like the rest of '{existing.name}'"))
        elif len(ts) >= 2:
            plans.append(dict(op="create", group=name, tracks=[t.name for t in ts], fold=False,
                              why=f"all {name.lower()}", mixed=not _same_outs(ts)))
    return plans


def findings(plans, tool):
    out = []
    for n, pl in enumerate(plans, 1):
        names = ", ".join(pl["tracks"][:12]) + ("…" if len(pl["tracks"]) > 12 else "")
        if pl["op"] == "create":
            problem = (f"{len(pl['tracks'])} track(s), {pl['why']}, sit in no group: {names}" +
                       ("; the DAW cannot route tracks with different channel counts to one bus, so this one is "
                        "by hand" if pl.get("mixed") else ""))
            fix = (("by hand (listed, never written by HypnoMix): " if pl.get("mixed") else "") +
               f"make the group track '{pl['group']}' in the open HypnoMix Studio (a route group plus its bus, "
                   f"the tracks routed to it, the bus fader as the group fader; nothing shared but the bus" +
                   (", folded" if pl.get("fold") else "") + "). Not in the undo history: Ungroup (group_delete) "
                   "puts it back")
        else:
            problem = f"{len(pl['tracks'])} track(s), {pl['why']}, are outside it: {names}"
            fix = f"add them to the group '{pl['group']}' in the open HypnoMix Studio (routed to its bus)"
        out.append(dict(id=f"group-{n}", tool=tool, kind="group-old" if tool == "tidy" else "group-family",
                        severity="low", track=names, where=f"{len(pl['tracks'])} track(s)", group=pl["group"],
                        problem=problem, fix=fix, applies="manual" if pl.get("mixed") else "engine",
                        plan={k: v for k, v in pl.items() if k != "mixed"}))
    return out


# ---------------------------------------------------------------- writing over MCP
def _route_ids(engine):
    tl = engine.call("tracks_list", {"includeHidden": True})
    out = {}
    for t in tl.get("tracks", []):
        out.setdefault(t.get("name"), str(t.get("id")))
    return out


def apply(engine, findings_, ids):
    """Approved group findings -> MCP calls. Returns (log lines, failures). `ids`: the finding ids to apply. A finding
    marked by hand (applies 'manual': tracks with different channel counts) is never written, only said in the log."""
    want = set(ids)
    log, failed = [], []
    rid = _route_ids(engine) if any(f["id"] in want and f.get("applies") != "manual" for f in findings_) else {}
    for f in findings_:
        if f["id"] not in want:
            continue
        pl = f["plan"]
        if f.get("applies") == "manual":
            log.append(f"- {f['id']}: left for you: '{pl['group']}' mixes tracks with different channel counts, which one "
                       "bus cannot take, so HypnoMix does not write it; group those tracks in HypnoMix Studio yourself")
            continue
        missing = [n for n in pl["tracks"] if n not in rid]
        if missing:
            failed.append(f"{f['id']}: not in the open session: {', '.join(missing)} (is this the session it scanned?)")
            continue
        tids = [rid[n] for n in pl["tracks"]]
        g = None
        try:
            if pl["op"] == "create":
                g = engine.call("group_create", {"name": pl["group"], "track_ids": tids})["group"]
                if pl.get("fold"):
                    g = engine.call("group_set", {"group_id": g["groupId"], "folded": True})["group"]
            else:
                gid = pl.get("group_id") or next((x["groupId"] for x in engine.call("group_list")["groups"]
                                                  if x["name"] == pl["group"]), None)
                if not gid:
                    raise EngineError(f"no group '{pl['group']}' in the open session")
                g = engine.call("group_add", {"group_id": gid, "track_ids": tids})["group"]
            back = next((x for x in engine.call("group_list")["groups"] if x["groupId"] == g["groupId"]), None)
        except (EngineError, KeyError, TypeError) as e:
            why = e if isinstance(e, EngineError) else f"the engine answered without {e}"
            made = f" (the group '{g.get('name', pl['group'])}' was made; check it in the DAW view)" \
                if isinstance(g, dict) else ""
            failed.append(f"{f['id']}: {why}{made}")
            continue
        routed = back is not None and all(m["routedToBus"] for m in back["members"]) and \
            set(tids) <= {m["trackId"] for m in back["members"]}
        if not routed:
            failed.append(f"{f['id']}: the group was made but reads back differently: {json.dumps(back)[:300]}")
            continue
        log.append(f"- {f['id']}: group '{back['name']}' ({len(back['members'])} track(s), bus '{back['busName']}')"
                   f"{', folded' if back['folded'] else ''}. Ungroup puts it back (group_delete {back['groupId']})")
    return log, failed


def labels_from(names_json):
    """names.json (`hypnomix name`) -> {track name: row}."""
    if not names_json:
        return {}
    from hypnomix.session import order as OR
    rows = OR.read_names(names_json)              # a missing or broken file stops with one sentence
    return {r.get("old"): dict(label=r.get("final") or r.get("label"), confidence=r.get("confidence", 1.0))
            for r in rows if isinstance(r, dict) and r.get("old")}


def run_cli(tool, path, a, plans_fn):
    """The HypnoMix Studio branch of `hypnomix tidy` / `hypnomix order`: list the group options, or write the approved ones
    into the open engine (--engine [URL] --ids group-1,...)."""
    from hypnomix.project import ardour as AR
    daw_flags(a, "group-1")
    p = AR.read(path)
    fs = findings(plans_fn(p), tool)
    print(f"{Path(p.path).name}: {len(fs)} group option(s) (HypnoMix Studio session; groups are written into the open "
          "HypnoMix engine, ask first)")
    for f in fs:
        print(f"  {f['id']:<8} {f['fix'].split('. Not in')[0]}\n           ({f['problem']})")
    if getattr(a, "json", None):
        from hypnomix.core import atomic as AT
        AT.write_json(Path(a.json), {"tool": tool, "set": str(p.path), "findings": fs})
    if getattr(a, "engine", None) is None:
        return 0
    want = wanted(fs, a.ids, "group-1")
    log, failed = [], []
    try:
        eng = Engine(a.engine or None)
        if not eng.has("group_create", "group_add", "group_set", "group_list"):
            raise SystemExit(f"the engine at {eng.url} does not answer, or has no group tools (an older HypnoMix "
                             f"engine); {WHERE_URL}")
        if require_open(eng, p.path):
            print("  note: the engine has unsaved changes, so the saved file may be behind it; each track is "
                  "found by its name in the engine")
        log, failed = apply(eng, fs, want)
    except EngineError as e:
        failed.append(str(e))
    for line in log:
        print(line)
    for line in failed:
        print("  not done: " + line)
    if log:
        print(APP_NOTICES + ".")
    return 1 if failed else 0
