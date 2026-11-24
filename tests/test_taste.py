"""taste: each song counts once; a narrow range across songs is a standard, a wide one a taste call."""
import unittest
from hypnomix.workflow import taste as T


def song(name, harm_level, rev):
    return dict(song=name, tempo=80.0, parts={"lead": 1, "harmony": 2}, returns=[("A", "reverb")], main_chain=["Limiter"],
                return_chains={}, level_vs_lead={"harmony": harm_level}, pan_width={"lead": 0.0, "harmony": 0.5},
                hard_panned={"lead": 0.0, "harmony": 0.0}, harmony_spread=1.0, reverb_send_db={"lead": rev, "harmony": rev - 3},
                delay_send_db={"lead": -70.0, "harmony": -70.0}, chains={"lead": [("EQ Eight", 1)], "harmony": [("EQ Eight", 1)]},
                automated_tracks={"lead": 1.0, "harmony": 0.0}, vocals_comped=1.0, vocal_warp_modes={"Complex Pro": 3},
                harmony_timing_ms=30.0)


class Taste(unittest.TestCase):
    def test_median_song_and_standard_vs_taste(self):
        prof = T.across([song("a", -5.0, -12.0), song("b", -6.0, -20.0), song("c", -5.5, -4.0), dict(song="d", skipped="x")])
        self.assertEqual(prof["level_vs_lead"]["harmony"]["median"], -5.5)
        self.assertTrue(T.standard(prof["level_vs_lead"]["harmony"], 4.0))     # within 1 dB across songs
        self.assertFalse(T.standard(prof["reverb_send_db"]["lead"], 6.0))      # 16 dB apart: a taste call
        self.assertEqual(prof["chains"]["lead"], [("EQ Eight", 3)])
        self.assertEqual(prof["skipped"], [("d", "x")])

    def test_roles(self):
        self.assertEqual(T.role("Harmony 3", 0.9), "harmony")
        self.assertEqual(T.role("Lead Vocal", 0.9), "lead")
        self.assertIsNone(T.role("Keys", 0.4))
