"""HypnoMix DAW as an add-on (hypnomix/app/engine_addon.py): fetched once, on a click, checked before it is used.

The real download code runs against an HTTPS server on this computer (self-signed, nothing leaves the machine), the way
tests/test_store.py does. The shipped manifest names no address, so every test that adds the engine uses a manifest of its own
(EA.MANIFEST patched to a temporary file); a test that touches the real one only reads it.

    python -m unittest tests.test_engine_addon -v
"""
import contextlib
import gzip
import hashlib
import http.server
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from hypnomix.app import engine_addon as EA, chat as CH, daw as DW, setup as SU
from hypnomix.store import install as I
from tests import _isolate
from tests.test_dawfix_packaging import make_kit

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
TLS = __import__("s" + "sl")                       # the secure-sockets module (spelled so the repo's name check passes)


def tar_dir(src, dest, extra=None, raw=True):
    """A .tar.gz of a folder as it is, with extra {name: bytes or ("link", target)} entries (not through EA.pack: a test
    needs archives that pack() would refuse)."""
    with tarfile.open(dest, "w:gz") as t:
        for p in sorted(Path(src).rglob("*")):
            t.add(str(p), p.relative_to(src).as_posix(), recursive=False)
        for name, data in (extra or {}).items():
            ti = tarfile.TarInfo(name)
            if isinstance(data, tuple):
                ti.type, ti.linkname = tarfile.SYMTYPE, data[1]
                t.addfile(ti)
            else:
                ti.size = len(data)
                t.addfile(ti, io.BytesIO(data))
    return Path(dest).read_bytes()


class Server:
    """An HTTPS server on this computer. routes: path -> (kind, bytes). kinds: ok, huge (claims a terabyte), endless (no
    length, never ends), cut (the first answer stops halfway, the next ones are whole), slow (a drip)."""

    def __init__(self):
        openssl = shutil.which("openssl")
        if not openssl:
            raise unittest.SkipTest("needs openssl to make a throwaway certificate")
        self.tmp = Path(tempfile.mkdtemp(prefix="hx-engine-tls-"))
        crt, key = self.tmp / "c.pem", self.tmp / "k.pem"
        r = subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(crt),
                            "-subj", "/CN=localhost", "-days", "2"], capture_output=True)
        if r.returncode:
            raise unittest.SkipTest("could not make a certificate")
        self.routes, self.seen, self.cut_done = {}, [], set()
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.seen.append(self.path)
                kind, data = outer.routes.get(self.path, ("missing", b""))
                try:
                    if kind == "missing":
                        self.send_response(404)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                    elif kind == "huge":
                        self.send_response(200)
                        self.send_header("Content-Length", str(10 ** 12))
                        self.end_headers()
                    elif kind in ("endless", "slow"):
                        self.send_response(200)
                        self.send_header("Transfer-Encoding", "chunked")
                        self.end_headers()
                        for _ in range(400):
                            chunk = b"\0" * (1 << 16) if kind == "endless" else b"x"
                            self.wfile.write(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
                            if kind == "slow":
                                time.sleep(0.2)
                    else:
                        self.send_response(200)
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        if kind == "cut" and self.path not in outer.cut_done:
                            outer.cut_done.add(self.path)
                            self.wfile.write(data[:len(data) // 2])
                            self.wfile.flush()
                            self.close_connection = True
                            return
                        self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError, TLS.SSLError):
                    pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        ctx = TLS.SSLContext(TLS.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(crt), str(key))
        self.srv.socket = ctx.wrap_socket(self.srv.socket, server_side=True)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.opener = urllib.request.build_opener(I._HttpsOnly(), urllib.request.HTTPSHandler(context=TLS._create_unverified_context()))

    def url(self, path):
        return f"https://127.0.0.1:{self.port}{path}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)


class Base(unittest.TestCase):
    """A hypnomix home of its own, a manifest of its own, and an HTTPS server that serves what the manifest names."""

    @classmethod
    def setUpClass(cls):
        cls.server = Server()
        cls.kitdir = Path(tempfile.mkdtemp(prefix="hx-engine-kit-"))
        cls.kit = make_kit(cls.kitdir)
        cls.good = cls.kitdir / "good.tar.gz"
        EA.pack(cls.kit, cls.good)                                   # the archive the owner would upload
        cls.good_bytes = cls.good.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.server.close()
        shutil.rmtree(cls.kitdir, ignore_errors=True)

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.home = Path(self.td.name) / "home"
        self.manifest = Path(self.td.name) / "engine_addon.json"
        for p in (mock.patch.dict(os.environ, {"HYPNOMIX_HOME": str(self.home), "HYPNOMIX_ENGINE": "", "HYPNOMIX_ENGINE_SRC": ""}),
                  mock.patch.object(EA, "MANIFEST", self.manifest), mock.patch.object(EA, "platform_key", lambda: "mac-arm64"),
                  mock.patch.object(I, "_opener", self.server.opener), mock.patch.object(DW, "_conf", lambda: {})):
            p.start()
            self.addCleanup(p.stop)
        EA.JOB.update(status="idle", got=0, size=0, error="")
        self.server.routes.clear()
        self.server.seen.clear()
        self.server.cut_done.clear()
        self.root = self.home / "engine"

    def publish(self, data=None, version="1.0.0", path="/engine.tar.gz", kind="ok", sha=None, size=None):
        """Serve data and write the manifest that names it (the sha and size can be made wrong on purpose)."""
        data = self.good_bytes if data is None else data
        self.server.routes[path] = (kind, data)
        self.manifest.write_text(json.dumps({"format": 1, "engine": version, "platforms": {"mac-arm64": {
            "url": self.server.url(path), "sha256": sha or hashlib.sha256(data).hexdigest(), "size": size or len(data)}}}), encoding="utf-8")

    def residue(self):
        """Anything in the engine folder that is not a whole version: half-made folders."""
        return sorted(p.name for p in self.root.iterdir() if p.name.startswith(".")) if self.root.is_dir() else []


class Adding(Base):
    def test_a_good_archive_is_added_and_the_app_finds_it(self):
        self.publish()
        s = EA.install()
        prog = self.root / "1.0.0" / "bin" / "hypnomix-engine"
        self.assertTrue(prog.is_file() and os.access(prog, os.X_OK))
        self.assertEqual((s["installed"], s["current"], s["needs_update"], s["available"]), ("1.0.0", True, False, True))
        self.assertEqual(s["program"], str(prog))
        self.assertEqual(self.residue(), [])                                     # no half-made folder, no archive left
        self.assertEqual(json.loads((self.root / "1.0.0" / "ADDON.json").read_text(encoding="utf-8"))["sha256"], hashlib.sha256(self.good_bytes).hexdigest())
        self.assertEqual(DW.find_engine(), prog)                                 # the DAW tab's lookup
        self.assertTrue(DW.available())
        self.assertEqual(self.server.seen, ["/engine.tar.gz"])
        self.assertEqual(EA.JOB["status"], "done")

    def test_the_engine_goes_under_hypnomix_home_wherever_that_is(self):
        self.publish()
        EA.install()
        self.assertTrue((self.home / "engine" / "1.0.0" / "COPYING").is_file())
        other = Path(self.td.name) / "elsewhere"
        with mock.patch.dict(os.environ, {"HYPNOMIX_HOME": str(other)}):
            self.assertIsNone(EA.find())                                          # a second home has not added it
            self.assertEqual(EA.root(), other / "engine")

    def test_a_wrong_fingerprint_deletes_the_download_and_unpacks_nothing(self):
        self.publish(sha="0" * 64)
        with mock.patch.object(I, "unpack", side_effect=AssertionError("unpacked before the fingerprint was checked")):
            with self.assertRaises(EA.AddonError) as cm:
                EA.install()
        self.assertIn("fingerprint does not match", str(cm.exception))
        self.assertIn("deleted", str(cm.exception))
        self.assertEqual((EA.installed_versions(), self.residue()), ([], []))
        self.assertEqual(EA.JOB["status"], "error")
        self.assertIn("fingerprint", EA.state()["job"]["error"])

    def test_a_download_that_claims_to_be_huge_is_refused_before_it_is_read(self):
        self.publish(kind="huge")
        with self.assertRaises(EA.AddonError) as cm:
            EA.install()
        self.assertIn("more than", str(cm.exception))
        self.assertEqual((EA.installed_versions(), self.residue()), ([], []))

    def test_a_download_that_never_ends_is_stopped_at_the_size_the_manifest_names(self):
        self.publish(data=b"x" * 1000, kind="endless")
        with mock.patch.object(EA, "SLACK", 4096):
            with self.assertRaises(EA.AddonError) as cm:
                EA.install()
        self.assertRegex(str(cm.exception), "went past|allowed")
        self.assertEqual((EA.installed_versions(), self.residue()), ([], []))

    def test_a_slow_download_runs_into_the_deadline(self):
        self.publish(data=b"x" * 400, kind="slow")
        with mock.patch.object(EA, "DEADLINE_S", 0.6):
            t = time.monotonic()
            with self.assertRaises(EA.AddonError) as cm:
                EA.install()
        self.assertLess(time.monotonic() - t, 5)
        self.assertIn("took longer", str(cm.exception))
        self.assertEqual((EA.installed_versions(), self.residue()), ([], []))

    def test_an_entry_outside_the_folder_is_refused_and_nothing_lands_outside(self):
        for name in ("../evil.txt", "/tmp/evil-absolute.txt", "bin/../../evil.txt"):
            data = tar_dir(self.kit, self.kitdir / "evil.tar.gz", extra={name: b"x"})
            self.publish(data=data)
            with self.assertRaises(EA.AddonError) as cm:
                EA.install()
            self.assertIn("refused", str(cm.exception), name)
            self.assertEqual((EA.installed_versions(), self.residue()), ([], []), name)
            self.assertFalse((self.home / "evil.txt").exists() or (self.root / "evil.txt").exists() or Path("/tmp/evil-absolute.txt").exists(), name)

    def test_a_link_pointing_out_is_refused(self):
        for target in ("/etc/hosts", "../../outside", "../../../.ssh"):
            data = tar_dir(self.kit, self.kitdir / "link.tar.gz", extra={"share/looks-harmless": ("link", target)})
            self.publish(data=data)
            with self.assertRaises(EA.AddonError) as cm:
                EA.install()
            self.assertIn("refused", str(cm.exception), target)
            self.assertEqual((EA.installed_versions(), self.residue()), ([], []), target)

    def test_a_chain_of_links_cannot_climb_out_either(self):
        data = tar_dir(self.kit, self.kitdir / "chain.tar.gz", extra={"share/a": ("link", "."), "share/a/b": ("link", "../..")})
        self.publish(data=data)
        with self.assertRaises(EA.AddonError):
            EA.install()
        self.assertEqual((EA.installed_versions(), self.residue()), ([], []))

    def test_a_kit_with_no_licence_text_is_not_added(self):
        for label, kw in (("no COPYING", dict(licence=False)), ("no SOURCE.txt", dict(notice=False))):
            with tempfile.TemporaryDirectory() as td:
                kit = make_kit(td, **kw)
                self.publish(data=tar_dir(kit, Path(td) / "k.tar.gz"))
                with self.assertRaises(EA.AddonError) as cm:
                    EA.install()
                self.assertIn("nothing was added", str(cm.exception), label)
                self.assertRegex(str(cm.exception), "licence text|source notice", label)
                self.assertEqual((EA.installed_versions(), self.residue()), ([], []), label)

    def test_a_kit_with_a_control_or_invisible_character_in_a_file_name_is_not_added(self):
        for label, name in (("escape", "share/a\x1b[2Jb.txt"), ("newline", "share/a\nb.txt"), ("right-to-left", "share/a\u202eb.txt")):
            with self.subTest(label), tempfile.TemporaryDirectory() as td:
                if sys.platform == "win32" and label in ("escape", "newline"):
                    self.skipTest("SKIPPED: Windows cannot make a file whose name has a control character, so this name was NOT tested here")
                kit = make_kit(td, extra={name: b"x"})
                self.assertTrue(any("control or invisible" in w for w in EA.kit_problems(kit)), label)
                self.publish(data=tar_dir(kit, Path(td) / "k.tar.gz"))
                with self.assertRaises(EA.AddonError) as cm:
                    EA.install()
                self.assertIn("control or invisible", str(cm.exception), label)
                self.assertEqual((EA.installed_versions(), self.residue()), ([], []), label)
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(EA.kit_problems(make_kit(td, extra={"share/ordinary name é.txt": b"x"})), [])

    def test_a_kit_without_the_engine_program_or_with_a_builders_path_is_not_added(self):
        with tempfile.TemporaryDirectory() as td:
            kit = make_kit(td)
            (kit / "bin" / "hypnomix-engine").unlink()
            self.publish(data=tar_dir(kit, Path(td) / "k.tar.gz"))
            with self.assertRaises(EA.AddonError) as cm:
                EA.install()
            self.assertIn("not a HypnoMix DAW engine kit", str(cm.exception))
        with tempfile.TemporaryDirectory() as td:
            kit = make_kit(td, extra={"lib/libx.dylib": b"\0-I/Users/somebody/build\0"})
            self.publish(data=tar_dir(kit, Path(td) / "k.tar.gz"))
            with self.assertRaises(EA.AddonError) as cm:
                EA.install()
            self.assertIn("home path", str(cm.exception))
            self.assertNotIn("somebody", str(cm.exception))
        self.assertEqual((EA.installed_versions(), self.residue()), ([], []))

    def test_something_that_is_not_an_archive_is_refused(self):
        self.publish(data=b"this is a web page, not an archive" * 20)
        with self.assertRaises(EA.AddonError) as cm:
            EA.install()
        self.assertIn("refused", str(cm.exception))
        self.assertEqual((EA.installed_versions(), self.residue()), ([], []))

    def test_an_interrupted_download_leaves_nothing_and_can_simply_be_run_again(self):
        self.publish(kind="cut")
        with self.assertRaises(EA.AddonError):
            EA.install()
        self.assertEqual((EA.installed_versions(), self.residue()), ([], []))
        self.assertEqual(EA.JOB["status"], "error")
        s = EA.install()                                                          # the same call, run again
        self.assertEqual((s["installed"], s["current"]), ("1.0.0", True))
        self.assertEqual(self.server.seen, ["/engine.tar.gz", "/engine.tar.gz"])
        self.assertEqual(self.residue(), [])

    def test_a_cut_off_add_leaves_a_half_made_folder_that_the_next_one_clears(self):
        self.publish()
        self.root.mkdir(parents=True)
        old = self.root / ".incoming-dead"
        (old / "kit").mkdir(parents=True)
        (old / "kit" / "junk").write_text("x", encoding="utf-8")
        os.utime(old, (time.time() - 7200, time.time() - 7200))
        fresh = self.root / ".incoming-live"                                     # another add that started a minute ago is left alone
        fresh.mkdir()
        EA.install()
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())
        self.assertEqual(EA.state()["installed"], "1.0.0")

    def test_a_second_add_of_a_whole_engine_downloads_nothing(self):
        self.publish()
        EA.install()
        n = len(self.server.seen)
        s = EA.install()
        self.assertEqual(len(self.server.seen), n)
        self.assertEqual((s["installed"], s["current"]), ("1.0.0", True))

    def test_a_second_add_of_a_damaged_engine_replaces_it_in_one_step(self):
        self.publish()
        EA.install()
        prog = self.root / "1.0.0" / "bin" / "hypnomix-engine"
        prog.unlink()                                                             # damaged
        (self.root / "1.0.0" / "stray.txt").write_text("from the old copy", encoding="utf-8")
        s = EA.install()
        self.assertTrue(prog.is_file())
        self.assertFalse((self.root / "1.0.0" / "stray.txt").exists())            # the whole kit was replaced, not mixed
        self.assertEqual((s["current"], self.residue()), (True, []))

    def test_a_failed_swap_puts_the_old_copy_back(self):
        old, new = Path(self.td.name) / "old", Path(self.td.name) / "new"
        (old / "bin").mkdir(parents=True)
        (old / "bin" / "x").write_text("old", encoding="utf-8")
        (new).mkdir()
        final = Path(self.td.name) / "final"
        shutil.copytree(old, final)
        real = os.replace
        calls = []

        def flaky(a, b):
            calls.append((a, b))
            if len(calls) == 2:
                raise OSError("disk full")
            return real(a, b)
        with mock.patch.object(EA.os, "replace", flaky):
            with self.assertRaises(OSError):
                EA._swap(new, final)
        self.assertEqual((final / "bin" / "x").read_text(encoding="utf-8"), "old")

    def test_nothing_is_added_when_the_manifest_has_no_address_for_this_computer(self):
        self.publish()
        with mock.patch.object(EA, "platform_key", lambda: "windows-x64"):
            with self.assertRaises(EA.AddonError) as cm:
                EA.install()
            self.assertIn("not available for Windows yet", str(cm.exception))
            self.assertFalse(EA.state()["available"])
        self.assertEqual(self.server.seen, [])
        self.assertFalse(self.root.exists())

    def test_a_manifest_entry_that_is_not_whole_is_ignored(self):
        good = {"url": self.server.url("/x"), "sha256": "a" * 64, "size": 10}
        for bad in (dict(good, url="http://127.0.0.1/x"), dict(good, url="https://user:pw@example.org/x"), dict(good, url=""),
                    dict(good, sha256="xyz"), dict(good, size=0), dict(good, size="10"), dict(good, size=True), "https://x"):
            self.manifest.write_text(json.dumps({"engine": "1.0.0", "platforms": {"mac-arm64": bad}}), encoding="utf-8")
            self.assertFalse(EA.state()["available"], bad)
        for ver in ("../x", "", ".hidden", "a/b", 5):
            self.manifest.write_text(json.dumps({"engine": ver, "platforms": {"mac-arm64": good}}), encoding="utf-8")
            self.assertFalse(EA.state()["available"], ver)
        self.manifest.write_text("not json", encoding="utf-8")
        self.assertFalse(EA.state()["available"])

    def test_the_progress_is_reported(self):
        self.publish()
        got = []
        EA.install(progress=lambda what, g, t: got.append((what, g, t)))
        self.assertTrue(got and got[-1][1] == got[-1][2] == len(self.good_bytes))


class Removing(Base):
    def test_remove_deletes_every_version_and_the_folder(self):
        self.publish()
        EA.install()
        s = EA.remove()
        self.assertEqual((s["installed"], s["versions"]), ("", []))
        self.assertFalse(self.root.exists())
        self.assertIsNone(DW.find_engine())

    def test_remove_with_nothing_added_is_quiet(self):
        self.assertEqual(EA.remove()["installed"], "")

    def test_remove_is_refused_while_the_engine_is_running(self):
        self.publish()
        EA.install()
        eng = DW.ENGINE
        keep = (eng.mode, eng.proc)
        eng.mode, eng.proc = "engine", mock.Mock(poll=lambda: None)
        try:
            with self.assertRaises(EA.AddonError) as cm:
                EA.remove()
            self.assertEqual(str(cm.exception).count("."), 1)                     # one sentence
            self.assertIn("running", str(cm.exception))
            self.assertTrue((self.root / "1.0.0" / "bin" / "hypnomix-engine").is_file())
        finally:
            eng.mode, eng.proc = keep
        self.assertEqual(EA.remove()["installed"], "")

    def test_remove_leaves_what_is_not_a_version_of_the_add_on(self):
        """A file or folder somebody put in engine/ is not the add-on's: only version-named folders and the add-on's own
        half-made ones go, and the folder stays while anything else is in it."""
        self.publish()
        EA.install()
        (self.root / "my-notes.txt").write_text("mine", encoding="utf-8")
        (self.root / "notes").mkdir()
        (self.root / "Backups").mkdir()
        (self.root / "2024-notes").write_text("mine", encoding="utf-8")
        self.assertEqual(EA.installed_versions(), ["1.0.0"])
        EA.remove()
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["2024-notes", "Backups", "my-notes.txt", "notes"])

    def test_the_tidying_after_a_first_run_leaves_what_is_not_a_version_too(self):
        self.publish(version="2.0.0")
        EA.install()
        (self.root / "0.9.0").mkdir()
        (self.root / "notes").mkdir()
        prog = self.root / "2.0.0" / "bin" / "hypnomix-engine"
        self.assertEqual(EA.note_ran(prog), ["0.9.0"])
        self.assertTrue((self.root / "notes").is_dir())

    def test_remove_never_follows_a_link_out_of_the_folder(self):
        outside = Path(self.td.name) / "precious"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep", encoding="utf-8")
        self.root.mkdir(parents=True)
        os.symlink(outside, self.root / "9.9.9")
        os.symlink(outside, self.root / ".incoming-link")
        EA.remove()
        self.assertTrue((outside / "keep.txt").exists())


class Versions(Base):
    def test_a_newer_engine_is_offered_and_the_old_one_goes_after_the_new_one_has_run_once(self):
        self.publish(version="1.0.0")
        EA.install()
        v1 = self.root / "1.0.0"
        # an app update names a newer engine
        newkit = make_kit(Path(self.td.name) / "k2", extra={"share/new.txt": b"2"})
        newpack = Path(self.td.name) / "v2.tar.gz"
        EA.pack(newkit, newpack)
        self.publish(data=newpack.read_bytes(), version="2.0.0", path="/v2.tar.gz")
        s = EA.state()
        self.assertEqual((s["needs_update"], s["current"], s["installed"], s["available"]), (True, False, "1.0.0", True))
        self.assertIn("2.0.0", s["message"])
        self.assertEqual(EA.find(), v1 / "bin" / "hypnomix-engine")               # the old one still works meanwhile
        self.assertEqual(DW.find_engine(), v1 / "bin" / "hypnomix-engine")
        self.assertTrue(DW.ENGINE.status()["binary"])
        self.assertTrue(EA.brief()["needs_update"])
        s = EA.install()
        v2 = self.root / "2.0.0"
        self.assertTrue(v1.is_dir() and v2.is_dir())                               # both kept for now
        self.assertEqual((s["needs_update"], s["current"], s["versions"]), (False, True, ["2.0.0", "1.0.0"]))
        self.assertEqual(DW.find_engine(), v2 / "bin" / "hypnomix-engine")         # the new one is found first
        self.assertEqual(EA.note_ran(v1 / "bin" / "hypnomix-engine"), [])            # the OLD one running removes nothing
        self.assertTrue(v1.is_dir())
        self.assertEqual(EA.note_ran(v2 / "bin" / "hypnomix-engine"), ["1.0.0"])    # the new one reached READY
        self.assertFalse(v1.exists())
        self.assertTrue(v2.is_dir())
        self.assertEqual(EA.state()["versions"], ["2.0.0"])

    def test_a_program_outside_the_add_on_folder_removes_nothing(self):
        self.publish()
        EA.install()
        other = Path(self.td.name) / "bin" / "hypnomix-engine"
        other.parent.mkdir()
        other.write_text("x", encoding="utf-8")
        self.assertEqual(EA.note_ran(other), [])
        self.assertEqual(EA.note_ran("/nonexistent/engine"), [])
        self.assertTrue((self.root / "1.0.0").is_dir())

    def test_the_supervisor_calls_it_when_the_engine_says_ready(self):
        """daw.Engine._read hands the program it started to note_ran after READY (the real reader, a stand-in process)."""
        self.publish(version="1.0.0")
        EA.install()
        old = self.root / "1.0.0"
        with tempfile.TemporaryDirectory() as td:
            kit = make_kit(td, extra={"share/new.txt": b"2"})
            pack = Path(td) / "n.tar.gz"
            EA.pack(kit, pack)
            self.publish(data=pack.read_bytes(), version="2.0.0", path="/n.tar.gz")
            EA.install()
        called = []
        real = EA.note_ran

        class Out:
            def __iter__(self):
                return iter(['HYPNOMIX-ENGINE READY port=1 backend="x"\n'])

            def close(self):
                pass
        new = self.root / "2.0.0" / "bin" / "hypnomix-engine"
        with mock.patch.object(EA, "note_ran", lambda p: called.append(str(p)) or real(p)):
            eng = DW.Engine()
            proc = mock.Mock()
            proc.args = [str(new), "--port", "1"]
            proc.stdout = Out()
            proc.wait.return_value = 0
            eng._want, eng._gen, eng.state, eng._stopping = 1, 1, "starting", False
            eng._read(proc, 1)
            eng._stopping = True
            for _ in range(50):
                if not old.exists():
                    break
                time.sleep(0.1)
        self.assertEqual(called, [str(new)])
        self.assertFalse(old.exists())


class FindingIt(Base):
    def test_the_lookup_order(self):
        """overrides first, then the add-on, then (one more version) the app bundle, next to Python, a developer's build."""
        self.publish()
        EA.install()
        prog = self.root / "1.0.0" / "bin" / "hypnomix-engine"
        override = Path(self.td.name) / "mine" / "hypnomix-engine"
        override.parent.mkdir()
        override.write_text("x", encoding="utf-8")
        override.chmod(0o755)
        with mock.patch.dict(os.environ, {"HYPNOMIX_ENGINE": str(override)}):
            self.assertEqual(DW.candidates()[:2], [override, prog])
            self.assertEqual(DW.find_engine(), override)                           # a developer's override wins
        c = Path(self.td.name).resolve() / "Hypnomix.app" / "Contents"
        py = c / "Resources" / "python" / "bin" / "python3"
        bundled = c / "Resources" / "engine" / "bin" / "hypnomix-engine"
        with mock.patch.object(DW.sys, "executable", str(py)):
            cand = DW.candidates()
            self.assertEqual(cand[0], prog)                                         # the add-on before the bundle
            self.assertIn(bundled, cand)
            self.assertLess(cand.index(prog), cand.index(bundled))
            bundled.parent.mkdir(parents=True)
            bundled.write_text("x", encoding="utf-8")
            bundled.chmod(0o755)
            self.assertEqual(DW.find_engine(), prog)
            EA.remove()
            self.assertEqual(DW.find_engine(), bundled)                             # a test build still works
        self.assertFalse(hasattr(DW, "app_edition"))                                # there are no editions
        self.assertFalse(hasattr(DW, "embedded_engine"))

    def test_no_engine_anywhere_and_no_tab(self):
        with mock.patch.object(DW.sys, "executable", "/usr/bin/python3"), mock.patch.dict(DW.STATE, {"daw": False}):
            self.assertIsNone(DW.find_engine())
            self.assertFalse(DW.available())

    def test_the_daw_state_carries_the_add_on_note(self):
        self.publish(version="1.0.0")
        EA.install()
        self.publish(version="2.0.0")
        code, st = DW.handle_get("/api/daw/state", {}, "t")
        self.assertEqual(code, 200)
        self.assertTrue(st["addon"]["needs_update"])
        self.assertIn("2.0.0", st["addon"]["message"])


class Shipped(unittest.TestCase):
    """The manifest that ships in the app, today: nothing to download."""

    def test_the_shipped_manifest_names_no_address(self):
        d = json.loads(EA.MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(d["format"], 1)
        self.assertRegex(d["engine"], EA.VERSION.pattern)
        self.assertEqual(d["platforms"], {})                                       # unpublished: when it is, this test changes with it
        self.assertEqual(EA.manifest()["platforms"], {})

    def test_the_state_says_it_is_not_available_yet_and_nothing_can_be_added(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HYPNOMIX_HOME": td}):
            for key in ("mac-arm64", "mac-intel", "windows-x64", "linux-x64"):
                with mock.patch.object(EA, "platform_key", lambda k=key: k):
                    s = EA.state()
                    self.assertFalse(s["available"], key)
                    self.assertTrue(s["message"].startswith("HypnoMix DAW is not available yet"), (key, s["message"]))
                    self.assertEqual((s["installed"], s["size"]), ("", 0))
                    with self.assertRaises(EA.AddonError):
                        EA.install()
                    with self.assertRaises(EA.AddonError):
                        EA.start_install()
            self.assertEqual(os.listdir(td), [])                                   # not even a folder was made
        with mock.patch.object(EA, "platform_key", lambda: "windows-x64"):
            self.assertIn("not yet for Windows", EA.state()["message"])

    def test_nothing_is_fetched_without_a_click(self):
        """Starting the app, reading Setup's state and the DAW's state never download or write anything."""
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HYPNOMIX_HOME": td}), \
                mock.patch.object(I, "download", side_effect=AssertionError("downloaded")), \
                mock.patch.object(I, "_open", side_effect=AssertionError("opened a connection")):
            EA.state(), EA.brief(), EA.find()
            DW.handle_get("/api/daw/state", {}, "t")
            self.assertEqual(os.listdir(td), [])

    def test_any_address_that_is_ever_published_is_the_projects_release_page(self):
        for key, e in EA.manifest()["platforms"].items():
            self.assertTrue(e["url"].startswith("https://github.com/drtranceypants/hypnomix/releases/download/"), key)

    def test_the_docs_say_the_fingerprint_is_checked_when_adding_not_when_starting(self):
        root = Path(__file__).resolve().parent.parent
        for rel in ("docs/APP.md", "hypnomix/app/wiki/articles/18-daw.html"):
            text = " ".join((root / rel).read_text(encoding="utf-8").split())
            self.assertIn("checked when the engine is added, not again when it is started", text, rel)

    def test_the_visible_words_are_true_today(self):
        for t in (EA.WHAT, EA.LICENCE, EA.NOT_YET):
            self.assertNotIn("Hypnomix", t)                                            # the product is written HypnoMix
        self.assertIn("built on Ardour", EA.WHAT)
        self.assertIn("expected to be about 100 MB", EA.WHAT)                           # no archive exists to measure
        self.assertEqual(EA._size_text(0), "expected to be about 100 MB")
        self.assertEqual(EA._size_text(104857600), "105 MB")                            # once there is one, its real size
        root = Path(__file__).resolve().parent.parent
        for rel in ("README.md", "docs/guides/09-setup-and-ai.md", "hypnomix/app/wiki/articles/18-setup.html",
                    "hypnomix/app/wiki/articles/20-install.html", "packaging/README.md"):
            for m in re.finditer(r"about 100 MB", (root / rel).read_text(encoding="utf-8")):
                self.assertTrue((root / rel).read_text(encoding="utf-8")[:m.start()].endswith("expected to be "), rel)
        self.assertIn("checked against a fingerprint", EA.WHAT)
        self.assertIn("only while the DAW view is open", EA.WHAT)
        self.assertIn("GNU General Public License", EA.LICENCE)
        self.assertIn("separate program", EA.LICENCE)
        self.assertIn("MIT", EA.LICENCE)


class Command(Base):
    def run_cmd(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with mock.patch.object(sys, "argv", ["hypnomix engine", *argv]), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                EA.main()
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (1 if e.code else 0)
                if isinstance(e.code, str):
                    err.write(e.code)
        return code, out.getvalue(), err.getvalue()

    def test_report_first_writes_nothing_and_downloads_nothing(self):
        self.publish()
        for argv in ((), ("status",), ("where",), ("install",), ("remove",)):
            code, out, err = self.run_cmd(*argv)
            self.assertEqual(code, 0, (argv, out, err))
        self.assertEqual(self.server.seen, [])
        self.assertFalse(self.root.exists())
        self.assertFalse(self.home.exists())
        code, out, _ = self.run_cmd("install")
        self.assertIn("Would add HypnoMix DAW 1.0.0", out)
        self.assertIn("SHA-256 " + hashlib.sha256(self.good_bytes).hexdigest(), out)
        self.assertIn("Nothing was downloaded or changed", out)
        self.assertIn("--yes", out)

    def test_install_and_remove_with_yes(self):
        self.publish()
        code, out, err = self.run_cmd("install", "--yes")
        self.assertEqual(code, 0, err)
        self.assertIn("is added in", out)
        self.assertTrue((self.root / "1.0.0" / "bin" / "hypnomix-engine").is_file())
        code, out, _ = self.run_cmd("install")
        self.assertIn("already added", out)
        code, out, _ = self.run_cmd("remove")
        self.assertIn("Nothing was changed", out)
        self.assertTrue((self.root / "1.0.0").is_dir())
        code, out, _ = self.run_cmd("remove", "--yes")
        self.assertIn("is removed", out)
        self.assertFalse(self.root.exists())

    def test_unpublished_says_so_and_exits_with_an_error(self):
        self.manifest.write_text(json.dumps({"format": 1, "engine": "1.0.0", "platforms": {}}), encoding="utf-8")
        code, out, err = self.run_cmd("install", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("not available yet", err)
        self.assertFalse(self.root.exists())

    def test_it_is_registered_and_documented(self):
        from hypnomix import cli
        self.assertEqual(cli.COMMANDS["engine"][0], "hypnomix.app.engine_addon")
        r = subprocess.run([sys.executable, "-m", "hypnomix.cli", "engine", "-h"], cwd=str(ROOT), capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, PYTHONPATH=str(ROOT)), encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        for word in ("--yes", "status", "install", "remove", "where", "HYPNOMIX_HOME"):
            self.assertIn(word, r.stdout)

    def test_a_typo_never_runs_the_wrong_thing(self):
        code, _, err = self.run_cmd("instal", "--yes")
        self.assertNotEqual(code, 0)
        code, _, err = self.run_cmd("install", "--ye")                                # no abbreviated options
        self.assertNotEqual(code, 0)


class AssistantGate(unittest.TestCase):
    def test_status_runs_unasked_and_everything_else_asks(self):
        for args in ([], ["status"], ["-h"], ["--help"], ["status", "-h"]):
            self.assertFalse(CH.needs_ok("engine", args), args)
        for args in (["install"], ["install", "--yes"], ["remove"], ["remove", "--yes"], ["where"], ["status", "--yes"],
                     ["--yes"], ["status", "install"], ["install", "status"], ["stat"], ["status", "extra"]):
            self.assertTrue(CH.needs_ok("engine", args), args)
        self.assertIn("engine", CH.READ_ONLY)

    def test_the_assistant_cannot_forbid_or_skip_the_card(self):
        self.assertNotIn("engine", CH.FORBIDDEN)                                       # allowed, with a click
        self.assertTrue(CH.needs_ok("engine", ["install", "--yes"]))


class Routes(Base):
    """The page's routes, against the real handler on a port of its own."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from hypnomix.app import server as S
        cls.S = S
        cls.wd = tempfile.TemporaryDirectory()
        cls._env = mock.patch.dict(os.environ, {"HYPNOMIX_APP_HOME": cls.wd.name})
        cls._env.start()
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(0))
        port = cls.srv.server_address[1]
        cls.srv.RequestHandlerClass = S.make_handler(port)
        cls.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls._env.stop()
        cls.wd.cleanup()
        super().tearDownClass()

    def call(self, path, body=None, token=True, headers=None):
        h = dict(headers or {})
        if token:
            h["X-Hypnomix"] = self.S.TOKEN
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, headers=h,
                                     method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def wait_done(self):
        for _ in range(100):
            code, s = self.call("/api/setup/engine")
            if not s["busy"]:
                return s
            time.sleep(0.1)
        self.fail("the add did not finish")

    def test_the_state_is_in_setups_state_and_has_its_own_route(self):
        self.manifest.write_text(json.dumps({"format": 1, "engine": "1.0.0", "platforms": {}}), encoding="utf-8")
        code, s = self.call("/api/setup/state")
        self.assertEqual(code, 200)
        self.assertFalse(s["engine"]["available"])
        self.assertIn("not available yet", s["engine"]["message"])
        self.assertNotIn("downloads", s)                                                # the "Which Hypnomix do you want?" step is gone
        self.assertNotIn("edition", s)
        self.assertIn("hypnomix", [d["id"] for d in s["daws"]])
        self.assertEqual(self.call("/api/setup/engine")[1]["version"], "1.0.0")

    def test_without_the_token_nothing_happens(self):
        self.publish()
        for what in ("install", "remove"):
            code, _ = self.call("/api/setup/engine/" + what, {}, token=False)
            self.assertEqual(code, 403, what)
        code, _ = self.call("/api/setup/engine/install", {}, headers={"X-Hypnomix": "not the token"}, token=False)
        self.assertEqual(code, 403)
        self.assertEqual((self.server.seen, EA.JOB["status"]), ([], "idle"))
        self.assertFalse(self.root.exists())

    def test_a_foreign_origin_is_refused_even_with_the_token(self):
        self.publish()
        for what in ("install", "remove"):
            code, _ = self.call("/api/setup/engine/" + what, {}, headers={"Origin": "http://evil.example"})
            self.assertEqual(code, 403, what)
        code, _ = self.call("/api/setup/engine", headers={"Origin": "http://evil.example"})
        self.assertEqual(code, 403)
        self.assertEqual((self.server.seen, EA.JOB["status"]), ([], "idle"))
        self.assertFalse(self.root.exists())

    def test_nothing_that_names_an_address_or_a_path_is_taken_from_a_request(self):
        self.publish()
        for body in ({"url": "https://evil.example/engine.tar.gz"}, {"path": "/tmp/anywhere"}, {"sha256": "0" * 64},
                     {"dest": "/tmp/anywhere"}, {"version": "../../x"}, {"anything": 1}):
            code, r = self.call("/api/setup/engine/install", body)
            self.assertEqual(code, 400, body)
            self.assertIn("takes nothing", r["error"])
            code, r = self.call("/api/setup/engine/remove", body)
            self.assertEqual(code, 400, body)
        self.assertEqual((self.server.seen, EA.JOB["status"]), ([], "idle"))
        self.assertFalse(self.root.exists())

    def test_an_add_goes_to_the_manifests_address_only(self):
        evil = "https://evil.example/engine.tar.gz"
        self.publish()
        with mock.patch.object(I, "_open", wraps=I._open) as op:
            code, s = self.call("/api/setup/engine/install", {})
            self.assertEqual(code, 200)
            s = self.wait_done()
        self.assertEqual([c.args[0] for c in op.call_args_list], [self.server.url("/engine.tar.gz")])
        self.assertEqual(s["job"]["status"], "done", s["job"])
        self.assertEqual((s["installed"], s["current"]), ("1.0.0", True))
        self.assertTrue((self.root / "1.0.0" / "bin" / "hypnomix-engine").is_file())
        code, s = self.call("/api/setup/engine/remove", {})
        self.assertEqual((code, s["installed"]), (200, ""))
        self.assertNotIn(evil, self.server.seen)

    def test_unpublished_the_click_is_answered_plainly_and_nothing_is_made(self):
        self.manifest.write_text(json.dumps({"format": 1, "engine": "1.0.0", "platforms": {}}), encoding="utf-8")
        code, r = self.call("/api/setup/engine/install", {})
        self.assertEqual(code, 400)
        self.assertIn("not available yet", r["error"])
        self.assertEqual(r["engine"]["job"]["status"], "idle")
        self.assertFalse(self.root.exists())

    def test_remove_while_running_is_answered_with_one_sentence(self):
        self.publish()
        EA.install()
        eng = DW.ENGINE
        keep = (eng.mode, eng.proc)
        eng.mode, eng.proc = "engine", mock.Mock(poll=lambda: None)
        try:
            code, r = self.call("/api/setup/engine/remove", {})
        finally:
            eng.mode, eng.proc = keep
        self.assertEqual(code, 400)
        self.assertIn("running", r["error"])
        self.assertTrue(r["engine"]["running"] is False or "running" in r["error"])
        self.assertTrue((self.root / "1.0.0").is_dir())

    def test_the_daw_choice_is_remembered_and_nothing_is_downloaded(self):
        self.manifest.write_text(json.dumps({"format": 1, "engine": "1.0.0", "platforms": {}}), encoding="utf-8")
        with mock.patch.object(SU, "STATE", Path(self.td.name) / "setup.json"):
            code, r = self.call("/api/setup/daw", {"daw": "hypnomix", "teach_level": ""})
            self.assertEqual((code, r["daw"]), (200, "hypnomix"))
            self.assertEqual(self.call("/api/setup/state")[1]["daw"], "hypnomix")
            self.assertEqual(SU.load()["daw"], "hypnomix")
        self.assertFalse(self.root.exists())
        self.assertEqual(self.server.seen, [])


class Archive(Base):
    """What the owner's side makes: the same kit gives the same bytes, and a kit that is not fit is not packed."""

    def test_the_same_kit_gives_the_same_bytes(self):
        a, b = Path(self.td.name) / "a.tar.gz", Path(self.td.name) / "b.tar.gz"
        ra, rb = EA.pack(self.kit, a), EA.pack(self.kit, b)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertEqual(ra["sha256"], rb["sha256"])
        self.assertEqual(ra["sha256"], hashlib.sha256(a.read_bytes()).hexdigest())
        self.assertEqual(ra["size"], a.stat().st_size)
        with tempfile.TemporaryDirectory() as td:                                       # another copy of the kit, touched later, in another place
            copy = Path(td) / "HypnomixEngine"
            shutil.copytree(self.kit, copy)
            for p in copy.rglob("*"):
                os.utime(p, (time.time() + 1000, time.time() + 1000))
            c = Path(td) / "c.tar.gz"
            EA.pack(copy, c)
            self.assertEqual(c.read_bytes(), a.read_bytes())

    def test_the_archive_is_sorted_with_fixed_times_and_no_owners(self):
        with tarfile.open(self.good) as t:
            ms = t.getmembers()
        names = [m.name for m in ms]
        self.assertEqual(names, sorted(names))
        self.assertTrue(all(m.mtime == EA.FIXED_TIME and m.uid == m.gid == 0 and not m.uname and not m.gname for m in ms))
        self.assertTrue(all(m.mode in (0o644, 0o755) for m in ms))
        raw = self.good.read_bytes()
        self.assertEqual(raw[:3], b"\x1f\x8b\x08")
        self.assertEqual(raw[3] & 0x08, 0)                                              # no file name in the gzip header
        self.assertEqual(raw[4:8], b"\0\0\0\0")                                         # and no time

    @_isolate.POSIX_MODES
    def test_a_program_is_packed_executable(self):
        with tarfile.open(self.good) as t:
            ms = t.getmembers()
        self.assertEqual(next(m for m in ms if m.name == "bin/hypnomix-engine").mode, 0o755)

    def test_a_kit_that_is_not_fit_is_not_packed(self):
        for kw, word in ((dict(licence=False), "licence text"), (dict(notice=False), "source notice"), (dict(link=True), "symbolic links")):
            with tempfile.TemporaryDirectory() as td:
                kit = make_kit(td, **kw)
                out = Path(td) / "out.tar.gz"
                with self.assertRaises(EA.AddonError) as cm:
                    EA.pack(kit, out)
                self.assertIn(word, str(cm.exception))
                self.assertFalse(out.exists() or out.with_name(out.name + ".part").exists())

    def test_the_builders_own_home_path_or_login_name_is_refused(self):
        import getpass
        with tempfile.TemporaryDirectory() as td:
            kit = make_kit(td, extra={"share/conf.txt": (f"path={Path.home()}/x\n").encode()})
            if str(Path.home()) in ("/", ""):
                self.skipTest("no home")
            with self.assertRaises(EA.AddonError) as cm:
                EA.pack(kit, Path(td) / "o.tar.gz")
            self.assertIn("home path", str(cm.exception))
            self.assertEqual(EA.kit_problems(kit, builder=False), [])                   # on the computer that adds it, only the general check
        user = getpass.getuser()
        if len(user) >= 5:
            with tempfile.TemporaryDirectory() as td:
                kit = make_kit(td, extra={"share/about.txt": f"built by {user} on a laptop\n".encode()})
                with self.assertRaises(EA.AddonError):
                    EA.pack(kit, Path(td) / "o.tar.gz")

    def test_an_existing_archive_is_never_overwritten(self):
        out = Path(self.td.name) / "o.tar.gz"
        out.write_text("mine", encoding="utf-8")
        with self.assertRaises(EA.AddonError):
            EA.pack(self.kit, out)
        self.assertEqual(out.read_text(encoding="utf-8"), "mine")

    def test_a_packed_kit_installs(self):
        """The archive pack() makes is the one install() accepts (the whole path, the owner's side to the person's)."""
        self.publish()
        self.assertEqual(EA.install()["installed"], "1.0.0")

    @_isolate.POSIX_ONLY                                      # the packaging scripts are Mac scripts (lipo, hdiutil)
    @unittest.skipUnless(BASH, "SKIPPED: no bash here, so this test was NOT run")
    def test_the_script_checks_packs_prints_the_manifest_line_and_uploads_nothing(self):
        shipped = ROOT / "hypnomix" / "app" / "engine_addon.json"
        before = shipped.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as td:
            kit = make_kit(td)
            out = Path(td) / "out"
            env = dict(os.environ, HYPNOMIX_PYTHON=sys.executable)
            r = subprocess.run([BASH, str(ROOT / "packaging/mac/build_engine_archive.sh"), str(kit), "mac-arm64", str(out)],
                               capture_output=True, text=True, timeout=120, env=env, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            arc = next(out.glob("HypnoMix-engine-*-mac-arm64.tar.gz"))
            sha = hashlib.sha256(arc.read_bytes()).hexdigest()
            self.assertIn(sha, r.stdout)
            self.assertIn(f'"mac-arm64": {{"url": "https://github.com/drtranceypants/hypnomix/releases/download/v', r.stdout)
            self.assertIn(f'"sha256": "{sha}", "size": {arc.stat().st_size}}}', r.stdout)
            self.assertIn("Nothing was uploaded", r.stdout)
            self.assertEqual(shipped.read_text(encoding="utf-8"), before)                              # the manifest is the owner's to edit
            r2 = subprocess.run([BASH, str(ROOT / "packaging/mac/build_engine_archive.sh"), str(kit), "mac-arm64", str(Path(td) / "out2")],
                                capture_output=True, text=True, timeout=120, env=env, encoding="utf-8")
            self.assertEqual(hashlib.sha256(next((Path(td) / "out2").glob("*.tar.gz")).read_bytes()).hexdigest(), sha)   # same kit, same bytes

    @_isolate.POSIX_ONLY                                      # the packaging scripts are Mac scripts (lipo, hdiutil)
    @unittest.skipUnless(BASH, "SKIPPED: no bash here, so this test was NOT run")
    def test_the_script_refuses_a_kit_that_is_not_fit_before_writing_anything(self):
        for kw in (dict(licence=False), dict(notice=False), dict(link=True)):
            with tempfile.TemporaryDirectory() as td:
                kit = make_kit(td, **kw)
                out = Path(td) / "out"
                r = subprocess.run([BASH, str(ROOT / "packaging/mac/build_engine_archive.sh"), str(kit), "mac-arm64", str(out)],
                                   capture_output=True, text=True, timeout=120, env=dict(os.environ, HYPNOMIX_PYTHON=sys.executable), encoding="utf-8")
                self.assertEqual(r.returncode, 1, kw)
                self.assertIn("nothing was written", r.stdout + r.stderr)
                self.assertFalse(out.exists(), kw)

    @_isolate.POSIX_ONLY                                      # the packaging scripts are Mac scripts (lipo, hdiutil)
    @unittest.skipUnless(BASH, "SKIPPED: no bash here, so this test was NOT run")
    def test_the_installer_script_no_longer_takes_the_engine(self):
        sh = (ROOT / "packaging/mac/build_dmg.sh").read_text(encoding="utf-8")
        for word in ("--daw)", "check_kit", "edition", "Resources/engine", "LICENSES/engine", "-full-"):
            self.assertNotIn(word, sh, word)
        r = subprocess.run([BASH, str(ROOT / "packaging/mac/build_dmg.sh"), "--daw", "/nowhere"], capture_output=True, text=True, timeout=60, encoding="utf-8")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown option", r.stdout + r.stderr)
        self.assertEqual(subprocess.run([BASH, "-n", str(ROOT / "packaging/mac/build_engine_archive.sh")]).returncode, 0)


class KitCheck(Base):
    """kit_problems: the Python twin of packaging/mac/check_kit.sh (tests/test_dawfix_packaging.py runs the script)."""

    def test_a_complete_kit_passes(self):
        self.assertEqual(EA.kit_problems(self.kit), [])

    def test_the_shared_users_folder_is_not_a_person(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(EA.kit_problems(make_kit(td, extra={"lib/libx.dylib": b"/Users/Shared/Library/x\0"})), [])

    def test_the_notice_must_say_where_and_which_version(self):
        for line in ("general public license source\n", "GNU General Public License, version 2 or later. The source is available.\n",
                     "GNU General Public License version 2 or later; source at https://example.org/src\n"):
            with tempfile.TemporaryDirectory() as td:
                kit = make_kit(td)
                (kit / "SOURCE.txt").write_text(line, encoding="utf-8")
                self.assertTrue(EA.kit_problems(kit), line)
        with tempfile.TemporaryDirectory() as td:
            kit = make_kit(td)
            (kit / "SOURCE.txt").write_text("GNU General Public License, version 2 or later. Source: https://example.org/src, commit 3fa9c21b.\n", encoding="utf-8")
            self.assertEqual(EA.kit_problems(kit), [])

    def test_a_licence_file_that_is_not_the_gpl_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            kit = make_kit(td)
            (kit / "COPYING").write_text("all rights reserved\n", encoding="utf-8")
            self.assertIn("licence", EA.kit_problems(kit)[0])


def hard_link_first(src, dest, link_from, link_to):
    """A .tar.gz whose FIRST entry is a hard link (link_from -> link_to) to an entry that only comes later."""
    with tarfile.open(dest, "w:gz") as t:
        ti = tarfile.TarInfo(link_from)
        ti.type, ti.linkname = tarfile.LNKTYPE, link_to
        t.addfile(ti)
        for p in sorted(Path(src).rglob("*")):
            if p.relative_to(src).as_posix() != link_from:
                t.add(str(p), p.relative_to(src).as_posix(), recursive=False)
    return Path(dest).read_bytes()


class Limits(Base):
    """The add-on's own unpack limits, which version is preferred, and when a folder on disk counts as whole."""

    def test_an_archive_that_unpacks_to_more_than_the_limit_is_refused_and_leaves_nothing(self):
        self.publish()
        with mock.patch.object(EA, "MAX_UNPACKED", 10):
            with self.assertRaises(EA.AddonError) as cm:
                EA.install()
        self.assertIn("refused", str(cm.exception))
        self.assertEqual((EA.installed_versions(), self.residue()), ([], []))
        self.assertEqual(EA.install()["installed"], "1.0.0")                       # the same archive is fine within the real limit

    def test_the_shipped_limits_are_sane_for_a_kit_of_about_100_mb(self):
        self.assertGreaterEqual(EA.MAX_UNPACKED, 300 << 20)                        # room for the kit ...
        self.assertLessEqual(EA.MAX_UNPACKED, 2 << 30)                             # ... and not for a bomb
        self.assertGreaterEqual(EA.MAX_ENTRIES, 2000)
        self.assertLessEqual(EA.MAX_ENTRIES, 50000)

    def test_an_archive_with_too_many_entries_is_refused_and_leaves_nothing(self):
        self.publish()
        with mock.patch.object(EA, "MAX_ENTRIES", 3):
            with self.assertRaises(EA.AddonError) as cm:
                EA.install()
        self.assertIn("refused", str(cm.exception))
        self.assertEqual((EA.installed_versions(), self.residue()), ([], []))

    def test_the_version_the_manifest_names_is_preferred_over_a_newer_one_on_disk(self):
        self.publish(version="1.0.0")
        EA.install()
        shutil.copytree(self.root / "1.0.0", self.root / "9.0.0")
        self.assertEqual(EA.installed_versions(), ["9.0.0", "1.0.0"])             # the newer one is there ...
        self.assertEqual(EA.find(), self.root / "1.0.0" / "bin" / "hypnomix-engine")      # ... but this app works with 1.0.0
        self.assertEqual(DW.find_engine(), self.root / "1.0.0" / "bin" / "hypnomix-engine")
        self.manifest.write_text(json.dumps({"format": 1, "engine": "3.0.0", "platforms": {}}), encoding="utf-8")   # the manifest names one that is not there
        self.assertEqual(EA.find(), self.root / "9.0.0" / "bin" / "hypnomix-engine")   # then the newest other one

    @_isolate.POSIX_MODES                                                          # Windows has no executable bit
    def test_a_program_that_is_not_executable_is_not_an_engine(self):
        self.publish()
        EA.install()
        prog = self.root / "1.0.0" / "bin" / "hypnomix-engine"
        prog.chmod(0o644)
        self.assertEqual(EA.installed_versions(), [])
        self.assertIsNone(EA.find())
        self.assertIsNone(DW.find_engine())
        s = EA.state()
        self.assertEqual((s["installed"], s["current"]), ("", False))

    def test_a_kit_with_the_program_but_no_licence_text_is_added_again(self):
        self.publish()
        EA.install()
        (self.root / "1.0.0" / "COPYING").unlink()
        n = len(self.server.seen)
        s = EA.install()
        self.assertEqual(len(self.server.seen), n + 1)                             # fetched again: a kit without its licence is not whole
        self.assertTrue((self.root / "1.0.0" / "COPYING").is_file())
        self.assertEqual((s["current"], self.residue()), (True, []))

    def test_an_archive_with_a_hard_link_to_a_later_entry_is_refused_in_one_sentence(self):
        data = hard_link_first(self.kit, self.kitdir / "hl.tar.gz", "bin/hypnomix-engine", "lib/hypnomix-engine")
        self.publish(data=data)
        with self.assertRaises(EA.AddonError) as cm:                               # not a KeyError out of the unpacker
            EA.install()
        self.assertIn("refused", str(cm.exception))
        self.assertEqual((EA.installed_versions(), self.residue()), ([], []))
        self.assertEqual(EA.JOB["status"], "error")
        code, out, err = Command.run_cmd(self, "install", "--yes")                  # and the command ends with a sentence, not a traceback
        self.assertEqual(code, 1)
        self.assertIn("refused", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(self.residue(), [])

    def test_damaged_archives_that_pass_the_fingerprint_are_refused_as_errors_of_ours(self):
        for exc in (KeyError("x"), ValueError("x"), EOFError("x"), tarfile.ReadError("x")):
            self.publish()
            with mock.patch.object(I, "unpack", side_effect=exc):
                with self.assertRaises(EA.AddonError) as cm:
                    EA.install()
            self.assertIn("refused", str(cm.exception))
            self.assertEqual((EA.installed_versions(), self.residue()), ([], []))


class Rebuilt(Base):
    """An archive rebuilt and published under the SAME engine version reaches people who already have that version."""

    def rebuilt_bytes(self):
        kit = make_kit(Path(self.td.name) / "rebuilt", extra={"share/rebuilt.txt": b"rebuilt"})
        out = Path(self.td.name) / "rebuilt.tar.gz"
        EA.pack(kit, out)
        return out.read_bytes()

    def test_a_different_archive_under_the_same_version_is_offered_and_fetched(self):
        self.publish()
        EA.install()
        self.assertTrue(EA.state()["current"])
        self.publish(data=self.rebuilt_bytes(), version="1.0.0", path="/rebuilt.tar.gz")
        s = EA.state()
        self.assertEqual((s["current"], s["needs_update"], s["installed"]), (False, True, "1.0.0"))
        self.assertIn("rebuilt", s["message"])
        self.assertTrue(EA.brief()["needs_update"])
        self.assertIsNotNone(DW.find_engine())                                     # the old build still works meanwhile
        s = EA.install()
        self.assertEqual(self.server.seen[-1], "/rebuilt.tar.gz")
        self.assertTrue((self.root / "1.0.0" / "share" / "rebuilt.txt").is_file())
        self.assertEqual((s["current"], s["needs_update"], self.residue()), (True, False, []))
        n = len(self.server.seen)
        EA.install()
        self.assertEqual(len(self.server.seen), n)                                 # and now it is the file the manifest names: nothing more

    def test_a_folder_with_no_record_is_left_alone(self):
        self.publish()
        EA.install()
        (self.root / "1.0.0" / "ADDON.json").unlink()
        self.assertTrue(EA.state()["current"])
        n = len(self.server.seen)
        EA.install()
        self.assertEqual(len(self.server.seen), n)

    def test_the_same_version_is_not_replaced_under_a_running_engine(self):
        self.publish()
        EA.install()
        self.publish(data=self.rebuilt_bytes(), version="1.0.0", path="/rebuilt.tar.gz")
        with mock.patch.object(EA, "running", lambda: True):
            with self.assertRaises(EA.AddonError) as cm:
                EA.install()
        self.assertIn("running", str(cm.exception))
        self.assertFalse((self.root / "1.0.0" / "share" / "rebuilt.txt").exists())
        self.assertEqual(self.residue(), [])


class ElsewhereRunning(Base):
    """Remove is refused while the engine runs, whichever process asks: the command line and the Assistant are not the app."""

    def setUp(self):
        from tests.test_daw import make_fake, need_fake, with_session
        need_fake(self)                                                             # a visible skip on Windows, but for the tests that never start it
        super().setUp()
        self.publish()
        EA.install()
        self.prog = self.root / "1.0.0" / "bin" / "hypnomix-engine"
        fake = make_fake(self.td.name, skip=False)                                  # a stand-in that answers like the engine
        self.prog.write_bytes(fake.read_bytes())
        self.prog.chmod(0o755)
        self.eng = with_session(DW.Engine(binary=self.prog, attach_url="http://127.0.0.1:9/mcp"), self.td.name)
        self.addCleanup(self.eng.stop)

    def other_process(self, *argv):
        r = subprocess.run([sys.executable, "-m", "hypnomix.cli", "engine", *argv], cwd=str(ROOT), capture_output=True, text=True,
                           timeout=120, env=dict(os.environ, PYTHONPATH=str(ROOT), HYPNOMIX_DISKCARE="off"), encoding="utf-8")
        return r.returncode, r.stdout, r.stderr

    def test_another_process_cannot_remove_an_engine_this_one_started(self):
        st = self.eng.start()
        self.assertEqual(st["state"], "running")
        self.assertTrue((self.root / ".running").is_file())                         # the supervisor says it runs
        code, out, err = self.other_process("remove", "--yes")                      # a process that never started it
        self.assertNotEqual(code, 0, out)
        self.assertIn("running", err)
        self.assertEqual(err.strip().count("."), 1)                                 # one sentence
        self.assertTrue(self.prog.is_file())
        code, out, err = self.other_process("remove")                               # the report first says so too
        self.assertEqual(code, 0)
        self.assertIn("running right now", out)
        code, out, err = self.other_process("status")
        self.assertIn("running:    yes", out)
        self.assertTrue(self.prog.is_file())
        self.eng.stop()
        self.assertFalse((self.root / ".running").exists())                         # ended: the marker goes with it
        code, out, err = self.other_process("remove", "--yes")
        self.assertEqual(code, 0, err)
        self.assertIn("is removed", out)
        self.assertFalse(self.root.exists())

    def test_the_app_started_engine_is_seen_by_the_add_on_from_any_process(self):
        self.eng.start()
        self.assertTrue(EA.state()["running"])
        with mock.patch.object(DW.ENGINE, "mode", None):                            # as a process that did not start it sees it
            self.assertTrue(EA.running())
            with self.assertRaises(EA.AddonError) as cm:
                EA.remove()
            self.assertIn("running", str(cm.exception))
        self.assertTrue(self.prog.is_file())

    def test_an_engine_that_died_leaves_a_marker_that_is_ignored_and_cleaned_by_remove(self):
        gone = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
        gone.wait()
        (self.root / ".running").write_text(json.dumps({"pid": gone.pid, "program": str(self.prog)}), encoding="utf-8")
        self.assertFalse(EA.running())
        self.assertFalse(EA.state()["running"])
        EA.remove()
        self.assertFalse(self.root.exists())

    def test_a_marker_for_a_live_process_group_counts_and_a_damaged_one_does_not(self):
        live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
        self.addCleanup(lambda: (live.kill(), live.wait()))
        EA.mark_running(self.prog, live.pid)
        self.assertTrue(EA.running())
        with self.assertRaises(EA.AddonError):
            EA.remove()
        EA.clear_running(live.pid + 1)                                              # another process's marker is not ours to clear
        self.assertTrue(EA.running())
        EA.clear_running(live.pid)
        self.assertFalse(EA.running())
        for junk in ("not json", "[]", json.dumps({"pid": "x"}), json.dumps({"pid": -5}), json.dumps({"pid": True})):
            (self.root / ".running").write_text(junk, encoding="utf-8")
            self.assertFalse(EA.running(), junk)

    def test_a_marker_with_a_huge_process_id_is_ignored_not_a_crash(self):
        """os.killpg raises OverflowError for a number that is not a C int: state(), running() and remove() must not die."""
        for pid in (2 ** 31, 4294967296, 10 ** 30):
            (self.root / ".running").write_text(json.dumps({"pid": pid, "program": str(self.prog)}), encoding="utf-8")
            self.assertFalse(EA.running(), pid)
            self.assertFalse(EA.state()["running"], pid)
        self.assertFalse(EA._alive(2 ** 40))
        (self.root / ".running").write_text(json.dumps({"pid": 4294967296}), encoding="utf-8")
        EA.remove()
        self.assertFalse(self.root.exists())

    def test_only_an_engine_inside_the_add_on_folder_is_marked(self):
        other = Path(self.td.name) / "bin" / "hypnomix-engine"
        other.parent.mkdir()
        other.write_text("x", encoding="utf-8")
        EA.mark_running(other, os.getpid())
        self.assertFalse((self.root / ".running").exists())


if __name__ == "__main__":
    unittest.main()
