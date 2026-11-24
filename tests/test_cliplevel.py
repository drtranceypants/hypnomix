"""cliplevel findings: an option with the raise and the reason, never applied by default."""
import unittest
from hypnomix.session import cliplevel as C


class Findings(unittest.TestCase):
    def test_text_and_fields(self):
        fs = C.findings([dict(track="Harmony 1", clip="7", a=64.0, b=80.0, level=-30.0, typical=-24.0, raise_db=6.0,
                              note="", new_gain=2.0)])
        f = fs[0]
        self.assertEqual(f["id"], "cliplevel-1"); self.assertEqual(f["where"], "bar 17.1")
        self.assertIn("6.0 dB under", f["problem"]); self.assertIn("never applied unless approved", f["fix"])
        self.assertNotIn("default", f)                     # not on by default


if __name__ == "__main__":
    unittest.main()
