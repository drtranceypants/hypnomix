"""Tests for the review workflow: preferences, scan (folder), fix safety, plans, check, diff, ab, review.

Everything is synthesised in a temporary folder: no audio or sets live in the repo. Run from the repo root:
    python -m unittest discover -s tests -v
"""
import gzip, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100


def hx(*args, home=None):
    env = dict(os.environ)
    if home:
        env["HYPNOMIX_HOME"] = str(home)
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True, env=env, encoding="utf-8")
    return r.returncode, r.stdout + r.stderr


def tone(seconds=6.0, f=220.0, amp=0.3, gate=True):
    t = np.arange(int(SR * seconds)) / SR
    env = ((t % 2) < 1).astype(float) if gate else 1.0
    return amp * np.sin(2 * np.pi * f * t) * env


def make_set(path, fade_out=0.0, extra_target_id=None, warp=((0.0, 0.0), (1.0, 2.0)), drive="18"):
    """A minimal Live-shaped set: one audio track with one clip, a Saturator, and a main track."""
    wm = "".join(f'<WarpMarker Id="{i}" SecTime="{s}" BeatTime="{b}"/>' for i, (s, b) in enumerate(warp))
    dup = f'<AutomationTarget Id="{extra_target_id}"/>' if extra_target_id is not None else ""
    mixer = lambda base: (f'<Mixer><Volume><Manual Value="1"/><AutomationTarget Id="{base}"/></Volume>'
                          f'<Pan><Manual Value="0"/><AutomationTarget Id="{base + 1}"/></Pan>'
                          f'<Speaker><Manual Value="true"/><AutomationTarget Id="{base + 2}"/></Speaker><Sends/></Mixer>')
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="12.0_12049" Creator="Ableton Live 12.0"><LiveSet>
<NextPointeeId Value="100"/>
<Tracks><AudioTrack Id="1"><Name><EffectiveName Value="Vox"/></Name>
 <AutomationEnvelopes><Envelopes/></AutomationEnvelopes>
 <DeviceChain>{mixer(10)}
  <MainSequencer><Sample><ArrangerAutomation><Events>
   <AudioClip Id="0" Time="0"><Name Value="take"/><CurrentStart Value="0"/><CurrentEnd Value="8"/>
    <Loop><LoopStart Value="0"/><LoopEnd Value="8"/><LoopOn Value="false"/><StartRelative Value="0"/></Loop>
    <IsWarped Value="true"/><WarpMarkers>{wm}</WarpMarkers><SampleVolume Value="1"/><Disabled Value="false"/>
    <Fades><FadeInLength Value="0"/><FadeOutLength Value="{fade_out}"/></Fades>
    <SampleRef><FileRef><Path Value=""/><RelativePath Value="missing.wav"/></FileRef></SampleRef>
   </AudioClip></Events></ArrangerAutomation></Sample></MainSequencer>
  <DeviceChain><Devices><Saturator Id="0"><On><Manual Value="true"/><AutomationTarget Id="20"/></On>
   <Drive><Manual Value="{drive}"/><AutomationTarget Id="21"/>{dup}</Drive></Saturator></Devices></DeviceChain>
 </DeviceChain></AudioTrack></Tracks>
<MainTrack><Name><EffectiveName Value="Main"/></Name><AutomationEnvelopes><Envelopes/></AutomationEnvelopes>
 <DeviceChain>{mixer(30)}<Mixer2/><DeviceChain><Devices/></DeviceChain></DeviceChain>
 <Tempo><Manual Value="120"/></Tempo></MainTrack>
</LiveSet></Ableton>'''
    with gzip.open(path, "wb") as f:
        f.write(xml.encode())
    return path


class Prefs(unittest.TestCase):
    def test_set_show_and_habit(self):
        from hypnomix.workflow import prefs as P
        with tempfile.TemporaryDirectory() as td:
            code, out = hx("prefs", "set", "targets.lufs=-16", "protect.tracks=Lead Vox,Strings", home=td)
            self.assertEqual(code, 0, out)
            d = json.loads((Path(td) / "preferences.json").read_text(encoding="utf-8"))
            self.assertEqual(d["targets"]["lufs"], -16)
            self.assertEqual(d["protect"]["tracks"], ["Lead Vox", "Strings"])
            code, out = hx("prefs", "set", "nonsense=1", home=td)
            self.assertNotEqual(code, 0)
        f = dict(tool="smooth", kind="click", severity="low")
        prefs = {"learned": {P.habit_key(f): {"skip": 9, "approve": 1}}}
        self.assertIn("skipped 9 of 10", P.habit(prefs, f))
        self.assertEqual(P.habit({"learned": {P.habit_key(f): {"skip": 2}}}, f), "")   # too few to say anything

    def test_questions_are_json(self):
        code, out = hx("prefs", "questions", home=tempfile.mkdtemp())
        keys = [q["key"] for q in json.loads(out)]
        self.assertIn("protect.tracks", keys)
        self.assertIn("targets.lufs", keys)


class FixLogic(unittest.TestCase):
    def test_rematch_never_swaps_neighbours(self):
        from hypnomix.workflow import fix
        f = lambda i, where: dict(id=f"smooth-{i}", tool="smooth", track="Vox", kind="click", where=where)
        approved = [f(2, "5.1.00"), f(3, "9.1.00")]
        # finding 1 was fixed in an earlier step, so every id moved down by one
        now = [f(1, "5.1.00"), f(2, "9.1.00"), f(3, "13.1.00")]
        ids, skipped = fix.rematch(approved, now)
        self.assertEqual(ids, ["smooth-1", "smooth-2"])
        self.assertEqual(skipped, [])
        ids, skipped = fix.rematch([f(9, "77.1.00")], now)        # gone: skip, never guess
        self.assertEqual(ids, [])
        self.assertEqual(len(skipped), 1)

    def test_gates(self):
        with tempfile.TemporaryDirectory() as td:
            sd = Path(td)
            als = make_set(sd / "Song.als")
            finding = dict(id="smooth-1", n=1, tool="smooth", kind="click", severity="low", track="Vox",
                           where="1.1.00", problem="p", fix="f", applies="set", protected=True)
            (sd / "findings.json").write_text(json.dumps({"set": str(als), "notes": [], "findings": [finding]}), encoding="utf-8")
            (sd / "scan.json").write_text(json.dumps({"set": str(als), "mode": "set", "set_mtime": als.stat().st_mtime}), encoding="utf-8")
            code, out = hx("fix", sd, "--approve", "smooth-1", "--out", "New.als")
            self.assertNotEqual(code, 0)
            self.assertIn("protected", out)
            code, out = hx("fix", sd, "--decide", "smooth-1=skip")
            self.assertEqual(code, 0, out)
            code, out = hx("fix", sd, "--approve", "smooth-1", "--allow-protected", "--out", "New.als")
            self.assertIn("recorded as skip", out)
            hx("fix", sd, "--decide", "smooth-1=approve")
            code, out = hx("fix", sd, "--approved", "--allow-protected", "--out", "Song.als")
            self.assertIn("refusing to overwrite", out)
            os.utime(als, (als.stat().st_atime, als.stat().st_mtime + 60))      # saved again after the scan
            code, out = hx("fix", sd, "--approved", "--allow-protected", "--out", "New.als")
            self.assertNotEqual(code, 0)
            self.assertIn("saved again after the scan", out)
            self.assertFalse((sd / "New.als").exists())
            code, out = hx("fix", sd, "--approve", "nope-1")
            self.assertIn("unknown ids", out)


class CheckAndDiff(unittest.TestCase):
    def test_check_sound_and_broken(self):
        from hypnomix.session import check as C
        with tempfile.TemporaryDirectory() as td:
            good = make_set(Path(td) / "good.als")
            err, warn, facts = C.check(good)
            self.assertEqual(err, [])
            self.assertEqual(facts["audio_clips"], 1)
            err, _, _ = C.check(make_set(Path(td) / "dup.als", extra_target_id=21))
            self.assertTrue(any("duplicate" in e for e in err), err)
            err, _, _ = C.check(make_set(Path(td) / "high.als", extra_target_id=500))
            self.assertTrue(any("NextPointeeId" in e for e in err), err)
            err, _, _ = C.check(make_set(Path(td) / "warp.als", warp=((1.0, 2.0), (0.5, 1.0))))
            self.assertTrue(any("warp markers" in e for e in err), err)
            (Path(td) / "junk.als").write_bytes(b"not a set")
            err, _, _ = C.check(Path(td) / "junk.als")
            self.assertTrue(err)
            code, _ = hx("check", Path(td) / "dup.als")
            self.assertEqual(code, 1)

    def test_diff_reports_plain_changes(self):
        from hypnomix.session import diff as D
        with tempfile.TemporaryDirectory() as td:
            a = make_set(Path(td) / "a.als")
            b = make_set(Path(td) / "b.als", fade_out=0.02, drive="4")
            rows = D.diff(a, b)
            what = {r["what"]: r for r in rows}
            self.assertEqual(len(rows), 2, rows)
            self.assertEqual((what["Saturator: Drive"]["before"], what["Saturator: Drive"]["after"]), ("18", "4"))
            self.assertEqual(what["fade out (take)"]["after"], "10 ms")        # 0.02 beats at 120 BPM
            self.assertEqual(D.diff(a, a), [])


class FolderScan(unittest.TestCase):
    def test_scan_review_fix_on_recordings(self):
        with tempfile.TemporaryDirectory() as td:
            raw, sd, home = Path(td) / "raw", Path(td) / "scan", Path(td) / "home"
            raw.mkdir()
            rng = np.random.default_rng(1)
            noisy = tone() + 0.004 * rng.standard_normal(int(SR * 6)) + 0.01
            sf.write(str(raw / "Guitar noisy.wav"), noisy, SR, subtype="PCM_24")
            sf.write(str(raw / "Bass clipped.wav"), np.clip(5 * tone(f=110), -1, 1), SR, subtype="PCM_24")
            before = {p.name: p.read_bytes() for p in raw.iterdir()}
            code, out = hx("scan", raw, "--out", sd, home=home)
            self.assertEqual(code, 0, out)
            F = json.loads((sd / "findings.json").read_text(encoding="utf-8"))["findings"]
            kinds = {(f["track"], f["kind"]) for f in F}
            self.assertIn(("Bass clipped.wav", "clipped"), kinds)
            self.assertIn(("Guitar noisy.wav", "noise"), kinds)
            self.assertIn(("Guitar noisy.wav", "dc"), kinds)
            self.assertIn("Nothing has been changed", (sd / "REVIEW.md").read_text(encoding="utf-8"))
            dc = next(f for f in F if f["kind"] == "dc")
            code, out = hx("fix", sd, "--approve", dc["id"], home=home)
            self.assertEqual(code, 0, out)
            self.assertTrue(list((sd / "fixed").glob("*.wav")))
            self.assertEqual(before, {p.name: p.read_bytes() for p in raw.iterdir()})   # sources untouched
            code, out = hx("ab", sd, "--ids", dc["id"], home=home)
            self.assertEqual(code, 0, out)
            ab = json.loads((sd / "ab" / "ab.json").read_text(encoding="utf-8"))
            self.assertTrue((sd / "ab" / ab[dc["id"]]["a"]).exists())
            code, out = hx("review", sd, home=home)
            page = (sd / "REVIEW.html").read_text(encoding="utf-8")
            self.assertIn(dc["id"], page)
            self.assertNotIn("</script><script", page)

    def test_two_mics_phase(self):
        from hypnomix.workflow import scan
        t = np.arange(SR * 4) / SR
        k = (np.sin(2 * np.pi * 60 * t) * np.exp(-(t % 0.5) * 18) * 0.6)[:, None]
        d = int(0.0015 * SR)
        other = -0.5 * np.vstack([np.zeros((d, 1)), k[:-d]])
        F = scan.phase_findings([("Kick In", k), ("Kick Out", other), ("Guitar", k * 0.1)], SR)
        self.assertEqual(len(F), 1)
        self.assertIn("polarity is flipped", F[0]["problem"])
        self.assertIn("1.50 ms late", F[0]["problem"])
        self.assertIsNone(scan.pair_base("Guitar"))
        self.assertEqual(scan.pair_base("Snare Top"), scan.pair_base("snare_bottom"))


class Plans(unittest.TestCase):
    def test_prep_plan_then_only_approved_steps(self):
        with tempfile.TemporaryDirectory() as td:
            raw, sd, home = Path(td) / "raw", Path(td) / "plan", Path(td) / "home"
            raw.mkdir()
            rng = np.random.default_rng(2)
            src = raw / "Guitar.wav"
            sf.write(str(src), tone() + 0.004 * rng.standard_normal(int(SR * 6)) + 0.01, SR, subtype="PCM_24")
            original = src.read_bytes()
            code, out = hx("prep", raw, "--plan", sd, home=home)
            self.assertEqual(code, 0, out)
            F = json.loads((sd / "findings.json").read_text(encoding="utf-8"))["findings"]
            steps = {f["plan"]["step"] for f in F}
            self.assertIn("rumble", steps)
            self.assertIn("gain", steps)
            self.assertFalse(list(sd.glob("**/*.wav")))                     # a plan writes no audio
            rumble = next(f for f in F if f["plan"]["step"] == "rumble")
            code, out = hx("fix", sd, "--approve", rumble["id"], home=home)
            self.assertEqual(code, 0, out)
            made = list((sd / "fixed" / "prep").glob("*.wav"))
            self.assertEqual(len(made), 1)
            y0, _ = sf.read(str(src))
            y1, _ = sf.read(str(made[0]))
            self.assertLess(abs(float(np.mean(y1))), 1e-3)                  # DC gone
            rms = lambda y: float(np.sqrt(np.mean(np.square(y - np.mean(y)))))
            self.assertAlmostEqual(20 * np.log10(rms(y1) / rms(y0)), 0.0, delta=0.5)   # gain step NOT applied
            self.assertEqual(original, src.read_bytes())

    def test_master_only_runs_approved_stages(self):
        from hypnomix.engineer import master as M
        rng = np.random.default_rng(3)
        y = np.stack([tone(8, 110, 0.2, False) + 0.05 * rng.standard_normal(SR * 8),
                      tone(8, 110, 0.2, False) + 0.05 * rng.standard_normal(SR * 8)], axis=1)
        _, before, after, log = M.master(y, SR, only={"hpf"})
        self.assertEqual([what for what, _, _ in log], ["Subsonic clean-up"])
        self.assertAlmostEqual(after["lufs"], before["lufs"], delta=0.5)     # no limiter: loudness stays put


class ReviewAndAb(unittest.TestCase):
    def test_record_and_import(self):
        from hypnomix.workflow import review as R
        with tempfile.TemporaryDirectory() as td:
            sd = Path(td)
            (sd / "findings.json").write_text(json.dumps({"set": "x", "findings": [dict(id="a-1"), dict(id="a-2")]}), encoding="utf-8")
            R.record(sd, "a-1", "approve", "ok")
            with self.assertRaises(ValueError):
                R.record(sd, "zzz", "approve")
            with self.assertRaises(ValueError):
                R.record(sd, "a-2", "delete everything")
            (sd / "dl.json").write_text(json.dumps({"a-2": {"decision": "skip"}, "bogus": {"decision": "approve"}}), encoding="utf-8")
            R.import_file(sd, sd / "dl.json")
            dec = json.loads((sd / "decisions.json").read_text(encoding="utf-8"))
            self.assertEqual({k: v["decision"] for k, v in dec.items()}, {"a-1": "approve", "a-2": "skip"})

    def test_ab_helpers(self):
        from hypnomix.workflow import ab
        self.assertEqual(ab.beats_of("33.3.50", 4), 32 * 4 + 2 + 0.5)
        self.assertIsNone(ab.beats_of("1:23", 4))
        self.assertEqual(ab.secs_of("1:23.5"), 83.5)
        with tempfile.TemporaryDirectory() as td:
            a = (0.2 * np.sin(np.arange(SR) / 20)).astype(np.float32)
            row = ab.write_pair(Path(td), "x/1", a, a * 10 ** (-9 / 20), SR)
            self.assertEqual(row["matched_db"], 3.0)                         # matched, but never by more than 3 dB
            self.assertTrue((Path(td) / row["a"]).exists())


class FinalRoundScan(unittest.TestCase):
    """Small exact fixes of the last round: scan, review, handoff and the files around them."""

    def test_a_failing_qc_on_the_mix_is_a_finding_without_like(self):
        import argparse
        from unittest import mock
        from hypnomix.workflow import scan
        with tempfile.TemporaryDirectory() as td:
            od = Path(td)
            (od / "raw").mkdir()
            a = argparse.Namespace(mix="m.wav", like=None, no_profile=True, profile=None)
            fake = lambda tool, *args, **kw: (1 if tool == "qc" else 0, f"{tool} said this")
            with mock.patch.object(scan, "hx", fake), mock.patch.object(scan, "profile_wanted", lambda a: False):
                found, _ = scan.g_mix("x.als", od, a, tempo=None)
        by = {f["id"]: f for f in found}
        self.assertEqual({"mix-1", "mix-2", "mix-3"} - set(by), set())
        self.assertEqual(by["mix-2"]["severity"], "high")
        self.assertIn("FAILED release checks", by["mix-2"]["problem"])
        self.assertEqual(by["mix-1"]["severity"], "info")

    def test_group_seconds_are_written_into_scan_json(self):
        from unittest import mock
        from hypnomix.workflow import scan
        with tempfile.TemporaryDirectory() as td:
            od = Path(td)
            (od / "scan.json").write_text(json.dumps({"set": "x.als"}), encoding="utf-8")
            (od / "names.json").write_text(json.dumps({"group": "names", "set": "x.als", "seconds": 3.24, "findings": [], "notes": []}), encoding="utf-8")
            (od / "mix.json").write_text(json.dumps({"group": "mix", "set": "x.als", "seconds": 12.0, "findings": [], "notes": []}), encoding="utf-8")
            with mock.patch("hypnomix.workflow.prefs.load", return_value={}):
                scan.merge(od)
            info = json.loads((od / "scan.json").read_text(encoding="utf-8"))
        self.assertEqual(info["group_seconds"], {"names": 3.2, "mix": 12.0})
        self.assertEqual(info["set"], "x.als")

    def test_since_is_refused_for_a_reaper_or_ardour_project_before_any_work(self):
        from unittest import mock
        from hypnomix.workflow import scan
        with tempfile.TemporaryDirectory() as td:
            for name in ("Song.rpp", "Song.ardour"):
                proj = Path(td) / name
                proj.write_text("x", encoding="utf-8")
                out = Path(td) / ("out-" + name)
                argv = ["scan", str(proj), "--since", str(Path(td) / "old"), "--out", str(out)]
                with mock.patch("sys.argv", argv), self.assertRaises(SystemExit) as cm:
                    scan.main()
                self.assertIn("--since is for a Live set", str(cm.exception))
                self.assertFalse(out.exists())

    def test_an_ardour_folder_and_the_file_inside_it_are_one_source(self):
        from hypnomix.workflow import scan
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "Song"
            folder.mkdir()
            (folder / "Song.ardour").write_text("<Session/>", encoding="utf-8")
            self.assertTrue(scan.same_source(str(folder), folder / "Song.ardour"))
            self.assertTrue(scan.same_source(str(folder / "Song.ardour"), folder))
            other = Path(td) / "Other.als"
            other.write_text("x", encoding="utf-8")
            self.assertFalse(scan.same_source(str(folder), other))

    def test_a_nudge_of_a_hundredth_of_a_second_is_still_the_same_spot(self):
        from hypnomix.workflow import scan
        self.assertEqual(scan._position("5.2.01 (9.60 s)"), ("s", [9.6]))
        self.assertEqual(scan._near("5.2.01 (9.60 s)", "5.2.01 (9.61 s)") <= 0.011, True)
        self.assertIsNone(scan._near("5.2.01 (9.60 s)", "9.1.01 (30.00 s)"))
        self.assertEqual(scan._position("1:23.4"), ("s", [83.4]))                  # the old forms are as before
        self.assertEqual(scan._position("bar 17.2"), ("bar", [17.25]))
        self.assertIs(scan.identity, scan._identity)

    def test_the_ardour_review_says_what_fix_writes(self):
        from hypnomix.workflow import scan
        with tempfile.TemporaryDirectory() as td:
            od = Path(td)
            scan.write_review(od, str(od / "Song.ardour"), [], [], {})
            text = (od / "REVIEW.md").read_text(encoding="utf-8")
        self.assertNotIn("later hypnomix release", text)
        self.assertIn('--approved --out "<Session> (fixed).ardour"', text)
        self.assertIn("not yet opened in HypnoMix Studio", text)

    def test_readers_of_the_scan_files_fall_back_to_the_backup(self):
        from hypnomix.workflow import handoff, oversight as O
        good = {"set": "/x/Song.als", "findings": [{"id": "smooth-1", "tool": "smooth", "applies": "manual"}]}
        with tempfile.TemporaryDirectory() as td:
            sd = Path(td)
            (sd / "findings.json").write_text('{"set": "/x/Song.als", "find', encoding="utf-8")                    # cut off by a crash
            (sd / "findings.json.bak").write_text(json.dumps(good), encoding="utf-8")
            (sd / "decisions.json").write_text('{"smooth-1": {"deci', encoding="utf-8")
            (sd / "decisions.json.bak").write_text(json.dumps({"smooth-1": {"decision": "approve", "note": "by hand"}}), encoding="utf-8")
            (sd / "scan.json").write_text("{", encoding="utf-8")
            (sd / "scan.json.bak").write_text(json.dumps({"set": "/x/Song.als", "mode": "folder"}), encoding="utf-8")
            self.assertEqual(O.load_findings_doc(sd)["findings"][0]["id"], "smooth-1")
            items, data = handoff.collect(sd)
            self.assertEqual([i["f"]["id"] for i in items], ["smooth-1"])
            self.assertEqual(items[0]["note"], "by hand")
            self.assertEqual(handoff.context(sd, data)[0], None)               # scan.json read from its backup: a folder, no set
            with self.assertRaises(FileNotFoundError):
                O.load_findings_doc(sd / "nowhere")

    def test_bulk_approve_takes_only_plain_low_fixes_and_the_page_shows_the_list_first(self):
        from hypnomix.workflow import oversight as O, review as RV
        fs = [dict(id="a", tool="smooth", kind="click", severity="low", applies="set"),
              dict(id="b", tool="tune", kind="note", severity="low", applies="audio"),                 # a taste call
              dict(id="c", tool="order", kind="track-order", severity="low", applies="set"),           # a tidy step
              dict(id="d", tool="smooth", kind="click", severity="low", applies="set", default="approve"),   # on by default
              dict(id="e", tool="smooth", kind="click", severity="low", applies="set", protected=True),
              dict(id="f", tool="name", kind="x", severity="low", applies="manual"),                   # by hand
              dict(id="g", tool="smooth", kind="click", severity="medium", applies="set"),
              dict(id="h", tool="smooth", kind="click", severity="low", applies="set"),                # decided already
              dict(id="i", tool="smooth", kind="spike", severity="low", applies="info"),
              dict(id="j", tool="smooth", kind="click", severity="low", applies="set", taste=True),
              dict(id="k", tool="smooth", kind="click", severity="low", applies="set"),
              dict(id="l", tool="tidy", kind="retire-off", severity="low", applies="set")]
        ok, left = O.bulk_low(fs, {"h": {"decision": "skip"}})
        self.assertEqual([f["id"] for f in ok], ["a", "k"])
        self.assertEqual(left, dict(taste=2, tidy=3, protected=1, by_hand=1))
        payload = RV.bulk_payload(fs)
        self.assertEqual(payload["ok"], ["a", "h", "k"])                      # decisions are looked at on the page
        self.assertEqual(sorted(payload["taste"]), ["b", "j"])
        self.assertEqual(sorted(payload["tidy"]), ["c", "d", "l"])
        page = RV.PAGE
        self.assertNotIn("DATA.findings.filter(f => f.severity === 'low'", page)      # the old rule is gone
        self.assertIn("Nothing is recorded until you confirm", page)

    def test_one_missing_audio_file_does_not_fail_the_timing_check(self):
        from types import SimpleNamespace
        from unittest import mock
        from hypnomix.project.model import Clip, Take
        from hypnomix.workflow import timing_project as TP
        with tempfile.TemporaryDirectory() as td:
            here = Path(td) / "here.wav"
            sf.write(str(here), np.zeros(SR // 2), SR)
            clips = [Clip(name="a", start=0.0, length=8.0, takes=[Take(name="a", path=here)]),
                     Clip(name="gone", start=8.0, length=8.0, takes=[Take(name="gone", path=Path(td) / "lost.wav")]),
                     Clip(name="gone2", start=16.0, length=8.0, takes=[Take(name="gone2", path=Path(td) / "lost2.wav")])]
            track = SimpleNamespace(name="Kick", on=True, clips=clips)
            p = SimpleNamespace(tempo=120.0, tracks=[track])
            beats = [i * 0.5 for i in range(16)]
            fake = lambda c, *a, **k: [dict(t=b * 0.5, src=b * 0.5, strength=1.0) for b in range(16)]
            with mock.patch.object(TP, "item_onsets", fake):
                out, issues, notes = TP.analyse(p, ["Kick"])
        self.assertEqual(notes["skipped_missing"], 2)
        self.assertEqual(len(notes["missing"]), 2)
        self.assertEqual(len(out), 1)                               # the track with the good file is still measured

    def test_the_audio_cache_follows_the_file_and_is_bounded(self):
        from unittest import mock
        from hypnomix.project import model
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "x.wav"
            sf.write(str(f), np.full(SR, 0.25), SR)
            model._SRC.clear()
            a = model._source(f, SR)
            self.assertIs(model._source(f, SR), a)                   # unchanged: from the cache
            sf.write(str(f), np.full(SR * 2, 0.5), SR)               # the file changed on disk
            b = model._source(f, SR)
            self.assertEqual((len(a), len(b)), (SR, SR * 2))
            self.assertAlmostEqual(float(b[0]), 0.5, places=3)
            self.assertEqual(len(model._SRC), 1)                     # the old version is dropped, not kept beside it
            with mock.patch.object(model, "_SRC_MAX_ITEMS", 3):
                for i in range(6):
                    g = Path(td) / f"g{i}.wav"
                    sf.write(str(g), np.zeros(100), SR)
                    model._source(g, SR)
            self.assertLessEqual(len(model._SRC), 3)
            with self.assertRaises(OSError):
                model._source(Path(td) / "nope.wav", SR)
            model._SRC.clear()


if __name__ == "__main__":
    unittest.main()


class TakeScales(unittest.TestCase):
    """The section-by-section key map is in song time; a take is tuned in its own time."""

    def test_each_played_part_of_a_take_gets_the_section_it_is_heard_in(self):
        import json, tempfile
        from pathlib import Path
        from hypnomix.workflow import fix
        with tempfile.TemporaryDirectory() as td:
            kj = Path(td) / "key.json"
            kj.write_text(json.dumps({"key": "G major", "sections": [
                {"t0": 0.0, "t1": 40.0, "bars": "1-16", "root": 7, "scale": "G major"},
                {"t0": 40.0, "t1": 80.0, "bars": "17-32", "root": 7, "scale": "G major", "unsure": True,
                 "disputed": ["F#", "F"], "runner_up": "C major"}]}), encoding="utf-8")
            # one clip plays take seconds 5-15 at song seconds 35-45 (across the section line); a warped clip
            # arrives as small pieces: 20-20.25 and 20.25-20.5 of the take at song 60-60.5
            spans = [(35.0, 45.0, 5.0, 15.0), (60.0, 60.25, 20.0, 20.25), (60.25, 60.5, 20.25, 20.5)]
            rows = fix.take_scales(kj, spans, Path(td) / "take.json")
            self.assertEqual([(r["bars"], r["t0"], r["t1"]) for r in rows],
                             [("1-16", 5.0, 10.0), ("17-32", 10.0, 15.0), ("17-32", 20.0, 20.5)])
            saved = json.loads((Path(td) / "take.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["key"], "G major")                     # unplayed parts keep the overall key
            self.assertTrue(saved["sections"][1]["unsure"])               # the question travels with the section
