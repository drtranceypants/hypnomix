"""Review fixes for REAPER's hands-on mixer tools (mixer.lua / mixer.py / client.py), against the fake bridge in
test_reaper_mixer."""
import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path

import soundfile as sf

from hypnomix.reaper import client as CL
from hypnomix.reaper import mixer as MX
from tests.test_reaper_mixer import LUA, SR, FakeBridge, fake_measure, tone


class WholeBridge(FakeBridge):
    """A solo render of several tracks (the whole-song render) sounds like the master: bar 1 quiet."""
    def __init__(self, folder, skip=()):
        super().__init__(folder)
        self.skip = set(skip)

    def call(self, cmd, **k):
        if cmd == "mixer_solo_render" and "," in k["tracks"]:
            self.calls.append((cmd, k))
            y = tone(100.0, secs=k["end"] - k["start"])
            y[: int(SR * 2)] *= 0.1
            sf.write(k["path"], y, SR, subtype="FLOAT")
            return {"path": k["path"], "exists": True, "soloed": 3}
        if cmd == "mixer_solo_render" and k["tracks"] in self.skip:
            self.calls.append((cmd, k))
            return {"path": k["path"], "exists": False, "soloed": 1}       # REAPER wrote nothing
        return super().call(cmd, **k)


class OwnPlugins(unittest.TestCase):
    """#6 / #12: HypnoMix's own JSFX are found whatever the case of their name; the bridge's values are left out."""
    def test_name_match_ignores_case(self):
        self.assertNotIn('"Hypnomix Probe"', LUA)
        self.assertNotIn('"Hypnomix Main"', LUA)
        self.assertIn('ln:find("hypnomix probe", 1, true)', LUA)
        self.assertIn('ln:find("hypnomix main", 1, true)', LUA)
        self.assertRegex(LUA, r"local ln = \(name or \"\"\):lower\(\)")

    def test_slot_and_ab_gain_are_skipped(self):
        jsfx = (Path(MX.__file__).parent / "jsfx" / "hypnomix_main.jsfx").read_text(encoding="utf-8")
        shown = re.search(r"^slider\d+:abgain=[^>]*>-?(.*)$", jsfx, re.M).group(1).lower()
        self.assertIn("match gain", shown)                       # what TrackFX_GetParamName gives
        self.assertIn('lp:find("match gain", 1, true)', LUA)
        self.assertIn('lp:find("slot", 1, true)', LUA)


class Revert(unittest.TestCase):
    """#13: --revert puts the mix back even when B fails."""
    def _failing_b(self, td, restore_fails=False):
        b, said, n = FakeBridge(td), [], [0]

        def measure(wav):
            n[0] += 1
            if n[0] == 2:
                raise RuntimeError("measuring B broke")
            return fake_measure(wav)
        if restore_fails:
            real = b.call

            def call(cmd, **k):
                if cmd == "mixer_restore":
                    raise MX.ReaperError("mixer_restore: bridge gone")
                return real(cmd, **k)
            b.call = call
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                MX.loop(b, 2.0, 6.0, Path(td) / "loop", label="kick", ab=["db Kick -3"], revert=True,
                        measure=measure, log=said.append)
        return b, said

    def test_b_failure_still_restores(self):
        with tempfile.TemporaryDirectory() as td:
            b, said = self._failing_b(td)
            self.assertIsNotNone(b.restored)
            self.assertTrue(any("put back" in s for s in said))

    def test_restore_failure_keeps_the_first_error_and_says_so(self):
        with tempfile.TemporaryDirectory() as td:
            _, said = self._failing_b(td, restore_fails=True)
            self.assertTrue(any("may still hold the B changes" in s for s in said))

    def test_no_revert_no_restore(self):
        with tempfile.TemporaryDirectory() as td:
            b = FakeBridge(td)
            with contextlib.redirect_stdout(io.StringIO()):
                MX.loop(b, 2.0, 6.0, Path(td) / "loop", ab=["db Kick -3"], measure=fake_measure, log=lambda *a: None)
            self.assertIsNone(b.restored)


class StaleRenders(unittest.TestCase):
    """#14: a file left by an earlier run never passes for this run's render."""
    def test_diagnose_ignores_an_old_solo_file(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "dx"
            folder.mkdir()
            sf.write(str(folder / "solo-002.wav"), tone(2000.0), SR)      # Lead Vocal, from last time
            b = WholeBridge(td, skip={"{V}"})
            out = MX.diagnose(b, folder, bars=2, log=lambda *a: None)
            self.assertEqual(out["units"]["Lead Vocal"].get("error"), "REAPER did not write the render")

    def test_render_master_removes_the_old_file_first(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out" / "take.wav"
            path.parent.mkdir()
            path.write_bytes(b"old")
            r = CL.Reaper.__new__(CL.Reaper)
            r.call = lambda cmd, **k: {}                                # REAPER writes nothing
            with self.assertRaises(CL.ReaperError):
                r.render_master(0.0, 1.0, path)
            self.assertFalse(path.exists())


class TakeNumbers(unittest.TestCase):
    """#15: takes keep counting past 99, and the previous take is the highest number."""
    def test_past_99(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "loop"
            folder.mkdir()
            for n in (9, 99, 100):
                (folder / f"{n:02d}-take.wav").write_bytes(b"")
                (folder / f"{n:02d}-take.json").write_text('{"metrics": {"integrated_lufs": %d}}' % n, encoding="utf-8")
            b = FakeBridge(td)
            with contextlib.redirect_stdout(io.StringIO()):
                out = MX.loop(b, 2.0, 6.0, folder, measure=fake_measure, log=lambda *a: None)
            self.assertEqual(Path(out["take"]).name, "101-take.wav")
            prev = sorted((f for f in folder.glob("*-*.json") if MX._take_no(f) is not None), key=MX._take_no)
            self.assertEqual(prev[-2].name, "100-take.json")
            self.assertEqual(MX._take_no(Path("05-x.wav")), 5)
            self.assertIsNone(MX._take_no(Path("whole.wav")))


class DiagnoseArgs(unittest.TestCase):
    """#16: a bad --bars is a plain message, before anything renders."""
    def test_zero_bars(self):
        b = FakeBridge(".")
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                MX.main_diagnose(["--bars", "0"], r=b)
        self.assertIn("--bars", str(cm.exception.code))
        self.assertEqual(b.calls, [])


class WholeSolo(unittest.TestCase):
    """#17: the whole-song render solos every top-level unit, so the user's own solos don't pick the bars."""
    def test_whole_render_solos_every_unit(self):
        with tempfile.TemporaryDirectory() as td:
            b = WholeBridge(td)
            out = MX.diagnose(b, Path(td) / "dx", bars=2, log=lambda *a: None)
            solos = [k for c, k in b.calls if c == "mixer_solo_render"]
            self.assertEqual(solos[0]["tracks"], "{D},{V},{R}")
            self.assertEqual((solos[0]["start"], solos[0]["end"]), (0.0, 8.0))
            self.assertEqual([k["tracks"] for k in solos[1:]], ["{D}", "{V}"])
            self.assertFalse([c for c, _ in b.calls if c == "render_master"])
            self.assertEqual(out["loud_bars"], [2, 3])

    def test_given_whole_file_skips_the_render(self):
        with tempfile.TemporaryDirectory() as td:
            whole = Path(td) / "mine.wav"
            y = tone(100.0, secs=8.0)
            y[: int(SR * 2)] *= 0.1
            sf.write(str(whole), y, SR)
            b = WholeBridge(td)
            MX.diagnose(b, Path(td) / "dx", bars=2, whole=str(whole), log=lambda *a: None)
            solos = [k["tracks"] for c, k in b.calls if c == "mixer_solo_render"]
            self.assertEqual(solos, ["{D}", "{V}"])


if __name__ == "__main__":
    unittest.main()
