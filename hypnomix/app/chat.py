"""The Assistant tab: talk to an AI about your song, and let it run hypnomix for you.

Bring your own key from any provider:
  Claude (Anthropic)                 the Anthropic SDK
  OpenAI, Google Gemini, OpenRouter,  the OpenAI SDK, each at its own address (these all speak the same chat format)
  Groq, Mistral, Ollama on this computer (free, no key), or any other service that speaks it

The key is kept on this computer only (~/.hypnomix/ai.json, readable by you alone) and goes only to the provider
you chose. Your audio never leaves the computer: the assistant sees hypnomix's text reports, not the songs.

What the assistant can do: list your songs, read a review, run any hypnomix command (a scan, a measurement, a
check, a render), point Live at a finding (with the Max for Live device loaded), and read the reports. Anything
that WRITES a set (an --apply, fix --approved, an .als --out) waits for you: the chat shows the exact command with
Run it / Don't, and nothing happens until you click. hypnomix itself never overwrites a set: changes always go
into a new one next to the original.
"""
import json, os, re, shlex, subprocess, sys, threading, time, uuid
from pathlib import Path

CONF = Path("~/.hypnomix/ai.json").expanduser()
FORBIDDEN = {"app", "install"}                       # starting another app, installing into Live: not from a chat
WRITE_FLAGS = {"--apply", "--apply-set", "--fix", "--approved", "--approve"}
MAX_STEPS = 40                                       # tool rounds per message, so a confused model can't loop forever

PROVIDERS = {
    "anthropic": dict(label="Claude (Anthropic)", kind="anthropic", base_url="", model="claude-opus-5-5",
                      keys_at="console.anthropic.com"),
    "openai": dict(label="OpenAI", kind="openai", base_url="https://api.openai.com/v1", model="",
                   keys_at="platform.openai.com"),
    "gemini": dict(label="Google Gemini", kind="openai", base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                   model="", keys_at="aistudio.google.com"),
    "openrouter": dict(label="OpenRouter (many models, one key)", kind="openai", base_url="https://openrouter.ai/api/v1",
                       model="", keys_at="openrouter.ai"),
    "groq": dict(label="Groq", kind="openai", base_url="https://api.groq.com/openai/v1", model="", keys_at="console.groq.com"),
    "mistral": dict(label="Mistral", kind="openai", base_url="https://api.mistral.ai/v1", model="", keys_at="console.mistral.ai"),
    "ollama": dict(label="Ollama on this computer (free, no key)", kind="openai", base_url="http://localhost:11434/v1",
                   model="", keys_at="", no_key=True),
    "custom": dict(label="Other (OpenAI-compatible address)", kind="openai", base_url="", model="", keys_at=""),
}
CLAUDE_FALLBACKS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-fable-5-2"}

LOCK = threading.RLock()
CHAT = {"id": uuid.uuid4().hex[:8], "items": [], "history": [], "provider": None, "busy": False, "pending": None,
        "stop": False, "error": ""}


# ---------------------------------------------------------------- settings (the key stays on this computer)
def load_conf():
    try:
        return json.loads(CONF.read_text())
    except (OSError, ValueError):
        return {"provider": "anthropic", "models": {}, "base_urls": {}, "keys": {}}


def save_conf(c):
    CONF.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONF.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(c, fh, indent=1)
    os.replace(tmp, CONF)
    os.chmod(CONF, 0o600)


def settings_view():
    c = load_conf()
    p = c.get("provider") or "anthropic"
    out = []
    for k, d in PROVIDERS.items():
        key = (c.get("keys") or {}).get(k) or ""
        out.append(dict(id=k, label=d["label"], kind=d["kind"], keys_at=d["keys_at"], no_key=bool(d.get("no_key")),
                        model=(c.get("models") or {}).get(k) or d["model"],
                        base_url=(c.get("base_urls") or {}).get(k) or d["base_url"],
                        key_hint=("…" + key[-4:]) if len(key) >= 8 else ("saved" if key else "")))
    return dict(provider=p, providers=out)


def update_settings(body):
    c = load_conf()
    p = body.get("provider") or c.get("provider") or "anthropic"
    if p not in PROVIDERS:
        raise ValueError("unknown provider")
    c["provider"] = p
    for field, store in (("model", "models"), ("base_url", "base_urls")):
        if field in body:
            c.setdefault(store, {})[p] = str(body[field]).strip()
    if body.get("key"):
        c.setdefault("keys", {})[p] = str(body["key"]).strip()
    if body.get("forget"):
        c.setdefault("keys", {}).pop(p, None)
    save_conf(c)
    return settings_view()


def active():
    c = load_conf()
    p = c.get("provider") or "anthropic"
    d = PROVIDERS[p]
    model = (c.get("models") or {}).get(p) or d["model"]
    base = (c.get("base_urls") or {}).get(p) or d["base_url"]
    key = (c.get("keys") or {}).get(p) or ("ollama" if d.get("no_key") else "")
    return p, d, model, base, key


def list_models():
    p, d, model, base, key = active()
    if not key:
        raise ValueError(f"save a {d['label']} key first")
    if d["kind"] == "anthropic":
        import anthropic
        return sorted(m.id for m in anthropic.Anthropic(api_key=key).models.list())
    import openai
    return sorted(m.id for m in openai.OpenAI(api_key=key, base_url=base or None).models.list())


# ---------------------------------------------------------------- what the assistant may do
TOOLS = [
    dict(name="list_songs",
         description="The songs this app has scanned: name, scan folder, how many findings are decided/approved.",
         params={}),
    dict(name="read_review",
         description="Every finding of one scanned song (id, tool, track, where, problem, fix, the person's decision). "
                     "Use the scan folder from list_songs.",
         params={"dir": ("string", "the scan folder")}),
    dict(name="run_hypnomix",
         description=("Run one hypnomix command and get its output, e.g. command='scan', args=['/path/Song.als', '--mix', "
                      "'/path/bounce.wav']; command='fix', args=['<scan dir>', '--list']; command='check', ...; "
                      "command='edges' etc. Use `<command> -h` (args=['-h']) to learn a command's options. Anything that "
                      "writes a set waits for the person to click Run it in the chat; reading and measuring run at once."),
         params={"command": ("string", "a hypnomix command name"),
                 "args": ("array", "the command's arguments, one per item (paths as they are, no quoting)")}),
    dict(name="read_file",
         description="Read a text report the tools wrote (REVIEW.md, fix-log.md, a .json or .txt in the songs folder).",
         params={"path": ("string", "full path of the file")}),
    dict(name="show_in_live",
         description="Make Live jump to a finding (select the track, move the playhead and loop there). Needs the "
                     "hypnomix Max for Live device loaded in the set.",
         params={"dir": ("string", "the scan folder"), "id": ("string", "the finding id, e.g. edges-3")}),
]


def anthropic_tools():
    out = []
    for t in TOOLS:
        props = {k: ({"type": "array", "items": {"type": "string"}, "description": d} if ty == "array"
                     else {"type": ty, "description": d}) for k, (ty, d) in t["params"].items()}
        out.append(dict(name=t["name"], description=t["description"], strict=True,
                        input_schema={"type": "object", "properties": props, "required": list(props),
                                      "additionalProperties": False}))
    return out


def openai_tools():
    return [dict(type="function", function=dict(name=t["name"], description=t["description"], parameters=a["input_schema"]))
            for t, a in zip(TOOLS, anthropic_tools())]


def needs_ok(command, args):
    a = [str(x) for x in args]
    if any(x in WRITE_FLAGS for x in a):
        return True
    if "--out" in a:
        rest = a[a.index("--out") + 1:]
        if rest and rest[0].lower().endswith((".als", ".rpp", ".ardour")):
            return True
    return command in ("rename", "device", "aligndevice") and "-h" not in a


def ask_ok(command, args):
    """Show the command in the chat and wait for the person's click."""
    pid = uuid.uuid4().hex[:8]
    ev = threading.Event()
    with LOCK:
        CHAT["pending"] = dict(id=pid, command=command, args=[str(x) for x in args], event=ev, ok=None)
        CHAT["items"].append(dict(kind="ask", id=pid, text="hypnomix " + " ".join(shlex.quote(str(x)) for x in [command, *args])))
    while not ev.wait(0.5):
        if CHAT["stop"]:
            break
    with LOCK:
        p, CHAT["pending"] = CHAT["pending"], None
        ok = bool(p and p.get("ok")) and not CHAT["stop"]
        for it in CHAT["items"]:
            if it.get("id") == pid:
                it["answer"] = "ran" if ok else "declined"
    return ok


def run_cli(command, args):
    """Through the app's job runner, so it shows in Activity and can be stopped there."""
    from hypnomix.app import server as S
    title = f"assistant: hypnomix {command}"
    try:
        S.run_job("tool", title, [(command, [command, *map(str, args)], True)])
    except RuntimeError as e:
        return f"not run: {e}"
    while S.JOB["status"] == "running":
        if CHAT["stop"]:
            p = S.JOB.get("proc")
            if p:
                p.terminate()
        time.sleep(0.3)
    log = "\n".join(S.JOB["log"])
    status = S.JOB["status"]
    return (f"[{status}]\n" + log[-9000:]) if log else f"[{status}] (no output)"


def tool(name, inp):
    from hypnomix.app import server as S
    try:
        if name == "list_songs":
            return json.dumps(S.scans(), default=str)[:12000]
        if name == "read_review":
            d = S.scan_dir(inp["dir"])
            p = S.review_payload(d)
            keep = ("id", "tool", "kind", "severity", "track", "where", "problem", "fix", "applies", "recommended")
            rows = [{k: f.get(k) for k in keep if f.get(k) is not None} for f in p.get("findings", [])]
            dec = p.get("decisions", {})
            for r in rows:
                if r["id"] in dec:
                    r["decision"] = dec[r["id"]]
            return json.dumps(dict(dir=str(d), findings=rows), default=str)[:30000]
        if name == "run_hypnomix":
            cmd, args = str(inp.get("command", "")).strip(), list(inp.get("args") or [])
            from hypnomix import cli
            if cmd not in cli.COMMANDS or cmd in FORBIDDEN:
                return f"no such command here: {cmd!r} (see list_songs, or run 'scan', 'fix', 'check', ... with -h)"
            if needs_ok(cmd, args) and not ask_ok(cmd, args):
                return "The person chose not to run this. Ask what they would like instead."
            return run_cli(cmd, args)
        if name == "read_file":
            f = Path(inp["path"]).expanduser().resolve()
            homes = [S.work().resolve(), Path("~/.hypnomix").expanduser().resolve()]
            if not any(f.is_relative_to(h) for h in homes) or f.suffix.lower() not in (".md", ".txt", ".json", ".csv"):
                return "only text reports in the songs folder can be read"
            return f.read_text(errors="replace")[:30000]
        if name == "show_in_live":
            d = S.scan_dir(inp["dir"])
            f = next((x for x in S.review_payload(d)["findings"] if x["id"] == inp["id"]), None)
            if not f or not f.get("jump"):
                return "that finding has no place in the set to jump to"
            S.live_send(dict(type="jump", **f["jump"]))
            return "sent to Live" if time.time() - S.LIVE["seen"] < 3.0 else \
                "sent, but the Max for Live device isn't connected: load it in the set (hypnomix device)"
        return f"unknown tool {name}"
    except (KeyError, ValueError, OSError) as e:
        return f"error: {e}"


def system_prompt():
    guide = ""
    for nm in ("AGENTS.md",):
        f = Path(__file__).resolve().parents[2] / nm
        if f.exists():
            guide = f.read_text()
    return ("You are the assistant inside the hypnomix app, a free mixing and mastering toolkit for people who record "
            "real instruments and voices. You help one musician with their own songs, in plain words, briefly.\n\n"
            "How you work here: you cannot type in a terminal; you act only through the tools you are given. "
            "run_hypnomix runs any hypnomix command (the reference below lists them). The usual path for a song is: "
            "scan it (read-only), read the review, explain each finding and what its fix would do, record the "
            "person's decisions (fix DIR --decide ID=approve|skip, only what they actually said), then apply only "
            "what they approved into a NEW set (fix DIR --approved --out \"<Song> (fixed).als\" next to the original). "
            "Rules: never overwrite a set; ask them to save and close the set in Live before anything writes; keep the "
            "human feel (gentle, partial edits, never quantise or hard-tune); never apply something they did not "
            "approve; when unsure what a track is or what they want, ask. Commands that write wait for the person "
            "to click Run it: say what the command will do before you run it. Report what changed and what to A/B. "
            "Paths: they can attach a set or folder with the buttons under the chat box, which pastes its path.\n\n"
            "Reference (written for terminal agents; here, use the tools instead of a shell):\n\n" + guide)


# ---------------------------------------------------------------- the conversation
def say(kind, text, **k):
    with LOCK:
        CHAT["items"].append(dict(kind=kind, text=text, t=time.time(), **k))


def _anthropic_turn(model, key):
    import anthropic
    client = anthropic.Anthropic(api_key=key, max_retries=3)
    tools = anthropic_tools()
    system = [{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}]
    for _ in range(MAX_STEPS):
        if CHAT["stop"]:
            return
        params = dict(model=model, max_tokens=16000, system=system, tools=tools, messages=CHAT["history"])
        if model in CLAUDE_FALLBACKS:     # on a policy decline, the API retries on the model it picks for that case
            r = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
        else:
            r = client.messages.create(**params)
        content = [b.model_dump(exclude_none=True) for b in r.content]   # thinking blocks kept as they came
        CHAT["history"].append({"role": "assistant", "content": content})
        for b in r.content:
            if b.type == "text" and b.text.strip():
                say("assistant", b.text)
        if r.stop_reason == "refusal":
            say("note", "The model declined this request.")
            return
        if r.stop_reason == "pause_turn":
            continue
        uses = [b for b in r.content if b.type == "tool_use"]
        if r.stop_reason != "tool_use" or not uses:
            if r.stop_reason == "max_tokens":
                say("note", "The reply was cut off (too long). Ask it to continue.")
            return
        results = []
        for b in uses:
            say("tool", _label(b.name, b.input))
            out = tool(b.name, b.input)
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
        CHAT["history"].append({"role": "user", "content": results})
    say("note", f"Stopped after {MAX_STEPS} steps; send a message to carry on.")


def _openai_turn(model, key, base):
    import openai
    client = openai.OpenAI(api_key=key, base_url=base or None, max_retries=3)
    tools = openai_tools()
    for _ in range(MAX_STEPS):
        if CHAT["stop"]:
            return
        r = client.chat.completions.create(model=model, tools=tools,
                                           messages=[{"role": "system", "content": system_prompt()}] + CHAT["history"])
        m = r.choices[0].message
        calls = m.tool_calls or []
        msg = {"role": "assistant", "content": m.content or ""}
        if calls:
            msg["tool_calls"] = [{"id": c.id, "type": "function",
                                  "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"}}
                                 for c in calls]
        CHAT["history"].append(msg)
        if (m.content or "").strip():
            say("assistant", m.content)
        if not calls:
            return
        for c in calls:
            try:
                inp = json.loads(c.function.arguments or "{}")
            except ValueError:
                inp = None
            if not isinstance(inp, dict):
                out = "error: the arguments were not valid JSON; send them again"
            else:
                say("tool", _label(c.function.name, inp))
                out = tool(c.function.name, inp)
            CHAT["history"].append({"role": "tool", "tool_call_id": c.id, "content": out})
    say("note", f"Stopped after {MAX_STEPS} steps; send a message to carry on.")


def _label(name, inp):
    if name == "run_hypnomix":
        return "hypnomix " + " ".join(shlex.quote(str(x)) for x in [inp.get("command", ""), *(inp.get("args") or [])])
    return name.replace("_", " ") + (f" ({inp.get('id') or Path(str(inp.get('dir') or inp.get('path') or '')).name})"
                                     if inp else "")


def _friendly(e, label):
    n = type(e).__name__
    if n == "AuthenticationError":
        return f"{label} refused the key. Check it in the settings above."
    if n == "PermissionDeniedError":
        return f"{label}: this key may not use that model."
    if n == "NotFoundError":
        return f"{label} doesn't know that model name. Use List models to pick one."
    if n == "RateLimitError":
        return f"{label} says too many requests (or no credit left). Wait a minute and try again."
    if n == "APIConnectionError":
        return f"Can't reach {label}." + (" Is Ollama running?" if "Ollama" in label else " Check the internet connection.")
    return f"{label}: {getattr(e, 'message', None) or e}"


def send(text):
    p, d, model, base, key = active()
    if not key:
        raise ValueError(f"add a {d['label']} key in the settings first")
    if not model:
        raise ValueError("choose a model in the settings (List models shows what your key can use)")
    with LOCK:
        if CHAT["busy"]:
            raise RuntimeError("the assistant is still working on the last message")
        if CHAT["provider"] not in (None, p):   # the two formats can't share one history: a new conversation
            CHAT["history"] = []
            say("note", f"Switched to {d['label']}: a new conversation starts here.")
        CHAT.update(provider=p, busy=True, stop=False, error="")
        CHAT["history"].append({"role": "user", "content": text})
        say("user", text)

    def go():
        try:
            if d["kind"] == "anthropic":
                _anthropic_turn(model, key)
            else:
                _openai_turn(model, key, base)
        except Exception as e:                    # shown in the chat, never as a crash
            CHAT["error"] = _friendly(e, d["label"])
            say("error", CHAT["error"])
        finally:
            with LOCK:
                CHAT["busy"] = False
                CHAT["pending"] = None
            _save()

    threading.Thread(target=go, daemon=True).start()


def answer(pid, ok):
    with LOCK:
        p = CHAT["pending"]
        if not p or p["id"] != pid:
            raise ValueError("that request is no longer waiting")
        p["ok"] = bool(ok)
        p["event"].set()


def stop():
    CHAT["stop"] = True
    p = CHAT.get("pending")
    if p:
        p["event"].set()


def reset():
    with LOCK:
        if CHAT["busy"]:
            raise RuntimeError("stop the assistant first")
        CHAT.update(id=uuid.uuid4().hex[:8], items=[], history=[], provider=None, pending=None, error="")
    _save()


def _store():
    from hypnomix.app import server as S
    return S.work() / "assistant" / "conversation.json"


def _save():
    try:
        f = _store()
        f.parent.mkdir(parents=True, exist_ok=True)
        with LOCK:
            f.write_text(json.dumps({k: CHAT[k] for k in ("id", "items", "history", "provider")}, default=str))
    except OSError:
        pass


def _load():
    try:
        d = json.loads(_store().read_text())
        CHAT.update({k: d[k] for k in ("id", "items", "history", "provider") if k in d})
    except (OSError, ValueError, KeyError):
        pass


def state(since=0):
    with LOCK:
        pend = CHAT["pending"]
        return dict(id=CHAT["id"], busy=CHAT["busy"], items=CHAT["items"][since:], total=len(CHAT["items"]),
                    pending=pend and {k: pend[k] for k in ("id", "command", "args")}, settings=settings_view())


_load()


# ---------------------------------------------------------------- the server's routes for this tab
def handle_get(path, q):
    if path == "/api/chat/state":
        return 200, state(int(q.get("since", 0)))
    if path == "/chat.js":
        return 200, (Path(__file__).with_name("chat.js")).read_bytes(), "text/javascript; charset=utf-8"
    return None


def handle_post(path, body):
    if path == "/api/chat/settings":
        return 200, update_settings(body)
    if path == "/api/chat/models":
        try:
            return 200, {"models": list_models()}
        except Exception as e:
            return 400, {"error": _friendly(e, active()[1]["label"]) if not isinstance(e, ValueError) else str(e)}
    if path == "/api/chat/send":
        send(str(body.get("text", "")).strip() or "(empty)")
        return 200, {"ok": True}
    if path == "/api/chat/answer":
        answer(body["id"], body.get("ok"))
        return 200, {"ok": True}
    if path == "/api/chat/stop":
        stop()
        return 200, {"ok": True}
    if path == "/api/chat/reset":
        reset()
        return 200, {"ok": True}
    return None
