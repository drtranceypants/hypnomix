"""Disk care: what the app clears on its own, and what it must never touch."""
import gzip, json, os, tempfile, time, unittest
from pathlib import Path

from tests import _isolate

OLD = time.time() - 40 * 86400


def touch(p, n=1000, when=OLD):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * n)
    os.utime(p, (when, when))
    return p


class DiskCare(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        r = Path(self.td.name)
        self.env = {k: os.environ.get(k) for k in ("HYPNOMIX_USER_HOME", "HYPNOMIX_HOME", "HYPNOMIX_APP_HOME")}
        os.environ.update(HYPNOMIX_USER_HOME=str(r), HYPNOMIX_HOME=str(r / ".hypnomix"), HYPNOMIX_APP_HOME=str(r / "Documents/Hypnomix"))
        from hypnomix.app import diskcare as DC
        self.DC, self.r = DC, r
        self._space = DC.space            # the test must not depend on how full this computer's own disk is
        DC.space = lambda: (500 * DC.GB, 1000 * DC.GB)

    def tearDown(self):
        self.DC.space = self._space
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.td.cleanup()

    def paths(self):
        return {str(i[2].relative_to(self.r)) for i in self.DC.plan("ok")[0]}

    def test_the_teacher_tabs_audio_examples_are_covered(self):
        touch(self.r / ".hypnomix/cache/teach/low-cut-a-v3.wav")                      # idle for weeks: made again on demand
        touch(self.r / ".hypnomix/cache/teach/low-cut-b-v3.wav", when=time.time())
        got = self.paths()
        self.assertIn(".hypnomix/cache/teach/low-cut-a-v3.wav", got)
        self.assertNotIn(".hypnomix/cache/teach/low-cut-b-v3.wav", got)

    def test_clears_old_leftovers_keeps_the_rest(self):
        r = self.r
        touch(r / ".hypnomix/cache/render/abc/x.wav")
        touch(r / ".hypnomix/cache/render/new/x.wav", when=time.time())
        scan = r / "Documents/Hypnomix/scan/song"
        touch(scan / "findings.json")
        touch(scan / "ab/a.wav")
        touch(r / "Documents/Hypnomix/hypnomix-out/dehiss/v.wav")
        for i in range(7):
            touch(r / f"Documents/Hypnomix/bounces/master-{i}.wav", when=OLD - i * 86400)
        got = self.paths()
        self.assertIn(".hypnomix/cache/render/abc", got)
        self.assertNotIn(".hypnomix/cache/render/new", got)
        self.assertIn("Documents/Hypnomix/scan/song/ab/a.wav", got)
        self.assertNotIn("Documents/Hypnomix/scan/song/findings.json", got)
        self.assertIn("Documents/Hypnomix/hypnomix-out/dehiss/v.wav", got)
        bounces = [p for p in got if "bounces" in p]
        self.assertEqual(sorted(bounces), ["Documents/Hypnomix/bounces/master-5.wav", "Documents/Hypnomix/bounces/master-6.wav"])

    def test_never_audio_a_project_uses(self):
        r = self.r
        touch(r / "Documents/Hypnomix/hypnomix-out/dehiss/Lead clean.wav")
        als = r / "Music/Song Project/Song.als"
        als.parent.mkdir(parents=True)
        with gzip.open(als, "wb") as f:
            f.write(b'<Ableton><FileRef><Path Value="/x/hypnomix-out/dehiss/Lead clean.wav" /></FileRef></Ableton>')
        self.assertNotIn("Documents/Hypnomix/hypnomix-out/dehiss/Lead clean.wav", self.paths())

    def test_loose_wavs_only_when_switched_on_and_restorable(self):
        r = self.r
        w = touch(r / "Desktop/old take.wav")
        touch(r / "Desktop/Song final.wav")
        touch(r / "Downloads/new.wav", when=time.time())
        self.assertNotIn("Desktop/old take.wav", self.paths())
        self.DC.settings({"wavs": True})
        got = self.paths()
        self.assertEqual({p for p in got if not p.startswith(".")}, {"Desktop/old take.wav"})
        self.DC.run()
        self.assertFalse(w.exists())
        self.assertEqual(self.DC.view()["holding"]["batches"], 1)
        self.DC.restore()
        self.assertTrue(w.exists())

    def test_waits_for_a_running_job_and_respects_off(self):
        touch(self.r / ".hypnomix/cache/render/abc/x.wav")
        self.DC.run(job_running=lambda: True)
        self.assertTrue((self.r / ".hypnomix/cache/render/abc").exists())
        self.DC.settings({"auto": False})
        self.assertFalse(self.DC.due())
        self.DC.settings({"auto": True})
        self.assertTrue(self.DC.due())
        self.DC.run()
        self.assertFalse((self.r / ".hypnomix/cache/render/abc").exists())
        self.assertFalse(self.DC.due())

    def test_notifies_only_when_it_matters(self):
        DC, GB, DAY = self.DC, self.DC.GB, self.DC.DAY
        s = {}
        self.assertTrue(DC.should_notify(s, 2 * GB, "ok"))            # freed something real
        self.assertFalse(DC.should_notify(s, 0, "ok"))
        self.assertTrue(DC.should_notify(s, 0, "low"))                # first time low
        s["notified"] = dict(when=DC.time.time(), level="low")
        self.assertFalse(DC.should_notify(s, 0, "low"))               # the same news an hour later: quiet
        self.assertTrue(DC.should_notify(s, 0, "critical"))           # fuller than at the last notice
        s["notified"]["when"] -= DAY + 1
        self.assertTrue(DC.should_notify(s, 0, "low"))                # once a day while it stays low

    def test_a_big_disk_is_not_low_with_plenty_left(self):
        GB = self.DC.GB
        self.assertEqual(self.DC.level(70 * GB, 926 * GB), "ok")     # 8% of 926 GB would have said low
        self.assertEqual(self.DC.level(45 * GB, 926 * GB), "low")
        self.assertEqual(self.DC.level(15 * GB, 926 * GB), "critical")
        self.assertEqual(self.DC.level(15 * GB, 200 * GB), "low")     # small disks keep 8% / 3%
        self.assertEqual(self.DC.level(5 * GB, 200 * GB), "critical")

    def test_off_in_the_environment_never_starts_the_hourly_look(self):
        import threading
        os.environ["HYPNOMIX_DISKCARE"] = "off"
        try:
            before = {t.name for t in threading.enumerate()}
            self.DC.start_in_background(first=0, every=1)
            self.assertNotIn("diskcare", {t.name for t in threading.enumerate()} - before)
        finally:
            os.environ.pop("HYPNOMIX_DISKCARE", None)

    # ---- which folders may be watched (the cleaner deletes old audio by rule inside them)
    def refused(self, folder, *words):
        before = self.DC.load()
        with self.assertRaises(ValueError) as c:
            self.DC.settings({"watch": [str(folder)], "wavs": True})
        for w in words:
            self.assertIn(w, str(c.exception))
        self.assertEqual(self.DC.load(), before)                    # nothing was saved, not even the other settings

    def test_watch_refuses_the_home_folder(self):
        self.refused(self.r, "home folder")
        self.refused("~", "home folder")

    def test_watch_refuses_the_top_of_the_disk(self):
        self.refused("/", "top of the disk")

    def test_watch_refuses_library(self):
        (self.r / "Library/Audio").mkdir(parents=True)
        self.refused(self.r / "Library", "Library")
        self.refused(self.r / "Library/Audio", "Library")

    def test_watch_refuses_all_of_music_desktop_documents(self):
        for n in ("Music", "Desktop", "Documents"):
            (self.r / n / "Projects").mkdir(parents=True)
            self.refused(self.r / n, f"All of {n}")
            self.refused(str(self.r / n) + "/", f"All of {n}")
            self.refused(self.r / n / "Projects" / "..", f"All of {n}")       # a dot-dot way round

    def test_watch_refuses_a_folder_outside_home_and_missing_and_relative(self):
        with tempfile.TemporaryDirectory() as other:
            self.refused(other, "outside your home folder")
        self.refused(self.r / "Music/nope", "isn't a folder that exists")
        (self.r / "Music/a.wav").parent.mkdir(parents=True)
        (self.r / "Music/a.wav").write_bytes(b"x")
        self.refused(self.r / "Music/a.wav", "isn't a folder that exists")
        self.refused("Music/Projects", "full folder path")

    def test_watch_refuses_a_link_that_leaves_home(self):
        with tempfile.TemporaryDirectory() as other:
            (self.r / "Music").mkdir()
            (self.r / "Music/link").symlink_to(other)
            self.refused(self.r / "Music/link", "outside your home folder")

    def test_watch_allows_subfolders_and_saves_the_real_path(self):
        d = self.r / "Music/Projects"
        d.mkdir(parents=True)
        v = self.DC.settings({"watch": f"{d}\n\n"})
        self.assertEqual(v["watch"], [str(d.resolve())])
        self.assertEqual(self.DC.watched(), [d.resolve()])
        (self.r / "Desktop/Takes").mkdir(parents=True)
        self.DC.settings({"watch": [str(d), str(self.r / "Desktop/Takes")]})
        self.assertEqual(len(self.DC.watched()), 2)

    def test_a_hand_edited_watch_list_cannot_widen_the_clean(self):
        self.DC.save({"watch": [str(self.r), "/", str(self.r / "Music")]})
        (self.r / "Music").mkdir()
        self.assertEqual(self.DC.watched(), [])
        via_http = self.DC.handle_post("/api/diskcare/settings", {"watch": [str(self.r)]})
        self.assertEqual(via_http[0], 400)
        self.assertIn("home folder", via_http[1]["error"])

    def test_a_watched_folder_never_loses_audio_a_project_uses(self):
        r = self.r
        work = r / "Music/Work"
        keep = touch(work / "song/hypnomix-out/dehiss/Lead clean.wav")
        gone = touch(work / "song/hypnomix-out/dehiss/Old take.wav")
        als = r / "Music/Work/Song.als"
        with gzip.open(als, "wb") as f:
            f.write(b'<Ableton><FileRef><Path Value="/x/Lead clean.wav" /></FileRef></Ableton>')
        self.DC.settings({"watch": [str(work)]})
        got = {str(i[2].relative_to(self.r.resolve())) for i in self.DC.plan("ok")[0]}
        self.assertIn("Music/Work/song/hypnomix-out/dehiss/Old take.wav", got)
        self.assertNotIn("Music/Work/song/hypnomix-out/dehiss/Lead clean.wav", got)
        self.DC.run()
        self.assertTrue(keep.exists())
        self.assertFalse(gone.exists())

    def test_a_saved_folder_that_no_longer_qualifies_still_protects_the_audio_its_projects_use(self):
        r = self.r
        with tempfile.TemporaryDirectory() as ext:                  # an external drive, say: outside the home folder
            proj = Path(ext) / "proj"
            proj.mkdir()
            (proj / "song.rpp").write_bytes(b'<REAPER_PROJECT\n  <SOURCE WAVE\n    FILE "/x/b7.wav"\n  >\n>')
            keep = touch(r / "Documents/Hypnomix/hypnomix-out/b7.wav")
            gone = touch(r / "Documents/Hypnomix/hypnomix-out/b8.wav")
            self.DC.save({"watch": [str(proj)]})                    # saved by an older version
            self.assertEqual(self.DC.watched(), [])                 # not cleaned...
            self.assertEqual([p.resolve() for p in self.DC.read_only()], [proj.resolve()])   # ...but still read
            got = self.paths()
            self.assertNotIn("Documents/Hypnomix/hypnomix-out/b7.wav", got)
            self.assertIn("Documents/Hypnomix/hypnomix-out/b8.wav", got)
            v = self.DC.view()
            self.assertEqual(v["watch"], [str(proj)])               # the person still sees it
            self.assertEqual([x["folder"] for x in v["refused"]], [str(proj)])
            self.assertIn("outside your home folder", v["refused"][0]["why"])
            self.DC.run()
            self.assertTrue(keep.exists())
            self.assertFalse(gone.exists())

    def test_read_only_never_reads_the_top_of_the_disk_home_or_library(self):
        (self.r / "Library").mkdir()
        self.DC.save({"watch": ["/", str(self.r), str(self.r / "Library"), 5, None, "", "~/nope"]})
        self.assertEqual(self.DC.read_only(), [])
        self.assertEqual(self.DC.watched(), [])

    def test_watch_of_the_wrong_type_is_a_message_not_a_crash(self):
        for bad in (5, {"a": 1}, True, 1.5):
            code, body = self.DC.handle_post("/api/diskcare/settings", {"watch": bad})
            self.assertEqual(code, 400, bad)
            self.assertIn("list of folders", body["error"])
        code, body = self.DC.handle_post("/api/diskcare/settings", {"watch": [5]})   # a number as a folder name
        self.assertEqual(code, 400)
        self.assertEqual(self.DC.load(), {})

    def test_a_hand_edited_state_file_of_the_wrong_shape_is_ignored(self):
        for w in (5, {"a": 1}, "x", [5, None, ["y"]]):
            self.DC.save({"watch": w})
            self.assertEqual(self.DC.watched(), [])
            self.assertEqual(self.DC.read_only(), [])
            self.assertIsInstance(self.DC.view()["watch"], list)

    @_isolate.POSIX_MODES
    def test_state_file_is_private(self):
        import stat
        self.DC.settings({"auto": True})
        f = self.DC.state_file()
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(f.parent.stat().st_mode), 0o700)


if __name__ == "__main__":
    unittest.main()
