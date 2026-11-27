"""Analysis performance: what the analysis code reads, holds and repeats on big inputs, and that none of it changes an answer.

Nothing here measures time. Each test counts something (whole-file reads, calls of the slow step, the length of the
largest array handed on, files kept) on a tiny synthetic input, and checks the answer is the one the plain
(slow, memory-hungry) way gives, bit for bit unless the test says otherwise.
"""
import gzip, os, tempfile, unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import numpy as np
import soundfile as sf

SR = 44100


def clicks(seconds, sr=SR, seed=1):
    """Stereo noise bursts every half second: something for an onset detector to find."""
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    y = rng.normal(0, 0.01, (n, 2))
    for k in range(0, n - 800, sr // 2):
        y[k:k + 800] += rng.normal(0, 0.5, (800, 2))
    return y


class Scratch(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.r = Path(self.td.name).resolve()
        self.env = mock.patch.dict(os.environ, HYPNOMIX_HOME=str(self.r / "home"), HYPNOMIX_USER_HOME=str(self.r))
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.td.cleanup()


# ---------------------------------------------------------------- timing reads
class TimingReads(Scratch):
    def item(self, path, start, length=1.8):
        return NS(take=NS(path=path, section=None, offset=start, rate=1.0, stretch=None, kind="audio"),
                  length=length, start=start, end=start + length)

    def test_a_file_is_read_whole_once_then_each_item_reads_its_own_stretch(self):
        from hypnomix.core import dsp
        from hypnomix.workflow import timing_project as TP
        TP._CHECKED.clear()
        wav = self.r / "a.wav"
        sf.write(str(wav), clicks(12), SR, subtype="PCM_16")
        items = [self.item(wav, 0.3 + 1.1 * i) for i in range(8)]
        with mock.patch.object(dsp, "load", wraps=dsp.load) as ld:
            got = [TP.item_onsets(c) for c in items]
        self.assertEqual(ld.call_count, 1)                    # eight items, one whole-file read (it was 8)

        def whole_file(path, s0, s1):                         # the way it was: the whole file, then the stretch
            y, sr = dsp.load(path)
            mono = y.mean(1)
            a, b = max(0, int((s0 - 0.05) * sr)), min(len(mono), int((s1 + 0.05) * sr))
            return mono[a:b], a, sr
        with mock.patch.object(TP, "item_audio", whole_file):
            want = [TP.item_onsets(c) for c in items]
        self.assertEqual(got, want)                           # the same hits, to the last digit
        self.assertTrue(any(got))
        for c in items:                                       # and the same samples
            s0, s1 = c.take.offset, c.take.offset + c.length
            seg, a, sr = TP.item_audio(wav, s0, s1)
            ref, a2, sr2 = whole_file(wav, s0, s1)
            self.assertTrue(np.array_equal(seg, ref))
            self.assertEqual((a, sr), (a2, sr2))

    def test_a_file_that_changed_is_checked_again(self):
        from hypnomix.core import dsp
        from hypnomix.workflow import timing_project as TP
        TP._CHECKED.clear()
        wav = self.r / "a.wav"
        sf.write(str(wav), clicks(6), SR, subtype="PCM_16")
        with mock.patch.object(dsp, "load", wraps=dsp.load) as ld:
            TP.item_audio(wav, 0.3, 2.0)
            TP.item_audio(wav, 2.3, 4.0)
            self.assertEqual(ld.call_count, 1)
            sf.write(str(wav), clicks(7), SR, subtype="PCM_16")       # another size
            TP.item_audio(wav, 0.3, 2.0)
            self.assertEqual(ld.call_count, 2)

    def test_a_broken_file_still_stops_the_check_every_time(self):
        from hypnomix.core import dsp
        from hypnomix.workflow import timing_project as TP
        TP._CHECKED.clear()
        y = clicks(4)
        y[1000, 0] = np.nan
        wav = self.r / "bad.wav"
        sf.write(str(wav), y, SR, subtype="FLOAT")
        for _ in range(2):
            with self.assertRaises(dsp.AudioReadError):
                TP.item_audio(wav, 0.3, 2.0)
        self.assertEqual(TP._CHECKED, {})                     # a file that failed is never remembered as checked

    def test_the_remembered_files_are_bounded(self):
        from hypnomix.workflow import timing_project as TP
        TP._CHECKED.clear()
        with mock.patch.object(TP, "_CHECKED_MAX", 3):
            for i in range(6):
                wav = self.r / f"f{i}.wav"
                sf.write(str(wav), clicks(2, seed=i), SR, subtype="PCM_16")
                TP.item_audio(wav, 0.1, 1.0)
            self.assertLessEqual(len(TP._CHECKED), 3)

    def test_a_format_whose_seek_is_not_exact_is_read_whole_for_every_item(self):
        from hypnomix.core import dsp
        from hypnomix.workflow import timing_project as TP
        TP._CHECKED.clear()
        wav = self.r / "a.wav"
        sf.write(str(wav), clicks(6), SR, subtype="PCM_16")

        class Mp3Like(sf.SoundFile):                          # the file says it is an mp3 (libsndfile's seek there is not sample-exact)
            format = property(lambda self: "MP3")
        with mock.patch.object(sf, "SoundFile", Mp3Like), mock.patch.object(dsp, "load", wraps=dsp.load) as ld:
            for i in range(3):
                TP.item_audio(wav, 0.3 + i, 1.8 + i)
        self.assertEqual(ld.call_count, 3)                    # one whole read each: the same samples as before the fix
        with mock.patch.object(dsp, "load", wraps=dsp.load) as ld:      # the real SoundFile again: a wav
            TP.item_audio(wav, 0.3, 1.8)
        self.assertEqual(ld.call_count, 0)                    # a wav (seek is exact there) reads only its stretch

    def test_live_clips_average_only_their_own_stretch(self):
        from hypnomix.session import smooth as sm, timing as TM
        y = clicks(20).astype(np.float32)
        seen = []

        class Spy(np.ndarray):
            def mean(self, *a, **k):
                seen.append(len(self))
                return np.asarray(super().mean(*a, **k))
        ci = dict(path="x.wav", start=2.0, end=6.0, loop_on=False, warped=True, markers=[], ls=1.0, le=3.0, rel=0.0,
                  gain=1.0)
        with mock.patch.object(sm, "load_audio", return_value=(y.view(Spy), SR, None)):
            got = TM.clip_onsets(ci, 120.0)
        self.assertTrue(seen and max(seen) < len(y) // 4)    # the stretch, not the whole file (it was every sample)
        self.assertTrue(got)
        s0, s1 = sm.file_seconds(ci, np.array([ci["start"], ci["end"]]), 120.0)
        a, b = max(0, int(s0 * SR) - int(0.05 * SR)), min(len(y), int(s1 * SR) + int(0.05 * SR))
        whole = y.mean(1)[a:b]                                # the way it was: the whole file's mean, then the stretch
        with mock.patch.object(sm, "load_audio", return_value=(y, SR, None)):
            self.assertEqual(got, TM.clip_onsets(ci, 120.0))
        self.assertTrue(np.array_equal(y[a:b].mean(1), whole))


# ---------------------------------------------------------------- the compressor smoother
def old_smooth_db(target_db, sr, attack_ms, release_ms, block):
    """_smooth_db as it was: one numpy scalar at a time."""
    import math
    n = len(target_db)
    k = max(1, n // block)
    t = target_db[: k * block].reshape(k, block).min(axis=1)
    if k * block < n:
        t = np.append(t, target_db[k * block:].min())
    fs_b = sr / block
    a_att = math.exp(-1 / max(1e-6, attack_ms / 1000 * fs_b))
    a_rel = math.exp(-1 / max(1e-6, release_ms / 1000 * fs_b))
    g = np.empty_like(t)
    s = 0.0
    for i, x in enumerate(t):
        s = a_att * s + (1 - a_att) * x if x < s else a_rel * s + (1 - a_rel) * x
        g[i] = s
    xs = (np.arange(len(g)) + 0.5) * block
    return np.interp(np.arange(n), xs, g)


class Smoother(unittest.TestCase):
    def test_doubles_take_the_plain_float_loop_and_nothing_else_does(self):
        from hypnomix.core import dsp
        calls = dict(tolist=0, iter=0)

        class Spy(np.ndarray):
            def tolist(self):
                calls["tolist"] += 1
                return super().tolist()

            def __iter__(self):
                calls["iter"] += 1
                return super().__iter__()
        for dtype, fast in ((np.float64, True), (np.float32, False)):
            calls.update(tolist=0, iter=0)
            x = (-np.abs(np.random.default_rng(1).normal(0, 6, 1024))).astype(dtype).view(Spy)
            dsp._smooth_db(x, 22050, 10.0, 100.0, 16)
            if fast:
                self.assertGreater(calls["tolist"], 0)       # the numpy-scalar loop (a call to iter per scalar) is not used
                self.assertEqual(calls["iter"], 0)
            else:
                self.assertEqual(calls["tolist"], 0)         # a narrower type keeps the loop that rounds at every step
                self.assertGreater(calls["iter"], 0)

    def test_same_bits_as_the_per_scalar_loop(self):
        from hypnomix.core import dsp
        rng = np.random.default_rng(3)
        for dtype in (np.float64, np.float32):
            for n in (16, 17, 1000, 22050):
                x = (-np.abs(rng.normal(0, 6, n)) * (rng.random(n) > 0.3)).astype(dtype)
                for att, rel in ((0.01, 1.0), (10.0, 100.0), (2.0, 800.0), (50.0, 30.0)):
                    want = old_smooth_db(x, 22050, att, rel, 16)
                    got = dsp._smooth_db(x, 22050, att, rel, 16)
                    self.assertTrue(np.array_equal(want, got), (dtype, n, att, rel))

    def test_the_threshold_fit_gives_the_same_answer(self):
        from hypnomix.core import dsp
        from hypnomix.engineer import devices as D, sidechain as SC
        sr = SC.SR
        t = np.arange(int(6 * sr)) / sr
        x = 0.3 * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.5 * t)) * ((t % 3) < 2)
        act, _, _ = D.active(x)
        c = dict(D.NEW_COMP)
        new = D.fit_threshold(x, act, dict(c), 3.5)
        with mock.patch.object(dsp, "_smooth_db", old_smooth_db):
            old = D.fit_threshold(x, act, dict(c), 3.5)
        self.assertEqual(new["threshold_db"], old["threshold_db"])


# ---------------------------------------------------------------- devices: only the tracks that matter
def devices_set(td, secs=3):
    """A Live set of five audio tracks with compressors, a limiter, a gate and two EQ Eights without a low cut (one
    track has rumble, so it gets an eq-lowcut item and the other does not: that item's presence depends on the audio).
    Returns (set path, {track name: wav})."""
    td = Path(td)
    td.mkdir(parents=True, exist_ok=True)
    t = np.arange(SR * secs) / SR
    env = ((t % 1.0) < 0.6) * (0.5 + 0.5 * np.sin(t * 3))
    mixer = lambda b: (f'<Mixer><Volume><Manual Value="1"/><AutomationTarget Id="{b}"/></Volume>'
                       f'<Pan><Manual Value="0"/><AutomationTarget Id="{b + 1}"/></Pan>'
                       f'<Speaker><Manual Value="true"/><AutomationTarget Id="{b + 2}"/></Speaker><Sends/></Mixer>')
    clip = lambda i, fn: (f'<AudioClip Id="{i}" Time="0"><Name Value="take"/><CurrentStart Value="0"/><CurrentEnd Value="{secs * 2}"/>'
                          f'<Loop><LoopStart Value="0"/><LoopEnd Value="{secs * 2}"/><LoopOn Value="false"/><StartRelative Value="0"/></Loop>'
                          f'<IsWarped Value="false"/><WarpMarkers><WarpMarker Id="0" SecTime="0" BeatTime="0"/>'
                          f'<WarpMarker Id="1" SecTime="1" BeatTime="2"/></WarpMarkers><SampleVolume Value="1"/><Disabled Value="false"/>'
                          f'<Fades><FadeInLength Value="0"/><FadeOutLength Value="0"/></Fades>'
                          f'<SampleRef><FileRef><Path Value="{td / fn}"/><RelativePath Value="{fn}"/></FileRef></SampleRef></AudioClip>')
    comp = lambda thr: (f'<Compressor2 Id="0"><On><Manual Value="true"/></On><SideChain><OnOff><Manual Value="false"/></OnOff></SideChain>'
                        f'<Threshold><Manual Value="{thr}"/></Threshold><Ratio><Manual Value="4"/></Ratio>'
                        f'<Attack><Manual Value="5"/></Attack><Release><Manual Value="120"/></Release></Compressor2>')
    limiter = ('<Limiter Id="0"><On><Manual Value="true"/></On><Gain><Manual Value="12"/></Gain>'
               '<Ceiling><Manual Value="-0.3"/></Ceiling></Limiter>')
    gate = '<Gate Id="0"><On><Manual Value="true"/></On><Threshold><Manual Value="0.2"/></Threshold></Gate>'
    eq = '<Eq8 Id="0"><On><Manual Value="true"/></On></Eq8>'
    chains = {"Tr0": comp(0.4), "Tr1": comp(0.3) + limiter, "Tr2": eq + comp(0.5),
              "Tr3": eq + comp(0.2) + comp(0.1), "Tr4": gate + comp(0.35)}
    freqs = {"Tr0": 220, "Tr1": 330, "Tr2": 40, "Tr3": 440, "Tr4": 262}      # Tr2 rumbles
    wavs, body = {}, ""
    for k, (name, devs) in enumerate(chains.items()):
        fn = f"{name}.wav"
        sf.write(str(td / fn), (0.6 * np.sin(2 * np.pi * freqs[name] * t) * env).astype(np.float32), SR)
        wavs[name] = td / fn
        body += (f'<AudioTrack Id="{k + 1}"><Name><EffectiveName Value="{name}"/></Name><AutomationEnvelopes><Envelopes/></AutomationEnvelopes>'
                 f'<DeviceChain>{mixer(10 + 10 * k)}<MainSequencer><Sample><ArrangerAutomation><Events>{clip(k, fn)}</Events>'
                 f'</ArrangerAutomation></Sample></MainSequencer><DeviceChain><Devices>{devs}</Devices></DeviceChain>'
                 f'</DeviceChain></AudioTrack>')
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><Ableton MajorVersion="5" MinorVersion="12.0_12049" Creator="Ableton Live 12.0">'
           f'<LiveSet><NextPointeeId Value="1000"/><Tracks>{body}</Tracks><MainTrack><Name><EffectiveName Value="Main"/></Name>'
           f'<AutomationEnvelopes><Envelopes/></AutomationEnvelopes><DeviceChain>{mixer(900)}<Mixer2/><DeviceChain><Devices/>'
           f'</DeviceChain></DeviceChain><Tempo><Manual Value="120"/></Tempo></MainTrack></LiveSet></Ableton>')
    with gzip.open(td / "Song.als", "wb") as f:
        f.write(xml.encode())
    return td / "Song.als", wavs


class DevicesNarrowed(Scratch):
    def setUp(self):
        super().setUp()
        from hypnomix.engineer import devices as D
        self.D = D
        self.als, self.wavs = devices_set(self.r / "set")
        self.rendered = []

        def fake_hx(*args):                 # the render, from the source files (what it would write for these simple clips)
            if args[0] == "render":
                out = Path(args[args.index("--out") + 1])
                names = args[args.index("--tracks") + 1:args.index("--out")]
                self.rendered.append(list(names))
                for n in names:
                    (out / f"{n}.wav").write_bytes(self.wavs[n].read_bytes())
            return 0, ""
        self.p = mock.patch.object(D, "hx", fake_hx)
        self.p.start()
        self.comps = {"Tr0": 1, "Tr1": 1, "Tr2": 1, "Tr3": 2, "Tr4": 1}     # compressors per track: each costs a threshold fit

    def tearDown(self):
        self.p.stop()
        super().tearDown()

    def fits(self, **kw):
        """(items, findings, how many threshold fits it took)"""
        with mock.patch.object(self.D, "fit_threshold", wraps=self.D.fit_threshold) as ft:
            items, notes, root, tempo = self.D.propose(self.als, **kw)
        return items, self.D.findings(items), ft.call_count, root, notes

    def test_the_set_covers_every_case(self):
        items, fs, fits, _, _ = self.fits()
        self.assertEqual(fits, sum(self.comps.values()))
        kinds = [(f["track"], f["kind"]) for f in fs]
        self.assertIn(("Tr2", "eq-lowcut"), kinds)                  # the rumble gets its item ...
        self.assertNotIn(("Tr3", "eq-lowcut"), kinds)               # ... a clean part with the same EQ does not
        self.assertEqual([f["id"] for f in fs], [f"devices-{n}" for n in range(1, len(fs) + 1)])
        self.assertIn(("Tr4", "gate"), kinds)
        self.assertIn(("Tr1", "limiter"), kinds)

    def test_every_id_is_the_whole_sets_and_only_its_track_is_judged(self):
        _, full, _, _, _ = self.fits()
        self.assertGreaterEqual(len(full), 8)
        for f in full:
            items, fs, fits, _, _ = self.fits(ids=[f["id"]])
            mine = [x for x in fs if x["id"] == f["id"]]
            self.assertEqual(mine, [f], f["id"])                    # the same finding under the same number
            self.assertEqual(fits, self.comps[f["track"]], f["id"])    # only its own track's compressors were fitted
            self.assertEqual({x["track"] for x in fs}, {f["track"]}, f["id"])      # no other track was judged
        total = sum(self.comps.values())
        _, _, fits, _, _ = self.fits(ids=["devices-1", "devices-%d" % len(full)])
        self.assertLess(fits, total)                                # the first and the last: not the middle ones

    def test_two_ids_and_a_focus_keep_the_whole_sets_numbers(self):
        _, full, _, _, _ = self.fits()
        want = {f["id"] for f in full if f["track"] in ("Tr1", "Tr4")}
        _, fs, fits, _, _ = self.fits(ids=sorted(want))
        self.assertEqual([f for f in fs if f["id"] in want], [f for f in full if f["id"] in want])
        self.assertEqual(fits, self.comps["Tr1"] + self.comps["Tr4"])
        _, fs, fits, _, _ = self.fits(focus=["Tr3"])
        self.assertEqual([f for f in fs if f["track"] == "Tr3"], [f for f in full if f["track"] == "Tr3"])
        self.assertEqual(fits, self.comps["Tr3"])                   # Tr4 comes after it: not even counted

    def test_the_written_set_is_the_same(self):
        _, full, _, _, _ = self.fits()
        for f in full:
            if f["applies"] != "set":
                continue
            outs = []
            for kw in ({}, {"ids": [f["id"]]}):
                items, fs, _, root, _ = self.fits(**kw)
                self.assertEqual(self.D.apply_settings(root, [i for i in items if i is not None], fs, {f["id"]}), 1)
                outs.append(ET.tostring(root))
            self.assertEqual(outs[0], outs[1], f["id"])

    def test_render_is_still_every_track_so_the_lengths_do_not_change(self):
        self.fits(ids=["devices-1"])
        self.assertEqual(self.rendered[-1], ["Tr0", "Tr1", "Tr2", "Tr3", "Tr4"])

    def test_ids_that_are_not_devices_ids_judge_the_whole_set(self):
        D = self.D
        self.assertEqual(D.id_numbers("devices-3, devices-5"), {3, 5})
        self.assertEqual(D.id_numbers(["devices-2"]), {2})
        for odd in (None, "", "smooth-1", "devices-1,smooth-2", "devices-x"):
            self.assertEqual(D.id_numbers(odd), set(), odd)
        _, _, fits, _, _ = self.fits(ids=["smooth-1"])
        self.assertEqual(fits, sum(self.comps.values()))

    def test_fix_asks_for_the_tracks_it_changes_only(self):
        from hypnomix.workflow import fix
        sd = self.r / "scan"
        calls = []

        def hx(*args):
            calls.append([str(a) for a in args])
            j = Path(args[args.index("--json") + 1])
            j.write_text('{"findings": []}', encoding="utf-8")
            return 0, ""
        with mock.patch.object(fix, "hx", hx):
            fix.recheck("devices", "x.als", sd, {}, [], "pre", focus=["Tr3", "Tr1", "Tr3"])
            fix.recheck("devices", "x.als", sd, {}, [], "pre")
            fix.recheck("devices", "x.als", sd, {}, [], "pre", focus=["Tr1", None])      # a finding with no track: all of them
            fix.recheck("smooth", "x.als", sd, {}, [], "pre", focus=["Tr1"])
        self.assertEqual([c[c.index("--focus") + 1] for c in calls[:1] for _ in [0]], ["Tr1"])
        self.assertEqual([calls[0][i + 1] for i, a in enumerate(calls[0]) if a == "--focus"], ["Tr1", "Tr3"])
        for c in calls[1:]:
            self.assertNotIn("--focus", c)


# ---------------------------------------------------------------- stems that stay on disk
def stems_folder(td):
    td = Path(td)
    td.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    for name, secs, f in (("01 Kick", 4.0, 60), ("02 Bass", 4.5, 55), ("03 Lead Vocal", 5.0, 300), ("04 Pad", 4.0, 260),
                          ("05 Guitar", 4.8, 330)):
        t = np.arange(int(SR * secs)) / SR
        env = ((t * 1.3) % 1.0 < 0.6) * (0.5 + 0.5 * np.sin(t * 2))
        y = 0.3 * np.sin(2 * np.pi * f * t) * env + rng.normal(0, 0.01, len(t))
        sf.write(str(td / f"{name}.wav"), np.stack([y, y * 0.9], 1), SR, subtype="PCM_16")
    return td


class StemsOnDisk(Scratch):
    def setUp(self):
        super().setUp()
        self.d = stems_folder(self.r / "stems")

    def lazy(self, mb):
        return mock.patch.dict(os.environ, HYPNOMIX_STEMS_LAZY_MB=str(mb))

    def test_a_small_folder_stays_a_list_and_a_big_one_stays_on_disk(self):
        from hypnomix.engineer import masking as M
        stems, sr = M.load_stems(self.d, lazy=True)
        self.assertIsInstance(stems, list)                          # well under the limit: as it always was
        with self.lazy(0):
            lazy, sr2 = M.load_stems(self.d, lazy=True)
            plain, _ = M.load_stems(self.d)                         # the default is still the list
        self.assertIsInstance(lazy, M.StemSet)
        self.assertIsInstance(plain, list)
        self.assertEqual(sr, sr2)
        self.assertEqual(len(lazy), len(stems))
        self.assertEqual(lazy.names, [n for n, _ in stems])
        for (n1, y1), (n2, y2) in zip(stems, lazy):
            self.assertEqual(n1, n2)
            self.assertEqual((y1.shape, y1.dtype), (y2.shape, y2.dtype))
            self.assertTrue(np.array_equal(y1, y2))                 # same samples, padded to the same length
        for (n1, y1), (n2, y2) in zip(stems, lazy):                 # and it can be walked again
            self.assertTrue(np.array_equal(y1, y2))
        self.assertEqual([n for n, _ in lazy.only(["05 Guitar", "01 Kick"])], ["01 Kick", "05 Guitar"])

    def test_only_a_shorter_stem_is_copied_to_pad_it(self):
        from hypnomix.engineer import masking as M
        with mock.patch.object(np, "pad", wraps=np.pad) as pad:
            stems, _ = M.load_stems(self.d)
        lengths = [len(y) for _, y in stems]
        self.assertEqual(len(set(lengths)), 1)
        self.assertEqual(pad.call_count, 4)                         # four are shorter than the fifth: it had five copies

    def test_roles_by_name_read_no_audio_from_disk(self):
        from hypnomix.core import dsp
        from hypnomix.engineer import masking as M, roles
        with self.lazy(0):
            lazy, sr = M.load_stems(self.d, lazy=True)
            plain, _ = M.load_stems(self.d)
        with mock.patch.object(dsp, "load", wraps=dsp.load) as ld:
            got = roles.classify_all(lazy, sr)
        named = [n for n in lazy.names if roles.by_name(n)]
        self.assertEqual(ld.call_count, len(lazy) - len(named))     # only the stems a name leaves open are read
        self.assertEqual(got, roles.classify_all(plain, sr))
        self.assertEqual(list(got), lazy.names)

    def test_masking_and_the_stem_findings_do_not_change(self):
        from hypnomix.engineer import masking as M
        from hypnomix.workflow import scan
        with self.lazy(0):
            lazy, sr = M.load_stems(self.d, lazy=True)
        plain, _ = M.load_stems(self.d)
        self.assertEqual(M.analyse(lazy, sr), M.analyse(plain, sr))
        paths = {p.stem: p for p in self.d.glob("*.wav")}
        self.assertEqual(scan.stem_findings(lazy, sr, paths), scan.stem_findings(plain, sr, paths))

    def test_phase_findings_read_only_the_pairs(self):
        from hypnomix.core import dsp
        from hypnomix.engineer import masking as M
        from hypnomix.workflow import scan
        d = self.r / "pairs"
        d.mkdir()
        y = np.random.default_rng(2).normal(0, 0.2, SR * 2)
        for n, z in (("Kick In", y), ("Kick Out", -np.roll(y, 20)), ("Bass", y * 0.5), ("Lead Vocal", y * 0.3)):
            sf.write(str(d / f"{n}.wav"), np.stack([z, z], 1), SR, subtype="PCM_16")
        with self.lazy(0):
            lazy, sr = M.load_stems(d, lazy=True)
        plain, _ = M.load_stems(d)
        with mock.patch.object(dsp, "load", wraps=dsp.load) as ld:
            got = scan.phase_findings(lazy, sr)
        self.assertEqual(ld.call_count, 2)                          # Kick In and Kick Out, not all four
        self.assertEqual(got, scan.phase_findings(plain, sr))
        self.assertTrue(got)

    def test_balance_gives_the_same_numbers(self):
        from hypnomix.engineer import balance as B
        with self.lazy(0):
            stems, sr, rows = B.measure(self.d)
            self.assertEqual(type(stems).__name__, "StemSet")
            lazy_res = B.propose(stems, sr, rows, vocal_over_band=3.0)
        with self.lazy(10 ** 9):
            stems2, sr2, rows2 = B.measure(self.d)
            self.assertIsInstance(stems2, list)
            res = B.propose(stems2, sr2, rows2, vocal_over_band=3.0)
        self.assertEqual(rows, rows2)
        self.assertEqual(lazy_res, res)

    def test_the_band_sum_is_the_same_as_summing_the_copies(self):
        from hypnomix.core import dsp
        from hypnomix.engineer import balance as B
        rng = np.random.default_rng(5)
        stems = [(f"s{i}", rng.normal(0, 0.1 * (i + 1), (SR, 2))) for i in range(4)]
        gains = {"s0": -2.0, "s1": 1.5, "s3": -6.0}
        skip = {"s2"}
        parts = [y * dsp.undb(gains.get(n, 0.0)) for n, y in stems if n not in skip]
        want = float(dsp.active_lufs(sum(parts), SR))
        self.assertEqual(B.band_lufs(stems, SR, gains, skip), want)
        self.assertIsNone(B.band_lufs(stems, SR, gains, {n for n, _ in stems}))

    def test_a_mono_stem_beside_a_stereo_one_adds_up_as_sum_does(self):
        from hypnomix.core import dsp
        from hypnomix.engineer import balance as B
        rng = np.random.default_rng(6)
        mono = lambda s: rng.normal(0, s, (SR, 1))
        stereo = lambda s: rng.normal(0, s, (SR, 2))
        for order in ((mono, stereo, stereo), (stereo, mono, stereo), (mono, mono, stereo), (stereo, stereo, mono)):
            stems = [(f"s{i}", make(0.1 * (i + 1))) for i, make in enumerate(order)]
            gains = {"s0": -2.0, "s2": -3.0}
            parts = [y * dsp.undb(gains.get(n, 0.0)) for n, y in stems]
            self.assertEqual(B.band_lufs(stems, SR, gains, set()), float(dsp.active_lufs(sum(parts), SR)))
        stems = [("a", rng.normal(0, 0.1, (SR, 2)).astype(np.float32)), ("b", rng.normal(0, 0.1, (SR, 2)))]   # two widths of float
        parts = [y * dsp.undb(0.0) for _, y in stems]
        self.assertEqual(B.band_lufs(stems, SR, {}, set()), float(dsp.active_lufs(sum(parts), SR)))


# ---------------------------------------------------------------- the pitch tracker's answer is kept
class PitchCache(Scratch):
    def setUp(self):
        super().setUp()
        from hypnomix.studio import tune
        self.T = tune
        self.calls = []

        def fake(y, sr):
            self.calls.append(len(y))
            return np.linspace(48.0, 60.0, 1 + len(y) // 220)
        self.p = mock.patch.object(tune, "_track_pitch", fake)
        self.p.start()
        self.y = np.random.default_rng(0).normal(0, 0.1, SR * 2).astype(np.float32)

    def tearDown(self):
        self.p.stop()
        super().tearDown()

    def files(self):
        return sorted((self.r / "home" / "cache" / "pitch").glob("pyin-*.npy"))

    def test_the_same_audio_is_tracked_once(self):
        a = self.T.track_pitch(self.y, SR)
        b = self.T.track_pitch(self.y.copy(), SR)                   # a copy of the same take hits too
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(np.array_equal(a, b))
        self.assertEqual(len(self.files()), 1)

    def test_changed_audio_or_rate_or_version_is_never_answered_from_the_old(self):
        self.T.track_pitch(self.y, SR)
        z = self.y.copy()
        z[100] += 1e-4                                              # one sample, one part in ten thousand
        self.T.track_pitch(z, SR)
        self.T.track_pitch(self.y, 22050)
        with mock.patch.object(self.T, "PITCH_VERSION", 2):
            self.T.track_pitch(self.y, SR)
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(len(self.files()), 4)

    def test_the_cache_is_bounded_and_can_be_off(self):
        with mock.patch.object(self.T, "PITCH_KEEP", 3):
            for i in range(7):
                self.T.track_pitch(self.y + i, SR)
        self.assertLessEqual(len(self.files()), 3)
        n = len(self.calls)
        with mock.patch.dict(os.environ, HYPNOMIX_NO_CACHE="1"):
            self.T.track_pitch(self.y + 6, SR)
            self.T.track_pitch(self.y + 6, SR)
        self.assertEqual(len(self.calls), n + 2)

    def test_a_damaged_file_is_measured_again(self):
        self.T.track_pitch(self.y, SR)
        self.files()[0].write_bytes(b"not a numpy file")
        got = self.T.track_pitch(self.y, SR)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(got), 1 + len(self.y) // 220)


# ---------------------------------------------------------------- true peak one stretch at a time
class TruePeak(unittest.TestCase):
    def whole(self, y, sr):
        from hypnomix.core import dsp
        return float(dsp.db(np.max(np.abs(dsp._sig().resample_poly(y, 4, 1, axis=0)))))

    def test_the_answer_is_the_whole_files_to_the_last_bit(self):
        from hypnomix.core import dsp
        rng = np.random.default_rng(1)
        n = SR * 3
        c = int(0.5 * SR)
        for at in (c - 1, c, c + 1, 2 * c - 3, 2 * c + 5, n - 2, 7):      # peaks on and around the chunk joins
            y = rng.normal(0, 0.1, (n, 2))
            y[at, 0] = 0.9
            y[at + 1 if at + 1 < n else at - 1, 0] = -0.8                 # an inter-sample peak between two samples
            self.assertEqual(dsp.true_peak(y, SR, chunk_s=0.5), self.whole(y, SR), at)
        y = rng.normal(0, 0.1, n)                                         # a mono file too
        self.assertEqual(dsp.true_peak(y, SR, chunk_s=0.5), self.whole(y, SR))

    def test_no_copy_of_the_whole_file_is_made(self):
        import scipy.signal
        from hypnomix.core import dsp
        sizes = []

        class Spy:
            def resample_poly(self, x, up, down, axis=0):
                sizes.append(len(x))
                return scipy.signal.resample_poly(x, up, down, axis=axis)
        y = np.random.default_rng(2).normal(0, 0.1, (SR * 5, 2))
        with mock.patch.object(dsp, "_sig", return_value=Spy()):
            dsp.true_peak(y, SR, chunk_s=0.5, pad=1024)
        self.assertGreater(len(sizes), 5)
        self.assertLessEqual(max(sizes), int(0.5 * SR) + 2 * 1024)       # never more than a stretch and its margins
        sizes.clear()
        with mock.patch.object(dsp, "_sig", return_value=Spy()):
            dsp.true_peak(y[: SR], SR)                                   # a short file: one pass, as before
        self.assertEqual(sizes, [SR])

    def test_the_shipped_stretch_is_what_keeps_a_long_song_in_pieces(self):
        import scipy.signal
        from hypnomix.core import dsp
        sizes = []

        class Spy:
            def resample_poly(self, x, up, down, axis=0):
                sizes.append(len(x))
                return scipy.signal.resample_poly(x, up, down, axis=axis)
        sr = 8000                                                         # 50 s at a low rate: longer than the default stretch, still small
        y = np.random.default_rng(2).normal(0, 0.1, (50 * sr, 2))
        with mock.patch.object(dsp, "_sig", return_value=Spy()):
            dsp.true_peak(y, sr)                                          # the defaults, as release / compare / master call it
        self.assertGreater(len(sizes), 1)
        self.assertLessEqual(max(sizes), 25 * sr)                         # a 20 s stretch and its margins, never the 50 s


# ---------------------------------------------------------------- HPSS for the key
class KeyHarmonic(unittest.TestCase):
    def signal(self, seconds=8, sr=22050):
        rng = np.random.default_rng(4)
        t = np.arange(int(seconds * sr)) / sr
        y = sum(0.2 * np.sin(2 * np.pi * f * t) for f in (220, 277.2, 329.6)) * (0.6 + 0.4 * np.sin(t * 1.7))
        for k in range(0, len(t) - 400, sr // 3):
            y[k:k + 400] += rng.normal(0, 0.4, 400)
        return y.astype(np.float32)

    def test_the_median_filters_are_scipys_to_the_last_bit(self):
        from scipy.ndimage import median_filter
        from hypnomix.ears import key as K
        S = np.abs(np.random.default_rng(0).normal(0, 1, (60, 90))).astype(np.float32)
        S[::7, ::5] = 0.0                                               # ties and zeros
        for axis in (0, 1):
            size = [31 if i == axis else 1 for i in range(2)]
            self.assertTrue(np.array_equal(K._median31(S, axis), median_filter(S, size=size, mode="reflect")))

    def test_harmonic_is_librosas_whole_and_within_rounding_in_blocks(self):
        import librosa
        from hypnomix.ears import key as K
        y = self.signal()
        want = librosa.effects.harmonic(y, margin=3)
        self.assertTrue(np.array_equal(K.harmonic(y, margin=3), want))      # the whole-song path: exact
        sizes = []
        real = K._harmonic_block
        with mock.patch.object(K, "_harmonic_block", side_effect=lambda s, m, n: (sizes.append(len(s)), real(s, m, n))[1]):
            got = K.harmonic(y, margin=3, block_s=1.0)                  # a block a second, with a second and a half either side
        # The blocked path was exact too on two Pythons and numpy 2.0 to 2.4, but on an Apple-silicon runner with librosa 1.0 and
        # numpy 2.5 it differs by rounding. The bound below is far under a seam error (the next test measures one); the size is printed.
        err = float(np.max(np.abs(got.astype(np.float64) - want.astype(np.float64))))
        self.assertLessEqual(err, 1e-5 * float(np.max(np.abs(want))), f"blocks differ from the whole song by {err:g}")
        self.assertGreater(len(sizes), 4)
        self.assertLess(max(sizes), len(y))                             # never the whole song in one piece

    def test_the_bound_on_the_blocked_path_catches_a_real_seam(self):
        import librosa
        from hypnomix.ears import key as K
        y = self.signal()
        want = librosa.effects.harmonic(y, margin=3)
        peak = float(np.max(np.abs(want)))
        with mock.patch.object(K, "_BLOCK_MARGIN_FRAMES", 1):           # a margin far too short for the median filters to see past
            got = K.harmonic(y, margin=3, block_s=1.0)
        err = float(np.max(np.abs(got.astype(np.float64) - want.astype(np.float64))))
        self.assertGreater(err, 1e-4 * peak, f"a one-frame margin differs from the whole song by only {err:g}, so the bound would not notice a seam")

    def test_the_shipped_block_is_what_keeps_a_long_song_in_pieces(self):
        from hypnomix.ears import key as K
        y = np.zeros(int(150 * 22050), dtype=np.float32)                # two and a half minutes (the block work is stubbed: only sizes count)
        sizes = []
        with mock.patch.object(K, "_harmonic_block", side_effect=lambda s, m, n: (sizes.append(len(s)), np.zeros_like(s))[1]):
            K.harmonic(y, margin=3)                                     # the defaults, as the album key calls it
        self.assertGreater(len(sizes), 1)
        self.assertLessEqual(max(sizes), 62 * 22050 + 2 * 64 * 512)     # a minute and its margins, never the 150 s


if __name__ == "__main__":
    unittest.main()
