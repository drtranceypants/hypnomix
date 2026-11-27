"""The updater trusts nothing in the release it reads: names, addresses, redirects and the staged file are all checked."""
import hashlib, json, os, shutil, signal, stat, subprocess, sys, tempfile, threading, time, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from hypnomix.app import update as UP

REAL_ASSET_NAME = UP.asset_name           # Base replaces it; the edition tests put the real one back

NAME = "Hypnomix-mac-arm64.dmg"
BLOB = b"pretend this is a disk image" * 100
SUMS_OK = f"{hashlib.sha256(BLOB).hexdigest()}  {NAME}\n"


class Feed(BaseHTTPRequestHandler):
    release = {}
    sums = SUMS_OK
    blob = BLOB

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/feed":
            body = json.dumps(Feed.release).encode()
        elif self.path == "/sums":
            body = Feed.sums.encode()
        elif self.path == "/asset":
            body = Feed.blob
        elif self.path == "/full":
            body = Feed.blob
        elif self.path == "/to-evil":
            self.send_response(302)
            self.send_header("Location", "https://evil.example/x.dmg")
            self.end_headers()
            return
        elif self.path == "/to-file":
            self.send_response(302)
            self.send_header("Location", "file:///etc/hosts")
            self.end_headers()
            return
        elif self.path == "/to-http":
            self.send_response(302)
            self.send_header("Location", "http://github.com/drtranceypants/hypnomix/releases/x")
            self.end_headers()
            return
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.r = Path(self.td.name)
        self.srv = HTTPServer(("127.0.0.1", 0), Feed)
        threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"
        self.env = os.environ.get("HYPNOMIX_UPDATE_URL")
        os.environ["HYPNOMIX_UPDATE_URL"] = self.base + "/feed"
        Feed.sums, Feed.blob = SUMS_OK, BLOB
        Feed.release = dict(tag_name="v9.9.9", html_url="https://github.com/drtranceypants/hypnomix/releases/tag/v9.9.9",
                            body="notes", published_at="2026-11-26T00:00:00Z", assets=[
                                dict(name=NAME, browser_download_url=self.base + "/asset", size=len(BLOB)),
                                dict(name="SHA256SUMS.txt", browser_download_url=self.base + "/sums", size=10)])
        self.patches = [mock.patch.object(UP, "STATE", self.r / ".hypnomix" / "update.json"),
                        mock.patch.object(UP, "DIR", self.r / ".hypnomix" / "updates"),
                        mock.patch.object(UP, "API", self.base + "/feed"),
                        mock.patch.object(UP, "current", lambda: "0.1.0"),
                        mock.patch.object(UP, "kind", lambda: "mac"),
                        mock.patch.object(UP, "asset_name", lambda: NAME),
                        mock.patch.dict(UP.JOB, {"status": "idle", "got": 0, "size": 0, "file": "", "error": "", "sha": ""})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.srv.shutdown()
        self.srv.server_close()
        if self.env is None:
            os.environ.pop("HYPNOMIX_UPDATE_URL", None)
        else:
            os.environ["HYPNOMIX_UPDATE_URL"] = self.env
        self.td.cleanup()

    def download(self):
        UP.check(True)
        UP._download_args = None
        UP.JOB.update(status="downloading", got=0, error="")
        UP._download()


class Names(Base):
    def test_tags(self):
        for t in ("v0.1.5", "0.1.5", "1", "v2.0"):
            self.assertTrue(UP.good_tag(t), t)
        for t in ("../../x", "v1.2.3/../..", "1.2.3-rc1", "v", "", "1..2", "v1.2.3.4.5", "1.2\n", " 1.2", None, "..", "1.2/x"):
            self.assertFalse(UP.good_tag(t), repr(t))

    def test_a_bad_tag_ignores_the_release(self):
        for t in ("../../escape", "v1.2.3-evil", "v1/../../x"):
            Feed.release["tag_name"] = t
            v = UP.check(True)
            self.assertFalse(v["newer"], t)
            self.assertEqual(v["latest"], "")
            self.assertIn("ignored", v["error"])
            self.assertFalse(v["one_click"])

    def test_draft_and_prerelease_ignored(self):
        Feed.release["prerelease"] = True
        self.assertFalse(UP.check(True)["newer"])

    def test_good_release_is_seen(self):
        v = UP.check(True)
        self.assertTrue(v["newer"] and v["one_click"])
        self.assertEqual(v["latest"], "9.9.9")

    def test_an_old_state_file_with_a_bad_tag_is_ignored(self):
        UP.save({"latest": "../../x", "assets": {NAME: dict(url=self.base + "/asset", size=1)}, "checked": 1e12})
        self.assertFalse(UP.view()["newer"])

    def test_page_link_must_be_a_release_page(self):
        Feed.release["html_url"] = "javascript:alert(1)"
        self.assertEqual(UP.check(True)["page"], "")

    def test_asset_names_reduced_to_the_known_installers(self):
        a = [dict(name="../../evil.sh", browser_download_url=self.base + "/asset"),
             dict(name="sub/" + NAME, browser_download_url=self.base + "/asset"),
             dict(name="Other.dmg", browser_download_url=self.base + "/asset"),
             dict(name=NAME, browser_download_url=self.base + "/asset", size=3)]
        self.assertEqual(list(UP._clean_assets({"assets": a})), [NAME])


class OneInstaller(unittest.TestCase):
    """There is one installer per platform for everyone: no edition changes its name, and HypnoMix DAW is not inside it."""
    def test_the_names_are_the_ordinary_ones_whatever_is_inside_the_app(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            app = Path(td).resolve() / "Hypnomix.app"
            py = app / "Contents" / "Resources" / "python" / "bin" / "python3"
            with mock.patch.object(UP.sys, "executable", str(py)), mock.patch.object(UP.sys, "platform", "darwin"), \
                    mock.patch.object(UP.platform, "machine", lambda: "arm64"):
                self.assertEqual(UP.asset_name(), "Hypnomix-mac-arm64.dmg")
                kit = app / "Contents" / "Resources" / "engine" / "bin" / "hypnomix-engine"     # an old test build that carried the engine
                kit.parent.mkdir(parents=True)
                kit.write_text("#!/bin/sh\n")
                kit.chmod(0o755)
                self.assertEqual(UP.asset_name(), "Hypnomix-mac-arm64.dmg")                    # it updates to the ordinary app
                with mock.patch.object(UP.platform, "machine", lambda: "x86_64"):
                    self.assertEqual(UP.asset_name(), "Hypnomix-mac-intel.dmg")
        self.assertEqual(sorted(UP.ASSETS), ["Hypnomix-mac-arm64.dmg", "Hypnomix-mac-intel.dmg", "Hypnomix-windows-setup.exe", "SHA256SUMS.txt"])

    def test_the_edition_idea_is_gone(self):
        self.assertFalse(hasattr(UP, "edition"))
        self.assertNotIn("edition", UP.view())
        self.assertNotIn("no_full_download", UP.view())
        src = (Path(__file__).resolve().parents[1] / "hypnomix" / "app" / "update.py").read_text()
        self.assertNotRegex(src, r"full-|app_edition")


class Addresses(unittest.TestCase):
    def setUp(self):
        self.env = os.environ.pop("HYPNOMIX_UPDATE_URL", None)

    def tearDown(self):
        if self.env is not None:
            os.environ["HYPNOMIX_UPDATE_URL"] = self.env

    GOOD = "https://github.com/drtranceypants/hypnomix/releases/download/v1.2.3/Hypnomix-mac-arm64.dmg"

    def test_the_real_address_passes(self):
        UP.check_url(self.GOOD, "asset")
        UP.check_url("https://api.github.com/repos/drtranceypants/hypnomix/releases/latest", "api")

    def test_refused_asset_addresses(self):
        for u in ("file:///etc/passwd", "ftp://github.com/drtranceypants/hypnomix/releases/x", "http://github.com/drtranceypants/hypnomix/releases/x",
                  "https://evil.example/drtranceypants/hypnomix/releases/x", "https://github.com/someone/else/releases/x",
                  "https://github.com/drtranceypants/hypnomix/issues/1", "https://github.com.evil.example/drtranceypants/hypnomix/releases/x",
                  "https://user:pw@github.com/drtranceypants/hypnomix/releases/x", "https://github.com:8443/drtranceypants/hypnomix/releases/x",
                  "https://github.com/drtranceypants/hypnomix/releases/../../x", "data:text/plain,hi", "http://127.0.0.1:1/x",
                  "https://objects.githubusercontent.com/x"):
            with self.assertRaises(RuntimeError, msg=u):
                UP.check_url(u, "asset")

    def test_redirect_hosts(self):
        UP.check_url("https://objects.githubusercontent.com/x", "hop")
        UP.check_url("https://release-assets.githubusercontent.com/x", "hop")
        UP.check_url("https://github.com/x", "hop")
        for u in ("http://objects.githubusercontent.com/x", "https://evil.example/x", "https://githubusercontent.com.evil.example/x",
                  "file:///etc/hosts", "ftp://github.com/x", "http://127.0.0.1/x"):
            with self.assertRaises(RuntimeError, msg=u):
                UP.check_url(u, "hop")

    def test_local_feed_only_when_the_variable_is_set(self):
        with self.assertRaises(RuntimeError):
            UP.check_url("http://127.0.0.1:9/x", "asset")
        os.environ["HYPNOMIX_UPDATE_URL"] = "http://127.0.0.1:9/feed"
        UP.check_url("http://127.0.0.1:9/x", "asset")
        UP.check_url("http://localhost:9/x", "asset")
        for u in ("http://192.168.1.5/x", "http://example.com/x", "ftp://127.0.0.1/x", "file:///etc/hosts", "http://127.0.0.1.evil.example/x"):
            with self.assertRaises(RuntimeError, msg=u):
                UP.check_url(u, "asset")


class Redirects(Base):
    def test_redirect_off_github_is_refused(self):
        for path in ("/to-evil", "/to-http"):
            with self.assertRaises(RuntimeError, msg=path):
                UP._get(self.base + path, role="asset")

    def test_redirect_to_file_is_refused(self):
        with self.assertRaises(Exception):
            UP._get(self.base + "/to-file", role="asset")

    def test_file_address_is_never_opened(self):
        with self.assertRaises(RuntimeError):
            UP._get("file:///etc/hosts")


class Download(Base):
    def test_download_verifies_and_records_the_hash(self):
        self.download()
        self.assertEqual(UP.JOB["status"], "ready", UP.JOB)
        self.assertEqual(UP.JOB["sha"], hashlib.sha256(BLOB).hexdigest())
        f = Path(UP.JOB["file"])
        self.assertEqual(f.parent, UP.DIR)
        self.assertEqual(f.name, f"9.9.9-{NAME}")

    def test_wrong_checksum_is_deleted(self):
        Feed.sums = f"{'0' * 64}  {NAME}\n"
        self.download()
        self.assertEqual(UP.JOB["status"], "error")
        self.assertEqual(list(UP.DIR.glob("*-Hypnomix-*")), [])

    def test_a_tag_that_would_escape_the_folder_downloads_nothing(self):
        UP.check(True)
        s = UP.load()
        s["latest"] = "../../x"
        UP.save(s)
        UP.JOB.update(status="downloading")
        UP._download()
        self.assertEqual(UP.JOB["status"], "error")
        self.assertFalse((self.r / "x-Hypnomix-mac-arm64.dmg").exists())

    def test_an_edited_state_file_with_an_untrusted_address_downloads_nothing(self):
        UP.check(True)
        s = UP.load()
        s["assets"][NAME]["url"] = "https://evil.example/x.dmg"
        UP.save(s)
        UP.JOB.update(status="downloading")
        UP._download()
        self.assertEqual(UP.JOB["status"], "error")

    def test_not_newer_is_not_downloaded(self):
        with mock.patch.object(UP, "current", lambda: "9.9.9"):
            UP.JOB.update(status="downloading")
            UP._download()
        self.assertEqual(UP.JOB["status"], "error")


class Install(Base):
    def run_install(self, **kw):
        app = self.r / "Hypnomix.app"
        app.mkdir(exist_ok=True)
        with mock.patch.object(UP, "app_root", lambda: app), mock.patch.object(UP.subprocess, "Popen") as P, \
                mock.patch.object(UP.subprocess, "run", return_value=mock.Mock(stdout="")):
            UP.install(**kw)
        return P

    def test_install_passes_the_recorded_hash_to_the_helper(self):
        self.download()
        P = self.run_install()
        args = P.call_args[0][0]
        self.assertEqual(args[-2], hashlib.sha256(BLOB).hexdigest())
        self.assertEqual(args[-1], "9.9.9")                                    # the version the release claimed
        self.assertEqual(args[3], UP.JOB["file"])

    def test_a_file_swapped_after_the_check_is_refused_and_deleted(self):
        self.download()
        f = Path(UP.JOB["file"])
        f.write_bytes(b"something else entirely")
        with mock.patch.object(UP.subprocess, "Popen") as P:
            with self.assertRaises(RuntimeError):
                UP.install()
        P.assert_not_called()
        self.assertFalse(f.exists())

    def test_install_needs_a_newer_version(self):
        self.download()
        with mock.patch.object(UP, "current", lambda: "9.9.9"), mock.patch.object(UP.subprocess, "Popen") as P:
            with self.assertRaises(ValueError):
                UP.install()
        P.assert_not_called()

    def test_install_refuses_a_file_that_was_not_downloaded_by_the_app(self):
        self.download()
        other = UP.DIR / "elsewhere.dmg"
        other.write_bytes(b"x")
        UP.JOB["file"] = str(other)
        with self.assertRaises(ValueError):
            UP.install()

    def test_install_without_a_download_is_refused(self):
        with self.assertRaises(ValueError):
            UP.install()

    def test_the_helper_checks_the_hash_and_the_bundle(self):
        h = UP.MAC_HELPER
        self.assertIn("shasum -a 256", h)
        self.assertIn("codesign --verify --deep --strict", h)
        self.assertLess(h.index("codesign --verify"), h.index('kill "$p"'))       # before the old app is touched
        self.assertNotIn("xattr", h)                                           # nothing that touches quarantine
        self.assertNotIn("quarantine", h)
        self.assertIn("-Sha", UP.WIN_HELPER.replace("$Sha", "-Sha"))


class Modes(Base):
    def test_state_files_are_private(self):
        UP.save({"auto": True})
        self.assertEqual(stat.S_IMODE(UP.STATE.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(UP.STATE.parent.stat().st_mode), 0o700)

    def test_existing_loose_folder_and_file_are_tightened(self):
        d = self.r / ".hypnomix"
        d.mkdir()
        d.chmod(0o755)
        UP.STATE.write_text("{}")
        UP.STATE.chmod(0o644)
        UP.save({"auto": True})
        self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(UP.STATE.stat().st_mode), 0o600)

    def test_setup_state_is_private(self):
        from hypnomix.app import setup as SU
        with mock.patch.object(SU, "STATE", self.r / "h2" / "setup.json"):
            SU.save({"done": True})
            self.assertEqual(stat.S_IMODE(SU.STATE.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(SU.STATE.parent.stat().st_mode), 0o700)

    def test_tighten_home_leaves_the_users_own_home_alone(self):
        from hypnomix.core import paths
        h = self.r / "hx"
        h.mkdir()
        h.chmod(0o755)
        with mock.patch.object(paths, "HOME", h):
            paths.tighten_home()
        self.assertEqual(stat.S_IMODE(h.stat().st_mode), 0o700)
        with mock.patch.object(paths, "HOME", Path.home()):
            before = stat.S_IMODE(Path.home().stat().st_mode)
            paths.tighten_home()
            self.assertEqual(stat.S_IMODE(Path.home().stat().st_mode), before)


REAL = "https://github.com/drtranceypants/hypnomix/releases/download/"


class Review(Base):
    """What an independent review found getting through the first round of fixes."""
    def test_look_alike_digits_are_not_a_version(self):
        for t in ("\u0661.\u0660", "\uff11.\uff10.\uff10", "\u0663", "v9\u0660", "1.\u0660"):
            self.assertFalse(UP.good_tag(t), repr(t))
        Feed.release["tag_name"] = "v9\u0660"
        v = UP.check(True)
        self.assertEqual((v["latest"], v["newer"]), ("", False))
        self.assertEqual(UP.vkey("\u0669\u0669\u0669.\u0660"), ())             # never counted as a number

    def test_a_release_can_not_point_at_another_versions_files(self):
        def rel(tag, folder):
            return dict(tag_name=tag, assets=[dict(name=NAME, browser_download_url=f"{REAL}{folder}/{NAME}"),
                                              dict(name="SHA256SUMS.txt", browser_download_url=f"{REAL}{folder}/SHA256SUMS.txt")])
        os.environ.pop("HYPNOMIX_UPDATE_URL", None)
        self.assertEqual(UP._clean_assets(rel("v9.9.9", "v0.1.1")), {})            # a new name on an old release's files
        self.assertEqual(UP._clean_assets(rel("v9.9.9", "v9.9.8")), {})
        self.assertEqual(sorted(UP._clean_assets(rel("v9.9.9", "v9.9.9"))), sorted((NAME, "SHA256SUMS.txt")))
        self.assertEqual(len(UP._clean_assets(rel("9.9.9", "v9.9.9"))), 2)         # the state file keeps the tag without its "v"

    def test_an_edited_state_file_pointing_at_an_older_release_downloads_nothing(self):
        os.environ.pop("HYPNOMIX_UPDATE_URL", None)
        UP.save({"latest": "9.9.9", "assets": {NAME: dict(url=f"{REAL}v0.1.1/{NAME}", size=1),
                                               "SHA256SUMS.txt": dict(url=f"{REAL}v0.1.1/SHA256SUMS.txt", size=1)}})
        UP.JOB.update(status="downloading")
        with mock.patch.object(UP, "_open", side_effect=AssertionError("must not connect")):
            UP._download()
        self.assertEqual(UP.JOB["status"], "error")
        self.assertIn("trusted address", UP.JOB["error"])

    def test_encoded_dot_segments_do_not_pass(self):
        os.environ.pop("HYPNOMIX_UPDATE_URL", None)
        p = "https://github.com/drtranceypants/hypnomix/releases/"
        for tail in ("%2e%2e/%2e%2e/evil/repo/releases/download/x", "%2E%2E/x", "..%2fx", "..;/x", ".%2e/x", "..\\x",
                     "%252e%252e/x", "%2e/x", "./x", "a/../x", "a;b/x", "a%5cb/x", "%25252e%25252e/x"):
            with self.assertRaises(RuntimeError, msg=tail):
                UP.check_url(p + tail, "asset")
        UP.check_url(p + "download/v1.2.3/Hypnomix-mac-arm64.dmg", "asset")
        self.assertEqual(UP._clean_assets(dict(tag_name="v1.2.3", assets=[dict(
            name=NAME, browser_download_url=p + "download/v1.2.3/%48ypnomix-mac-arm64.dmg")])), {})

    def test_the_proxy_settings_are_still_used(self):
        seen = []
        real = UP.urllib.request.OpenerDirector.add_handler
        with mock.patch.object(UP.urllib.request.OpenerDirector, "add_handler",
                               lambda o, h: (seen.append(type(h).__name__), real(o, h))[1]):
            UP._opener()
        self.assertIn("ProxyHandler", seen)
        self.assertIn("_Redirects", seen)                                      # and every hop is still checked
        with mock.patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:9", "no_proxy": ""}):
            o = UP._opener()
            self.assertTrue(any(isinstance(h, UP.urllib.request.ProxyHandler) for h in o.handle_open.get("http", [])))

    def test_the_page_link_is_checked_when_shown_too(self):
        UP.check(True)
        for bad in ("javascript:alert(1)", "https://evil.example/x", "file:///etc/hosts"):
            s = UP.load()
            s["page"] = bad
            UP.save(s)
            self.assertEqual(UP.view()["page"], "", bad)

    def test_a_hand_edited_state_file_of_the_wrong_shape_does_not_break_the_page(self):
        for state in ([], "x", 5, {"assets": []}, {"assets": {NAME: "x"}}, {"assets": {NAME: ["y"]}, "latest": "9.9.9"},
                      {"assets": {NAME: {"url": 1, "size": "big"}}, "latest": "9.9.9", "notes": None, "error": 7}):
            UP.STATE.parent.mkdir(parents=True, exist_ok=True)
            UP.STATE.write_text(json.dumps(state))
            v = UP.view()
            self.assertIsInstance(v["size"], int)
            self.assertFalse(v["one_click"] and not isinstance(state, dict))
        UP.STATE.write_text(json.dumps({"latest": "9.9.9", "assets": {NAME: {"url": 1, "size": "big"}}}))
        UP.JOB.update(status="downloading")
        UP._download()                                                         # a plain error, not an exception
        self.assertEqual(UP.JOB["status"], "error")

    def test_the_helper_compares_the_version_inside_the_new_app(self):
        h = UP.MAC_HELPER
        self.assertIn("CFBundleShortVersionString", h)
        self.assertLess(h.index("CFBundleShortVersionString"), h.index('kill "$p"'))   # before the old app is touched
        self.assertNotIn("xattr", h)
        self.assertNotIn("quarantine", h)
        self.assertIn("-LiteralPath", UP.WIN_HELPER)
        self.assertNotIn("-Path $Setup", UP.WIN_HELPER)

    def test_the_helper_version_compare_rule(self):
        import shutil, subprocess
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("no bash")
        line = next(l for l in UP.MAC_HELPER.splitlines() if l.startswith("norm()"))
        def norm(v):
            return subprocess.run([bash, "-c", f'{line}\nnorm "$1"', "x", v], capture_output=True, text=True).stdout.strip()
        self.assertEqual(norm("v1.2.0"), norm("1.2"))
        self.assertEqual(norm("0.1.5"), "0.1.5")
        self.assertNotEqual(norm("0.1.1"), norm("9.9.9"))
        self.assertNotEqual(norm("1.10"), norm("1.1"))


class PrivateFolders(unittest.TestCase):
    def test_private_dir_makes_every_missing_folder_0700(self):
        from hypnomix.core import paths
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "a" / ".hypnomix" / "updates"
            paths.private_dir(d)
            for p in (d, d.parent, d.parent.parent):
                self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o700, str(p))

    def test_private_dir_leaves_the_home_folder_and_above_alone(self):
        from hypnomix.core import paths
        with tempfile.TemporaryDirectory() as t:
            home = Path(t) / "home"
            (home / "x").mkdir(parents=True)
            home.chmod(0o755)
            with mock.patch.object(Path, "home", classmethod(lambda cls: home)):
                paths.private_dir(home)
                self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o755)
                paths.private_dir(Path(t))
                self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o755)
                paths.write_private(home / "f.json", "{}")
                self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o755)
                self.assertEqual(stat.S_IMODE((home / "f.json").stat().st_mode), 0o600)
                paths.private_dir(home / ".hypnomix" / "updates")              # made 0700 even though home is left alone
                self.assertEqual(stat.S_IMODE((home / ".hypnomix").stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o755)

    def test_diskcare_does_not_tighten_a_home_folder_either(self):
        from hypnomix.app import diskcare as DC
        from hypnomix.core import paths
        with tempfile.TemporaryDirectory() as t:
            home = Path(t) / "home"
            home.mkdir()
            home.chmod(0o755)
            # HYPNOMIX_USER_HOME too: Disk care reads the free space of that folder, which may not exist on a run set up by hand
            with mock.patch.dict(os.environ, {"HYPNOMIX_HOME": str(home), "HYPNOMIX_USER_HOME": str(home)}), \
                    mock.patch.object(Path, "home", classmethod(lambda cls: home)):
                DC.settings({"auto": True})
            self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE((home / "diskcare.json").stat().st_mode), 0o600)



OLD_FULL = "Hypnomix-full-mac-arm64.dmg"          # a name an earlier plan used: it is not an installer any more
OLD_BLOB = b"the old full image" * 100


class OneNamePerPlatform(Base):
    """The updater offers one installer name per platform, and says plainly when a release does not carry it."""
    def setUp(self):
        super().setUp()
        self.extra = [mock.patch.object(UP, "asset_name", REAL_ASSET_NAME),
                      mock.patch.object(UP.platform, "machine", lambda: "arm64")]
        for p in self.extra:
            p.start()
        Feed.sums = SUMS_OK + f"{hashlib.sha256(OLD_BLOB).hexdigest()}  {OLD_FULL}\n"

    def tearDown(self):
        for p in self.extra:
            p.stop()
        super().tearDown()

    def release(self, *names):
        assets = [dict(name="SHA256SUMS.txt", browser_download_url=self.base + "/sums", size=10)]
        for n in names:
            assets.append(dict(name=n, browser_download_url=self.base + ("/asset" if n == NAME else "/full"), size=len(BLOB)))
        Feed.release["assets"] = assets
        UP.save({})
        return UP.check(True)

    def test_the_ordinary_installer_is_offered_whatever_else_the_release_holds(self):
        for names in ((NAME,), (NAME, OLD_FULL)):
            v = self.release(*names)
            self.assertEqual(UP.asset_name(), NAME)
            self.assertEqual((v["one_click"], v["no_download"]), (True, False), names)
            self.assertNotIn(OLD_FULL, UP.load()["assets"])                 # a file with another name is not kept at all

    def test_a_release_without_this_computers_installer_is_said_plainly_and_nothing_is_offered(self):
        for names in ((), (OLD_FULL,), ("Hypnomix-mac-intel.dmg",)):
            v = self.release(*names)
            self.assertTrue(v["newer"])
            self.assertEqual((v["one_click"], v["no_download"]), (False, True), names)
            with self.assertRaises(ValueError):
                UP.download()
            self.assertEqual(UP.JOB["status"], "idle")
            with self.assertRaises(ValueError):
                UP.install()
            # even a stray state file naming an image does not make _download fetch anything
            UP._download()
            self.assertEqual(UP.JOB["status"], "error")
            self.assertEqual(list(UP.DIR.glob("*.dmg")) + list(UP.DIR.glob("*.part")), [])
            UP.JOB.update(status="idle", error="")
        js = (Path(__file__).resolve().parents[1] / "hypnomix" / "app" / "update.js").read_text()
        self.assertIn("U.no_download", js)
        self.assertIn("has no installer for this computer yet", js)

    def test_the_installer_is_fetched_and_checked_by_its_own_name(self):
        self.release(NAME)
        UP._download()
        self.assertEqual(UP.JOB["status"], "ready", UP.JOB)
        self.assertEqual(Path(UP.JOB["file"]).name, f"9.9.9-{NAME}")
        self.assertEqual(UP.JOB["sha"], hashlib.sha256(BLOB).hexdigest())

    def test_a_release_with_no_checksum_line_for_the_installer_installs_nothing(self):
        Feed.sums = f"{hashlib.sha256(OLD_BLOB).hexdigest()}  {OLD_FULL}\n"       # a line for another file only
        self.release(NAME)
        UP._download()
        self.assertEqual(UP.JOB["status"], "error")
        self.assertIn("no checksum", UP.JOB["error"])
        self.assertEqual(list(UP.DIR.glob("*.dmg")), [])

    def test_an_app_that_was_a_test_build_with_the_engine_inside_updates_like_any_other(self):
        """Its bundle is replaced by the ordinary app; HypnoMix DAW is then found at the add-on's place or offered from Setup."""
        from hypnomix.app import daw
        with tempfile.TemporaryDirectory() as td:
            app = Path(td).resolve() / "Hypnomix.app"
            py = app / "Contents" / "Resources" / "python" / "bin" / "python3"
            kit = app / "Contents" / "Resources" / "engine" / "bin" / "hypnomix-engine"
            kit.parent.mkdir(parents=True)
            kit.write_text("#!/bin/sh\n")
            kit.chmod(0o755)
            with mock.patch.object(UP.sys, "executable", str(py)), mock.patch.object(UP.sys, "platform", "darwin"), \
                    mock.patch.object(daw.sys, "executable", str(py)), mock.patch.dict(os.environ, {"HYPNOMIX_ENGINE": ""}), \
                    mock.patch.object(daw, "_conf", lambda: {}):
                v = self.release(NAME)
                self.assertEqual((UP.asset_name(), v["one_click"]), (NAME, True))
                self.assertEqual(daw.find_engine(), kit)                    # until the swap, it keeps working from its own bundle
                kit.unlink()                                                # after the swap there is no bundled engine
                self.assertIsNone(daw.find_engine())                        # ...and Setup offers HypnoMix DAW as the add-on


class UnsavedSession(Base):
    """Install and restart closes the app, and the DAW session with it: refused while it has unsaved changes."""
    def run_install(self):
        app = self.r / "Hypnomix.app"
        app.mkdir(exist_ok=True)
        with mock.patch.object(UP, "app_root", lambda: app), mock.patch.object(UP.subprocess, "Popen") as P, \
                mock.patch.object(UP.subprocess, "run", return_value=mock.Mock(stdout="")):
            try:
                UP.install()
            finally:
                self.P = P

    def test_refused_while_the_session_is_dirty(self):
        from hypnomix.app import daw
        self.download()
        with mock.patch.object(daw, "dirty", lambda: True, create=True):
            with self.assertRaises(UP.Unsaved):
                self.run_install()
            self.P.assert_not_called()
            self.assertTrue(Path(UP.JOB["file"]).exists())             # the checked download stays for later
            code, body = UP.handle_post("/api/update/install", {})
            self.assertEqual((code, body["dirty"]), (409, True))
            self.assertIn("not saved", body["error"])
        self.assertEqual(UP.JOB["status"], "ready")                    # nothing was started
        with mock.patch.object(daw, "dirty", lambda: False, create=True):
            self.run_install()
            self.P.assert_called_once()

    def test_a_clean_session_or_an_app_without_the_function_installs(self):
        from hypnomix.app import daw
        self.download()
        had = hasattr(daw, "dirty")
        with mock.patch.object(daw, "dirty", lambda: False, create=True):
            self.assertFalse(UP.unsaved())
        if not had:
            self.assertFalse(UP.unsaved())                             # no daw.dirty() at all: nothing to lose
        with mock.patch.object(daw, "dirty", mock.Mock(side_effect=RuntimeError("boom")), create=True):
            self.assertFalse(UP.unsaved())                             # a fault there never blocks updates for good

    def test_the_command_line_install_asks_too(self):
        from hypnomix.app import daw
        f = self.r / "x.dmg"
        f.write_bytes(b"x")
        with mock.patch.object(daw, "dirty", lambda: True, create=True), mock.patch.object(UP.subprocess, "Popen") as P:
            with self.assertRaises(UP.Unsaved):
                UP.install(str(f))
        P.assert_not_called()

    def test_the_helper_is_told_the_engine_to_wait_for(self):
        from hypnomix.app import daw
        self.download()
        eng = mock.Mock(mode="engine", proc=mock.Mock(pid=4242, poll=lambda: None))
        with mock.patch.object(daw, "ENGINE", eng), mock.patch.object(daw, "dirty", lambda: False, create=True):
            self.run_install()
        args = self.P.call_args[0][0]
        self.assertEqual(args[6], "4242")                              # after the server's pid, before the log
        self.assertEqual(args[-1], "9.9.9")
        with mock.patch.object(daw, "ENGINE", mock.Mock(mode="attached", proc=None)):
            self.assertEqual(UP.engine_pid(), "")                      # a window it only attached to is not waited for


class HelperWaitsForTheEngine(unittest.TestCase):
    """The Mac helper's stop step, run for real against stand-in processes: it waits for the app, the server and the
    engine, longer than the engine's own stop time, and only then kills what is left (the engine's whole group)."""
    def block(self):
        h = UP.MAC_HELPER
        return h[h.index("# stop-begin"):h.index("# stop-end")]

    def start(self, code, **kw):
        """A process that is not our child (so it is not a zombie after it ends): its pid is printed by a parent that exits."""
        out = subprocess.run([sys.executable, "-c",
                              "import subprocess,sys;p=subprocess.Popen([sys.executable,'-c',sys.argv[1]],start_new_session=True,"
                              "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL);print(p.pid)", code],
                             capture_output=True, text=True).stdout.strip()
        pid = int(out)
        self.addCleanup(self.kill, pid)
        return pid

    @staticmethod
    def kill(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            pass

    @staticmethod
    def alive(pid):
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def run_block(self, grace, app="", server="", engine=""):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("no bash")
        t = time.time()
        r = subprocess.run([bash, "-c", self.block()], capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, APP_PID=str(app), SERVER_PID=str(server), ENGINE_PID=str(engine), HYPNOMIX_UPDATE_GRACE=str(grace)))
        return time.time() - t, r.stdout

    SLOW_QUIT = "import signal,time\nsignal.signal(signal.SIGTERM,lambda *a:(time.sleep(2.5),exit(0)))\ntime.sleep(60)"
    DEAF = "import signal,time\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(60)"

    def test_it_waits_for_a_slow_server_instead_of_killing_it(self):
        server = self.start(self.SLOW_QUIT)
        time.sleep(0.5)                                               # its handler is set
        took, out = self.run_block(20, server=server)
        self.assertGreaterEqual(took, 2.0)                           # it waited out the slow quit...
        self.assertLess(took, 10)
        self.assertNotIn("stopping it now", out)                     # ...and killed nothing
        self.assertFalse(self.alive(server))

    def test_it_waits_for_a_lingering_engine_when_the_server_is_already_gone(self):
        # the server pid is not running at all, so only the engine holds the wait open; it is let finish, not killed
        with tempfile.TemporaryDirectory() as td:
            marker = os.path.join(td, "ended-by-itself")
            engine = self.start("import time\ntime.sleep(3)\nopen(%r,'w').write('done')" % marker)
            gone = self.start("pass")
            time.sleep(0.5)
            took, out = self.run_block(20, server=gone, engine=engine)
            self.assertGreaterEqual(took, 2.0)                       # it waited for the engine...
            self.assertNotIn("stopping it now", out)
            time.sleep(0.3)
            self.assertTrue(os.path.exists(marker))                  # ...which finished its own way, not killed early
            self.assertFalse(self.alive(engine))

    def test_what_will_not_quit_is_killed_after_the_wait_engine_group_included(self):
        server, engine = self.start(self.DEAF), self.start(self.DEAF)
        time.sleep(0.5)
        took, out = self.run_block(2, server=server, engine=engine)
        self.assertGreaterEqual(took, 2.0)
        self.assertIn("stopping it now", out)
        time.sleep(0.5)
        self.assertFalse(self.alive(server))
        self.assertFalse(self.alive(engine))

    def test_the_wait_is_longer_than_the_engine_stop_time(self):
        from hypnomix.app import daw
        import inspect
        default = int(__import__("re").search(r'HYPNOMIX_UPDATE_GRACE:-(\d+)', UP.MAC_HELPER).group(1))
        sig = inspect.signature(daw.Engine.stop).parameters["timeout"].default
        self.assertGreater(default, sig + 5 + 5)                      # the engine's stop (TERM wait, then 5 s after a kill) plus margin
        self.assertIn("kill -9 -- \"-$ENGINE_PID\"", UP.MAC_HELPER)   # its whole process group

    def test_with_nothing_to_wait_for_it_does_not_wait(self):
        took, _ = self.run_block(30)
        self.assertLess(took, 2)


if __name__ == "__main__":
    unittest.main()
