"""What a vocal stack is lined up to is the person's choice, never assumed: the group's average timing (--to-average)
or one lead that is never moved (--to-lead, --lead NAME). The answer comes from a flag, a preset that follows the
guide, the saved preference harmony.reference, or the question in the Align device / panel; a stack with no answer is
refused in one sentence. "Average" is the engine as it was: the same bytes."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import soundfile as sf

from hypnomix.studio import alignopts as AO
from tests.test_align import NOTES, voice
from tests.test_reaper_align import ROOT, SR, stack_project


def ns(**k):
    return SimpleNamespace(**dict(dict(to_average=False, to_lead=False, lead_name=None, preset=None), **k))


def run(mod, *argv, home=None):
    env = dict(os.environ)
    if home:
        env["HYPNOMIX_HOME"] = str(home)
    return subprocess.run([sys.executable, "-m", mod, *map(str, argv)], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", env=env)


class TheChoice(unittest.TestCase):
    def test_a_flag_a_preset_a_saved_answer_or_one_part(self):
        self.assertEqual(AO.reference(ns(to_average=True), 3, {}), ("average", "--to-average"))
        self.assertEqual(AO.reference(ns(to_lead=True), 3, {}), ("lead", "--to-lead"))
        self.assertEqual(AO.reference(ns(lead_name="Harm"), 3, {})[0], "lead")          # naming a lead chooses it
        a = ns(to_lead=True, preset="tight-pop")
        self.assertEqual(AO.reference(a, 3, {}), ("lead", "preset tight-pop"))
        self.assertTrue(a.to_lead and not a.to_average and a._reference == "lead")
        for saved in ("average", "lead"):
            a = ns()
            self.assertEqual(AO.reference(a, 3, {"harmony": {"reference": saved}})[0], saved)
            self.assertEqual((a.to_average, a.to_lead), (saved == "average", saved == "lead"))
            self.assertIn("saved preference", AO.reference_line(a))
        # a flag wins over the saved answer
        self.assertEqual(AO.reference(ns(to_lead=True), 3, {"harmony": {"reference": "average"}})[0], "lead")
        self.assertEqual(AO.reference(ns(to_average=True), 3, {"harmony": {"reference": "lead"}})[0], "average")
        # one part alone follows its guide, as it always has
        self.assertEqual(AO.reference(ns(), 1, {})[0], "lead")

    def test_a_stack_with_no_answer_is_refused_in_one_sentence(self):
        for prefs in ({}, {"harmony": {"reference": "ask"}}, {"harmony": {"reference": "whatever"}}):
            with self.assertRaises(SystemExit) as e:
                AO.reference(ns(), 2, prefs)
            msg = str(e.exception)
            self.assertEqual(msg, AO.NEEDS_CHOICE)
        for word in ("--to-average", "--to-lead", "--lead NAME", "harmony.reference"):
            self.assertIn(word, AO.NEEDS_CHOICE)
        self.assertNotIn(". ", AO.NEEDS_CHOICE)                      # one sentence
        self.assertNotIn("\n", AO.NEEDS_CHOICE)
        with self.assertRaises(SystemExit) as e:                     # both at once is not an answer either
            AO.reference(ns(to_average=True, to_lead=True), 3, {})
        self.assertIn("choose one", str(e.exception))
        with self.assertRaises(SystemExit):
            AO.reference(ns(to_average=True, lead_name="Harm"), 3, {})

    def test_a_preset_does_not_overrule_to_average(self):
        from hypnomix.studio import vocalign as V
        ap = V.build_parser()
        defaults = {k: ap.get_default(k) for k in vars(ap.parse_args(["x", "y"]))}
        a = ap.parse_args(["x", "y", "z", "--preset", "tight-pop", "--to-average"])
        AO.apply_preset(a, a.preset, defaults)
        self.assertFalse(a.to_lead)
        self.assertEqual(AO.reference(a, 2, {})[0], "average")
        a = ap.parse_args(["x", "y", "z", "--preset", "tight-pop"])
        AO.apply_preset(a, a.preset, defaults)
        self.assertEqual(AO.reference(a, 2, {})[0], "lead")

    def test_the_preference_is_a_question_with_three_answers(self):
        from hypnomix.workflow import prefs as P
        q = next(q for q in P.QUESTIONS if q["key"] == "harmony.reference")
        self.assertEqual((q["options"], q["default"]), (["ask", "average", "lead"], "ask"))
        self.assertEqual(P.parse("harmony.reference", "Average"), "average")
        with self.assertRaises(P.PrefError):
            P.parse("harmony.reference", "tightest")
        self.assertIn("harmony.reference", P.known_keys())
        self.assertEqual(AO.saved_reference({}), "")
        self.assertEqual(AO.saved_reference({"harmony": {"reference": "ask"}}), "")
        self.assertEqual(AO.saved_reference({"harmony": {"reference": "lead"}}), "lead")


class Files(unittest.TestCase):
    """`hypnomix vocalign` on three short files (8 s each)."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.d = d = Path(cls.tmp.name)
        sf.write(d / "Lead.wav", voice(NOTES), SR, subtype="PCM_24")
        sf.write(d / "Dbl.wav", voice(NOTES, delay=0.04, seed=1), SR, subtype="PCM_24")
        sf.write(d / "Harm.wav", voice([(t, du, m + 4) for t, du, m in NOTES], delay=-0.025, seed=2), SR, subtype="PCM_24")
        cls.files = [d / "Lead.wav", d / "Dbl.wav", d / "Harm.wav"]
        cls.home = d / "home"
        cls.home.mkdir()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_no_answer_writes_nothing_and_says_what_it_needs(self):
        r = run("hypnomix.studio.vocalign", *self.files, "--out", self.d / "none", home=self.home)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr.strip(), AO.NEEDS_CHOICE)
        self.assertFalse((self.d / "none").exists())

    def test_average_is_the_engine_as_it_was_byte_for_byte(self):
        from hypnomix.studio import vocalign as V
        r = run("hypnomix.studio.vocalign", *self.files, "--to-average", "--bpm", "120", "--out", self.d / "avg", home=self.home)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertIn("Lined up to: the group's average timing", r.stdout)
        # the stack engine itself, called the way the command always called it (its defaults are the command's)
        rows, _ = V.stack_align([str(f) for f in self.files], str(self.d / "direct"), 0.1, 0.3, 120.0, 60.0, 0.6, 30.0, 0.8, [], [])
        kept = [Path(x["out"]) for x in rows if x.get("out")]
        self.assertEqual(sorted(p.name for p in kept), sorted(p.name for p in (self.d / "avg").glob("*.wav")))
        self.assertTrue(kept)
        for p in kept:
            self.assertEqual(p.read_bytes(), (self.d / "avg" / p.name).read_bytes(), p.name)

    def test_lead_moves_the_parts_and_never_the_lead(self):
        out = self.d / "lead"
        r = run("hypnomix.studio.vocalign", *self.files, "--to-lead", "--engine", "wsola", "--strength", "0.7", "--max-ms", "80",
                "--out", out, home=self.home)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertIn("Lined up to: the lead, which is never moved (--to-lead)", r.stdout)
        names = sorted(p.name for p in out.glob("*.wav"))
        self.assertIn("Dbl (aligned).wav", names)
        self.assertFalse([n for n in names if n.startswith("Lead")])          # nothing is written for the lead
        from hypnomix.core import dsp
        lead, _ = dsp.load(self.files[0]); before, _ = dsp.load(self.files[1]); after, _ = dsp.load(out / "Dbl (aligned).wav")
        lb, la = AO.precise_lag(lead, before, SR, 1.1), AO.precise_lag(lead, after, SR, 1.1)
        self.assertLess(abs(la), abs(lb))                                     # closer to the lead
        self.assertGreater(abs(la), 0.002)                                    # 70%: nudged, not forced all the way

    def test_lead_names_the_lead_among_the_files(self):
        out = self.d / "named"
        r = run("hypnomix.studio.vocalign", *self.files, "--lead", "Dbl", "--engine", "wsola", "--out", out, home=self.home)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertIn("# Vocal alignment to Dbl.wav", r.stdout)
        self.assertFalse(list(out.glob("Dbl*")))                              # the named lead is never moved
        r = run("hypnomix.studio.vocalign", *self.files, "--lead", "Nobody", "--out", self.d / "x", home=self.home)
        self.assertEqual(r.returncode, 1)
        self.assertIn("is not one of the files", r.stderr)

    def test_the_saved_answer_is_used_and_ask_still_asks(self):
        home = self.d / "home2"
        home.mkdir()
        self.assertEqual(run("hypnomix.workflow.prefs", "set", "harmony.reference=lead", home=home).returncode, 0)
        r = run("hypnomix.studio.vocalign", *self.files, "--engine", "wsola", "--out", self.d / "saved", home=home)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertIn("(your saved preference harmony.reference)", r.stdout)
        self.assertIn("# Vocal alignment to Lead.wav", r.stdout)
        run("hypnomix.workflow.prefs", "set", "harmony.reference=ask", home=home)
        r = run("hypnomix.studio.vocalign", *self.files, "--out", self.d / "asked", home=home)
        self.assertEqual((r.returncode, r.stderr.strip()), (1, AO.NEEDS_CHOICE))


class InAProject(unittest.TestCase):
    """`hypnomix alignset` on a small REAPER project: refused before anything is rendered; the lead gets no markers."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.home = self.d / "home"
        self.home.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_answer_is_refused_before_rendering(self):
        path = stack_project(self.d)
        r = run("hypnomix.studio.alignset", path, "--guide", "Lead", "--parts", "Double", "Harmony", "--out", self.d / "o",
                home=self.home)
        self.assertEqual((r.returncode, r.stderr.strip()), (1, AO.NEEDS_CHOICE))
        self.assertFalse((self.d / "o").exists())
        r = run("hypnomix.studio.alignset", path, "--parts", "Double", "Harmony", "--to-average", home=self.home)
        self.assertEqual(r.returncode, 1)
        self.assertIn("--guide", r.stderr)

    def test_lead_mode_leaves_the_lead_alone_and_average_may_nudge_it(self):
        path = stack_project(self.d)
        r = run("hypnomix.studio.alignset", path, "--guide", "Lead", "--parts", "Double", "Harmony", "--to-lead", "--engine",
                "wsola", "--out", self.d / "l", "--json", self.d / "l.json", home=self.home)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        res = json.loads((self.d / "l.json").read_text(encoding="utf-8"))
        self.assertEqual((res["reference"], res["guide"]), ("lead", "Lead Vox"))
        self.assertNotIn("Lead Vox", [row["track"] for row in res["parts"]])    # no markers, no take: never moved
        self.assertIsNone(res["previews"].get("Lead Vox"))
        r = run("hypnomix.studio.alignset", path, "--guide", "Lead", "--parts", "Double", "Harmony", "--to-average",
                "--out", self.d / "a", "--json", self.d / "a.json", home=self.home)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        res = json.loads((self.d / "a.json").read_text(encoding="utf-8"))
        self.assertEqual(res["reference"], "average")
        self.assertIn("Lined up to: the group's average timing", res["markdown"])

    def test_lead_can_be_another_track_than_the_guide(self):
        path = stack_project(self.d)
        r = run("hypnomix.studio.alignset", path, "--guide", "Lead", "--parts", "Double", "Harmony", "--lead", "Harmony",
                "--engine", "wsola", "--out", self.d / "h", "--json", self.d / "h.json", home=self.home)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        res = json.loads((self.d / "h.json").read_text(encoding="utf-8"))
        self.assertEqual((res["reference"], res["guide"]), ("lead", "Harmony"))
        self.assertEqual(sorted(row["track"] for row in res["parts"]), ["Double", "Lead Vox"])


class AppDeviceAndPanel(unittest.TestCase):
    def test_the_request_carries_the_answer_or_is_asked(self):
        from hypnomix.app import align as AL
        body = dict(guide="Lead", parts=["Dbl", "Harm"])
        self.assertEqual(AO.saved_reference(), "")                     # the test run's own home has no answer saved
        with self.assertRaises(AL.NeedsReference) as e:
            AL.argv_for(body, "/x/Song.als", "/tmp/o")
        self.assertIn("Average", str(e.exception)); self.assertIn("Guide", str(e.exception))
        self.assertIn("--to-average", AL.argv_for(dict(body, reference="average"), "/x/Song.als", "/tmp/o"))
        self.assertIn("--to-lead", AL.argv_for(dict(body, reference="lead"), "/x/Song.als", "/tmp/o"))
        with self.assertRaises(ValueError):
            AL.argv_for(dict(body, reference="tightest"), "/x/Song.als", "/tmp/o")
        argv = AL.argv_for(dict(body, preset="natural-double"), "/x/Song.als", "/tmp/o")     # the preset follows the guide
        self.assertNotIn("--to-average", argv)
        with self.assertRaises(AL.NeedsReference):                     # a stack preset does not answer the question
            AL.argv_for(dict(body, preset="gentle-stack"), "/x/Song.als", "/tmp/o")
        AL.argv_for(dict(guide="Lead", parts=["Dbl"]), "/x/Song.als", "/tmp/o")              # one part: follows its guide

    def test_the_app_answers_ask_reference_and_starts_nothing(self):
        from hypnomix.app import align as AL
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "Song.rpp"
            f.write_text("<REAPER_PROJECT 0.1\n>\n", encoding="utf-8")
            code, d = AL.handle_post("/api/align/run", dict(set=str(f), guide="Lead", parts=["Dbl", "Harm"]))
        self.assertEqual((code, d.get("ask")), (400, "reference"))
        self.assertIn("Choose what the parts line up to first", d["error"])
        self.assertIn("reference", AL.state())

    def test_the_live_device_and_the_reaper_panel_have_the_control(self):
        from hypnomix.app import aligndevice as AD
        for bit in ('ref: ""', 'if (st.ref) body.reference = st.ref;', '"To: "', 'a == "ref"'):
            self.assertIn(bit, AD.JS)
        lua = (ROOT / "hypnomix" / "reaper" / "bridge.lua").read_text(encoding="utf-8")
        for bit in ('"ref_average"', '"ref_lead"', "LINE UP TO"):
            self.assertIn(bit, lua)

    def test_the_panel_asks_before_it_sends_a_stack(self):
        import importlib
        from hypnomix.reaper import align as RA
        sent, flashes = [], []
        RA.app = lambda path, body=None, timeout=5: sent.append((path, body)) or ({"reference": ""} if path.endswith("/state") else {"job": 1})
        try:
            bridge = SimpleNamespace(call=lambda name, **k: flashes.append(k.get("flash")) if name == "panel_set" and "flash" in k
                                     else dict(tracks=[], project="/p/Song.rpp", dirty=0))
            p = RA.Panel(bridge)
            p.st.update(guide="Lead Vox", parts=["Double", "Harmony"])
            p.align()
            self.assertFalse([x for x in sent if x[0] == "/api/align/run"])
            self.assertIn("Choose what the parts line up to first", flashes[-1])
            p.on("ref_lead")
            self.assertEqual(p.body()["reference"], "lead")
            p.align()
            self.assertEqual([x[1]["reference"] for x in sent if x[0] == "/api/align/run"], ["lead"])
        finally:
            importlib.reload(RA)


class TheScanCard(unittest.TestCase):
    def test_the_vocal_timing_card_asks_or_names_the_saved_answer(self):
        from unittest import mock
        from hypnomix.workflow import scan as SC
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            sf.write(d / "lead.wav", voice(NOTES), SR, subtype="PCM_16")
            sf.write(d / "dbl.wav", voice(NOTES, delay=0.09, seed=1), SR, subtype="PCM_16")
            files = {"Lead Vox": d / "lead.wav", "Double": d / "dbl.wav"}
            out, _ = SC.doubles(files, "Lead Vox")
            self.assertTrue(out)
            self.assertIn("First choose what the parts line up to", out[0]["fix"])
            self.assertEqual(out[0]["reference"], "ask")
            with mock.patch.object(AO, "saved_reference", lambda prefs=None: "average"):
                out, _ = SC.doubles(files, "Lead Vox")
            self.assertIn("Your saved answer", out[0]["fix"])
            self.assertEqual(out[0]["reference"], "average")


if __name__ == "__main__":
    unittest.main()
