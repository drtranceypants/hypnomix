"""Disk care: what the app clears on its own, and what it must never touch."""
import gzip, json, os, tempfile, time, unittest
from pathlib import Path

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

    def tearDown(self):
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


if __name__ == "__main__":
    unittest.main()
