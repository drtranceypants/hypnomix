"""A/B inside REAPER: the A/B project (plug-in copies bypassed, track copies muted, in the same folder, sending where
the original sends) and the review panel's switching."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix import project
from hypnomix.project import rpp
from hypnomix.project import rpp_edit as E
from tests.test_rpp import RPP, SR

ROOT = Path(__file__).resolve().parents[1]


def _with_send(txt):
    """The test project with a send from Lead Vocal (track 1) into Guitar."""
    root = rpp.parse(txt)
    root.chunks("TRACK")[3].add(rpp.Line(["AUXRECV", 1, 0, 0.5, 0, 0, 0, 0, 0, 0, "-1:U", 0, -1, "''"]))
    return rpp.dumps(root)


class ABProject(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)
        (self.dir / "Audio").mkdir()
        sf.write(self.dir / "Audio" / "lead.wav", (np.arange(3 * SR) / (3 * SR)).astype(np.float32), SR, subtype="FLOAT")
        self.song = self.dir / "Song.rpp"
        self.song.write_text(_with_send(RPP))

    def tearDown(self):
        self._td.cleanup()

    def test_insert_copies_keeps_folder_and_sends(self):
        p = project.load(self.song)
        lead = p.tracks[1]
        new = rpp.parse("\n".join(lead.native.text_lines()))
        E.fresh_ids(new)
        E.insert_copies(p, [(lead, new, "Lead Vocal · B x-1")])
        out = self.dir / "Song (A-B).rpp"
        E.save(p, out)
        q = project.load(out)
        self.assertEqual([t.name for t in q.tracks], ["Vocals", "Lead Vocal", "Lead Vocal · B x-1", "Harmony", "Guitar"])
        self.assertIs(q.tracks[2].parent, q.tracks[0])           # inside the same folder
        self.assertIs(q.tracks[3].parent, q.tracks[0])           # and Harmony still closes it
        self.assertIsNone(q.tracks[4].parent)
        srcs = sorted(int(l.tokens[1]) for l in q.tracks[4].native.lines("AUXRECV"))
        self.assertEqual([q.tracks[k].name for k in srcs], ["Lead Vocal", "Lead Vocal · B x-1"])
        self.assertNotEqual(q.tracks[2].native.tokens[1], q.tracks[1].native.tokens[1])   # a new track GUID
        guids = lambda t: {l.tokens[1] for c in [t.native, *t.native.walk()] for l in c.lines() if l.key in ("GUID", "FXID", "IGUID")}
        self.assertFalse(guids(q.tracks[1]) & guids(q.tracks[2]))

    def test_build_one_plugins_and_tracks(self):
        from hypnomix.workflow import abset_project as AP
        orig, ab = project.load(self.song), project.load(self.song)
        # the "fix": a retuned JS plug-in on Lead Vocal (plug-in only) and a fade on Guitar (everything else)
        fixed = project.load(self.song)
        js = next(c for c in fixed.tracks[1].native.walk() if isinstance(c, rpp.Chunk) and c.name == "JS")
        js.children[0] = rpp.Line(["0", "250", "2000", "0"] + ["-"] * 60, indent=js.children[0].indent)
        fixed.tracks[3].native.chunk("ITEM").set("FADEIN", 1, 0.005, 0, 1, 0, 0, 0)
        copies, b_fx = [], {}
        parts, notes = AP.build_one(ab, orig, fixed, "f-1", copies, b_fx)
        self.assertEqual(notes, [])
        self.assertEqual([p["mode"] for p in parts], ["devices", "tracks"])
        items = {"f-1": dict(parts=parts)}
        E.insert_copies(ab, copies)
        AP.finalize(ab, items)
        dev, trk = parts
        self.assertEqual((dev["track"], dev["a"], dev["b"]), ("Lead Vocal", [1], [2]))
        self.assertEqual(dev["a_on"], [False])                   # the original JS was bypassed: B starts off as well
        self.assertEqual((trk["a"], trk["b"]), (["Guitar"], ["Guitar · B f-1"]))
        out = self.dir / "Song (A-B).rpp"
        E.save(ab, out)
        q = project.load(out)
        chain = q.tracks[1].native.chunk("FXCHAIN")
        byp = [l for l in chain.lines("BYPASS")]
        self.assertEqual(len(byp), 3)
        self.assertEqual(byp[2].tokens[1], "1")                  # the copy is bypassed
        fxids = [l.tokens[1] for l in chain.lines("FXID")]
        self.assertEqual(len(set(fxids)), 3)
        g, gb = q.tracks[-2], q.tracks[-1]
        self.assertEqual((g.name, gb.name), ("Guitar", "Guitar · B f-1"))
        self.assertEqual(gb.native.line("MUTESOLO").tokens[1], "1")
        self.assertTrue(gb.native.chunk("ITEM").line("FADEIN").tokens[2].startswith("0.005"))
        self.assertEqual(g.native.chunk("ITEM").line("FADEIN").tokens[2], "0")   # A is untouched

    def test_folder_with_tracks_is_not_copied(self):
        from hypnomix.workflow import abset_project as AP
        orig, ab, fixed = (project.load(self.song) for _ in range(3))
        fixed.tracks[0].native.set("VOLPAN", 0.4, 0, -1, -1, 1)   # a ride on the folder, not a plug-in change
        copies = []
        parts, notes = AP.build_one(ab, orig, fixed, "f-2", copies, {})
        self.assertEqual((parts, copies), ([], []))
        self.assertIn("folder", notes[0])


class FakeReaper:
    def __init__(self):
        self.fx, self.mute = {}, {}

    def enable(self, track, i, on):
        self.fx[(track, i)] = on

    def set_track(self, name, mute):
        self.mute[name] = mute

    def call(self, *a, **k):
        return {}


class Panel(unittest.TestCase):
    def setUp(self):
        from hypnomix.reaper import review as R
        self.R = R
        self.calls = []
        R.app = lambda path, body=None, timeout=5: self.calls.append((path, body)) or {}
        self.r = FakeReaper()
        self.p = R.Panel(self.r)
        self.spec = dict(parts=[dict(mode="devices", track="Bass", a=[0], b=[1], a_on=[True], b_on=[True]),
                                dict(mode="tracks", a=["Vox"], b=["Vox · B x"], a_on=[True], b_on=[True])])
        self.p.cur = dict(id="x", ab=self.spec)

    def tearDown(self):
        import importlib
        importlib.reload(self.R)

    def test_switch_and_back(self):
        self.p.set_ab("B")
        self.assertEqual(self.r.fx, {("Bass", 0): False, ("Bass", 1): True})
        self.assertEqual(self.r.mute, {"Vox": 1, "Vox · B x": 0})
        self.assertEqual(self.calls[-1], ("/api/ab/state", {"id": "x", "state": "B"}))
        self.p.cur = dict(id="y")                                # moving on puts the last one back to A
        self.p.follow()
        self.assertEqual(self.r.fx, {("Bass", 0): True, ("Bass", 1): False})
        self.assertEqual(self.r.mute, {"Vox": 0, "Vox · B x": 1})

    def test_muted_original_stays_muted(self):
        self.spec["parts"][1].update(a_on=[False], b_on=[False])
        self.p.set_ab("B")
        self.assertEqual(self.r.mute, {"Vox": 1, "Vox · B x": 1})

    def test_blind_records_choice(self):
        self.p.on("blind")
        x = self.p.ab["blind"]["X"]
        self.p.on("like_Y")
        self.assertEqual(self.calls[-1][0], "/api/ab/blind")
        self.assertEqual(self.calls[-1][1]["chose"], "B" if x == "A" else "A")
        self.assertIsNone(self.p.ab["blind"])


class MainMatch(unittest.TestCase):
    def test_main_has_the_match_gain(self):
        jd = ROOT / "hypnomix" / "reaper" / "jsfx"
        main, inc = (jd / "hypnomix_main.jsfx").read_text(), (jd / "hypnomix_meter.jsfx-inc").read_text()
        self.assertIn("slider9:abgain=0<-12,12,0.01>-match gain dB (set by hypnomix during A/B)", main)  # hidden slider
        self.assertIn("match_g=10^(abgain/20)", inc.replace(" ", ""))
        self.assertTrue(inc.rstrip().endswith("spl0 *= match_g; spl1 *= match_g;        // after measuring: Main reports the level before matching"))

    def test_main_keeps_the_meter_sections(self):
        """An effect's own @init/@slider/@sample REPLACE the imported ones in REAPER (measured in 7.86: Main stopped
        measuring), so Main may only add @gfx; and `match` is a built-in EEL2 function, never a variable."""
        import re
        jd = ROOT / "hypnomix" / "reaper" / "jsfx"
        for f in ("hypnomix_main.jsfx", "hypnomix_probe.jsfx"):
            txt = (jd / f).read_text()
            self.assertEqual([x for x in re.findall(r"^@(\w+)", txt, re.M) if x != "gfx"], [], f)
        for f in jd.iterdir():
            names = re.findall(r"^slider\d+:(\w+)=", f.read_text(), re.M)
            self.assertFalse({n.lower() for n in names} & {"match", "matchi", "strlen", "sprintf", "printf", "str_setlen"}, f.name)


if __name__ == "__main__":
    unittest.main()
