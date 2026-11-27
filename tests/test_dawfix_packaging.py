"""Packaging for the DAW: the engine kit checks (licence, source notice, builder's path) in the shell script and in the
add-on's Python twin, the quit and first-launch wiring of the Mac app, the plain wording about HypnoMix DAW as an add-on
(one app, one installer, the DAW added from Setup), and the pages' claims."""
import getpass, os, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

from tests import _isolate

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


@_isolate.POSIX_ONLY                                      # the packaging scripts are Mac scripts (lipo, hdiutil)
@unittest.skipUnless(BASH, "SKIPPED: no bash here, so this test was NOT run")
class KitChecks(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)

    def check(self, kit, via="script"):
        """The shell check on its own, or through the archive script (which makes nothing when it refuses)."""
        if via == "script":
            cmd = [BASH, str(ROOT / "packaging/mac/check_kit.sh"), str(kit)]
        else:
            cmd = [BASH, str(ROOT / "packaging/mac/build_engine_archive.sh"), str(kit), "mac-arm64", str(Path(self.td.name) / "out")]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=dict(os.environ, HYPNOMIX_PYTHON=sys.executable))
        return r.returncode, r.stdout + r.stderr

    def test_a_complete_kit_passes(self):
        self.assertEqual(self.check(make_kit(self.td.name))[0], 0)
        self.assertEqual(self.check(Path(self.td.name) / "HypnomixEngine", "archive")[0], 0)

    def test_the_python_check_agrees_with_the_shell_check(self):
        """hypnomix/app/engine_addon.py kit_problems is the same check, run on what was downloaded."""
        from hypnomix.app import engine_addon as EA
        cases = [dict(), dict(licence=False), dict(notice=False), dict(link=True),
                 dict(extra={"lib/libx.dylib": b"\x00cflags -I/Users/somebody/build/src -O2\x00"}),
                 dict(extra={"lib/libx.dylib": b"/Users/Shared/Library/x\x00"})]
        for kw in cases:
            with tempfile.TemporaryDirectory() as td:
                kit = make_kit(td, **kw)
                code, _ = self.check(kit)
                self.assertEqual(code == 0, EA.kit_problems(kit) == [], kw)

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
        self.assertIn("not a HypnoMix DAW engine kit", out)

    def test_the_archive_script_refuses_before_writing_anything(self):
        """A kit with no licence stops it before an archive is made or a folder created."""
        kit = make_kit(self.td.name, licence=False)
        code, out = self.check(kit, "archive")
        self.assertEqual(code, 1)
        self.assertIn("nothing was written", out)
        self.assertFalse((Path(self.td.name) / "out").exists())

    def test_the_scripts_parse_and_check_before_they_pack(self):
        for f in ("packaging/mac/build_dmg.sh", "packaging/mac/check_kit.sh", "packaging/mac/build_engine_archive.sh", "macapp/build.sh"):
            self.assertEqual(subprocess.run([BASH, "-n", str(ROOT / f)]).returncode, 0, f)
        sh = (ROOT / "packaging/mac/build_engine_archive.sh").read_text()
        self.assertLess(sh.index('check_kit "$kit"'), sh.index("pack_engine.py"))             # checked before anything is made
        self.assertNotRegex(sh, r"\b(gh|curl|scp|rsync|git push)\b\s")                       # it never uploads
        self.assertIn("check_kit.sh", (ROOT / "macapp/build.sh").read_text())

    def test_the_app_asks_for_the_microphone_in_words_that_cover_the_daw_if_it_is_added(self):
        sh = (ROOT / "packaging/mac/build_dmg.sh").read_text()
        self.assertIn("NSMicrophoneUsageDescription</key><string>$mictext", sh)
        self.assertRegex(sh, r'mictext="[^"]*HypnoMix DAW[^"]*records from the audio input')
        self.assertNotIn("HypnomixEdition", sh)


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
    """There is one app and one installer; HypnoMix DAW is an add-on that is not available yet. The pages say only that."""
    PLAIN = [ROOT / f for f in ("hypnomix/app/setup.py", "hypnomix/app/setup.js", "packaging/README.md", "THIRD_PARTY.md",
                                "hypnomix/app/wiki/articles/18-setup.html", "hypnomix/app/wiki/articles/20-install.html")]

    def test_no_page_still_offers_two_downloads_or_a_full_app(self):
        gone = re.compile(r"(?i)two downloads|full download|the full (hypnomix|app)|hypnomix assistant|which hypnomix do you want|"
                          r"your download|full-mac|replaces (this|the) app|coming soon")
        for f in self.PLAIN + [ROOT / "hypnomix/app/wiki/articles/18-daw.html", ROOT / "hypnomix/app/wiki/articles/26-features.html",
                               ROOT / "hypnomix/app/wiki/articles/27-next.html", ROOT / "README.md", ROOT / "docs/APP.md", ROOT / "AGENTS.md"]:
            for m in gone.finditer(f.read_text()):
                self.fail(f"{f.name}: still describes the old plan of two downloads: {m.group(0)!r}")

    def test_setup_has_no_download_step_and_asks_which_daw(self):
        from hypnomix.app import setup as SU
        self.assertFalse(hasattr(SU, "DOWNLOADS") or hasattr(SU, "downloads"))
        self.assertEqual([d["id"] for d in SU.DAWS], ["live", "reaper", "hypnomix", "other"])
        js = (ROOT / "hypnomix/app/setup.js").read_text()
        for gone in ("pickDownload", "Which Hypnomix do you want", "data-edition"):
            self.assertNotIn(gone, js)
        self.assertIn("Add HypnoMix DAW", js)
        self.assertIn("data-engine", js)

    def test_the_licence_is_stated_where_the_engine_is_described(self):
        for f in ("THIRD_PARTY.md", "packaging/README.md", "hypnomix/app/wiki/articles/20-install.html", "hypnomix/app/wiki/articles/18-setup.html"):
            t = " ".join(re.sub(r"<[^>]+>", " ", (ROOT / f).read_text()).split())
            self.assertRegex(t, r"GNU General Public License", f)
            self.assertRegex(t, r"HypnoMix DAW" if "/wiki/" in f else r"Ardour", f)      # Ardour is named only where the disclosure belongs
            self.assertIn("source will be published with the first release that includes the engine", t, f)
            self.assertNotRegex(t, r"https?://[^\s\"')]*(engine|daw)[^\s\"')]*source", f)        # no invented source address

    def test_what_is_true_today_is_said_plainly(self):
        for f in ("README.md", "docs/APP.md", "packaging/README.md", "hypnomix/app/wiki/articles/18-setup.html",
                  "hypnomix/app/wiki/articles/20-install.html", "hypnomix/app/wiki/articles/18-daw.html"):
            t = " ".join(re.sub(r"<[^>]+>", " ", (ROOT / f).read_text()).split())
            self.assertRegex(t, r"(?i)not available yet", f)
            self.assertRegex(t, r"(?i)one (app|download|installer)", f)

    def test_what_was_not_verified_is_said_plainly(self):
        t = " ".join((ROOT / "packaging/README.md").read_text().split())
        for word in ("real sound card", "recording", "native File menu", "disk image", "signing", "Intel"):
            self.assertIn(word, t)

    def test_the_engine_finder_looks_in_the_bundle_in_one_place_only(self):
        from hypnomix.app import daw
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
                self.assertNotIn(eng, daw.candidates())                   # a program in another place is not found

    def test_an_app_in_daw_mode_opens_on_the_setup_the_first_time(self):
        from hypnomix.app import setup as SU
        with tempfile.TemporaryDirectory() as td, mock.patch.object(SU, "STATE", Path(td) / "setup.json"):
            self.assertFalse(SU.is_done())
            SU.STATE.write_text('{"done": true, "version": %d}' % SU.VERSION)
            self.assertTrue(SU.is_done())
            SU.STATE.write_text('{"done": true, "version": 0}')
            self.assertFalse(SU.is_done())                            # an older setup that gained a step is shown again
        server = (ROOT / "hypnomix/app/server.py").read_text()
        self.assertIn('"true" if DW.STATE["daw"] and SU.is_done() else "false"', server)

    def test_the_update_banner_says_plainly_a_release_has_no_installer_for_this_computer(self):
        js = (ROOT / "hypnomix/app/update.js").read_text()
        self.assertIn("U.no_download", js)
        self.assertIn("has no installer for this computer yet", js)
        self.assertNotIn("no_full_download", js)
