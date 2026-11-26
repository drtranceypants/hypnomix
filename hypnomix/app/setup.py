"""Guided setup: what the app shows the first time it opens (and again from the Setup button).

It asks how you want to work, which DAW you use (and whether you'd like teacher mode: hypnomix/app/teacher.py, a
guided course: a tour of hypnomix in your DAW for people who already engineer, or a 101 crash course for people new to
audio), and sets that up:
  app       just the app: you click through scan → review → apply. No AI, no account, free
  key       the app's Assistant with an AI service's key (Google Gemini's free tier, Claude, OpenRouter, OpenAI…)
  local     the Assistant with an open-source model on this computer (Ollama or LM Studio): free and private
  desktop   a desktop AI app runs hypnomix for you (Claude Code in the Claude app or a terminal, Codex, Cursor…)

Then the connection to your DAW (Live: `hypnomix install`; REAPER: the bridge; only on a click), and for desktop AI apps a `hypnomix`
command and a folder with the agent guide and the Claude Code skills; then the optional extras (hypnomix/extras.py),
each installed only on a click. Keys are saved by the Assistant's own settings (~/.hypnomix/ai.json,
readable by you alone). The setup's own answers are in ~/.hypnomix/setup.json.

Costs are estimates from list prices for one typical song (scan to approved fixes, about 40 assistant steps:
~1.2 M input tokens, most of them repeated context, and ~20 k output tokens). The guide docs/guides/09-setup-and-ai.md
(the wiki article "Setting Up, and Choosing an AI") shows the same numbers: change both together."""
import io, json, os, shutil, sys, time
from contextlib import redirect_stdout
from pathlib import Path

STATE = Path("~/.hypnomix/setup.json").expanduser()
VERSION = 3                      # bump when the setup gains a step people who finished it should see

# one typical song through the Assistant: what the cost estimates assume
TYPICAL = dict(input=1_200_000, repeated=0.9, output=20_000)
PRICES_CHECKED = "2026-11-25"

# $ per million tokens: (input, output, repeated-context price or None when not counted). Claude's repeated
# context is the prompt cache (1-hour writes cost 2x input), as the Assistant uses it.
PRICES = {
    "claude-opus-5-5":   dict(label="Claude Opus 5.5",   inp=4.00, out=20.00, cached=0.20, write=8.00),
    "claude-sonnet-5-5": dict(label="Claude Sonnet 5.5", inp=2.00, out=10.00, cached=0.10, write=4.00),
    "claude-haiku-5-5":  dict(label="Claude Haiku 5.5",  inp=0.10, out=0.50,  cached=0.01, write=0.20),
    "gemini-flash":      dict(label="Gemini Flash (paid tier)", inp=0.75, out=3.75, cached=None, write=None,
                              note="introductory price through 2026-12-31; $1.50 / $7.50 from 2027-01-01"),
}


def song_cost(p):
    t, d = TYPICAL, PRICES[p]
    if d["cached"] is None:
        return t["input"] / 1e6 * d["inp"] + t["output"] / 1e6 * d["out"]
    fresh = t["input"] * (1 - t["repeated"])
    return (fresh / 1e6 * d["write"] + t["input"] * t["repeated"] / 1e6 * d["cached"] + t["output"] / 1e6 * d["out"])


def money(x):
    return "under $0.01" if x < 0.01 else f"about ${x:.2f}" if x < 10 else f"about ${x:.0f}"


def modes():
    c = {k: money(song_cost(k)) for k in PRICES}
    return [
        dict(id="app", title="Just the app", tag="free · no account",
             cost="$0",
             what="You click through it yourself: scan a song, read each finding, hear the before and after, approve or skip, then apply. The Wiki tab teaches every step.",
             pros=["Free, nothing to sign up for", "Nothing leaves your computer", "Every tool works: the AI options only explain and drive them"],
             cons=["You read the reports and decide on your own", "No one to ask \"what does this mean?\" in plain words"]),
        dict(id="key", title="Assistant with an AI key", tag="recommended to start: Gemini free tier",
             cost=f"Gemini free tier $0 (daily limits) · Gemini paid {c['gemini-flash']} per song · Claude Haiku {c['claude-haiku-5-5']}, Sonnet {c['claude-sonnet-5-5']}, Opus {c['claude-opus-5-5']} per song",
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
        dict(id="desktop", title="A desktop AI app drives hypnomix", tag="most capable · subscription",
             cost="Claude Pro $20 / month (includes Claude Code); Max $100 or $200 / month for heavy use. Other agents: their own plans",
             what="Claude Code (in the Claude desktop app's Code tab, or in a terminal) or another agent like Codex or Cursor runs hypnomix commands, reads the reports and works through a whole song with you. This sets up a `hypnomix` command and a folder with the instructions the agent reads.",
             pros=["The strongest option for long, many-step work: whole songs, batches, your own requests", "A flat monthly price instead of paying per use",
                   "Comes with the hypnomix skills for Claude Code (the first-pass workflow) and works with every optional extra"],
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
    "anthropic": dict(label="Claude (Anthropic)", model="claude-sonnet-5-5", url="https://console.anthropic.com/settings/keys",
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
        return json.loads(STATE.read_text())
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
        ok = dest.exists() and "volume_string" in (dest / "abletonosc/track.py").read_text(errors="ignore")
    except OSError:
        ok = False
    lib = I.remote_scripts_dir().parent.parent           # .../Ableton
    try:
        teach = ok and "load_browser_item" in (dest / "abletonosc/track.py").read_text(errors="ignore")
    except OSError:
        teach = False
    return dict(installed=ok, where=str(dest), ableton=lib.exists(), teach_ready=teach)


DAWS = [
    dict(id="live", title="Ableton Live", note="the most depth: hypnomix reads, fixes and drives Live 11 and 12"),
    dict(id="reaper", title="REAPER", note="reads and writes projects, and drives the open REAPER through its bridge"),
    dict(id="ardour", title="Ardour", note="reads and scans sessions; you make the changes in Ardour (the least tested)"),
    dict(id="other", title="Something else", note="Logic, Pro Tools, Studio One…: export your tracks and scan the folder"),
]


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


def cli_status():
    found = shutil.which("hypnomix")
    shim = shim_path()
    on_path = str(shim.parent) in os.environ.get("PATH", "").split(os.pathsep)
    sk = agent_dir() / ".claude" / "skills"
    return dict(command=found or (str(shim) if shim.exists() else ""), shim=str(shim), shim_exists=shim.exists(),
                on_path=bool(found) or on_path, agent_dir=str(agent_dir()), agent_ready=(agent_dir() / "AGENTS.md").exists(),
                skills=sorted(p.name for p in sk.iterdir() if (p / "SKILL.md").exists()) if sk.is_dir() else [])


def make_cli():
    """A `hypnomix` command that runs this app's own Python, and a folder an AI agent can be opened in."""
    py = Path(sys.executable).absolute()          # not resolved: a venv's python is a link to a Python without hypnomix
    if sys.platform == "win32":
        py = py.with_name("python.exe") if py.name.lower() == "pythonw.exe" else py
    shim = shim_path()
    shim.parent.mkdir(parents=True, exist_ok=True)
    b = _bin_dir()
    if sys.platform == "win32":
        text = "@echo off\r\n" + (f'set "PATH={b};%PATH%"\r\n' if b else "") + f'"{py}" -m hypnomix.cli %*\r\n'
        shim.write_text(text)
    else:
        text = "#!/bin/sh\n# made by the hypnomix app's setup: runs the installed app's own hypnomix\n" + \
               (f'PATH="{b}:$PATH"; export PATH\n' if b else "") + f'exec "{py}" -m hypnomix.cli "$@"\n'
        shim.write_text(text)
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
        "# hypnomix (installed app)\n\n"
        "This folder is for an AI agent (Claude Code, Codex, Cursor…) working with hypnomix, a mixing and mastering\n"
        "assistant for Ableton Live and REAPER. Read AGENTS.md first: the loop every job follows, the safety rules\n"
        "and the command map. GUIDE.md is the user's guide.\n\n"
        f"Run hypnomix as `hypnomix <command>` (or by its full path, `{cmd}`). Start with `hypnomix doctor`.\n"
        "Every change that writes a set needs the person's OK first; hypnomix never overwrites the original.\n"
        "The songs' scans are in the folder above this one.\n"
        + (f"\nClaude Code skills (in .claude/skills): {', '.join(skills)}. For a whole new song, use first-pass.\n" if skills else "")
        + (f"Subagents (in .claude/agents): {', '.join(agents)}.\n" if agents else ""))
    shutil.copyfile(d / "CLAUDE.md", d / "README.txt")
    return cli_status()


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


def _level(s):
    lv = s.get("teach_level") or ("101" if s.get("teach") else "")
    return lv if lv in ("tour", "101") else ""


def _set_level(s, lv):
    s["teach_level"] = lv if lv in ("tour", "101") else ""
    s["teach"] = bool(s["teach_level"])


def state_view():
    from hypnomix.app import chat as CH
    from hypnomix import extras as X
    s = load()
    return dict(done=bool(s.get("done")) and s.get("version", 0) >= VERSION, mode=s.get("mode", ""),
                daw=s.get("daw", ""), teach_level=_level(s), daws=DAWS, reaper=reaper_status(),
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
        return 400, dict(ok=False, error=msg, settings=CH.settings_view())
    return 200, dict(ok=True, models=models[:200], count=len(models), settings=CH.settings_view())


def setup_live():
    from hypnomix import install as I
    out = io.StringIO()
    with redirect_stdout(out):
        I.install([])
    return dict(log=out.getvalue(), live=live_status())


def handle_get(path, q):
    if path == "/api/setup/state":
        return 200, state_view()
    if path == "/api/setup/extras":
        from hypnomix import extras as X
        return 200, X.status()
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
            s["daw"] = str(body["daw"]) if body["daw"] in {d["id"] for d in DAWS} else ""
        if "teach_level" in body:
            _set_level(s, body["teach_level"])
        save(s)
        return 200, dict(daw=s.get("daw", ""), teach_level=_level(s))
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
        if body.get("daw") in {d["id"] for d in DAWS}:
            s["daw"] = body["daw"]
        if "teach_level" in body:
            _set_level(s, body["teach_level"])
        save(s)
        return 200, state_view()
    return None
