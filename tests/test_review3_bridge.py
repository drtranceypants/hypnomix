"""Re-check N2/N3: a `busy` file left by a REAPER that crashed or was quit mid-command never makes the bridge look
alive once that REAPER is gone, even when another REAPER is running (the same one restarted, or a second one).
`busy` and `alive` carry the bridge's start token and REAPER's process id; start() trusts only an `alive` written
after it launched; call() keeps to its own timeout unless a REAPER known to be at work holds the bridge."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hypnomix.reaper import client as C

BRIDGE = (Path(__file__).resolve().parent.parent / "hypnomix" / "reaper" / "bridge.lua").read_text(encoding="utf-8")


def age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


class StaleBusy(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.d = Path(self._td.name)
        self.r = C.Reaper(folder=self.d, timeout=2.0)
        for name, val in (("reaper_running", True), ("reaper_executable", "reaper")):
            pt = mock.patch.object(C, name, return_value=val); pt.start(); self.addCleanup(pt.stop)

    def left_over(self, cmd="render_master", pid=999999):
        """A REAPER crashed 30 s ago in the middle of `cmd`: its alive and busy files stayed."""
        (self.d / "alive").write_text(f"1\nOLD\n{pid}\n", encoding="utf-8"); age(self.d / "alive", 30)
        (self.d / "busy").write_text(f"abc\n{cmd}\nOLD\n{pid}\n", encoding="utf-8"); age(self.d / "busy", 30)

    def test_restarted_reaper_without_the_bridge_is_not_alive(self):
        self.left_over()
        with mock.patch.object(C, "pid_running", side_effect=lambda pid: False if pid == 999999 else None):
            self.assertIsNone(self.r.busy())
            self.assertFalse(self.r.alive())

    def test_start_launches_and_waits_for_a_new_beat(self):
        self.left_over()
        launched = []

        def popen(*a, **k):                              # the new REAPER's bridge beats a moment later
            launched.append(a)
            (self.d / "alive").write_text("x\nNEW\n123\n", encoding="utf-8")
            return mock.Mock()

        with mock.patch.object(C, "pid_running", side_effect=lambda pid: pid == 123), \
                mock.patch.object(C.subprocess, "Popen", side_effect=popen):
            self.assertTrue(self.r.start(wait=3))
        self.assertEqual(len(launched), 1)               # it did start a bridge
        self.assertFalse((self.d / "busy").exists())     # the left-over busy file is gone

    def test_start_does_not_take_an_old_alive_file_for_the_new_bridge(self):
        self.left_over()
        with mock.patch.object(C, "pid_running", return_value=False), \
                mock.patch.object(C.subprocess, "Popen", return_value=mock.Mock()):
            t0 = time.time()
            with self.assertRaises(C.ReaperError):
                self.r.start(wait=1.0)                   # nothing beat after the launch
            self.assertGreaterEqual(time.time() - t0, 0.9)

    def test_call_keeps_its_own_timeout_with_a_stale_busy(self):
        self.left_over()
        (self.d / "alive").write_text("1\nOLD\n999999\n", encoding="utf-8")          # fresh enough to call
        with mock.patch.object(C, "pid_running", return_value=False):
            t0 = time.time()
            with self.assertRaises(C.ReaperError):
                self.r.call("ping")
            self.assertLess(time.time() - t0, 4)

    def test_a_busy_from_an_earlier_bridge_token_does_not_count(self):
        (self.d / "alive").write_text("1\nNEW\n0\n", encoding="utf-8"); age(self.d / "alive", 30)
        (self.d / "busy").write_text("abc\nrender_master\nOLD\n0\n", encoding="utf-8")
        self.assertIsNone(self.r.busy())
        self.assertFalse(self.r.alive())

    def test_a_live_reaper_at_work_still_counts(self):
        (self.d / "alive").write_text("1\nT\n4242\n", encoding="utf-8"); age(self.d / "alive", 30)
        (self.d / "busy").write_text("abc\nrender_master\nT\n4242\n", encoding="utf-8")
        with mock.patch.object(C, "pid_running", return_value=True):
            self.assertEqual(self.r.busy(), ("abc", "render_master"))
            self.assertTrue(self.r.alive())

    def test_the_bridge_error_is_in_the_timeout_message(self):
        (self.d / "alive").write_text("1", encoding="utf-8")
        (self.d / "last-error.txt").write_text("1\nan old failure\n", encoding="utf-8")
        age(self.d / "last-error.txt", 60)                   # from before this call: not shown

        def fails():                                         # the bridge fails while handling our request
            time.sleep(0.5)
            (self.d / "last-error.txt").write_text("1\nmixer: attempt to index a nil value\n", encoding="utf-8")
        import threading
        threading.Thread(target=fails, daemon=True).start()
        with self.assertRaises(C.ReaperError) as cm:
            self.r.call("ping")
        self.assertIn("the bridge says: mixer: attempt to index a nil value", str(cm.exception))
        self.assertNotIn("an old failure", str(cm.exception))


class ReaperRunning(unittest.TestCase):
    def run_codes(self, *codes):
        it = iter(codes)
        return mock.patch.object(C.subprocess, "run", side_effect=lambda *a, **k: mock.Mock(returncode=next(it), stdout=""))

    @unittest.skipIf(os.name == "nt", "pgrep is the Mac path")
    def test_pgrep_codes(self):
        with mock.patch.object(C.platform, "system", return_value="Darwin"):
            with self.run_codes(0):
                self.assertTrue(C.reaper_running())
            with self.run_codes(1, 1):
                self.assertFalse(C.reaper_running())
            with self.run_codes(3):
                self.assertIsNone(C.reaper_running())     # pgrep itself failed: cannot tell
            with self.run_codes(1, 2):
                self.assertIsNone(C.reaper_running())


class BridgeWritesItsStamp(unittest.TestCase):
    def test_alive_and_busy_carry_token_and_pid(self):
        self.assertIn('"\\n" .. TOKEN .. "\\n" .. PID .. "\\n"', BRIDGE)
        self.assertEqual(BRIDGE.count('TOKEN .. "\\n" .. PID'), 2)
        self.assertIn('io.popen("echo $PPID")', BRIDGE)
        self.assertIn('"/last-error.txt"', BRIDGE)


class CappedWait(unittest.TestCase):
    """call() waits its turn behind another caller's command, but never past that command's own limit."""
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.d = Path(self._td.name)
        self.r = C.Reaper(folder=self.d, timeout=2.0)

    def run_bounded(self, fn, limit):
        import threading
        out = {}
        t = threading.Thread(target=lambda: out.update(err=self._catch(fn)), daemon=True)
        t0 = time.time(); t.start(); t.join(limit)
        self.assertFalse(t.is_alive(), f"call() still waiting after {limit} s")      # never hang the suite
        return out.get("err"), time.time() - t0

    @staticmethod
    def _catch(fn):
        try:
            fn()
        except C.ReaperError as e:
            return e
        return None

    def test_wait_ends_at_the_other_commands_limit(self):
        (self.d / "alive").write_text("1\nT\n4242\n", encoding="utf-8")
        (self.d / "busy").write_text("other\nrender_master\nT\n4242\n", encoding="utf-8")
        age(self.d / "busy", C.LONG["render_master"] - 1)        # its render should have ended a second from now
        with mock.patch.object(C, "pid_running", return_value=True), mock.patch.object(C, "reaper_running", return_value=True):
            err, took = self.run_bounded(lambda: self.r.call("ping"), 12)
        self.assertIsInstance(err, C.ReaperError)
        self.assertLess(took, 8)

    def test_windows_bridge_without_a_pid_still_waits_its_turn(self):
        (self.d / "alive").write_text("1\nT\n0\n", encoding="utf-8")
        (self.d / "busy").write_text("other\nrender_master\nT\n0\n", encoding="utf-8")

        def bridge():
            time.sleep(3.0)                                  # past the 2 s timeout: the render ends, then ours
            (self.d / "busy").unlink()
            for f in self.d.glob("req-*.txt"):
                (self.d / f.name.replace("req-", "res-").replace(".txt", ".json")).write_bytes(b'{"ok": true, "result": 5}')
                f.unlink()
        import threading
        threading.Thread(target=bridge, daemon=True).start()
        with mock.patch.object(C, "pid_running", return_value=None):
            out = {}
            err, _ = self.run_bounded(lambda: out.update(v=self.r.call("ping")), 12)
        self.assertIsNone(err)
        self.assertEqual(out["v"], 5)

    def test_a_slow_computers_sleeps_still_see_the_other_command(self):
        """The look at `busy` goes by the clock, not by a count of sleeps: on a slow runner each 20 ms sleep lasted far
        longer, the first look came after the 2 s timeout, and call() gave up while the other command was still running."""
        import threading
        import types
        (self.d / "alive").write_text("1\nT\n4242\n", encoding="utf-8")
        (self.d / "busy").write_text("other\nrender_master\nT\n4242\n", encoding="utf-8")

        def bridge():
            time.sleep(3.0)
            (self.d / "busy").unlink()
            for f in self.d.glob("req-*.txt"):
                (self.d / f.name.replace("req-", "res-").replace(".txt", ".json")).write_bytes(b'{"ok": true, "result": 6}')
                f.unlink()
        threading.Thread(target=bridge, daemon=True).start()
        slow = types.SimpleNamespace(time=time.time, sleep=lambda s: time.sleep(s * 5))   # each sleep lasts 5x longer
        with mock.patch.object(C, "time", slow), mock.patch.object(C, "pid_running", return_value=True):
            out = {}
            err, _ = self.run_bounded(lambda: out.update(v=self.r.call("ping")), 12)
        self.assertIsNone(err)
        self.assertEqual(out["v"], 6)


class RepeatedBridgeError(unittest.TestCase):
    def test_every_failure_is_written_again(self):
        self.assertIn("probes.err = nil", BRIDGE)            # cleared once written, so the same failure again is written
        self.assertIn("probes.err = panel.flash", BRIDGE)    # a panel that fails to draw is reported too


class OddDigits(unittest.TestCase):
    def test_only_ascii_digits_are_a_track_number(self):
        from hypnomix.reaper import mixer as M
        snap = {"tracks": [{"index": 0, "name": "١"}, {"index": 1, "name": "x"}]}
        self.assertEqual(M._find(snap, "١")["index"], 0)                    # an Arabic-Indic one is a name
        self.assertIsNone(M._find(snap, "9" * 400))                              # no crash on a huge number
        self.assertEqual(M._find(snap, "1")["index"], 1)


if __name__ == "__main__":
    unittest.main()
