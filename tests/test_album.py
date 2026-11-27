"""`hypnomix album`: songs side by side. Everything is synthesised in a temporary folder.

    python -m unittest tests.test_album
"""
import hashlib, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

from hypnomix.core import dsp
from hypnomix.engineer import album as A

SR = 44100


def song(name, folder, gain_db=-14.0, bright_db=0.0, dur=9.0, head=0.3, tail=1.0, fade=0.0, root=220.0, minor=True,
         seed=0, quiet_half=False, stereo=True, subtype="PCM_24"):
    """A chordal tone with a pulsing envelope and a little noise, with silence before and after it."""
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    t = np.arange(n) / SR
    chord = [root, root * 2 ** ((3 if minor else 4) / 12), root * 2 ** (7 / 12)]
    y = sum(np.sin(2 * np.pi * f * h * t) / h ** 1.2 for f in chord for h in range(1, 8))
    y = y * (0.6 + 0.4 * np.exp(-((t * 2) % 1) * 3)) + rng.standard_normal(n) * 0.02
    if quiet_half:                                              # the first half of every 6 s is much quieter
        y = y * np.where((t % 6) < 3, 0.3, 1.0)
    y = y / np.abs(y).max()
    if bright_db:
        y = y + sosfilt(butter(2, 4000, "highpass", fs=SR, output="sos"), y) * (10 ** (bright_db / 20) - 1)
    y = y * 10 ** (gain_db / 20) / max(1.0, np.abs(y).max() * 10 ** (gain_db / 20))
    if fade:
        f = int(fade * SR)
        y[-f:] *= np.linspace(1, 0, f)
    z = np.zeros(int((head + dur + tail) * SR))
    z[int(head * SR):int(head * SR) + n] = y
    out = np.stack([z, np.roll(z, 12)], 1) if stereo else z
    p = Path(folder) / f"{name}.wav"
    sf.write(str(p), out, SR, subtype=subtype)
    return p


def digest(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def run(*args, home=None):
    env = dict(os.environ)
    if home:
        env["HYPNOMIX_HOME"] = str(home)
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True, env=env, encoding="utf-8")
    return r.returncode, r.stdout + r.stderr


class Album(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._td.name)
        d = cls.dir / "songs"
        d.mkdir()
        cls.songs = d
        song("A one", d, seed=1, head=0.4, tail=1.2)
        song("B two", d, seed=2, head=0.1, tail=2.5, fade=5.0, root=196.0, minor=False)
        song("C quiet", d, gain_db=-26.0, seed=3, head=0.8, tail=3.0, root=233.08)
        song("D bright", d, bright_db=7.0, seed=4, head=0.2, tail=0.5, root=261.63, minor=False)
        song("E verses", d, seed=5, head=0.2, tail=2.0, quiet_half=True, root=174.61)
        cls.files = sorted(d.glob("*.wav"))
        cls.info = [A.analyse(f, quick=True) for f in cls.files]
        cls.home = cls.dir / "home"

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def opts(self, **kw):
        o = dict(anchor=None, target=None, keep_quiet=[], reading="both", tolerance=2.0, tone_tolerance=1.5, width_tolerance=3.0,
                 tilt_amount=50.0, max_tilt_db=2.0, ceiling=-1.0, gap=None, gap_style="normal", head=0.1, last_tail=2.0,
                 gap_tolerance=0.3, suggest_order=True)
        o.update(kw)
        return o

    # ---------------------------------------------------------------- measuring
    def test_measures(self):
        a = self.info[0]
        self.assertAlmostEqual(a["head_s"], 0.4, delta=0.02)
        self.assertAlmostEqual(a["tail_s"], 1.2, delta=0.02)
        self.assertLess(a["true_peak"], 0.0)
        self.assertEqual(a["channels"], 2)
        self.assertEqual(len(a["curve"]), 8)
        self.assertIsNone(a["key"])                     # --quick measured no key
        quiet = self.info[2]
        self.assertAlmostEqual(a["whole_lufs"] - quiet["whole_lufs"], 12.0, delta=0.6)

    def test_how_a_song_ends(self):
        by = {s["name"]: s for s in self.info}
        self.assertEqual(by["A one"]["tail_kind"], "abrupt")
        self.assertIn(by["B two"]["tail_kind"], ("ring-out", "long fade"))        # a 5 s fade
        self.assertGreater(by["B two"]["decay_s"], 1.5)

    def test_mono_file_has_no_width(self):
        p = song("mono", self.dir, seed=9, stereo=False)
        s = A.analyse(p, quick=True)
        self.assertTrue(s["mono"])
        self.assertIsNone(s["width_db"])

    def test_silent_file_is_refused(self):
        p = self.dir / "silent.wav"
        sf.write(str(p), np.zeros((SR, 2)), SR)
        with self.assertRaises(ValueError):
            A.analyse(p, quick=True)

    def test_short_term_loudest_is_not_below_whole(self):
        y, sr = dsp.load(self.files[4])               # the verses song: quiet halves, loud halves
        st = A.short_term(y, sr)
        self.assertGreater(max(st), dsp.lufs(y, sr) + 1.5)

    # ---------------------------------------------------------------- level, tone, width
    def test_level_states(self):
        cmp = A.compare(self.info, self.opts())
        st = {r["name"]: r["state"] for r in cmp["rows"]}
        self.assertEqual(st["C quiet"], "apart")
        self.assertEqual(st["E verses"], "whole only")          # quiet as a whole, but its loudest section is in line
        self.assertIn(st["A one"], ("in line", "whole only"))
        loud = {r["name"]: r for r in cmp["rows"]}["E verses"]
        self.assertLess(loud["d_whole"], -2.0)
        self.assertLess(abs(loud["d_loudest"]), 2.0)

    def test_readings(self):
        whole = {r["name"]: r["state"] for r in A.compare(self.info, self.opts(reading="whole"))["rows"]}
        self.assertEqual(whole["E verses"], "apart")            # judged on the whole song alone, the verses song is off
        loudest = {r["name"]: r["state"] for r in A.compare(self.info, self.opts(reading="loudest"))["rows"]}
        self.assertEqual(loudest["E verses"], "in line")

    def test_keep_quiet_and_anchor_and_target(self):
        cmp = A.compare(self.info, self.opts(keep_quiet=["c quiet"]))
        self.assertEqual({r["name"]: r["state"] for r in cmp["rows"]}["C quiet"], "kept quiet")
        cmp = A.compare(self.info, self.opts(anchor="C quiet"))
        st = {r["name"]: r["state"] for r in cmp["rows"]}
        self.assertEqual(st["C quiet"], "anchor")
        self.assertEqual(st["A one"], "apart")                  # now it is the loud one
        cmp = A.compare(self.info, self.opts(target=-14.0))
        row = {r["name"]: r for r in cmp["rows"]}["A one"]
        self.assertAlmostEqual(row["ref_whole"], -14.0)

    def test_tone_words_and_width(self):
        cmp = A.compare(self.info, self.opts())
        row = {r["name"]: r for r in cmp["rows"]}["D bright"]
        self.assertGreater(row["groups"]["high"], 1.5)
        self.assertTrue(any("brighter" in w for _, w in row["tone_words"]))
        self.assertEqual(len(row["dev"]), 8)

    def test_gain_follows_the_smaller_gap_and_respects_the_ceiling(self):
        o = self.opts()
        cmp = A.compare(self.info, o)
        i = [s["name"] for s in self.info].index("C quiet")
        g, note = A.level_gain(cmp["rows"][i], self.info[i], o)
        self.assertAlmostEqual(g, -cmp["rows"][i]["d_whole"] if abs(cmp["rows"][i]["d_whole"]) < abs(cmp["rows"][i]["d_loudest"])
                               else -cmp["rows"][i]["d_loudest"], delta=0.11)
        self.assertGreater(g, 5)
        hot = dict(self.info[i], true_peak=-1.5)               # a raise would cross the ceiling
        g2, note2 = A.level_gain(cmp["rows"][i], hot, o)
        self.assertLessEqual(g2, 0.5 + 1e-9)
        self.assertIn("limiter", note2)
        e = [s["name"] for s in self.info].index("E verses")
        self.assertEqual(A.level_gain(cmp["rows"][e], self.info[e], o)[0], None)    # a whole-only difference is left alone

    def test_tilt_is_a_fraction_and_capped(self):
        row = {"groups": {"low": 0.0, "high": 8.0}}
        t = A.tilt_for(row, self.opts())
        self.assertEqual(t, {"high": -2.0})                     # 50% of 8 dB is 4, capped at 2
        t = A.tilt_for({"groups": {"low": 1.0, "high": -3.0}}, self.opts())
        self.assertEqual(t, {"high": 1.5})                      # low is inside the tolerance
        self.assertIsNone(A.tilt_for({"groups": {"low": 0.5, "high": 1.0}}, self.opts()))

    # ---------------------------------------------------------------- gaps and orders
    def test_gap_follows_the_tail_and_the_style(self):
        by = {s["name"]: s for s in self.info}
        g_abrupt, why = A.gap_for(by["A one"], by["B two"], self.opts())
        g_fade, _ = A.gap_for(dict(by["A one"], tail_kind="long fade", decay_s=5.0), by["B two"], self.opts())
        self.assertGreater(g_abrupt, g_fade)
        self.assertTrue(any("abruptly" in w for w in why))
        tight, _ = A.gap_for(by["A one"], by["B two"], self.opts(gap_style="tight"))
        roomy, _ = A.gap_for(by["A one"], by["B two"], self.opts(gap_style="roomy"))
        self.assertLess(tight, g_abrupt)
        self.assertGreater(roomy, g_abrupt)
        self.assertEqual(A.gap_for(by["A one"], by["B two"], self.opts(gap=1.7))[0], 1.7)

    def test_transitions_and_silence_targets(self):
        order = [0, 1, 2, 3, 4]
        tr = A.transitions(self.info, order, self.opts())
        self.assertEqual(len(tr), 4)
        self.assertAlmostEqual(tr[0]["have"], self.info[0]["tail_s"] + self.info[1]["head_s"], places=2)
        tg = A.ends_targets(self.info, order, tr, self.opts())
        self.assertEqual(tg[4][1], 2.0)                         # the last song ends with --last-tail
        self.assertAlmostEqual(tg[0][1] + tg[1][0], tr[0]["gap"], delta=0.11)

    def test_keys_on_the_circle_of_fifths(self):
        self.assertEqual(A.key_distance("A minor", "C major"), 0)          # relative keys
        self.assertEqual(A.key_distance("C major", "G major"), 1)
        self.assertEqual(A.key_distance("C major", "F# major"), 6)
        self.assertIsNone(A.key_distance(None, "C major"))
        self.assertIn("far apart", A.key_words(5))

    def test_order_options_are_orderings_and_never_applied(self):
        keys = ["A minor", "G major", "Bb minor", "B major", "F minor"]
        songs = [dict(s, key=k, tempo=100.0 + 5 * i) for i, (s, k) in enumerate(zip(self.info, keys))]
        before = json.dumps(songs, sort_keys=True)
        opts = A.suggest_orders(songs)
        self.assertEqual(before, json.dumps(songs, sort_keys=True))
        self.assertTrue(1 <= len(opts) <= 2)
        for o in opts:
            self.assertEqual(sorted(o["order"]), [0, 1, 2, 3, 4])
        self.assertEqual(A.suggest_orders(songs[:2]), [])                  # two songs: nothing to arrange
        arc = opts[0]["order"]
        e = A.energy(songs)
        self.assertNotEqual(int(np.argmax(e)), arc[0])                     # the peak is not the opener...
        self.assertNotEqual(int(np.argmax(e)), arc[-1])                    # ...and not the closer

    def test_resolve_order(self):
        self.assertEqual(A.resolve_order("E verses, a one,3,B two,d bright", self.info), [4, 0, 2, 1, 3])
        with self.assertRaises(SystemExit):
            A.resolve_order("A one,B two", self.info)                       # leaves songs out
        with self.assertRaises(SystemExit):
            A.resolve_order("A one,A one,B two,C quiet,D bright,E verses", self.info)
        with self.assertRaises(SystemExit):
            A.resolve_order("nonsense,B two,C quiet,D bright,E verses", self.info)

    # ---------------------------------------------------------------- the proposals and what applies them
    def test_proposals_are_commands_for_fix(self):
        o = self.opts()
        cmp = A.compare(self.info, o)
        order = list(range(len(self.info)))
        props = A.proposals(self.info, cmp, order, A.transitions(self.info, order, o), o)
        kinds = {(p["track"], p["kind"]) for p in props}
        self.assertIn(("C quiet.wav", "gain"), kinds)
        self.assertNotIn(("E verses.wav", "gain"), kinds)
        self.assertIn(("D bright.wav", "tilt"), kinds)
        for p in props:
            self.assertEqual(p["applies"], "audio")
            self.assertEqual(p["run"][:2], ["album", "--render"])
            self.assertIn("{out}", p["run"])

    def test_render_gain_writes_a_new_file_and_leaves_the_song(self):
        src = self.files[0]
        before = digest(src)
        out = self.dir / "r1"
        dest = A.render("gain", src, out, db=-3.0)
        self.assertEqual(before, digest(src))
        self.assertEqual(dest.name, "A one (album gain).wav")
        y0, sr = dsp.load(src)
        y1, _ = dsp.load(dest)
        self.assertAlmostEqual(dsp.lufs(y1, sr) - dsp.lufs(y0, sr), -3.0, delta=0.05)
        again = A.render("gain", src, out, db=-3.0)                         # the same move twice is not applied twice
        self.assertEqual(again, dest)
        self.assertEqual(len(list(out.glob("*.wav"))), 1)

    def test_moves_on_one_song_chain(self):
        src = self.files[3]
        out = self.dir / "r2"
        a = A.render("gain", src, out, db=-2.0)
        b = A.render("tilt", src, out, tilt={"high": -2.0})
        c = A.render("ends", src, out, head=0.1, tail=2.0)
        self.assertEqual(c.name, "D bright (album gain+tilt+ends).wav")
        self.assertEqual(len(list(out.glob("*.wav"))), 3)                    # every step is kept, none overwritten
        y0, sr = dsp.load(src)
        y3, _ = dsp.load(c)
        self.assertAlmostEqual(dsp.lufs(y3, sr), dsp.lufs(y0, sr) - 2.0, delta=0.25)    # the tilt keeps the level
        s = A.analyse(c, quick=True)
        self.assertAlmostEqual(s["head_s"], 0.1, delta=0.01)
        self.assertAlmostEqual(s["tail_s"], 2.0, delta=0.01)
        self.assertLess(A.analyse(c, quick=True)["curve"][6], A.analyse(src, quick=True)["curve"][6] + 0.01)   # highs came down

    def test_tilt_stays_under_the_ceiling(self):
        src = song("hot", self.dir, gain_db=-1.2, seed=7)
        dest = A.render("tilt", src, self.dir / "r3", tilt={"low": 2.0, "high": 2.0}, ceiling=-1.0)
        y0, sr = dsp.load(src)
        y1, _ = dsp.load(dest)
        self.assertLessEqual(dsp.true_peak(y1, sr), max(-1.0, dsp.true_peak(y0, sr)) + 0.05)

    def test_ends_only_touches_silence(self):
        src = self.files[2]
        y0, sr = dsp.load(src)
        on = np.flatnonzero(np.abs(y0).max(axis=1) > A.SILENCE)
        dest = A.render("ends", src, self.dir / "r4", head=0.05, tail=4.0)
        y1, _ = dsp.load(dest)
        on1 = np.flatnonzero(np.abs(y1).max(axis=1) > A.SILENCE)
        self.assertEqual(on1[-1] - on1[0], on[-1] - on[0])                  # the sound is the same length
        np.testing.assert_allclose(y1[on1[0]:on1[-1] + 1], y0[on[0]:on[-1] + 1], atol=1e-6)     # and sample for sample the same
        self.assertAlmostEqual((len(y1) - 1 - on1[-1]) / sr, 4.0, delta=0.001)

    def test_16_bit_stays_16_bit(self):
        src = song("sixteen", self.dir, seed=8, subtype="PCM_16")
        dest = A.render("gain", src, self.dir / "r5", db=-1.0)
        self.assertEqual(sf.info(str(dest)).subtype, "PCM_16")
        dest = A.render("ends", src, self.dir / "r5b", tail=0.5)
        self.assertEqual(sf.info(str(dest)).subtype, "PCM_16")

    # ---------------------------------------------------------------- the report and the command
    def test_report_in_plain_words(self):
        o = self.opts()
        cmp = A.compare(self.info, o)
        order = [4, 0, 2, 1, 3]
        tr = A.transitions(self.info, order, o)
        text = A.report(self.info, order, cmp, tr, [], A.proposals(self.info, cmp, order, tr, o), o, [])
        for must in ("## The songs, in this order", "## Level", "Reading used: both readings", "Sits apart: quieter",
                     "## Tone", "## Stereo width", "## Between the songs", "suggested gap", "Nothing here is applied", "## What could change"):
            self.assertIn(must, text)
        self.assertLess(text.index("E verses"), text.index("A one"))        # in the order given

    def test_command_writes_a_report_and_changes_nothing(self):
        out = self.dir / "cmd"
        before = {f: digest(f) for f in self.files}
        code, txt = run("album", *self.files, "--quick", "--suggest-order", "--order", "E verses,A one,C quiet,B two,D bright",
                        "--out", out, home=self.home)
        self.assertEqual(code, 0, txt)
        md = (out / "ALBUM.md").read_text(encoding="utf-8")
        self.assertIn("E verses", md)
        self.assertIn("## Order options (never applied)", md)
        self.assertTrue((out / "raw" / "album.json").exists())
        self.assertEqual(before, {f: digest(f) for f in self.files})
        self.assertFalse((out / "findings.json").exists())                  # no plan without --plan

    def test_command_refuses_one_song_and_bad_names(self):
        self.assertNotEqual(run("album", self.files[0], home=self.home)[0], 0)
        code, txt = run("album", *self.files, "--quick", "--anchor", "nope", "--out", self.dir / "x", home=self.home)
        self.assertNotEqual(code, 0)
        self.assertIn("The songs are", txt)

    def test_a_folder_is_the_album(self):
        code, txt = run("album", self.songs, "--quick", "--out", self.dir / "cmd2", home=self.home)
        self.assertEqual(code, 0, txt)
        self.assertIn("5 songs", (self.dir / "cmd2" / "ALBUM.md").read_text(encoding="utf-8"))

    def test_plan_review_and_fix_end_to_end(self):
        """--plan -> findings -> approve two -> fix writes only the approved moves into new files."""
        scan = self.dir / "scan"
        code, txt = run("album", *self.files, "--quick", "--plan", scan, home=self.home)
        self.assertEqual(code, 0, txt)
        data = json.loads((scan / "findings.json").read_text(encoding="utf-8"))
        fs = {f["id"]: f for f in data["findings"]}
        self.assertTrue(fs)
        self.assertTrue(all(f["tool"] == "album" and f["applies"] == "audio" for f in fs.values()))
        gain = next(i for i, f in fs.items() if f["kind"] == "gain")
        ends = next(i for i, f in fs.items() if f["kind"] == "ends" and f["track"] == fs[gain]["track"])
        before = {f: digest(f) for f in self.files}
        code, txt = run("fix", scan, "--decide", f"{gain}=approve,{ends}=approve", home=self.home)
        self.assertEqual(code, 0, txt)
        code, txt = run("fix", scan, "--approved", home=self.home)
        self.assertEqual(code, 0, txt)
        made = sorted(p.name for p in (scan / "fixed").glob("*.wav"))
        stem = Path(fs[gain]["track"]).stem
        self.assertEqual(made, sorted([f"{stem} (album gain).wav", f"{stem} (album gain+ends).wav"]))
        self.assertEqual(before, {f: digest(f) for f in self.files})        # the songs themselves never change
        # the other findings were not decided, so nothing else was written
        self.assertEqual(len(made), 2)


    # ---------------------------------------------------------------- repairs found by the independent check
    def test_a_boost_above_6k_is_named_even_though_presence_is_flat(self):
        """The air band alone is +2.4 dB: averaging it with a flat presence band (+1.2) used to hide it."""
        songs = []
        for k in range(5):
            s = dict(self.info[0], name=f"S{k}", file=f"/x/S{k}.wav")
            s["curve"] = list(self.info[0]["curve"])
            songs.append(s)
        songs[2]["curve"][7] = songs[2]["curve"][7] + 2.4          # air only; 4-8 kHz (presence) unchanged
        o = self.opts()
        cmp = A.compare(songs, o)
        row = cmp["rows"][2]
        self.assertGreater(row["groups"]["high"], o["tone_tolerance"])
        self.assertTrue(any("brighter" in w for _, w in row["tone_words"]), row["tone_words"])
        self.assertFalse(any(cmp["rows"][i]["tone_words"] for i in (0, 1, 3, 4)))     # the others are not blamed
        order = list(range(5))
        tr = A.transitions(songs, order, o)
        text = A.report(songs, order, cmp, tr, [], A.proposals(songs, cmp, order, tr, o), o, [])
        self.assertIn("**S2**: brighter by", text)
        self.assertNotIn("No song is more than", text)
        props = A.proposals(songs, cmp, order, tr, o)
        self.assertTrue(any(p["kind"] == "tilt" and p["track"] == "S2.wav" for p in props))

    def test_nothing_apart_sentence_matches_the_table(self):
        songs = [dict(self.info[0], name=f"S{k}", file=f"/x/S{k}.wav") for k in range(4)]
        o = self.opts()
        cmp = A.compare(songs, o)
        text = A.report(songs, list(range(4)), cmp, A.transitions(songs, list(range(4)), o), [], [], o, [])
        self.assertIn("No song is more than 1.5 dB away from the others in any band from 60 Hz up", text)
        for r in cmp["rows"]:
            self.assertTrue(all(abs(v) <= 1.5 for v in r["dev"][1:]))

    def test_two_songs_meet_in_the_middle_and_never_swap(self):
        a = dict(self.info[0], name="A", file="/x/A.wav", whole_lufs=-14.0, loudest_lufs=-11.0, true_peak=-6.0)
        b = dict(self.info[0], name="B", file="/x/B.wav", whole_lufs=-17.2, loudest_lufs=-14.2, true_peak=-6.0)
        o = self.opts()
        cmp = A.compare([a, b], o)
        self.assertEqual({r["state"] for r in cmp["rows"]}, {"apart"})
        self.assertIn("midpoint", cmp["rows"][0]["ref_how"])
        ga = A.level_gain(cmp["rows"][0], a, o)[0]
        gb = A.level_gain(cmp["rows"][1], b, o)[0]
        self.assertAlmostEqual(ga, -1.6, delta=0.05)                 # half of the 3.2 dB gap each
        self.assertAlmostEqual(gb, +1.6, delta=0.05)
        after_a, after_b = a["whole_lufs"] + ga, b["whole_lufs"] + gb
        self.assertAlmostEqual(after_a, after_b, delta=0.1)          # they meet, they do not swap
        order = [0, 1]
        tr = A.transitions([a, b], order, o)
        text = A.report([a, b], order, cmp, tr, [], A.proposals([a, b], cmp, order, tr, o), o, [])
        self.assertIn("midpoint of the two", text)
        self.assertNotIn("is just their midpoint", text)
        # a gap under the tolerance is still not a proposal
        b2 = dict(b, whole_lufs=-15.0, loudest_lufs=-12.0)
        self.assertEqual({r["state"] for r in A.compare([a, b2], o)["rows"]}, {"in line"})
        # an anchor moves only the other song, by the whole gap
        cmp_a = A.compare([a, b], self.opts(anchor="A"))
        self.assertEqual(cmp_a["rows"][0]["state"], "anchor")
        self.assertAlmostEqual(A.level_gain(cmp_a["rows"][1], b, self.opts(anchor="A"))[0], 3.2, delta=0.05)

    def test_a_plain_quiet_song_is_only_offered_a_raise(self):
        o = self.opts()
        cmp = A.compare(self.info, o)
        order = list(range(len(self.info)))
        props = A.proposals(self.info, cmp, order, A.transitions(self.info, order, o), o)
        g = next(p for p in props if p["kind"] == "gain" and p["track"] == "C quiet.wav")
        self.assertIn("Only if you want it to match", g["fix"])
        text = A.report(self.info, order, cmp, A.transitions(self.info, order, o), [], props, o, [])
        self.assertIn("only if you want it to match the others", text)
        o2 = self.opts(anchor="A one")                                # asked to match: no hedge
        cmp2 = A.compare(self.info, o2)
        g2 = next(p for p in A.proposals(self.info, cmp2, order, A.transitions(self.info, order, o2), o2)
                  if p["kind"] == "gain" and p["track"] == "C quiet.wav")
        self.assertNotIn("Only if", g2["fix"])

    def test_plan_survives_scan_merge_in_a_fresh_process(self):
        scan = self.dir / "scan_merge"
        code, txt = run("album", *self.files, "--quick", "--plan", scan, home=self.home)
        self.assertEqual(code, 0, txt)
        n = len(json.loads((scan / "findings.json").read_text(encoding="utf-8"))["findings"])
        self.assertGreater(n, 0)
        code, txt = run("fix", scan, "--decide", "album-1=approve", home=self.home)
        self.assertEqual(code, 0, txt)
        code, txt = run("scan", "--merge", scan, home=self.home)
        self.assertEqual(code, 0, txt)
        self.assertEqual(len(json.loads((scan / "findings.json").read_text(encoding="utf-8"))["findings"]), n)
        self.assertFalse((scan / "decisions-orphaned.json").exists())
        self.assertEqual(json.loads((scan / "decisions.json").read_text(encoding="utf-8"))["album-1"]["decision"], "approve")


if __name__ == "__main__":
    unittest.main()
