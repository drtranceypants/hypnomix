"""The fix pipeline tells the truth: what `fix` says it applied is what it applied.

Approved findings no step can write are reported (never counted as applied); `--dry-run` writes nothing; a repaired
copy never replaces an earlier one; a run that wrote nothing is not a version in history; history, diff and undo work
for REAPER projects and say why they cannot for a folder; `ab` and `abset` say what failed in plain words and never
log a version of their own; concurrent decisions are not lost; the verify line pairs hits by nearest position.

Everything is synthesised in a temporary folder. Run from the repo root:
    python -m unittest tests.test_fix_fixpipe -v
"""
import gzip
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

from tests.test_workflow import make_set, tone, SR

ROOT = Path(__file__).resolve().parents[1]


def hx(*args, home):
    env = dict(os.environ, HYPNOMIX_HOME=str(home), HYPNOMIX_APP_HOME=str(Path(home) / "app"), HOME=str(home),
               HYPNOMIX_USER_HOME=str(home), HYPNOMIX_DISKCARE="off")
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True, env=env,
                       cwd=str(ROOT), encoding="utf-8")
    return r.returncode, r.stdout + r.stderr


def named_set(path):
    """make_set, with a UserName on its track so that a rename can be written into it."""
    p = make_set(path)
    x = gzip.open(p).read().decode().replace('<EffectiveName Value="Vox"/>',
                                              '<EffectiveName Value="Vox"/><UserName Value="Vox"/>', 1)
    with gzip.open(p, "wb") as f:
        f.write(x.encode())
    return p


def scenario(root, findings, name="Song"):
    """A Live set and a scan folder whose findings.json holds exactly `findings` (hand-made, as a scan would write)."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    als = named_set(root / f"{name}.als")
    sd = root / "scan"
    sd.mkdir(exist_ok=True)
    rows = [dict(dict(n=i, severity="low", track="Vox", where="1.1.00", problem="p", fix="f", kind="x"), **f)
            for i, f in enumerate(findings, 1)]
    (sd / "findings.json").write_text(json.dumps({"set": str(als), "notes": [], "findings": rows}), encoding="utf-8")
    (sd / "scan.json").write_text(json.dumps({"set": str(als), "mode": "set", "set_mtime": als.stat().st_mtime}), encoding="utf-8")
    return sd, als


RENAME = dict(id="name-1", tool="name", applies="set", kind="track-name", old="Vox", new="Lead", track="Vox")
VOCALLEVEL = dict(id="vocallevel-1", tool="vocallevel", applies="set", kind="upper-over-melody",
                  fix="lower Vox Harm by 4.0 dB on this line")


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.td = Path(self._td.name)
        self.home = self.td / "home"
        self.home.mkdir()

    def tearDown(self):
        self._td.cleanup()

    def fix(self, sd, *args):
        return hx("fix", sd, *args, home=self.home)

    def versions(self, sd):
        p = Path(sd) / "history" / "history.json"
        return json.loads(p.read_text(encoding="utf-8"))["versions"] if p.exists() else []


class ApprovedButNotWritten(Base):
    def test_an_approved_vocal_level_fix_is_reported_not_counted_as_applied(self):
        sd, als = scenario(self.td / "a", [VOCALLEVEL])
        code, out = self.fix(sd, "--approve", "vocallevel-1", "--out", "Song (fixed).als")
        self.assertEqual(code, 1, out)
        self.assertIn("FAILED (not done)", out)
        self.assertIn("vocallevel-1: fix does not write vocal-level moves", out)
        self.assertIn("hypnomix vocallevel", out)                       # and what to do instead
        self.assertIn("nothing was written", out)
        self.assertFalse((als.parent / "Song (fixed).als").exists())
        self.assertEqual(self.versions(sd), [])                          # no phantom version
        self.assertNotIn("history: v1", out)

    def test_the_rest_of_the_run_still_applies_and_the_stuck_item_is_listed(self):
        sd, als = scenario(self.td / "a", [VOCALLEVEL, RENAME])
        code, out = self.fix(sd, "--approve", "vocallevel-1,name-1", "--out", "Song (fixed).als")
        self.assertEqual(code, 1, out)
        self.assertTrue((als.parent / "Song (fixed).als").exists())
        self.assertIn("- vocallevel-1: fix does not write vocal-level moves", out)
        v = self.versions(sd)
        self.assertEqual(len(v), 1)
        self.assertIn("vocallevel-1: fix does not write", v[0]["failed"][0])   # the log says it was not done

    def test_a_scan_offers_vocal_level_moves_as_by_hand(self):
        from hypnomix.session import vocallevel as VL
        from tests.test_vocallevel import GAPS, SR as VSR, tone as vtone
        sig = {"Low": vtone(220, 20.5, -20, GAPS), "High": vtone(440, 20.5, -18, GAPS)}
        _, findings, _ = VL.plan(sig, VSR, melody="Low", order=["Low", "High"], jump=9, upper_under=1.5)
        self.assertTrue(findings)
        self.assertEqual({f["applies"] for f in findings}, {"manual"})

    def test_approving_a_by_hand_vocal_level_move_is_listed_by_hand_and_logs_no_version(self):
        sd, als = scenario(self.td / "a", [dict(VOCALLEVEL, applies="manual")])
        code, out = self.fix(sd, "--approve", "vocallevel-1")
        self.assertEqual(code, 0, out)
        self.assertIn("approved, but by hand", out)
        self.assertIn("hypnomix vocallevel", out)
        self.assertEqual(self.versions(sd), [])

    def test_an_unknown_tool_or_a_missing_applies_is_never_dropped_quietly(self):
        sd, als = scenario(self.td / "a", [dict(id="smooth-1", tool="frobnicate", applies="set"),
                                           dict(id="smooth-2", tool="smooth")])
        for fid, words in (("smooth-1", "no step for 'frobnicate'"), ("smooth-2", "does not say how it is applied")):
            code, out = self.fix(sd, "--approve", fid, "--out", f"New {fid}.als")
            self.assertEqual(code, 1, out)
            self.assertIn(f"- {fid}:", out)
            self.assertIn(words, out)
            self.assertFalse((als.parent / f"New {fid}.als").exists())
        self.assertEqual(self.versions(sd), [])

    def test_an_approved_id_that_is_not_in_the_scan_any_more_is_listed(self):
        sd, als = scenario(self.td / "a", [dict(id="info-1", tool="intent", applies="manual", fix="by hand")])
        self.fix(sd, "--decide", "info-1=approve")
        dec = json.loads((sd / "decisions.json").read_text(encoding="utf-8"))
        dec["ghost-7"] = dict(dec["info-1"])
        (sd / "decisions.json").write_text(json.dumps(dec), encoding="utf-8")
        code, out = self.fix(sd, "--approved")
        self.assertEqual(code, 0, out)
        self.assertIn("approved, but not in this scan any more (1)", out)
        self.assertIn("- ghost-7:", out)


class DryRun(Base):
    def snapshot(self, sd):
        return {str(p.relative_to(sd.parent)): p.read_bytes() for p in sd.parent.rglob("*") if p.is_file()}

    def test_approved_dry_run_writes_nothing(self):
        sd, als = scenario(self.td / "a", [RENAME])
        self.fix(sd, "--decide", "name-1=approve")
        before = self.snapshot(sd)
        code, out = self.fix(sd, "--approved", "--out", "Song (dry).als", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("About to write", out)
        self.assertIn("Would try to apply: name-1", out)
        self.assertNotIn("Would apply:", out)                            # a step can still refuse: no promise
        self.assertIn("dry run: nothing was written", out)
        self.assertEqual(before, self.snapshot(sd))                      # no set, no log, no history, no decision, no lock
        code, out = self.fix(sd, "--approved", "--out", "Song (dry).als")  # and the same command then really writes
        self.assertEqual(code, 0, out)
        self.assertTrue((als.parent / "Song (dry).als").exists())
        self.assertEqual(len(self.versions(sd)), 1)

    def test_explicit_approve_dry_run_does_not_record_the_decision(self):
        sd, als = scenario(self.td / "a", [RENAME])
        code, out = self.fix(sd, "--approve", "name-1", "--out", "Song (dry).als", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertFalse((sd / "decisions.json").exists())
        self.assertFalse((sd / "fix-log.md").exists())
        self.assertFalse((als.parent / "Song (dry).als").exists())

    def test_decide_dry_run_records_nothing(self):
        sd, als = scenario(self.td / "a", [RENAME])
        code, out = self.fix(sd, "--decide", "name-1=approve", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("nothing recorded", out)
        self.assertFalse((sd / "decisions.json").exists())


class ConcurrentDecisions(Base):
    def test_record_keeps_a_decision_written_by_someone_else_meanwhile(self):
        from hypnomix.workflow import fix as F
        sd = self.td / "scan"
        sd.mkdir()
        entry = lambda d: dict(decision=d)
        F.record(sd, {"a": entry("approve")})
        stale = F.load_decisions(sd)                                      # what a slow process read first ...
        F.record(sd, {"c": entry("skip")})                                # ... another one decided meanwhile ...
        F.record(sd, {"b": entry("change")})                              # ... and then the slow one saves its own
        self.assertEqual(sorted(F.load_decisions(sd)), ["a", "b", "c"])
        self.assertEqual(sorted(stale), ["a"])
        F.record(sd, {"a": entry("skip")}, keep_existing=True)           # an explicit --approve never changes a decision
        self.assertEqual(F.load_decisions(sd)["a"]["decision"], "approve")

    def test_many_writers_at_once_lose_nothing(self):
        from hypnomix.workflow import fix as F
        sd = self.td / "scan"
        sd.mkdir()
        errs = []

        def work(k):
            try:
                for j in range(15):
                    F.record(sd, {f"id-{k}-{j}": dict(decision="approve")})
            except Exception as e:      # pragma: no cover
                errs.append(e)
        ts = [threading.Thread(target=work, args=(k,)) for k in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errs, [])
        self.assertEqual(len(F.load_decisions(sd)), 6 * 15)

    def test_separate_processes_deciding_at_once_lose_nothing(self):
        ids = [f"smooth-{i}" for i in range(1, 7)]
        sd, als = scenario(self.td / "a", [dict(id=i, tool="smooth", applies="manual") for i in ids])
        env = dict(os.environ, HYPNOMIX_HOME=str(self.home), HOME=str(self.home), HYPNOMIX_DISKCARE="off")
        for rnd in range(3):
            if (sd / "decisions.json").exists():
                (sd / "decisions.json").unlink()
            ps = [subprocess.Popen([sys.executable, "-m", "hypnomix.cli", "fix", str(sd), "--decide", f"{i}=skip"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=str(ROOT)) for i in ids]
            for p in ps:
                p.communicate()
                self.assertEqual(p.returncode, 0)
            self.assertEqual(sorted(json.loads((sd / "decisions.json").read_text(encoding="utf-8"))), sorted(ids), f"round {rnd}")


class FolderRepairs(Base):
    def raw_folder(self, *names):
        raw = self.td / "raw"
        raw.mkdir(exist_ok=True)
        for n in names:
            sf.write(str(raw / n), tone(3.0) + 0.05, SR, subtype="PCM_16")      # a DC offset: the clean-up finding
        return raw

    def scan(self, raw):
        sd = self.td / "scan"
        code, out = hx("scan", raw, "--out", sd, home=self.home)
        self.assertEqual(code, 0, out)
        return sd, [f for f in json.loads((sd / "findings.json").read_text(encoding="utf-8"))["findings"] if f["kind"] == "dc"]

    def test_same_stem_in_three_formats_gives_three_repaired_copies(self):
        raw = self.raw_folder("take.wav", "take.flac", "take.aiff")
        sd, dc = self.scan(raw)
        self.assertEqual(len(dc), 3)
        code, out = self.fix(sd, "--approve", ",".join(f["id"] for f in dc))
        self.assertEqual(code, 0, out)
        made = sorted(p.name for p in (sd / "fixed").iterdir())
        self.assertEqual(len(made), 3, made)
        self.assertEqual(len(set(made)), 3)
        self.assertEqual(out.count(" ok "), 3)
        self.assertFalse([p for p in (sd / "fixed").iterdir() if p.name.startswith(".")])   # no scratch folder left

    def test_an_earlier_repaired_copy_is_never_overwritten(self):
        raw = self.raw_folder("Guitar.wav")
        sd, dc = self.scan(raw)
        self.fix(sd, "--approve", dc[0]["id"])
        mine = next((sd / "fixed").iterdir())
        mine.write_bytes(b"MINE")
        code, out = self.fix(sd, "--approve", dc[0]["id"])
        self.assertEqual(code, 0, out)
        self.assertEqual(mine.read_bytes(), b"MINE")
        names = sorted(p.name for p in (sd / "fixed").iterdir())
        self.assertEqual(len(names), 2, names)
        self.assertIn(" 2", names[0] + names[1])
        self.assertIn("a name that is taken gets a number", out)          # the banner says so

    def test_a_scanned_folder_that_moved_is_named_and_nothing_is_logged(self):
        raw = self.raw_folder("Guitar.wav")
        sd, dc = self.scan(raw)
        shutil.move(str(raw), str(self.td / "raw_moved"))
        code, out = self.fix(sd, "--approve", dc[0]["id"])
        self.assertNotEqual(code, 0)
        self.assertIn("the scanned folder is gone", out)
        self.assertNotIn("Traceback", out)
        self.assertEqual(self.versions(sd), [])
        self.assertFalse((sd / "fixed").exists())

    def test_a_failing_repair_says_why_on_the_console_and_logs_no_version(self):
        raw = self.raw_folder("Guitar.wav")
        sd, dc = self.scan(raw)
        (raw / "Guitar.wav").unlink()                                      # the folder is there, the file is not
        code, out = self.fix(sd, "--approve", dc[0]["id"])
        self.assertEqual(code, 1, out)
        self.assertIn("failed:", out.split("FAILED (not done)")[1])         # not only "failed": the reason follows
        self.assertEqual(self.versions(sd), [])
        self.assertEqual(list((sd / "fixed").iterdir()), [])

    def test_history_of_a_folder_scan_says_there_is_no_set(self):
        raw = self.raw_folder("Guitar.wav")
        sd, dc = self.scan(raw)
        self.fix(sd, "--approve", dc[0]["id"])
        self.assertEqual(len(self.versions(sd)), 1)
        code, out = self.fix(sd, "--approve", dc[0]["id"])           # the hint after a folder run points at no dead end
        self.assertIn("history: v2", out)
        self.assertNotIn("--undo", out)
        for args in (("--undo", "1"), ("--undo-item", dc[0]["id"]), ("--diff", "0", "1")):
            code, out = hx("history", sd, *args, home=self.home)
            self.assertNotEqual(code, 0)
            self.assertIn("folder of recordings", out)
            self.assertNotIn("kept no copy", out)
            self.assertNotIn("Traceback", out)


class Helpers(unittest.TestCase):
    def test_free_dest_numbers_a_taken_name(self):
        from hypnomix.workflow import fix as F
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self.assertEqual(F.free_dest(d, "a (clean).wav"), d / "a (clean).wav")
            (d / "a (clean).wav").write_text("1", encoding="utf-8")
            self.assertEqual(F.free_dest(d, "a (clean).wav"), d / "a (clean 2).wav")
            (d / "a (clean 2).wav").write_text("2", encoding="utf-8")
            self.assertEqual(F.free_dest(d, "a (clean).wav"), d / "a (clean 3).wav")
            (d / "plain.txt").write_text("x", encoding="utf-8")
            self.assertEqual(F.free_dest(d, "plain.txt"), d / "plain 2.txt")

    def test_a_long_line_keeps_its_reason_and_loses_only_the_path(self):
        from hypnomix.workflow.fix import last_line, short_line
        long_dir = "/very/long/" + "folder name/" * 20
        txt = f"error: can't read '{long_dir}take.flac' as audio: not an audio file"
        got = last_line(txt)
        self.assertLessEqual(len(got), 200)
        self.assertTrue(got.endswith("as audio: not an audio file"), got)
        self.assertIn("take.flac", got)
        self.assertNotIn("folder name/", got)
        bare = f"could not open {long_dir}x.wav: no such file or directory"        # a path that is not quoted
        self.assertTrue(last_line(bare, 80).endswith("no such file or directory"), last_line(bare, 80))
        wall = "word " * 100 + "and then the reason it failed"                      # no path to shrink: cut the middle
        cut = short_line(wall, 60)
        self.assertEqual(len(cut), 60)
        self.assertIn("...", cut)
        self.assertTrue(cut.endswith("the reason it failed"), cut)
        self.assertEqual(short_line("short and plain", 60), "short and plain")

    def test_last_line_skips_log_pointers(self):
        from hypnomix.workflow import fix as F
        self.assertEqual(F.last_line("one\n\nthe reason\nlog: /x/fix-log.md\nhistory: v1"), "the reason")
        self.assertEqual(F.last_line(""), "")

    def test_timing_hits_are_paired_by_nearest_position(self):
        from hypnomix.workflow import fix as F
        self.assertEqual(F.where_beats("13.3.09"), 12 * 4 + 2 + 0.09)
        self.assertIsNone(F.where_beats("whole take"))
        items = [("timing-1", "Drums", F.where_beats("13.3.09")), ("timing-2", "Drums", F.where_beats("14.1.10")),
                 ("timing-3", "Bass", F.where_beats("14.1.10"))]
        left = [("Drums", F.where_beats("13.3.04")), ("Bass", 99.0)]      # timing-1 moved to .04: still measured
        self.assertEqual(F.timing_still(items, left), ["timing-1"])
        self.assertEqual(F.timing_still(items, []), [])
        # one remaining hit can stand for only one approved hit
        two = [("a", "Drums", 10.0), ("b", "Drums", 10.1)]
        self.assertEqual(len(F.timing_still(two, [("Drums", 10.05)])), 1)

    def test_planned_files_names_the_real_folders_and_only_the_checks_that_run(self):
        from hypnomix.workflow import fix as F
        tune = dict(id="tune-Lead", tool="tune", applies="audio", track="Lead")
        smooth = dict(id="smooth-1", tool="smooth", applies="set", track="Vox")
        dehiss = dict(id="rec-1", tool="dehiss", applies="audio", run=["dehiss", "a.wav", "{out}"])
        sd = Path("/scan")
        rows = lambda *a, **k: {str(p): w for p, w in F.planned_files(*a, **k)}
        rp = rows([tune], sd, Path("/proj/Song.rpp"), Path("/proj/New.rpp"), Path("/proj/Song.rpp"), True)
        self.assertIn(str(Path("/proj/Tuned")), rp)
        self.assertNotIn(str(Path("/proj/Samples/Tuned")), rp)
        self.assertIn(".notes.txt", rp[str(Path("/proj/Tuned"))])
        lv = rows([tune], sd, Path("/proj/Song.als"), Path("/proj/New.als"), Path("/proj/Song.als"), False)
        self.assertIn(str(Path("/proj/Samples/Tuned")), lv)
        self.assertNotIn(str(sd / "raw" / "recheck-*.json"), lv)           # tuning does not re-measure
        au = rows([dehiss], sd, None, None, None, False)
        self.assertNotIn(str(sd / "raw" / "recheck-*.json"), au)           # a repaired recording is not re-measured
        self.assertIn("gets a number", au[str(sd / "fixed")])
        st = rows([smooth], sd, Path("/proj/Song.als"), Path("/proj/New.als"), Path("/proj/Song.als"), False)
        self.assertIn(str(sd / "raw" / "recheck-*.json"), st)

    def test_reaper_timing_verify_pairs_hits_by_nearest_position(self):
        from hypnomix.workflow import fix_project as FP
        from hypnomix.workflow import timing_project as TP
        items = [dict(id="timing-1", track="Drums", where="13.3.09", edit=dict(roles={})),
                 dict(id="timing-2", track="Drums", where="20.1.00", edit=dict(roles={}))]
        issues = [dict(track="Drums", beat=12 * 4 + 2 + 0.04)]            # the first one moved a little, still late
        buf = io.StringIO()
        with mock.patch("hypnomix.project.load", return_value=object()), \
                mock.patch.object(TP, "analyse", return_value=([], issues, {})), mock.patch("sys.stdout", buf):
            log = FP.verify_timing(Path("x.rpp"), Path("."), items)
        line = [l for l in log if l.startswith("- timing")][0]
        self.assertIn("1 of 2 approved hits no longer out of time", line)
        self.assertIn("still measured: timing-1", line)


class AbPreviewNotes(Base):
    def prepare(self, scan_extra):
        sd, als = scenario(self.td / "a", [dict(id="tune-Vox", tool="tune", applies="audio", track="Vox", kind="pitch")])
        scan = json.loads((sd / "scan.json").read_text(encoding="utf-8"))
        scan.update(key="A minor", **scan_extra)
        (sd / "scan.json").write_text(json.dumps(scan), encoding="utf-8")
        (sd / "raw" / "renders").mkdir(parents=True)
        sf.write(str(sd / "raw" / "renders" / "Vox.wav"), tone(4.0), SR)
        return sd

    def run_ab(self, sd):
        from hypnomix.workflow import ab
        calls = []

        def fake(*args, **kw):
            calls.append([str(a) for a in args])
            sf.write(str(args[2]), tone(4.0, f=233.0), SR)
            return 0, "ok"
        with mock.patch.object(ab, "hx", fake), mock.patch("sys.argv", ["ab", str(sd)]), mock.patch("sys.stdout", io.StringIO()):
            ab.main()
        return calls, json.loads((sd / "ab" / "ab.json").read_text(encoding="utf-8"))

    def test_tune_preview_gets_the_instrumental_the_scan_was_given(self):
        back = self.td / "backing.wav"
        sf.write(str(back), tone(4.0, f=110.0), SR)
        sd = self.prepare(dict(backing=str(back)))
        calls, manifest = self.run_ab(sd)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][calls[0].index("--chords") + 1], str(back))
        self.assertTrue(manifest["tune-Vox"].get("a"), manifest)

    def test_tune_preview_without_a_chord_source_says_to_scan_again_not_to_pass_flags_ab_lacks(self):
        sd = self.prepare({})
        calls, manifest = self.run_ab(sd)
        self.assertEqual(calls, [])                                         # nothing is run to fail
        note = manifest["tune-Vox"]["note"]
        self.assertIn("scan again with --backing", note)
        self.assertNotIn("--no-chord-check", note)

    def test_a_failure_reason_is_its_last_line_not_the_tail_of_a_path(self):
        from hypnomix.workflow import ab
        txt = "\nrefusing to correct notes without checking the chord under them: pass --chords X or --no-chord-check"
        self.assertIn("scan again with --backing", ab.why_failed(txt))
        self.assertNotIn("--chords", ab.why_failed(txt))
        long = "/very/long/path/" * 30 + "\ncan't read /x/Harmony.wav as audio: no such file\nlog: /tmp/x"
        self.assertEqual(ab.why_failed(long), "can't read /x/Harmony.wav as audio: no such file")


class AbsetBuildsQuietly(Base):
    def test_a_throwaway_fix_leaves_the_real_history_alone(self):
        from hypnomix.workflow import abset as A
        sd, als = scenario(self.td / "a", [RENAME])
        code, out = self.fix(sd, "--approve", "name-1", "--out", "Song (named).als")
        self.assertEqual(code, 0, out)
        before = sorted(p.name for p in (sd / "history").iterdir())
        self.assertEqual(len(self.versions(sd)), 1)
        env = dict(os.environ, HYPNOMIX_HOME=str(self.home), HOME=str(self.home), HYPNOMIX_DISKCARE="off")
        with mock.patch.dict(os.environ, env):
            fx, err = A.fixed_copy(sd, "name-1", als)
        try:
            self.assertEqual(err, [])
            self.assertTrue(fx.exists())
        finally:
            if fx:
                fx.unlink()
        self.assertEqual(len(self.versions(sd)), 1)                         # no version for the throwaway run
        self.assertEqual(sorted(p.name for p in (sd / "history").iterdir()), before)

    def test_a_build_that_fails_gives_the_real_reason_not_a_deleted_log(self):
        from hypnomix.workflow import abset as A
        sd, als = scenario(self.td / "a", [VOCALLEVEL])
        env = dict(os.environ, HYPNOMIX_HOME=str(self.home), HOME=str(self.home), HYPNOMIX_DISKCARE="off")
        with mock.patch.dict(os.environ, env):
            fx, err = A.fixed_copy(sd, "vocallevel-1", als)
        self.assertIsNone(fx)
        self.assertIn("vocal-level", err[0])
        self.assertNotIn("fix-log.md", err[0])
        self.assertNotIn("hm-ab-", err[0])
        self.assertNotIn("hypnomix-ab-", err[0])

    def test_fail_reason_reads_the_failed_list_then_what_was_not_applied(self):
        from hypnomix.workflow import abset as A
        out = "About to write\n\nNot applied (1):\n\n  no longer found (1): x\n  - smooth-1 Vox 1.1.00: gone\n      next: re-scan\n"
        self.assertEqual(A.fail_reason(out, ""), "smooth-1 Vox 1.1.00: gone")
        out += "\nFAILED (not done):\n- smooth-1: smooth --apply failed\n\nlog: /tmp/x/fix-log.md\n"
        self.assertEqual(A.fail_reason(out, ""), "smooth-1: smooth --apply failed")
        self.assertEqual(A.fail_reason("", "the set is gone\n"), "the set is gone")

    def test_it_works_where_the_system_will_not_make_symlinks(self):
        from hypnomix.workflow import abset as A
        sd, als = scenario(self.td / "a", [RENAME])
        (sd / "raw").mkdir()
        (sd / "raw" / "note.txt").write_text("x", encoding="utf-8")
        made = []
        real = tempfile.mkdtemp

        def spy(*a, **k):
            made.append(real(*a, **k))
            return made[-1]
        err = OSError(1314, "A required privilege is not held by the client")
        with mock.patch("os.symlink", side_effect=err), mock.patch("tempfile.mkdtemp", spy):
            tmp = A.scratch_scan(sd)
            try:
                self.assertEqual((tmp / "raw" / "note.txt").read_text(encoding="utf-8"), "x")
                self.assertFalse((tmp / "raw").is_symlink())
                self.assertFalse((tmp / "history").exists())
            finally:
                shutil.rmtree(tmp)
            # a copy that fails halfway leaves no folder behind, and fixed_copy answers in one sentence
            with mock.patch("shutil.copytree", side_effect=OSError(28, "No space left on device")):
                fx, why = A.fixed_copy(sd, "name-1", als)
        self.assertIsNone(fx)
        self.assertIn("could not be copied", why[0])
        self.assertTrue(made)
        self.assertFalse([m for m in made if Path(m).exists()])


class AbsetScratchWithoutSymlinks(Base):
    def test_a_folder_is_rebuilt_from_links_not_copied_where_symlinks_are_refused(self):
        from hypnomix.workflow import abset as A
        sd, als = scenario(self.td / "a", [RENAME])
        (sd / "raw").mkdir()
        (sd / "raw" / "render.bin").write_bytes(b"R" * 4096)
        with mock.patch("os.symlink", side_effect=OSError(1314, "no privilege")):
            tmp = A.scratch_scan(sd)
        try:
            self.assertFalse((tmp / "raw").is_symlink())
            self.assertTrue(os.path.samefile(tmp / "raw" / "render.bin", sd / "raw" / "render.bin"))   # no second copy on disk
            with mock.patch("os.symlink", side_effect=OSError(1314, "no privilege")), \
                    mock.patch("os.link", side_effect=OSError(18, "cross-device link")):
                again = A.scratch_scan(sd)          # another drive: a plain copy still works
            try:
                self.assertEqual((again / "raw" / "render.bin").read_bytes(), b"R" * 4096)
                self.assertFalse(os.path.samefile(again / "raw" / "render.bin", sd / "raw" / "render.bin"))
            finally:
                shutil.rmtree(again)
        finally:
            shutil.rmtree(tmp)
        self.assertEqual((sd / "raw" / "render.bin").read_bytes(), b"R" * 4096)       # removing the scratch left the real file


class ArdourDiffShowsRealEditsOnly(unittest.TestCase):
    A = """<?xml version="1.0" encoding="UTF-8"?>
<Session version="7000" name="S">
  <Routes>
    <Route id="1" name="Vox" gain="1"/>
  </Routes>
</Session>
"""

    def test_rewriting_the_file_out_again_is_not_a_change(self):
        from hypnomix.workflow import history as H
        td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, td, True)
        (td / "a.ardour").write_text(self.A, encoding="utf-8")
        import xml.etree.ElementTree as ET
        ET.ElementTree(ET.parse(str(td / "a.ardour")).getroot()).write(str(td / "b.ardour"), encoding="utf-8", xml_declaration=True)
        same = H.text_diff(td / "a.ardour", td / "b.ardour")
        self.assertTrue(same.startswith("0 changed line(s)"), same)
        (td / "c.ardour").write_text(self.A.replace('gain="1"', 'gain="0.5"'), encoding="utf-8")
        changed = H.text_diff(td / "a.ardour", td / "c.ardour")
        self.assertTrue(changed.startswith("2 changed line(s)"), changed)
        self.assertIn('gain="0.5"', changed)
        self.assertNotIn("<?xml", changed)


class DemoReachesTheTuningFix(unittest.TestCase):
    def test_the_reaper_demo_writes_an_instrumental_and_the_scan_line_passes_it(self):
        from hypnomix.studio import demo
        td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, td, True)
        proj, folder = demo.write_demo(td, "reaper")
        back = (folder / "Instrumental.wav").resolve()
        self.assertTrue(back.exists())
        self.assertFalse((folder / "Audio" / "Instrumental.wav").exists())
        info = sf.info(str(back))
        self.assertGreater(info.duration, 30)
        text = (folder / "DEMO.md").read_text(encoding="utf-8")
        self.assertIn(f'--key "A minor" --backing "{back}"', text)
        _, flat = demo.write_demo(td, "folder")
        self.assertFalse((flat / "Instrumental.wav").exists())                  # a folder of stems stays only stems
        self.assertNotIn("--backing", (flat / "DEMO.md").read_text(encoding="utf-8"))


class HarmonyOutsideLive(Base):
    def project(self, suffix):
        d = self.td / "Song"
        d.mkdir()
        t = np.arange(SR * 3) / SR
        sf.write(str(d / "Lead.wav"), (0.3 * np.sin(2 * np.pi * 220 * t) * ((t % 1) < 0.8)).astype(np.float32), SR)
        sf.write(str(d / "Harm.wav"), (0.5 * np.sin(2 * np.pi * 277 * t) * ((t % 1) < 0.8)).astype(np.float32), SR)
        proj = d / f"Song{suffix}"
        proj.write_text("x", encoding="utf-8")
        sd = self.td / "scan"
        sd.mkdir()
        f = dict(id="harmony-1", n=1, tool="voices", kind="balance", severity="low", track="(vocal parts)", where="",
                 problem="p", fix="f", applies="audio", stems=[str(d / "Lead.wav"), str(d / "Harm.wav")], lead="Lead")
        (sd / "findings.json").write_text(json.dumps({"set": str(proj), "findings": [f]}), encoding="utf-8")
        (sd / "scan.json").write_text(json.dumps({"set": str(proj), "mode": "reaper", "set_mtime": proj.stat().st_mtime}), encoding="utf-8")
        return sd, proj

    def test_harmony_balance_in_a_reaper_project_or_ardour_session_is_balanced_copies(self):
        for suffix in (".rpp", ".ardour"):
            with self.subTest(suffix=suffix):
                shutil.rmtree(self.td / "Song", ignore_errors=True)
                shutil.rmtree(self.td / "scan", ignore_errors=True)
                sd, proj = self.project(suffix)
                code, out = self.fix(sd, "--approve", "harmony-1", "--out", f"Song (fixed){suffix}")
                self.assertEqual(code, 0, out)
                self.assertNotIn("Traceback", out)
                self.assertNotIn("FAILED", out)
                self.assertTrue(list((sd / "fixed" / "voices").glob("*.wav")))
                self.assertFalse((proj.parent / f"Song (fixed){suffix}").exists())     # no project is written for it
                self.assertEqual(proj.read_text(encoding="utf-8"), "x")
                self.assertIn(f"Song (fixed){suffix} was not used", out)               # and --out says it was not used
                self.assertNotIn("Open the new project", out)
                self.assertNotIn("Written and re-read", out)

    def test_the_app_does_not_promise_a_project_for_harmony_balance_outside_live(self):
        from hypnomix.app import server
        f = dict(applies="audio", tool="voices")
        self.assertTrue(server.writes_set(f, "als"))
        self.assertFalse(server.writes_set(f, "rpp"))
        self.assertFalse(server.writes_set(f, "ardour"))
        self.assertTrue(server.writes_set(dict(applies="audio", tool="tune"), "rpp"))
        self.assertTrue(server.writes_set(dict(applies="set", tool="clips"), "ardour"))
        js = (ROOT / "hypnomix" / "app" / "review.js").read_text(encoding="utf-8")
        self.assertIn("f.tool === 'voices' && kind === 'als'", js)
        self.assertIn("writesSetOf(f, R.kind)", js)


class HistoryForProjects(Base):
    def test_history_diff_undo_and_undo_item_work_for_a_reaper_project(self):
        from tests.test_scan_parity import make_rpp, TWO_ITEMS, QUICK, scan
        proj = make_rpp(self.td / "p", TWO_ITEMS)
        sd = self.td / "scan"
        with mock.patch.dict(os.environ, dict(HYPNOMIX_HOME=str(self.home), HOME=str(self.home))):
            scan(proj, "--out", sd, *QUICK)
        ids = [f["id"] for f in json.loads((sd / "findings.json").read_text(encoding="utf-8"))["findings"] if f["tool"] == "clips"][:2]
        self.assertEqual(len(ids), 2)
        code, out = self.fix(sd, "--approve", ",".join(ids), "--out", "Song (fixed).rpp")
        self.assertEqual(code, 0, out)
        self.assertTrue((sd / "history" / "v1-input.rpp").exists())
        self.assertTrue((sd / "history" / "v1-output.rpp").exists())
        code, out = hx("history", sd, "--diff", "0", "1", home=self.home)
        self.assertEqual(code, 0, out)
        self.assertIn("changed line(s) in the project file", out)
        self.assertIn("FADEIN", out)
        code, out = hx("history", sd, "--undo", "1", home=self.home)
        self.assertEqual(code, 0, out)
        self.assertTrue((proj.parent / "Song (back to v1 input).rpp").exists())
        self.assertIn("REAPER", out)
        self.assertNotIn("Live", out)
        code, out = hx("history", sd, "--undo-item", ids[0], home=self.home)
        self.assertEqual(code, 0, out)
        self.assertNotIn("--out", out)
        self.assertTrue(list(proj.parent.glob("Song (v1 without *.rpp")))


if __name__ == "__main__":
    unittest.main()
