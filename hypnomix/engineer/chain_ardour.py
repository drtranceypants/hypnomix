"""`hypnomix chain --ardour`: the same mastering chain as in Live, built in the open HypnoMix Studio session over
MCP, from its own ACE plug-ins and the two HypnoMix Studio devices (all free, all built into HypnoMix Studio).

    Live device          HypnoMix Studio                             set by
    EQ Eight (low cut)   ACE High/Low Pass Filter             High Pass Steepness 12 or 48 dB/oct, cut-off, Q 0.71
    EQ Eight (tone)      ACE EQ                               low shelf (L), up to 4 bells (1-4, width in octaves
                                                              from Q), high shelf (H); unused bells switched off.
                                                              More than 4 bells: a second ACE EQ
    Glue Compressor      ACE Compressor (stereo)              threshold, ratio, attack, release, knee 6 dB
    Utility              Hypnomix Utility                     Bass Mono + its frequency (Linkwitz-Riley side
                                                              high-pass, mid all-pass: the highs keep their image),
                                                              Width %
    Saturator            (none yet)                           left out, listed in the notes
    Limiter              Hypnomix Limiter                     Gain, Ceiling (true peak, 4x oversampled), Release

The chain goes on the master bus, before Hypnomix Main if it is there (Main measures what the chain makes),
otherwise just before the fader. Values are set in the plug-in's own units (Hz, dB, ms, %), clamped to the
control's range, so they read in HypnoMix Studio exactly as planned.

If a step fails part-way, the build is taken back out: the plug-ins this run added are removed again, and (with
--existing bypass, which is done only after the whole chain is built) yours are switched back on; the message says what
was undone and, if something could not be, exactly what is left to check. The plug-in tools are not part of the
session's undo history, so Edit > Undo is not how to take a chain out: remove it from the master strip. The plan table
shows only what was really built and set: a stage that could not be added reads "NOT BUILT", a control that could not be
set reads "NOT SET", a value the plug-in's range moved reads "CLAMPED" with planned -> set (for Gain, Ceiling, Threshold
and Makeup, which change the loudness, it also counts as NOT SET), and the command then exits with an error. A failed run leaves nothing
behind; an incomplete one leaves what it built (the table says what), to be removed from the master strip before running
again. A plug-in whose add was applied but whose answer was lost is found by its position, never its name.

The connection: HypnoMix Studio's MCP server (switched on in Preferences → Control Surfaces → MCPHttp) or hypnomix-engine, at $HYPNOMIX_MCP_URL or
http://127.0.0.1:4820/mcp. The address must be on this computer (http://127.0.0.1, localhost or [::1]): the client uses
no proxy, follows no redirect and refuses any other address (core/loopback.py). Tools used: session_get_info,
tracks_list, track_get_info, plugin_add_by_unique_id, plugin_list_available + plugin_add_by_plugin_id (the Lua filter),
plugin_get_description, plugin_set_parameter_by_control_value, plugin_set_enabled, plugin_remove.
"""
import http.client
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from hypnomix.core import loopback

from hypnomix.engineer.chain_reaper import q_to_octaves

URL = os.environ.get("HYPNOMIX_MCP_URL", "http://127.0.0.1:4820/mcp")

# (type, uniqueId or catalogue name, shown name)
HPF = ("lua", "ACE High/Low Pass Filter", "ACE High/Low Pass Filter")
AEQ = ("lv2", "urn:ardour:a-eq", "ACE EQ")
ACOMP = ("lv2", "urn:ardour:a-comp#stereo", "ACE Compressor (stereo)")
UTILITY = ("lv2", "urn:hypnomix:utility", "Hypnomix Utility")
LIMITER = ("lv2", "urn:hypnomix:limiter", "Hypnomix Limiter")
LEVEL_CONTROLS = ("Ceiling", "Gain", "Threshold", "Makeup")     # a clamp here changes the loudness: the stage counts as not set
METERS = ("Hypnomix Main", "Hypnomix Probe")          # measuring devices: never bypassed, the chain goes before Main
STEEP = {"lowcut12": 1, "lowcut48": 4, "highcut12": 1, "highcut48": 4}


class MCPError(RuntimeError):
    """The engine could not be asked, or answered with something that is not MCP."""


class MCPToolError(MCPError):
    """The engine answered, and said no (an unknown plug-in, a refused value): a normal answer, not a broken link."""


def check_url(url):
    """The engine is a program on this computer: any other address (a name on the network, https, file:) is refused
    with one plain sentence, so the master plan can never be sent anywhere else."""
    u = urllib.parse.urlparse(str(url or ""))
    if u.scheme != "http" or not loopback.is_loopback(url):
        raise MCPError("the engine address must be on this computer, like http://127.0.0.1:4820/mcp "
                       f"(got {str(url)[:80]!r})")
    return url


class MCP:
    """A minimal MCP-over-HTTP client (JSON-RPC tools/call), standard library only. Loopback only: no proxy, no
    redirect; every reply it cannot use is an MCPError with one plain sentence."""

    def __init__(self, url=URL, timeout=30):
        self.url, self.timeout, self.n = check_url(url), timeout, 0

    def call(self, name, **args):
        self.n += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self.n, "method": "tools/call",
                           "params": {"name": name, "arguments": args}}).encode()
        req = urllib.request.Request(self.url, body, {"Content-Type": "application/json",
                                                      "Accept": "application/json, text/event-stream"})
        try:
            with loopback.urlopen(req, timeout=self.timeout) as r:      # this computer only: no proxy, no redirect
                raw = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise MCPError(f"{name}: the engine answered HTTP {e.code} ({e.reason})") from e
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            raise MCPError(f"{name}: no answer from {self.url} ({e})") from e
        d = self._message(name, raw)
        try:
            return self._result(name, d)
        except MCPError:
            raise
        except (KeyError, TypeError, IndexError, AttributeError) as e:
            raise MCPError(f"{name}: the engine's answer is not what HypnoMix Studio sends ({type(e).__name__}); "
                           "it is not MCP") from e

    @staticmethod
    def _text(res):
        """The text of a result's first content item ("" when there is none or the shape is not a list of objects)."""
        content = res.get("content")
        first = content[0] if isinstance(content, list) and content else None
        txt = first.get("text") if isinstance(first, dict) else first
        return txt if isinstance(txt, str) else ""

    def _result(self, name, d):
        if d.get("error") is not None:
            err = d["error"]
            msg = err.get("message") if isinstance(err, dict) else err
            raise MCPToolError(f"{name}: {msg or 'the engine reported an error without saying what'}")
        res = d.get("result", {})
        if not isinstance(res, dict):
            raise MCPError(f"{name}: the engine's answer has no result (it is not MCP)")
        if res.get("isError"):
            raise MCPToolError(f"{name}: {self._text(res) or 'the engine refused it without saying why'}")
        if "structuredContent" in res:
            return res["structuredContent"]
        txt = self._text(res)
        try:
            return json.loads(txt)
        except (TypeError, ValueError):
            return txt

    def _message(self, name, raw):
        """The JSON-RPC message that answers this call: a plain JSON reply, or the matching event of an event
        stream (progress notifications and other events around it are skipped)."""
        text = raw.strip()
        cands = []
        try:
            if text.startswith(("event:", "data:", "id:", ":")):                # SSE framing, event by event
                for block in re.split(r"\r?\n\r?\n", text):
                    data = "\n".join(ln[5:][1:] if ln[5:].startswith(" ") else ln[5:]
                                     for ln in block.splitlines() if ln.startswith("data:"))
                    if data.strip():
                        cands.append(json.loads(data))
            else:
                cands.append(json.loads(text))
        except ValueError as e:
            raise MCPError(f"{name}: the engine answered with something that is not MCP (not JSON: {text[:40]!r})") from e
        flat = [x for c in cands for x in (c if isinstance(c, list) else [c]) if isinstance(x, dict)]
        answers = [x for x in flat if "result" in x or "error" in x]
        mine = [x for x in answers if x.get("id") == self.n]
        # an answer that carries a different id belongs to another call: never taken. One that carries no id at all is
        # taken only when it is the only answer in the reply
        mine = mine or ([x for x in answers if x.get("id") is None] if len(answers) == 1 else [])
        if not mine:
            raise MCPError(f"{name}: the engine's reply held no answer to the call (it is not MCP)")
        return mine[-1]

    def ping(self):
        return self.call("session_get_info")


def obj(m, name, **args):
    """`m.call`, for tools whose answer is an object: anything else is an MCPError, not a crash further on."""
    r = m.call(name, **args)
    if not isinstance(r, dict):
        raise MCPError(f"{name}: the engine's answer was not what HypnoMix Studio sends ({str(r)[:60]!r})")
    return r


def master_route(m):
    # Hypnomix's tracks_list reports the master as type "bus" (route_type_string has no "master") and Ardour names
    # it "Master": take an explicit flag when the server has one, else the bus named Master
    routes = [r for r in obj(m, "tracks_list", includeHidden=True).get("tracks", []) if isinstance(r, dict)]
    for r in routes:
        if r.get("type") == "master" or r.get("isMaster"):
            return r
    for r in routes:
        if r.get("type") == "bus" and r.get("name") == "Master":
            return r
    raise MCPError('the session has no master bus (no bus in tracks_list is named "Master")')


class Builder:
    def __init__(self, m, route_id, dry=False, position=None):
        self.m, self.rid, self.dry, self.notes = m, route_id, dry, []
        self.position = position          # insert here (and after each insert, one further); None = before the fader
        self.start = position             # where the first insert went (an add whose reply is lost sits here once the rest are out)
        self.added = []                   # (pluginIndex, shown name)
        self.unset = []                   # (pluginIndex, label) of controls that could not be set (as planned)
        self.clamps = []                  # (pluginIndex, label, planned, set) where the plug-in's range moved the value
        self._desc = {}

    def add(self, dev):
        kind, uid, shown = dev
        if self.dry:
            self.added.append((None, shown))
            return None
        args = {"id": self.rid}
        if self.position is not None:
            args["position"] = self.position
        try:
            if kind == "lua":
                hits = [p for p in obj(self.m, "plugin_list_available", search=uid, type="lua").get("plugins", [])
                        if isinstance(p, dict) and p.get("name") == uid]
                if not hits:
                    self.notes.append(f"{shown}: not found in this HypnoMix Studio (Lua scripts missing?); add it by hand")
                    return None
                r = obj(self.m, "plugin_add_by_plugin_id", pluginId=hits[0]["pluginId"], **args)
            else:
                r = obj(self.m, "plugin_add_by_unique_id", uniqueId=uid, type=kind, **args)
        except MCPToolError as e:             # the engine said no: a missing or older device. A broken link is fatal
            self.notes.append(f"{shown}: could not be added ({e}); is this HypnoMix Studio older than the device?")
            return None
        try:
            pi = int(r["pluginIndex"])
        except (KeyError, TypeError, ValueError) as e:
            raise MCPError(f"{shown}: the engine added it but did not say where (no pluginIndex)") from e
        if self.position is not None:
            self.position = pi + 1
        self.added.append((pi, shown))
        return pi

    def params(self, pi):
        if pi not in self._desc:
            d = obj(self.m, "plugin_get_description", id=self.rid, pluginIndex=pi)
            self._desc[pi] = {p["label"]: p for p in d.get("parameters", []) if isinstance(p, dict) and "label" in p
                              and p.get("isInput", True) and not p.get("isOutput")}
        return self._desc[pi]

    def set(self, pi, label, value):
        """Set a control by its label in the plug-in's own units, clamped to its range. Returns the value set."""
        if self.dry or pi is None:
            return value
        p = self.params(pi).get(label)
        if p is None:
            self.notes.append(f"{label}: not found on plug-in {pi} (set it by hand to {value})")
            self.unset.append((pi, label))
            return None
        v = float(value)
        lo, hi = p.get("lower"), p.get("upper")
        if lo is not None and hi is not None and lo < hi:
            if v < lo or v > hi:
                self.notes.append(f"{label} {value} is outside {lo:g}..{hi:g}: set to the nearest end")
                self.clamps.append((pi, label, float(value), min(max(v, lo), hi)))
                if label in LEVEL_CONTROLS:          # a different level is a different master: not "as planned"
                    self.unset.append((pi, label))
            v = min(max(v, lo), hi)
        try:
            self.m.call("plugin_set_parameter_by_control_value", id=self.rid, pluginIndex=pi,
                        controlId=int(p["controlId"]), value=v)
        except MCPToolError as e:             # the engine refused this one value
            self.notes.append(f"{label}: the engine refused it ({e}); set it by hand to {value}")
            self.unset.append((pi, label))
            return None
        except (KeyError, TypeError, ValueError) as e:
            raise MCPError(f"{label}: the engine's description of this control is damaged ({type(e).__name__})") from e
        return v

    # ------------------------------------------------------------ stages
    def filters(self, bands):
        """Low and high cuts (EQ Eight types lowcut*/highcut*) on one ACE High/Low Pass Filter."""
        lo = next((b for b in bands if b["type"].startswith("lowcut")), None)
        hi = next((b for b in bands if b["type"].startswith("highcut")), None)
        if not lo and not hi:
            return None
        pi = self.add(HPF)
        self.set(pi, "High Pass Steepness", STEEP[lo["type"]] if lo else 0)
        if lo:
            self.set(pi, "High Pass Cut off frequency", lo["freq"])
            self.set(pi, "High Pass Resonance", lo.get("q", 0.7071) or 0.7071)
        self.set(pi, "Low Pass Steepness", STEEP[hi["type"]] if hi else 0)
        if hi:
            self.set(pi, "Low Pass Cut off frequency", hi["freq"])
            self.set(pi, "Low Pass Resonance", hi.get("q", 0.7071) or 0.7071)
        return pi

    def eq(self, bands):
        """Shelves and bells onto ACE EQ (low shelf, 4 bells, high shelf); a second one if there are more bells."""
        tone = [b for b in bands if b["type"] in ("lowshelf", "highshelf", "bell", "notch")]
        if not tone:
            return []
        ls = next((b for b in tone if b["type"] == "lowshelf"), None)
        hs = next((b for b in tone if b["type"] == "highshelf"), None)
        bells = [b for b in tone if b["type"] in ("bell", "notch")]
        for b in bells:
            if b["type"] == "notch":
                self.notes.append(f"notch at {b['freq']:g} Hz: ACE EQ has no notch, a narrow -18 dB bell instead")
        out = []
        for k in range(0, max(1, len(bells)), 4):
            part = bells[k:k + 4]
            pi = self.add(AEQ)
            first = k == 0
            self.set(pi, "Filter L", 1 if first and ls else 0)
            self.set(pi, "Filter H", 1 if first and hs else 0)
            if first and ls:
                self.set(pi, "Frequency L", ls["freq"]); self.set(pi, "Gain L", ls["gain"])
            if first and hs:
                self.set(pi, "Frequency H", hs["freq"]); self.set(pi, "Gain H", hs["gain"])
            for n in range(1, 5):
                if n <= len(part):
                    b = part[n - 1]
                    notch = b["type"] == "notch"
                    self.set(pi, f"Filter {n}", 1)
                    self.set(pi, f"Frequency {n}", b["freq"])
                    self.set(pi, f"Gain {n}", -18.0 if notch else b["gain"])
                    self.set(pi, f"Bandwidth {n}", 0.1 if notch else round(min(4.0, max(0.1, q_to_octaves(b.get("q", 0.9)))), 3))
                else:
                    self.set(pi, f"Filter {n}", 0)
                    self.set(pi, f"Gain {n}", 0)
            self.set(pi, "Master Gain", 0)
            out.append(pi)
        return out


def _existing(m, rid):
    """The plug-ins on a route now: [{index, name, enabled, ...}] in the engine's order."""
    plugins = obj(m, "track_get_info", id=rid).get("plugins", [])
    out = [p for p in plugins if isinstance(p, dict)]
    if len(out) != len(plugins) or any("index" not in p for p in out):
        raise MCPError("track_get_info: the engine's plug-in list is not what HypnoMix Studio sends")
    return out


def _name(p):
    return str(p.get("name", ""))


OURS = {HPF[2], AEQ[2], ACOMP[2], UTILITY[2], LIMITER[2]}       # the plug-ins this command adds (never the person's own)


def _unknown_adds(before, now, position):
    """The plug-ins now on the master that this run added although the engine's reply never said so. They were put in
    as one block, so they are the run of plug-ins that, taken out, leaves the list as it was. Found by position, never
    by name (the person may have a plug-in named like ours): [] when nothing is extra; a sentence (nothing is removed) when
    the block cannot be told from the person's own plug-ins or holds something that is not ours."""
    names_b, names_n = [_name(p) for p in before], [_name(p) for p in now]
    k = len(now) - len(before)
    if k < 0:
        return "the master has fewer plug-ins than before this run: look at the master strip"
    if k == 0:
        return []
    starts = [i for i in range(len(before) + 1) if names_n[:i] == names_b[:i] and names_n[i + k:] == names_b[i:]]
    if position is not None and position in starts:
        starts = [position]                         # where the run was inserting when the reply was lost
    if len(starts) != 1:
        return (f"{k} plug-in(s) too many on the master and it cannot be told which are the chain's (plug-ins "
                f"0..{len(now) - 1}: {', '.join(names_n)}); nothing was removed, look at the master strip")
    block = now[starts[0]:starts[0] + k]
    if any(_name(p) not in OURS for p in block):
        return "plug-ins appeared on the master that are not the chain's: look at the master strip"
    return block


def _rollback(m, rid, before, b, bypassed):
    """Put the master back as it was before this run: remove what it added, switch the person's own plug-ins on again.
    Never raises; returns the list of things it could not undo (empty = the master is as it was)."""
    problems = []

    def step(what, tool, **a):
        try:
            m.call(tool, id=rid, **a)
            return True
        except Exception as e:
            problems.append(f"{what}: {e}")
            return False
    for pi, shown in sorted([x for x in b.added if x[0] is not None], reverse=True):     # highest first: indexes hold
        step(f"could not remove {shown} (plug-in {pi})", "plugin_remove", pluginIndex=pi)
    try:                    # an add whose reply could not be read: find it by where it is, not by its name
        now = _existing(m, rid)
        gone = _unknown_adds(before, now, b.start)
        if isinstance(gone, str):
            problems.append(gone)
        for p in sorted(gone if not isinstance(gone, str) else [], key=lambda p: -int(p["index"])):
            step(f"could not remove {_name(p)} (plug-in {p['index']})", "plugin_remove", pluginIndex=int(p["index"]))
    except Exception as e:
        problems.append(f"could not look at the master to check what was added: {e}")
    if bypassed:
        try:
            now = {int(p["index"]): p for p in _existing(m, rid)}
        except Exception as e:
            now = None
            problems.append(f"could not look at the master to switch your plug-ins back on: {e}")
        for orig, name in bypassed:
            if now is not None and _name(now.get(orig, {})) != name:
                problems.append(f"{name} (plug-in {orig}) is not where it was: switch it on again by hand")
            else:
                step(f"could not switch {name} (plug-in {orig}) back on", "plugin_set_enabled", pluginIndex=orig,
                     enabled=True)
    return problems


class Stage:
    """What one stage of the plan really became: the plug-ins added and the controls that could not be set."""

    def __init__(self, b, name, why):
        self.b, self.name, self.why, self.mark, self.pis = b, name, why, len(b.unset), []
        self.cmark = len(b.clamps)

    def done(self, settings, pis=None):
        b = self.b
        pis = self.pis if pis is None else pis
        if not b.dry and (not pis or any(pi is None for pi in pis)):
            return (f"NOT BUILT: {self.name}", "not added (see the notes below)", self.why)
        bad = sorted({label for _, label in b.unset[self.mark:]})
        cut = [f"{label} {planned:g} -> {got:g}" for _, label, planned, got in b.clamps[self.cmark:]]
        text = settings
        if bad:
            text += f" -- NOT SET: {', '.join(bad)}"
        if cut:
            text += f" -- CLAMPED by the plug-in's range (planned -> set): {'; '.join(cut)}"
        return (self.name, text, self.why)


def incomplete(rows):
    """Did anything in the plan fail to be built or set (the Saturator is left out by design, not a failure)?"""
    return any(r[0].startswith("NOT BUILT") or "NOT SET" in r[1] for r in rows)


def build_master(m, plan, existing="refuse", dry=False, route_id=None):
    """Build the plan's chain on the master bus. Returns (rows for the report, notes). The rows say what was really
    built and set. If a call fails part-way the build is taken back out and an MCPError says what was done and what was
    not (the person's own plug-ins are only switched off once the whole chain is in, and switched on again on failure)."""
    position = None
    rid = route_id
    before, others = [], []
    if not dry:
        try:
            rid = rid or master_route(m)["id"]
            have = before = _existing(m, rid)
        except MCPError as e:
            raise MCPError(f"Nothing was changed: {e}") from e
        meters = [p for p in have if any(_name(p).startswith(n) for n in METERS)]
        others = [p for p in have if p not in meters]
        if others:
            names = [_name(p) for p in others]
            if existing not in ("bypass", "keep"):
                raise SystemExit(f"the master already has plug-ins {names}; use --existing bypass or --existing keep")
        main = next((p for p in meters if _name(p).startswith("Hypnomix Main")), None)
        if main is not None:
            position = int(main["index"])
    b = Builder(m, rid, dry, position)
    bypassed = []                                    # [(original index, name)] of the person's plug-ins switched off here
    try:
        rows = _build_stages(b, plan)
        if not dry and others and existing == "bypass" and incomplete(rows):
            b.notes.append("Your own plug-ins on the master were NOT bypassed, because the chain above is "
                           "incomplete: switch them off by hand once the chain is finished.")
        elif not dry and others and existing == "bypass":
            # now that the chain is in: find the person's plug-ins again (the new ones shifted the indexes) and bypass them
            now = _existing(m, rid)
            new_idx = {pi for pi, _ in b.added if pi is not None}
            old_now = [p for p in now if int(p["index"]) not in new_idx]
            if len(old_now) != len(before):
                raise MCPError("the master changed while the chain was being built (plug-ins you did not ask for "
                               "appeared or went)")
            for was, cur in zip(before, old_now):
                if was in others and cur.get("enabled", True):
                    bypassed.append((int(was["index"]), _name(was), int(cur["index"])))       # noted first: on failure it is put back
                    m.call("plugin_set_enabled", id=rid, pluginIndex=int(cur["index"]), enabled=False)
    except BaseException as e:
        if dry or isinstance(e, SystemExit):
            raise
        problems = _rollback(m, rid, before, b, [(o, n) for o, n, _ in bypassed])
        raise MCPError(_failure_text(e, b, before, problems)) from e
    return rows, b.notes


def _failure_text(e, b, before, problems):
    """One complete message: why, what was undone, what is left to look at."""
    why = str(e) if isinstance(e, MCPError) else f"{type(e).__name__}: {e}"
    if isinstance(e, KeyboardInterrupt):
        why = "interrupted"
    made = [f"{shown} (plug-in {pi})" for pi, shown in b.added if pi is not None]
    if not problems:
        return (f"The chain was NOT built: {why}. Everything this run had changed was taken back out "
                f"({len(made)} plug-in(s) removed, your own plug-ins as they were): the master is as it was.")
    return (f"The chain was NOT built: {why}. This run had added: {', '.join(made) or 'nothing it could name'}. "
            f"It could not take everything back out: " + "; ".join(problems) + ". Look at the master strip in "
            "HypnoMix Studio: remove any plug-in of the chain that is still there and switch your own back on if they "
            "are off.")


def _build_stages(b, plan):
    """The plan's stages, built; the rows describe what each really became."""
    rows = []
    for step in plan:
        d = step["device"]
        if d == "EQ Eight":
            bands = step["bands"]
            cuts = [x for x in bands if x["type"].startswith(("lowcut", "highcut"))]
            if cuts:
                st = Stage(b, "ACE High/Low Pass Filter", step["why"])
                st.pis = [b.filters(bands)]
                rows.append(st.done("; ".join(
                    f"{'high-pass' if x['type'].startswith('lowcut') else 'low-pass'} {x['freq']:g} Hz, "
                    f"{12 if x['type'].endswith('12') else 48} dB/oct" for x in cuts)))
            tone = [x for x in bands if x["type"] in ("lowshelf", "highshelf", "bell", "notch")]
            if tone:
                st = Stage(b, "ACE EQ", step["why"])
                eqs = b.eq(bands)
                st.name = "ACE EQ" + (f" x{len(eqs)}" if len(eqs) > 1 else "")
                rows.append(st.done("; ".join(f"{x['type']} {x['freq']:g} Hz {x['gain']:+.1f} dB" for x in tone), eqs))
        elif d == "Glue Compressor":
            st = Stage(b, "ACE Compressor (stereo)", step["why"])
            pi = b.add(ACOMP)
            b.set(pi, "Attack", step["attack_ms"])
            b.set(pi, "Release", step["release_s"] * 1000)
            b.set(pi, "Knee", 6)
            b.set(pi, "Ratio", step["ratio"])
            b.set(pi, "Threshold", step["threshold_db"])
            b.set(pi, "Makeup", step.get("makeup_db", 0))
            b.set(pi, "Sidechain", 0)
            rows.append(st.done(f"threshold {step['threshold_db']} dB, {step['ratio']}:1, attack "
                                f"{step['attack_ms']} ms, release {step['release_s'] * 1000:.0f} ms, knee 6 dB", [pi]))
        elif d == "Utility":
            st = Stage(b, "Hypnomix Utility", step["why"])
            pi = b.add(UTILITY)
            parts = []
            hz = step.get("bass_mono_hz")
            b.set(pi, "Bass Mono", 1 if hz else 0)
            if hz:
                b.set(pi, "Bass Mono Frequency", hz)
                parts.append(f"bass mono below {hz:g} Hz")
            w = step.get("width_pct", 100)
            b.set(pi, "Width", w)
            if w != 100:
                parts.append(f"width {w}%")
            if step.get("gain_db"):
                b.set(pi, "Gain", step["gain_db"])
                parts.append(f"gain {step['gain_db']:+.1f} dB")
            rows.append(st.done(", ".join(parts) or "neutral", [pi]))
        elif d == "Saturator":
            b.notes.append(f"Saturator (drive {step['drive_db']} dB, {step['dry_wet_pct']}% wet): HypnoMix Studio has no "
                           "saturator yet, so the warmth stage is left out")
            rows.append(("(left out)", f"Saturator drive {step['drive_db']} dB", step["why"]))
        elif d == "Limiter":
            st = Stage(b, "Hypnomix Limiter", step["why"])
            pi = b.add(LIMITER)
            b.set(pi, "Gain", step["gain_db"])
            b.set(pi, "Ceiling", step["ceiling_db"])
            if step.get("release_ms"):
                b.set(pi, "Release", step["release_ms"])
            b.set(pi, "Lookahead", step.get("lookahead_ms", 1.5))
            b.set(pi, "True Peak", 1)
            step["_pi"] = pi
            rows.append(st.done(f"gain {step['gain_db']:+.1f} dB, ceiling {step['ceiling_db']} dBTP "
                                f"(true peak)" + (f", release {step['release_ms']:g} ms" if step.get("release_ms") else ""),
                                [pi]))
    return rows


def main_ardour(a, plan_master):
    """`hypnomix chain master BOUNCE --ardour`: plan offline, build over MCP (or print the plan with --dry-run)."""
    import sys
    from pathlib import Path
    if a.cmd != "master":
        sys.exit("chain strips --ardour isn't built yet: in HypnoMix Studio, use chain master (strips are Live and REAPER for now)")
    m = None
    if not a.dry_run:
        try:
            m = MCP(getattr(a, "mcp_url", None) or URL)
            info = m.ping()
        except MCPError as e:
            sys.exit(f"HypnoMix Studio isn't answering at {getattr(a, 'mcp_url', None) or URL}: open the session in HypnoMix Studio "
                     f"(its MCP server is switched on in Preferences → Control Surfaces → MCPHttp) or start hypnomix-engine. ({e})")
        name = info.get("name") if isinstance(info, dict) else None
        print(f"HypnoMix Studio session {name or '(open)'}: the chain is built on the master bus; if a step fails, what this "
              f"run added is taken back out.", file=sys.stderr)
    print(f"analysing {Path(a.bounce).name} …", file=sys.stderr)
    plan, ctx = plan_master(a.bounce, a.target, a.ceiling, a.reference, a.match, a.warmth, a.width)
    try:
        rows, notes = build_master(m, plan, a.existing, a.dry_run)
    except MCPError as e:
        sys.exit(str(e))
    except (KeyError, TypeError, ValueError, AttributeError) as e:      # a reply that is not what Hypnomix sends, before any change
        sys.exit(f"The engine's answer was not what HypnoMix Studio sends ({type(e).__name__}: {e}); nothing was changed.")
    md = [f"# Mastering chain on the HypnoMix Studio master bus{' (plan only)' if a.dry_run else ''}", "",
          "| plug-in | settings | why |", "|---|---|---|", *[f"| {d} | {s} | {w} |" for d, s, w in rows]]
    if notes:
        md += ["", "Notes:", *[f"- {n}" for n in notes]]
    if getattr(a, "verify", False):
        md += ["", "--verify isn't available in HypnoMix Studio yet (it needs an export over MCP). Hypnomix Main's "
               "Match target turns the chain to the song card's loudness while the song plays."]
    print("\n".join(md))
    if incomplete(rows):
        sys.exit("The chain is incomplete: the rows marked NOT BUILT or NOT SET above were not done (see the notes). "
                 "What was built is on the master bus and your own plug-ins were left as they were. Finish the missing "
                 "parts by hand; or, to build it again once the cause is fixed, first remove the plug-ins this run "
                 "added from the master strip (every row above that is not marked NOT BUILT), because running it again "
                 "on top of them would build the chain twice.")
    return rows, notes
