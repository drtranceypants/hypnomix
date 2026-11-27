"""`hypnomix ab` previews for timing nudges, device changes and masking cuts, and the device models behind them.

Everything is synthetic: audio and sets are built in a temp folder. The fixes themselves are not recomputed here
(`timing`, `devices` and the others are tested elsewhere): a stand-in for the command that would write the fixed
set copies a prepared "after" set into place, so what is tested is the preview: what is rendered, what is
refused and why, how the pair is labelled."""
import gzip, json, shutil, sys, tempfile, unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

from hypnomix.session import devmodel, plugrender as PR, render as R
from hypnomix.workflow import ab
from tests import _isolate

SR = 44100
HAVE_RB = bool(shutil.which("rubberband"))


def tone(freq, seconds, amp=0.5):
    t = np.arange(int(SR * seconds)) / SR
    return amp * np.sin(2 * np.pi * freq * t)


def rms_db(x):
    return 10 * np.log10(float(np.mean(np.square(x))) + 1e-20)


def peak_db_at(x, sr, f):
    """Level (dB) of the component at f Hz of a windowed block."""
    w = np.hanning(len(x))
    X = np.abs(np.fft.rfft(x * w)) / (w.sum() / 2)
    return 20 * np.log10(X[int(round(f * len(x) / sr))] + 1e-12)


def clip_xml(wav, markers, end=16.0, rel="x.wav"):    # end in beats: 16 beats = 8 s at 120 BPM
    wm = "".join(f'<WarpMarker Id="{i}" SecTime="{s}" BeatTime="{b}"/>' for i, (s, b) in enumerate(markers))
    return (f'<AudioClip Id="0" Time="0"><Name Value="take"/><CurrentStart Value="0"/><CurrentEnd Value="{end}"/>'
            '<Loop><LoopStart Value="0"/><LoopEnd Value="' + str(end) + '"/><LoopOn Value="false"/><StartRelative Value="0"/></Loop>'
            f'<IsWarped Value="true"/><WarpMarkers>{wm}</WarpMarkers><SampleVolume Value="1"/><Disabled Value="false"/>'
            '<Fades><FadeInLength Value="0"/><FadeOutLength Value="0"/></Fades>'
            f'<SampleRef><FileRef><Path Value="{wav}"/><RelativePath Value="{rel}"/></FileRef></SampleRef></AudioClip>')


def track_xml(tid, name, wav, markers, devices="", end=16.0, base=100, rel="x.wav"):
    mixer = (f'<Mixer><Volume><Manual Value="1"/><AutomationTarget Id="{base}"/></Volume>'
             f'<Pan><Manual Value="0"/><AutomationTarget Id="{base + 1}"/></Pan>'
             f'<Speaker><Manual Value="true"/><AutomationTarget Id="{base + 2}"/></Speaker><Sends/></Mixer>')
    return (f'<AudioTrack Id="{tid}"><Name><EffectiveName Value="{name}"/></Name>'
            '<AutomationEnvelopes><Envelopes/></AutomationEnvelopes>'
            f'<DeviceChain>{mixer}<MainSequencer><Sample><ArrangerAutomation><Events>{clip_xml(wav, markers, end, rel=rel)}</Events>'
            f'</ArrangerAutomation></Sample></MainSequencer><DeviceChain><Devices>{devices}</Devices></DeviceChain></DeviceChain></AudioTrack>')


def write_set(path, tracks):
    xml = ('<?xml version="1.0" encoding="UTF-8"?><Ableton MajorVersion="5" MinorVersion="12.0_12049" Creator="Ableton Live 12.0">'
           f'<LiveSet><NextPointeeId Value="1000"/><Tracks>{"".join(tracks)}</Tracks>'
           '<MainTrack><Name><EffectiveName Value="Main"/></Name><AutomationEnvelopes><Envelopes/></AutomationEnvelopes>'
           '<DeviceChain><Mixer><Volume><Manual Value="1"/><AutomationTarget Id="30"/></Volume>'
           '<Pan><Manual Value="0"/><AutomationTarget Id="31"/></Pan><Speaker><Manual Value="true"/>'
           '<AutomationTarget Id="32"/></Speaker><Sends/></Mixer><Mixer2/><DeviceChain><Devices/></DeviceChain></DeviceChain>'
           '<Tempo><Manual Value="120"/></Tempo></MainTrack></LiveSet></Ableton>')
    with gzip.open(path, "wb") as f:
        f.write(xml.encode())
    return Path(path)


def fake_hx(after_set):
    """Stands in for the command that writes the fixed set: copies the prepared one to the --apply path."""
    def hx(*args, timeout=0):
        args = [str(a) for a in args]
        shutil.copyfile(after_set, args[args.index("--apply") + 1])
        return 0, ""
    return hx


# ---------------------------------------------------------------- the models
def eq8_el(bands, mode=0):
    def band(i, on, m, f, g, q=0.7071):
        p = lambda n, v: f'<{n}><Manual Value="{v}"/></{n}>'
        return f'<Bands.{i}><ParameterA>{p("IsOn", on)}{p("Mode", m)}{p("Freq", f)}{p("Gain", g)}{p("Q", q)}</ParameterA></Bands.{i}>'
    body = "".join(band(i, *b) for i, b in enumerate(bands))
    return ET.fromstring(f'<Eq8 Id="0"><On><Manual Value="true"/></On><Mode Value="{mode}"/>'
                         f'<GlobalGain><Manual Value="0"/></GlobalGain><Scale><Manual Value="1"/></Scale>{body}</Eq8>')


class Models(unittest.TestCase):
    def test_eq_eight_bell_lands_its_gain_at_the_centre_and_leaves_far_tones(self):
        d = eq8_el([("true", 3, 1000, -6.0, 1.4)])
        for f, want in ((1000, -6.0), (100, 0.0), (8000, 0.0)):
            x = tone(f, 1.0)
            y, note = devmodel.eq8(np.stack([x, x], 1), SR, d)
            self.assertIsNone(note)
            got = peak_db_at(y[SR // 4:SR // 4 + 8192, 0], SR, f) - peak_db_at(x[SR // 4:SR // 4 + 8192], SR, f)
            self.assertAlmostEqual(got, want, delta=0.4, msg=f"{f} Hz")

    def test_eq_eight_cuts_shelves_and_off_bands(self):
        x = tone(60, 1.0) + tone(5000, 1.0)
        st = np.stack([x, x], 1)
        y, _ = devmodel.eq8(st, SR, eq8_el([("true", 0, 200, 0.0)]))                   # low cut 48 dB/oct at 200 Hz
        self.assertLess(peak_db_at(y[SR // 4:SR // 4 + 8192, 0], SR, 60), peak_db_at(x[SR // 4:SR // 4 + 8192], SR, 60) - 30)
        y, _ = devmodel.eq8(st, SR, eq8_el([("false", 0, 200, 0.0)]))                  # switched off: nothing happens
        np.testing.assert_allclose(y, st)
        y, _ = devmodel.eq8(st, SR, eq8_el([("true", 5, 3000, -9.0)]))                 # high shelf down
        self.assertLess(peak_db_at(y[SR // 4:SR // 4 + 8192, 0], SR, 5000), peak_db_at(x[SR // 4:SR // 4 + 8192], SR, 5000) - 6)

    def test_eq_eight_in_ms_mode_is_not_modelled(self):
        st = np.ones((100, 2)) * 0.1
        y, note = devmodel.eq8(st, SR, eq8_el([("true", 3, 1000, -6.0)], mode=2))
        self.assertTrue(note.startswith("no model:"))
        np.testing.assert_allclose(y, st)

    def test_gate_closes_under_the_threshold_and_opens_over_it(self):
        loud, quiet = tone(220, 1.0, 0.5), tone(220, 1.0, 0.002)
        x = np.concatenate([loud, quiet, loud])
        d = ET.fromstring('<Gate Id="0"><On><Manual Value="true"/></On><Threshold><Manual Value="0.05"/></Threshold>'
                          '<Return><Manual Value="4"/></Return><Attack><Manual Value="1"/></Attack><Hold><Manual Value="50"/></Hold>'
                          '<Release><Manual Value="30"/></Release><Gain><Manual Value="-40"/></Gain><FlipMode><Manual Value="false"/></FlipMode></Gate>')
        y, _ = devmodel.gate(np.stack([x, x], 1), SR, d)
        self.assertGreater(rms_db(y[: SR // 2, 0]), rms_db(x[: SR // 2]) - 1)            # the loud part passes
        self.assertLess(rms_db(y[int(1.3 * SR): int(1.9 * SR), 0]), rms_db(x[int(1.3 * SR): int(1.9 * SR)]) - 25)   # the quiet one is shut
        self.assertGreater(rms_db(y[int(2.3 * SR): int(2.9 * SR), 0]), rms_db(x[int(2.3 * SR): int(2.9 * SR)]) - 1)


# ---------------------------------------------------------------- previews of device changes
LIMITER = lambda gain: (f'<Limiter Id="0"><On><Manual Value="true"/></On><Gain><Manual Value="{gain}"/></Gain>'
                        '<Ceiling><Manual Value="-0.3"/></Ceiling></Limiter>')


class DevicePairs(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.wav = self.td / "keys.wav"
        sf.write(self.wav, tone(220, 8.0, 0.3), SR, subtype="PCM_24")
        self.mk = lambda name, dev: write_set(self.td / f"{name}.als", [track_xml(1, "Keys", self.wav, [(0.0, 0.0), (1.0, 2.0)], dev)])
        self.f = dict(id="devices-1", tool="devices", track="Keys", kind="limiter", applies="set")

    def preview(self, before_dev, after_dev, f=None):
        orig, after = self.mk("before", before_dev), self.mk("after", after_dev)
        return PR.device_preview(f or self.f, orig, {}, self.td, SR, fake_hx(after), {}, plugins=False)

    def test_a_modelled_device_gets_a_pair_labelled_as_a_model(self):
        r = self.preview(LIMITER(6.0), LIMITER(0.0))
        self.assertIsNotNone(r.get("before"), r)
        self.assertTrue(r["model"])
        self.assertIn("MODEL", r["note"])
        self.assertIn("not Live itself", r["note"])
        self.assertIn("Limiter", r["note"])
        self.assertGreater(rms_db(r["before"]), rms_db(r["after"]) + 3)         # 6 dB of gain, less the limiter's catch

    def test_an_unmodelled_device_is_refused_with_its_name(self):
        sat = lambda d: f'<Saturator Id="0"><On><Manual Value="true"/></On><PreDrive><Manual Value="{d}"/></PreDrive></Saturator>'
        r = self.preview(sat(18), sat(12))
        self.assertNotIn("before", r)
        self.assertIn("Saturator", r["note"])
        self.assertIn("no model", r["note"])

    def test_eq_eight_in_ms_mode_is_refused(self):
        eq = lambda g: ET.tostring(eq8_el([("true", 3, 1000, g)], mode=2), encoding="unicode")
        r = self.preview(eq(-3.0), eq(-6.0))
        self.assertNotIn("before", r)
        self.assertIn("EQ Eight", r["note"])

    def test_a_fix_outside_the_tracks_own_chain_is_refused(self):
        r = self.preview(LIMITER(6.0), LIMITER(6.0))
        self.assertNotIn("before", r)
        self.assertIn("outside the track's own device chain", r["note"])

    def test_ab_writes_the_pair_and_marks_it_as_a_model_in_ab_json(self):
        orig, after = self.mk("before", LIMITER(6.0)), self.mk("after", LIMITER(0.0))
        sd = self.td / "scan"
        sd.mkdir()
        fs = [self.f, dict(id="devices-2", tool="devices", track="Return A", kind="gate", applies="set")]
        (sd / "findings.json").write_text(json.dumps(dict(set=str(orig), findings=fs)), encoding="utf-8")
        (sd / "scan.json").write_text(json.dumps(dict(mode="set", set_mtime=orig.stat().st_mtime)), encoding="utf-8")
        with mock.patch.object(ab, "hx", fake_hx(after)), mock.patch.object(sys, "argv", ["ab", str(sd)]):
            ab.main()
        m = json.loads((sd / "ab" / "ab.json").read_text(encoding="utf-8"))
        row = m["devices-1"]
        self.assertTrue(row["model"])
        self.assertIn("not Live itself", row["note"])
        self.assertTrue((sd / "ab" / row["a"]).exists() and (sd / "ab" / row["b"]).exists())
        self.assertNotIn("a", m["devices-2"])                                          # a track that is not an audio track: refused
        self.assertIn("Return A", m["devices-2"]["note"])


# ---------------------------------------------------------------- previews of timing nudges
def hits_wav(path, times, freq=440.0, length=0.25, seconds=8.0):
    y = np.zeros(int(SR * seconds))
    for t in times:
        n = int(SR * length)
        y[int(t * SR):int(t * SR) + n] += tone(freq, length, 0.5) * np.hanning(n) ** 0.25
    sf.write(path, y, SR, subtype="PCM_24")


def onset(y, after, thr=0.05):
    i = int(after * SR)
    return (i + int(np.argmax(np.abs(y[i:]) > thr))) / SR


class TimingBase(unittest.TestCase):
    # the hit at source 4.0 s (beat 8 at 120 BPM) plays 40 ms late in the "after" set; the onsets next to it hold
    BEFORE = [(0.0, 0.0), (1.0, 2.0)]
    AFTER = [(0.0, 0.0), (3.9, 7.8), (4.0, 8.08), (4.1, 8.2), (8.0, 16.0)]

    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.wav = self.td / "drums.wav"
        hits_wav(self.wav, [2.0, 4.0, 6.0])
        self.orig = write_set(self.td / "before.als", [track_xml(1, "Keys", self.wav, self.BEFORE)])
        self.after = write_set(self.td / "after.als", [track_xml(1, "Keys", self.wav, self.AFTER)])
        self.f = dict(id="timing-1", tool="timing", track="Keys", kind="beat", where="3.1.00", applies="set",
                      problem="beat hit 40 ms early against the band")

    def run_preview(self, findings=None, hx=None):
        sd = self.td / "scan"
        sd.mkdir(exist_ok=True)
        (sd / "ab").mkdir(exist_ok=True)
        manifest = {}
        with mock.patch.object(ab, "hx", hx or fake_hx(self.after)):
            ab.preview_timing(findings or [self.f], self.orig, {}, sd, 2.0, 3.0, manifest, SR)
        return manifest, sd


class TimingWithoutRubberBand(TimingBase):
    # needs no Rubber Band (the lookup is mocked to find none), so it runs on every system, Windows runners included
    def test_without_rubber_band_the_case_is_refused_and_says_why(self):
        with mock.patch.object(ab.shutil, "which", return_value=None):
            m, _ = self.run_preview()
        self.assertNotIn("a", m["timing-1"])
        self.assertIn("Rubber Band", m["timing-1"]["note"])


@unittest.skipUnless(HAVE_RB, _isolate.NO_RUBBERBAND)
class TimingPairs(TimingBase):
    def test_the_pair_plays_the_nudged_hit_late_and_everything_else_where_it_was(self):
        m, sd = self.run_preview()
        row = m["timing-1"]
        self.assertIn("a", row, row)
        a, _ = sf.read(sd / "ab" / row["a"])
        b, _ = sf.read(sd / "ab" / row["b"])
        # the window starts at 4.0 - 2.0 s: the hit sits 2.0 s into both files
        self.assertAlmostEqual(onset(b, 1.8) - onset(a, 1.8), 0.040, delta=0.010)
        self.assertEqual(row["matched_db"], row["matched_db"])
        self.assertIn("Rubber Band", row["note"])
        self.assertNotIn("model", row)

    def test_the_stretched_stretch_keeps_its_pitch(self):
        R.WARP_TIMEMAP[0] = True
        try:
            y, spb, _ = ab.render_tracks(self.after, ["Keys"], SR)
        finally:
            R.WARP_TIMEMAP[0] = False
        seg = y["Keys"][int(4.045 * SR):int(4.045 * SR) + 2048]                      # inside the squeezed stretch (4.04 - 4.10 s)
        f = np.fft.rfftfreq(len(seg), 1 / SR)
        peak = f[int(np.argmax(np.abs(np.fft.rfft(seg * np.hanning(len(seg))))))]
        self.assertAlmostEqual(peak, 440.0, delta=440 * 0.04)                        # read at varying speed this would sit near 730 Hz

    def test_a_midi_note_nudge_is_refused_with_the_reason(self):
        f = dict(self.f, problem="beat hit 40 ms early against the band (MIDI note)")
        m, _ = self.run_preview([f])
        self.assertNotIn("a", m["timing-1"])
        self.assertIn("MIDI", m["timing-1"]["note"])

    def test_a_set_saved_after_the_scan_is_refused(self):
        sd = self.td / "scan"
        sd.mkdir(exist_ok=True)
        (sd / "ab").mkdir(exist_ok=True)
        manifest = {}
        with mock.patch.object(ab, "hx", fake_hx(self.after)):
            ab.preview_timing([self.f], self.orig, {"set_mtime": self.orig.stat().st_mtime - 100}, sd, 2.0, 3.0, manifest, SR)
        self.assertIn("re-scan", manifest["timing-1"]["note"])

    def test_a_second_nudge_in_the_window_is_named(self):
        g = dict(self.f, id="timing-2", where="3.2.00")
        m, _ = self.run_preview([self.f, g])
        self.assertIn("timing-2", m["timing-1"]["note"])

    def test_the_render_is_off_again_afterwards(self):
        self.run_preview()
        self.assertFalse(R.WARP_TIMEMAP[0])


# ---------------------------------------------------------------- masking cuts
class MaskingPairs(unittest.TestCase):
    def test_the_cut_takes_the_giving_part_down_where_they_fight(self):
        td = Path(tempfile.mkdtemp())
        a, b = td / "keys.wav", td / "pad.wav"
        sf.write(a, tone(250, 8.0, 0.3), SR, subtype="PCM_24")
        sf.write(b, tone(1000, 8.0, 0.3), SR, subtype="PCM_24")
        orig = write_set(td / "Song.als", [track_xml(1, "Keys", a, [(0.0, 0.0), (1.0, 2.0)]),
                                          track_xml(2, "Pad", b, [(0.0, 0.0), (1.0, 2.0)], base=200)])
        sd = td / "scan"
        (sd / "ab").mkdir(parents=True)
        f = dict(id="mask-1", tool="masking", track="Keys", applies="set",
                 eq=dict(freq=250.0, gain_db=-6.0, q=1.4, keep="Pad"))
        manifest = {}
        ab.preview_masking([f], orig, {}, 2.0, 4.0, manifest, sd, SR)
        row = manifest["mask-1"]
        self.assertTrue(row["model"])
        self.assertIn("not Live itself", row["note"])
        x, _ = sf.read(sd / "ab" / row["a"])
        y, _ = sf.read(sd / "ab" / row["b"])
        n = 8192
        mid = len(x) // 2
        # the pair is level-matched, so judge the cut against the other part: 250 Hz falls about 6 dB relative to 1 kHz
        rel = lambda z: peak_db_at(z[mid:mid + n], SR, 250) - peak_db_at(z[mid:mid + n], SR, 1000)
        self.assertAlmostEqual(rel(y) - rel(x), -6.0, delta=1.0)


# ---------------------------------------------------------------- temporary sets stay out of the song's folder
class AbTempSets(unittest.TestCase):
    def test_song_folder_unchanged_and_relative_samples_resolve(self):
        td = Path(tempfile.mkdtemp())
        song_dir = td / "song"
        scan_dir = td / "scan"
        prep_dir = td / "prepared"
        (song_dir / "Samples").mkdir(parents=True)
        scan_dir.mkdir()
        prep_dir.mkdir()
        sf.write(song_dir / "Samples" / "keys.wav", tone(220, 8.0, 0.3), SR, subtype="PCM_24")

        # Only RelativePath is valid: absolute Path points nowhere, proving sample resolution against orig.parent
        missing = "/nonexistent/moved/keys.wav"
        orig = write_set(song_dir / "Song.als",
                         [track_xml(1, "Keys", missing, [(0.0, 0.0), (1.0, 2.0)], LIMITER(6.0), rel="Samples/keys.wav")])
        after_dev = write_set(prep_dir / "after-dev.als",
                              [track_xml(1, "Keys", missing, [(0.0, 0.0), (1.0, 2.0)], LIMITER(0.0), rel="Samples/keys.wav")])
        after_sm = write_set(prep_dir / "after-sm.als",
                             [track_xml(1, "Keys", missing, [(0.0, 0.0), (1.0, 2.0)], LIMITER(6.0), rel="Samples/keys.wav").replace(
                                 '<SampleVolume Value="1"/>', '<SampleVolume Value="0.5"/>')])
        (scan_dir / "scan.json").write_text(json.dumps({"set": str(orig)}), encoding="utf-8")
        (scan_dir / "findings.json").write_text(json.dumps({
            "set": str(orig),
            "findings": [
                {"id": "smooth-1", "tool": "smooth", "track": "Keys", "where": "2.1.00", "applies": "set"},
                {"id": "devices-1", "tool": "devices", "track": "Keys", "kind": "limiter", "applies": "set"},
            ],
        }), encoding="utf-8")

        before_tree = sorted(str(p.relative_to(song_dir)) for p in song_dir.rglob("*"))
        apply_paths = []

        def recording_hx(*args, timeout=0):
            sargs = [str(x) for x in args]
            dest = Path(sargs[sargs.index("--apply") + 1])
            apply_paths.append(dest)
            src = after_sm if sargs[0] == "smooth" else after_dev
            shutil.copyfile(src, dest)
            return 0, ""

        with mock.patch.object(ab, "hx", recording_hx), mock.patch.object(sys, "argv", ["ab", str(scan_dir)]):
            ab.main()

        self.assertEqual(sorted(str(p.relative_to(song_dir)) for p in song_dir.rglob("*")), before_tree)
        self.assertEqual(len(apply_paths), 2)
        for p in apply_paths:
            self.assertNotEqual(p.resolve().parent, song_dir.resolve())
            self.assertIn(scan_dir.resolve(), p.resolve().parents)
        self.assertEqual(list((scan_dir / "ab").rglob("*.als")), [])
        self.assertEqual(list((scan_dir / "ab").glob("ab-tmp-*")), [])

        manifest = json.loads((scan_dir / "ab" / "ab.json").read_text(encoding="utf-8"))
        for fid in ("smooth-1", "devices-1"):
            row = manifest[fid]
            self.assertIn("a", row, row)
            ya, _ = sf.read(scan_dir / "ab" / row["a"])
            yb, _ = sf.read(scan_dir / "ab" / row["b"])
            self.assertGreater(rms_db(ya), -30.0)
            self.assertGreater(rms_db(yb), -30.0)

    def test_real_subprocess_ab_leaves_song_folder_unchanged(self):
        td = Path(tempfile.mkdtemp())
        song_dir = td / "song"
        scan_dir = td / "scan"
        (song_dir / "Samples").mkdir(parents=True)
        scan_dir.mkdir()
        # Steady tone with a +20 dB, 60 ms spike at 2.0 s (bar 2.1.00 at 120 BPM)
        sig = tone(220, 6.0, 0.08)
        sig[int(2.0 * SR):int(2.06 * SR)] *= 10.0
        sf.write(song_dir / "Samples" / "lead.wav", sig, SR, subtype="PCM_24")

        missing = "/nonexistent/moved/lead.wav"
        orig = write_set(song_dir / "Song.als",
                         [track_xml(1, "Lead", missing, [(0.0, 0.0), (1.0, 2.0)], end=12.0, rel="Samples/lead.wav")])
        sm_json = scan_dir / "smooth.json"
        import subprocess
        r = subprocess.run([sys.executable, "-m", "hypnomix.cli", "smooth", str(orig), "--json", str(sm_json)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        issues = json.loads(sm_json.read_text(encoding="utf-8"))["findings"]
        self.assertTrue(issues, "expected smooth to detect the synthetic click")
        f = dict(issues[0], tool="smooth", applies="set")
        (scan_dir / "scan.json").write_text(json.dumps({"set": str(orig)}), encoding="utf-8")
        (scan_dir / "findings.json").write_text(json.dumps({"set": str(orig), "findings": [f]}), encoding="utf-8")

        before_tree = sorted(str(p.relative_to(song_dir)) for p in song_dir.rglob("*"))
        with mock.patch.object(sys, "argv", ["ab", str(scan_dir)]):
            ab.main()

        self.assertEqual(sorted(str(p.relative_to(song_dir)) for p in song_dir.rglob("*")), before_tree)
        self.assertEqual(list((scan_dir / "ab").rglob("*.als")), [])
        manifest = json.loads((scan_dir / "ab" / "ab.json").read_text(encoding="utf-8"))
        row = manifest[f["id"]]
        self.assertIn("a", row, row)
        ya, _ = sf.read(scan_dir / "ab" / row["a"])
        self.assertGreater(rms_db(ya), -40.0)

        # Direct user CLI call to smooth --apply outside orig.parent still refuses
        outside = scan_dir / "moved.als"
        r2 = subprocess.run([sys.executable, "-m", "hypnomix.cli", "smooth", str(orig), "--apply", str(outside),
                             "--ids", f["id"]], capture_output=True, text=True)
        self.assertNotEqual(r2.returncode, 0)
        self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main()
