"""REAPER and Ardour scans (and a few readers) brought level with the Live and folder scans: a re-scan keeps each
decision on ITS finding, two different projects never share a scan folder, a check that did not run says so in one
plain sentence, the review stays short, the tuning / timing preferences are honoured; decisions are read with the
backup fallback; plans are written whole or not at all; the voices / taste caches follow HYPNOMIX_HOME; the REAPER
align panel reads the app's port from HYPNOMIX_PORT.

Everything is synthetic, in temporary folders. Run from the repo root:  python -m unittest tests.test_scan_parity
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import soundfile as sf

from hypnomix.core import atomic as AT
from hypnomix.workflow import scan as S
from hypnomix.workflow import scan_project as SP

ROOT = Path(__file__).resolve().parent.parent
SR = 44100


# ---------------------------------------------------------------- synthetic projects
def item(pos, length, f, name, fade=0.0):
    return f'''    <ITEM
      POSITION {pos}
      LENGTH {length}
      LOOP 0
      FADEIN 1 {fade} 0 1 0 0 0
      FADEOUT 1 {fade} 0 1 0 0 0
      MUTE 0 0
      NAME "{name}"
      VOLPAN 1 0 1 -1
      SOFFS 0
      PLAYRATE 1 1 0 -1 0 0.0025
      <SOURCE WAVE
        FILE "{f}"
      >
    >
'''


def track(name, items, guid, extra=""):
    return f'''  <TRACK {{{guid}}}
    NAME "{name}"
    VOLPAN 1 0 -1 -1 1
    MUTESOLO 0 0 0
    IPHASE 0
    ISBUS 0 0
    FX 1
{extra}{items}  >
'''


def make_rpp(folder, items, name="Song", level=0.3):
    """A REAPER project with one Guitar track. items: [(position, length, fade, file name)]."""
    folder = Path(folder)
    (folder / "Audio").mkdir(parents=True, exist_ok=True)
    sf.write(folder / "Audio" / "gtr.wav", np.full(4 * SR, level, np.float32), SR, subtype="FLOAT")
    body = "".join(item(pos, ln, f"Audio/{fn}", f"take {k}", fade) for k, (pos, ln, fade, fn) in enumerate(items, 1))
    txt = ('<REAPER_PROJECT 0.1 "7.27/macOS-arm64" 1764000000\n  TEMPO 120 4 4\n  SAMPLERATE 44100 0 0\n'
           + track("Guitar", body, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa") + ">\n")
    p = folder / f"{name}.rpp"
    p.write_text(txt)
    return p


TWO_ITEMS = [(0.5, 1.0, 0.0, "gtr.wav"), (2.0, 1.0, 0.0, "gtr.wav")]


def make_ardour(folder, name="Song"):
    from tests.test_ardour import SESSION, SR as ASR
    folder = Path(folder) / name
    af = folder / "interchange" / name / "audiofiles"
    af.mkdir(parents=True)
    sf.write(af / "lead.wav", np.linspace(0, 1, 3 * ASR, endpoint=False), ASR, subtype="FLOAT")
    sf.write(af / "comp.wav", np.full(3 * ASR, 0.1), ASR, subtype="FLOAT")
    sf.write(af / "gtr-L.wav", np.full(ASR, 0.2), ASR, subtype="FLOAT")
    sf.write(af / "gtr-R.wav", np.full(ASR, 0.6), ASR, subtype="FLOAT")
    (folder / f"{name}.ardour").write_text(SESSION.replace('name="Song"', f'name="{name}"', 1))
    return folder


def scan(*args):
    """`hypnomix scan ...` in this process (quick groups only). Returns (printed text, exit text or None)."""
    from hypnomix.core import paths
    from hypnomix.project import model
    from hypnomix.workflow import prefs
    model._SRC.clear()                                  # a scan is a fresh process: no audio kept from an earlier one
    out, old_argv, old_out = io.StringIO(), sys.argv, paths.OUT
    old_env = os.environ.get("HYPNOMIX_OUT")
    sys.argv = ["scan", *map(str, args)]
    bail = None
    try:
        with mock.patch.object(prefs, "PREFS", Path(tempfile.gettempdir()) / "hypnomix-no-such-prefs.json"), \
                contextlib.redirect_stdout(out):
            try:
                S.main()
            except SystemExit as e:
                bail = str(e.code)
    finally:
        sys.argv, paths.OUT = old_argv, old_out
        if old_env is None:
            os.environ.pop("HYPNOMIX_OUT", None)
        else:
            os.environ["HYPNOMIX_OUT"] = old_env
    return out.getvalue(), bail


QUICK = ["--only", "clips", "--only", "files", "--only", "intent", "--only", "effects"]


def findings(od):
    return json.loads((Path(od) / "findings.json").read_text())["findings"]


def where_of(od, kind):
    return {f["where"]: f["id"] for f in findings(od) if f.get("kind") == kind}


class Isolated(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()


# ---------------------------------------------------------------- 1. a re-scan, two same-named projects, plain notes
class ReaperRescan(Isolated):
    def test_a_rescan_after_the_project_changed_keeps_each_decision_on_its_own_finding(self):
        proj = make_rpp(self.dir / "p", TWO_ITEMS)
        od = self.dir / "out"
        scan(proj, "--out", od, *QUICK)
        before = where_of(od, "click")
        self.assertEqual(len(before), 4)                                  # a start and an end on each of two items
        ids = sorted(before.values(), key=lambda i: int(i.split("-")[1]))
        # approve the first item's edges, skip the second item's start
        first = [w for w in before if "(0.50 s)" in w or "(1.50 s)" in w]
        second_start = next(w for w in before if "(2.00 s)" in w)
        dec = {before[w]: {"decision": "approve"} for w in first}
        dec[before[second_start]] = {"decision": "skip"}
        AT.write_json(od / "decisions.json", dec)
        self.assertEqual(len(first), 2)
        # the person gave the first item fades in REAPER and saved: its findings are gone, every id shifts
        make_rpp(self.dir / "p", [(0.5, 1.0, 0.01, "gtr.wav"), (2.0, 1.0, 0.0, "gtr.wav")])
        text, _ = scan(proj, "--out", od, *QUICK)
        after = where_of(od, "click")
        self.assertEqual(len(after), 2)
        now = AT.load_json(od / "decisions.json", {})
        self.assertEqual(now, {after[second_start]: {"decision": "skip"}})  # the skip followed ITS finding
        self.assertNotIn(after[next(w for w in after if w != second_start)], now)   # nothing landed on the other one
        orphans = json.loads((od / "decisions-orphaned.json").read_text())
        self.assertEqual(sorted(v["decision"]["decision"] for v in orphans.values()), ["approve", "approve"])
        self.assertIn("2 earlier decisions no longer match a finding and were set aside", text)
        self.assertTrue(any("set aside" in n for n in json.loads((od / "findings.json").read_text())["notes"]))

    def test_the_renders_are_not_reused_after_the_project_changed(self):
        proj = make_rpp(self.dir / "p", TWO_ITEMS)
        od = self.dir / "out"
        scan(proj, "--out", od, *QUICK)
        wav = od / "raw" / "renders" / "Guitar.wav"
        y1, _ = sf.read(str(wav))
        self.assertAlmostEqual(float(y1[int(0.5 * SR) + 2]), 0.3, places=3)
        stamp1 = (od / "raw" / "renders" / ".stamp").read_text()
        make_rpp(self.dir / "p", [(0.5, 1.0, 0.2, "gtr.wav"), (2.0, 1.0, 0.0, "gtr.wav")])   # a fade-in on the first item
        scan(proj, "--out", od, *QUICK)
        y2, _ = sf.read(str(wav))
        self.assertLess(float(y2[int(0.5 * SR) + 2]), 0.01)               # the new render, not the old one
        stamp2 = (od / "raw" / "renders" / ".stamp").read_text()
        self.assertNotEqual(stamp1, stamp2)
        made = wav.stat().st_mtime_ns
        scan(proj, "--out", od, *QUICK)                                   # nothing changed: the renders are kept
        self.assertEqual(stamp2, (od / "raw" / "renders" / ".stamp").read_text())
        self.assertEqual(made, wav.stat().st_mtime_ns)

    def test_the_audio_file_changing_also_counts(self):
        proj = make_rpp(self.dir / "p", TWO_ITEMS)
        od = self.dir / "out"
        scan(proj, "--out", od, *QUICK)
        s1 = (od / "raw" / "renders" / ".stamp").read_text()
        make_rpp(self.dir / "p", TWO_ITEMS, level=0.5)                     # re-recorded: same project file, new audio
        scan(proj, "--out", od, *QUICK)
        self.assertNotEqual(s1, (od / "raw" / "renders" / ".stamp").read_text())
        y, _ = sf.read(str(od / "raw" / "renders" / "Guitar.wav"))
        self.assertAlmostEqual(float(y[int(0.5 * SR) + 2]), 0.5, places=3)

    def test_two_bypassed_plugins_on_one_track_are_two_findings_a_rescan_can_tell_apart(self):
        from hypnomix import project as PJ
        proj = make_rpp(self.dir / "p", TWO_ITEMS)
        text = proj.read_text().replace("    FX 1\n", '''    FX 1
    <FXCHAIN
      WNDRECT 0 0 0 0
      BYPASS 1 0 0
      <JS "loser/3BandEQ" ""
        0 200 2000
      >
      FXID {44444444-4444-4444-4444-444444444444}
      BYPASS 1 0 0
      <JS "loser/Saturation" ""
        0 1
      >
      FXID {55555555-5555-5555-5555-555555555555}
    >
''', 1)
        proj.write_text(text)
        p = PJ.load(proj)
        out, _ = SP.g_effects(p, None, self.dir, SimpleNamespace())
        byp = [f for f in out if f["kind"] == "bypassed"]
        self.assertEqual(len(byp), 2)
        self.assertEqual(len({S._identity(f) for f in byp}), 2)           # told apart by the plug-in's name
        self.assertTrue(all(f["device"] for f in byp))

    def test_intent_questions_on_one_track_have_their_own_identity(self):
        from hypnomix import project as PJ
        proj = make_rpp(self.dir / "p", TWO_ITEMS)
        proj.write_text(proj.read_text().replace("VOLPAN 1 0 -1 -1 1", "VOLPAN 1 1 -1 -1 1", 1)
                        .replace("IPHASE 0", "IPHASE 1", 1))                      # panned hard, polarity flipped
        out, _ = SP.g_intent(PJ.load(proj), None, self.dir, SimpleNamespace())
        mine = [f for f in out if f["track"] == "Guitar" and not f["where"]]
        self.assertGreaterEqual(len(mine), 2)
        self.assertEqual(len({S._identity(f) for f in mine}), len(mine))


    def test_a_second_scan_starting_while_the_first_is_rendering_keeps_its_renders(self):
        from hypnomix import project as PJ
        proj = make_rpp(self.dir / "p", TWO_ITEMS)
        od = self.dir / "out"
        p = PJ.load(proj)
        a = SP.Renders(p, od)
        a.dir.mkdir(parents=True)
        a._fresh(SP.signature(p))                                          # scan A has claimed the folder, and rendered one file
        done = a.dir / "Guitar.wav"
        sf.write(str(done), np.full(SR, 0.7, np.float32), SR, subtype="FLOAT")
        mark = done.stat().st_mtime_ns
        b = SP.Renders(p, od).build()                                      # scan B starts before A has finished
        self.assertEqual(done.stat().st_mtime_ns, mark)                    # A's finished render was not deleted or redone
        self.assertEqual(b.files["Guitar"], done)

    def test_renders_with_no_stamp_are_not_trusted_and_a_part_file_is_never_left_behind(self):
        from hypnomix import project as PJ
        proj = make_rpp(self.dir / "p", TWO_ITEMS)
        od = self.dir / "out"
        old = od / "raw" / "renders" / "Guitar.wav"
        old.parent.mkdir(parents=True)
        sf.write(str(old), np.full(SR, 0.9, np.float32), SR, subtype="FLOAT")      # an older version's render, no stamp
        SP.Renders(PJ.load(proj), od).build()
        y, _ = sf.read(str(old))
        self.assertAlmostEqual(float(y[int(0.5 * SR) + 2]), 0.3, places=3)          # re-made from the project
        self.assertEqual([x.name for x in old.parent.iterdir() if x.name.endswith(".part")], [])

    def test_an_old_error_file_goes_when_the_check_runs_clean_again(self):
        proj = make_rpp(self.dir / "p", TWO_ITEMS)
        od = self.dir / "out"
        with mock.patch.object(SP, "g_intent", side_effect=RuntimeError("boom")):
            scan(proj, "--out", od, *QUICK)
        self.assertTrue((od / "raw" / "intent-error.txt").exists())
        text, _ = scan(proj, "--out", od, *QUICK)
        self.assertFalse((od / "raw" / "intent-error.txt").exists())
        self.assertFalse(any("failed" in n for n in json.loads((od / "intent.json").read_text())["notes"]))
        for stale in ("edges-error.txt", "key-error.txt", "tune-Guitar-error.txt", "sidechain-error.txt"):
            (od / "raw" / stale).write_text("old")
        scan(proj, "--out", od, *QUICK)                                    # clips and effects ran again
        self.assertFalse((od / "raw" / "edges-error.txt").exists())
        self.assertFalse((od / "raw" / "sidechain-error.txt").exists())
        self.assertTrue((od / "raw" / "key-error.txt").exists())           # vocals did not run: its note still stands


class SameNameProjects(Isolated):
    def test_two_different_reaper_projects_with_one_name_do_not_share_a_folder(self):
        a = make_rpp(self.dir / "one", TWO_ITEMS)
        b = make_rpp(self.dir / "two", [(1.0, 1.0, 0.0, "gtr.wav")])
        base = self.dir / "out" / "Song"
        scan(a, "--out", base, *QUICK)
        AT.write_json(base / "decisions.json", {"clips-1": {"decision": "approve"}})
        text, _ = scan(b, "--out", base, *QUICK)
        self.assertIn("not mixing the two songs", text)
        second = self.dir / "out" / "Song (2)"
        self.assertTrue((second / "scan.json").exists())
        self.assertEqual(AT.load_json(base / "scan.json")["set"], str(a.resolve()))
        self.assertEqual(AT.load_json(second / "scan.json")["set"], str(b.resolve()))
        self.assertEqual(AT.load_json(base / "decisions.json"), {"clips-1": {"decision": "approve"}})   # untouched
        self.assertFalse((second / "decisions.json").exists())            # nothing inherited
        scan(b, "--out", base, *QUICK)                                    # and the same project finds its folder again
        self.assertFalse((self.dir / "out" / "Song (3)").exists())

    def test_a_reaper_project_and_an_ardour_session_with_one_name_do_not_share_a_folder(self):
        a = make_rpp(self.dir / "one", TWO_ITEMS)
        s = make_ardour(self.dir / "two")
        base = self.dir / "out" / "Song"
        scan(a, "--out", base, *QUICK)
        text, _ = scan(s, "--out", base, "--only", "files", "--only", "intent", "--only", "effects")
        self.assertIn("not mixing the two songs", text)
        second = self.dir / "out" / "Song (2)"
        self.assertEqual(AT.load_json(second / "scan.json")["mode"], "ardour")
        self.assertEqual(AT.load_json(base / "scan.json")["mode"], "reaper")

    def test_two_ardour_sessions_with_one_name_do_not_share_a_folder(self):
        a = make_ardour(self.dir / "one")
        b = make_ardour(self.dir / "two")
        base = self.dir / "out" / "Song"
        scan(a, "--out", base, "--only", "files", "--only", "intent")
        text, _ = scan(b, "--out", base, "--only", "files", "--only", "intent")
        self.assertIn("not mixing the two songs", text)
        self.assertTrue((self.dir / "out" / "Song (2)" / "scan.json").exists())

    def test_an_ardour_rescan_keeps_each_decision_on_its_finding(self):
        s = make_ardour(self.dir / "one")
        od = self.dir / "out"
        scan(s, "--out", od, "--only", "intent", "--only", "effects")
        by = lambda: {S._identity(f)[3]: f["id"] for f in findings(od) if f["tool"] == "intent"}
        f1 = by()
        for key in ("automation: Pan", "automation: Volume", "muted"):
            self.assertIn(key, f1)
        AT.write_json(od / "decisions.json", {f1["automation: Volume"]: {"decision": "approve"},
                                              f1["automation: Pan"]: {"decision": "skip"},
                                              f1["muted"]: {"decision": "approve"}})
        # the person removed the pan automation in Ardour and saved: that finding is gone and every later id shifts
        sess = s / "Song.ardour"
        txt = sess.read_text()
        a, b = txt.index("      <Pannable>"), txt.index("</Pannable>") + len("</Pannable>")
        sess.write_text(txt[:a] + txt[b:])
        text, _ = scan(s, "--out", od, "--only", "intent", "--only", "effects")
        f2 = by()
        self.assertNotIn("automation: Pan", f2)
        self.assertNotEqual(f2["automation: Volume"], f1["automation: Volume"])        # the ids really did shift
        self.assertNotEqual(f2["muted"], f1["muted"])
        now = AT.load_json(od / "decisions.json")
        self.assertEqual(now, {f2["automation: Volume"]: {"decision": "approve"}, f2["muted"]: {"decision": "approve"}})
        orphans = json.loads((od / "decisions-orphaned.json").read_text())
        self.assertEqual([v["decision"]["decision"] for v in orphans.values()], ["skip"])
        self.assertIn("1 earlier decision no longer matches a finding and was set aside", text)


class PlainNotes(Isolated):
    def test_a_check_that_fails_is_one_plain_sentence_and_the_traceback_is_saved(self):
        proj = make_rpp(self.dir / "p", TWO_ITEMS)
        od = self.dir / "out"
        boom = RuntimeError("could not read '/private/tmp/some/deep/folder/take 3.wav' as audio")
        with mock.patch.object(SP, "g_intent", side_effect=boom):
            text, _ = scan(proj, "--out", od, *QUICK)
        notes = json.loads((od / "intent.json").read_text())["notes"]
        self.assertEqual(len(notes), 1)
        n = notes[0]
        self.assertTrue(n.startswith("intent: failed (could not read 'take 3.wav' as audio)"), n)
        self.assertIn("does not mean it is clean", n)
        self.assertIn("raw/intent-error.txt", n)
        for bad in ("Traceback", "File \"", "line ", "RuntimeError", "/private"):
            self.assertNotIn(bad, n)
        self.assertNotIn("\n", n)
        self.assertIn("Traceback", (od / "raw" / "intent-error.txt").read_text())
        self.assertTrue((od / "files.json").exists())                      # the other groups still ran
        review = (od / "REVIEW.md").read_text()
        self.assertIn("## Checks that did NOT run", review)
        self.assertIn(n, review)
        self.assertIn("did NOT run", text)

    def test_the_parts_of_a_group_fail_the_same_way(self):
        from hypnomix import project as PJ
        proj = make_rpp(self.dir / "p", TWO_ITEMS)
        p = PJ.load(proj)
        od = self.dir
        boom = ValueError("max() arg is an empty sequence")
        with mock.patch("hypnomix.workflow.edges_project.scan", side_effect=boom):
            _, notes = SP.g_clips(p, SP.Renders(p, od), od, SimpleNamespace(), vocals=["Guitar"])
        edge = [n for n in notes if n.startswith("edges:")]
        self.assertEqual(len(edge), 1)
        self.assertIn("edges: failed (no notes or values were found to measure)", edge[0])
        self.assertIn("raw/edges-error.txt", edge[0])
        self.assertTrue((od / "raw" / "edges-error.txt").exists())
        with mock.patch("hypnomix.workflow.sidechain_project.analyse", side_effect=boom):
            _, notes = SP.g_effects(p, None, od, SimpleNamespace())
        self.assertTrue(any(n.startswith("sidechain: failed (no notes or values") and "raw/sidechain-error.txt" in n
                            for n in notes))

    def test_a_tuning_check_that_failed_says_so_plainly(self):
        from hypnomix import project as PJ
        p = PJ.load(make_rpp(self.dir / "p", TWO_ITEMS))
        od = self.dir
        (od / "raw").mkdir()
        wav = od / "raw" / "Lead.wav"
        sf.write(str(wav), np.zeros(SR, np.float32), SR)
        R = SimpleNamespace(files={"Lead": wav}, mix=lambda: None, dir=od / "raw")
        trace = ("Traceback (most recent call last):\n  File \"/x/tune.py\", line 9, in go\nValueError: no sung notes "
                 "found (is this a monophonic vocal?)\n")
        a = SimpleNamespace(vocal_track=["Lead"], lead_track="Lead", ref=None, key="C major", backing=None, jobs=1)
        with mock.patch.object(S, "hx", return_value=(1, trace)):
            f, notes = SP.g_vocals(p, R, od, a, {"Lead": "lead_vocal"})
        self.assertEqual(f, [])
        n = next(x for x in notes if x.startswith("tuning check on Lead"))
        self.assertIn("failed (no sung notes found (is this a monophonic vocal?))", n)
        self.assertIn("raw/tune-Lead-error.txt", n)
        self.assertNotIn("Traceback", n)
        self.assertIn("Traceback", (od / "raw" / "tune-Lead-error.txt").read_text())


class Preferences(Isolated):
    def _vocals(self, wants):
        from hypnomix import project as PJ
        p = PJ.load(make_rpp(self.dir / "p", TWO_ITEMS))
        od = self.dir
        (od / "raw").mkdir(exist_ok=True)
        wav = od / "raw" / "Lead.wav"
        sf.write(str(wav), np.zeros(SR, np.float32), SR)
        R = SimpleNamespace(files={"Lead": wav}, mix=lambda: None, dir=od / "raw")
        a = SimpleNamespace(vocal_track=["Lead"], lead_track="Lead", ref=None, key="C major", backing=None, jobs=1)

        def fake(*args):
            if args[0] == "tune":
                Path(args[args.index("--json") + 1]).write_text(json.dumps(
                    {"findings": [dict(id="tune-1", tool="tune", kind="pitch", severity="low", where="1.1.01", problem="p",
                                       fix="f", applies="audio")], "key": "C major", "tuning_cents": 0,
                     "flagged": [1, 2, 3]}))
            return 0, ""
        with mock.patch.object(S, "hx", side_effect=fake), mock.patch.object(S, "pref_wants", side_effect=wants):
            return SP.g_vocals(p, R, od, a, {"Lead": "lead_vocal"})

    def test_tuning_off_lists_nothing_and_says_how_many_were_left_out(self):
        f, notes = self._vocals(lambda kind: "off" if kind == "tune" else "")
        self.assertEqual([x for x in f if x.get("tool") == "tune"], [])
        self.assertTrue(any("tuning proposals are off in your preferences" in n and "3 note(s)" in n for n in notes))

    def test_tuning_on_lists_the_finding(self):
        f, notes = self._vocals(lambda kind: "")
        self.assertEqual([x["id"] for x in f if x.get("tool") == "tune"], ["tune-1"])
        self.assertFalse(any("proposals are off" in n for n in notes))

    def test_timing_off_proposes_no_nudges(self):
        from hypnomix import project as PJ
        p = PJ.load(make_rpp(self.dir / "p", TWO_ITEMS))
        fs = [dict(id="timing-1", tool="timing", kind="late", applies="set", edit={}),
              dict(id="x-1", tool="other", kind="k", applies="manual")]
        with mock.patch("hypnomix.workflow.timing_project.analyse", return_value=({}, [], {"looseness": 0.01})), \
                mock.patch("hypnomix.workflow.timing_project.findings", return_value=[dict(f) for f in fs]), \
                mock.patch.object(S, "pref_wants", side_effect=lambda kind: "off" if kind == "timing" else ""):
            out, notes = SP.g_timing(p, None, self.dir, SimpleNamespace(timing_track=["Guitar"]), {"Guitar": "guitar"})
            self.assertEqual([f["id"] for f in out], ["x-1"])
            self.assertTrue(any("timing proposals are off in your preferences" in n for n in notes))
        with mock.patch("hypnomix.workflow.timing_project.analyse", return_value=({}, [], {"looseness": 0.01})), \
                mock.patch("hypnomix.workflow.timing_project.findings", return_value=[dict(f) for f in fs]), \
                mock.patch.object(S, "pref_wants", return_value=""):
            out, notes = SP.g_timing(p, None, self.dir, SimpleNamespace(timing_track=["Guitar"]), {"Guitar": "guitar"})
            self.assertEqual([f["id"] for f in out], ["timing-1", "x-1"])

    def test_the_helper_asks_prefs_wants(self):
        from hypnomix.workflow import prefs as P
        with mock.patch.object(P, "wants", return_value="Off") as w:
            self.assertEqual(S.pref_wants("tune"), "off")
            w.assert_called_with("tune")


class CompactReview(Isolated):
    def test_the_relink_how_to_is_written_once_not_under_every_missing_file(self):
        items = [(0.5 * k, 0.4, 0.01, f"gone{k}.wav") for k in range(1, 7)]
        proj = make_rpp(self.dir / "p", items)
        od = self.dir / "out"
        scan(proj, "--out", od, "--only", "files")
        fs = [f for f in findings(od) if f["kind"] == "missing-audio"]
        self.assertEqual(len(fs), 6)
        review = (od / "REVIEW.md").read_text()
        self.assertEqual(review.count("offers to search for missing media"), 1)
        self.assertTrue(all(len(f["fix"]) < 80 for f in fs))
        self.assertEqual(review.count("**files · missing-audio** (6 items)"), 1)     # the kind is explained once
        self.assertIn("## Why these fixes", review)

    def test_click_and_cut_texts_stay_short(self):
        proj = make_rpp(self.dir / "p", TWO_ITEMS)
        od = self.dir / "out"
        scan(proj, "--out", od, "--only", "clips")
        for f in findings(od):
            self.assertLess(len(f["fix"]), 130, f["fix"])


# ---------------------------------------------------------------- 2. decisions are read with the backup fallback
def cut_off(path):
    text = Path(path).read_text()
    Path(path).write_text(text[: len(text) // 2])


class AtomicReaders(Isolated):
    def scan_folder(self):
        sd = self.dir / "scan"
        sd.mkdir()
        fs = [dict(id="smooth-1", tool="smooth", kind="click", severity="low", track="Vox", where="1.1.00",
                   problem="p", fix="f", applies="manual"),
              dict(id="timing-1", tool="timing", kind="late", severity="low", track="Gtr", where="2.1.00",
                   problem="p", fix="f", applies="manual")]
        AT.write_json(sd / "findings.json", {"set": "x.als", "notes": [], "findings": fs})
        AT.write_json(sd / "scan.json", {"set": "x.als", "mode": "set"})
        return sd

    def test_prefs_learn_survives_a_cut_off_decisions_file(self):
        from hypnomix.workflow import prefs as P
        sd = self.scan_folder()
        AT.write_json(sd / "decisions.json", {"smooth-1": {"decision": "approve"}})
        AT.write_json(sd / "decisions.json", {"smooth-1": {"decision": "approve"}, "timing-1": {"decision": "skip"}})
        cut_off(sd / "decisions.json")                                      # a crash in the middle of a write
        path = self.dir / "prefs.json"
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            P.learn(sd, path)
        learned = json.loads(path.read_text())["learned"]
        self.assertEqual(learned["smooth/click/low"], {"approve": 1})       # read from decisions.json.bak
        self.assertIn("using the previous copy", err.getvalue())

    def test_prefs_learn_says_so_when_there_is_no_usable_copy(self):
        from hypnomix.workflow import prefs as P
        sd = self.scan_folder()
        (sd / "decisions.json").write_text('{"smooth-1": {"decis')
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            P.learn(sd, self.dir / "prefs.json")
        self.assertIn("could not be read", str(cm.exception))
        self.assertTrue((sd / "decisions.json.corrupt").exists())

    def test_prefs_learn_reads_a_cut_off_findings_file_from_its_backup_too(self):
        from hypnomix.workflow import prefs as P
        sd = self.scan_folder()
        AT.write_json(sd / "decisions.json", {"smooth-1": {"decision": "approve"}})
        AT.write_json(sd / "findings.json", AT.load_json(sd / "findings.json"))      # now there is a .bak
        cut_off(sd / "findings.json")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            P.learn(sd, self.dir / "prefs.json")
        self.assertEqual(json.loads((self.dir / "prefs.json").read_text())["learned"]["smooth/click/low"], {"approve": 1})

    def test_ab_reads_a_cut_off_findings_file_from_its_backup(self):
        from hypnomix.workflow import ab
        sd = self.scan_folder()
        AT.write_json(sd / "findings.json", AT.load_json(sd / "findings.json"))
        cut_off(sd / "findings.json")
        out, old = io.StringIO(), sys.argv
        sys.argv = ["ab", str(sd)]
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                ab.main()
        finally:
            sys.argv = old
        self.assertIn("before/after pair(s)", out.getvalue())

    def test_ab_with_no_usable_findings_says_what_to_do(self):
        from hypnomix.workflow import ab
        sd = self.dir / "scan"
        sd.mkdir()
        (sd / "findings.json").write_text('{"set": "x.al')
        old = sys.argv
        sys.argv = ["ab", str(sd)]
        try:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                ab.main()
        finally:
            sys.argv = old
        self.assertIn("scan again", str(cm.exception))

    def test_history_reads_a_cut_off_scan_file_from_its_backup(self):
        from hypnomix.workflow import history as H
        from tests.test_workflow import make_set
        sd = self.dir / "scan"
        sd.mkdir()
        orig = make_set(self.dir / "Song.als")
        AT.write_json(sd / "scan.json", {"set": str(orig), "mode": "set"})
        AT.write_json(sd / "scan.json", {"set": str(orig), "mode": "set"})
        cut_off(sd / "scan.json")
        (sd / "history").mkdir()
        (sd / "history" / "v1-input.als").write_bytes(orig.read_bytes())
        h = {"versions": [dict(n=1, kind="fix", input=str(orig), output=None, approved=[], input_snapshot="v1-input.als")]}
        with contextlib.redirect_stderr(io.StringIO()):
            dest, _ = H.undo(sd, h, 1)
        self.assertEqual(dest.parent, orig.parent)                           # found the song through the .bak
        self.assertIn("back to v1 input", dest.name)


class MoreAtomicReaders(Isolated):
    def test_history_survives_a_cut_off_log_and_writes_it_whole(self):
        from hypnomix.workflow import history as H
        sd = self.dir / "scan"
        sd.mkdir()
        H.save(sd, {"versions": [dict(n=1, kind="fix")]})
        H.save(sd, {"versions": [dict(n=1, kind="fix"), dict(n=2, kind="fix")]})
        self.assertEqual([x.name for x in (sd / "history").glob(".*.tmp")], [])
        self.assertTrue((sd / "history" / "history.json.bak").exists())
        cut_off(sd / "history" / "history.json")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            h = H.load(sd)
        self.assertEqual([v["n"] for v in h["versions"]], [1])               # the previous copy, no traceback
        self.assertIn("using the previous copy", err.getvalue())
        (sd / "history" / "history.json.bak").unlink()
        cut_off(sd / "history" / "history.json")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(H.load(sd), {"versions": []})                   # no usable copy: starts a new log, still runs
        (sd / "history" / "history.json").write_text("[1, 2]")                # parses, but is not a log
        self.assertEqual(H.load(sd), {"versions": []})

    def test_the_history_command_does_not_crash_on_a_cut_off_log(self):
        sd = self.dir / "scan"
        (sd / "history").mkdir(parents=True)
        (sd / "history" / "history.json").write_text('{"vers')
        AT.write_json(sd / "scan.json", {"set": "x.als", "mode": "set"})
        env = dict(os.environ, HOME=str(self.dir / "h"), HYPNOMIX_HOME=str(self.dir / "hx"), PYTHONPATH=str(ROOT))
        r = subprocess.run([sys.executable, "-m", "hypnomix.cli", "history", str(sd)], capture_output=True, text=True,
                           env=env, cwd=str(self.dir))
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])

    def test_ab_reads_its_own_files_with_the_backup_fallback(self):
        from hypnomix.workflow import ab
        sd = self.dir / "scan"
        (sd / "raw").mkdir(parents=True)
        AT.write_json(sd / "raw" / "timing.json", {"tracks": ["Gtr"]})
        AT.write_json(sd / "raw" / "timing.json", {"tracks": ["Gtr"]})
        cut_off(sd / "raw" / "timing.json")
        with contextlib.redirect_stderr(io.StringIO()):
            args = ab.timing_args(sd, "x.als", "y.als", ["timing-1"], False)
        self.assertIn("Gtr", args)
        (sd / "raw" / "timing.json.bak").unlink()
        cut_off(sd / "raw" / "timing.json")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIn("timing", ab.timing_args(sd, "x.als", "y.als", ["timing-1"], False))   # no crash without a copy

    def test_the_preferences_file_survives_a_cut_off_and_is_saved_whole(self):
        from hypnomix.workflow import prefs as P
        path = self.dir / "preferences.json"
        P.save({"taste": {"tuning": "off"}}, path)
        P.save({"taste": {"tuning": "gentle"}}, path)
        self.assertEqual([x.name for x in self.dir.glob(".*.tmp")], [])
        cut_off(path)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(P.load(path)["taste"]["tuning"], "off")           # the previous copy
        path.with_name(path.name + ".bak").unlink()
        cut_off(path)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(P.load(path), {})

    def test_prefs_learn_tells_an_empty_file_from_a_broken_one(self):
        from hypnomix.workflow import prefs as P
        sd = self.dir / "scan"
        sd.mkdir()
        (sd / "decisions.json").write_text("{}")                              # what a re-scan that set everything aside leaves
        with self.assertRaises(SystemExit) as cm:
            P.learn(sd, self.dir / "prefs.json")
        self.assertIn("no decisions recorded yet", str(cm.exception))
        self.assertNotIn("corrupt", str(cm.exception))
        (sd / "decisions.json").write_text('{"a": {"decis')
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            P.learn(sd, self.dir / "prefs.json")
        self.assertIn("decisions.json.corrupt", str(cm.exception))
        self.assertTrue((sd / "decisions.json.corrupt").exists())             # the file the message names is really there


class PlanFiles(Isolated):
    def test_plan_writes_its_group_file_and_scan_json_whole_with_a_backup(self):
        from hypnomix.workflow import plan as PL
        from hypnomix.workflow import prefs
        src = self.dir / "songs"
        src.mkdir()
        sf.write(str(src / "a.wav"), np.zeros(SR, np.float32), SR)
        od = self.dir / "out"
        with mock.patch.object(prefs, "PREFS", self.dir / "none.json"), contextlib.redirect_stdout(io.StringIO()):
            PL.write(od, "balance", src, [dict(kind="level", track="a.wav", problem="p", fix="f")], ["n"])
            first = json.loads((od / "balance.json").read_text())
            PL.write(od, "balance", src, [dict(kind="level", track="a.wav", problem="q", fix="f")], ["n"])
        self.assertEqual(first["findings"][0]["id"], "balance-1")
        self.assertEqual(json.loads((od / "balance.json.bak").read_text())["findings"][0]["problem"], "p")
        self.assertEqual(json.loads((od / "scan.json.bak").read_text())["set"], str(src.resolve()))
        self.assertEqual([p.name for p in od.glob(".*.tmp")], [])            # no half-written leftovers
        cut_off(od / "scan.json")
        with mock.patch.object(prefs, "PREFS", self.dir / "none.json"), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            PL.write(od, "balance", src, [dict(kind="level", track="a.wav", problem="r", fix="f")], ["n"])
        self.assertEqual(json.loads((od / "scan.json").read_text())["set"], str(src.resolve()))   # not lost to the cut


# ---------------------------------------------------------------- 3. the caches live under the hypnomix home
class CachesFollowTheHome(Isolated):
    def run_py(self, code, home, fake_home):
        env = dict(os.environ, HOME=str(fake_home), HYPNOMIX_HOME=str(home), PYTHONPATH=str(ROOT))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=str(self.dir))
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        return r.stdout.strip()

    def test_voices_and_taste_cache_under_hypnomix_home_and_nothing_lands_under_the_real_home(self):
        from hypnomix.workflow import taste as T
        from tests.test_workflow import make_set
        fake, home = self.dir / "realhome", self.dir / "hx"
        fake.mkdir()
        als = make_set(self.dir / "Song.als")
        code = f"""
from pathlib import Path
from hypnomix.studio import voices as V
from hypnomix.workflow import taste as T
print(V.cache_dir(), T.cache_dir(), V.CACHE, T.CACHE, sep="|")
print(V.song_spacing({str(als)!r}).get("skipped", "")[:40])
"""
        out = self.run_py(code, home, fake).splitlines()
        self.assertEqual(out[0].split("|"), [str(home / "cache")] * 4)
        self.assertTrue(list((home / "cache" / "names").glob("*/names.json")))      # the names went there
        self.assertEqual(sorted(p.name for p in fake.iterdir()), [])                 # nothing under the real home
        key = T.cache_key(als)
        self.assertTrue((home / "cache" / "names" / key / "names.json").exists())    # and taste looks in the same place

    def test_the_learned_style_and_the_taste_profile_also_follow_hypnomix_home(self):
        from tests.test_workflow import make_set
        fake, home = self.dir / "realhome", self.dir / "hx"
        fake.mkdir()
        als = make_set(self.dir / "Song.als")
        code = f"""
from hypnomix.studio import voices as V
from hypnomix.workflow import taste as T
print(V.STYLE, T.PROFILE, V.style_path(), T.profile_path(), sep="|")
"""
        out = self.run_py(code, home, fake).split("|")
        self.assertEqual(out, [str(home / "harmony-style.json"), str(home / "taste.json")] * 2)
        env = dict(os.environ, HOME=str(fake), HYPNOMIX_HOME=str(home), PYTHONPATH=str(ROOT))
        for args in (["voices", "--confirm", "lead_margin=4"],
                     ["taste", str(als), "--out", str(self.dir / "tasteout")]):
            r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *args], capture_output=True, text=True, env=env,
                               cwd=str(self.dir))
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertEqual(json.loads((home / "harmony-style.json").read_text())["confirmed"], {"lead_margin": 4.0})
        self.assertTrue((home / "taste.json").exists())
        self.assertEqual(sorted(p.name for p in fake.iterdir()), [])             # nothing under the real home, not even a folder

    def test_without_hypnomix_home_the_default_place_is_unchanged(self):
        fake = self.dir / "realhome"
        fake.mkdir()
        env = {k: v for k, v in os.environ.items() if k != "HYPNOMIX_HOME"}
        env.update(HOME=str(fake), PYTHONPATH=str(ROOT))
        r = subprocess.run([sys.executable, "-c", "from hypnomix.studio import voices as V; from hypnomix.workflow "
                            "import taste as T; print(V.CACHE, T.CACHE)"], capture_output=True, text=True, env=env)
        want = str(fake / ".hypnomix" / "cache")
        self.assertEqual(r.stdout.split(), [want, want], r.stderr[-500:])

    def test_taste_song_reads_the_cache_of_the_current_home(self):
        from hypnomix.workflow import taste as T
        from tests.test_workflow import make_set
        als = make_set(self.dir / "Song.als")
        with mock.patch.dict(os.environ, {"HYPNOMIX_HOME": str(self.dir / "h1")}):
            self.assertIn("not studied yet", T.song(als)["skipped"])
            nd = T.cache_dir() / "names" / T.cache_key(als)
            nd.mkdir(parents=True)
            (nd / "names.json").write_text(json.dumps({"tracks": [{"old": "Vox", "label": "Lead Vocal", "confidence": 0.9}]}))
            self.assertNotIn("not studied yet", str(T.song(als).get("skipped", "")))
        with mock.patch.dict(os.environ, {"HYPNOMIX_HOME": str(self.dir / "h2")}):   # another home: nothing studied there
            self.assertIn("not studied yet", T.song(als)["skipped"])


# ---------------------------------------------------------------- 4. the REAPER align panel's port
class AlignPort(unittest.TestCase):
    def setUp(self):
        from hypnomix.reaper import align as A
        self.A = A
        A.APP = None

    def tearDown(self):
        self.A.APP = None

    def test_the_port_comes_from_hypnomix_port(self):
        with mock.patch.dict(os.environ, {"HYPNOMIX_PORT": "9123"}):
            self.assertEqual(self.A.app_url(), "http://127.0.0.1:9123")
        env = {k: v for k, v in os.environ.items() if k != "HYPNOMIX_PORT"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(self.A.app_url(), "http://127.0.0.1:8791")
        with mock.patch.dict(os.environ, {"HYPNOMIX_PORT": "nonsense"}):
            self.assertEqual(self.A.app_url(), "http://127.0.0.1:8791")

    def test_app_calls_go_to_that_port(self):
        seen = []

        class Resp:
            def read(self):
                return b"{}"
        with mock.patch.dict(os.environ, {"HYPNOMIX_PORT": "9124"}), \
                mock.patch("urllib.request.urlopen", side_effect=lambda req, timeout=0: seen.append(req.full_url) or Resp()):
            self.A.app("/api/align/state")
        self.assertEqual(seen, ["http://127.0.0.1:9124/api/align/state"])

    def test_the_flag_wins_and_the_panel_asks_the_right_app(self):
        with mock.patch.dict(os.environ, {"HYPNOMIX_PORT": "9125"}), \
                mock.patch.object(self.A, "app", side_effect=OSError("down")):
            with self.assertRaises(SystemExit):
                self.A.main(["--port", "9126"])
            self.assertEqual(self.A.APP, "http://127.0.0.1:9126")
            self.A.APP = None
            with self.assertRaises(SystemExit):
                self.A.main([])
            self.assertEqual(self.A.APP, "http://127.0.0.1:9125")

    def test_no_port_is_written_into_the_source_any_more(self):
        text = (ROOT / "hypnomix" / "reaper" / "align.py").read_text()
        self.assertNotIn('"http://127.0.0.1:8791"', text)
        self.assertNotIn("default=8791", text)


if __name__ == "__main__":
    unittest.main()
