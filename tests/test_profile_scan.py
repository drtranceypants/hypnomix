"""scan compares the mix with the person's OWN ranges (their profile), in the "mix" group. Synthetic profile and mix.

Run from the repo root:  python -m unittest tests.test_profile_scan -v
"""
import json, shutil, tempfile, unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

from hypnomix.session import profile as PR
from hypnomix.workflow import scan as S

SR = 44100

# what a measure result holds, for four songs the person likes (the numbers are made up)
SONGS = [
    dict(integrated_lufs=-13.0, true_peak_dbtp=-1.0, lra_lu=5.0, crest_factor_db=12.0, spectral_centroid_hz=2000.0,
         rolloff_85_hz=4500.0, side_to_mid_db=-9.0, lr_correlation=0.60, lr_corr_below_150hz=0.95, duration_s=200.0,
         short_term_spread_lu=4.0, band_sub_20_60=-30.0, band_bass_60_250=-12.0, band_lowmid_250_500=-14.0,
         band_mid_500_2k=-12.0, band_highmid_2k_6k=-18.0, band_air_6k_20k=-30.0),
    dict(integrated_lufs=-12.0, true_peak_dbtp=-1.0, lra_lu=6.0, crest_factor_db=13.0, spectral_centroid_hz=2200.0,
         rolloff_85_hz=5000.0, side_to_mid_db=-8.0, lr_correlation=0.65, lr_corr_below_150hz=0.96, duration_s=210.0,
         short_term_spread_lu=5.0, band_sub_20_60=-29.0, band_bass_60_250=-11.0, band_lowmid_250_500=-13.5,
         band_mid_500_2k=-12.5, band_highmid_2k_6k=-17.5, band_air_6k_20k=-29.0),
    dict(integrated_lufs=-14.0, true_peak_dbtp=-1.0, lra_lu=7.0, crest_factor_db=14.0, spectral_centroid_hz=2400.0,
         rolloff_85_hz=5500.0, side_to_mid_db=-7.0, lr_correlation=0.70, lr_corr_below_150hz=0.97, duration_s=190.0,
         short_term_spread_lu=6.0, band_sub_20_60=-28.0, band_bass_60_250=-10.0, band_lowmid_250_500=-13.0,
         band_mid_500_2k=-13.0, band_highmid_2k_6k=-17.0, band_air_6k_20k=-28.0),
    dict(integrated_lufs=-13.5, true_peak_dbtp=-1.0, lra_lu=6.5, crest_factor_db=13.5, spectral_centroid_hz=2300.0,
         rolloff_85_hz=5200.0, side_to_mid_db=-7.5, lr_correlation=0.68, lr_corr_below_150hz=0.96, duration_s=205.0,
         short_term_spread_lu=5.5, band_sub_20_60=-28.5, band_bass_60_250=-10.5, band_lowmid_250_500=-13.2,
         band_mid_500_2k=-12.8, band_highmid_2k_6k=-17.2, band_air_6k_20k=-28.5),
]
PROFILE_KEYS = [k for k in SONGS[0] if k not in ("duration_s", "true_peak_dbtp")]     # the true peak is the target check's


def write_profile(path, songs=SONGS):
    prof = {"name": "mine", "songs": [f"s{i}" for i in range(len(songs))],
            "audio": {k: PR.stats([s[k] for s in songs]) for k in songs[0]}}
    Path(path).write_text(json.dumps(prof), encoding="utf-8")
    return path


def measure_result(**over):
    """A `measure` result (the file it writes) for a mix that sits in the middle of SONGS, with changes in `over`."""
    v = dict(SONGS[3], **over)
    return {"file": "mix.wav", "sr": SR, "channels": 2, "duration_s": v["duration_s"],
            "ffmpeg": {"integrated_lufs": v["integrated_lufs"], "lra_lu": v["lra_lu"], "true_peak_dbtp": v["true_peak_dbtp"]},
            "crest_factor_db": v["crest_factor_db"], "spectral_centroid_hz": v["spectral_centroid_hz"],
            "rolloff_85_hz": v["rolloff_85_hz"], "stereo_side_to_mid_db": v["side_to_mid_db"],
            "lr_correlation": v["lr_correlation"], "lr_correlation_below_150hz": v["lr_corr_below_150hz"],
            "short_term_p10_p95": [-20.0, -20.0 + v["short_term_spread_lu"]],
            "band_energy_db": {"sub_20_60": v["band_sub_20_60"], "bass_60_250": v["band_bass_60_250"],
                               "lowmid_250_500": v["band_lowmid_250_500"], "mid_500_2k": v["band_mid_500_2k"],
                               "highmid_2k_6k": v["band_highmid_2k_6k"], "air_6k_20k": v["band_air_6k_20k"]}}


class Tmp(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, True)
        self.prof = write_profile(self.td / "profile.json")


class OwnRange(Tmp):
    def compare(self, **over):
        ranges = PR.profile_ranges(self.prof)
        return S.own_range_findings(S.profile_values(measure_result(**over)), ranges)

    def test_a_mix_inside_the_ranges_gives_nothing(self):
        found, compared = self.compare()
        self.assertEqual(found, [])
        self.assertEqual(compared, len(PROFILE_KEYS))

    def test_a_dark_mix_is_one_finding_in_plain_words_with_the_numbers(self):
        found, _ = self.compare(spectral_centroid_hz=1500.0)
        self.assertEqual(len(found), 1)
        f = found[0]
        self.assertEqual((f["tool"], f["kind"], f["track"], f["applies"]), ("profile", "own-range", "mix", "manual"))
        self.assertEqual(f["id"], "mix-profile-spectral_centroid_hz")
        for text in ("2000 and 2400 Hz", "middle 2250 Hz", "this mix is 1500 Hz", "500 Hz below", "darker than your songs"):
            self.assertIn(text, f["problem"])
        self.assertIn("Listen for:", f["fix"])
        self.assertIn("Nothing is changed", f["fix"])

    def test_one_finding_per_measure_and_the_direction_is_named(self):
        found, _ = self.compare(side_to_mid_db=-3.0, crest_factor_db=9.0)
        self.assertEqual(sorted(f["id"] for f in found), ["mix-profile-crest_factor_db", "mix-profile-side_to_mid_db"])
        by = {f["id"]: f["problem"] for f in found}
        self.assertIn("above that (wider than your songs)", by["mix-profile-side_to_mid_db"])
        self.assertIn("below that (flatter than your songs)", by["mix-profile-crest_factor_db"])

    def test_severity_grows_with_the_distance(self):
        near = self.compare(spectral_centroid_hz=2550.0)[0][0]       # 150 Hz over: under the width of the middle half
        far = self.compare(spectral_centroid_hz=4500.0)[0][0]
        self.assertEqual(near["severity"], "low")
        self.assertEqual(far["severity"], "medium")
        self.assertNotIn("high", {near["severity"], far["severity"]})   # a taste check is never urgent

    def test_a_miss_smaller_than_the_noise_is_not_reported(self):
        self.assertEqual(self.compare(spectral_centroid_hz=2450.0)[0], [])      # 50 Hz over the highest song

    def test_a_mono_mix_skips_the_width_measures(self):
        m = measure_result()
        for k in ("stereo_side_to_mid_db", "lr_correlation", "lr_correlation_below_150hz"):
            del m[k]
        found, compared = S.own_range_findings(S.profile_values(m), PR.profile_ranges(self.prof))
        self.assertEqual((found, compared), ([], len(PROFILE_KEYS) - 3))

    def test_loudness_is_left_to_the_target_check_when_that_spoke(self):
        values = S.profile_values(measure_result(integrated_lufs=-20.0))
        ranges = PR.profile_ranges(self.prof)
        self.assertEqual([f["id"] for f in S.own_range_findings(values, ranges)[0]], ["mix-profile-integrated_lufs"])
        self.assertEqual(S.own_range_findings(values, ranges, skip={"mix-loudness"})[0], [])

    def test_the_text_has_no_double_punctuation(self):
        every = {k: v for k, v in dict(integrated_lufs=-30.0, lra_lu=20.0, crest_factor_db=3.0, short_term_spread_lu=20.0,
                                       spectral_centroid_hz=9000.0, rolloff_85_hz=12000.0, band_sub_20_60=-5.0,
                                       band_bass_60_250=-2.0, band_lowmid_250_500=-3.0, band_mid_500_2k=-4.0,
                                       band_highmid_2k_6k=-5.0, band_air_6k_20k=-6.0, side_to_mid_db=5.0,
                                       lr_correlation=-0.5, lr_corr_below_150hz=0.2).items()}
        for over in (every, {k: -v for k, v in every.items()}):
            found, _ = self.compare(**over)
            self.assertGreaterEqual(len(found), 12)
            for f in found:
                for text in (f["problem"], f["fix"]):
                    for bad in ("?.", "..", ".?", "!.", " ,", "  "):
                        self.assertNotIn(bad, text, f["id"])
                self.assertTrue(f["fix"].startswith("Listen for: "), f["id"])

    def test_a_loudness_gap_is_in_lu_not_lufs(self):
        f = self.compare(integrated_lufs=-9.0)[0][0]
        self.assertIn("this mix is -9.0 LUFS, 3.0 LU above that", f["problem"])
        self.assertNotIn("LUFS above", f["problem"])
        self.assertNotIn("LUFS below", f["problem"])

    def test_a_range_with_no_width_says_all_at_one_value(self):
        write_profile(self.prof, [dict(SONGS[0], spectral_centroid_hz=883.0)] * 3)
        f = [x for x in self.compare(spectral_centroid_hz=2000.0)[0] if x["id"].endswith("spectral_centroid_hz")][0]
        self.assertIn("sit at 883 Hz here", f["problem"])
        self.assertNotIn("between 883 and 883", f["problem"])
        self.assertNotIn("middle", f["problem"])

    def test_a_small_profile_says_the_range_is_rough(self):
        write_profile(self.prof, SONGS[:3])
        f = self.compare(spectral_centroid_hz=1500.0)[0][0]
        self.assertIn("only 3 songs", f["problem"])
        write_profile(self.prof, SONGS * 2)
        self.assertNotIn("only", self.compare(spectral_centroid_hz=1500.0)[0][0]["problem"])

    def test_a_result_with_nothing_to_give_is_not_a_crash(self):
        for m in ({}, {"silent": True}, {"ffmpeg": None}, None):
            self.assertEqual(S.profile_values(m), {})
        m = measure_result()
        m["short_term_p10_p95"] = None                 # a mix under 3 s: every measure but the spread still counts
        v = S.profile_values(m)
        self.assertNotIn("short_term_spread_lu", v)
        self.assertIn("spectral_centroid_hz", v)


class Check(Tmp):
    def setUp(self):
        super().setUp()
        self.mj = self.td / "mix.json"
        self.mj.write_text(json.dumps(measure_result(spectral_centroid_hz=1500.0)), encoding="utf-8")

    def test_no_profile_is_one_info_line_and_no_findings(self):
        f, notes = S.profile_check(self.mj, path=self.td / "nope.json")
        self.assertEqual(f, [])
        self.assertEqual(len(notes), 1)
        self.assertIn("hypnomix profile build", notes[0])

    def test_a_broken_or_tiny_profile_is_a_note(self):
        (self.td / "bad.json").write_text("{not json", encoding="utf-8")
        f, notes = S.profile_check(self.mj, path=self.td / "bad.json")
        self.assertEqual((f, len(notes)), ([], 1))
        self.assertIn("could not be read", notes[0])
        write_profile(self.td / "two.json", SONGS[:2])
        f, notes = S.profile_check(self.mj, path=self.td / "two.json")
        self.assertEqual(f, [])
        self.assertIn("2 songs", notes[0])

    def test_a_missing_measurement_is_a_note(self):
        f, notes = S.profile_check(self.td / "no-such.json", path=self.prof)
        self.assertEqual(f, [])
        self.assertIn("no measurements", notes[0])

    def test_findings_and_a_summary_note(self):
        f, notes = S.profile_check(self.mj, path=self.prof)
        self.assertEqual([x["id"] for x in f], ["mix-profile-spectral_centroid_hz"])
        self.assertIn("1 of 15 measure sits outside", notes[0])
        self.mj.write_text(json.dumps(measure_result()), encoding="utf-8")
        f, notes = S.profile_check(self.mj, path=self.prof)
        self.assertEqual(f, [])
        self.assertIn("all 15 measures sit inside", notes[0])


class Switch(unittest.TestCase):
    def test_flag_and_preference_turn_it_off(self):
        with mock.patch("hypnomix.workflow.prefs.load", return_value={}):
            self.assertTrue(S.profile_wanted(Namespace()))
            self.assertTrue(S.profile_wanted(Namespace(no_profile=False)))
            self.assertFalse(S.profile_wanted(Namespace(no_profile=True)))
        for v in ("off", "no", False, "False", "0"):
            with mock.patch("hypnomix.workflow.prefs.load", return_value={"taste": {"profile": v}}):
                self.assertFalse(S.profile_wanted(Namespace(no_profile=False)), v)
        with mock.patch("hypnomix.workflow.prefs.load", return_value={"taste": {"profile": "on"}}):
            self.assertTrue(S.profile_wanted(Namespace(no_profile=False)))

    def test_the_preference_can_be_saved_with_prefs_set(self):
        from hypnomix.workflow import prefs as P
        self.assertIs(P.parse("taste.profile", "off"), "off")           # `hypnomix prefs set taste.profile=off`

    def test_the_flag_is_in_the_help(self):
        import io, contextlib
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scan", "-h"]), contextlib.redirect_stdout(buf), self.assertRaises(SystemExit):
            S.main()
        self.assertIn("--no-profile", buf.getvalue())


class InTheMixGroup(Tmp):
    """g_mix with the tools stubbed: the comparison reads what `measure` wrote, and measures nothing again."""

    def run_group(self, mix_over, profile=True, no_profile=False, said="mix.wav: -13.5 LUFS (pyln -13.5), TP -1.0 dBTP, LRA 6.5 LU"):
        od = self.td / "scan"
        calls = []

        def fake_hx(tool, *args, **kw):
            calls.append(tool)
            if tool == "measure":
                out = Path(args[2])
                out.mkdir(parents=True, exist_ok=True)
                (out / (Path(args[0]).stem + ".json")).write_text(json.dumps(measure_result(**mix_over)), encoding="utf-8")
                return 0, said
            return 0, "ok"

        a = Namespace(mix=str(self.td / "mix.wav"), like=None, no_profile=no_profile)
        prof = self.prof if profile else self.td / "none.json"
        with mock.patch.object(S, "hx", fake_hx), mock.patch("hypnomix.core.paths.PROFILE", prof), \
                mock.patch("hypnomix.workflow.prefs.load", return_value={}):
            found, notes = S.g_mix(self.td / "x.als", od, a)
        return found, notes, calls

    def test_findings_land_in_the_mix_group_and_measure_runs_once(self):
        found, notes, calls = self.run_group(dict(spectral_centroid_hz=1500.0, side_to_mid_db=-3.0))
        mine = [f for f in found if f["tool"] == "profile"]
        self.assertEqual(sorted(f["id"] for f in mine), ["mix-profile-side_to_mid_db", "mix-profile-spectral_centroid_hz"])
        self.assertTrue(all(f["track"] == "mix" and f["applies"] == "manual" for f in mine))
        self.assertEqual(calls.count("measure"), 1)
        self.assertIn("2 of 15 measures sit outside", notes[0])

    def test_the_count_includes_the_loudness_the_target_check_said(self):
        found, notes, _ = self.run_group(dict(spectral_centroid_hz=1500.0, integrated_lufs=-20.0),
                                          said="mix.wav: -20.0 LUFS (pyln -20.0), TP -1.0 dBTP, LRA 6.5 LU")
        self.assertIn("mix-loudness", {f["id"] for f in found})
        self.assertEqual([f["id"] for f in found if f["tool"] == "profile"], ["mix-profile-spectral_centroid_hz"])
        self.assertIn("2 of 15 measures sit outside", notes[0])

    def test_a_failed_release_check_is_reported_without_a_reference(self):
        """qc failing must show up as a high finding, with or without --like (it was lost when it sat under --like)."""
        od = self.td / "scan"

        def fake_hx(tool, *args, **kw):
            if tool == "measure":
                out = Path(args[2])
                out.mkdir(parents=True, exist_ok=True)
                (out / (Path(args[0]).stem + ".json")).write_text(json.dumps(measure_result()), encoding="utf-8")
                return 0, "mix.wav: -13.5 LUFS (pyln -13.5), TP -1.0 dBTP, LRA 6.5 LU"
            return (1, "FAILED: clipping") if tool == "qc" else (0, "ok")
        a = Namespace(mix=str(self.td / "mix.wav"), like=None, no_profile=True)
        with mock.patch.object(S, "hx", fake_hx), mock.patch("hypnomix.workflow.prefs.load", return_value={}):
            found, _ = S.g_mix(self.td / "x.als", od, a)
        by = {f["id"]: f for f in found if f["id"].startswith("mix-") and f["id"][4:].isdigit()}
        self.assertEqual(sorted(by), ["mix-1", "mix-2", "mix-3"])
        self.assertEqual((by["mix-2"]["tool"], by["mix-2"]["severity"], by["mix-2"]["applies"]), ("qc", "high", "manual"))
        self.assertIn("FAILED release checks", by["mix-2"]["problem"])
        self.assertEqual({by["mix-1"]["severity"], by["mix-3"]["severity"]}, {"info"})

    def test_no_profile_gives_no_findings_and_one_line(self):
        found, notes, _ = self.run_group(dict(spectral_centroid_hz=1500.0), profile=False)
        self.assertEqual([f for f in found if f["tool"] == "profile"], [])
        self.assertEqual(len(notes), 1)
        self.assertIn("hypnomix profile build", notes[0])

    def test_no_profile_flag_skips_the_check(self):
        found, notes, _ = self.run_group(dict(spectral_centroid_hz=1500.0), no_profile=True)
        self.assertEqual([f for f in found if f["tool"] == "profile"], [])
        self.assertEqual(notes, [])

    def test_the_findings_go_through_the_review_machinery(self):
        """merge() normalises, sorts and writes REVIEW.md: a finding from a tool it has no words for must not break it."""
        found, notes, _ = self.run_group(dict(spectral_centroid_hz=1500.0))
        od = self.td / "scan"
        od.mkdir(exist_ok=True)
        (od / "scan.json").write_text(json.dumps({"set": str(self.td / "x.als"), "mode": "set", "mix": "m.wav"}), encoding="utf-8")
        (od / "mix.json").write_text(json.dumps({"group": "mix", "findings": found, "notes": notes}), encoding="utf-8")
        with mock.patch("hypnomix.workflow.prefs.load", return_value={}):
            allf, _ = S.merge(od)
        self.assertIn("mix-profile-spectral_centroid_hz", {f["id"] for f in allf})
        review = (od / "REVIEW.md").read_text(encoding="utf-8")
        self.assertIn("darker than your songs", review)
        self.assertIn("90%", review)                  # the finding's own figure (or its kind's), not the 50% default
        from hypnomix.workflow import teach
        if ("profile", None) in teach.TEXT:           # words for this kind in teach.py (a change in a file this group does not own)
            self.assertNotIn("A measured problem with a proposed fix", review)   # not the generic fix explanation
            self.assertIn("your own finished songs", review.lower())


class RealMeasure(unittest.TestCase):
    """The real `measure` on short synthetic songs: the profile builds, the comparison reads what measure wrote."""

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_end_to_end(self):
        td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, td, True)
        t = np.arange(int(SR * 4)) / SR
        rng = np.random.default_rng(1)

        def song(path, lows, highs):
            y = sum(a * np.sin(2 * np.pi * f * t) for f, a in lows) + highs * rng.standard_normal(len(t))
            sf.write(str(path), np.stack([y, y * 0.9], axis=1).astype(np.float32), SR)
            return path
        songs = [song(td / f"s{i}.wav", [(110, 0.3 - 0.01 * i), (440, 0.1)], 0.01) for i in range(3)]
        prof = PR.build([str(p) for p in songs], out=td / "profile.json")
        bright = song(td / "bright.wav", [(110, 0.05), (5000, 0.3)], 0.2)
        a = Namespace(mix=str(bright), like=None, no_profile=False)
        with mock.patch("hypnomix.core.paths.PROFILE", prof), mock.patch("hypnomix.workflow.prefs.load", return_value={}):
            found, notes = S.g_mix(td / "x.als", td / "scan", a)
        mine = {f["id"]: f for f in found if f["tool"] == "profile"}
        self.assertIn("mix-profile-spectral_centroid_hz", mine)
        self.assertIn("brighter than your songs", mine["mix-profile-spectral_centroid_hz"]["problem"])


if __name__ == "__main__":
    unittest.main()
