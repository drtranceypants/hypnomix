"""Human oversight: amounts, grouped decisions, the question budget, teach mode, collaborators, history and undo.

Everything is synthesised in a temporary folder (a scratch HYPNOMIX_HOME too): no audio or sets live in the repo.
"""
import gzip, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from tests.test_workflow import make_set

SR = 44100


def hx(*args, home):
    env = dict(os.environ, HYPNOMIX_HOME=str(home), HYPNOMIX_RENDER_CACHE=str(Path(home) / "cache"))
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


def py(mod, *args, home):
    env = dict(os.environ, HYPNOMIX_HOME=str(home), HYPNOMIX_RENDER_CACHE=str(Path(home) / "cache"))
    r = subprocess.run([sys.executable, "-m", mod, *map(str, args)], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


def clicky_set(td):
    """A set whose two clips start and end on loud samples with their fades switched off: four clicks."""
    td = Path(td)
    t = np.arange(SR * 8) / SR
    sf.write(str(td / "take.wav"), 0.4 * np.cos(2 * np.pi * 220 * t), SR, subtype="PCM_24")

    def clip(i, s, e, off):
        return (f'<AudioClip Id="{i}" Time="{s}"><Name Value="take"/><CurrentStart Value="{s}"/><CurrentEnd Value="{e}"/>'
                f'<Loop><LoopStart Value="{off}"/><LoopEnd Value="{off + e - s}"/><LoopOn Value="false"/><StartRelative Value="0"/></Loop>'
                f'<IsWarped Value="false"/><WarpMarkers><WarpMarker Id="0" SecTime="0" BeatTime="0"/><WarpMarker Id="1" SecTime="1" BeatTime="2"/></WarpMarkers>'
                f'<SampleVolume Value="1"/><Disabled Value="false"/>'
                f'<Fades><FadeInLength Value="0"/><FadeOutLength Value="0"/><IsDefaultFadeIn Value="false"/><IsDefaultFadeOut Value="false"/></Fades>'
                f'<SampleRef><FileRef><Path Value="{td / "take.wav"}"/><RelativePath Value="take.wav"/></FileRef></SampleRef></AudioClip>')
    mixer = lambda base, vol="1": (f'<Mixer><Volume><Manual Value="{vol}"/><AutomationTarget Id="{base}"/></Volume>'
                                   f'<Pan><Manual Value="0"/><AutomationTarget Id="{base + 1}"/></Pan>'
                                   f'<Speaker><Manual Value="true"/><AutomationTarget Id="{base + 2}"/></Speaker><Sends/></Mixer>')
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="12.0_12049" Creator="Ableton Live 12.0"><LiveSet><NextPointeeId Value="100"/>
<Tracks><AudioTrack Id="1"><Name><EffectiveName Value="Vox"/></Name><AutomationEnvelopes><Envelopes/></AutomationEnvelopes>
 <DeviceChain>{mixer(10)}<MainSequencer><Sample><ArrangerAutomation><Events>{clip(0, 1.0, 3.0, 0.5)}{clip(1, 5.0, 7.0, 1.3)}
 </Events></ArrangerAutomation></Sample></MainSequencer><DeviceChain><Devices/></DeviceChain></DeviceChain></AudioTrack></Tracks>
<MainTrack><Name><EffectiveName Value="Main"/></Name><AutomationEnvelopes><Envelopes/></AutomationEnvelopes>
 <DeviceChain>{mixer(30)}<Mixer2/><DeviceChain><Devices/></DeviceChain></DeviceChain><Tempo><Manual Value="120"/></Tempo></MainTrack>
</LiveSet></Ableton>'''
    with gzip.open(td / "Song.als", "wb") as f:
        f.write(xml.encode())
    return td / "Song.als"


def fake_scan(sd, als, findings):
    sd.mkdir(parents=True, exist_ok=True)
    for n, f in enumerate(findings, 1):
        f.setdefault("n", n)
    (sd / "findings.json").write_text(json.dumps({"set": str(als), "notes": [], "findings": findings}))
    (sd / "scan.json").write_text(json.dumps({"set": str(als), "mode": "set", "set_mtime": Path(als).stat().st_mtime}))


def F(i, kind="click", size_db=8, sev="medium", track="Vox", tool="smooth", applies="set"):
    return dict(id=f"{tool}-{i}", tool=tool, kind=kind, severity=sev, track=track, where=f"{i}.1.00",
                problem=f"clip starts on a -{size_db} dBFS sample, no fade", fix="5 ms fade", applies=applies)


class Amount(unittest.TestCase):
    def test_parse_and_scaling_table(self):
        from hypnomix.workflow import oversight as O
        self.assertEqual(O.parse_decision("approve@60"), ("approve", 60))
        self.assertEqual(O.parse_decision("skip"), ("skip", None))
        for bad in ("approve@150", "approve@x", "delete"):
            with self.assertRaises(ValueError):
                O.parse_decision(bad)
        self.assertEqual(O.amount_of({}), 100)
        self.assertEqual(O.amount_of({"amount": 40}), 40)
        self.assertEqual(O.amount_flags("timing", 50), ["--strength", "0.5000"])
        self.assertEqual(O.amount_flags("smooth", 100), [])
        self.assertTrue(O.scalable(dict(tool="devices"))[0])
        ok, why = O.scalable(dict(tool="name"))
        self.assertFalse(ok)
        self.assertIn("all or nothing", why)
        # a kind that can't scale: any amount above 0 is 100, and 0 is nothing
        self.assertEqual(O.effective_amount(dict(tool="order"), {"amount": 30}), 100)
        self.assertEqual(O.effective_amount(dict(tool="order"), {"amount": 0}), 0)
        self.assertEqual(O.effective_amount(dict(tool="edges"), {"amount": 30}), 30)

    def test_blend_moves_numbers_part_of_the_way(self):
        from hypnomix.workflow import oversight as O
        import xml.etree.ElementTree as ET
        with tempfile.TemporaryDirectory() as td:
            a = make_set(Path(td) / "a.als")
            b = make_set(Path(td) / "b.als", drive="4", fade_out=0.02)
            out = Path(td) / "c.als"
            scaled, kept = O.blend(a, b, out, 0.5)
            self.assertEqual(scaled, 2)
            r = ET.fromstring(gzip.open(out).read())
            self.assertAlmostEqual(float(r.find(".//Saturator/Drive/Manual").get("Value")), 11.0)
            self.assertAlmostEqual(float(r.find(".//Fades/FadeOutLength").get("Value")), 0.01)
            # gains move in dB: halfway from 0 dB to -12 dB is -6 dB
            old = ET.fromstring('<a><SampleVolume Value="1"/><Mode Value="0"/></a>')
            new = ET.fromstring('<a><SampleVolume Value="0.251189"/><Mode Value="2"/></a>')
            O.blend_trees(old, new, 0.5)
            self.assertAlmostEqual(20 * np.log10(float(new.find("SampleVolume").get("Value"))), -6.0, places=2)
            self.assertEqual(new.find("Mode").get("Value"), "2")                # a switch is all or nothing

    def test_fix_scales_smooth_fades(self):
        with tempfile.TemporaryDirectory() as td:
            td, home = Path(td), Path(td) / "home"
            als = clicky_set(td)
            sd = td / "scan"
            code, out = hx("scan", als, "--only", "clips", "--out", sd, home=home)
            self.assertEqual(code, 0, out)
            ids = [f["id"] for f in json.loads((sd / "findings.json").read_text())["findings"] if f["tool"] == "smooth"]
            self.assertEqual(len(ids), 4, ids)
            code, out = hx("fix", sd, "--decide", "smooth-1=approve@50,smooth-3=approve", "--as", "Ana", home=home)
            self.assertEqual(code, 0, out)
            dec = json.loads((sd / "decisions.json").read_text())
            self.assertEqual((dec["smooth-1"]["amount"], dec["smooth-1"]["by"]), (50, "Ana"))
            code, out = hx("fix", sd, "--approved", "--out", "Song (fixed).als", home=home)
            self.assertEqual(code, 0, out)
            from hypnomix.session import diff as D
            rows = D.diff(als, td / "Song (fixed).als")
            fades = sorted(r["after"] for r in rows if r["what"].startswith("fade in"))
            self.assertEqual(fades, ["2 ms", "5 ms"])                         # 50% of a 5 ms fade, and a full one
            # history: logged, with the amount; undo writes a NEW set equal to the input
            h = json.loads((sd / "history" / "history.json").read_text())
            self.assertEqual(h["versions"][0]["approved"][0]["amount"], 50)
            before = {p.name for p in td.glob("*.als")}
            code, out = py("hypnomix.workflow.history", sd, "--undo", "1", home=home)
            self.assertEqual(code, 0, out)
            made = {p.name for p in td.glob("*.als")} - before
            self.assertEqual(len(made), 1)
            self.assertEqual(D.diff(als, td / made.pop()), [])
            self.assertTrue((td / "Song (fixed).als").exists())                # nothing deleted
            code, out = py("hypnomix.workflow.history", sd, "--diff", "0", "1", home=home)
            self.assertIn("fade in", out)
            code, out = py("hypnomix.workflow.history", sd, "--undo-item", "smooth-1", home=home)
            self.assertEqual(code, 0, out)
            rebuilt = td / "Song (v1 without smooth-1).als"
            self.assertTrue(rebuilt.exists(), out)
            rows = D.diff(als, rebuilt)
            self.assertEqual([r["after"] for r in rows if r["what"].startswith("fade in")], ["5 ms"])
            h = json.loads((sd / "history" / "history.json").read_text())
            self.assertEqual([v["kind"] for v in h["versions"]], ["fix", "undo", "undo-item"])


class Grouped(unittest.TestCase):
    def test_like_matches_kind_role_and_size(self):
        from hypnomix.workflow import oversight as O
        fs = [F(1, size_db=10), F(2, size_db=12), F(3, size_db=30), F(4, kind="cut"), F(5, size_db=9, sev="high"),
              F(6, size_db=11, track="Kick"), F(7, size_db=9)]
        role = {"Vox": "Lead", "Kick": "Drums"}
        got = [f["id"] for f in O.like(fs, {"smooth-7": {"decision": "skip"}}, fs[0], band=0.5, role_of=role)]
        self.assertEqual(got, ["smooth-2"])        # not 30 dB, not a cut, not high, not drums, not already decided

    def test_decide_like_dry_run_then_record_and_override(self):
        with tempfile.TemporaryDirectory() as td:
            td, home = Path(td), Path(td) / "home"
            als = make_set(td / "Song.als")
            sd = td / "scan"
            fake_scan(sd, als, [F(1, size_db=10), F(2, size_db=12), F(3, size_db=30)])
            code, out = hx("fix", sd, "--decide-like", "smooth-1=approve@70", "--dry-run", home=home)
            self.assertEqual(code, 0, out)
            self.assertIn("smooth-2", out)
            self.assertNotIn("smooth-3", out.split("dry run")[0].split("undecided finding(s)")[1])
            self.assertFalse((sd / "decisions.json").exists())
            code, out = hx("fix", sd, "--decide-like", "smooth-1=approve@70", home=home)
            dec = json.loads((sd / "decisions.json").read_text())
            self.assertEqual(sorted(dec), ["smooth-1", "smooth-2"])
            self.assertEqual(dec["smooth-2"]["via"], "like:smooth-1")
            self.assertEqual(dec["smooth-2"]["amount"], 70)
            hx("fix", sd, "--decide", "smooth-2=skip", home=home)                   # an individual decision wins
            hx("fix", sd, "--decide-like", "smooth-1=approve", home=home)
            self.assertEqual(json.loads((sd / "decisions.json").read_text())["smooth-2"]["decision"], "skip")

    def test_review_page_record_like(self):
        from hypnomix.workflow import review as R
        with tempfile.TemporaryDirectory() as td:
            sd = Path(td)
            (sd / "findings.json").write_text(json.dumps({"set": "x", "findings": [F(1), F(2), F(3, kind="cut")]}))
            self.assertEqual(R.record_like(sd, "smooth-1", "approve", 40), ["smooth-1", "smooth-2"])
            e = R.record(sd, "smooth-3", "approve", "", amount=25, by="Bo")
            self.assertEqual((e["amount"], e["by"]), (25, "Bo"))
            with self.assertRaises(ValueError):
                R.record(sd, "smooth-3", "approve", "", amount=500)


class Budget(unittest.TestCase):
    def test_budget_keeps_high_and_protected_and_batches_the_rest(self):
        from hypnomix.workflow import oversight as O
        fs = [F(1, sev="high"), F(2, sev="low"), F(3, sev="low"), F(4, sev="medium"), F(5, sev="low"),
              dict(F(6, sev="low"), protected=True), dict(F(7, sev="info"), applies="info")]
        ask, batch, info = O.budget(fs, 2)
        ids = lambda xs: [f["id"] for f in xs]
        self.assertIn("smooth-1", ids(ask))
        self.assertIn("smooth-6", ids(ask))                    # protected: always asked
        self.assertEqual(len(ask), 2)
        self.assertEqual(sorted(ids(batch)), ["smooth-2", "smooth-3", "smooth-4", "smooth-5"])
        self.assertEqual(ids(info), ["smooth-7"])
        ask, batch, _ = O.budget(fs, None)
        self.assertEqual(batch, [])
        sg = O.batch_suggestions(batch or fs[1:5], prefs={})
        self.assertTrue(all(s["decision"] in ("approve", "skip") for s in sg))

    def test_review_md_and_page_show_budget_teach_and_lines(self):
        with tempfile.TemporaryDirectory() as td:
            od, home = Path(td) / "scan", Path(td) / "home"
            od.mkdir()
            home.mkdir()
            (home / "preferences.json").write_text(json.dumps({"review": {"max_questions": 2}}))
            (home / "taste.json").write_text(json.dumps({"profile": {"harmonies": {"lead_margin": 3.5}}}))
            fs = [F(i, sev="low", size_db=8 + i) for i in range(1, 7)] + \
                [dict(id="harmony-1", tool="voices", kind="harmony-balance", severity="low", track="(vocal parts)",
                      where="", problem="p", fix="f", applies="audio")]
            (od / "clips.json").write_text(json.dumps({"group": "clips", "set": "S.als", "findings": fs, "notes": []}))
            code, out = hx("scan", "--merge", od, home=home)
            self.assertEqual(code, 0, out)
            md = (od / "REVIEW.md").read_text()
            self.assertIn("question budget: 2", md)
            self.assertIn("Low priority: batch", md)
            self.assertIn("why this technique:", md)
            self.assertIn("common practice:", md)
            self.assertIn("confidence:", md)
            self.assertIn("about 3.5 dB under the lead", md)              # "you usually" from taste.json
            code, out = hx("review", od, home=home)
            page = (od / "REVIEW.html").read_text()
            self.assertIn("ovBatchHTML", page)
            self.assertIn('"max": 2', page)
            self.assertNotIn("</script><script", page)
            (home / "preferences.json").write_text(json.dumps({"review": {"teach": "off"}}))
            hx("scan", "--merge", od, home=home)
            self.assertNotIn("why this technique:", (od / "REVIEW.md").read_text())

    def test_usually_handles_missing_files(self):
        from hypnomix.workflow import oversight as O
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(O.usually(F(1), home=td, prefs={}), "")
            (Path(td) / "library.json").write_text(json.dumps({"kinds": {"smooth/click": {"approve": 5, "skip": 1}}}))
            self.assertIn("approved 5 of 6", O.usually(F(1), home=td, prefs={}))
            (Path(td) / "library.json").write_text("not json")
            self.assertEqual(O.usually(F(1), home=td, prefs={}), "")

    def test_confidence(self):
        from hypnomix.workflow import oversight as O
        self.assertEqual(O.confidence(dict(tool="name", confidence=0.42))[0], 0.42)
        self.assertEqual(O.confidence(dict(tool="edges", sure=True)), (0.85, "measured"))
        self.assertEqual(O.confidence(dict(tool="smooth", kind="click"))[1], "default for this kind")


class Teach(unittest.TestCase):
    def test_every_tool_scan_can_emit_has_words(self):
        from hypnomix.workflow import teach as T
        tools = ["smooth", "edges", "timing", "tune", "key", "vocalign", "cliplevel", "duck", "voices", "distortion",
                 "sidechain", "audit", "measure", "qc", "translate", "sections", "match", "dehiss", "intent", "refs",
                 "name", "order", "tidy", "devices", "masking", "align", "recording", "cleanup", "deess", "breaths",
                 "prep", "automix", "master", "motion", "borrow", "structure", "profile"]
        for t in tools:
            self.assertNotEqual(T.why(dict(tool=t, kind="x")), T.FALLBACK[0], t)
        self.assertIn("click", T.why(dict(tool="smooth", kind="click")))
        self.assertTrue(T.practice(dict(tool="measure", kind="true-peak")).startswith("-1 dBTP"))

    def test_profile_findings_have_their_own_words_and_confidence(self):
        from hypnomix.workflow import oversight as O, teach as T
        f = dict(tool="profile", kind="own-range")
        self.assertIn("Your own finished songs", T.why(f))
        self.assertNotEqual(T.practice(f), T.FALLBACK[1])
        self.assertEqual(O.confidence(f), (0.45, "default for this kind"))


class Collaborators(unittest.TestCase):
    def test_export_merge_conflicts_and_settle(self):
        from hypnomix.workflow import oversight as O
        with tempfile.TemporaryDirectory() as td:
            mine, theirs = Path(td) / "mine", Path(td) / "theirs"
            fs = [F(1), F(2), F(3), F(4)]
            for d in (mine, theirs):
                d.mkdir()
                (d / "findings.json").write_text(json.dumps({"set": "/x/Song.als", "findings": fs}))
            O.save_decisions(mine, {"smooth-1": O.entry("approve", by="Owner"), "smooth-2": O.entry("skip", by="Owner"),
                                    "smooth-4": "approve"})
            O.save_decisions(theirs, {"smooth-1": O.entry("approve", by="Cy"), "smooth-2": O.entry("approve", "too clicky", 60, by="Cy"),
                                      "smooth-3": O.entry("approve", by="Cy"), "smooth-4": O.entry("skip", by="Cy")})
            O.add_note(theirs, "smooth-2", "listen here", "33.2", by="Cy")
            O.add_note(theirs, "smooth-3", "and here", "1:23.5", by="Cy")
            with self.assertRaises(ValueError):
                O.add_note(theirs, "smooth-3", "x", "soon")
            exp = Path(td) / "cy.json"
            O.export(theirs, exp, by="Cy")
            r = O.merge(mine, exp)
            dec = O.load_decisions(mine)
            self.assertEqual(r["adopted"], ["smooth-3"])
            self.assertEqual(r["same"], ["smooth-1"])
            self.assertEqual(sorted(c[0] for c in r["conflicts"]), ["smooth-2", "smooth-4"])
            self.assertEqual(dec["smooth-2"]["decision"], "skip")                 # the owner's stays
            self.assertEqual(dec["smooth-2"]["conflicts"][0]["amount"], 60)
            self.assertEqual(dec["smooth-4"]["decision"], "approve")              # old plain-string entry kept
            notes = O.load_notes(mine)
            self.assertEqual(notes["smooth-2"][0]["bar"], "33.2")
            self.assertEqual(notes["smooth-3"][0]["sec"], 83.5)
            O.merge(mine, exp)                                                    # merging twice adds nothing
            self.assertEqual(len(O.load_notes(mine)["smooth-2"]), 1)
            self.assertEqual(len(O.load_decisions(mine)["smooth-2"]["conflicts"]), 1)
            e = O.settle(mine, "smooth-2", "theirs", by="Owner")
            self.assertEqual((e["decision"], e["amount"]), ("approve", 60))
            e = O.settle(mine, "smooth-4", "mine")
            self.assertNotIn("conflicts", e)
            with self.assertRaises(ValueError):
                O.settle(mine, "smooth-1", "mine")

    def test_merge_matches_findings_by_what_they_are(self):
        from hypnomix.workflow import oversight as O
        with tempfile.TemporaryDirectory() as td:
            mine, theirs = Path(td) / "mine", Path(td) / "theirs"
            for d, fs in ((mine, [F(1), F(2)]), (theirs, [dict(F(2), id="smooth-9")])):
                d.mkdir()
                (d / "findings.json").write_text(json.dumps({"set": "S.als", "findings": fs}))
            O.save_decisions(theirs, {"smooth-9": O.entry("skip", by="Cy")})
            O.export(theirs, Path(td) / "x.json", by="Cy")
            r = O.merge(mine, Path(td) / "x.json")
            self.assertEqual(r["adopted"], ["smooth-2"])                         # same finding, other number


if __name__ == "__main__":
    unittest.main()
