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
import importlib.machinery
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
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
    # Anthropic's library needs Python 3.10 or newer (pyproject.toml), so a 3.9 run needs only the other one
    ("assistant", ("anthropic", "openai") if sys.version_info >= (3, 10) else ("openai",), "uv pip install -e \".[assistant]\"",
     "the Assistant's approval flow and provider loops (test_chat, test_daw, test_daw_assistant)"),
)
# how to get a program, by system (the project tests on macOS and Windows; the Linux words help a person who runs the tests there)
_HOW = {"darwin": {"rubberband": "brew install rubberband", "ffmpeg": "brew install ffmpeg"},
        "win32": {"rubberband": "no reliable package on Windows: the command-line program from breakfastquay.com/rubberband, "
                                "its folder on PATH", "ffmpeg": "choco install ffmpeg"}}


def _how(tool, default):
    return _HOW.get(sys.platform, {}).get(tool, default)


TOOLS = (
    ("rubberband", _how("rubberband", "install rubberband-cli with your package manager"), "the tune, vocalign and align tests"),
    ("ffmpeg", _how("ffmpeg", "install ffmpeg with your package manager"), "the release and preflight tests"),
    ("node", "install Node.js", "the check that every page script parses"),
)

# The reason a test gives when it needs Rubber Band and it is not installed: a visible skip that names the tool (like
# tests/_jscheck.py's NO_RUNNER), never a silent pass. The Windows runners of CI have no Rubber Band (.github/workflows/tests.yml).
NO_RUBBERBAND = "SKIPPED: Rubber Band (the `rubberband` program) is not installed here, so this test was NOT run"

# For a test whose whole point is a file permission (chmod, mode 0o600, a read-only folder): Windows has no such bits, so it
# is a visible skip there, never a pass and never a failure that says nothing about HypnoMix.
POSIX_MODES = unittest.skipIf(sys.platform == "win32", "SKIPPED: this test checks file permission bits (chmod, 0o600, "
                                                       "read-only folders), which Windows does not have, so it was NOT run")
# For a test that starts a shell script or a program with a shebang line, uses process groups or sends POSIX signals: a
# visible skip on Windows (the Mac helper script, the DAW engine's stand-in).
POSIX_ONLY = unittest.skipIf(sys.platform == "win32", "SKIPPED: this test starts a shell script or uses POSIX process groups "
                                                      "and signals, which Windows does not have, so it was NOT run")


def _bind_without_dns():
    """http.server.HTTPServer.server_bind asks the resolver for this computer's name (socket.getfqdn, a reverse lookup of
    the address). A stand-in server in a test has no use for the name, and on a runner with a slow resolver each one
    waited more than half a minute. The stand-in servers of a run bind without the lookup."""
    import http.server
    import socketserver

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[0], self.server_address[1]
    http.server.HTTPServer.server_bind = server_bind


def find_bash():
    """Git Bash (or any real bash), never Windows' System32 bash.exe, which is the WSL launcher: it finds no distribution
    and prints a sentence in UTF-16 instead of running the script."""
    for cand in (shutil.which("bash"), r"C:\Program Files\Git\bin\bash.exe"):
        if cand and os.path.exists(cand) and "system32" not in cand.lower().replace("/", "\\"):
            return cand
    return None


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
    # Apple's own Python 3.9 (Xcode, the Command Line Tools: what `uv venv --python 3.9` finds on a Mac runner) keeps its
    # compiled modules in ~/Library/Caches/com.apple.python, under the HOME the program was STARTED with. A test that starts
    # a program with an empty folder as HOME and then checks that nothing was written there found "Library". The compiled
    # modules of every program a test starts go inside the temporary folder instead (and are removed with it).
    os.environ.setdefault("PYTHONPYCACHEPREFIX", str(root / "pycache"))
    tempfile.tempdir = str(tmp)
    _bind_without_dns()
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


def stand_in_for_claude_library():
    """Python 3.9 cannot have Anthropic's library (it needs 3.10; see pyproject.toml). The tests never call the real one:
    each replaces the client by a stand-in (`mock.patch("anthropic.Anthropic", Fake)`), which needs a module of that name to
    exist. So on a Python that cannot install the library, and only then, an empty module of that name is made, whose
    client refuses to be used. Returns True when it made one."""
    if sys.version_info >= (3, 10) or importlib.util.find_spec("anthropic") is not None:
        return False
    import types
    m = types.ModuleType("anthropic")
    m.__spec__ = importlib.machinery.ModuleSpec("anthropic", None)

    class Anthropic:
        def __init__(self, *a, **k):
            raise RuntimeError("this is the tests' stand-in for Anthropic's library, not a client: a test must replace Anthropic")
    m.Anthropic = Anthropic
    m.STAND_IN = True
    sys.modules["anthropic"] = m
    return True


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
    if getattr(sys.modules.get("anthropic"), "STAND_IN", False):
        out.append("tests: Anthropic's library needs Python 3.10 or newer: an empty stand-in module is used, and the tests that "
                   "replace the client run; nothing here can test the real library")
    for name, how, what in missing_extras():
        out.append(f"tests: the '{name}' extra is not installed ({how}): {what} is SKIPPED")
    for tool, how, what in missing_tools():
        out.append(f"tests: {tool} is not installed ({how}): {what} is SKIPPED")
    return out


stand_in_for_claude_library()
if not os.environ.get(MARK):
    isolate()
    for line in notice():
        print(line, file=sys.stderr)
