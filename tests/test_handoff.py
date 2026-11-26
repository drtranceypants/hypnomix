"""`hypnomix handoff`: the by-hand list in a DAW's words, with markers that pass the DAW's own checks."""
import csv, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

from hypnomix import project
from hypnomix.project import rpp
from hypnomix.workflow import handoff as H
from tests.test_rpp import RPP
from tests.test_workflow import make_set


def hx(*args):
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True,
                       env=dict(os.environ, HYPNOMIX_HOME=tempfile.gettempdir() + "/hx-none"))
    return r.returncode, r.stdout + r.stderr


def F(i, track, where, applies="manual", fix="lower it a little", kind="level"):
    return dict(id=f"t-{i}", tool="t", kind=kind, severity="low", track=track, where=where, applies=applies,
                problem=f"problem {i}", fix=fix)


FINDINGS = [F(1, "Vocals", "9.1.00", fix="turn the vocal fader down 1 dB"),          # bar 9 at 120 bpm = 16 s
            F(2, "Vocals", "2.3.50 (5.40 s)", kind="click", fix="short fade at the edge"),
            F(3, "Bass", "bars 4, 6", kind="eq", fix="cut 250 Hz"),
            F(4, "Vocals", "whole take", kind="tune"),
            F(5, "Bass", "1:05.0", applies="set"),                                  # fix handles this one: skipped
            F(6, "Vocals", "3.1.00", applies="set", kind="timing"),                 # skipped by the person, with a note
            F(7, "Bass", "7.1.00")]                                                 # never decided


def scan_folder(d, src, mode="set", tempo=None):
    sd = d / "scan"
    sd.mkdir()
    (sd / "findings.json").write_text(json.dumps(dict(set=str(src), findings=FINDINGS)))
    (sd / "scan.json").write_text(json.dumps(dict(set=str(src), mode=mode)))
    dec = {f"t-{i}": dict(decision="approve") for i in (1, 2, 3, 4, 5)}
    dec["t-6"] = dict(decision="skip", note="I will redo this part live")
    (sd / "decisions.json").write_text(json.dumps(dec))
    return sd


class PositionTests(unittest.TestCase):
    def test_positions(self):
        self.assertEqual(H.positions("9.1.00", 120, 4), [16.0])
        self.assertEqual(H.positions("2.3.50 (5.40 s)", 120, 4), [5.4])
        self.assertEqual(H.positions("bars 4, 6", 120, 4), [6.0, 10.0])
        self.assertEqual(H.positions("1:05.0"), [65.0])
        self.assertEqual(H.positions("12 s where 2+ parts sing together"), [12.0])
        self.assertEqual(H.positions("9.1.00"), [])                      # no tempo: bar.beat can't be placed
        self.assertEqual(H.positions("whole take", 120, 4), [])

    def test_text(self):
        self.assertEqual(H.barbeat(16.0, 120, 4), "9.1")
        self.assertEqual(H.mmss(65.0), "1:05.0")


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_collects_only_what_fix_cannot_do(self):
        sd = scan_folder(self.d, self.d)
        items, _ = H.collect(sd)
        self.assertEqual(sorted(i["f"]["id"] for i in items), ["t-1", "t-2", "t-3", "t-4", "t-6"])
        items, _ = H.collect(sd, undecided=True)
        self.assertIn("t-7", [i["f"]["id"] for i in items])

    def test_live_set_gets_locators_and_passes_check(self):
        als = make_set(self.d / "Song.als")
        sd = scan_folder(self.d, als)
        code, out = hx("handoff", sd, "--daw", "live")
        self.assertEqual(code, 0, out)
        new = self.d / "Song (handoff).als"
        self.assertTrue(new.exists())
        code, out = hx("check", new, "--against", als)
        self.assertEqual(code, 0, out)
        import gzip
        import xml.etree.ElementTree as ET
        root = ET.fromstring(gzip.open(new).read())
        locs = sorted(float(l.find("Time").get("Value")) for l in root.iter("Locator"))
        self.assertEqual(len(locs), 5)                                  # 2.3.50 → 10.8 beats ... t-1 at 32 beats
        self.assertAlmostEqual(max(locs), 32.0)                         # bar 9 at 120 bpm = 32 beats
        self.assertEqual(len(list(root.iter("Locator"))), len(set(l.get("Id") for l in root.iter("Locator"))))
        md = (sd / "handoff" / "HANDOFF.md").read_text()
        self.assertLess(md.index("(finding `t-6`)"), md.index("(finding `t-2`)"))            # ordered by position
        self.assertLess(md.index("(finding `t-2`)"), md.index("(finding `t-1`)"))
        self.assertIn("EQ Eight", md)
        self.assertIn("Listen for", md)
        self.assertIn("I will redo this part live", md)                 # the person's note is kept
        self.assertTrue((sd / "handoff" / "markers.mid").read_bytes().startswith(b"MThd"))
        rows = list(csv.reader(open(sd / "handoff" / "markers.csv")))
        self.assertEqual(rows[0][:3], ["name", "seconds", "bar.beat"])
        self.assertEqual(len(rows), 6)

    def test_never_overwrites(self):
        als = make_set(self.d / "Song.als")
        sd = scan_folder(self.d, als)
        before = als.read_bytes()
        hx("handoff", sd)
        hx("handoff", sd)
        self.assertEqual(als.read_bytes(), before)
        self.assertTrue((self.d / "Song (handoff 2).als").exists())

    def test_reaper_project_gets_markers_and_round_trips(self):
        src = self.d / "Song.rpp"
        src.write_text(RPP)
        sd = scan_folder(self.d, src)
        code, out = hx("handoff", sd, "--daw", "reaper")
        self.assertEqual(code, 0, out)
        new = self.d / "Song (handoff).rpp"
        self.assertTrue(new.exists())
        root = rpp.load(new)
        marks = root.lines("MARKER")
        self.assertEqual(len(marks), 5)
        self.assertEqual(rpp.dumps(rpp.parse(rpp.dumps(root))), rpp.dumps(root))     # round trip
        a, b = project.load(src), project.load(new)
        self.assertEqual([t.name for t in a.tracks], [t.name for t in b.tracks])
        self.assertIn("ReaEQ", (sd / "handoff" / "HANDOFF.md").read_text())
        self.assertEqual(RPP, src.read_text())                                          # original untouched

    def test_folder_scan_gives_marker_files_only(self):
        sd = scan_folder(self.d, self.d, mode="folder")
        code, out = hx("handoff", sd, "--bpm", "100", "--daw", "generic")
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(p.suffix for p in (sd / "handoff").iterdir()), [".csv", ".md", ".mid"])
        self.assertEqual(list(self.d.glob("*.als")) + list(self.d.glob("*.rpp")), [])
        self.assertIn("bar 9.1", (sd / "handoff" / "HANDOFF.md").read_text())

class RecordingJobTests(unittest.TestCase):
    def test_recording_problems_get_their_own_to_do_and_listen_for_in_every_daw(self):
        not_these = ("drag its volume fader", "volume-automation", "Move the", "covering the singer")
        for tool, kind, problem, fix, expect in (
                ("recording", "clipped", "412 clipped samples", "re-record lower", "flat tops"),
                ("recording", "hot", "peaks reach -0.1 dBFS", "lower the input", "flat tops"),
                ("recording", "quiet", "very quiet", "raise the clip gain", "gaps between phrases"),
                ("dehiss", "boosted-noise", "3 clip(s) boosted +14 dB with clip gain", "hypnomix dehiss", "hiss"),
                ("recording", "noise", "steady noise floor around -50 dBFS", "dehiss", "hiss"),
                ("recording", "silent", "the file is silent", "check the export (wrong track or range?)", "silent"),
                ("recording", "dc", "DC offset 1.2% of full scale", "remove it", "cleaned copy")):
            f = dict(id="rec-1", tool=tool, kind=kind, problem=problem, fix=fix, track="Take 1", applies="manual")
            job = H.job_for(f)
            for daw in H.DAWS:
                todo = job[2][daw].format(t="Take 1")
                self.assertIn("Take 1", todo)
                self.assertIn(expect, todo + job[3])
                self.assertFalse(any(w in todo or w in job[3] for w in not_these), (kind, daw, todo))
            self.assertNotEqual(job[0], "fader")
        # Ardour's own plug-in is not named a-EQ (a parametric EQ with no high-pass)
        self.assertNotIn("a-EQ", H.job_for(dict(tool="recording", kind="dc"))[2]["ardour"])
        # the other jobs are as they were
        fader = H.job_for(dict(tool="balance", kind="level", problem="too loud", fix="turn it down"))
        self.assertEqual(fader[0], "fader")
        self.assertEqual(H.job_for(dict(tool="smooth", kind="click"))[0], "fade")
        # a recording kind it has no words for keeps the general lookup
        self.assertEqual(H.job_for(dict(tool="recording", kind="sibilance", problem="s", fix="deess"))[0], H.job_for(dict(tool="x", kind="sibilance", problem="s", fix="deess"))[0])



if __name__ == "__main__":
    unittest.main()
