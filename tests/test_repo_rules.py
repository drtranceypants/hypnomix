"""The repository's own rules, checked over every file git tracks: no names of paid products, hardware or songs, and no
path of anyone's computer. (The lessons have their own, stricter check in test_lessons.py; this one reuses its list.)

Names are kept as fingerprints, never in plain text: the first 12 hex digits of the SHA-256 of the name in lower case.
To add one:  python -c "import hashlib; print(hashlib.sha256('the name'.encode()).hexdigest()[:12])"
"""
import ast
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


# ---------------------------------------------------------------------------------------------------------------------
# THE NAMING RULES (the owner's decisions of 2026-11-26). What a person READS says "HypnoMix" (capital H, capital M) and
# "HypnoMix Studio"; the name of the program under that DAW is given in a few places, each named below, and nowhere else.
# Both checks look at the text a person can read: for a Python file its string literals and docstrings (never comments);
# for a script, a style sheet or a source file in a language with comments, the text without them; for every other file
# (documents, wiki articles, data, shell scripts) the whole text. This file states the names it polices, so it is skipped.
SELF = "tests/test_repo_rules.py"
LINE_COMMENT = {".yml": "#", ".yaml": "#", ".ps1": "#", ".toml": "#", ".iss": ";", ".lua": "--", ".jsfx": "//"}
NUL = "\x00"                                     # between two string literals of a Python file: a literal can be matched whole


def strip_c_comments(text, line_comments=True):
    """`text` of a JavaScript, CSS or Swift file without its comments. A quote that does not close on its line is taken for
    an ordinary character (a regular expression's quote, an apostrophe), so a comment after one is still found."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if line_comments and text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif c in "\"'`":
            j = i + 1
            while j < n and text[j] != c and not (text[j] == "\n" and c != "`"):
                j += 2 if text[j] == "\\" else 1
            if j < n and text[j] == c:
                out.append(text[i:j + 1])
                i = j + 1
            else:
                out.append(c)
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def reader_text(rel, text):
    """What a person can read in this file (see the note above)."""
    ext = Path(rel).suffix.lower()
    if ext in (".py", ".pyw"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return text
        return NUL.join(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str))
    if ext in (".js", ".css", ".swift"):
        return strip_c_comments(text, line_comments=ext != ".css")
    if ext in LINE_COMMENT:
        return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith(LINE_COMMENT[ext]))
    return text


# (a) "Ardour" (capital A: the program's own name) in text a person reads. path -> (how many times, why). None: any number
# of times, at least once. A NEW occurrence anywhere, or a changed count, or an entry that matches nothing, fails.
ARDOUR_PLACES = {
    # the disclosure: HypnoMix Studio is built on Ardour, a free open-source DAW under the GNU GPL
    "README.md": (3, "the disclosure sentence near the top with the honesty line, and the licence paragraph"),
    "THIRD_PARTY.md": (3, "the licence notice of the add-on: what it is built on, and its licence"),
    "hypnomix/app/wiki/articles/28-ardour.html": (10, "the ONE wiki article about HypnoMix Studio: what it is built on, the .ardour format, the honesty line"),
    "hypnomix/app/engine_addon.py": (1, "the Setup card of the add-on: 'built on Ardour, a free open-source DAW'"),
    "hypnomix/app/teacher.py": (1, "HONESTY: the honesty line, shown in the first step of each HypnoMix Studio course"),
    "packaging/README.md": (2, "the engine's licence notice in the packaging notes"),
    "packaging/mac/build_dmg.sh": (1, "the engine's licence notice in the installer script"),
    "packaging/mac/build_engine_archive.sh": (1, "the engine's licence notice in the engine-kit script"),
    # developer documentation of the file format that the reader and the writer handle (no product text)
    "hypnomix/project/ardour.py": (8, "docstrings of the reader of the session format"),
    "hypnomix/project/ardour_edit.py": (7, "docstrings of the writer of new snapshots"),
    "hypnomix/project/als2ardour.py": (4, "docstrings of helpers that write the session format"),
    "hypnomix/project/__init__.py": (3, "the package docstring and the session-folder helper name the supported formats"),
    "hypnomix/workflow/fix_ardour.py": (4, "docstrings of the module that writes fixes into a session snapshot"),
    # tests: they pin the disclosure, assert that the name is absent elsewhere, or test the format reader
    "tests/test_ardour.py": (3, "tests of the session reader"),
    "tests/test_als2ardour.py": (2, "tests of the Live-set converter"),
    "tests/test_lessons.py": (6, "pins the honesty line and checks that no lesson names the program otherwise"),
    "tests/test_app.py": (3, "asserts that no app page names the program"),
    "tests/test_release_gate.py": (1, "asserts that a roadmap row does not name it"),
    "tests/test_engine_addon.py": (1, "pins the Setup card phrase"),
    "tests/test_dawfix_packaging.py": (1, "asserts that the disclosure is in the packaging notes only"),
    "tests/test_daw_assistant.py": (1, "a fixture copied from the engine's own plug-in list (its 'creator' field)"),
}

# (b) The old spelling "Hypnomix" (capital H, small m) in text a person reads. Only these literal names, which other
# programs look up or which sit on people's disks, may carry it. (regular expression, why). A match is taken away before
# the rest of the text is checked; an entry that matches nothing fails.
OLD_NAMES = [
    (r"(?<=HypnomixMain, )Hypnomix\b|(?<=HypnomixMain and )Hypnomix\b", "the review device, the third in a list of the three Max devices"),
    (r"(?<![^\x00])Hypnomix(?![^\x00])", "a string that is exactly the name: the review device, the executable and the folders of the app"),
    (r"(?<![^\x00])/Hypnomix(?![^\x00])", "the app's executable, tested by its path ending"),
    (r"Hypnomix\.(?:app|amxd|swift|icns|iconset)", "the Mac app bundle, the review device file, the Swift source, the icon files"),
    (r"Hypnomix-(?:\d|mac|windows|full|\$|<|\{|\*)[^\s\"'`)\]|,;]*|-Hypnomix-", "the installer file names, which the updater matches"),
    (r"Hypnomix Library", "the folder in the person's Music folder that the Store fills"),
    (r"X-Hypnomix", "the request header that proves a request comes from the app's own page"),
    (r"Hypnomix Demo Song", "the demo project's folder and file names"),
    (r"Hypnomix(?:Probe|Main)", "the Max for Live devices, found by this name in saved sets"),
    (r"Hypnomix(?:Engine|Python)", "the engine kit's folder name and the app bundle's Info.plist key"),
    (r"Hypnomix\s+(?:Probe|Main|Align|Master|Utility|Limiter|Saturator|Tools)", "the devices, REAPER effects and plug-ins that code finds by name, and the old rack name (Master) that older Live sets hold"),
    (r"Hypnomix · ", "the tag in front of the plug-ins that the REAPER chain builds"),
    (r"Max Audio Effect(?: -> | → |/)Hypnomix", "the Live browser folder that the device installer creates"),
    (r"(?:Documents|Programs|LOCALAPPDATA%?)[/\\]+Hypnomix|Work\\Hypnomix|MacOS/Hypnomix", "the app's folders and executable on disk"),
    (r"<string>Hypnomix</string>", "CFBundleExecutable and CFBundleIconFile in the app bundle's Info.plist"),
    (r"Hypnomix\s+(?:review\s+)?devices?|Hypnomix panel", "the review device and the REAPER panel, named as they are in Live and REAPER"),
    (r"\*\*Hypnomix\*\*|<b>Hypnomix</b>|Hypnomix \(the review device\)", "the review device's name in bold or in a command list"),
    (r"type Hypnomix in", "the search term for the review device in REAPER's effect browser"),
]
OLD_NAMES = [(re.compile(p), why) for p, why in OLD_NAMES]
# What is left of the old spelling after those names are taken away: only tests that must write it to assert that it is gone.
OLD_SPELLING_IN_TESTS = {
    "tests/test_app.py": (3, "the naming test of the app's pages: the patterns that find the old spelling"),
    "tests/test_lessons.py": (1, "the lessons' naming test: the pattern that finds the old spelling"),
    "tests/test_dawfix_packaging.py": (2, "asserts that two retired page texts are gone"),
    "tests/test_release_gate.py": (1, "asserts that a retired page text is gone"),
}


def ardour_counts():
    found = {}
    for rel, text in FILES:
        if rel != SELF:
            n = reader_text(rel, text).count("Ardour")
            if n:
                found[rel] = n
    return found


def old_spelling_counts():
    """({path: occurrences left after the allowed names are taken away}, {pattern: matches})."""
    left, used = {}, {}
    for rel, text in FILES:
        if rel == SELF:
            continue
        v = reader_text(rel, text)
        if "Hypnomix" not in v:
            continue
        for rx, _ in OLD_NAMES:
            v, n = rx.subn("\x01", v)
            used[rx.pattern] = used.get(rx.pattern, 0) + n
        if "Hypnomix" in v:
            left[rel] = v.count("Hypnomix")
    return left, used


HONESTY_LINE = "HypnoMix Studio is new: its first engine (0.1.0) is for Apple-silicon Macs. Steps written here for it were written against Ardour 8 or 9, the free DAW it is built on, and not every one has been tried in HypnoMix Studio yet."
DISCLOSURE_SENTENCE = "It is built on Ardour, a free open-source DAW under the GNU General Public License."
WIKI = "hypnomix/app/wiki/articles"
ENGINE_SOURCE = "https://github.com/drtranceypants/hypnomix-daw"


@unittest.skipIf(FILES is None, "needs git and a checkout (git ls-files)")
class OldNames(unittest.TestCase):
    """The old names cannot come back: 'Ardour' and the spelling 'Hypnomix' appear only in the places listed above."""

    def test_ardour_is_named_only_in_the_places_the_owner_allowed(self):
        found = ardour_counts()
        bad = sorted(rel for rel in found if rel not in ARDOUR_PLACES)
        self.assertEqual(bad, [], "'Ardour' is in text a person reads here: say HypnoMix Studio (the disclosure places are in ARDOUR_PLACES)")
        wrong = {rel: (found.get(rel, 0), want) for rel, (want, _) in ARDOUR_PLACES.items()
                 if (want is None and not found.get(rel)) or (want is not None and found.get(rel, 0) != want)}
        self.assertEqual(wrong, {}, "path: (found, listed): a new mention, or an entry that matches less than it says (fix the entry)")

    def test_every_ardour_entry_has_a_reason_and_names_a_file_that_exists(self):
        for rel, (want, why) in ARDOUR_PLACES.items():
            self.assertTrue((REPO / rel).is_file(), rel)
            self.assertTrue(why.strip(), rel)

    def test_the_old_spelling_is_left_only_in_the_names_that_must_not_change(self):
        left, used = old_spelling_counts()
        bad = {rel: n for rel, n in left.items() if rel not in OLD_SPELLING_IN_TESTS}
        self.assertEqual(bad, {}, "path: how many. 'Hypnomix' (small m) is in text a person reads: write HypnoMix, or `hypnomix` "
                                  "when it is the command. Only the names in OLD_NAMES keep the old spelling.")
        wrong = {rel: (left.get(rel, 0), want) for rel, (want, _) in OLD_SPELLING_IN_TESTS.items() if left.get(rel, 0) != want}
        self.assertEqual(wrong, {}, "path: (found, listed): a test entry that no longer matches what it lists")
        stale = [p for p, n in used.items() if not n] + [rx.pattern for rx, _ in OLD_NAMES if rx.pattern not in used]
        self.assertEqual(stale, [], "these OLD_NAMES entries match nothing any more: delete them")

    def test_the_scanner_reads_what_a_person_reads(self):
        py = 'import x\n# Hypnomix in a comment\n"""A docstring about Ardour."""\nname = "Hypnomix Align"   # trailing\n'
        self.assertEqual(reader_text("a.py", py).count("Ardour"), 1)
        self.assertEqual(reader_text("a.py", py).count("Hypnomix"), 1)
        js = "/* Hypnomix · header, with Ardour */\nvar a = 'Ardour';  // Hypnomix\nvar b = \"//Hypnomix\"; /* Ardour */\nvar re = /[\"']/;  // Hypnomix\n"
        seen = reader_text("a.js", js)
        self.assertEqual((seen.count("Ardour"), seen.count("Hypnomix")), (1, 1), seen)
        self.assertEqual(reader_text("a.css", "a { content: 'Ardour' } /* Ardour */").count("Ardour"), 1)
        self.assertEqual(reader_text("a.yml", "# Hypnomix\nname: Hypnomix\n").count("Hypnomix"), 1)
        self.assertEqual(reader_text("a.md", "<!-- Hypnomix -->\nArdour").count("Hypnomix"), 1)             # a document is read whole
        left = old_names_left("The Hypnomix Align device, HypnomixMain, Hypnomix-mac-arm64.dmg and Hypnomix.app stay; the Hypnomix app does not.")
        self.assertEqual(left, 1)
        self.assertEqual(old_names_left("HypnoMix, hypnomix scan and HYPNOMIX are the new spellings"), 0)
        self.assertEqual(old_names_left("Made HypnomixProbe, HypnomixMain and Hypnomix: in Live"), 0)
        self.assertEqual(old_names_left("a bare Hypnomix in prose"), 1)

    def test_no_command_help_names_the_program_or_uses_the_old_spelling(self):
        """`hypnomix COMMAND -h` prints the module's docstring where the command has no option parser of its own."""
        from hypnomix import cli
        for name, (mod, _) in sorted(cli.COMMANDS.items()):
            path = REPO / (mod.replace(".", "/") + ".py")
            if not path.is_file():
                path = REPO / mod.replace(".", "/") / "__init__.py"
            doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
            self.assertNotIn("Ardour", doc, f"`hypnomix {name} -h` names the program")
            self.assertEqual(old_names_left(doc), 0, f"`hypnomix {name} -h` uses the old spelling")


def old_names_left(sentence):
    v = sentence
    for rx, _ in OLD_NAMES:
        v = rx.sub("\x01", v)
    return v.count("Hypnomix")


@unittest.skipIf(FILES is None, "needs git and a checkout (git ls-files)")
class Disclosure(unittest.TestCase):
    """HypnoMix Studio is built on Ardour, and that is said plainly and once where the owner wants it said."""

    def test_the_wiki_has_exactly_one_article_that_discloses_what_hypnomix_daw_is_built_on(self):
        saying = [rel for rel, text in FILES if rel.startswith(WIKI + "/") and rel.endswith(".html") and "built on Ardour" in squash(text)]
        self.assertEqual(saying, [WIKI + "/28-ardour.html"])
        arts = [rel for rel, _ in FILES if rel.startswith(WIKI + "/") and rel.endswith(".html")]
        self.assertEqual([rel for rel in arts if "Ardour" in read(rel)], [WIKI + "/28-ardour.html"], "no other article names the program")
        head = read(WIKI + "/28-ardour.html").split("-->")[0]
        self.assertRegex(head, r"(?m)^title: HypnoMix Studio \(beta\)$")
        t = squash(read(WIKI + "/28-ardour.html"))
        self.assertEqual(t.count(HONESTY_LINE), 1, "the honesty line, once, in the article")
        self.assertIn("Ardour-format session folder", t)
        self.assertIn(".ardour", t)
        self.assertIn("Sessions saved by Ardour 3 to 9 open the same way", t)

    def test_the_readme_has_the_disclosure_sentence_and_the_honesty_line_once_each(self):
        t = squash(read("README.md"))
        self.assertEqual(t.count(DISCLOSURE_SENTENCE), 1)
        self.assertEqual(t.count(HONESTY_LINE), 1)
        install = t.index("## Install")
        self.assertLess(install, t.index(DISCLOSURE_SENTENCE), "in Install, where the add-on is described")
        self.assertLess(t.index(DISCLOSURE_SENTENCE), t.index(HONESTY_LINE), "the honesty line follows the disclosure")
        self.assertLess(t.index(HONESTY_LINE) - install, 1500, "both near the start of Install")
        self.assertRegex(t, r"GNU General Public License,? \(?(version )?2 or later")          # the licence paragraph, with its notice of the engine
        self.assertIn("a rebranded fork of Ardour", t)

    def test_third_party_names_what_it_gives_notice_of(self):
        t = squash(read("THIRD_PARTY.md"))
        self.assertIn("HypnoMix Studio: built on Ardour", t)
        self.assertRegex(t, r"GNU General Public License, version 2 or later")

    def test_the_honesty_line_is_said_in_these_places_and_no_others(self):
        from hypnomix.app import teacher as T, engine_addon as EA
        self.assertEqual(T.HONESTY, HONESTY_LINE)
        self.assertIn("built on Ardour, a free open-source DAW", EA.WHAT)
        places = sorted(rel for rel, text in FILES if not rel.startswith("tests/") and HONESTY_LINE in squash(text))
        self.assertEqual(places, ["README.md", WIKI + "/28-ardour.html"], "teacher.py holds it as HONESTY (two string pieces)")
        for level in T.LEVELS:
            first = T.steps("ardour", level)[0]["steps"][0]
            self.assertEqual(sum(HONESTY_LINE in h for h in first["how"]), 1, level)
            for daw in ("live", "reaper"):
                self.assertNotIn(HONESTY_LINE, " ".join(T.steps(daw, level)[0]["steps"][0]["how"]), (daw, level))


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
            self.assertIn("Ardour" if rel in ("README.md", "THIRD_PARTY.md", "packaging/README.md") else "HypnoMix Studio", t, rel)   # Ardour is named only where the disclosure belongs
            self.assertRegex(t, r"General Public License,? \(?(version )?2 or later",
                             rel + " must say the engine is under the GNU General Public License, version 2 or later")
            self.assertIn("separate program", t, rel + " must say the engine is a separate program")

    def test_the_engine_source_address_is_the_real_one(self):
        """The engine's source is public at one address; no other address of it is invented. The archive itself is on
        the project's own release page."""
        for rel in ("README.md", "docs/APP.md", "THIRD_PARTY.md", "packaging/README.md"):
            t = squash(read(rel))
            self.assertIn(ENGINE_SOURCE, t, rel)
            self.assertNotIn("published with the first release that includes the engine", t, rel)
        for rel, text in FILES:
            for url in re.findall(r"https?://[^\s\"')<>]+", text):
                if url.rstrip(".,;:") == ENGINE_SOURCE or url.startswith("https://github.com/drtranceypants/hypnomix/releases/"):
                    continue
                self.assertNotRegex(url, r"(?i)hypnomix[-_]?(daw|engine)", f"{rel}: {url} is not the engine's source address")

    def test_als2ardour_is_said_to_be_unopened_in_a_released_daw_wherever_it_is_described(self):
        for rel in ("README.md", "AGENTS.md", "hypnomix/app/wiki/articles/26-features.html", "hypnomix/app/wiki/articles/25-chores.html"):
            t = squash(read(rel))
            self.assertIn("not yet opened in a released DAW", t, rel)

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

    def test_hypnomix_daw_is_not_said_to_be_available_where_it_is_not(self):
        """HypnoMix Studio is an add-on fetched from Setup, and its first engine is for Apple-silicon Macs only: a page that says
        it can be added from Setup must say, in the same page, where it is (or is not) available; and none says it is out
        without saying for what."""
        for rel, text in FILES:
            if rel.endswith((".md", ".html", ".js", ".py")) and not rel.startswith(("tests/", "docs/launch/")):
                t = squash(text)
                self.assertNotRegex(t, r"(?i)\bHypnoMix Studio (is|are) (now )?(available|out|ready|released)\b(?! (yet|for|on))", f"{rel}: say for what")
                if re.search(r"(?i)added? (it |HypnoMix Studio )?(from|in|with) \**Setup", t):
                    self.assertRegex(t, r"(?i)Apple[- ]silicon|not available (for [^.]{1,40} |there )?yet|no archive|names no address",
                                     f"{rel}: says it can be added from Setup, and not where it is available")

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
                               text=True, timeout=120, encoding="utf-8")
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
                               cwd=str(REPO), env=env, capture_output=True, text=True, timeout=300, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            self.assertEqual(sorted(os.listdir(t)), [], "the run wrote into the home folder it was given")

    def test_a_workflow_runs_this_suite_on_the_pythons_the_package_supports(self):
        wf = read(".github/workflows/tests.yml")
        self.assertIn("unittest discover -s tests", wf)
        self.assertRegex(wf, r"(?m)^\s*push:")
        self.assertRegex(wf, r"(?m)^\s*pull_request:")
        oldest = re.search(r'requires-python\s*=\s*">=(\d+\.\d+)"', read("pyproject.toml")).group(1)
        self.assertIn(f'"{oldest}"', wf, "the workflow must test the oldest Python the package supports")
        self.assertIn('".[assistant]"', wf.replace("\\", ""), "the workflow must install the extra the tests skip without")

    def test_the_workflow_runs_on_macos_and_windows_and_never_on_linux(self):
        """The owner's decision (after 0.3.1): the project tests on macOS and Windows only; Linux is left to outside people."""
        wf = read(".github/workflows/tests.yml")
        code = "\n".join(l for l in wf.splitlines() if not l.lstrip().startswith("#"))       # the header may name Linux
        self.assertRegex(code, r"(?m)^\s*os:\s*\[[^\]]*\bmacos-latest\b")
        self.assertRegex(code, r"(?m)^\s*os:\s*\[[^\]]*\bwindows-latest\b")
        self.assertNotRegex(code, r"(?i)ubuntu|\blinux\b|apt-get|\bsudo\b")
        self.assertRegex(code, r"(?m)^\s*runs-on:\s*\$\{\{\s*matrix\.os\s*\}\}")
        self.assertRegex(code, r"(?m)^\s*fail-fast:\s*false\s*$")
        self.assertRegex(code, r"(?m)^\s*timeout-minutes:\s*60\s*$")
        self.assertRegex(wf, r"(?i)Linux is not tested by the project")

    def test_every_run_step_of_the_workflow_says_shell_bash(self):
        """One script serves both systems (Git Bash on Windows): no step may fall back to PowerShell or cmd."""
        steps = re.split(r"(?m)^      - ", read(".github/workflows/tests.yml"))[1:]
        runs = [s for s in steps if re.search(r"(?m)^\s+run:", s)]
        self.assertGreaterEqual(len(runs), 5)
        for s in runs:
            self.assertRegex(s, r"(?m)^\s+shell:\s*bash\s*$", "a run step without `shell: bash`: " + s.splitlines()[0])

    def test_the_workflow_keeps_line_endings_as_in_the_repository_before_the_checkout(self):
        """The Windows image checks out CRLF by default, which breaks the shell scripts the tests run and the byte-exact reads."""
        wf = read(".github/workflows/tests.yml")
        self.assertIn("git config --global core.autocrlf false", wf)
        self.assertLess(wf.index("core.autocrlf false"), wf.index("actions/checkout@"), "it must be set before the checkout")

    def test_the_windows_jobs_are_honest_about_rubber_band(self):
        """Windows has no reliable Rubber Band package: the jobs run without it and the log says so, the tests that need it skip by name."""
        wf = read(".github/workflows/tests.yml")
        self.assertIn("choco install ffmpeg", wf)
        self.assertIn("brew install ffmpeg rubberband", wf)
        self.assertIn("::warning::Rubber Band", wf)
        from tests import _isolate
        self.assertIn("Rubber Band", _isolate.NO_RUBBERBAND)
        self.assertTrue(_isolate.NO_RUBBERBAND.startswith("SKIPPED"))
        for rel in ("tests/test_align.py", "tests/test_als2ardour.py", "tests/test_previews.py", "tests/test_reaper_align.py"):
            t = read(rel)
            self.assertIn("_isolate.NO_RUBBERBAND", t, rel + ": a skip for a missing Rubber Band must say so by name")
            self.assertNotRegex(t, r'skipUnless\([^\n]*rubberband[^\n]*"needs', rel)

    def test_the_docs_do_not_promise_private_files_on_windows(self):
        """File permission bits do nothing on Windows (hypnomix/core/paths.py private_dir). Wherever the docs say a file can
        be read by the person alone, they say that this is on a Mac, and what holds on Windows."""
        for rel in ("README.md", "docs/guides/09-setup-and-ai.md", "hypnomix/app/wiki/articles/18-assistant.html"):
            t = squash(read(rel))
            self.assertIn("HypnoMix adds no lock of its own there", t, rel)
            self.assertIn("On a Mac only your account can read", t, rel)
            for old in ("readable by you only", "readable by you alone", "can be read by you alone"):
                self.assertNotIn(old, t, rel + ": true on a Mac only; say what holds on Windows")

    def test_the_docs_say_the_project_does_not_test_on_linux(self):
        for rel in ("README.md", "hypnomix/app/wiki/articles/19-requirements.html", "hypnomix/app/wiki/articles/28-faq.html",
                    "hypnomix/app/wiki/articles/20-install.html"):
            self.assertIn("the project does not test on Linux", squash(read(rel)), rel)
        c = squash(read("CONTRIBUTING.md"))
        self.assertIn("Work on macOS and Windows, which the tests run on", c)
        self.assertNotIn("Work on Windows and Linux too", c)
        self.assertNotIn("Windows and Linux parity", read("docs/ROADMAP.md") + read("hypnomix/app/wiki/articles/27-next.html"))

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
