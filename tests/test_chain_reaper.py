"""`chain --reaper`: which stock plug-ins, in which order, set to what (a fake REAPER records every call)."""
import math
import unittest

from hypnomix.engineer import chain_reaper as CR


class FakeReaper:
    def __init__(self):
        self.fx, self.calls = [], []

    def fx_list(self, track):
        return []

    def add_fx(self, track, name):
        self.fx.append(name)
        return {"fx": len(self.fx) - 1}

    def set_shown(self, track, fx, param, value):
        self.calls.append(("shown", self.fx[fx], param, value))
        return {"shown": str(value)}

    def set_norm(self, track, fx, param, value):
        self.calls.append(("norm", self.fx[fx], param, value))
        return {"shown": str(value)}

    def named(self, track, fx, key, value=None):
        self.calls.append(("named", self.fx[fx], key, value))
        return {"ok": True}

    def pins(self, track, fx, output, pin, mask):
        self.calls.append(("pins", fx, output, pin, mask))
        return {"ok": True}


PLAN = [dict(device="EQ Eight", bands=[dict(type="lowcut12", freq=22, gain=0, q=0.71),
                                       dict(type="bell", freq=550, gain=-1.2, q=0.9)], why=""),
        dict(device="Glue Compressor", threshold_db=-12.5, ratio=2, attack_ms=30, release_s=0.2, makeup_db=0, why=""),
        dict(device="Utility", bass_mono_hz=120, width_pct=100, why=""),
        dict(device="Limiter", gain_db=3.0, ceiling_db=-1.0, release_ms=80, why="")]


class ChainReaper(unittest.TestCase):
    def test_q_to_octaves(self):
        self.assertAlmostEqual(CR.q_to_octaves(1.4142), 1.0, places=2)   # Q 1.41 is one octave
        self.assertAlmostEqual(CR.q_to_octaves(0.7071), 1.90, places=2)

    def test_master_chain(self):
        r = FakeReaper()
        rows, notes = CR.build_master(r, [dict(s) for s in PLAN])
        self.assertEqual(notes, [])
        self.assertEqual(r.fx, [CR.REAEQ, CR.REACOMP, CR.MS_ENC, CR.REAEQ, CR.REAEQ, CR.MS_DEC, CR.REALIMIT])
        c = r.calls
        self.assertIn(("named", CR.REAEQ, "BANDTYPE0", "4"), c)          # low cut = ReaEQ high pass
        self.assertIn(("named", CR.REAEQ, "BANDTYPE1", "8"), c)          # bell = ReaEQ band
        self.assertIn(("named", CR.REAEQ, "BANDENABLED2", "0"), c)       # unused bands off
        self.assertIn(("shown", CR.REACOMP, "Release", 200.0), c)
        # bass mono: side (channel 2) high-passed twice, mid (channel 1) all-passed, each on its own channel only
        self.assertEqual([x[4] for x in c if x[0] == "pins"], [2, 0, 2, 0, 1, 0, 1, 0])
        # ReaLimit raises the level by ceiling - threshold: +3 dB of gain at a -1 dB ceiling is a -4 dB threshold
        self.assertIn(("shown", CR.REALIMIT, "Threshold", -4.0), c)
        self.assertIn(("shown", CR.REALIMIT, "Ceiling", -1.0), c)

    def test_more_than_five_bands_uses_a_second_reaeq(self):
        r = FakeReaper()
        b = CR.Builder(r, "master")
        b.reaeq([dict(type="bell", freq=100 * (k + 1), gain=-1, q=1) for k in range(7)])
        self.assertEqual(r.fx, [CR.REAEQ, CR.REAEQ])

    def test_existing_master_plugins_are_never_silently_kept(self):
        class Busy(FakeReaper):
            def fx_list(self, track):
                return [{"name": "VST: Something"}]
        with self.assertRaises(SystemExit):
            CR.build_master(Busy(), [dict(s) for s in PLAN], existing="refuse")


if __name__ == "__main__":
    unittest.main()
