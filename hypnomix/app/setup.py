"""Guided setup: what the app shows the first time it opens (and again from the Setup button).

It asks how you want to work, which DAW you use (Ableton Live, REAPER, HypnoMix DAW or something else; and
whether you'd like teacher mode: hypnomix/app/teacher.py, a guided course: a tour of HypnoMix in your DAW for people who
already engineer, or a 101 crash course for people new to audio), and sets that up. There is one app and one installer for
everyone. HypnoMix DAW (HypnoMix's own DAW) is an add-on: choosing it shows what it is, and only the
button "Add HypnoMix DAW" fetches it (hypnomix/app/engine_addon.py; the address and the SHA-256 come from the manifest
shipped inside the app, never from a request). Until the first archive is published it says so and the choice is remembered:
  app       just the app: you click through scan → review → apply. No AI, no account, free
  key       the app's Assistant with an AI service's key (Google Gemini's free tier, Claude, OpenRouter, OpenAI…)
  local     the Assistant with an open-source model on this computer (Ollama or LM Studio): free and private
  desktop   a desktop AI app runs HypnoMix for you (Claude Code in the Claude app or a terminal, Codex, Cursor…)

Then the connection to your DAW (Live: `hypnomix install`; REAPER: the bridge; only on a click), and for desktop AI apps a `hypnomix`
command and a folder with the agent guide and the Claude Code skills; then the optional extras (hypnomix/extras.py),
each installed only on a click. Keys are saved by the Assistant's own settings (~/.hypnomix/ai.json,
readable by you alone). The setup's own answers are in ~/.hypnomix/setup.json (the folder HYPNOMIX_HOME names, if set).

Costs are estimates from list prices for one typical song (scan to approved fixes, about 40 assistant steps:
~1.2 M input tokens, most of them repeated context, and ~20 k output tokens). The guide docs/guides/09-setup-and-ai.md
(the wiki article "Setting Up, and Choosing an AI") shows the same numbers: change both together."""
import io, json, os, shutil, sys, time
from contextlib import redirect_stdout
from pathlib import Path

from hypnomix.core import paths, prices

STATE = paths.HOME / "setup.json"       # the same home as the rest of HypnoMix: HYPNOMIX_HOME moves it (default ~/.hypnomix)
VERSION = 3                      # bump when the setup gains a step people who finished it should see

# one typical song through the Assistant: what the cost estimates assume
TYPICAL = dict(input=1_200_000, repeated=0.9, output=20_000)
PRICES_CHECKED = prices.CHECKED

# $ per million tokens: (input, output, repeated-context price or None when not counted). Claude's repeated
# context is the prompt cache (1-hour writes cost 2x input), as the Assistant uses it. The numbers come from the one
# table in hypnomix/core/prices.py (the Assistant's cost counter and the guide read the same one).
PRICES = {
    "claude-opus-5-5":   prices.for_setup("claude-opus-5-5"),
    "claude-sonnet-5-5": prices.for_setup("claude-sonnet-5-5"),
    "claude-haiku-5-5":  prices.for_setup("claude-haiku-5-5"),
    "gemini-flash":      None,       # filled by _gemini_row(): its price depends on the day (prices.GEMINI_FROM)
}


def _gemini_row():
    pi, po = prices.gemini_price()
    return dict(label=prices.GEMINI["label"], inp=pi, out=po, cached=None, write=None, note=prices.GEMINI["note"])


PRICES["gemini-flash"] = _gemini_row()


def song_cost(p, long=False):
    """What one typical song costs on model p. long=True: a very long session, whose requests pass the 100,000-token
    prompt size above which Haiku's price is higher (other models have one price, so it changes nothing for them)."""
    t = TYPICAL
    if p == "gemini-flash":                      # the price in force today, not the one on the day the app was started
        PRICES[p] = _gemini_row()
    d = prices.for_setup(p, long=True) if long and p in prices.TIERS else PRICES[p]
    if d["cached"] is None:
        return t["input"] / 1e6 * d["inp"] + t["output"] / 1e6 * d["out"]
    fresh = t["input"] * (1 - t["repeated"])
    return (fresh / 1e6 * d["write"] + t["input"] * t["repeated"] / 1e6 * d["cached"] + t["output"] / 1e6 * d["out"])


def money(x):
    return "under $0.01" if x < 0.01 else f"about ${x:.2f}" if x < 10 else f"about ${x:.0f}"


def modes():
    c = {k: money(song_cost(k)) for k in PRICES}
    longhaiku = money(song_cost("claude-haiku-5-5", long=True))
    return [
        dict(id="app", title="Just the app", tag="free · no account",
             cost="$0",
             what="You click through it yourself: scan a song, read each finding, hear the before and after, approve or skip, then apply. The Wiki tab teaches every step.",
             pros=["Free, nothing to sign up for", "Nothing leaves your computer", "Every tool works: the AI options only explain and drive them"],
             cons=["You read the reports and decide on your own", "No one to ask \"what does this mean?\" in plain words"]),
        dict(id="key", title="Assistant with an AI key", tag="recommended to start: Gemini free tier",
             cost=f"Gemini free tier $0 (daily limits) · Gemini paid {c['gemini-flash']} per song · Claude Haiku {c['claude-haiku-5-5']} ({longhaiku} on a very long song), Sonnet {c['claude-sonnet-5-5']}, Opus {c['claude-opus-5-5']} per song",
             what="The Assistant tab explains each finding, answers questions, runs the scans and checks for you, and asks before anything changes a set. You paste a key from the AI company; you pay them per use (or not at all on Gemini's free tier).",
             pros=["Works right inside the app, no other program", "Pay only for what you use; Gemini's free tier costs nothing",
                   "Gemini can also be the Listener: it hears a bounce and gives notes by ear (off until you turn it on)"],
             cons=["You need an account and a key with that company", "The text reports (not your audio, unless you allow a listen) go to that company",
                   "On Gemini's free tier Google may use what you send to improve its products; its paid tier doesn't",
                   "Costs add up on long sessions with the bigger models"]),
        dict(id="local", title="Assistant with a model on this computer", tag="free · private · slower",
             cost="$0 (your electricity)",
             what="An open-source model runs on your own computer through Ollama or LM Studio, and the Assistant talks to it. Nothing goes online.",
             pros=["Free and fully private, works offline", "No account, no key, no usage limits"],
             cons=["Needs a recent computer: 16 GB of memory for a good model (8 GB for a small one)", "Slower, and small models make more mistakes when running tools",
                   "A few GB download per model"]),
        dict(id="desktop", title="A desktop AI app drives HypnoMix", tag="most capable · subscription",
             cost="Claude Pro $20 / month (includes Claude Code); Max $100 or $200 / month for heavy use. Other agents: their own plans",
             what="Claude Code (in the Claude desktop app's Code tab, or in a terminal) or another agent like Codex or Cursor runs HypnoMix commands, reads the reports and works through a whole song with you. This sets up a `hypnomix` command and a folder with the instructions the agent reads.",
             pros=["The strongest option for long, many-step work: whole songs, batches, your own requests", "A flat monthly price instead of paying per use",
                   "Comes with the HypnoMix skills for Claude Code (the first-pass workflow) and works with every optional extra"],
             cons=["A monthly subscription, with usage limits", "Happens in a chat with the agent, beside the app rather than inside it",
                   "Each change still waits for your OK, so expect to read and approve as it goes"]),
    ]


PROVIDER_GUIDES = {
    "gemini": dict(label="Google Gemini", model="gemini-flash-latest", url="https://aistudio.google.com/apikey",
                   steps=["Open aistudio.google.com/apikey (Google AI Studio) and sign in with any Google account.",
                          "Click Create API key. If it asks for a project, let it create one.",
                          "Copy the key (it starts with AIza) and paste it below.",
                          "Free tier: no card needed, with daily limits. For higher limits, set up billing in AI Studio (the paid tier)."],
                   listen=True),
    "anthropic": dict(label="Claude (Anthropic)", model=prices.DEFAULT_CLAUDE_MODEL, url="https://console.anthropic.com/settings/keys",
                      steps=["Open console.anthropic.com and sign up or sign in.",
                             "Under Billing, add credit (prepaid; you can set a monthly limit).",
                             "Under Settings → API keys, click Create Key, copy it (it starts with sk-ant-) and paste it below.",
                             "A Claude Pro or Max subscription is separate and doesn't include API keys: for that, choose \"A desktop AI app\" instead."]),
    "openrouter": dict(label="OpenRouter", model="google/gemini-3.8-flash", url="https://openrouter.ai/keys",
                       steps=["Open openrouter.ai and sign in.", "Add credit under Credits.",
                              "Under Keys, create a key, copy it (it starts with sk-or-) and paste it below.",
                              "One key reaches models from many companies; prices are on each model's page."], listen=True),
    "openai": dict(label="OpenAI", model="", url="https://platform.openai.com/api-keys",
                   steps=["Open platform.openai.com, sign in and add credit under Billing.",
                          "Under API keys, create a key, copy it (it starts with sk-) and paste it below."]),
}

LOCAL_GUIDES = {
    "ollama": dict(label="Ollama", url="https://ollama.com/download", model="gpt-oss:20b", base_url="http://localhost:11434/v1",
                   steps=["Download Ollama from ollama.com/download and open it (it runs in the menu bar / system tray).",
                          "Get a model built for tool use. In Terminal (Mac) or PowerShell (Windows): ollama pull gpt-oss:20b  (about 14 GB, needs 16 GB of memory; with 8 GB use qwen3:8b instead and change the model name below).",
                          "Give it room to think: in Ollama's Settings, drag the context length to 64k (the Assistant reads long reports).",
                          "Leave Ollama running, then click Test below."]),
    "lmstudio": dict(label="LM Studio", url="https://lmstudio.ai", model="", base_url="http://localhost:1234/v1",
                     steps=["Download LM Studio from lmstudio.ai and open it.",
                            "Search for and download a model with tool use (gpt-oss 20B, or Qwen3 8B with 8 GB of memory), then load it with a context length of 64k.",
                            "Open the Developer tab and switch Start server on (port 1234), then click Test below."]),
}


def load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(d):
    from hypnomix.core.paths import write_private       # setup.json: mode 0600, in a 0700 folder
    write_private(STATE, json.dumps(d, indent=1))


def bundled():
    """Running from an installer (the Mac app, the Windows setup), not a source checkout."""
    from hypnomix.extras import bundled as b
    return b()


def _bin_dir():
    exe = Path(sys.executable).resolve()
    for d in (exe.parents[2] / "bin", exe.parent.parent / "bin"):      # Mac: Resources/bin; Windows: <app>/bin
        if (d / "ffmpeg").exists() or (d / "ffmpeg.exe").exists():
            return d
    return None


def live_status():
    from hypnomix import install as I
    dest = I.remote_scripts_dir() / "AbletonOSC"
    try:
        ok = dest.exists() and "volume_string" in (dest / "abletonosc/track.py").read_text(errors="ignore", encoding="utf-8")
    except OSError:
        ok = False
    lib = I.remote_scripts_dir().parent.parent           # .../Ableton
    try:
        teach = ok and "load_browser_item" in (dest / "abletonosc/track.py").read_text(errors="ignore", encoding="utf-8")
    except OSError:
        teach = False
    return dict(installed=ok, where=str(dest), ableton=lib.exists(), teach_ready=teach)


DAWS = [
    dict(id="live", title="Ableton Live", note="the most depth: HypnoMix reads, fixes and drives Live 11 and 12"),
    dict(id="reaper", title="REAPER", note="reads and writes projects, and drives the open REAPER through its bridge"),
    dict(id="hypnomix", title="HypnoMix DAW", note="HypnoMix's own DAW, an optional add-on (Extras says whether it can be added yet)"),
    dict(id="other", title="Something else", note="any other DAW: export your tracks and scan the folder"),
]


DAW_IDS = {d["id"] for d in DAWS} | {"ardour"}       # "ardour" is no longer asked, but a choice saved earlier keeps working


def _daw_id(v):
    """The DAW id a request names, "" when it is not one of the ids. A list or a number is a plain 400 (the wrong kind of
    field), as it was before DAW_IDS became a set: testing it with `in` raised TypeError out of this file, which is a bug."""
    if v is None:
        return ""
    if not isinstance(v, str):
        from hypnomix.app.server import WRONG_KIND
        raise ValueError(WRONG_KIND)
    return v if v in DAW_IDS else ""


def reaper_status():
    from hypnomix.reaper.client import Reaper, reaper_executable
    try:
        alive = Reaper().alive()
    except Exception:
        alive = False
    return dict(found=bool(reaper_executable()), running=alive)


def setup_reaper():
    from hypnomix.reaper.client import Reaper
    Reaper().start()
    return dict(reaper=reaper_status())


def shim_path():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Microsoft" / "WindowsApps" / "hypnomix.cmd"
    return Path.home() / ".local" / "bin" / "hypnomix"


def agent_dir():
    from hypnomix.app.server import work
    return Path(work()) / "AI agent"


def shim_is_ours(shim):
    """True for a command this setup made earlier: a plain file (never a link to someone else's) that carries setup's marker line.
    Only that kind is ever made again; anything else at that path is the person's own and is left as it is."""
    try:
        # the marker line setup writes, not just "hypnomix.cli": a pip console script or a hand-written wrapper holds that text too
        return not shim.is_symlink() and shim.is_file() and "made by the hypnomix app's setup" in shim.read_text(errors="ignore", encoding="utf-8")[:2000]
    except OSError:
        return False


def cli_status():
    found = shutil.which("hypnomix")
    shim = shim_path()
    on_path = str(shim.parent) in os.environ.get("PATH", "").split(os.pathsep)
    sk = agent_dir() / ".claude" / "skills"
    return dict(command=str(shim) if shim_is_ours(shim) else found or (str(shim) if shim.exists() else ""), shim=str(shim), shim_exists=shim.exists(),
                on_path=bool(found) or on_path, agent_dir=str(agent_dir()), agent_ready=(agent_dir() / "AGENTS.md").exists(),
                skills=sorted(p.name for p in sk.iterdir() if (p / "SKILL.md").exists()) if sk.is_dir() else [])


def windows_shim_text(py, bin_dir):
    """The text of the Windows command: lines end in CR LF. A command prompt reads a batch file in its own code page, so a
    folder name with letters outside ASCII (an accent, a Cyrillic or CJK name) is run under UTF-8 (code page 65001) and
    the prompt's code page is put back afterwards, exit code kept. An all-ASCII command (the usual case) changes nothing."""
    body = [f'set "PATH={bin_dir};%PATH%"'] if bin_dir else []
    body.append(f'"{py}" -m hypnomix.cli %*')
    head = ["@echo off", "REM made by the hypnomix app's setup"]
    if all(ord(c) < 128 for c in "".join(body)):
        lines = head + body
    else:
        lines = (head + ["for /f \"tokens=2 delims=:\" %%a in ('chcp') do set \"HYPNOMIX_CP=%%a\"", "chcp 65001 >nul"] + body +
                 ["set \"HYPNOMIX_RC=%errorlevel%\"", "chcp %HYPNOMIX_CP% >nul", "exit /b %HYPNOMIX_RC%"])
    return "\r\n".join(lines) + "\r\n"


def make_cli():
    """A `hypnomix` command that runs this app's own Python, and a folder an AI agent can be opened in."""
    py = Path(sys.executable).absolute()          # not resolved: a venv's python is a link to a Python without HypnoMix
    if sys.platform == "win32":
        py = py.with_name("python.exe") if py.name.lower() == "pythonw.exe" else py
    shim = shim_path()
    note = ""
    if (shim.exists() or shim.is_symlink()) and not shim_is_ours(shim):
        # a command that is not ours (pipx and pip --user leave a link here): never written through, never moved
        note = (f"A command already exists at {shim} and this setup did not make it, so it was left exactly as it is. "
                "The AI agent folder is ready; the agent will use that command.")
    else:
        shim.parent.mkdir(parents=True, exist_ok=True)
        b = _bin_dir()
        if sys.platform == "win32":
            shim.write_bytes(windows_shim_text(py, b).encode("utf-8"))      # bytes: a text-mode write would turn each CR LF into CR CR LF
        else:
            text = "#!/bin/sh\n# made by the hypnomix app's setup: runs the installed app's own hypnomix\n" + \
                   (f'PATH="{b}:$PATH"; export PATH\n' if b else "") + f'exec "{py}" -m hypnomix.cli "$@"\n'
            shim.write_text(text, encoding="utf-8")
            shim.chmod(0o755)
    d = agent_dir()
    d.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).resolve()
    for name in ("AGENTS.md", "GUIDE.md"):
        for src in (here.parents[2] / name, here.with_name("wiki") / "docs" / name):
            if src.exists():
                shutil.copyfile(src, d / name)
                break
    skills, agents = copy_skills(d, here)
    cmd = str(shim)
    (d / "CLAUDE.md").write_text(
        "# HypnoMix (installed app)\n\n"
        "This folder is for an AI agent (Claude Code, Codex, Cursor…) working with HypnoMix, a mixing and mastering\n"
        "assistant for Ableton Live, REAPER and HypnoMix DAW. Read AGENTS.md first: the loop every job follows, the safety rules\n"
        "and the command map. GUIDE.md is the user's guide.\n\n"
        f"Run HypnoMix as `hypnomix <command>` (or by its full path, `{cmd}`). Start with `hypnomix doctor`.\n"
        "Every change that writes a set needs the person's OK first; HypnoMix never overwrites the original.\n"
        "The songs' scans are in the folder above this one.\n"
        + (f"\nClaude Code skills (in .claude/skills): {', '.join(skills)}. For a whole new song, use first-pass.\n" if skills else "")
        + (f"Subagents (in .claude/agents): {', '.join(agents)}.\n" if agents else ""), encoding="utf-8")
    shutil.copyfile(d / "CLAUDE.md", d / "README.txt")
    return dict(cli_status(), note=note)


def _first(*dirs):
    return next((x for x in dirs if x.is_dir()), None)


def copy_skills(d, here):
    """The repository's Claude Code skills and subagents, into the folder's .claude/ (where Claude Code finds them).
    They ship inside the app (the Wiki shows them), from the source checkout or the installed package."""
    skills, agents = [], []
    src = _first(here.parents[2] / "skills", here.with_name("wiki") / "skills")
    if src:
        dest = d / ".claude" / "skills"
        for s in sorted(p for p in src.iterdir() if (p / "SKILL.md").exists()):
            shutil.rmtree(dest / s.name, ignore_errors=True)
            shutil.copytree(s, dest / s.name)
            skills.append(s.name)
    src = _first(here.parents[2] / "agents", here.with_name("wiki") / "agents")
    if src:
        dest = d / ".claude" / "agents"
        dest.mkdir(parents=True, exist_ok=True)
        for a in sorted(src.glob("*.md")):
            shutil.copyfile(a, dest / a.name)
            agents.append(a.stem)
    return skills, agents


LEVELS = ("tour", "101", "az")                 # the teacher-mode courses (hypnomix/app/teacher.py LEVELS)


def _level(s):
    lv = s.get("teach_level") or ("101" if s.get("teach") else "")
    return lv if lv in LEVELS else "101" if lv else ""          # a level this version doesn't know falls back to 101


def _set_level(s, lv):
    s["teach_level"] = lv if lv in LEVELS else ""
    s["teach"] = bool(s["teach_level"])


def is_done():
    """True once the guided setup was finished or skipped (the same test as state_view's "done"). An app opened in DAW mode
    shows the DAW view only after that, so a first launch shows the setup instead of skipping past it."""
    s = load()
    return bool(s.get("done")) and s.get("version", 0) >= VERSION


def state_view():
    from hypnomix.app import chat as CH
    from hypnomix import extras as X
    from hypnomix.app import engine_addon as EA
    s = load()
    return dict(done=bool(s.get("done")) and s.get("version", 0) >= VERSION, mode=s.get("mode", ""),
                daw=s.get("daw", ""), teach_level=_level(s), daws=DAWS, engine=EA.state(),
                reaper=reaper_status(),
                platform="windows" if sys.platform == "win32" else "mac" if sys.platform == "darwin" else "linux",
                bundled=bundled(), modes=modes(), providers=PROVIDER_GUIDES, local=LOCAL_GUIDES,
                typical=TYPICAL, prices_checked=PRICES_CHECKED,
                settings=CH.settings_view(), live=live_status(), cli=cli_status(), extras=X.status())


def connect(body):
    """Save the chosen provider (and key) through the Assistant's settings, then try it: list its models."""
    from hypnomix.app import chat as CH
    p = body.get("provider")
    upd = dict(provider=p)
    if body.get("key"):
        upd["key"] = body["key"]
    if body.get("model") is not None:
        upd["model"] = body["model"]
    if body.get("base_url"):
        upd["base_url"] = body["base_url"]
    if "listen_provider" in body:
        upd["listen_provider"] = body["listen_provider"]
    CH.update_settings(upd)
    label = dict(ollama="Ollama", custom="LM Studio").get(p) or CH.PROVIDERS.get(p, {}).get("label", p)
    if not CH.active()[4]:
        return 400, dict(ok=False, error=f"Paste your {label} key above first.", settings=CH.settings_view())
    try:
        models = CH.list_models()
    except Exception as e:
        msg = str(e) if isinstance(e, ValueError) else CH._friendly(e, label)
        # the same scrubbing the Assistant uses, plus the key that was just typed: a provider that answers "Incorrect API
        # key provided: <the key>" must not have its words (or the key) come back to the page unmasked
        keys = set(CH.saved_keys())
        typed = str(body.get("key") or "").strip()
        if len(typed) >= 6:
            keys.add(typed)
        msg = CH.scrub(msg, sorted(keys, key=len, reverse=True))
        return 400, dict(ok=False, error=msg, settings=CH.settings_view())
    chosen = ""
    if models and not CH.active()[2] and (p == "ollama" or CH.local_address(CH.active()[3])):
        # a model on this computer with no name typed: the first one it lists is used (Send needs a name), and said
        chosen = models[0]
        CH.update_settings(dict(provider=p, model=chosen))
    return 200, dict(ok=True, models=models[:200], count=len(models), model=chosen, settings=CH.settings_view())


def setup_live():
    from hypnomix import install as I
    out = io.StringIO()
    with redirect_stdout(out):
        I.install([])
    log = out.getvalue().split("\n2. ")[0].strip() + "\n"       # step 1 only (the script): the CLI's other steps are not for this page
    return dict(log=log, live=live_status())


def engine_post(what, body):
    """Add or remove HypnoMix DAW, on the page's click. The request carries nothing: the address and the SHA-256 are the
    manifest's (shipped inside the app), and the folder is the HypnoMix home's, so a request that names any is refused."""
    from hypnomix.app import engine_addon as EA
    if body:
        return 400, dict(error="this request takes nothing: the address and fingerprint come from the app itself, never from a request",
                         engine=EA.state())
    try:
        if what == "install":
            return 200, EA.start_install()
        return 200, EA.remove()
    except EA.AddonError as e:
        return 400, dict(error=str(e), engine=EA.state())


def handle_get(path, q):
    if path == "/api/setup/state":
        return 200, state_view()
    if path == "/api/setup/extras":
        from hypnomix import extras as X
        return 200, X.status()
    if path == "/api/setup/engine":                   # HypnoMix DAW: what is added, what could be, the job's progress
        from hypnomix.app import engine_addon as EA
        return 200, EA.state()
    if path == "/setup.js":
        return 200, Path(__file__).with_name("setup.js").read_bytes(), "text/javascript; charset=utf-8"
    return None


def handle_post(path, body):
    if path == "/api/setup/connect":
        return connect(body)
    if path == "/api/setup/live":
        return 200, setup_live()
    if path == "/api/setup/reaper":
        from hypnomix.reaper.client import ReaperError
        try:
            return 200, setup_reaper()
        except ReaperError as e:
            return 400, dict(error=str(e), reaper=reaper_status())
    if path == "/api/setup/daw":                      # saved at once, so the Wiki and the Teacher tab follow it
        s = load()
        if "daw" in body:
            s["daw"] = _daw_id(body["daw"])
        if "teach_level" in body:
            _set_level(s, body["teach_level"])
        save(s)
        return 200, dict(daw=s.get("daw", ""), teach_level=_level(s))
    if path in ("/api/setup/engine/install", "/api/setup/engine/remove"):
        return engine_post(path.rsplit("/", 1)[1], body)
    if path == "/api/setup/cli":
        return 200, make_cli()
    if path == "/api/setup/extra":
        from hypnomix import extras as X
        try:
            return 200, X.install(str(body.get("name", "")))
        except ValueError as e:
            return 400, dict(error=str(e), **X.status())
    if path == "/api/setup/finish":
        s = load()
        s.update(done=bool(body.get("done", True)), mode=str(body.get("mode") or s.get("mode") or ""), version=VERSION,
                 at=time.strftime("%Y-%m-%d %H:%M"))
        if _daw_id(body.get("daw")):
            s["daw"] = body["daw"]
        if "teach_level" in body:
            _set_level(s, body["teach_level"])
        save(s)
        return 200, state_view()
    return None
