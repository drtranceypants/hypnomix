"""Record and review before export in REAPER: the relay hands the bridge's events to the app, and the app renders
exactly what played and reviews it with the song card's targets."""
import os
import tempfile
import unittest

from hypnomix.reaper import probes as RP


class FakeReaper:
    def __init__(self):
        self.calls, self.renders = [], []

    def call(self, cmd, **k):
        self.calls.append((cmd, k))
        return {}

    def render_master(self, start, end, path):
        self.renders.append((start, end, path))
        open(path, "wb").close()
        return path


class Hub:
    on_record = None


class Relay(unittest.TestCase):
    def test_no_app_says_so(self):
        with self.assertRaises(RP.NoApp):                               # Main then says to open the app (3)
            RP.handle(Hub(), {"ev": "start", "pos": 0}, FakeReaper())

    def test_stop_marks_reviewing(self):
        h, r, seen = Hub(), FakeReaper(), []
        h.on_record = lambda ev, rr: seen.append(ev["ev"])
        RP.handle(h, {"ev": "start", "pos": 2.0}, r)
        self.assertEqual(r.calls, [])
        RP.handle(h, {"ev": "stop", "start": 2.0, "end": 9.5}, r)
        self.assertEqual(seen, ["start", "stop"])
        self.assertEqual(r.calls, [("rec_status", {"code": 4})])


class MainStates(unittest.TestCase):
    def test_every_state_has_its_words(self):
        """Each state the bridge can report has its own line on Main (a failed review is not 'no app')."""
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / "hypnomix" / "reaper"
        main = (root / "jsfx" / "hypnomix_main.jsfx").read_text()
        lua = (root / "bridge.lua").read_text()
        for k in range(1, 7):
            self.assertIn(f"rr_state == {k} ?", main)
        self.assertIn("!rr_down && rr_was && rr_armed && rr_in ?", main)      # a press counts on release
        self.assertIn("or reaper.time_precise() - rec.began > 3 then", lua)  # playback gets time to start
        self.assertIn("if rec.last - rec.start < 1.0 then reaper.gmem_write(GM_STATE, 5); return false end", lua)


class App(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        os.environ["HYPNOMIX_APP_HOME"] = self.td.name
        from hypnomix.app import server as S
        self.S = S
        self.jobs = []
        self._run_job = S.run_job
        S.run_job = lambda kind, title, steps, d="": self.jobs.append((title, steps)) or None
        self._hub = S.PROBE["hub"]
        S.PROBE["hub"] = None

    def tearDown(self):
        self.S.run_job = self._run_job
        self.S.PROBE["hub"] = self._hub
        self.S.MASTER["path"] = ""
        os.environ.pop("HYPNOMIX_APP_HOME", None)
        self.td.cleanup()

    def test_render_what_played_and_review_with_the_card(self):
        S, r = self.S, FakeReaper()

        class CardHub:
            capture = None
            def begin(self, label=""):
                self.capture = {"label": label}
            def end(self, out_dir, song=""):
                self.capture = None
                return out_dir / "capture.json"
            def song_card(self):
                return dict(sig="abc", song=dict(target=-12, ceiling=-1, mode="punch", amount=80))
        S.PROBE["hub"] = CardHub()
        start = S.reaper_record({"ev": "start", "pos": 2.0}, r)
        self.assertTrue(start["path"].endswith(".wav"))
        S.reaper_record({"ev": "stop", "start": 2.0, "end": 9.5}, r)
        self.assertEqual(r.renders, [(2.0, 9.5, start["path"])])          # exactly the stretch that played
        title, steps = self.jobs[-1]
        cmds = {s[1][0]: s[1] for s in steps}
        self.assertEqual(cmds["probe"][:3], ["probe", "report", str(S.work() / "captures" / "capture.json")])
        self.assertEqual(cmds["qc"][-2:], ["--target", "-12"])            # the card's target reaches qc
        self.assertIn("punch", cmds["master"])
        self.assertIn("80", cmds["master"])

    def test_too_short_is_refused(self):
        with self.assertRaises(RuntimeError):
            self.S.reaper_record({"ev": "stop", "start": 3.0, "end": 3.4}, FakeReaper())


if __name__ == "__main__":
    unittest.main()
