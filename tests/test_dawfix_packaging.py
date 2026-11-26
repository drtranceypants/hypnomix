"""Packaging fixes for the DAW branch: the engine kit checks (licence, source notice, builder's path), the quit and
first-launch wiring of the Mac app, the plain wording about the download choice, and the pages' claims."""
import getpass, os, re, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
GPL = "GNU GENERAL PUBLIC LICENSE\nVersion 2, June 1991\n"
NOTICE = ("The engine is a separate program under the GNU General Public License, version 2 or later.\n"
          "Its source is available: the source will be published with the first release that includes the engine.\n"
          "Built from version 1.2.3 of the engine.\n")


def make_kit(root, licence=True, notice=True, extra=None, link=False):
    kit = Path(root) / "HypnomixEngine"
    for rel in ("bin/hypnomix-engine", "lib/hypnomix-engine"):
        f = kit / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"\xcf\xfa\xed\xfe fake program")
        f.chmod(0o755)
    if licence:
        (kit / "COPYING").write_text(GPL)
    if notice:
        (kit / "SOURCE.txt").write_text(NOTICE)
    for rel, data in (extra or {}).items():
        f = kit / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    if link:
        os.symlink("/etc/hosts", kit / "share-link")
    return kit


@unittest.skipUnless(BASH, "no bash")
class KitChecks(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)

    def check(self, kit, via="build"):
        cmd = ([BASH, str(ROOT / "packaging/mac/build_dmg.sh"), "--check-kit", str(kit)] if via == "build"
               else [BASH, str(ROOT / "packaging/mac/check_kit.sh"), str(kit)])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return r.returncode, r.stdout + r.stderr

    def test_a_complete_kit_passes(self):
        for via in ("build", "script"):
            code, out = self.check(make_kit(self.td.name) if via == "build" else Path(self.td.name) / "HypnomixEngine", via)
            self.assertEqual(code, 0, out)

    def test_no_licence_text_is_refused(self):
        code, out = self.check(make_kit(self.td.name, licence=False))
        self.assertEqual(code, 1)
        self.assertIn("no licence text", out)

    def test_a_licence_file_that_is_not_the_gpl_is_refused(self):
        kit = make_kit(self.td.name)
        (kit / "COPYING").write_text("all rights reserved\n")
        self.assertEqual(self.check(kit)[0], 1)

    def test_no_source_notice_is_refused(self):
        code, out = self.check(make_kit(self.td.name, notice=False))
        self.assertEqual(code, 1)
        self.assertIn("no source notice", out)

    def test_a_notice_that_names_no_licence_is_refused(self):
        kit = make_kit(self.td.name)
        (kit / "SOURCE.txt").write_text("thanks for using this\n")
        self.assertEqual(self.check(kit)[0], 1)

    def test_a_one_line_notice_is_refused(self):
        for line in ("general public license source\n",
                     "GNU General Public License, version 2 or later. The source is available.\n",            # no where/when, no version built
                     "GNU General Public License version 2 or later; source at https://example.org/src\n",   # no version built from
                     "GNU General Public License version 2 or later; source: version 1.2.3 of the engine\n"):  # no where/when
            kit = make_kit(self.td.name)
            (kit / "SOURCE.txt").write_text(line)
            code, out = self.check(kit)
            self.assertEqual((code, "no source notice" in out), (1, True), line)

    def test_a_notice_with_an_address_and_a_commit_is_fine(self):
        kit = make_kit(self.td.name)
        (kit / "SOURCE.txt").write_text("GNU General Public License, version 2 or later. Source: https://example.org/src, commit 3fa9c21b.\n")
        self.assertEqual(self.check(kit)[0], 0)

    def test_a_home_path_inside_a_program_is_refused_without_printing_it(self):
        kit = make_kit(self.td.name, extra={"lib/libx.dylib": b"\x00cflags -I/Users/somebody/build/src -O2\x00"})
        code, out = self.check(kit)
        self.assertEqual(code, 1)
        self.assertIn("lib/libx.dylib", out)
        self.assertIn("home path", out)
        self.assertNotIn("somebody", out)                             # the check does not repeat the name it found

    def test_the_machines_own_home_path_is_refused_wherever_it_sits(self):
        kit = make_kit(self.td.name, extra={"share/conf.txt": ("path=" + str(Path.home()) + "/x\n").encode()})
        if str(Path.home()) in ("/", ""):
            self.skipTest("no home")
        self.assertEqual(self.check(kit)[0], 1)

    def test_the_login_name_is_refused(self):
        user = getpass.getuser()
        if len(user) < 5:
            self.skipTest("a short login name is not searched for")
        kit = make_kit(self.td.name, extra={"share/about.txt": f"built by {user} on a laptop\n".encode()})
        self.assertEqual(self.check(kit)[0], 1)

    def test_the_shared_users_folder_is_not_a_person(self):
        kit = make_kit(self.td.name, extra={"lib/libx.dylib": b"/Users/Shared/Library/x\x00"})
        self.assertEqual(self.check(kit)[0], 0)

    def test_symbolic_links_are_refused(self):
        self.assertEqual(self.check(make_kit(self.td.name, link=True))[0], 1)

    def test_a_folder_that_is_not_a_kit_is_refused(self):
        (Path(self.td.name) / "x").mkdir()
        code, out = self.check(Path(self.td.name) / "x")
        self.assertEqual(code, 1)
        self.assertIn("not a Hypnomix engine kit", out)

    def test_the_build_refuses_before_building_anything(self):
        """--daw runs the check first: a kit with no licence stops it before Python is fetched or anything is written."""
        kit = make_kit(self.td.name, licence=False)
        before = (ROOT / "packaging" / "build").exists()
        r = subprocess.run([BASH, str(ROOT / "packaging/mac/build_dmg.sh"), "--daw", str(kit)], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 1)
        self.assertIn("nothing was built", r.stdout + r.stderr)
        self.assertNotIn("Python 3", r.stdout)
        self.assertEqual((ROOT / "packaging" / "build").exists(), before)

    def test_the_scripts_parse_and_the_licence_is_copied_into_the_app(self):
        for f in ("packaging/mac/build_dmg.sh", "packaging/mac/check_kit.sh", "macapp/build.sh"):
            self.assertEqual(subprocess.run([BASH, "-n", str(ROOT / f)]).returncode, 0, f)
        sh = (ROOT / "packaging/mac/build_dmg.sh").read_text()
        self.assertIn('cp "$kit/COPYING" "$kit/SOURCE.txt" "$res/LICENSES/engine/"', sh)
        self.assertLess(sh.index("check_kit \"$kit\""), sh.index("uv python install"))        # checked before anything is built
        self.assertIn("check_kit.sh", (ROOT / "macapp/build.sh").read_text())

    def test_the_full_app_asks_for_the_microphone_in_words_that_cover_recording(self):
        sh = (ROOT / "packaging/mac/build_dmg.sh").read_text()
        self.assertIn("NSMicrophoneUsageDescription</key><string>$mictext", sh)
        self.assertRegex(sh, r'\[ -z "\$kit" \] \|\| mictext="[^"]*DAW records')
        self.assertNotIn("HypnomixEdition", sh)                       # nothing reads it: one way to know the edition


class MacAppQuit(unittest.TestCase):
    """The window asks the server before it quits and waits for it to exit (compiled for a syntax check separately)."""
    def swift(self):
        return (ROOT / "macapp" / "Hypnomix.swift").read_text()

    def test_quit_asks_save_dont_save_cancel_and_waits_for_the_server(self):
        s = self.swift()
        for word in ("applicationShouldTerminate(_ sender: NSApplication)", ".terminateLater", "api/daw/state", '"dirty"',
                     "api/daw/save", '"Save"', '"Don\'t Save"', '"Cancel"', "X-Hypnomix", "HX_TOKEN",
                     "toApplicationShouldTerminate: true", "toApplicationShouldTerminate: false", "p.isRunning && Date() < end"):
            self.assertIn(word, s)
        self.assertIn("if error == nil { stop(); return }", s)        # quits after a save only when the save was confirmed
        self.assertRegex(s, r"quitOnTerm\.setEventHandler \{ delegate\.forceQuit = true")

    def test_the_server_is_stopped_before_the_app_goes(self):
        s = self.swift()
        start = s.index("func stopServer")
        self.assertLess(s.index("p.terminate()", start), s.index("done()", s.index("p.isRunning && Date() < end", start)))

    def test_swift_compiles_when_the_compiler_is_there(self):
        swiftc = shutil.which("swiftc")
        if not swiftc or os.uname().sysname != "Darwin":
            self.skipTest("no Swift compiler")
        with tempfile.TemporaryDirectory() as td:
            r = subprocess.run([swiftc, "-typecheck", "-target", "arm64-apple-macos12", "-module-cache-path", td,
                                str(ROOT / "macapp" / "Hypnomix.swift"), "-framework", "Cocoa", "-framework", "WebKit"],
                               capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr[-1500:])


class DownloadWording(unittest.TestCase):
    """The setup's "Your download" step and the pages that describe the editions say only what is true."""
    PLAIN = [ROOT / f for f in ("hypnomix/app/setup.py", "hypnomix/app/setup.js", "packaging/README.md", "THIRD_PARTY.md",
                                "hypnomix/app/wiki/articles/18-setup.html", "hypnomix/app/wiki/articles/20-install.html")]
    PROMISE = re.compile(r"(add|added|adds|install)[a-z]* (it|the hypnomix dau|the full hypnomix|the dau)[^.<]{0,50}(later|one click|one-click|from setup)"
                         r"|(to add|added) (it )?with one click|appears? (here|on the .?extras)", re.I)

    def test_no_promise_that_the_assistant_adds_the_full_download_later(self):
        for f in self.PLAIN:
            for m in self.PROMISE.finditer(f.read_text()):
                self.fail(f"{f.name}: promises an add-on that nothing builds: {m.group(0)!r}")

    def test_the_pages_say_it_is_a_separate_download_that_replaces_the_app_and_is_mac_only(self):
        for f in (ROOT / "hypnomix/app/wiki/articles/18-setup.html", ROOT / "hypnomix/app/wiki/articles/20-install.html",
                  ROOT / "packaging/README.md"):
            t = f.read_text()
            self.assertIn("separate download that replaces", t, f.name)
            self.assertRegex(t, r"Mac only|for the Mac only|Mac only at first", f.name)

    def test_the_licence_is_stated_where_the_engine_is_described(self):
        for f in ("THIRD_PARTY.md", "packaging/README.md", "hypnomix/app/wiki/articles/20-install.html", "hypnomix/app/wiki/articles/18-setup.html"):
            t = (ROOT / f).read_text()
            self.assertRegex(t, r"GNU General Public License", f)
            self.assertIn("source will be published with the first release that includes the engine", t, f)
            self.assertNotRegex(t, r"https?://[^\s\"')]*(engine|daw)[^\s\"')]*source", f)        # no invented source address

    def test_what_was_not_verified_is_said_plainly(self):
        t = " ".join((ROOT / "packaging/README.md").read_text().split())
        for word in ("real sound card", "recording", "native File menu", "disk image", "signing", "Intel"):
            self.assertIn(word, t)

    def test_off_a_mac_the_full_download_says_mac_only_instead_of_coming_soon(self):
        from hypnomix.app import setup as SU
        win = SU.downloads("", "win32")
        self.assertEqual([d["id"] for d in win], ["assistant", "full"])
        self.assertEqual(win[1]["tag"], "Mac only for now")
        self.assertTrue(win[1]["soon"])
        self.assertIn("Mac only", win[1]["what"])
        self.assertEqual(SU.downloads("", "darwin")[1]["tag"], "coming soon")
        self.assertEqual(SU.downloads("full", "darwin")[1]["tag"], "what you have now")

    def test_the_engine_finder_and_the_edition_use_one_place_inside_an_app(self):
        from hypnomix.app import daw, update
        with tempfile.TemporaryDirectory() as td:
            c = Path(td).resolve() / "Hypnomix.app" / "Contents"
            (c / "MacOS").mkdir(parents=True)
            eng = c / "MacOS" / "hypnomix-engine"
            eng.write_text("x"); eng.chmod(0o755)
            py = c / "Resources" / "python" / "bin" / "python3"
            with mock.patch.object(daw.sys, "executable", str(py)), mock.patch.dict(os.environ, {"HYPNOMIX_ENGINE": ""}), \
                    mock.patch.object(daw, "_conf", lambda: {}):
                inside = [p for p in daw.candidates() if c in p.parents]
                self.assertEqual(inside, [c / "Resources" / "engine" / "bin" / "hypnomix-engine"])
                self.assertEqual(update.edition(), "assistant")           # a program in another place is not the full edition...
                self.assertNotIn(eng, daw.candidates())                   # ...and the DAW tab does not find it either

    def test_the_full_downloads_text_makes_no_promise_of_an_add_on(self):
        from hypnomix.app import setup as SU
        for d in SU.DOWNLOADS:
            self.assertNotIn("Extras", d["what"])
            self.assertNotRegex(d["what"], r"(?i)one click|later from")

    def test_the_full_app_opens_on_the_setup_the_first_time(self):
        from hypnomix.app import setup as SU
        with tempfile.TemporaryDirectory() as td, mock.patch.object(SU, "STATE", Path(td) / "setup.json"):
            self.assertFalse(SU.is_done())
            SU.STATE.write_text('{"done": true, "version": %d}' % SU.VERSION)
            self.assertTrue(SU.is_done())
            SU.STATE.write_text('{"done": true, "version": 0}')
            self.assertFalse(SU.is_done())                            # an older setup that gained a step is shown again
        server = (ROOT / "hypnomix/app/server.py").read_text()
        self.assertIn('"true" if DW.STATE["daw"] and SU.is_done() else "false"', server)

    def test_the_update_banner_says_plainly_a_full_app_has_no_download_yet(self):
        js = (ROOT / "hypnomix/app/update.js").read_text()
        self.assertIn("U.no_full_download", js)
        self.assertIn("has no full download yet", js)
