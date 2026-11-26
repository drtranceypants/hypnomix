"""Keeps a test run away from the person's own hypnomix folders, and says what the run cannot test.

Imported first by `tests/__init__.py` and by `tests/test_00_isolation.py` (which sorts before every other test file, so
`python -m unittest discover -s tests` reaches it before any test imports hypnomix). Each of the folders the code
resolves from the environment is pointed at a fresh temporary folder, unless whoever started the run has already set
it (CONTRIBUTING.md shows how):

    HYPNOMIX_HOME       settings, preferences, the engine's "last session" pointer (default ~/.hypnomix)
    HYPNOMIX_APP_HOME   the app's work folder: scans, the Assistant's conversation (default ~/Documents/Hypnomix)
    HYPNOMIX_USER_HOME  what stands for the home folder in the Disk care checks (default ~)
    HYPNOMIX_OUT        where commands without --out write (default ./hypnomix-out)

When HYPNOMIX_USER_HOME is not set, HOME (USERPROFILE on Windows) is moved too, so ~/Library, ~/Music and the like
cannot be reached either. The developer's own API keys, tokens and engine or app addresses (SCRUBBED) are removed from
the environment, and the system's temporary folder (TMPDIR) becomes a folder inside the temporary one, so whatever a
test leaves behind goes too. The temporary folder is removed when the run ends. `isolate()` does nothing a second time.
"""
import atexit
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

FOLDERS = ("HYPNOMIX_HOME", "HYPNOMIX_APP_HOME", "HYPNOMIX_USER_HOME", "HYPNOMIX_OUT")
MARK = "HYPNOMIX_TESTS_ROOT"        # set to the temporary folder once a run is isolated (the child processes see it too)

# Taken out of the environment for the run: the developer's own keys and tokens (a test that passes only because one of
# them is set fails on every other computer, and a test must never use a real key), and the addresses of programs a
# test must not reach by accident (the engine, the hypnomix app on its own port, the updater). A test that needs one
# sets it itself (mock.patch.dict).
SCRUBBED = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_BASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID", "GROQ_API_KEY", "MISTRAL_API_KEY",
            "GITHUB_TOKEN", "HYPNOMIX_GITHUB_TOKEN", "HYPNOMIX_ENGINE", "HYPNOMIX_ENGINE_ARGS", "HYPNOMIX_ENGINE_SRC",
            "HYPNOMIX_ENGINE_URL", "HYPNOMIX_MCP_URL", "HYPNOMIX_PORT", "HYPNOMIX_PROBE_PORT", "HYPNOMIX_UPDATE_URL")

# What a run skips when it is missing: (what, the modules or programs, how to get it, what is skipped without it)
EXTRAS = (
    ("assistant", ("anthropic", "openai"), "uv pip install -e \".[assistant]\"",
     "the Assistant's approval flow and provider loops (test_chat, test_daw, test_daw_assistant)"),
)
TOOLS = (
    ("rubberband", "brew install rubberband", "the tune, vocalign and align tests"),
    ("ffmpeg", "brew install ffmpeg", "the release and preflight tests"),
    ("node", "install Node.js", "the check that every page script parses"),
)


def isolate():
    """Point the unset folders at a temporary one. Returns the temporary folder, or None when already done."""
    if os.environ.get(MARK):
        return None
    root = Path(tempfile.mkdtemp(prefix="hypnomix-tests-")).resolve()
    moved_home = not os.environ.get("HYPNOMIX_USER_HOME")
    for name in FOLDERS:
        if not os.environ.get(name):
            p = root / name.split("HYPNOMIX_")[1].lower()
            p.mkdir()
            os.environ[name] = str(p)
    if moved_home:
        fake = root / "home_dir"
        fake.mkdir()
        os.environ["HOME"] = os.environ["USERPROFILE"] = str(fake)
    for name in SCRUBBED:
        os.environ.pop(name, None)
    tmp = root / "tmp"                          # what the tests leave in the system's temporary folder goes with the rest
    tmp.mkdir()
    os.environ["TMPDIR"] = str(tmp)
    tempfile.tempdir = str(tmp)
    os.environ[MARK] = str(root)
    atexit.register(shutil.rmtree, str(root), True)
    paths = sys.modules.get("hypnomix.core.paths")
    if paths is not None:                       # hypnomix was imported before us: its folders were read from the old environment
        paths.OUT = Path(os.environ["HYPNOMIX_OUT"])
        paths.HOME = Path(os.environ["HYPNOMIX_HOME"])
        paths.PROFILE = paths.HOME / "profile.json"
        print("tests: hypnomix was imported before the tests' isolation; only its output and home folders were moved",
              file=sys.stderr)
    return root


def fresh_chat():
    """A new Assistant conversation. hypnomix.app.chat.CHAT (and PREVIEW) are module state shared by every test module
    that touches the Assistant, so a test that leaves a conversation behind (its tokens, its pending card, the DAW
    view, a half-run turn) changes what the next module's tests see: tests.test_chat then tests.test_daw_assistant
    in one process failed on it. Every setUp that uses the Assistant calls this, and so does its tearDown."""
    import time
    import uuid
    from hypnomix.app import chat as CH
    deadline = time.time() + 5
    while CH.CHAT.get("busy") and time.time() < deadline:        # a turn still finishing in its thread
        CH.CHAT["stop"] = True
        time.sleep(0.02)
    CH.CHAT.update(id=uuid.uuid4().hex[:8], items=[], history=[], provider=None, busy=False, pending=None, stop=False,
                   error="", usage=CH.new_usage(), msg={}, elided_at=0, engine_mark=None, daw_tools={},
                   daw_groups=set(), view=None, foreign_said=False)
    CH.PREVIEW.update(id=None, undo=[], title="")


def missing_extras():
    """[(extra, install command, what is skipped)] for the optional extras that are not installed."""
    return [(name, how, what) for name, mods, how, what in EXTRAS
            if any(importlib.util.find_spec(m) is None for m in mods)]


def missing_tools():
    mac_js = sys.platform == "darwin" and shutil.which("osascript") is not None      # macOS parses JavaScript without node
    return [(t, how, what) for t, how, what in TOOLS if shutil.which(t) is None and not (t == "node" and mac_js)]


def notice():
    """The lines a run prints at its start when something it tests is missing (a skip is not a pass)."""
    out = []
    for name, how, what in missing_extras():
        out.append(f"tests: the '{name}' extra is not installed ({how}): {what} is SKIPPED")
    for tool, how, what in missing_tools():
        out.append(f"tests: {tool} is not installed ({how}): {what} is SKIPPED")
    return out


if not os.environ.get(MARK):
    isolate()
    for line in notice():
        print(line, file=sys.stderr)
