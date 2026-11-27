"""Second review of reaper-parity-031, vocallevel and saving .rpp files: nothing existing is ever overwritten (the
original under another spelling of its name, an earlier --apply or --json output, an earlier "(BROKEN ...)" file),
bad input ends in one plain sentence, and envelope points far from every change are left exactly as they were
(a ride above +6 dB is refused, never cut down). Synthetic projects only."""
import contextlib
import gzip
import io
import os
import tempfile
import unittest
from pathlib import Path

from hypnomix import project
from hypnomix.project import rpp
from hypnomix.project import rpp_edit as E
from hypnomix.session import vocallevel as VL
from hypnomix.workflow import vocallevel_project as VP
from tests.test_vocallevel_reaper import Base


def case_insensitive(folder):
    probe = Path(folder) / "CaseProbe.tmp"
    probe.write_text("x", encoding="utf-8")
    try:
        return (Path(folder) / "caseprobe.tmp").exists()
    finally:
        probe.unlink()


class Outputs(Base):
    def run_quiet(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            try:
                code = VL.main([str(a) for a in args])
            except SystemExit as e:
                return e.code, buf.getvalue()
        return code, buf.getvalue()

    def test_an_existing_apply_file_is_refused_and_kept(self):
        path = self.song()
        out = self.dir / "precious.rpp"
        out.write_text("precious", encoding="utf-8")
        code, _ = self.run_quiet(path, "--apply", out)
        self.assertIn("already exists", str(code))
        self.assertEqual(out.read_text(encoding="utf-8"), "precious")

    def test_an_existing_json_file_is_refused_and_kept(self):
        path = self.song()
        j = self.dir / "ex.json"
        j.write_text("PRECIOUS", encoding="utf-8")
        code, _ = self.run_quiet(path, "--json", j)
        self.assertIn("already exists", str(code))
        self.assertEqual(j.read_text(encoding="utf-8"), "PRECIOUS")

    def test_apply_and_json_on_one_file_is_refused(self):
        path = self.song()
        code, _ = self.run_quiet(path, "--apply", self.dir / "new.rpp", "--json", self.dir / "new.rpp")
        self.assertIn("same file", str(code))
        self.assertFalse((self.dir / "new.rpp").exists())

    def test_the_original_under_another_case_is_refused(self):
        path = self.song()
        if not case_insensitive(self.dir):
            self.skipTest("this disk tells names apart by case")
        before = path.read_bytes()
        code, _ = self.run_quiet(path, "--apply", self.dir / "SONG.rpp")
        self.assertIn("refusing to overwrite the original", str(code))
        self.assertEqual(path.read_bytes(), before)

    def test_apply_into_a_missing_folder_is_one_sentence(self):
        path = self.song()
        code, _ = self.run_quiet(path, "--apply", self.dir / "nowhere" / "new.rpp")
        self.assertIsInstance(code, str)
        self.assertIn("no such folder", code)

    def test_a_missing_project_is_one_sentence(self):
        for name in ("none.rpp", "none.ardour", "none.als"):
            code, _ = self.run_quiet(self.dir / name)
            self.assertIsInstance(code, str, name)
            self.assertTrue(code.startswith("no such file:"), code)
            self.assertIn("check the name and the folder", code)

    def test_a_new_file_is_still_written(self):
        path = self.song()
        out, j = self.dir / "new.rpp", self.dir / "v.json"
        code, text = self.run_quiet(path, "--apply", out, "--json", j)
        self.assertEqual(code, 0, text)
        self.assertTrue(out.exists() and j.exists())
        self.assertEqual(E.check(path, out), [])

    def test_broken_rename_never_replaces_an_earlier_broken_file(self):
        path = self.song()
        out = self.dir / "new.rpp"
        earlier = self.dir / "new (BROKEN, do not open).rpp"
        earlier.write_text("earlier", encoding="utf-8")
        real_check = E.check
        E.check = lambda *a, **k: ["forced failure"]
        try:
            code, text = self.run_quiet(path, "--apply", out)
        finally:
            E.check = real_check
        self.assertEqual(code, 1, text)
        self.assertEqual(earlier.read_text(encoding="utf-8"), "earlier")
        self.assertTrue((self.dir / "new (BROKEN, do not open) 2.rpp").exists())
        self.assertFalse(out.exists())

    def test_live_apply_refuses_an_existing_set_before_measuring(self):
        als = self.dir / "Song.als"
        with gzip.open(als, "wb") as f:
            f.write(b"<Ableton />")
        out = self.dir / "New.als"
        out.write_bytes(b"keep")
        renders = self.dir / "Audio"
        code, _ = self.run_quiet(als, "--renders", renders, "--apply", out)
        self.assertIn("already exists", str(code))
        self.assertEqual(out.read_bytes(), b"keep")


class Save(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)
        self.src = self.dir / "Song.rpp"
        self.src.write_text('<REAPER_PROJECT 0.1 "7.86/macOS-arm64" 1\n  TEMPO 120 4 4\n>\n', encoding="utf-8")

    def tearDown(self):
        self._td.cleanup()

    def test_save_refuses_an_existing_file(self):
        out = self.dir / "Other.rpp"
        out.write_text("keep", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            rpp.save(rpp.load(self.src), out)
        self.assertIn("already exists", str(cm.exception))
        self.assertEqual(out.read_text(encoding="utf-8"), "keep")

    def test_save_refuses_the_original_under_any_spelling(self):
        before = self.src.read_bytes()
        names = [self.src, self.dir / "." / "Song.rpp"]
        if case_insensitive(self.dir):
            names.append(self.dir / "SONG.RPP")
        for n in names:
            with self.assertRaises(SystemExit) as cm:
                rpp.save(rpp.load(self.src), n)
            self.assertIn("original", str(cm.exception), n)
        self.assertEqual(self.src.read_bytes(), before)

    def test_save_refuses_a_missing_folder(self):
        with self.assertRaises(SystemExit) as cm:
            rpp.save(rpp.load(self.src), self.dir / "nope" / "x.rpp")
        self.assertIn("no such folder", str(cm.exception))

    def test_save_writes_a_new_file_byte_for_byte(self):
        out = rpp.save(rpp.load(self.src), self.dir / "Song (fixed).rpp")
        self.assertEqual(out.read_bytes(), self.src.read_bytes())

    def test_rpp_edit_save_is_covered_too(self):
        out = self.dir / "x.rpp"
        out.write_text("keep", encoding="utf-8")
        with self.assertRaises(SystemExit):
            E.save(project.load(self.src), out)
        self.assertEqual(out.read_text(encoding="utf-8"), "keep")

    def test_free_name_numbers_a_taken_name(self):
        a = self.dir / "Song (BROKEN, do not open).rpp"
        self.assertEqual(rpp.free_name(a), a)
        a.write_text("x", encoding="utf-8")
        self.assertEqual(rpp.free_name(a).name, "Song (BROKEN, do not open) 2.rpp")

    def test_same_file_tells_different_files_apart(self):
        other = self.dir / "Other.rpp"
        self.assertFalse(rpp.same_file(self.src, other))
        self.assertTrue(rpp.same_file(self.src, Path(os.path.relpath(self.src)) if os.name != "nt" else self.src))


class HotEnvelope(Base):
    def test_a_ride_above_six_db_is_refused_not_cut_down(self):
        path = self.song(lead_env=[(0, 1.0), (5.0, 3.0), (20.0, 3.0)])
        p = project.load(path)
        lead = p.track("Lead Vocal")
        before = [ln.raw if hasattr(ln, "raw") else None for _, _, ln in E.points(E.volume_envelope(lead))]
        with self.assertRaises(ValueError) as cm:
            VP.write_gains(lead, [(7.0, 10.0, 2.0)])
        self.assertIn("+6 dB", str(cm.exception))
        pts = [(t, v) for t, v, _ in E.points(E.volume_envelope(lead))]
        self.assertEqual(pts, [(0.0, 1.0), (5.0, 3.0), (20.0, 3.0)])     # nothing changed on a refusal
        self.assertEqual(before, [ln.raw if hasattr(ln, "raw") else None for _, _, ln in E.points(E.volume_envelope(lead))])

    def test_a_hot_point_far_from_every_change_is_left_exactly_as_it_was(self):
        path = self.song(lead_env=[(0, 1.0), (5.0, 1.0), (10.6, 1.0), (19.0, 3.0), (20.0, 3.0)])
        p = project.load(path)
        lead = p.track("Lead Vocal")
        self.assertEqual(VP.write_gains(lead, [(3.5, 6.5, 2.0)]), 1)
        out = self.dir / "new.rpp"
        E.save(p, out)
        q = project.load(out)
        pts = {round(t, 4): v for t, v in q.track("Lead Vocal").envelopes["Volume"]}
        self.assertAlmostEqual(pts[19.0], 3.0, 9)
        self.assertAlmostEqual(pts[20.0], 3.0, 9)
        text = out.read_text(encoding="utf-8")
        self.assertIn("PT 19.0 3.0 0", text)                                 # its line text untouched

    def test_untouched_points_keep_their_text(self):
        path = self.song(lead_env=[(0, 1.0), (18.5, 0.6)])
        raw = path.read_text(encoding="utf-8").replace("PT 18.5 0.6 0", "PT 18.500000 0.600000 0")
        path.write_text(raw, encoding="utf-8")
        p = project.load(path)
        VP.write_gains(p.track("Lead Vocal"), [(7.0, 10.0, 2.0)])
        out = self.dir / "new.rpp"
        E.save(p, out)
        self.assertIn("PT 18.500000 0.600000 0", out.read_text(encoding="utf-8"))

    def test_a_boost_past_the_top_is_refused(self):
        path = self.song(lead_env=[(0, 1.9)])
        p = project.load(path)
        with self.assertRaises(ValueError):
            VP.write_gains(p.track("Lead Vocal"), [(7.0, 10.0, 2.0)])


if __name__ == "__main__":
    unittest.main()
