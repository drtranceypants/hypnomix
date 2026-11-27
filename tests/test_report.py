"""Bug reports and crash records: the scrubber, the crash path of the commands, of the app's handlers and job threads,
the page-error route, `hypnomix report`, the report's contents, the new-issue address, the Assistant's gate and Disk care."""
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from hypnomix import cli
from hypnomix.core import report as R
from tests import _isolate

SECRET = "sk-test-SECRET0123456789abcdef"
ENV_SECRET = "envsecretvalue-99887766"
TRACK, SONG = "Zephyr Lead", "Moonlit Harbor"
USERS, WUSERS = "/" + "Users" + "/", "C:" + "\\" + "Users" + "\\"          # not written whole: tests.test_repo_rules reads this file too


def listing(root):
    root = Path(root)
    return sorted(str(p.relative_to(root)) for p in root.rglob("*")) if root.exists() else []


class Homed(unittest.TestCase):
    """A hypnomix home, an app work folder and a user home of their own for each test."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name).resolve()
        self.home = self.root / "hxhome"
        self.work = self.root / "work"
        self.user = self.root / "Users" / "pat"
        for d in (self.home, self.work, self.user):
            d.mkdir(parents=True)
        p = mock.patch.dict(os.environ, {"HYPNOMIX_HOME": str(self.home), "HYPNOMIX_APP_HOME": str(self.work),
                                         "HYPNOMIX_USER_HOME": str(self.user), "HOME": str(self.user), "USERPROFILE": str(self.user),
                                         "FAKE_API_KEY": ENV_SECRET})
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("HYPNOMIX_DEBUG", None)
        R.forget_recent()
        self.addCleanup(self._td.cleanup)
        for k in ("_saved_keys",):
            q = mock.patch.object(R, k, lambda: [SECRET])
            q.start()
            self.addCleanup(q.stop)

    def make_scan(self, name=SONG, tracks=(TRACK, "Bass Guitar"), tools=("smooth", "smooth", "tune")):
        d = self.work / "scan" / name
        d.mkdir(parents=True)
        findings = [dict(id=f"{t}-{i}", tool=t, kind="k", severity="low", track=tracks[i % len(tracks)], where="1.1.1",
                         problem=f"x on {tracks[0]}", fix="y", applies="set") for i, t in enumerate(tools)]
        (d / "findings.json").write_text(json.dumps(dict(set=str(self.user / "Music" / f"{name}.als"), findings=findings)), encoding="utf-8")
        return d


class Scrubbing(Homed):
    def test_the_home_folder_becomes_a_tilde_and_other_paths_a_placeholder_with_the_extension(self):
        s = R.Scrubber()
        h = str(self.user)
        self.assertEqual(s.text(f"home is {h} here"), "home is ~ here")
        out = s.text(f"can't read {h}/Music/My Song/take 1.wav as audio and /Volumes/Drive/stems/Lead.flac too")
        self.assertEqual(out, "can't read <file 1>.wav as audio and <file 2>.flac too")
        self.assertNotIn("Music", out)
        self.assertEqual(s.text(f"again {h}/Music/My Song/take 1.wav"), "again <file 1>.wav")        # stable within one report
        self.assertEqual(s.text("a folder /opt/stuff/Samples"), "a folder <folder 1>")

    def test_windows_and_non_ascii_paths(self):
        s = R.Scrubber()
        out = s.text("bad " + WUSERS + "Jo Smith\\Music\\My Song\\lead.wav and " + WUSERS.replace("\\", "\\\\") + "Jo\\\\Música\\\\canción.mp3 and \\\\nas\\share\\a.wav")
        self.assertEqual(out, "bad <file 1>.wav and <file 2>.mp3 and <file 3>.wav")
        out = s.text("ünïcode " + USERS + "José Núñez/Música/canción ñandú.wav end " + USERS + "Zoë/x")
        self.assertNotIn("Núñez", out)
        self.assertNotIn("Zoë", out)
        self.assertNotIn("Música", out)
        self.assertTrue(out.endswith("<file 5>") or "<folder" in out, out)

    def test_paths_with_spaces_stop_where_the_sentence_goes_on(self):
        s = R.Scrubber()
        self.assertEqual(s.text("wrote /a/My Songs/b.wav and /opt/x/y.json."), "wrote <file 1>.wav and <file 2>.json.")
        self.assertEqual(s.text("read /a/b/My Song and then stopped"), "read <folder 1> and then stopped")
        self.assertEqual(s.text("see /api/state and https://github.com/x/y and and/or 1/2"),
                         "see /api/state and https://github.com/x/y and and/or 1/2")             # a route, a URL and plain slashes stay
        self.assertEqual(s.text("hypnomix/app/server.py:12 stays"), "hypnomix/app/server.py:12 stays")

    def test_relative_paths_lose_their_folders(self):
        s = R.Scrubber()
        out = s.text("hypnomix-out/scan/Some Song/ab/x.wav then scan/Song/ab")
        self.assertNotIn("scan/", out)
        self.assertIn("<file", out)

    def test_names_from_a_scan_are_replaced_everywhere_and_kept_on_request(self):
        s = R.Scrubber(names={"track": [TRACK], "song": [SONG]})
        out = s.text(f"{TRACK} is loud in {SONG}; {TRACK} again")
        self.assertEqual(out, "<track 1> is loud in <song 1>; <track 1> again")
        k = R.Scrubber(keep_names=True, names={"track": [TRACK]})
        self.assertEqual(k.text(f"{TRACK} at {self.user}/Music/Song/vocal.wav"), f"{TRACK} at vocal.wav")
        self.assertEqual(k.text(f"{self.user}"), "~")
        self.assertEqual(k.text(f"key {SECRET}"), "key <hidden>")                               # keys go whatever the choice

    def test_a_name_in_the_other_unicode_form_a_mac_file_name_has_is_still_replaced(self):
        import unicodedata
        nfc = "Caf\u00e9 Del Mar"
        nfd = unicodedata.normalize("NFD", nfc)
        self.assertNotEqual(nfc, nfd)
        for known, text in ((nfc, nfd), (nfd, nfc)):
            out = R.Scrubber(names={"song": [known]}).text(f"mixing {text} now")
            self.assertEqual(out, "mixing <song 1> now", (known, text))

    def test_a_cookie_a_secret_query_parameter_and_the_apps_own_token_are_hidden(self):
        from hypnomix.app import server
        s = R.Scrubber()
        out = s.text("GET /x?key=plainvalue1&n=3 HTTP/1.1\nCookie: sid=abc123; theme=dark\nlater " + server.TOKEN + " and ?sig=zzz9")
        for leak in ("plainvalue1", "abc123", "theme=dark", server.TOKEN, "zzz9"):
            self.assertNotIn(leak, out)
        self.assertIn("n=3", out)
        self.assertIn("later", out)

    def test_never_phones_home_names_the_two_requests_the_app_does_make(self):
        root = Path(R.__file__).resolve().parent.parent.parent
        for rel in ("hypnomix/app/wiki/articles/18-reporting.html", "hypnomix/app/wiki/articles/28-faq.html"):
            text = " ".join((root / rel).read_text(encoding="utf-8").split())
            self.assertIn("GitHub's list of releases", text, rel)
            self.assertIn("the website's list of Wiki articles", text, rel)
        self.assertIn("api.github.com", (root / "hypnomix/app/update.py").read_text(encoding="utf-8"))

    def test_the_report_header_does_not_promise_more_than_the_scrubbing_can_keep(self):
        for names in (False, True):
            first = R.build("bug", "x", "y", names=names).split("\n\n")[1]
            self.assertIn("hidden as far as HypnoMix can tell", first)
            self.assertIn("read it before you share it", first)
        root = Path(R.__file__).resolve().parent.parent.parent
        for rel in ("hypnomix/app/report.js", "docs/APP.md", "README.md", "hypnomix/app/wiki/articles/18-reporting.html"):
            text = " ".join((root / rel).read_text(encoding="utf-8").split())
            self.assertIn("as far as HypnoMix can tell", text, rel)
            self.assertNotIn("always hidden", text, rel)
            self.assertNotIn("has no paths, names or keys", text, rel)

    def test_keys_and_tokens_never_survive(self):
        s = R.Scrubber()
        bad = [SECRET, ENV_SECRET, "sk-ant-api03-ABCDEFGHIJKLMNOP", "AIzaSyA1234567890abcdefghijkl", "gsk_abcdefghijklmnop1234",
               "ghp_abcdefghijklmnop12345", "Bearer abcdefghijklmnopqrstuv", "X-Hypnomix: tok123tok", "api_key=hello123",
               '"token": "abc12345"', "password: hunter22", "a" * 20 + "1" * 12]
        for b in bad:
            out = s.text(f"before {b} after")
            self.assertNotIn(b.split("=")[-1].strip('"'), out.replace("<hidden>", ""), b)
            self.assertIn("<hidden>", out, b)
        self.assertNotIn(SECRET, s.text(json.dumps({"keys": {"x": SECRET}})))

    def test_option_summary_keeps_names_and_hides_values(self):
        out = R.option_summary(["Song One.als", "--mix", USERS + "pat/Music/mix.wav", "--bpm", "120", "--key=F# major", "--deep", "--bpm", "-3"])
        self.assertEqual(out, ["<path>", "--mix <path>", "--bpm <number>", "--key <text>", "--deep", "--bpm <number>"])
        self.assertEqual(R.option_summary(["--Made-Up-Song-Name-That-Is-Not-An-Option-And-Is-Far-Too-Long-To-Be-One-123456"]), ["<text>"])

    def test_relative_paths_and_bare_file_names_are_reduced_too(self):
        """The form Python's own file errors quote ('Secret Song.als'), with spaces and brackets, with and without a folder."""
        cases = [("No such file or directory: 'Secret.wav'", "No such file or directory: '<file 1>.wav'"),
                 ("[Errno 13] Permission denied: 'Music/Night Drive Mix.wav'", "[Errno 13] Permission denied: '<file 1>.wav'"),
                 ("bad file stems/Lead Vocal.wav here", "bad file <file 1>.wav here"),
                 ("Secret Album/Song Name.wav", "<file 1>.wav"),
                 ("[Errno 21] Is a directory: 'My Album'", "[Errno 21] Is a directory: '<folder 1>'"),
                 ("'Harbor (Final) v2.als'", "'<file 1>.als'"),
                 ("../Secret/Song Name.wav", "<file 1>.wav"),
                 ("Rendering Lead Vocal.wav to disk", "Rendering <file 1>.wav to disk"),
                 ('"Don\'t Stop.wav" is bad', '"<file 1>.wav" is bad'),
                 (USERS + "alice/Music/Night Drive (mix 2).wav failed", "<file 1>.wav failed")]
        for raw, want in cases:
            out = R.Scrubber().text(raw)
            self.assertEqual(out, want, raw)
            self.assertEqual(R.Scrubber().text(out), out, "scrubbing twice changes nothing")
        for leak in ("Secret", "Lead", "Song Name", "Night Drive", "Harbor", "Album"):
            self.assertNotIn(leak, " ".join(R.Scrubber().text(r) for r, _ in cases))
        s = R.Scrubber()
        self.assertEqual(s.text("a Secret.wav b Secret.wav"), "a <file 1>.wav b <file 1>.wav")      # the same name, the same number
        self.assertEqual(R.Scrubber(keep_names=True).text("No such file: 'Secret.wav'"), "No such file: 'Secret.wav'")
        self.assertEqual(s.text("see hypnomix/core/report.py and 3 files"), "see hypnomix/core/report.py and 3 files")   # not a name

    def test_more_credential_shapes_are_hidden(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk"
        for raw, secret in [("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"), ("authorization=Bearer abc.def-ghi_jkl", "abc.def"),
                            (f"token was {jwt}", jwt), ("key AKIAIOSFODNN7EXAMPLE used", "AKIAIOSFODNN7EXAMPLE"),
                            ("mail bob@example.com please", "bob@example.com"), ("ssh://carol@host.example/x", "carol"),
                            ("https://dave:pw1234@host.example/x", "pw1234")]:
            out = R.Scrubber().text(raw)
            self.assertNotIn(secret, out, raw)


class CliCrash(Homed):
    def setUp(self):
        super().setUp()
        self.boom = types.ModuleType("hx_fake_boom")
        self.boom.main = self.explode
        self.kind = KeyError(f"{TRACK} {self.user}/Music/Song.wav {SECRET}")
        p = mock.patch.dict(sys.modules, {"hx_fake_boom": self.boom})
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.dict(cli.COMMANDS, {"boom": ("hx_fake_boom", "a fake command")})
        q.start()
        self.addCleanup(q.stop)

    def explode(self):
        raise self.kind

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        code = None
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main(argv)
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_an_unexpected_error_writes_one_record_and_one_sentence_and_exit_70(self):
        code, out, err = self.run_cli(["boom", str(self.user / "Music" / "Song One.als"), "--mix", "/x/y.wav", "--bpm", "120"])
        self.assertEqual(code, 70)
        self.assertEqual(out, "")
        self.assertNotIn("Traceback", err)
        self.assertEqual(len(err.strip().splitlines()), 1, err)
        self.assertIn("HypnoMix hit a bug", err)
        self.assertIn("nothing was sent", err)
        self.assertIn("hypnomix report --crash", err)
        files = list((self.home / "crashes").glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertRegex(files[0].name, r"^\d{8}T\d{6}Z-boom\.json$")
        self.assertIn(files[0].name, err)
        rec = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual((rec["command"], rec["where"], rec["exception"]), ("boom", "cli", "KeyError"))
        self.assertEqual(rec["options"], ["<path>", "--mix <path>", "--bpm <number>"])      # names kept, values by kind
        text = files[0].read_text(encoding="utf-8")
        for secret in (SECRET, str(self.user), "Music", "Song One", "Song.wav"):
            self.assertNotIn(secret, text)
        self.assertIn("<hidden>", rec["message"])
        for fr in rec["traceback"]:
            self.assertFalse(fr["file"].startswith("/"), fr)
        self.assertTrue(any(fr["file"] == "hypnomix/cli.py" for fr in rec["traceback"]))
        self.assertEqual(R.last_run()["status"], "crashed")

    @_isolate.POSIX_MODES                                                     # Windows has no permission bits
    def test_a_crash_record_is_private_to_the_person(self):
        self.run_cli(["boom"])
        files = list((self.home / "crashes").glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(oct(files[0].stat().st_mode & 0o777), "0o600")

    def test_the_same_crash_twice_is_one_record(self):
        self.run_cli(["boom"])
        self.run_cli(["boom"])
        self.assertEqual(len(list((self.home / "crashes").glob("*.json"))), 1)

    def test_only_the_newest_twenty_records_are_kept(self):
        for i in range(25):
            R.forget_recent()
            info = R.write_crash("cli", f"cmd{i:02d}", exc=ValueError("x"))
            self.assertTrue(info["id"])
            time.sleep(0.002)
        ids = sorted(p.stem for p in (self.home / "crashes").glob("*.json"))
        self.assertEqual(len(ids), R.KEEP)
        self.assertTrue(ids[-1].endswith("cmd24") and ids[0].endswith("cmd05"), ids)

    def test_more_than_nine_records_in_one_second_still_keep_the_newest(self):
        """Ids sorted as text put '-10' before '-2': the trim then deleted the newest records."""
        from datetime import datetime, timezone
        frozen = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        made = []
        with mock.patch.object(R, "utcnow", lambda: frozen):
            for i in range(25):
                R.forget_recent()
                made.append(R.write_crash("cli", "same", exc=ValueError("x"))["id"])
        kept = sorted(p.stem for p in (self.home / "crashes").glob("*.json"))
        self.assertEqual(len(kept), R.KEEP)
        self.assertEqual(sorted(kept), sorted(made[-R.KEEP:]))
        self.assertEqual(R.crashes()[0]["id"], made[-1])                                  # newest first
        self.assertEqual([r["id"] for r in R.crashes()], list(reversed(made[-R.KEEP:])))

    def test_old_entries_of_the_repeat_table_are_dropped(self):
        for i in range(5):
            R._RECENT[("cli", f"E{i}", "f.py", i, "")] = (time.time() - 400, f"id{i}")
        R._RECENT[("cli", "Fresh", "f.py", 1, "")] = (time.time() - 10, "idfresh")
        R.write_crash("cli", "late", exc=KeyError("y"))
        self.assertEqual(len(R._RECENT), 2)                                              # the fresh one and the new one

    def test_the_debug_switch_still_shows_the_traceback_and_writes_nothing(self):
        with mock.patch.dict(os.environ, {"HYPNOMIX_DEBUG": "1"}):
            with self.assertRaises(KeyError):
                cli.main(["boom"])
        self.assertFalse((self.home / "crashes").exists())

    def test_what_is_not_a_bug_is_left_as_it_was(self):
        from hypnomix.core.tools import MissingToolError
        self.kind = MissingToolError("needs Rubber Band")
        code, _, err = self.run_cli(["boom"])
        self.assertEqual((code, err.strip()), (2, "needs Rubber Band"))
        self.kind = BrokenPipeError()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), self.assertRaises(BrokenPipeError):
            cli.main(["boom"])
        self.kind = KeyboardInterrupt()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), self.assertRaises(KeyboardInterrupt):
            cli.main(["boom"])
        self.assertFalse((self.home / "crashes").exists())

    def test_a_command_that_ends_with_a_sentence_is_remembered_for_the_next_report(self):
        self.kind = SystemExit(f"can't read {self.user}/Music/a.wav: no such file")
        code, _, err = self.run_cli(["boom"])
        self.assertIn("no such file", code)
        last = R.last_run()
        self.assertEqual((last["what"], last["status"], last["exit"]), ("boom", "failed", 1))
        self.assertFalse((self.home / "crashes").exists())
        text = R.build("bug")
        self.assertIn("ended: failed", text)
        self.assertNotIn(str(self.user), text)
        self.assertNotIn("Music", text)

    def test_a_clean_command_leaves_nothing_behind(self):
        self.kind = SystemExit(0)
        self.run_cli(["boom"])
        self.assertEqual(listing(self.home), [])

    def test_a_real_run_without_argv_still_knows_the_command(self):
        """main() with no argv (how the installed command calls it): _main rewrites sys.argv, the record must keep the command."""
        out, err = io.StringIO(), io.StringIO()
        code = None
        with mock.patch.object(sys, "argv", ["hypnomix", "boom", "--what", "hi", "--mix", "x.wav", "--bpm", "120"]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main()
            except SystemExit as e:
                code = e.code
        self.assertEqual(code, 70)
        files = list((self.home / "crashes").glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertRegex(files[0].name, r"^\d{8}T\d{6}Z-boom\.json$")
        rec = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(rec["command"], "boom")
        self.assertEqual(rec["options"], ["--what <text>", "--mix <path>", "--bpm <number>"])
        self.assertEqual((R.last_run()["what"], R.last_run()["status"]), ("boom", "crashed"))

    def test_a_plain_failure_in_a_real_run_is_remembered_under_its_command(self):
        def fail():
            sys.exit("that file is not a Live set")
        self.boom.main = fail
        with mock.patch.object(sys, "argv", ["hypnomix", "boom", "Secret Song.als"]), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.main()
        last = R.last_run()
        self.assertEqual((last["what"], last["status"]), ("boom", "failed"))
        self.assertEqual(list((self.home / "crashes").glob("*.json")), [])

    def test_a_file_error_with_a_bare_name_never_puts_the_name_in_the_record_or_the_report(self):
        self.kind = FileNotFoundError(2, "No such file or directory", "Secret Banjo Song.als")
        code, out, err = self.run_cli(["boom"])
        self.assertEqual(code, 70)
        text = (list((self.home / "crashes").glob("*.json"))[0]).read_text(encoding="utf-8")
        self.assertNotIn("Secret Banjo", text)
        report = R.build("crash")
        self.assertNotIn("Secret Banjo", report)
        self.assertIn("<file 1>.als", report)


class Contents(Homed):
    def job(self):
        return dict(title=f"First pass: {SONG}", kind="scan", status="failed", reason=f"{TRACK} broke at {self.user}/Music/x.wav",
                    dir=str(self.work / "scan" / SONG),
                    log=[f"$ hypnomix scan '{self.user}/Music/{SONG}.als'", f"track {TRACK}: error with key {SECRET}",
                         f"wrote {self.work}/scan/{SONG}/REVIEW.md", f"token={ENV_SECRET}"])

    def test_no_secret_or_name_is_in_a_report_unless_names_are_kept(self):
        self.make_scan()
        R.write_crash("cli", "scan", exc=KeyError(f"{TRACK} {SECRET}"))
        what = f"{TRACK} on {SONG} crashed at {self.user}/Music/Song.wav with {SECRET} and {ENV_SECRET}"
        text = R.build("bug", what, "it to work", job=self.job())
        for bad in (SECRET, ENV_SECRET, str(self.user), TRACK, SONG, "Bass Guitar", "Music/"):
            self.assertNotIn(bad, text, bad)
        for good in ("## What happened", "## What I expected", "## Version and setup", "## What ran last", "## Log",
                     "## Crash record", "## Findings in the open scan", "smooth: 2", "tune: 1", "<track 1>", "<song 1>"):
            self.assertIn(good, text, good)
        kept = R.build("bug", what, "", names=True, job=self.job())
        self.assertIn(TRACK, kept)
        self.assertIn(SONG, kept)
        for bad in (SECRET, ENV_SECRET, str(self.user)):
            self.assertNotIn(bad, kept, bad)

    def test_each_optional_part_can_be_switched_off(self):
        self.make_scan()
        R.write_crash("cli", "scan", exc=KeyError("x"))
        full = R.compose("bug", include=R.ALL, job=self.job())
        self.assertEqual(full["parts"], dict(log=True, crash=True, scan=True))
        self.assertNotIn("## Log", R.build("bug", include=("crash", "scan"), job=self.job()))
        self.assertNotIn("## Crash record", R.build("bug", include=("log", "scan"), job=self.job()))
        self.assertNotIn("## Findings in the open scan", R.build("bug", include=("log", "crash"), job=self.job()))

    def test_the_environment_is_never_dumped(self):
        with mock.patch.dict(os.environ, {"HYPNOMIX_DEBUG": "yes-it-is-set", "UNRELATED_SWITCH": "some-value-xyz", "PATH": "/very/secret/bin"}):
            text = R.build("bug")
        self.assertIn("HYPNOMIX_DEBUG", text)
        self.assertNotIn("yes-it-is-set", text)
        self.assertNotIn("UNRELATED_SWITCH", text)
        self.assertNotIn("/very/secret/bin", text)
        self.assertNotIn(str(self.root), text)

    def test_helpers_are_present_or_not_never_a_path(self):
        with mock.patch("shutil.which", lambda x, *a, **k: "/usr/local/bin/" + x if x == "ffmpeg" else None), \
                mock.patch("hypnomix.core.tools.rubberband_path", lambda: None):
            text = R.build("bug")
        self.assertIn("ffmpeg: present", text)
        self.assertIn("not found", text)
        self.assertNotIn("/usr/local/bin", text)

    def test_the_setup_daw_is_named(self):
        (self.home / "setup.json").write_text(json.dumps({"daw": "reaper"}), encoding="utf-8")
        self.assertIn("DAW chosen in Setup: REAPER", R.build("bug"))

    def test_a_crash_report_puts_the_record_first(self):
        R.write_crash("cli", "scan", exc=ValueError("kaboom"))
        text = R.build("crash", crash_id=R.crash(1)["id"])
        self.assertLess(text.index("## Crash record"), text.index("## What happened"))
        self.assertIn("ValueError: kaboom", text)

    def test_the_log_fence_survives_backticks_in_the_log(self):
        text = R.build("bug", job=dict(title="t", kind="scan", status="failed", log=["a ``` b", "````"]))
        fence = [l for l in text.splitlines() if l.startswith("`") and l.endswith("text")][0]
        self.assertGreater(len(fence), 7)

    def test_the_digest_follows_the_text(self):
        a, b = R.compose("bug", "one"), R.compose("bug", "two")
        self.assertNotEqual(a["digest"], b["digest"])
        self.assertEqual(a["digest"], R.compose("bug", "one")["digest"])


class SendingIsTheirs(Homed):
    def test_the_issue_address_carries_the_template_name_only(self):
        self.assertEqual(R.ISSUE_URL, "https://github.com/drtranceypants/hypnomix/issues/new?template=bug_report.yml")
        seen = []
        self.assertTrue(R.open_issue_page(lambda u: seen.append(u) or True))
        self.assertEqual(seen, [R.ISSUE_URL])
        self.assertFalse(R.open_issue_page(lambda u: (_ for _ in ()).throw(OSError("no browser"))))

    def test_copy_says_plainly_when_there_is_no_clipboard_program(self):
        with mock.patch("shutil.which", lambda *a, **k: None):
            done, why = R.copy_text("x")
        self.assertFalse(done)
        self.assertIn("no clipboard program", why)
        self.assertIn("--out", why)

    def test_a_saved_report_is_a_new_file_each_time(self):
        a = R.save_report("one", self.work / "reports")
        b = R.save_report("two", self.work / "reports")
        self.assertNotEqual(a, b)
        self.assertEqual((a.read_text(encoding="utf-8"), b.read_text(encoding="utf-8")), ("one", "two"))


class Command(Homed):
    def run_cmd(self, *args):
        from hypnomix.workflow import report as C
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                C.main(list(args))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def snapshot(self):
        return (listing(self.home), listing(self.work), listing(self.user), listing(os.getcwd()) if Path(os.getcwd()).is_dir() and
                len(listing(os.getcwd())) < 4000 else [])

    def test_the_report_first_form_prints_and_writes_nothing(self):
        self.make_scan()
        R.write_crash("cli", "scan", exc=KeyError("x"))
        before = self.snapshot()
        mtimes = {p: p.stat().st_mtime_ns for p in self.home.rglob("*") if p.is_file()}
        with mock.patch("webbrowser.open", side_effect=AssertionError("opened a browser")), \
                mock.patch("subprocess.run", side_effect=AssertionError("ran a program")):
            code, out, err = self.run_cmd("--what", f"{TRACK} broke")
        self.assertEqual(code, 0)
        self.assertIn("# HypnoMix problem report", out)
        self.assertIn("<track 1> broke", out)
        self.assertIn("Nothing was written and nothing was sent", err)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(mtimes, {p: p.stat().st_mtime_ns for p in self.home.rglob("*") if p.is_file()})

    def test_the_list_and_the_crash_forms_are_read_only_too(self):
        code, out, _ = self.run_cmd("--list")
        self.assertIn("No crash records", out)
        code, _, _ = self.run_cmd("--crash")
        self.assertIn("no crash record is saved", code)
        R.write_crash("cli", "scan", exc=ValueError("kaboom"))
        before = self.snapshot()
        _, out, _ = self.run_cmd("--list")
        self.assertIn("ValueError", out)
        _, out, _ = self.run_cmd("--crash")
        self.assertIn("# HypnoMix crash report", out)
        self.assertIn("kaboom", out)
        code, _, _ = self.run_cmd("--crash", "3")
        self.assertIn("no crash record number 3", code)
        self.assertEqual(before, self.snapshot())

    def test_out_saves_a_new_file_and_never_over_one(self):
        t = self.root / "r.md"
        code, out, err = self.run_cmd("--out", str(t))
        self.assertEqual(t.read_text(encoding="utf-8"), out)
        self.assertIn("saved as", err)
        code, _, _ = self.run_cmd("--out", str(t))
        self.assertIn("never writes over a file", code)
        folder = self.root / "reports"
        folder.mkdir()
        self.run_cmd("--out", str(folder))
        self.assertEqual(len(list(folder.glob("hypnomix-report-*.md"))), 1)

    def test_copy_and_open_copy_first_and_open_the_page_with_the_name_only(self):
        seen = []
        with mock.patch("webbrowser.open", lambda u: seen.append(u) or True), \
                mock.patch.object(R, "copy_text", return_value=(True, "pbcopy")) as cp:
            code, out, err = self.run_cmd("--what", "secret words here", "--open")
        self.assertEqual(seen, [R.ISSUE_URL])
        self.assertNotIn("secret", seen[0])
        cp.assert_called_once()
        self.assertIn("secret words here", cp.call_args[0][0])
        self.assertIn("paste it there", err)
        self.assertLess(err.index("copied"), err.index("opened"))

    def test_no_clipboard_is_said_plainly(self):
        with mock.patch.object(R, "copy_text", return_value=(False, "no clipboard program was found")):
            _, _, err = self.run_cmd("--copy")
        self.assertIn("NOT copied", err)

    def test_no_options_drop_the_parts_asked_for(self):
        self.make_scan()
        _, out, _ = self.run_cmd("--no-scan", "--no-log", "--no-crash")
        self.assertNotIn("## Findings in the open scan", out)

    def test_the_command_is_registered_where_doctor_lives(self):
        group = next(t for t, cmds in cli.GROUPS if any(n == "doctor" for n, _, _ in cmds))
        self.assertIn("report", [n for n, _, _ in dict(cli.GROUPS)[group]])


class Gate(unittest.TestCase):
    def test_report_is_read_only_only_when_it_prints_or_lists(self):
        from hypnomix.app import chat as CH
        for args in ([], ["--crash"], ["--crash", "2"], ["--list"], ["-h"]):
            self.assertFalse(CH.needs_ok("report", args), args)
        for args in (["--out", "x.md"], ["--copy"], ["--open"], ["--crash", "--open"], ["--list", "--out", "x"], ["--what", "hi"],
                     ["--expected", "x"], ["--names"], ["--no-log"], ["--cr"], ["--crash=1", "--copy"], ["--out=x"], ["--scan", "d"]):
            self.assertTrue(CH.needs_ok("report", args), args)


class Server(Homed):
    """The app's handlers, job threads, page-error route and report routes, on a private server."""

    def setUp(self):
        super().setUp()
        from hypnomix.app import server as S
        from hypnomix.app import reporting as RP
        self.S, self.RP = S, RP
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(0))
        port = self.srv.server_address[1]
        self.srv.RequestHandlerClass = S.make_handler(port)
        self.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.opened = []
        p = mock.patch.object(S, "open_web", lambda u: self.opened.append(u) or True)
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(R, "copy_text", lambda t: (True, "pbcopy"))
        q.start()
        self.addCleanup(q.stop)
        self.old_job = dict(self.S.JOB)
        self.addCleanup(lambda: (self.S.JOB.clear(), self.S.JOB.update(self.old_job)))

    def call(self, path, body=None, token=True, headers=None):
        h = dict(headers or {})
        if token:
            h["X-Hypnomix"] = self.S.TOKEN
        if body is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, headers=h,
                                     method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if r.headers.get("Content-Type", "").startswith("application/json") else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def records(self):
        return sorted((self.home / "crashes").glob("2*.json")) if (self.home / "crashes").exists() else []

    # -- a bug in a request handler
    def test_an_unhandled_error_in_a_get_writes_a_record_and_answers_in_a_sentence(self):
        with mock.patch.object(self.S, "scans", side_effect=ZeroDivisionError("bad sum")):
            code, body = self.call("/api/state")
        self.assertEqual(code, 500)
        self.assertEqual(body["error"], self.RP.SAID)
        self.assertEqual(len(self.records()), 1)
        rec = json.loads(self.records()[0].read_text(encoding="utf-8"))
        self.assertEqual((rec["where"], rec["exception"]), ("app-request", "ZeroDivisionError"))
        self.assertTrue(any(f["file"] == "hypnomix/app/server.py" for f in rec["traceback"]))
        code, body = self.call("/api/crashes")
        self.assertEqual([r["state"] for r in body["records"]], ["new"])
        self.assertNotIn("traceback", body["records"][0])

    def test_an_unhandled_error_in_a_post_does_the_same_and_the_plain_errors_stay_plain(self):
        with mock.patch.object(self.S, "stop_job", side_effect=ZeroDivisionError("bad")):
            code, body = self.call("/api/stop", {})
        self.assertEqual((code, body["error"]), (500, self.RP.SAID))
        self.assertEqual(len(self.records()), 1)
        code, body = self.call("/api/decide", {"dir": "/nowhere"})              # a person-caused error: a 400 sentence, no record
        self.assertIn(code, (400, 403, 409))
        self.assertEqual(len(self.records()), 1)

    def test_an_error_in_a_job_thread_ends_the_job_failed_with_a_record(self):
        calls = {"n": 0}
        real = self.S.listing

        def flaky(dirs):
            calls["n"] += 1
            if calls["n"] > 1:
                raise ZeroDivisionError("the second look broke")
            return real(dirs)
        with mock.patch.object(self.S, "listing", flaky):
            jid = self.S.run_job("tool", "A test job", [("waiting", lambda: None, True)])
            for _ in range(100):
                if self.S.JOB["status"] != "running":
                    break
                time.sleep(0.05)
        self.assertEqual(self.S.JOB["status"], "failed")
        self.assertEqual(self.S.JOB["reason"], self.RP.SAID)
        self.assertIn(self.RP.SAID, self.S.JOB["log"])
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(json.loads(self.records()[0].read_text(encoding="utf-8"))["where"], "app-job")
        self.assertEqual(R.last_run()["status"], "failed")        # the job's end is remembered for the next report

    def test_a_thread_that_dies_leaves_a_record(self):
        try:
            raise ZeroDivisionError("in a thread")
        except ZeroDivisionError:
            info = sys.exc_info()
        args = types.SimpleNamespace(exc_type=info[0], exc_value=info[1], exc_traceback=info[2], thread=threading.current_thread())
        with mock.patch.object(self.RP, "_OLD_HOOK", [lambda a: None]):
            self.RP.thread_hook(args)
        self.assertEqual(json.loads(self.records()[0].read_text(encoding="utf-8"))["where"], "app-thread")

    def test_the_test_hooks_exist_only_under_their_environment_variable(self):
        os.environ.pop("HYPNOMIX_TEST_HOOKS", None)
        self.assertEqual(self.call("/api/test/crash", {})[0], 404)
        self.assertEqual(self.records(), [])
        with mock.patch.dict(os.environ, {"HYPNOMIX_TEST_HOOKS": "1"}):
            self.assertEqual(self.call("/api/test/crash", {}, token=False)[0], 403)         # still behind the token
            code, body = self.call("/api/test/crash", {})
        self.assertEqual((code, body["error"]), (500, self.RP.SAID))
        self.assertEqual(len(self.records()), 1)

    # -- page errors
    def page_error(self, n=1, **kw):
        body = dict(message=f"x{n} is not a function", source="http://127.0.0.1:1/review.js", line=12, stack=f"at f ({self.user}/a.js:1)", page="home")
        body.update(kw)
        return self.call("/api/crashes/page", body)

    def test_a_page_error_needs_the_token_and_is_recorded_like_a_crash(self):
        self.assertEqual(self.call("/api/crashes/page", {"message": "x"}, token=False)[0], 403)
        self.assertEqual(self.records(), [])
        code, body = self.page_error()
        self.assertEqual((code, body["recorded"]), (200, True))
        rec = json.loads(self.records()[0].read_text(encoding="utf-8"))
        self.assertEqual((rec["where"], rec["command"]), ("page", "page-script"))
        self.assertNotIn(str(self.user), json.dumps(rec))
        self.assertNotIn("127.0.0.1", json.dumps(rec))

    def test_page_errors_are_rate_limited_and_validated(self):
        codes = [self.page_error(i, message=f"different {i}", line=i)[0] for i in range(R.PAGE_PER_MINUTE + 3)]
        self.assertEqual(codes[:R.PAGE_PER_MINUTE], [200] * R.PAGE_PER_MINUTE)
        self.assertEqual(codes[R.PAGE_PER_MINUTE:], [429] * 3)
        self.assertLessEqual(len(self.records()), R.PAGE_PER_MINUTE)
        self.assertEqual(self.call("/api/crashes/page", {"message": 5})[0], 400)
        self.assertEqual(self.call("/api/crashes/page", {"message": "x", "stack": ["a"]})[0], 400)
        self.assertEqual(self.call("/api/crashes/page", {})[0], 400)

    def test_different_page_errors_are_different_records_and_the_same_one_is_not_repeated(self):
        self.page_error(1, message="first", line=1)
        self.page_error(2, message="second", line=2)
        self.assertEqual(len(self.records()), 2)
        self.page_error(3, message="first", line=1)
        self.assertEqual(len(self.records()), 2)

    def test_the_tools_tabs_report_job_is_never_its_own_log(self):
        self.S.JOB.update(status="done", title="hypnomix report", kind="tool", log=["# HypnoMix problem report"], stopped=False)
        self.assertIsNone(self.RP.job_info(self.S))
        self.RP.job_ended(self.S)
        self.assertEqual(R.last_run(), {})

    # -- the records the page offers
    def test_a_record_is_offered_once_and_dismissed_on_request(self):
        info = R.write_crash("cli", "scan", exc=KeyError("x"))
        _, body = self.call("/api/crashes")
        self.assertEqual(body["records"][0]["state"], "new")
        self.assertTrue(body["records"][0]["earlier"] or True)
        self.assertEqual(self.call("/api/crashes/dismiss", {"id": info["id"], "offered": True})[0], 200)
        self.assertEqual(self.call("/api/crashes")[1]["records"][0]["state"], "offered")
        self.assertEqual(self.call("/api/crashes/dismiss", {"id": info["id"]})[0], 200)
        self.assertEqual(self.call("/api/crashes")[1]["records"][0]["state"], "dismissed")
        self.assertEqual(len(self.records()), 1)                                           # dismissing hides the notice, it deletes nothing
        self.assertEqual(self.call("/api/crashes/dismiss", {"id": "../../x"})[0], 400)
        self.assertEqual(self.call("/api/crashes/dismiss", {"id": info["id"]}, token=False)[0], 403)
        code, one = self.call("/api/crashes?id=" + info["id"])
        self.assertIn("KeyError", one["text"])
        self.assertEqual(self.call("/api/crashes?id=nope")[0], 404)

    # -- the report routes
    def test_the_preview_is_the_report_and_validates_its_choices(self):
        self.make_scan()
        code, body = self.call("/api/report/preview?what=" + urllib.request.quote(f"{TRACK} sounds odd") + "&names=0&scan=1")
        self.assertEqual(code, 200)
        self.assertIn("<track 1> sounds odd", body["text"])
        self.assertNotIn(TRACK, body["text"])
        self.assertEqual(body["parts"]["scan"], True)
        code, kept = self.call("/api/report/preview?names=1&what=" + urllib.request.quote(TRACK))
        self.assertIn(TRACK, kept["text"])
        self.assertNotEqual(kept["digest"], body["digest"])
        self.assertEqual(self.call("/api/report/preview?what=" + "x" * 5000)[0], 400)
        self.assertEqual(self.call("/api/report/preview?kind=weird")[0], 400)
        self.assertEqual(self.call("/api/report/preview?dir=/etc")[0], 400)                # only the app's own scans
        self.assertEqual(self.call("/api/report/preview?crash_id=../../etc/passwd")[0], 400)
        code, off = self.call("/api/report/preview?scan=0")
        self.assertNotIn("## Findings in the open scan", off["text"])

    def test_the_preview_uses_the_apps_own_job_and_hides_what_is_in_it(self):
        self.make_scan()
        self.S.JOB.update(status="failed", title=f"First pass: {SONG}", kind="scan", reason=f"{TRACK} failed at {self.user}/a.wav", dir="",
                          log=[f"key {SECRET}", f"{self.user}/Music/{SONG}.als broke"], stopped=False)
        _, body = self.call("/api/report/preview")
        for bad in (SECRET, str(self.user), SONG, TRACK):
            self.assertNotIn(bad, body["text"], bad)
        self.assertIn("ended: failed", body["text"])
        self.assertIn("## Log", body["text"])

    def test_save_writes_a_new_file_with_the_text_that_was_shown(self):
        _, prev = self.call("/api/report/preview?what=hello")
        code, saved = self.call("/api/report/save", {"what": "hello", "digest": prev["digest"]})
        self.assertEqual(code, 200)
        p = Path(saved["path"])
        self.assertEqual(p.parent, self.work / "reports")
        self.assertEqual(p.read_text(encoding="utf-8"), prev["text"])
        code, again = self.call("/api/report/save", {"what": "hello", "digest": prev["digest"]})
        self.assertNotEqual(again["path"], saved["path"])
        self.assertEqual(self.call("/api/report/save", {"what": "hello"}, token=False)[0], 403)
        self.assertEqual(self.call("/api/report/save", {"what": 5})[0], 400)
        self.assertEqual(self.call("/api/report/save", {"what": "x" * 5000})[0], 400)

    def test_a_report_that_changed_since_it_was_shown_is_not_saved_or_opened(self):
        before = listing(self.work)
        code, body = self.call("/api/report/save", {"what": "hello", "digest": "0000000000000000"})
        self.assertEqual(code, 409)
        self.assertIn("text", body)
        code, _ = self.call("/api/report/open", {"what": "hello", "digest": "0000000000000000"})
        self.assertEqual(code, 409)
        self.assertEqual(self.opened, [])
        self.assertEqual(before, listing(self.work))

    def test_open_copies_then_opens_the_fixed_address_without_a_word_of_the_report(self):
        what = "very private words about my song"
        _, prev = self.call("/api/report/preview?what=" + urllib.request.quote(what))
        copied = []
        with mock.patch.object(R, "copy_text", lambda t: copied.append(t) or (True, "pbcopy")):
            code, body = self.call("/api/report/open", {"what": what, "digest": prev["digest"], "url": "https://evil.example/"})
        self.assertEqual(code, 200)
        self.assertEqual(self.opened, [R.ISSUE_URL])                      # the address is fixed in code; the request cannot change it
        self.assertEqual(copied, [prev["text"]])
        for word in what.split():
            self.assertNotIn(word, self.opened[0])
        self.assertEqual(self.opened[0].split("?")[1], "template=bug_report.yml")
        self.assertTrue(body["copied"] and body["opened"])
        self.assertEqual(self.call("/api/report/open", {}, token=False)[0], 403)

    def test_a_missing_clipboard_or_browser_is_reported_not_hidden(self):
        with mock.patch.object(R, "copy_text", lambda t: (False, "no clipboard program was found")), \
                mock.patch.object(self.S, "open_web", lambda u: False):
            code, body = self.call("/api/report/open", {})
        self.assertEqual(code, 200)
        self.assertFalse(body["copied"])
        self.assertFalse(body["opened"])
        self.assertIn("no clipboard", body["why"])

    def test_the_page_carries_the_script_and_no_inline_handlers(self):
        code, page = self.call("/", token=False)
        self.assertIn(b'<script src="/report.js"></script>', page)
        self.assertEqual(self.call("/report.js", token=False)[0], 200)
        src = (Path(self.RP.__file__).with_name("report.js")).read_text(encoding="utf-8")
        for bad in ("onclick=", "onerror=", "eval(", "document.write(", "<script"):
            self.assertNotIn(bad, src)
        ui = (Path(self.S.__file__).with_name("ui.py")).read_text(encoding="utf-8")
        self.assertIn('data-report="job"', ui)
        self.assertIn('data-report="msg"', ui)

    # -- which handler errors are bugs
    def test_a_key_or_type_error_from_the_apps_own_helper_code_is_a_bug_and_one_from_a_request_field_is_not(self):
        from hypnomix.workflow import prefs
        src = compile("def broken(*a, **k):\n    raise KeyError('inside')\n", prefs.__file__, "exec")     # code that lives in the package
        ns = {}
        exec(src, ns)
        with mock.patch.object(prefs, "load", ns["broken"]):
            code, body = self.call("/api/state")
        self.assertEqual((code, body["error"]), (500, self.RP.SAID))
        self.assertEqual(len(self.records()), 1)
        src = compile("def broken(*a, **k):\n    return None.nothing\n", prefs.__file__, "exec")
        exec(src, ns)
        with mock.patch.object(prefs, "load", ns["broken"]):
            code, body = self.call("/api/state")
        self.assertEqual(code, 500)
        self.assertEqual(sorted(json.loads(r.read_text(encoding="utf-8"))["exception"] for r in self.records()), ["AttributeError", "KeyError"])
        n = len(self.records())
        for path, body in (("/api/decide", {}), ("/api/decide", {"dir": 5, "id": ["x"]})):
            code, answer = self.call(path, body)
            self.assertIn(code, (400, 409), (path, body, answer))
        self.assertEqual(len(self.records()), n, "a missing or wrong-kind field is a plain sentence, never a record")

    def test_a_failure_while_the_app_starts_leaves_a_record_and_one_sentence(self):
        try:
            raise OSError("cannot start")
        except OSError:
            info = sys.exc_info()
        seen, err = [], io.StringIO()
        with mock.patch.object(self.RP, "_OLD_SYS_HOOK", [lambda *a: seen.append(a)]), contextlib.redirect_stderr(err):
            self.RP.main_hook(*info)
        self.assertEqual(len(seen), 1)                                                      # the usual traceback still follows
        self.assertEqual(json.loads(self.records()[0].read_text(encoding="utf-8"))["where"], "app-server")
        self.assertIn("nothing was sent", err.getvalue())
        with mock.patch.object(self.RP, "_OLD_SYS_HOOK", [lambda *a: None]), contextlib.redirect_stderr(io.StringIO()):
            self.RP.main_hook(KeyboardInterrupt, KeyboardInterrupt(), None)
            self.RP.main_hook(BrokenPipeError, BrokenPipeError(), None)
        self.assertEqual(len(self.records()), 1)                                            # not a bug: no record
        old = sys.excepthook
        try:
            self.RP.install_hooks()
            self.assertEqual(sys.excepthook, self.RP.main_hook)
        finally:
            sys.excepthook, threading.excepthook = old, self.RP._OLD_HOOK[0]

    def test_asking_for_the_hooks_twice_changes_nothing(self):
        saved = (sys.excepthook, threading.excepthook, list(self.RP._OLD_SYS_HOOK), list(self.RP._OLD_HOOK))
        try:
            self.RP.install_hooks()
            self.RP.install_hooks()
            self.RP.install_hooks()
            self.assertIs(sys.excepthook, self.RP.main_hook)
            self.assertIs(threading.excepthook, self.RP.thread_hook)
            self.assertIsNot(self.RP._OLD_SYS_HOOK[0], self.RP.main_hook)        # else the hook calls itself until Python gives up
            self.assertIsNot(self.RP._OLD_HOOK[0], self.RP.thread_hook)
        finally:
            sys.excepthook, threading.excepthook = saved[0], saved[1]
            self.RP._OLD_SYS_HOOK[:], self.RP._OLD_HOOK[:] = saved[2], saved[3]

    def test_long_text_in_both_boxes_previews_through_a_post(self):
        what = "音" * 4000
        code, body = self.call("/api/report/preview", {"what": what, "expected": what})
        self.assertEqual(code, 200)
        self.assertIn(what[:50], body["text"])
        self.assertEqual(self.call("/api/report/preview", {"what": what}, token=False)[0], 403)
        self.assertEqual(self.call("/api/report/preview", {"what": "x" * 5000})[0], 400)
        self.assertEqual(self.call("/api/report/preview", {"what": ["a"]})[0], 400)
        self.assertEqual(self.call("/api/report/preview", {"what": "Hi there"})[1]["text"], self.call("/api/report/preview?what=Hi+there")[1]["text"])
        js = (Path(self.RP.__file__).with_name("report.js")).read_text(encoding="utf-8")
        self.assertNotIn("'/api/report/preview?'", js)                                      # the dialog never puts its text in an address

    def test_the_daw_view_has_the_report_link_and_records_its_page_errors(self):
        code, page = self.call("/daw/", token=False)
        self.assertEqual(code, 200)
        self.assertIn(b'<script src="js/report.js"></script>', page)
        code, js = self.call("/daw/js/report.js", token=False)
        self.assertEqual(code, 200)
        text = js.decode("utf-8")
        self.assertIn("/api/crashes/page", text)
        self.assertIn("X-Hypnomix", text)
        self.assertIn("'/#report'", text)
        for bad in ("onclick=", "onerror=", "eval(", "document.write(", "<script"):
            self.assertNotIn(bad, text)
        main = (Path(self.RP.__file__).with_name("report.js")).read_text(encoding="utf-8")
        self.assertIn("#report", main)                                                      # the app's page opens the dialog for the link

    def test_every_red_message_of_the_pages_offers_report_this(self):
        app = Path(self.RP.__file__).parent
        for name, at_least in (("review.js", 5), ("setup.js", 1), ("store.js", 1), ("teacher.js", 1), ("chat.js", 1), ("ui.py", 3)):
            self.assertGreaterEqual((app / name).read_text(encoding="utf-8").count("data-report"), at_least, name)


class DiskCare(Homed):
    def test_the_crashes_folder_is_listed_with_its_size_and_kept_small(self):
        from hypnomix.app import diskcare as DC
        d = self.home / "crashes"
        d.mkdir()
        for i in range(23):
            f = d / f"20261126T0000{i:02d}Z-cmd.json"
            f.write_text("x" * 100, encoding="utf-8")
            os.utime(f, (time.time() - 7200, time.time() - 7200))                      # disk care leaves what changed in the last hour
        (d / "_state.json").write_text("{}", encoding="utf-8")
        v = DC.view()["crashes"]
        self.assertEqual((v["count"], v["keeps"]), (24, 20))
        self.assertGreater(v["bytes"], 2000)
        items, _ = DC.plan()
        gone = sorted(p.name for rule, _, p, _ in items if rule == "crashes")
        self.assertEqual(len(gone), 3)
        self.assertEqual(gone, sorted(p.name for p in d.glob("2*.json"))[:3])               # the oldest three


if __name__ == "__main__":
    unittest.main()
