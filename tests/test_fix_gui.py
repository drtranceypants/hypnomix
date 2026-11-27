"""Fixes in the app's pages (hypnomix/app/ui.py, review.js, teacher.js, wiki.js, setup.js, setup.py): what the server tells the
pages is checked by running it; what the page scripts do is checked in a real browser when they are changed (no JavaScript engine
is needed to run this file), and here by reading their source for the rule each fix put in."""
import json, os, re, shutil, sys, tempfile, threading, unittest, urllib.parse
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tests.test_app import call, F

APP = Path(__file__).resolve().parents[1] / "hypnomix" / "app"


def src(name):
    return (APP / name).read_text(encoding="utf-8")


class GuiServer(unittest.TestCase):
    """The same stand-in as the app's own tests: the server runs for real, the commands it would start are recorded."""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.root = Path(cls.td.name)
        cls.work = cls.root / "work"
        cls.music = cls.root / "music"
        cls.music.mkdir()
        cls._env = os.environ.get("HYPNOMIX_APP_HOME")
        os.environ["HYPNOMIX_APP_HOME"] = str(cls.work)
        from hypnomix.app import server as S
        cls.S = S
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(0))
        port = cls.srv.server_address[1]
        cls.srv.RequestHandlerClass = S.make_handler(port)
        cls.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.td.cleanup()
        if cls._env is None:
            os.environ.pop("HYPNOMIX_APP_HOME", None)
        else:
            os.environ["HYPNOMIX_APP_HOME"] = cls._env

    def setUp(self):
        shutil.rmtree(self.work / "scan", ignore_errors=True)
        for f in self.music.iterdir():
            shutil.rmtree(f) if f.is_dir() else f.unlink()
        self.S.JOB.update(status="idle", log=[], files=[], reason="", stopped=False, dir="", kind="")
        self.runs = []
        self._run_job = self.S.run_job
        self.S.run_job = lambda kind, title, steps, sdir="", watch=(): (self.runs.append((kind, title, steps, str(sdir), list(watch))), 1)[1]

    def tearDown(self):
        self.S.run_job = self._run_job

    def post(self, path, body):
        return call(self.base, path, body, self.S.TOKEN)

    def scan(self, name, source, findings, dec=None, mode="set", **meta):
        d = self.work / "scan" / name
        (d / "ab").mkdir(parents=True)
        (d / "findings.json").write_text(json.dumps(dict(set=str(source), notes=[], findings=findings)), encoding="utf-8")
        (d / "scan.json").write_text(json.dumps(dict(dict(set=str(source), mode=mode), **meta)), encoding="utf-8")
        if dec is not None:
            (d / "decisions.json").write_text(json.dumps(dec), encoding="utf-8")
        return d

    def source(self, name, text="x"):
        p = self.music / name
        p.write_text(text, encoding="utf-8")
        return p

    def songs(self):
        code, st, _ = call(self.base, "/api/state")
        self.assertEqual(code, 200)
        return {s["name"]: s for s in st["scans"]}

    def result(self, d):
        code, r, _ = call(self.base, "/api/fix/result?dir=" + urllib.parse.quote(str(d)))
        self.assertEqual(code, 200, r)
        return r

    # ---- a failed Apply is not "applied" (Songs card, result page)
    def test_a_run_that_wrote_nothing_does_not_mark_the_song_applied(self):
        als = self.source("Song.als")
        d = self.scan("Song", als, [F("smooth-1")], {"smooth-1": {"decision": "approve"}})
        (d / "fix-log.md").write_text("\n## fix run now\n\n### FAILED (not done)\n\n- tune-Vox: not tuned\n", encoding="utf-8")      # every run appends here, even one that wrote nothing
        (d / "history").mkdir()
        (d / "history" / "history.json").write_text(json.dumps({"versions": [dict(n=1, kind="fix", input=str(als), output=None, approved=[dict(id="smooth-1")], failed=["tune-Vox: x"])]}), encoding="utf-8")
        self.assertFalse(self.songs()["Song"]["applied"])
        new = self.source("Song (fixed).als")
        (d / "history" / "history.json").write_text(json.dumps({"versions": [dict(n=1, kind="fix", input=str(als), output=str(new), approved=[dict(id="smooth-1")], failed=[])]}), encoding="utf-8")
        self.assertTrue(self.songs()["Song"]["applied"])                                    # a new file the run made, still there
        new.unlink()
        self.assertFalse(self.songs()["Song"]["applied"])                                   # gone: nothing is applied any more

    def test_a_folder_scan_is_applied_when_its_fixed_folder_has_the_repaired_copies(self):
        stems = self.music / "Stems"
        stems.mkdir()
        d = self.scan("Stems", stems, [F("clip-1", "repair", "clip", applies="audio")], {"clip-1": {"decision": "approve"}}, mode="folder")
        (d / "fix-log.md").write_text("\n## fix run now\n", encoding="utf-8")
        self.assertFalse(self.songs()["Stems"]["applied"])
        (d / "fixed").mkdir()
        (d / "fixed" / "Bass.wav").write_text("x", encoding="utf-8")
        self.assertTrue(self.songs()["Stems"]["applied"])

    def test_a_failed_apply_that_wrote_nothing_says_so_and_lists_no_spots_to_listen_at(self):
        als = self.source("Song.als")
        d = self.scan("Song", als, [F("smooth-1", where="12.3.50"), F("tune-Vox", "tune", "pitch", applies="audio")],
                      {"smooth-1": {"decision": "approve"}, "tune-Vox": {"decision": "approve"}})
        (d / "fix-log.md").write_text("\n## fix run now\n\napproved: smooth-1, tune-Vox\n\n### FAILED (not done)\n\n"
                                      "- tune-Vox: not tuned: confirm the key with the person, then pass --key \"<key>\" (the scan estimated None)\n", encoding="utf-8")
        (d / "history").mkdir()
        (d / "history" / "history.json").write_text(json.dumps({"versions": [dict(
            n=1, kind="fix", at="2026-11-26 10:00:00", input=str(als), output=None, approved=[dict(id="smooth-1"), dict(id="tune-Vox")], failed=["x"])]}), encoding="utf-8")
        self.S.JOB.update(id=3, status="failed", kind="fix", dir=str(d.resolve()), files=[], stopped=False,
                          reason=self.S.app_words('tune-Vox: not tuned: confirm the key with the person, then pass --key "<key>" (the scan estimated None)'),
                          log=["$ hypnomix fix", "FAILED (not done):"])
        r = self.result(d)
        self.assertEqual(r["status"], "failed")
        self.assertTrue(r["wrote_nothing"])
        self.assertEqual((r["listen"], r["applied"]), ([], []))                              # nothing was written, so there is nothing to listen to
        self.assertNotIn("--key", r["reason"])
        self.assertNotIn("None", r["reason"])
        self.assertIn("Confirmed key", r["reason"])
        for line in r["run"]["sections"][-1]["lines"]:
            self.assertNotIn("--key", line["t"])

    def test_a_stopped_apply_that_did_write_a_file_is_not_called_nothing(self):
        als = self.source("Song.als")
        new = self.source("Song (fixed).als")
        d = self.scan("Song", als, [F("order-1", "order", "track-order", where=""), F("tune-Vox", "tune", "pitch", applies="audio")])
        (d / "fix-log.md").write_text("\n## fix run now\n", encoding="utf-8")
        (d / "history").mkdir()
        (d / "history" / "history.json").write_text(json.dumps({"versions": [dict(n=1, kind="fix", input=str(als), output=str(new), approved=[dict(id="order-1")], failed=["tune-Vox: x"])]}), encoding="utf-8")
        self.S.JOB.update(id=4, status="failed", kind="fix", dir=str(d.resolve()), files=[str(new)], stopped=False, reason="tune-Vox: x", log=["x"])
        r = self.result(d)
        self.assertFalse(r["wrote_nothing"])
        self.assertEqual([f["name"] for f in r["files"]], ["Song (fixed).als"])
        self.assertEqual([x["id"] for x in r["applied"]], ["order-1"])

    def test_a_second_failed_apply_on_a_folder_is_not_credited_with_the_first_runs_copies(self):
        stems = self.music / "Stems"
        stems.mkdir()
        d = self.scan("Stems", stems, [F("clip-1", "repair", "clip", applies="audio")], {"clip-1": {"decision": "approve"}}, mode="folder")
        (d / "fix-log.md").write_text("\n## fix run now\n\n### FAILED (not done)\n\n- clip-1: not repaired\n", encoding="utf-8")
        (d / "fixed").mkdir()
        (d / "fixed" / "Bass (dehiss).wav").write_text("x", encoding="utf-8")                                     # what an earlier run left
        self.S.JOB.update(id=5, status="failed", kind="fix", dir=str(d.resolve()), files=[], stopped=False, reason="clip-1: not repaired", log=["x"])
        r = self.result(d)
        self.assertTrue(r["wrote_nothing"])                                                    # this run wrote nothing
        self.assertEqual((r["files"], r["applied"]), ([], []))
        self.S.JOB.update(dir="", kind="")                                                     # app restarted: the old copies are all there is to go by
        self.assertFalse(self.result(d)["wrote_nothing"])

    def test_the_page_reads_a_failed_apply_by_what_was_written(self):
        ui = src("ui.py")
        self.assertIn("part = bad && !r.wrote_nothing", ui)
        self.assertIn("Applied in part", ui)
        self.assertIn("r.wrote_nothing && !bad", ui)                                          # one banner, not "Nothing was written" under the failure banner
        self.assertIn("r.listen.length && !r.wrote_nothing", ui)

    # ---- tuning needs its key before Apply starts; the page says it in its own words
    def test_apply_with_tuning_approved_and_no_key_is_refused_in_one_sentence(self):
        als = self.source("Song.als")
        d = self.scan("Song", als, [F("tune-Vox", "tune", "pitch", applies="audio")], {"tune-Vox": {"decision": "approve"}})
        code, j, _ = self.post("/api/fix", dict(dir=str(d), key="  "))
        self.assertEqual(code, 409, j)
        self.assertIn("Confirmed key", j["error"])
        self.assertNotIn("--key", j["error"])
        self.assertEqual(self.runs, [])
        code, j, _ = self.post("/api/fix", dict(dir=str(d), key="F# major"))
        self.assertEqual(code, 200, j)
        self.assertIn("--key", self.runs[-1][2][0][1])
        # a key given when the scan was made counts
        d2 = self.scan("Song2", als, [F("tune-Vox", "tune", "pitch", applies="audio")], {"tune-Vox": {"decision": "approve"}}, key="A minor")
        self.assertEqual(self.post("/api/fix", dict(dir=str(d2), out="Other"))[0], 200)
        self.assertEqual(self.review(d2)["scan_key"], "A minor")

    def review(self, d):
        code, r, _ = call(self.base, "/api/review?dir=" + urllib.parse.quote(str(d)))
        self.assertEqual(code, 200, r)
        return r

    def test_answers_to_key_questions_go_to_fix_as_answer_flags(self):
        als = self.source("Song.als")
        d = self.scan("Song", als, [F("smooth-1"), F("key-1", "key", "key-question", applies="answer", notes=["F", "F#"], bars=["17-24"])],
                      {"smooth-1": {"decision": "approve"}})
        code, j, _ = self.post("/api/fix", dict(dir=str(d), answers=["F#", " 17-24=F ", ""]))
        self.assertEqual(code, 200, j)
        argv = self.runs[-1][2][0][1]
        self.assertEqual([argv[i + 1] for i, x in enumerate(argv) if x == "--answer"], ["F#", "17-24=F"])
        for bad in ("F#", [3], ["x" * 301]):
            code, j, _ = self.post("/api/fix", dict(dir=str(d), answers=bad))
            self.assertEqual(code, 400, bad)

    def test_the_question_card_has_an_answer_box_and_apply_sends_what_was_typed(self):
        js, ui = src("review.js"), src("ui.py")
        self.assertIn("data-answer=", js)
        self.assertNotIn("put your answer in the box when you apply", js)                     # the sentence that promised a box that was not there
        self.assertIn("f.applies !== 'answer' ? ovItemHTML", js)                              # no confidence or common practice on a question
        self.assertIn("body.answers = said", ui)
        self.assertIn("rvAnswers", js)

    def test_app_words_turn_the_commands_flags_into_the_pages_boxes(self):
        w = self.S.app_words
        self.assertEqual(w("tune-Vox: not tuned: confirm the key with the person, then pass --key \"<key>\" (the scan estimated A major)"),
                         "tune-Vox: not tuned: type the song's key in the \"Confirmed key\" box on the review page (open the review again), then apply again (the scan estimated A major)")
        self.assertIn("(the scan found no estimate)", w("x (the scan estimated None)"))
        self.assertNotIn("--key", w("tune-Vox: not tuned: this scan has no key map; re-scan or pass --key \"<key>\""))
        self.assertNotIn("--key", w("a: confirm the key with the person, then pass --key \"<key>\" or --key sections after answering its questions (the scan estimated A)"))
        self.assertEqual(w(""), "")

    def test_the_apply_button_refuses_in_the_page_before_it_asks_to_confirm(self):
        ui = src("ui.py")
        i = ui.index("b.id === 'apply'")
        seg = ui[i:i + 2600]
        self.assertLess(seg.index("Vocal tuning is approved"), seg.index("confirm("))

    # ---- the doctor's own failed lines are the reason
    def test_a_reports_crossed_lines_are_why_it_stopped(self):
        log = ["$ hypnomix doctor", " ✓ Python                    3.11", " ✗ AbletonOSC remote script  not installed (or the unpatched upstream version): hypnomix install",
               " · extra [ml] (basic_pitch)  not installed", " ✓ extra [critique] (openai)  installed", "", "✓ ok   ✗ needed   · optional", "(doctor: exit code 1)"]
        why = self.S.job_reason(log)
        self.assertEqual(why, "AbletonOSC remote script: not installed (or the unpatched upstream version): hypnomix install")
        self.assertEqual(self.S.job_reason(["$ hypnomix x", "boom", "(x: exit code 1)"]), "boom")             # a plain failure still gives its last lines

    # ---- a pasted path loses the quotes a file manager adds
    def test_a_pasted_path_may_keep_its_quotes_or_be_a_file_url(self):
        b = self.S.bare_path
        self.assertEqual(b('"/a/B C/Real Song.als"'), "/a/B C/Real Song.als")
        self.assertEqual(b("  '/a/b.rpp' "), "/a/b.rpp")
        self.assertEqual(b("\u201c/a/b.rpp\u201d"), "/a/b.rpp")
        self.assertEqual(b("file:///a/B%20C/s.als"), "/a/B C/s.als")
        self.assertEqual(b("file:///C:/Music/s.rpp"), "C:/Music/s.rpp")
        self.assertEqual(b("/a/it's/b.als"), "/a/it's/b.als")                               # a quote inside is part of the name
        als = self.source("Real Song.als")
        wav = self.source("m.wav")
        for wrapped in (f'"{als}"', f"'{als}'", f"  {als}  ", als.as_uri()):
            self.runs.clear()
            code, j, _ = self.post("/api/scan", dict(source=wrapped, mix=f'"{wav}"'))
            self.assertEqual(code, 200, (wrapped, j))
            argvs = [s[1] for s in self.runs[-1][2] if isinstance(s[1], list)]
            scan = next(a for a in argvs if a and a[0] == "scan")
            self.assertEqual(Path(scan[scan.index("--mix") + 1]).resolve(), wav.resolve())
            self.assertIn(str(als.resolve()), scan)
        code, j, _ = self.post("/api/scan", dict(source='"/nowhere/x.als"'))
        self.assertEqual(code, 400)
        self.assertNotIn('"', j["error"])                                                     # the message names the path, not the quotes

    def test_the_page_cleans_a_pasted_path_too(self):
        ui = src("ui.py")
        self.assertIn("const barePath", ui)
        self.assertNotIn("t.value.trim()", ui[ui.index("document.addEventListener('input'"):ui.index("document.addEventListener('play'")])

    # ---- words that fit the song's own DAW
    def test_review_words_follow_the_songs_own_daw(self):
        js, ui = src("review.js"), src("ui.py")
        self.assertIn("const dawOf", js)
        for dead in ("'Show in Live'", ">Show in Live<", "'Build A/B set for Live'", '<span class="tag">A/B in Live</span>'):
            self.assertNotIn(dead, js)
        self.assertIn("hypnomix reaper review", js)
        self.assertIn("Build A/B ${noun} for ${daw}", js)
        self.assertIn("S.review.kind === 'rpp'", ui)                                          # the "device is not connected" notice too

    def test_the_a_b_build_job_is_named_for_the_scans_daw(self):
        for name, ext, mode, want in (("Song", ".als", "set", "A/B set for Live: Song"), ("Proj", ".rpp", "reaper", "A/B project for REAPER: Proj"),
                                      ("Sess", ".ardour", "ardour", "A/B build: Sess")):
            d = self.scan(name, self.source(name + ext), [F("smooth-1")], mode=mode)
            self.runs.clear()
            code, j, _ = self.post("/api/ab/build", dict(dir=str(d)))
            self.assertEqual(code, 200, j)
            self.assertEqual(self.runs[-1][1], want)

    def test_abset_says_ardour_has_no_a_b_build_and_does_not_ask_for_a_live_set(self):
        from hypnomix.workflow import abset
        d = self.scan("Sess", self.music / "Sess.ardour", [F("smooth-1")], mode="ardour")
        (self.music / "Sess.ardour").write_text("<Session/>", encoding="utf-8")
        with self.assertRaises(RuntimeError) as cm:
            abset.build(d)
        self.assertIn("HypnoMix DAW has no A/B build yet", str(cm.exception))
        self.assertNotIn("Live", str(cm.exception))
        text = (Path(abset.__file__).with_name("ab.py")).read_text(encoding="utf-8")
        self.assertIn("build the A/B project with `hypnomix abset`", text)                    # the REAPER note points at the build

    # ---- the file chooser
    def test_the_state_says_whether_the_chooser_can_open_and_the_page_leaves_out_dead_buttons(self):
        S = self.S
        code, st, _ = call(self.base, "/api/state")
        self.assertIn("chooser", st)
        with mock.patch.object(S.sys, "platform", "win32"), mock.patch("importlib.util.find_spec", return_value=None):
            self.assertFalse(S.chooser_available())
        with mock.patch.object(S.sys, "platform", "win32"), mock.patch("importlib.util.find_spec", return_value=object()):
            self.assertTrue(S.chooser_available())
        with mock.patch.object(S.sys, "platform", "darwin"):
            self.assertTrue(S.chooser_available())
        ui = src("ui.py")
        self.assertIn("st.chooser !== false", ui)
        self.assertIn("data-form=\"mix\"", ui)                                                # the paths of the other files can still be typed
        self.assertNotIn("on every system", (Path(__file__).resolve().parents[1] / "docs" / "APP.md").read_text(encoding="utf-8"))

    # ---- the setup step that makes a command
    def test_the_setup_never_writes_through_a_link_or_over_a_command_it_did_not_make(self):
        from hypnomix.app import setup as SU
        home = self.root / "sh"
        (home / ".local" / "bin").mkdir(parents=True)
        ext = home / "ext"
        ext.mkdir()
        orig = ext / "hypnomix-orig"
        orig.write_text("ORIGINAL user script\n", encoding="utf-8")
        shim = home / ".local" / "bin" / "hypnomix"
        agent = self.root / "agent"
        try:
            shim.symlink_to(orig)
        except (OSError, NotImplementedError):
            self.skipTest("this system makes no symbolic links")
        with mock.patch.object(SU, "shim_path", lambda: shim), mock.patch.object(SU, "agent_dir", lambda: agent):
            r = SU.make_cli()
            self.assertEqual(orig.read_text(encoding="utf-8"), "ORIGINAL user script\n")                     # not written through
            self.assertTrue(shim.is_symlink())
            self.assertIn("left exactly as it is", r["note"])
            self.assertTrue((agent / "AGENTS.md").exists() or (agent / "CLAUDE.md").exists())          # the folder is still made
            shim.unlink()
            shim.write_text("#!/bin/sh\nexec pipx run hypnomix\n", encoding="utf-8")                             # a plain file that is not ours
            self.assertIn("left exactly as it is", SU.make_cli()["note"])
            self.assertIn("pipx", shim.read_text(encoding="utf-8"))
            shim.write_text("#!/usr/bin/python3\nfrom hypnomix.cli import main\nmain()\n", encoding="utf-8")        # a pip console script names hypnomix.cli too
            self.assertIn("left exactly as it is", SU.make_cli()["note"])
            self.assertIn("from hypnomix.cli import main", shim.read_text(encoding="utf-8"))
            shim.unlink()
            r = SU.make_cli()                                                                  # nothing there: it is made
            self.assertEqual(r["note"], "")
            self.assertIn("hypnomix.cli", shim.read_text(encoding="utf-8"))
            self.assertEqual(r["command"], str(shim))                                           # the command it made, not another one found on the PATH
            shim.write_text(shim.read_text(encoding="utf-8") + "# older\n", encoding="utf-8")                                     # one it made earlier is made again
            self.assertEqual(SU.make_cli()["note"], "")
            self.assertNotIn("# older", shim.read_text(encoding="utf-8"))

    def test_the_assistant_leaves_out_its_choose_buttons_when_the_app_has_no_file_chooser(self):
        js = src("chat.js")
        self.assertIn("S.state && S.state.chooser === false ? '' : '<button data-cpick=\"set\">", js)

    def test_the_live_pill_and_the_reaper_card_note_follow_the_songs_daw(self):
        ui, rv = src("ui.py"), src("review.js")
        self.assertIn("noLive", ui)
        self.assertIn("lv.hidden = !lt", ui)
        self.assertIn("noteWords(R, ab.note)", rv)
        self.assertNotIn("hypnomix abset", rv.split("const noteWords")[1].split("function cardHTML")[0].split("'To hear it")[1])    # the replacement names the page's button
        self.assertIn("Build A/B project for REAPER", rv.split("const noteWords")[1])
        code, st, _ = call(self.base, "/api/state")
        self.assertIn("daw", st)                                                               # the page hides the Live pill for a REAPER or Ardour person

    def test_the_setup_says_when_an_ai_was_not_connected(self):
        js = src("setup.js")
        self.assertIn("tested !== 'ok'", js)
        self.assertIn("'Setup saved'", js)
        self.assertIn("The AI is not connected yet: the last connection test did not pass", js)
        self.assertIn("The AI connection was not tested in this setup", js)                   # a key saved earlier is not called "not connected"
        self.assertNotIn("its connection was not tested", js)

    # ---- the DAW in Setup and in Preferences is one answer wherever HYPNOMIX_HOME points
    def test_prefs_read_the_setup_choice_from_hypnomix_home(self):
        from hypnomix.workflow import prefs
        home = self.root / "hh"
        home.mkdir()
        (home / "setup.json").write_text(json.dumps({"daw": "reaper"}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"HYPNOMIX_HOME": str(home), "HOME": str(self.root / "nobody"), "USERPROFILE": str(self.root / "nobody")}):
            self.assertEqual(prefs.setup_daw(), "reaper")                                   # the folder HYPNOMIX_HOME names, as setup.py keeps it
        with mock.patch.dict(os.environ, {"HYPNOMIX_HOME": str(self.root / "elsewhere"), "HOME": str(self.root / "nobody"), "USERPROFILE": str(self.root / "nobody")}):
            self.assertEqual(prefs.setup_daw(), "")
        (self.root / "nobody" / ".hypnomix").mkdir(parents=True)
        (self.root / "nobody" / ".hypnomix" / "setup.json").write_text(json.dumps({"daw": "ardour"}), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "HYPNOMIX_HOME"}
        env["HOME"] = env["USERPROFILE"] = str(self.root / "nobody")
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(prefs.setup_daw(), "ardour")                                   # unset: the usual place

    def test_the_preferences_page_shows_setups_daw_as_the_unanswered_default(self):
        home = self.root / "hh2"
        home.mkdir()
        (home / "setup.json").write_text(json.dumps({"daw": "reaper"}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"HYPNOMIX_HOME": str(home), "HOME": str(self.root / "nobody2"), "USERPROFILE": str(self.root / "nobody2")}):
            qs = {q["key"]: q for q in call(self.base, "/api/prefs")[1]}
            self.assertEqual(qs["tools.daw"]["default"], "reaper")                          # not a fixed "live"
        with mock.patch.dict(os.environ, {"HYPNOMIX_HOME": str(self.root / "nowhere"), "HOME": str(self.root / "nobody2"), "USERPROFILE": str(self.root / "nobody2")}):
            qs = {q["key"]: q for q in call(self.base, "/api/prefs")[1]}
            self.assertEqual(qs["tools.daw"]["default"], "live")                            # Setup never answered: the question's own default


class PageRules(unittest.TestCase):
    """What the page scripts do, as the rules their source now follows (each was also run in a browser when it was changed)."""

    def test_the_lesson_and_article_lists_are_links_the_keyboard_reaches(self):
        for name, attrs in (("teacher.js", ("data-tstep", "data-tjump")), ("wiki.js", ("data-wart",))):
            text = src(name)
            for a in attrs:
                for m in re.finditer(r"<a\s[^>]*" + a + r"=", text):
                    self.assertIn('href="#"', text[m.start():m.end()], f"{name}: a link with {a} has no href")
        self.assertIn("aria-current=\"step\"", src("teacher.js"))
        self.assertIn("aria-current=\"page\"", src("wiki.js"))
        t = src("teacher.js")
        self.assertIn("if (b.tagName === 'A') e.preventDefault();", t)                       # a real link goes nowhere by itself
        self.assertIn("teachFocus()", t)

    def test_the_glossary_filter_has_the_pages_input_style_a_label_and_starts_empty(self):
        t, ui = src("teacher.js"), src("ui.py")
        self.assertIn("input[type=search]", ui[:ui.index("</style>")])
        self.assertIn('id="tgq" type="search" aria-label="Filter the words"', t)
        self.assertIn("T.glq = '';", t[t.index("if (ds.tgloss)"):t.index("if (ds.tjump)")])

    def test_setup_takes_the_keyboard_holds_it_and_escape_is_skip(self):
        js = src("setup.js")
        self.assertIn("x.inert = true", js)                                                    # the page behind takes no focus
        self.assertIn("h.focus(", js)                                                          # on every step the heading gets the keyboard
        self.assertIn("function trap(e)", js)
        self.assertIn("if (e.key === 'Escape') { e.preventDefault(); finish('skip'); }", js)   # the same path as the Skip setup button
        self.assertIn("if (a === 'skip' || a === 'finish') return finish(a);", js)
        self.assertIn("/api/setup/finish", js[js.index("async function finish"):js.index("function draw")])
        self.assertIn("position:sticky;bottom:0", js)                                          # Next is never far below the fold

    def test_a_notice_belongs_to_its_screen_and_polling_stops_in_a_hidden_tab(self):
        ui = src("ui.py")
        go = ui[ui.index("function go(view, extra)"):]
        self.assertIn("showMsg('')", go[:go.index("\n")])
        self.assertIn("if (!document.hidden) tick();", ui)
        self.assertIn("visibilitychange", ui)
        pj = ui[ui.index("async function pollJob()"):ui.index("function startJob")]
        self.assertIn("a job that ended and was already taken", pj)

    def test_the_preferences_page_takes_any_number_its_help_says_and_shows_a_saved_one(self):
        ui = src("ui.py")
        seg = ui[ui.index("async function prefsView()"):ui.index("// ---------------------------------------------------------------- live (probes)")]
        self.assertIn("data-num=\"1\"", seg)
        self.assertIn("<datalist", seg)
        self.assertIn("const own =", seg)                                                      # a saved answer that is not in the list is still shown
        self.assertIn("el.dataset.num", ui)                                                    # an empty number box is not sent

    def test_the_tools_pickers_use_the_flag_the_commands_usage_names(self):
        ui = src("ui.py")
        self.assertIn("function pickFlag(kind)", ui)
        self.assertIn("pickFlag(ds.toolpick)", ui)
        self.assertNotIn("' \"' + r.path + '\"'", ui)
        self.assertIn("includes('=')", ui)                                                     # `plugins --folder FORMAT=DIR` takes no bare path
        node = shutil.which("node")
        if node:                                                                               # run the function itself when a JavaScript engine is at hand
            import subprocess
            body = ui[ui.index("function pickFlag(kind)"):ui.index("function toolsView()")]
            code = "const S={toolHelp:process.argv[1]};" + body + "console.log(JSON.stringify(['set','audio','folder'].map(pickFlag)));"
            run = lambda usage: json.loads(subprocess.run([node, "-e", code, usage], capture_output=True, text=True, check=True, encoding="utf-8").stdout)
            self.assertEqual(run("usage: hypnomix plugins [-h] [--free] [--folder FORMAT=DIR] [--save]"), ["", "", ""])
            self.assertEqual(run("usage: hypnomix loop [-h] --set SET [--folder DIR]"), ["--set ", "", "--folder "])

    def test_the_review_says_what_was_decided_for_the_mouse_too_and_the_help_floats(self):
        js, ui = src("review.js"), src("ui.py")
        i = js.index("function decideOne")
        self.assertIn("announce(", js[i:i + 700])
        i = js.index("function setAmount")
        self.assertIn("announce(", js[i:i + 500])
        i = js.index("function decideCur")
        self.assertNotIn("announce(", js[i:js.index("function togglePlay")])                  # not said twice
        self.assertIn("#rvhelp:not([hidden]){position:fixed", ui)
        self.assertIn("id=\"rvhelpclose\"", js)

    def test_the_like_this_button_and_its_box_count_the_same_things(self):
        js = src("review.js")
        self.assertIn("const others = r.includes_example ? r.n - 1 : r.n;", js)
        self.assertIn("${verb} this one and the ${others} like it?", js)

    def test_the_popups_have_a_label_take_the_keyboard_close_on_escape_and_show_links(self):
        for name, pop, btn in (("update.js", "updpop", "ver"), ("diskcare.js", "dcpop", "btn")):
            text = src(name)
            self.assertIn(f"#{pop} a", text)
            self.assertIn("setAttribute('role', 'dialog')", text)
            self.assertIn("p.focus(", text)
            self.assertIn(f"getElementById('{pop}'); if (e.key === 'Escape' && p)", text)
            self.assertIn(f"{btn}.focus()", text)
        self.assertIn('id="dcclose"', src("diskcare.js"))

    def test_the_songs_card_and_notes_wrap_a_long_unbroken_path(self):
        ui = src("ui.py")[:src("ui.py").index("</style>")]
        self.assertRegex(ui, r"\.song \.name\{[^}]*overflow-wrap:anywhere")
        self.assertRegex(ui, r"\.note\{[^}]*overflow-wrap:anywhere")


if __name__ == "__main__":
    unittest.main()
