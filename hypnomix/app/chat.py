"""The Assistant tab: talk to an AI about your song, and let it run hypnomix for you.

Bring your own key from any provider:
  Claude (Anthropic)                 the Anthropic SDK
  OpenAI, Google Gemini, OpenRouter,  the OpenAI SDK, each at its own address (these all speak the same chat format)
  Groq, Mistral, Ollama on this computer (free, no key), or any other service that speaks it

The key is kept on this computer only (~/.hypnomix/ai.json, readable by you alone) and goes only to the provider
you chose. Your audio stays on the computer: the assistant sees hypnomix's text reports, not the songs. The one
exception is Listening (off until you choose Google Gemini or OpenRouter for it): then the assistant may ask to
send a reduced mono copy of one song to that service for notes by ear, and each listen waits for your click.

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
# Claude list prices, $ per million tokens: (input, output, cache read). Writing to the 1-hour cache costs 2x input.
# Other providers: tokens are counted, the cost is theirs to quote (see their pricing page).
CLAUDE_PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20), "claude-sonnet-5-5": (2.0, 10.0, 0.10), "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-fable-5-2": (8.0, 40.0, 0.20), "claude-fable-5-1": (10.0, 50.0, 1.0), "claude-fable-5": (10.0, 50.0, 1.0),
    "claude-opus-5": (5.0, 25.0, 0.5), "claude-opus-4-8": (5.0, 25.0, 0.5), "claude-opus-4-7": (5.0, 25.0, 0.5),
    "claude-opus-4-6": (5.0, 25.0, 0.5), "claude-sonnet-5": (2.0, 10.0, 0.2), "claude-sonnet-4-6": (3.0, 15.0, 0.3),
    "claude-haiku-4-5": (1.0, 5.0, 0.1),
}
CACHE = {"type": "ephemeral", "ttl": "1h"}     # people listen and A/B between messages: 5 minutes is too short
REVIEW_PAGE = 40                               # findings per read_review page
CLAUDE_FALLBACKS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-fable-5-2"}

LOCK = threading.RLock()
def new_usage():
    return {"calls": 0, "input": 0, "cache_write": 0, "cache_read": 0, "output": 0, "cost": 0.0, "priced": True}


CHAT = {"id": uuid.uuid4().hex[:8], "items": [], "history": [], "provider": None, "busy": False, "pending": None,
        "stop": False, "error": "", "usage": new_usage()}


def count(model, provider, inp=0, out=0, cw=0, cr=0):
    """Add one call's tokens to the conversation's total, and its cost where the price is known."""
    u = CHAT["usage"]
    u["calls"] += 1
    u["input"] += inp; u["output"] += out; u["cache_write"] += cw; u["cache_read"] += cr
    if provider == "ollama":
        return
    price = CLAUDE_PRICES.get(model) if provider == "anthropic" else None
    if price is None:
        u["priced"] = False
        return
    pi, po, pr = price
    u["cost"] += (inp * pi + cw * pi * 2.0 + cr * pr + out * po) / 1e6


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
    from hypnomix.ears import critique as L
    ls = c.get("listen") or {}
    lp = ls.get("provider") if ls.get("provider") in L.LISTENERS else ""
    opts = []
    for k, d in L.LISTENERS.items():
        saved = (c.get("keys") or {}).get(k) or ""
        env = bool(os.environ.get(d["env"]))
        opts.append(dict(id=k, label=d["label"], model=(ls.get("models") or {}).get(k) or d["model"], keys_at=d["keys_at"],
                         has_key=bool(saved or env), picks=[dict(id=m, note=n) for m, n in d["picks"]],
                         key_hint=("…" + saved[-4:]) if len(saved) >= 8 else ("saved" if saved else
                                                                            f"from {d['env']}" if env else "")))
    listen = dict(provider=lp, options=opts)
    return dict(provider=p, providers=out, listen=listen)


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
    if "listen_provider" in body:                   # '' switches Listening off
        from hypnomix.ears import critique as L
        lp = str(body["listen_provider"] or "")
        if lp and lp not in L.LISTENERS:
            raise ValueError("listening works with Google Gemini or OpenRouter")
        c.setdefault("listen", {})["provider"] = lp
        if lp and body.get("listen_model") is not None:
            c["listen"].setdefault("models", {})[lp] = str(body["listen_model"]).strip()
        if lp and body.get("listen_key"):            # the listener's own key: separate from the chat model's
            c.setdefault("keys", {})[lp] = str(body["listen_key"]).strip()
        if lp and body.get("listen_forget"):
            c.setdefault("keys", {}).pop(lp, None)
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
         description=(f"The findings of one scanned song, {REVIEW_PAGE} per page (id, tool, track, where, problem, fix, "
                      "the person's decision), with how many there are of each tool. Page 1 first; read the next pages "
                      "only when you need them. tool narrows it to one tool (e.g. 'edges'); '' for all."),
         params={"dir": ("string", "the scan folder from list_songs"), "page": ("integer", "1 for the first page"),
                 "tool": ("string", "only this tool's findings, or '' for all")}),
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
    dict(name="listen",
         description=("Have a cloud listening model (Gemini) hear one bounced song and give a producer's notes by ear, "
                      "with timestamps: arrangement, energy, balance, clarity, low-end feel, performance. It hears a "
                      "reduced MONO copy, so it can't judge stereo width, air above 8 kHz or exact loudness: those come "
                      "from hypnomix's own measurements. The person must click to send the audio (it shows the length "
                      "and rough cost); only works when Listening is switched on in the settings. Pass the song's scan "
                      "folder so the review goes along as text and the listener can confirm or question it."),
         params={"audio": ("string", "full path of the bounced song (.wav, .mp3, .aif, .flac)"),
                 "question": ("string", "what to listen for, in the person's words, or '' for a full pass"),
                 "dir": ("string", "the song's scan folder from list_songs, or ''")}),
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


def ask_ok(command, args, text=None, what="write"):
    """Show the command (or, for a listen, what will be sent) in the chat and wait for the person's click."""
    pid = uuid.uuid4().hex[:8]
    ev = threading.Event()
    with LOCK:
        CHAT["pending"] = dict(id=pid, command=command, args=[str(x) for x in args], event=ev, ok=None, what=what)
        CHAT["items"].append(dict(kind="ask", id=pid, what=what,
                                  text=text or "hypnomix " + " ".join(shlex.quote(str(x)) for x in [command, *args])))
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
            allf = p.get("findings", [])
            counts = {}
            for f in allf:
                counts[f.get("tool")] = counts.get(f.get("tool"), 0) + 1
            want = str(inp.get("tool") or "").strip()
            sel = [f for f in allf if not want or f.get("tool") == want]
            pages = max(1, -(-len(sel) // REVIEW_PAGE))
            page = min(max(1, int(inp.get("page") or 1)), pages)
            dec = p.get("decisions", {})
            rows = []
            for f in sel[(page - 1) * REVIEW_PAGE:page * REVIEW_PAGE]:
                r = {k: f.get(k) for k in keep if f.get(k) is not None}
                for k in ("problem", "fix"):                 # long texts trimmed: the page stays readable
                    if isinstance(r.get(k), str) and len(r[k]) > 600:
                        r[k] = r[k][:600] + "…"
                if r["id"] in dec:
                    r["decision"] = dec[r["id"]]
                rows.append(r)
            return json.dumps(dict(dir=str(d), total=len(allf), shown=f"{want or 'all'}: page {page} of {pages}",
                                   per_tool=counts, findings=rows), default=str)
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
        if name == "listen":
            return listen_tool(inp)
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


def listen_tool(inp):
    """One listen: switched on, a real song, the person's click, then the notes (also saved next to the scan)."""
    from hypnomix.ears import critique as L
    from hypnomix.app import server as S
    c = load_conf()
    lp = (c.get("listen") or {}).get("provider") or ""
    if lp not in L.LISTENERS:
        return ("Listening is off. Tell the person they can set up a Listener in the Assistant tab (Set up a listener: "
                "Google Gemini or OpenRouter, with that service's key); until then, work from hypnomix's measurements.")
    f = Path(str(inp.get("audio") or "")).expanduser()
    if not f.is_file() or f.suffix.lower() not in (".wav", ".mp3", ".aif", ".aiff", ".flac", ".m4a", ".ogg"):
        return "that is not an audio file on this computer: ask the person to attach the bounce (Attach audio…)"
    provider, _, model, key = L.listener(lp)
    if not key:
        return f"Listening is set to {L.LISTENERS[provider]['label']} but no key is saved for it: ask the person to add one."
    est = L.estimate(f, provider, model)
    cost = f", about ${est['cost']:.3f}" if est["cost"] is not None else ""
    q = str(inp.get("question") or "").strip()
    text = (f"Send {f.name} ({est['seconds'] / 60:.1f} min, reduced mono copy) to {L.LISTENERS[provider]['label']} "
            f"({model}) to listen{': ' + q if q else ''}. About {est['tokens']:,} tokens{cost}.")
    if not ask_ok("listen", [str(f)], text=text, what="listen"):
        return "The person chose not to send the audio. Carry on from hypnomix's measurements, or ask what they'd like."
    scan = None
    if inp.get("dir"):
        try:
            scan = S.scan_dir(inp["dir"])
        except (KeyError, ValueError, OSError):
            scan = None
    say("tool", f"listening to {f.name}…")
    try:
        notes, usage = L.listen(f, q, L.context(scan=scan), provider, model)
    except ValueError as e:
        return f"error: {e}"
    except Exception as e:
        return "error: " + _friendly(e, L.LISTENERS[provider]["label"])
    u = CHAT["usage"]
    if usage.get("cost"):
        u["cost"] += float(usage["cost"])
    else:
        u["priced"] = False
    if scan:
        try:
            (Path(scan) / f"listen - {f.stem}.md").write_text(
                f"# Notes by ear: {f.name}\n\n{L.LISTENERS[provider]['label']} · {model}"
                f"{' · question: ' + q if q else ''}\n\n{notes}\n")
        except OSError:
            pass
    return (f"[{L.LISTENERS[provider]['label']} {model} listened to {f.name}; it heard mono, reduced audio]\n\n" + notes)[:20000]


def system_prompt():
    guide = ""
    for f in (Path(__file__).resolve().parents[2] / "AGENTS.md",          # a git checkout
              Path(__file__).with_name("wiki") / "docs" / "AGENTS.md"):    # installed (pip, the installers)
        if f.exists():
            guide = f.read_text()
            break
    return ("You are the assistant inside the hypnomix app, a free mixing and mastering toolkit for people who record "
            "real instruments and voices. You help one musician with their own songs, in plain words, briefly.\n\n"
            "How you work here: you cannot type in a terminal; you act only through the tools you are given. "
            "run_hypnomix runs any hypnomix command (the reference below lists them). The usual path for a song is: "
            "scan it (read-only), read the review, explain each finding and what its fix would do, record the "
            "person's decisions (fix DIR --decide ID=approve,ID=skip,... several in ONE call, only what they actually said), "
            "then apply only "
            "what they approved into a NEW set (fix DIR --approved --out \"<Song> (fixed).als\" next to the original). "
            "Rules: never overwrite a set; ask them to save and close the set in Live before anything writes; keep the "
            "human feel (gentle, partial edits, never quantise or hard-tune); never apply something they did not "
            "approve; when unsure what a track is or what they want, ask. Commands that write wait for the person "
            "to click Run it: say what the command will do before you run it. Report what changed and what to A/B. "
            "Paths: they can attach a set or folder with the buttons under the chat box, which pastes its path. "
            "Each step you take costs the person money on their AI plan: read the review a page at a time, group "
            "similar findings when you explain them, and record decisions in batches. "
            "listen lets a cloud model hear a bounce for notes by ear (when the person switched Listening on): use it "
            "when they ask how the song sounds or feels, or to check a finding by ear; weigh its notes against "
            "hypnomix's measurements, which win on numbers, and never turn its notes into fixes they didn't approve."
            + _teacher_note() +
            "\n\nReference (written for terminal agents; here, use the tools instead of a shell):\n\n" + guide)


def _teacher_note():
    try:
        from hypnomix.app import teacher
        return teacher.assistant_note()
    except Exception:
        return ""


# ---------------------------------------------------------------- the conversation
def say(kind, text, **k):
    with LOCK:
        CHAT["items"].append(dict(kind=kind, text=text, t=time.time(), **k))


def _anthropic_turn(model, key):
    import anthropic
    client = anthropic.Anthropic(api_key=key, max_retries=3)
    tools = anthropic_tools()
    system = [{"type": "text", "text": system_prompt(), "cache_control": CACHE}]
    for _ in range(MAX_STEPS):
        if CHAT["stop"]:
            return
        # cache_control at the top caches the whole conversation so far: each call re-reads it at the cache price
        params = dict(model=model, max_tokens=16000, system=system, tools=tools, messages=CHAT["history"],
                      cache_control=CACHE)
        if model in CLAUDE_FALLBACKS:     # on a policy decline, the API retries on the model it picks for that case
            r = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
        else:
            r = client.messages.create(**params)
        u = r.usage
        count(model, "anthropic", u.input_tokens or 0, u.output_tokens or 0,
              getattr(u, "cache_creation_input_tokens", 0) or 0, getattr(u, "cache_read_input_tokens", 0) or 0)
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
        u = getattr(r, "usage", None)
        if u is not None:
            cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
            count(model, CHAT["provider"], (u.prompt_tokens or 0) - cached, u.completion_tokens or 0, 0, cached)
        m = r.choices[0].message
        calls = m.tool_calls or []
        msg = {"role": "assistant", "content": m.content or ""}
        # what a provider adds beyond the standard fields goes back as it came: Gemini refuses the next call without
        # each tool call's thought signature (extra_content), OpenRouter wants its reasoning_details back
        extra = getattr(m, "model_extra", None) or {}
        if extra.get("reasoning_details"):
            msg["reasoning_details"] = extra["reasoning_details"]
        if calls:
            msg["tool_calls"] = []
            for c in calls:
                tc = {"id": c.id, "type": "function",
                      "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"}}
                if (getattr(c, "model_extra", None) or {}).get("extra_content"):
                    tc["extra_content"] = c.model_extra["extra_content"]
                msg["tool_calls"].append(tc)
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
            CHAT["usage"] = new_usage()
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
        CHAT.update(id=uuid.uuid4().hex[:8], items=[], history=[], provider=None, pending=None, error="", usage=new_usage())
    _save()


def _store():
    from hypnomix.app import server as S
    return S.work() / "assistant" / "conversation.json"


def _save():
    try:
        f = _store()
        f.parent.mkdir(parents=True, exist_ok=True)
        with LOCK:
            f.write_text(json.dumps({k: CHAT[k] for k in ("id", "items", "history", "provider", "usage")}, default=str))
    except OSError:
        pass


def _load():
    try:
        d = json.loads(_store().read_text())
        CHAT.update({k: d[k] for k in ("id", "items", "history", "provider", "usage") if k in d})
    except (OSError, ValueError, KeyError):
        pass


def state(since=0):
    with LOCK:
        pend = CHAT["pending"]
        return dict(id=CHAT["id"], busy=CHAT["busy"], items=CHAT["items"][since:], total=len(CHAT["items"]),
                    pending=pend and {k: pend.get(k) for k in ("id", "command", "args", "what")}, settings=settings_view(),
                    usage=dict(CHAT["usage"]))


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
    if path == "/api/chat/listen-models":
        from hypnomix.ears import critique as L
        try:
            lp = (load_conf().get("listen") or {}).get("provider") or ""
            if lp not in L.LISTENERS:
                raise ValueError("choose Google Gemini or OpenRouter as the listener first")
            return 200, {"models": L.audio_models(lp)}
        except ValueError as e:
            return 400, {"error": str(e)}
        except Exception as e:
            return 400, {"error": f"couldn't list the models: {getattr(e, 'reason', None) or e}"}
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
