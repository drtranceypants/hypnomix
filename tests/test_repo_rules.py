"""The repository's own rules, checked over every file git tracks: no names of paid products, hardware or songs, and no
path of anyone's computer. (The lessons have their own, stricter check in test_lessons.py; this one reuses its list.)

Names are kept as fingerprints, never in plain text: the first 12 hex digits of the SHA-256 of the name in lower case.
To add one:  python -c "import hashlib; print(hashlib.sha256('the name'.encode()).hexdigest()[:12])"
"""
import hashlib
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.test_lessons import BANNED, BANNED_WORDS

REPO = Path(__file__).resolve().parent.parent

# Hardware makers and models that the Store's catalogue named by mistake (a classic six-operator FM synth, a vintage
# analogue polysynth, a concert grand are described by what they do instead). The same lower-case fingerprints.
HARDWARE = {"80537d65d479", "53eeb36a6e8a", "498102976065", "3d0077b8d152"}
# A song of the owner's that two tests and a doc used as a session name. Its title is also an ordinary English
# adjective, so only the capitalised spelling counts as the title: the fingerprint is of that exact text (also found at
# the start of a file name such as "Title.ardour" or "Title's"). Single words only.
SONG_TITLES = {"07e7305c5340"}

# Names that stay only where code has to recognise them in someone's session or where the word is ordinary: the
# preferences accept older answers (the names of two other DAWs), the track-name sorter knows a synth's name, and an ordinary word for
# cutting audio is also a product's name.
# No document and no text a person reads may be here. (path, fingerprint): a NEW occurrence anywhere fails; an entry
# that no longer matches anything fails too, so the list can only get shorter. Owner: decide whether these may stay.
KNOWN = {
    ("hypnomix/workflow/prefs.py", "06178141c7c8"), ("hypnomix/workflow/prefs.py", "611d633fc825"),
    ("hypnomix/workflow/prefs.py", "bdf8c1e06ce1"),
    ("hypnomix/session/names.py", "63cc98599f0a"),
    ("hypnomix/studio/alignopts.py", "a067c68e292e"), ("hypnomix/studio/demo.py", "a067c68e292e"),
    ("hypnomix/workflow/handoff.py", "a067c68e292e"),
}


def words(text):
    """(word, lower-case word) in reading order. Same tokens as test_lessons.banned_in, so a line break is a space."""
    return [(m, m.lower()) for m in re.findall(r"[A-Za-z0-9][A-Za-z0-9+.'-]*[A-Za-z0-9+]|[A-Za-z0-9]", text)]


def fp(s):
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def names_in(text):
    """Every banned name in `text`, as the set of fingerprints found (never the names)."""
    ws = words(text)
    found = set()
    low = [w[1] for w in ws]
    for n in range(1, BANNED_WORDS + 1):
        for k in range(len(low) - n + 1):
            h = fp(" ".join(low[k:k + n]))
            if h in BANNED or (n == 1 and h in HARDWARE):
                found.add(h)
    for raw, _ in ws:
        for part in (raw, raw.split(".")[0], re.sub("'s$", "", raw)):
            if fp(part) in SONG_TITLES:
                found.add(fp(part))
    return found


def tracked_text_files():
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=str(REPO), capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    files = []
    for rel in out.decode("utf-8", "replace").split("\0"):
        p = REPO / rel
        if not rel or not p.is_file():
            continue
        try:
            files.append((rel, p.read_bytes().decode("utf-8")))
        except UnicodeDecodeError:
            continue                                         # a picture, a font, a binary
    return files


PLACEHOLDER = re.compile(r"^(x+|you|your[-_ ]?name|name|user(name)?|me|someone|person|example|alice|bob|test|tester|"
                         r"ann|jane|john|nobody|somebody|anybody|anyone|myname|yourusername|shared|public|guest|foo|bar|runner|ci|\.\.\.|…)$", re.I)
HOME_PATH = re.compile(r"(?:/Users/|/home/|[A-Za-z]:(?:\\+|/)Users(?:\\+|/))([^/\\\s\"'`)\]]+)")


def home_paths_in(text):
    """The account names in /Users/NAME/, /home/NAME/ and C:\\Users\\NAME\\ that look like a real person's."""
    out = []
    for m in HOME_PATH.finditer(text):
        name = m.group(1)
        if PLACEHOLDER.match(name) or not re.match(r"[A-Za-z0-9_]", name):
            continue
        out.append(name)
    return out


FILES = tracked_text_files()


@unittest.skipIf(FILES is None, "needs git and a checkout (git ls-files)")
class Names(unittest.TestCase):
    _hits = None

    def hits(self):
        if Names._hits is None:                                 # a few seconds over every file: once
            Names._hits = self._scan()
        return Names._hits

    def _scan(self):
        known, found = set(KNOWN), set()
        bad = []
        for rel, text in FILES:
            for h in names_in(text):
                if (rel, h) in known:
                    found.add((rel, h))
                else:
                    bad.append((rel, h))
        return bad, known - found

    def test_no_paid_product_hardware_or_song_names_in_any_tracked_file(self):
        bad, _ = self.hits()
        self.assertEqual(bad, [], "a fingerprinted name is in these files (path, fingerprint): reword it by what it does. "
                                  "To find the line: python -m tests.test_repo_rules FILE")

    def test_the_known_list_only_shrinks(self):
        _, stale = self.hits()
        self.assertEqual(sorted(stale), [], "these KNOWN entries match nothing any more: delete them")

    def test_the_fingerprints_catch_what_they_should(self):
        probe = "ZZ Made-Up Synth"
        title = "Zzprobe"
        BANNED.add(fp(probe.lower()))
        HARDWARE.add(fp("zzmaker"))
        SONG_TITLES.add(fp(title))
        try:
            self.assertEqual(names_in("Load the zz made-up synth, then the vocal."), {fp(probe.lower())})
            self.assertEqual(names_in("after the ZZMaker of old"), {fp("zzmaker")})
            self.assertEqual(names_in("the zzprobe sound"), set())              # a song title counts only as written
            self.assertEqual(names_in("scan/Zzprobe (DAW)"), {fp(title)})
            self.assertEqual(names_in("Zzprobe.ardour and Zzprobe's mix"), {fp(title)})
            self.assertEqual(names_in("A\nfine\nsound"), set())
            self.assertEqual(names_in("Put the ZZ\nMade-Up\nSynth on it"), {fp(probe.lower())})     # a line break is a space
        finally:
            BANNED.discard(fp(probe.lower()))
            HARDWARE.discard(fp("zzmaker"))
            SONG_TITLES.discard(fp(title))

    def test_the_fingerprints_are_in_place(self):
        for h in HARDWARE | SONG_TITLES:
            self.assertRegex(h, r"^[0-9a-f]{12}$")
        self.assertEqual((len(HARDWARE), len(SONG_TITLES)), (4, 1))
        self.assertEqual(names_in("OB-Xd 2 is a free project, and a hollow sound is a sound"), set())   # a free project's name, an adjective


@unittest.skipIf(FILES is None, "needs git and a checkout (git ls-files)")
class Paths(unittest.TestCase):
    def test_no_absolute_path_of_a_home_folder(self):
        bad = [(rel, n) for rel, text in FILES for n in home_paths_in(text)]
        self.assertEqual(bad, [], "a home folder of a real-looking account is named (path, account): write ~ or a placeholder")

    def test_the_path_check_works(self):
        users, home, win = "/Users/", "/home/", "C:" + "\\Users\\"                        # not written whole: this file is checked too
        self.assertEqual(home_paths_in(f"{users}jsmith/Music and {home}rjones/x and {win}Carol Jones\\x"),
                         ["jsmith", "rjones", "Carol"])
        self.assertEqual(home_paths_in(win.replace("\\", "\\\\") + "jsmith" + "\\\\x"), ["jsmith"])          # as written inside a string
        self.assertEqual(home_paths_in("C:" + users + "jsmith/x"), ["jsmith"])
        self.assertEqual(home_paths_in(f"{users}x/y {users}you/y {home}<you>/y {win}<you>\\z {users}[username] {home}$USER"), [])


def read(rel):
    return (REPO / rel).read_text(encoding="utf-8")


def squash(text):
    """Text without tags, and with every run of white space (and a line break inside a sentence) as one space."""
    return re.sub(r"\s+", " ", re.sub(r"[*`]", "", re.sub(r"<[^>]+>", " ", text)))


ENGINE_DOCS = ("README.md", "docs/APP.md", "docs/guides/09-setup-and-ai.md", "THIRD_PARTY.md", "packaging/README.md",
               "hypnomix/app/wiki/articles/18-daw.html", "hypnomix/app/wiki/articles/18-app.html")


@unittest.skipIf(FILES is None, "needs git and a checkout (git ls-files)")
class Claims(unittest.TestCase):
    """What the documents say about the engine, the full download and what was tried."""

    def test_the_engine_is_said_to_be_a_separate_gpl_program(self):
        for rel in ENGINE_DOCS:
            t = squash(read(rel))
            self.assertIn("Ardour", t, rel)
            self.assertRegex(t, r"General Public License,? \(?(version )?2 or later",
                             rel + " must say the engine is under the GNU General Public License, version 2 or later")
            self.assertIn("separate program", t, rel + " must say the engine is a separate program")

    def test_no_source_address_is_invented(self):
        for rel in ("README.md", "docs/APP.md", "THIRD_PARTY.md", "packaging/README.md"):
            t = squash(read(rel))
            self.assertIn("published with the first release that includes the engine", t, rel)
        for rel, text in FILES:
            for url in re.findall(r"https?://[^\s\"')<>]+", text):
                self.assertNotRegex(url, r"(?i)hypnomix[-_]?(daw|engine)", f"{rel}: {url} is an address of the engine's source")

    def test_als2ardour_is_said_to_be_unopened_in_ardour_wherever_it_is_described(self):
        for rel in ("README.md", "AGENTS.md", "hypnomix/app/wiki/articles/26-features.html", "hypnomix/app/wiki/articles/25-chores.html"):
            t = squash(read(rel))
            self.assertIn("not yet opened in Ardour", t, rel)

    def test_the_engine_mcp_server_is_not_said_to_be_on_by_default(self):
        """It is a preference (Preferences, Control Surfaces, MCPHttp) that the person switches on; daw.py says so."""
        for rel, text in FILES:
            if rel.startswith("tests/") or not rel.endswith((".md", ".html", ".py", ".js")):
                continue
            self.assertNotRegex(squash(text), r"(?i)MCP server \(?(is )?on by default", rel)

    def test_what_was_not_tried_is_said_plainly(self):
        for rel in ("README.md", "docs/APP.md", "hypnomix/app/wiki/articles/18-daw.html", "hypnomix/app/wiki/articles/27-next.html"):
            t = squash(read(rel)).lower()
            for word in ("sound card", "file menu", "intel"):
                self.assertIn(word, t, f"{rel} must say that '{word}' was not tried")
            self.assertRegex(t, r"signing|signed|notaris", f"{rel} must say that signing was not tried")

    def test_the_full_download_is_not_said_to_be_addable(self):
        for rel, text in FILES:
            if rel.endswith((".md", ".html", ".js", ".py")) and not rel.startswith(("tests/", "docs/launch/")):
                self.assertNotRegex(squash(text), r"(?i)\b(can|will) be added (later )?(from|in) \**Setup|add it later from \**Setup",
                                    f"{rel}: the full download cannot be added from Setup → Extras (nothing does that yet)")

    def test_numbers_written_by_hand_match_the_code(self):
        from hypnomix import cli
        from hypnomix.app import teacher as T
        counts = [T.count(d, "az") for d in T.DAWS]
        lo, hi = min(counts), max(counts)
        n_commands = sum(len(cmds) for _, cmds in cli.GROUPS)
        n_skills = len([p for p in (REPO / "skills").iterdir() if (p / "SKILL.md").is_file()])
        words = {"six": 6, "seven": 7, "five": 5, "four": 4, "eight": 8}
        seen = 0
        for rel, text in FILES:
            if not rel.endswith((".md", ".html")) or rel.startswith(("hypnomix/app/lessons/", "tests/")):
                continue
            t = squash(text)
            for m in re.finditer(r"(\d+) to (\d+) lessons", t):
                seen += 1
                self.assertEqual((int(m.group(1)), int(m.group(2))), (lo, hi), rel)
            self.assertNotRegex(t, r"about \d+ (?:short )?lessons", f"{rel}: write '{lo} to {hi} lessons': the courses differ by DAW")
            for m in re.finditer(r"\b(\d+) chapters", t):
                seen += 1
                self.assertEqual(int(m.group(1)), len(T.CHAPTERS), rel)
            for m in re.finditer(r"\b(\d+) commands\b", t):
                seen += 1
                self.assertEqual(int(m.group(1)), n_commands, f"{rel}: hypnomix has {n_commands} commands")
            for m in re.finditer(r"\b(Four|Five|Six|Seven|Eight) skills ship", t):
                seen += 1
                self.assertEqual(words[m.group(1).lower()], n_skills, rel)
        self.assertGreater(seen, 5, "the number check found nothing to check: has the wording changed?")


@unittest.skipIf(FILES is None, "needs git and a checkout (git ls-files)")
class Documented(unittest.TestCase):
    """Options and environment variables that the DAW mode, the Store and the Ardour tools added are written down."""

    @classmethod
    def setUpClass(cls):
        cls.docs = "\n".join(t for rel, t in FILES if rel.endswith((".md", ".html")) and not rel.startswith("tests/"))

    def test_every_option_in_the_help_of_the_new_commands_is_in_the_docs(self):
        import sys
        for cmd in ("store", "als2ardour", "chain", "app"):
            r = subprocess.run([sys.executable, "-m", "hypnomix.cli", cmd, "-h"], cwd=str(REPO), capture_output=True,
                               text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            opts = set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]+", r.stdout)) - {"--help"}
            self.assertTrue(opts, cmd)
            self.assertEqual(sorted(o for o in opts if o not in self.docs), [], f"`hypnomix {cmd} -h` lists options no document names")

    def test_every_environment_variable_of_the_new_code_is_in_docs_apps_environment_table(self):
        apps = read("docs/APP.md")
        names = set()
        for rel in ("hypnomix/app/daw.py", "hypnomix/app/store.py", "hypnomix/store/install.py", "hypnomix/store/cli.py",
                    "hypnomix/engineer/chain_ardour.py", "hypnomix/app/server.py", "hypnomix/app/update.py",
                    "hypnomix/app/diskcare.py", "macapp/Hypnomix.swift"):
            names |= set(re.findall(r"\bHYPNOMIX_[A-Z][A-Z0-9_]*", read(rel)))
        self.assertTrue(names)
        self.assertIn("HYPNOMIX_DAW", names, "the scan must see server.py and the Swift app, which read HYPNOMIX_DAW")
        listed = set(re.findall(r"\bHYPNOMIX_[A-Z][A-Z0-9_]*", apps))              # whole names: HYPNOMIX_DAW_UPLOADS is not HYPNOMIX_DAW
        self.assertEqual(sorted(n for n in names if n not in listed), [], "add these to the table in docs/APP.md")
        table = apps[apps.index("**Environment variables**"):]
        in_table = set(re.findall(r"\bHYPNOMIX_[A-Z][A-Z0-9_]*", table))
        self.assertEqual(sorted(n for n in names if n not in in_table), [], "the names must be in the environment table itself")

    def test_the_store_says_it_is_mac_only(self):
        for rel in ("docs/APP.md", "hypnomix/app/wiki/articles/18-store.html", "README.md"):
            self.assertRegex(squash(read(rel)), r"(?i)\bMac only\b|macOS only|only on (a )?Mac", rel)
        from hypnomix.store import cli as store_cli
        self.assertRegex(store_cli.__doc__ or "", r"macOS only")


class Environment(unittest.TestCase):
    """A skipped test says OK. In CI (CI is set) a missing extra or tool fails the run instead of skipping tests."""

    def test_optional_extras_the_tests_need_are_installed(self):
        from tests import _isolate
        missing = _isolate.missing_extras()
        if os.environ.get("CI") and missing:
            self.fail("CI must install the extras the tests use: " + "; ".join(f"'{n}' ({how})" for n, how, _ in missing))
        if missing:
            self.skipTest("MISSING EXTRA, tests that need it are skipped: " + "; ".join(f"'{n}': {how}" for n, how, _ in missing))

    def test_the_docs_tell_how_to_run_one_test_file_without_losing_the_isolation(self):
        """`discover -s tests -p FILE` never imports tests/__init__.py, so only `-t .` (or `-m unittest tests.x`) is isolated."""
        for rel in ("CONTRIBUTING.md", "AGENTS.md"):
            t = squash(read(rel))
            self.assertTrue("-t ." in t, rel + " must give the -t . form")
            self.assertTrue(re.search(r"(?i)\bnot isolated\b", t), rel + " must say a run without -t . is not isolated")
        for rel, text in FILES:
            if rel.startswith("tests/") or not rel.endswith((".md", ".yml", ".html")):
                continue
            for line in text.splitlines():
                if re.search(r"discover -s tests\b.*\s-p\b", line):
                    self.assertIn("-t .", line, f"{rel}: a discover run with -p and without -t . is not isolated: {line.strip()}")

    def test_a_pattern_limited_discover_run_is_isolated_with_top_level_dir(self):
        """The one command the docs give for a single file really moves the run onto temporary folders."""
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            env = {k: v for k, v in os.environ.items() if not k.startswith("HYPNOMIX_")}
            env.update(HOME=t, USERPROFILE=t)
            r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-p", "test_daw_meta.py"],
                               cwd=str(REPO), env=env, capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            self.assertEqual(sorted(os.listdir(t)), [], "the run wrote into the home folder it was given")

    def test_a_workflow_runs_this_suite_on_the_pythons_the_package_supports(self):
        wf = read(".github/workflows/tests.yml")
        self.assertIn("unittest discover -s tests", wf)
        self.assertRegex(wf, r"(?m)^\s*push:")
        self.assertRegex(wf, r"(?m)^\s*pull_request:")
        self.assertIn("ubuntu-latest", wf)
        oldest = re.search(r'requires-python\s*=\s*">=(\d+\.\d+)"', read("pyproject.toml")).group(1)
        self.assertIn(f'"{oldest}"', wf, "the workflow must test the oldest Python the package supports")
        self.assertIn('".[assistant]"', wf.replace("\\", ""), "the workflow must install the extra the tests skip without")

    def test_node_is_there_to_parse_the_page_scripts(self):
        if not shutil.which("node"):
            if os.environ.get("CI"):
                self.fail("CI must have Node.js: the check that every page script parses is skipped without it")
            self.skipTest("MISSING TOOL: node (the check that every page script parses is skipped)")


if __name__ == "__main__":
    import sys
    for rel, text in (FILES or []):
        if len(sys.argv) > 1 and sys.argv[1] not in rel:
            continue
        for h in sorted(names_in(text)):
            lines = [i for i, l in enumerate(text.splitlines(), 1) if h in names_in(l)]
            print(rel, h, lines[:5])
        for n in home_paths_in(text):
            print(rel, "home path", n)
