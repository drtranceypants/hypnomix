"""Decisions that cannot be lost or misplaced, REVIEW.md that an agent can afford to read, and caches that stay
under the hypnomix home. Everything is synthesised in a temporary folder with a scratch HYPNOMIX_HOME.

Run from the repo root:  python -m unittest tests.test_agents_speed
"""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from tests.test_workflow import make_set

ROOT = Path(__file__).resolve().parent.parent
SR = 44100


def env_for(home, **extra):
    e = dict(os.environ, HYPNOMIX_HOME=str(home), HYPNOMIX_RENDER_CACHE=str(Path(home) / "cache" / "render"),
             PYTHONPATH=str(ROOT))
    e.update({k: str(v) for k, v in extra.items()})
    return e


def hx(*args, home, cwd=None, **extra):
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True,
                       env=env_for(home, **extra), cwd=str(cwd or ROOT), encoding="utf-8")
    return r.returncode, r.stdout + r.stderr


def finding(i, tool="smooth", kind="click", where=None, applies="manual", **kw):
    f = dict(id=f"{tool}-{i}", n=i, tool=tool, kind=kind, severity="low", track="Vox",
             where=where if where is not None else f"{i}.1.00", problem="p", fix="do it by hand", applies=applies)
    f.update(kw)
    return f


def scan_dir(td, findings, setp="", mode="set", name="scan"):
    sd = Path(td) / name
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "findings.json").write_text(json.dumps({"set": str(setp), "notes": [], "findings": findings}), encoding="utf-8")
    (sd / "scan.json").write_text(json.dumps({"set": str(setp), "mode": mode}), encoding="utf-8")
    return sd


class Atomic(unittest.TestCase):
    def test_second_write_keeps_the_first_as_bak_and_a_cut_off_file_falls_back(self):
        from hypnomix.core import atomic as AT
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "decisions.json"
            AT.write_json(p, {"a": 1})
            AT.write_json(p, {"a": 2})
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"a": 2})
            self.assertEqual(json.loads(Path(str(p) + ".bak").read_text(encoding="utf-8")), {"a": 1})
            p.write_text('{"a": 2, "b": [1, 2', encoding="utf-8")                       # a crash in the middle of a plain write
            self.assertEqual(AT.load_json(p, {}, warn=False), {"a": 1})   # the backup, not an exception
            AT.write_json(p, {"a": 3})                                   # a cut-off file never replaces a good backup
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"a": 3})
            self.assertEqual(json.loads(Path(str(p) + ".bak").read_text(encoding="utf-8")), {"a": 1})

    def test_no_backup_returns_default_and_keeps_the_broken_file(self):
        from hypnomix.core import atomic as AT
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "findings.json"
            p.write_text("{ not json", encoding="utf-8")
            self.assertEqual(AT.load_json(p, {"x": 0}, warn=False), {"x": 0})
            self.assertTrue((Path(td) / "findings.json.corrupt").exists())
            self.assertIsNone(AT.load_json(Path(td) / "missing.json"))

    def test_a_failure_before_the_swap_leaves_the_old_file_whole_and_no_temp_file(self):
        from hypnomix.core import atomic as AT
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "scan.json"
            AT.write_json(p, {"v": 1})
            real = os.replace
            os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("disk went away"))
            try:
                with self.assertRaises(OSError):
                    AT.write_json(p, {"v": 2})
            finally:
                os.replace = real
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"v": 1})
            self.assertEqual([x.name for x in Path(td).iterdir() if x.name.endswith(".tmp")], [])

    def test_decisions_use_it(self):
        from hypnomix.workflow import oversight as O
        with tempfile.TemporaryDirectory() as td:
            O.save_decisions(td, {"smooth-1": O.entry("approve")})
            O.save_decisions(td, {"smooth-1": O.entry("skip")})
            (Path(td) / "decisions.json").write_text('{"smooth-1": {"decis', encoding="utf-8")
            self.assertEqual(O.load_decisions(td)["smooth-1"]["decision"], "approve")      # the .bak


class FixDecisions(unittest.TestCase):
    def test_flat_takes_repeats_and_comma_lists(self):
        from hypnomix.workflow import fix
        self.assertEqual(fix.flat(["a,b", "c", " d , "]), ["a", "b", "c", "d"])
        self.assertEqual(fix.flat([]), [])

    def test_approve_and_decide_can_be_repeated(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            sd = scan_dir(td, [finding(1), finding(2), finding(3), finding(4)])
            code, out = hx("fix", sd, "--decide", "smooth-1=skip", "--decide", "smooth-2=skip,smooth-3=change",
                           "--note", "less", home=home)
            self.assertEqual(code, 0, out)
            dec = json.loads((sd / "decisions.json").read_text(encoding="utf-8"))
            self.assertEqual({k: v["decision"] for k, v in dec.items()},
                             {"smooth-1": "skip", "smooth-2": "skip", "smooth-3": "change"})
            code, out = hx("fix", sd, "--approve", "smooth-4", "--approve", "smooth-5", home=home)
            self.assertNotEqual(code, 0)                                     # smooth-5 is unknown: said so, not dropped
            self.assertIn("unknown ids: smooth-5", out)
            sd2 = scan_dir(td, [finding(1), finding(2), finding(3)], name="scan2")
            code, out = hx("fix", sd2, "--approve", "smooth-1", "--approve", "smooth-2,smooth-3", home=home)
            self.assertEqual(code, 0, out)
            dec = json.loads((sd2 / "decisions.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(dec), ["smooth-1", "smooth-2", "smooth-3"])      # all three, not only the last

    def test_not_applied_lists_changes_by_hand_and_what_to_do_next(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            sd = scan_dir(td, [finding(1), finding(2), finding(3, applies="info")])
            hx("fix", sd, "--decide", "smooth-2=change", "--note", "less correction on the verse", home=home)
            hx("fix", sd, "--decide", "smooth-1=approve", home=home)
            code, out = hx("fix", sd, "--approved", home=home)
            self.assertEqual(code, 0, out)
            self.assertIn("Not applied (", out)
            self.assertIn("decided as \"change\"", out)
            self.assertIn("less correction on the verse", out)
            self.assertIn("smooth-1", out.split("approved, but by hand")[1])
            self.assertIn("next:", out)
            log = (sd / "fix-log.md").read_text(encoding="utf-8")
            self.assertIn("Not applied", log)
            self.assertIn("less correction on the verse", log)

    def test_not_applied_lists_findings_no_longer_found(self):
        from hypnomix.workflow import fix
        lines = fix.not_applied("D", [], {}, [], [(dict(id="smooth-9", track="Vox", where="9.1.00"), "no longer found "
                                                    "in this set (already fixed, or the set changed)")], [])
        self.assertIn("no longer found (1)", "\n".join(lines))
        self.assertIn("re-scan", "\n".join(lines))

    def test_defaults_are_announced_with_every_file_before_anything_is_written(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            als = make_set(Path(td) / "Song.als")
            order = finding(1, tool="order", kind="track-order", applies="set", default="approve", where="")
            order["id"] = "order-1"
            retire = finding(2, tool="tidy", kind="retire-off", applies="set", default="approve", where="2 switched-off track(s)",
                             retire=["old a", "old b"])
            retire["id"] = "retire-1"
            sd = scan_dir(td, [order, retire], setp=als)
            (sd / "scan.json").write_text(json.dumps({"set": str(als), "mode": "set", "set_mtime": als.stat().st_mtime}), encoding="utf-8")
            code, out = hx("fix", sd, "--approved", "--out", "Song (fixed).als", home=home)
            head = out.split("About to write")[0]
            self.assertIn("Also applied because they are on by default (skip them to opt out", head)
            self.assertIn("order-1 (track order)", head)
            self.assertIn("retire-1 (removes 2 switched-off tracks; a full copy is kept as 'Song (archive, all takes).als')", head)
            block = out.split("About to write")[1].split("\n\n")[0]
            self.assertIn("Song (fixed).als", block)
            self.assertIn("Song (archive, all takes).als", block)       # the archive copy is listed too
            self.assertIn("fix-log.md", block)
            self.assertIn("decisions.json", block)
            # --no-defaults: nothing was approved by name, so nothing is applied and nothing is announced
            sd2 = scan_dir(td, [order, retire], setp=als, name="scan2")
            code, out = hx("fix", sd2, "--approved", "--no-defaults", "--out", "Other.als", home=home)
            self.assertNotEqual(code, 0)
            self.assertIn("nothing approved", out)
            self.assertNotIn("Also applied because", out)
            self.assertFalse((Path(td) / "Other.als").exists())

    def test_a_default_cleanup_done_by_an_earlier_one_is_not_called_no_longer_found(self):
        from hypnomix.workflow import fix
        f = dict(id="order-1", track="", where="")
        why = "no longer found in this set (already fixed, or the set changed)"
        lines = "\n".join(fix.not_applied("D", [], {}, [], [(f, why)], [], default_ids={"order-1"}))
        self.assertIn("nothing left to change here after the earlier clean-ups", lines)
        self.assertNotIn("already fixed, or the set changed", lines)
        lines = "\n".join(fix.not_applied("D", [], {}, [], [(f, why)], []))          # approved by name: unchanged
        self.assertIn("already fixed, or the set changed", lines)

    def test_about_to_write_lists_the_measurement_files_under_raw(self):
        from hypnomix.workflow import fix
        rows = fix.planned_files([finding(1, tool="smooth", applies="set")], "D", None, Path("X.als"), None, False)
        self.assertTrue(any(str(p).endswith("recheck-*.json") for p, _ in rows), rows)
        rows = fix.planned_files([finding(1, applies="manual")], "D", None, None, None, False)
        self.assertFalse(any("recheck" in str(p) for p, _ in rows))

    def test_list_filters_and_show(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            fs = [finding(i, tool="tune" if i % 2 else "smooth", applies="manual", severity="high" if i < 3 else "low")
                  for i in range(1, 9)]
            sd = scan_dir(td, fs)
            hx("fix", sd, "--decide", "smooth-2=skip", "--decide", "tune-1=approve", home=home)
            _, out = hx("fix", sd, "--list", "--undecided", "--top", "3", home=home)
            ids = [l.split()[1] for l in out.splitlines() if not l.startswith("--")]
            self.assertEqual(len(ids), 3)
            self.assertNotIn("tune-1", ids)
            self.assertNotIn("smooth-2", ids)
            self.assertIn("next page: --offset 3", out)
            _, out = hx("fix", sd, "--list", "--severity", "high", "--tool", "smooth", home=home)
            self.assertEqual([l.split()[1] for l in out.splitlines() if not l.startswith("--")], ["smooth-2"])
            _, out = hx("fix", sd, "--list", "--undecided", "--top", "3", "--offset", "3", home=home)
            self.assertEqual(len([l for l in out.splitlines() if not l.startswith("--")]), 3)
            code, out = hx("fix", sd, "--show", "tune-3", home=home)
            self.assertEqual(code, 0, out)
            self.assertIn("`tune-3`", out)
            self.assertIn("problem:", out)
            self.assertIn("Why this kind of fix:", out)
            self.assertIn("why this technique:", out)
            code, out = hx("fix", sd, "--show", "nope", home=home)
            self.assertNotEqual(code, 0)


class ReScanKeepsDecisionsOnTheirFindings(unittest.TestCase):
    def _group(self, od, rows):
        (Path(od) / "clips.json").write_text(json.dumps({"group": "clips", "set": "S.als", "findings": rows, "notes": []}), encoding="utf-8")

    def test_an_approval_never_moves_to_a_different_finding(self):
        from hypnomix.workflow import oversight as O
        with tempfile.TemporaryDirectory() as td:
            home, od = Path(td) / "home", Path(td) / "scan"
            od.mkdir()
            A = lambda i, w: finding(i, where=w, applies="set", track="Vox")
            self._group(od, [A(1, "5.1.00"), A(2, "9.1.00"), A(3, "13.1.00")])
            self.assertEqual(hx("scan", "--merge", od, home=home)[0], 0)
            hx("fix", od, "--decide", "smooth-1=approve", "--decide", "smooth-3=skip", home=home)
            # the person fixed the clip at 5.1 in the meantime: every id shifts down by one
            self._group(od, [A(1, "9.1.00"), A(2, "13.1.00")])
            code, out = hx("scan", "--merge", od, home=home)
            self.assertEqual(code, 0, out)
            dec = O.load_decisions(od)
            self.assertNotIn("smooth-1", dec)                                    # did NOT attach to the clip at 9.1
            self.assertEqual(dec["smooth-2"]["decision"], "skip")               # followed ITS finding (13.1) to the new id
            self.assertIn("1 earlier decision no longer matches a finding and was set aside", out)
            orphans = json.loads((od / "decisions-orphaned.json").read_text(encoding="utf-8"))
            self.assertEqual(orphans["smooth-1"]["decision"]["decision"], "approve")
            self.assertEqual(orphans["smooth-1"]["was"]["where"], "5.1.00")
            # merging again with nothing changed must not lose or move anything
            code, out = hx("scan", "--merge", od, home=home)
            self.assertEqual(O.load_decisions(od), dec)
            self.assertNotIn("set aside", out)

    def test_same_spot_within_tolerance_is_the_same_finding_and_far_is_not(self):
        from hypnomix.workflow import scan as S
        old = [dict(id="smooth-1", tool="smooth", track="Vox", kind="click", where="1:23.4")]
        near = [dict(id="smooth-7", tool="smooth", track="Vox", kind="click", where="1:23.6")]
        far = [dict(id="smooth-7", tool="smooth", track="Vox", kind="click", where="1:29.0")]
        other = [dict(id="smooth-7", tool="smooth", track="Gtr", kind="click", where="1:23.4")]
        dec = {"smooth-1": {"decision": "approve"}}
        self.assertEqual(S.remap_decisions(old, near, dec)[0], {"smooth-7": {"decision": "approve"}})
        self.assertEqual(S.remap_decisions(old, far, dec)[0], {})
        self.assertEqual(S.remap_decisions(old, other, dec)[0], {})
        bars_old = [dict(id="a-1", tool="t", track="x", kind="k", where="bar 17.2")]
        bars_new = [dict(id="a-4", tool="t", track="x", kind="k", where="bar 17.3")]
        self.assertEqual(list(S.remap_decisions(bars_old, bars_new, {"a-1": {"decision": "skip"}})[0]), ["a-4"])

    def test_two_findings_that_cannot_be_told_apart_are_not_guessed(self):
        from hypnomix.workflow import scan as S
        two = [dict(id=f"x-{i}", tool="t", track="x", kind="k", where="") for i in (1, 2)]
        one = [dict(id="x-1", tool="t", track="x", kind="k", where="")]
        kept, dropped = S.remap_decisions(two, one, {"x-1": {"decision": "approve"}})
        self.assertEqual(kept, {})
        self.assertIn("x-1", dropped)

    def test_a_scan_of_another_source_does_not_inherit_the_folder(self):
        from hypnomix.workflow import scan as S
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "Song.als"
            a.write_text("x", encoding="utf-8")
            ard = Path(td) / "Song"
            ard.mkdir()
            base = Path(td) / "out" / "Song"
            base.mkdir(parents=True)
            (base / "scan.json").write_text(json.dumps({"set": str(a)}), encoding="utf-8")
            self.assertEqual(S.scan_folder(base, a), base)                        # the same source: reuse the folder
            got = S.scan_folder(base, ard)
            self.assertEqual(got.name, "Song (2)")
            (got / "scan.json").write_text(json.dumps({"set": str(ard)}), encoding="utf-8")
            third = Path(td) / "Other" / "Song"
            third.parent.mkdir()
            third.touch()
            self.assertEqual(S.scan_folder(base, ard), got)                       # and it is reused for that source
            self.assertEqual(S.scan_folder(base, third).name, "Song (3)")

    def test_a_set_scan_writes_nothing_outside_its_out_folder(self):
        with tempfile.TemporaryDirectory() as td:
            home, cwd = Path(td) / "home", Path(td) / "cwd"
            cwd.mkdir()
            als = make_set(Path(td) / "Song.als")
            code, out = hx("scan", als, "--only", "effects", "--out", Path(td) / "result", home=home, cwd=cwd)
            self.assertEqual(code, 0, out)
            self.assertEqual(sorted(p.name for p in cwd.iterdir()), [])          # no hypnomix-out/audit/Song.md here
            self.assertTrue((Path(td) / "result" / "effects.json").exists())
            self.assertTrue(list((Path(td) / "result" / "raw").rglob("Song.md")))


class PlainNotes(unittest.TestCase):
    TRACE = ("Traceback (most recent call last):\n  File \"/x/hypnomix/studio/key.py\", line 189, in sections\n"
             "    top = max(votes)\nValueError: max() arg is an empty sequence\n")

    def test_reason_is_the_last_line_without_the_exception_class(self):
        from hypnomix.workflow import scan as S
        self.assertEqual(S.plain_reason(self.TRACE), "no notes or values were found to measure")
        self.assertEqual(S.plain_reason(""), "no output")
        self.assertEqual(S.plain_reason("ok\nsomething broke\n"), "something broke")

    def test_long_paths_become_file_names_and_the_reason_is_never_cut_mid_word(self):
        from hypnomix.workflow import scan as S
        out = "Traceback (most recent call last):\n  File \"x.py\", line 1\nRuntimeError: can't read '/private/tmp/a/b/c/d/e/f/take 3.wav' as audio\n"
        r = S.plain_reason(out)
        self.assertEqual(r, "can't read 'take 3.wav' as audio")
        self.assertNotIn("/", r)
        long = "ValueError: " + "this is a very long reason that goes on and on " * 5
        r = S.plain_reason(long)
        self.assertLessEqual(len(r), 101)
        self.assertTrue(r.endswith("…"))
        self.assertFalse(r[:-1].endswith(("goe", "an")) and not r[:-1].split()[-1] in long.split())

    def test_a_failed_check_is_one_sentence_and_the_traceback_goes_to_raw(self):
        from hypnomix.workflow import scan as S
        with tempfile.TemporaryDirectory() as td:
            note = S.check_failed(Path(td), "key map", self.TRACE, "so vocal tuning uses one key", "key-error.txt")
            for bad in ("Traceback", "line 189", "File "):
                self.assertNotIn(bad, note)
            self.assertNotIn("\n", note)
            self.assertIn("key map: failed (no notes or values were found to measure)", note)
            self.assertIn("raw/key-error.txt", note)
            self.assertIn("Traceback", (Path(td) / "raw" / "key-error.txt").read_text(encoding="utf-8"))

    def test_a_group_that_raises_is_reported_plainly(self):
        from hypnomix.workflow import review as RV, scan as S
        notes = ["key map: failed (x), so tuning uses one key. Full output: raw/key-error.txt",
                 "order: failed (y), so none. Full output: raw/o.txt", "tidy: did NOT run (z)"]
        with tempfile.TemporaryDirectory() as td:
            od = Path(td)
            S.write_review(od, "", [], notes, {})
            md = (od / "REVIEW.md").read_text(encoding="utf-8")
            self.assertEqual(md.count("Checks that did NOT run"), 1)
            self.assertIn("- tidy: did NOT run (z)", md.split("## Notes")[0])


class Preferences(unittest.TestCase):
    def test_off_means_never_propose_and_says_so(self):
        from hypnomix.workflow import scan as S
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            home.mkdir()
            (home / "preferences.json").write_text(json.dumps({"taste": {"tuning": "off", "timing": "off"}}), encoding="utf-8")
            from hypnomix.workflow import prefs as P
            keep = P.PREFS
            P.PREFS = home / "preferences.json"
            try:
                self.assertEqual(S.pref_wants("tune"), "off")
                self.assertEqual(S.pref_wants("timing"), "off")
                od = Path(td) / "scan"
                (od / "raw").mkdir(parents=True)
                rows = [dict(id=f"timing-{i}", tool="timing", kind="hit", severity="low", track="Gtr", where=f"{i}.1.00",
                             problem="p", fix="f", applies="set") for i in range(1, 4)]

                def fake_hx(*args, **kw):
                    (od / "raw" / "timing.json").write_text(json.dumps(
                        dict(findings=rows, looseness_ms=9, tracks=["Gtr"], grid=[])), encoding="utf-8")
                    return 0, ""
                real = S.hx
                S.hx = fake_hx
                try:
                    a = type("A", (), dict(timing_track=["Gtr"]))()
                    found, notes = S.g_timing(Path("S.als"), od, a, {"Gtr": dict(kind="Audio", label="Guitar")})
                finally:
                    S.hx = real
                self.assertEqual(found, [])
                self.assertEqual(len(notes), 1)
                self.assertIn("timing proposals are off in your preferences", notes[0])
                self.assertIn("3 hit(s)", notes[0])
            finally:
                P.PREFS = keep

    def test_a_missing_wants_helper_is_not_an_error(self):
        from hypnomix.workflow import scan as S
        self.assertIsInstance(S.pref_wants("tune"), str)                       # "off", "gentle", a default, or ""


class ReviewIsCompact(unittest.TestCase):
    def _many(self, od, n=40):
        rows = [dict(id=f"smooth-{i}", tool="smooth", kind="click", severity="low", track=f"T{i % 5}", where=f"{i}.1.00",
                     problem=f"click at the start of a clip on T{i % 5}", fix="add a 4 ms fade", applies="set")
                for i in range(1, n + 1)]
        rows += [dict(id=f"timing-{i}", tool="timing", kind="hit", severity="medium", track="Gtr", where=f"{i}.2.00",
                      problem="a hit behind the band", fix="nudge it", applies="set") for i in range(1, n // 2)]
        (Path(od) / "clips.json").write_text(json.dumps({"group": "clips", "set": "S.als", "findings": rows, "notes": []}), encoding="utf-8")
        return rows

    def test_each_explanation_is_written_once_and_items_keep_only_what_is_theirs(self):
        with tempfile.TemporaryDirectory() as td:
            home, od = Path(td) / "home", Path(td) / "scan"
            od.mkdir()
            rows = self._many(od)
            self.assertEqual(hx("scan", "--merge", od, home=home)[0], 0)
            md = (od / "REVIEW.md").read_text(encoding="utf-8")
            self.assertEqual(md.count("why this technique:"), 2)                  # one per kind, not one per finding
            self.assertEqual(md.count("common practice:"), 2)
            self.assertEqual(md.count("more like this"), 0)
            self.assertNotIn("decision: [ ] approve", md)
            self.assertIn("## Why these fixes", md)
            self.assertLess(md.index("## Why these fixes"), md.index("## Items"))
            for r in rows:                                                       # every item is still there, with its own facts
                self.assertIn(f"`{r['id']}`", md)
                self.assertIn(r["where"], md)
            item = next(b for b in md.split("### ")[1:] if "`smooth-1`" in b)
            self.assertIn("proposed fix: add a 4 ms fade", item)
            self.assertNotIn("why this technique", item)
            self.assertNotIn("confidence", item)                                  # the kind's usual figure is not repeated
            old_style = len(rows) * 560                                           # what the five repeated lines cost per item
            self.assertLess(len(md), len(rows) * 900 + old_style // 4)

    def test_show_prints_the_item_and_its_kinds_explanation(self):
        from hypnomix.workflow import scan as S
        with tempfile.TemporaryDirectory() as td:
            home, od = Path(td) / "home", Path(td) / "scan"
            od.mkdir()
            self._many(od, 6)
            hx("scan", "--merge", od, home=home)
            code, out = hx("fix", od, "--show", "smooth-2", home=home)
            self.assertEqual(code, 0, out)
            self.assertIn("click at the start of a clip", out)
            self.assertIn("why this technique:", out)
            self.assertIn("confidence: 85% for this kind", out)


class CachesStayUnderTheHypnomixHome(unittest.TestCase):
    def test_audio_features_are_cached_and_a_second_ask_is_a_read(self):
        from hypnomix.session import names as N
        with tempfile.TemporaryDirectory() as td:
            old = os.environ.get("HYPNOMIX_HOME")
            os.environ["HYPNOMIX_HOME"] = td
            try:
                t = np.arange(SR * 3) / SR
                y = (0.3 * np.sin(2 * np.pi * 220 * t) * ((t % 1) < 0.5)).astype(np.float32)
                h0, m0 = N.FEATURES_STATS["hits"], N.FEATURES_STATS["misses"]
                a = N.audio_features(y, SR)
                b = N.audio_features(y.astype(np.float64), SR)                  # the same audio read another way
                c = N.audio_features(np.concatenate([y, np.zeros(4000, np.float32)]), SR)   # padded with silence
                self.assertEqual(a, b)
                self.assertEqual(a, c)
                self.assertEqual((N.FEATURES_STATS["misses"] - m0, N.FEATURES_STATS["hits"] - h0), (1, 2))
                self.assertEqual(len(list((Path(td) / "cache" / "names").rglob("*.json"))), 1)
                d = N.audio_features(y * 0.5, SR)                                  # other audio: measured again
                self.assertEqual(N.FEATURES_STATS["misses"] - m0, 2)
                self.assertIsNotNone(d)
                self.assertEqual(N.audio_features(y, SR, cache=False)["active_s"], a["active_s"])
            finally:
                if old is None:
                    os.environ.pop("HYPNOMIX_HOME", None)
                else:
                    os.environ["HYPNOMIX_HOME"] = old

    def test_a_cut_off_cache_file_is_measured_again(self):
        from hypnomix.session import names as N
        with tempfile.TemporaryDirectory() as td:
            old = os.environ.get("HYPNOMIX_HOME")
            os.environ["HYPNOMIX_HOME"] = td
            try:
                y = (0.2 * np.sin(2 * np.pi * 110 * np.arange(SR * 2) / SR)).astype(np.float32)
                a = N.audio_features(y, SR)
                f = next((Path(td) / "cache" / "names").rglob("*.json"))
                f.write_text('{"features": {"active', encoding="utf-8")
                self.assertEqual(N.audio_features(y, SR), a)
            finally:
                if old is None:
                    os.environ.pop("HYPNOMIX_HOME", None)
                else:
                    os.environ["HYPNOMIX_HOME"] = old

    def test_with_hypnomix_home_set_nothing_is_written_under_the_real_home(self):
        with tempfile.TemporaryDirectory() as td:
            real_home, hh = Path(td) / "realhome", Path(td) / "hh"
            real_home.mkdir()
            wav = Path(td) / "tone.wav"
            t = np.arange(SR * 3) / SR
            sf.write(str(wav), (0.3 * np.sin(2 * np.pi * 220 * t) * ((t % 1) < 0.5)).astype(np.float32), SR)
            code = (
                "import numpy as np, soundfile as sf\n"
                "from hypnomix.core import pitch\n"
                "from hypnomix.session import names, render\n"
                f"pitch.track({str(wav)!r})\n"
                f"y, sr = sf.read({str(wav)!r}, dtype='float32')\n"
                "names.audio_features(y, sr)\n"
                "render.cache_put('ab' + '0' * 62, np.zeros(10, dtype=np.float32))\n")
            env = dict(os.environ, HOME=str(real_home), HYPNOMIX_HOME=str(hh), PYTHONPATH=str(ROOT))
            env.pop("HYPNOMIX_RENDER_CACHE", None)
            r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=td, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(list(real_home.iterdir()), [])                       # not even an empty ~/.hypnomix
            for sub in ("pitch", "names", "render"):
                self.assertTrue(list((hh / "cache" / sub).rglob("*.*")), sub)

    def test_the_render_cache_variable_still_wins(self):
        from hypnomix.session import render
        with tempfile.TemporaryDirectory() as td:
            old = os.environ.get("HYPNOMIX_RENDER_CACHE")
            os.environ["HYPNOMIX_RENDER_CACHE"] = td
            try:
                self.assertEqual(render.cache_dir(), Path(td))
            finally:
                if old is None:
                    os.environ.pop("HYPNOMIX_RENDER_CACHE", None)
                else:
                    os.environ["HYPNOMIX_RENDER_CACHE"] = old


class ParallelChecks(unittest.TestCase):
    def test_per_file_checks_run_side_by_side_and_keep_their_order(self):
        from hypnomix.workflow import scan as S
        with tempfile.TemporaryDirectory() as td:
            old = os.environ.get("HYPNOMIX_HOME")
            os.environ["HYPNOMIX_HOME"] = td
            try:
                rng = np.random.default_rng(3)
                files = []
                for i in range(3):
                    t = np.arange(SR * 2) / SR
                    y = 0.3 * np.sin(2 * np.pi * (110 + 40 * i) * t) + 0.002 * rng.standard_normal(len(t))
                    p = Path(td) / f"Take {i}.wav"
                    sf.write(str(p), np.clip(y * (6 if i == 0 else 1), -1, 1), SR, subtype="PCM_24")
                    files.append(p)
                (Path(td) / "Bad.wav").write_text("not audio", encoding="utf-8")
                files.append(Path(td) / "Bad.wav")
                got = S.measure_files(files, 3)
                self.assertEqual([p.name for p, _ in got], [f.name for f in files])
                self.assertIn("clipped", [k for k, *_ in got[0][1][0]])
                self.assertEqual(got[-1][1][0][0][0], "unreadable")              # an unreadable file is a finding, not a crash
                self.assertEqual(S.parallel_map(lambda x: x * 2, [1, 2, 3], 2), [2, 4, 6])
                S.warm_features(files[:3], 2)                                      # measured once, ahead of the groups
                from hypnomix.session import names as N
                self.assertGreaterEqual(len(list((Path(td) / "cache" / "names").rglob("*.json"))), 3)
            finally:
                if old is None:
                    os.environ.pop("HYPNOMIX_HOME", None)
                else:
                    os.environ["HYPNOMIX_HOME"] = old


class Ports(unittest.TestCase):
    def test_probe_and_app_ports_come_from_the_environment(self):
        from hypnomix.app import probe as PR, device as D
        from hypnomix.reaper import review as RR
        keep = {k: os.environ.get(k) for k in ("HYPNOMIX_PROBE_PORT", "HYPNOMIX_PORT")}
        try:
            os.environ.pop("HYPNOMIX_PROBE_PORT", None)
            os.environ.pop("HYPNOMIX_PORT", None)
            self.assertEqual((PR.probe_port(), PR.app_port(), D.app_port(), RR.app_port()), (8792, 8791, 8791, 8791))
            os.environ["HYPNOMIX_PROBE_PORT"], os.environ["HYPNOMIX_PORT"] = "9102", "9101"
            self.assertEqual((PR.probe_port(), PR.app_port(), D.app_port(), RR.app_port()), (9102, 9101, 9101, 9101))
            self.assertEqual(RR.app_port(9300), 9300)                                   # --port still wins
            os.environ["HYPNOMIX_PORT"] = "not a port"
            self.assertEqual(PR.app_port(), 8791)
        finally:
            for k, v in keep.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_generated_devices_use_the_ports(self):
        from hypnomix.app import probe as PR, device as D
        blank = {"patcher": {"boxes": [{"box": {"id": "obj-1", "maxclass": "newobj", "text": "plugin~"}},
                                       {"box": {"id": "obj-2", "maxclass": "newobj", "text": "plugout~"}},
                                       {"box": {"id": "obj-6", "maxclass": "live.comment", "text": "Build your Audio Effect here"}}],
                             "lines": [{"patchline": {"destination": ["obj-2", 0], "source": ["obj-1", 0]}}],
                             "openinpresentation": 0, "devicewidth": 0.0}}
        keep = {k: os.environ.get(k) for k in ("HYPNOMIX_PROBE_PORT", "HYPNOMIX_PORT")}
        os.environ["HYPNOMIX_PROBE_PORT"], os.environ["HYPNOMIX_PORT"] = "9102", "9101"
        try:
            with tempfile.TemporaryDirectory() as td:
                tpl = Path(td) / "Max Audio Effect.amxd"
                D.write_amxd(tpl, b"ampf\x04\x00\x00\x00aaaameta\x04\x00\x00\x00\x00\x00\x00\x00", blank)
                out = D.build(Path(td) / "review", tpl)
                self.assertIn("127.0.0.1:9101", (out / "hypnomix_device.js").read_text(encoding="utf-8"))
                out = PR.build(Path(td) / "probe", tpl)
                self.assertIn("9101", (out / "hypnomix_probe.js").read_text(encoding="utf-8"))
                self.assertIn("9101", (out / "hypnomix_master.js").read_text(encoding="utf-8"))
                _, patch = D.read_amxd(out / "HypnomixProbe.amxd")
                self.assertIn("udpsend 127.0.0.1 9102", [b["box"].get("text") for b in patch["patcher"]["boxes"]])
        finally:
            for k, v in keep.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_a_busy_probe_port_says_which_port_and_how_to_change_it(self):
        import socket
        from hypnomix.app import probe as PR
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        keep = os.environ.get("HYPNOMIX_PROBE_PORT")
        os.environ["HYPNOMIX_PROBE_PORT"] = str(port)
        try:
            with self.assertRaises(OSError) as cm:
                PR.Hub().start()
            self.assertIn(f"port {port}", str(cm.exception))
            self.assertIn("HYPNOMIX_PROBE_PORT", str(cm.exception))
            self.assertIn("HYPNOMIX_PROBE_PORT", PR.port_in_use_text(port, "x"))
        finally:
            s.close()
            if keep is None:
                os.environ.pop("HYPNOMIX_PROBE_PORT", None)
            else:
                os.environ["HYPNOMIX_PROBE_PORT"] = keep


if __name__ == "__main__":
    unittest.main()
