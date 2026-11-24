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
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True, env=env)
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
            d = json.loads((Path(td) / "preferences.json").read_text())
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
            (sd / "findings.json").write_text(json.dumps({"set": str(als), "notes": [], "findings": [finding]}))
            (sd / "scan.json").write_text(json.dumps({"set": str(als), "mode": "set", "set_mtime": als.stat().st_mtime}))
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
            F = json.loads((sd / "findings.json").read_text())["findings"]
            kinds = {(f["track"], f["kind"]) for f in F}
            self.assertIn(("Bass clipped.wav", "clipped"), kinds)
            self.assertIn(("Guitar noisy.wav", "noise"), kinds)
            self.assertIn(("Guitar noisy.wav", "dc"), kinds)
            self.assertIn("Nothing has been changed", (sd / "REVIEW.md").read_text())
            dc = next(f for f in F if f["kind"] == "dc")
            code, out = hx("fix", sd, "--approve", dc["id"], home=home)
            self.assertEqual(code, 0, out)
            self.assertTrue(list((sd / "fixed").glob("*.wav")))
            self.assertEqual(before, {p.name: p.read_bytes() for p in raw.iterdir()})   # sources untouched
            code, out = hx("ab", sd, "--ids", dc["id"], home=home)
            self.assertEqual(code, 0, out)
            ab = json.loads((sd / "ab" / "ab.json").read_text())
            self.assertTrue((sd / "ab" / ab[dc["id"]]["a"]).exists())
            code, out = hx("review", sd, home=home)
            page = (sd / "REVIEW.html").read_text()
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
            F = json.loads((sd / "findings.json").read_text())["findings"]
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
            (sd / "findings.json").write_text(json.dumps({"set": "x", "findings": [dict(id="a-1"), dict(id="a-2")]}))
            R.record(sd, "a-1", "approve", "ok")
            with self.assertRaises(ValueError):
                R.record(sd, "zzz", "approve")
            with self.assertRaises(ValueError):
                R.record(sd, "a-2", "delete everything")
            (sd / "dl.json").write_text(json.dumps({"a-2": {"decision": "skip"}, "bogus": {"decision": "approve"}}))
            R.import_file(sd, sd / "dl.json")
            dec = json.loads((sd / "decisions.json").read_text())
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


if __name__ == "__main__":
    unittest.main()
