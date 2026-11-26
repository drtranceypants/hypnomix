"""`hypnomix balance`: fader proposals for a folder of stems, the plan, and fix rendering only approved moves."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix.engineer import balance as B

SR = 44100


def stem(path, f, amp, seconds=6.0):
    t = np.arange(int(SR * seconds)) / SR
    sf.write(str(path), amp * np.sin(2 * np.pi * f * t) * (((t % 2) < 1.5) * 1.0), SR, subtype="PCM_24")


def hx(*args):
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True,
                       env=dict(os.environ, HYPNOMIX_HOME=tempfile.gettempdir() + "/hx-none"))
    return r.returncode, r.stdout + r.stderr


class BalanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.stems = self.d / "stems"
        self.stems.mkdir()
        stem(self.stems / "Lead Vocal.wav", 440, 0.05)       # too quiet against the band
        stem(self.stems / "Bass.wav", 80, 0.1)
        stem(self.stems / "Pad.wav", 300, 0.05)

    def tearDown(self):
        self.tmp.cleanup()

    def test_moves_put_vocal_on_top(self):
        stems, sr, rows = B.measure(self.stems)
        self.assertEqual(rows["Lead Vocal"]["role"], "lead_vocal")
        res = B.propose(stems, sr, rows)
        mv = {m["name"]: m for m in res["moves"]}
        self.assertEqual(res["anchor"], "Lead Vocal")
        self.assertAlmostEqual(max(m["gain_db"] for m in res["moves"]), 0.0, places=1)   # loudest fader at 0
        self.assertGreater(mv["Lead Vocal"]["gain_db"], mv["Bass"]["gain_db"])
        self.assertLess(mv["Pad"]["after_lufs"], mv["Lead Vocal"]["after_lufs"])

    def test_options(self):
        stems, sr, rows = B.measure(self.stems)
        r = B.propose(stems, sr, rows, vocal_over_band=3.0)
        self.assertAlmostEqual(r["vocal"]["after"], 3.0, delta=0.6)
        k = B.propose(stems, sr, rows, keep_level=True)
        self.assertNotAlmostEqual(max(m["gain_db"] for m in k["moves"]), 0.0, places=0)
        o = B.propose(stems, sr, rows, offsets={"bass": -4.0})
        base = {m["name"]: m["gain_db"] for m in B.propose(stems, sr, rows)["moves"]}
        self.assertLess(next(m["gain_db"] for m in o["moves"] if m["name"] == "Bass"), base["Bass"] + 0.01)
        a = B.propose(stems, sr, rows, anchor="bass")
        self.assertEqual(a["anchor"], "Bass")
        with self.assertRaises(SystemExit):
            B.propose(stems, sr, rows, anchor="nothing here")
        with self.assertRaises(SystemExit):
            B.parse_offsets("flute=1")
        self.assertEqual(B.parse_offsets("bass=-1.5, hats=-2"), {"bass": -1.5, "hats": -2.0})

    def test_profile_range(self):
        rng = dict(p25=-6.0, p75=-1.0, median=-3.0, n=12)
        self.assertIn("below", B.judge(dict(gain_db=-20.0), rng))
        self.assertEqual(B.judge(dict(gain_db=-2.0), rng), "inside your usual faders")
        self.assertIsNone(B.judge(dict(gain_db=-2.0), None))

    def test_plan_then_fix_renders_only_approved(self):
        sd = self.d / "scan"
        code, out = hx("balance", self.stems, "--plan", sd)
        self.assertEqual(code, 0, out)
        self.assertEqual(list(self.stems.glob("*")).__len__(), 3)             # nothing next to the stems
        data = json.loads((sd / "findings.json").read_text())
        ids = {f["track"]: f["id"] for f in data["findings"] if f["tool"] == "balance"}
        self.assertIn("Bass", ids)
        self.assertTrue(all(f["plan"]["key"].startswith("fader:") for f in data["findings"] if f["tool"] == "balance"))
        code, out = hx("fix", sd, "--decide", f"{ids['Bass']}=approve")
        self.assertEqual(code, 0, out)
        code, out = hx("fix", sd, "--approved")
        self.assertEqual(code, 0, out)
        made = sorted(p.name for p in (sd / "fixed" / "balance").glob("*.wav"))
        self.assertEqual(len(made), 2, made)                                  # one moved stem + the trial mix
        self.assertTrue(any(n.startswith("Bass (fader") for n in made))
        self.assertFalse(any(n.startswith("Pad") for n in made))

    def test_render_refuses_to_overwrite(self):
        out = self.d / "o"
        B.render(self.stems, {"Bass": -3.0}, out)
        with self.assertRaises(SystemExit):
            B.render(self.stems, {"Bass": -3.0}, out)


if __name__ == "__main__":
    unittest.main()
