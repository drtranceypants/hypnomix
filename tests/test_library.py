"""library: which sets count (newest per song, no packs / backups / templates), the cache, what is read from a
set's devices, and when each 'where you could improve' suggestion fires."""
import gzip, json, os, tempfile, time, unittest
from pathlib import Path

import numpy as np

from hypnomix.workflow import library as L


def touch(p, age_days=0.0, data=b"x"):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    t = time.time() - age_days * 86400
    os.utime(p, (t, t))
    return p


def param(name, value):
    return f'<{name}><LomId Value="0" /><Manual Value="{value}" /></{name}>'


def band(i, on, mode, freq, gain=0, q=0.71):
    return (f'<Bands.{i}><ParameterA>{param("IsOn", on)}{param("Mode", mode)}{param("Freq", freq)}'
            f'{param("Gain", gain)}{param("Q", q)}</ParameterA></Bands.{i}>')


COMP = ('<Compressor2 Id="1">' + param("On", "true") + param("Threshold", 0.1) + param("Ratio", 4) + param("Attack", 5)
        + param("Release", 20) + param("Knee", 6) + param("Gain", 2) + param("DryWet", 1)
        + '<SideChain><OnOff><Manual Value="false" /></OnOff><Volume><Manual Value="1" /></Volume></SideChain></Compressor2>')
EQ = '<Eq8 Id="2">' + param("On", "true") + band(0, "true", 1, 90) + band(1, "true", 3, 3000, 2.5, 1) + \
     band(2, "true", 3, 500, 0) + band(3, "false", 3, 200, -6) + '</Eq8>'
LIMITER = '<Limiter Id="3">' + param("On", "true") + param("Ceiling", -0.1) + param("Gain", 3) + param("Release", 300) + \
          param("AutoRelease", "true") + '</Limiter>'
UTIL = '<StereoGain Id="4">' + param("On", "true") + param("StereoWidth", 1.2) + param("BassMono", "true") + \
       param("BassMonoFrequency", 110) + param("Mono", "false") + param("Gain", 1) + '</StereoGain>'
REVERB = '<Reverb Id="5">' + param("On", "true") + param("DecayTime", 2400) + param("PreDelay", 20) + param("RoomSize", 60) + '</Reverb>'
DELAY = '<Delay Id="6">' + param("On", "true") + param("DelayLine_SyncL", "false") + param("DelayLine_TimeL", 0.25) + \
        param("Feedback", 0.4) + param("DryWet", 0.3) + '</Delay>'
PLUG = '<AuPluginDevice Id="7"><On><Manual Value="true" /></On><PluginDesc><AuPluginInfo Id="0"><Name Value="Some Free EQ" />' \
       '<ComponentType Value="1635083896" /></AuPluginInfo></PluginDesc></AuPluginDevice>'
SIMPLER = '<OriginalSimpler Id="8"><On><Manual Value="true" /></On><Player><MultiSampleMap><SampleParts><MultiSamplePart>' \
          '<SampleRef><FileRef><Path Value="/x/Kick One.wav" /><LivePackName Value="Some Pack" /></FileRef></SampleRef>' \
          '</MultiSamplePart></SampleParts></MultiSampleMap></Player></OriginalSimpler>'


def track(tag, tid, name, devices, vol=1.0, group=-1, clip_end=None):
    clips = f'<AudioClip Id="0"><CurrentStart Value="0" /><CurrentEnd Value="{clip_end}" /></AudioClip>' if clip_end else ""
    seq = "Sample" if tag == "AudioTrack" else "ClipTimeable"
    return (f'<{tag} Id="{tid}"><Name><EffectiveName Value="{name}" /></Name><TrackGroupId Value="{group}" />'
            f'<DeviceChain><Mixer><Volume><Manual Value="{vol}" /></Volume><Pan><Manual Value="0" /></Pan>'
            f'<Speaker><Manual Value="true" /></Speaker><Sends /></Mixer>'
            f'<MainSequencer><{seq}><ArrangerAutomation><Events>{clips}</Events></ArrangerAutomation></{seq}></MainSequencer>'
            f'<DeviceChain><Devices>{devices}</Devices></DeviceChain></DeviceChain>'
            f'<AutomationEnvelopes><Envelopes /></AutomationEnvelopes></{tag}>')


def make_set(path):
    tracks = (track("GroupTrack", 10, "Band", COMP)
              + track("AudioTrack", 1, "Lead Vocal", COMP + EQ, clip_end=200)
              + track("AudioTrack", 2, "Bass", COMP, group=10)
              + track("AudioTrack", 3, "Guitar", PLUG, group=10)
              + track("MidiTrack", 4, "Kit", '<DrumGroupDevice Id="9"><On><Manual Value="true" /></On></DrumGroupDevice>' + SIMPLER)
              + track("ReturnTrack", 5, "A-Reverb", REVERB) + track("ReturnTrack", 6, "B-Delay", DELAY))
    xml = (f'<Ableton Creator="Ableton Live 12.0"><LiveSet><Tracks>{tracks}</Tracks>'
           f'<MainTrack><DeviceChain><Mixer><Tempo><Manual Value="100" /></Tempo></Mixer>'
           f'<DeviceChain><Devices>{UTIL}{LIMITER}</Devices></DeviceChain></DeviceChain></MainTrack></LiveSet></Ableton>')
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as f:
        f.write(xml.encode())
    return Path(path)


class Discovery(unittest.TestCase):
    def test_newest_per_song_and_skips(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            proj = d / "Song Project"
            (proj / "Ableton Project Info").mkdir(parents=True)
            touch(proj / "Song.als", 30)
            newest = touch(proj / "Song (final 2).als", 1)
            touch(proj / "Backup" / "Song [2026-01-01 101010].als", 0)
            touch(d / "Song v1 Project" / "Song v1.als", 60)                 # an older copy in another folder
            touch(d / "Factory Packs" / "Some Pack" / "Demo.als", 0)
            pack = d / "Free Keys Project"
            (pack / "Presets").mkdir(parents=True)
            touch(pack / "Free Keys.als", 0)
            touch(d / "Templates" / "My Start.als", 0)
            other = touch(d / "Other Project" / "Other Tune.als", 5)
            found = L.find_sets([d], spotlight=False)
            self.assertNotIn(str((proj / "Backup" / "Song [2026-01-01 101010].als").resolve()), found)   # never walked
            kept, skipped = L.dedupe(found)
            self.assertEqual(sorted(kept), sorted([str(newest.resolve()), str(other.resolve())]))
            why = {Path(p).name: r for p, r in skipped}
            self.assertIn("older set in the same project", why["Song.als"])
            self.assertIn("another folder", why["Song v1.als"])
            self.assertIn("Factory Packs", why["Demo.als"])
            self.assertIn("pack", why["Free Keys.als"])
            self.assertIn("template", why["My Start.als"])
            self.assertIn("Backup", L.skip_reason(str(proj / "Backup" / "x.als")))

    def test_base_name(self):
        self.assertEqual(L.base_name("Song v3 (final review 2).als"), "song")
        self.assertEqual(L.base_name("Song (remix final).wav"), "song")
        self.assertEqual(L.base_name("Song v2 Project"), "song")
        self.assertEqual(L.song_key("/a/Song Project/Untitled.als"), ("song", "song"))

    def test_bounce_ranking(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            s = touch(d / "Tune Project" / "Tune (recheck 3).als")
            exp = d / "exports"
            touch(exp / "Tune (mix v1).wav", 5, b"0" * 300_000)
            touch(exp / "Tune (remix final, before fix).wav", 0, b"0" * 300_000)      # an earlier state: not a mix
            touch(exp / "Tune vocals.wav", 0, b"0" * 300_000)                        # a stem: not a mix
            touch(exp / "Other Song (final).wav", 0, b"0" * 300_000)                 # another song
            self.assertEqual(Path(L.find_bounce(s, extra_dirs=[exp])).name, "Tune (mix v1).wav")
            touch(exp / "Tune (recheck 3).wav", 9, b"0" * 300_000)                   # named exactly like the set
            self.assertEqual(Path(L.find_bounce(s, extra_dirs=[exp])).name, "Tune (recheck 3).wav")


class ReadSet(unittest.TestCase):
    def test_device_parameters(self):
        with tempfile.TemporaryDirectory() as d:
            s = L.read_set(make_set(Path(d) / "P" / "Tune.als"))
        dev = {(x["role"], x["kind"]): x for x in s["devices"]}
        c = dev[("lead", "compressor")]
        self.assertAlmostEqual(c["threshold"], -20.0, places=1)
        self.assertEqual((c["ratio"], c["attack"], c["release"], c["makeup"], c["sidechain"]), (4.0, 5.0, 20.0, 2.0, False))
        eq = dev[("lead", "eq")]
        self.assertEqual(eq["low_cut"], 90.0)
        self.assertEqual([b["mode"] for b in eq["bands"]], ["low cut 12", "bell"])   # 0 dB bell and switched-off band dropped
        self.assertEqual(dev[("main", "limiter")]["ceiling"], -0.1)
        self.assertTrue(dev[("main", "utility")]["bass_mono"])
        self.assertEqual(dev[("return:reverb", "reverb")]["decay_ms"], 2400)
        dl = dev[("return:delay", "delay")]
        self.assertFalse(dl["synced"]); self.assertEqual(dl["free_ms"], 250.0); self.assertAlmostEqual(dl["beats"], 0.417, 3)
        self.assertEqual(dev[("group", "compressor")]["carries"], ["bass", "keys/guitar/synth"])
        self.assertEqual([(p["role"], p["name"]) for p in s["plugins"]], [("keys/guitar/synth", "Some Free EQ")])
        self.assertIn("Drum Rack", {i["name"] for i in s["instruments"]})
        self.assertEqual(s["samples"], {"Kick One.wav": 1})
        self.assertEqual(s["packs"], {"Some Pack": 1})
        self.assertEqual(s["arranged_s"], 120.0)                                  # 200 beats at 100 BPM
        self.assertFalse(s["genre_guess"]["confirmed"])
        self.assertEqual([x["track"] for x in s["no_low_cut"]], ["Guitar"])

    def test_cache_hit_and_miss(self):
        with tempfile.TemporaryDirectory() as d:
            old = L.CACHE
            L.CACHE = Path(d) / "cache"
            try:
                p = make_set(Path(d) / "P" / "Tune.als")
                r1, hit1 = L.cached("sets", p, L.read_set)
                r2, hit2 = L.cached("sets", p, L.read_set)
                self.assertEqual((hit1, hit2), (False, True))
                self.assertEqual(r1["tempo"], r2["tempo"])
                os.utime(p, (time.time() + 5, time.time() + 5))                       # the set changed: read again
                self.assertFalse(L.cached("sets", p, L.read_set)[1])
            finally:
                L.CACHE = old


def set_(name, devices=(), roles=None, no_cut=(), plugins=(), f0=None):
    return dict(song=name, path=f"/x/{name}.als", project=f"/x/{name} Project", tempo=90.0, devices=list(devices),
                roles=roles or {}, no_low_cut=list(no_cut), plugins=list(plugins), bass_f0=f0, bounce=f"/b/{name}.wav",
                instruments=[], samples={}, packs={}, drum_racks=0)


def bounce(name, lufs, tp, bands=None):
    return dict(file=f"/b/{name}.wav", lufs=lufs, true_peak=tp, plr=round(tp - lufs, 1), crest=12.0,
                bands=bands or {k: -10.0 for k, _, _ in L.BANDS8})


def comp(role, release, **kw):
    return dict(dict(kind="compressor", on=True, role=role, track=role, ratio=4.0, attack=5.0, release=release,
                     threshold=-20.0, makeup=0.0, knee=6.0, sidechain=False), **kw)


def eq(role, cut):
    return dict(kind="eq", on=True, role=role, track=role, bands=[], low_cut=cut)


class Improve(unittest.TestCase):
    def rules(self, sets, bounces):
        return {x["rule"]: x for x in L.improve(sets, bounces, prefs={})}

    def test_each_rule_fires_with_evidence(self):
        lim = dict(kind="limiter", on=True, role="main", track="Main", ceiling=0.0, gain=4.0)
        sets = [set_("a", [lim, comp("bass", 15.0), eq("lead", 100)], roles={"lead": 1}, f0=41.2),
                set_("b", [eq("lead", 90)], roles={"lead": 1}),
                set_("c", [eq("lead", 80)], roles={"lead": 1}),
                set_("d", [], roles={"lead": 1}, no_cut=[dict(track="Vox", role="lead", eq=False, plugins=0)])]
        warm = {k: -10.0 for k, _, _ in L.BANDS8}
        warm["sub"] = 0.0
        bs = {"/b/a.wav": bounce("a", -7.0, -0.2), "/b/b.wav": bounce("b", -12.0, -1.5),
              "/b/c.wav": bounce("c", -14.0, -2.0, warm), "/b/d.wav": bounce("d", -11.0, -1.4)}
        r = self.rules(sets, bs)
        self.assertEqual(r["ceiling"]["evidence"][0]["set"], "a")
        self.assertEqual(r["ceiling"]["evidence"][0]["live_limiter_ceiling"], 0.0)
        self.assertEqual(r["fast-release"]["evidence"][0]["release_ms"], 15.0)
        self.assertEqual(r["low-cut"]["evidence"], [dict(set="d", tracks=["Vox"], note="")])
        self.assertIn("-14 to -7 LUFS", r["loudness-spread"]["advice"])
        self.assertEqual([e["set"] for e in r["heavy-limiting"]["evidence"]], ["a"])        # PLR 6.8 dB
        self.assertEqual(r["tonal-outlier"]["evidence"], [dict(set="c", bands_vs_your_median_db={"sub": 10.0})])

    def test_quiet_when_nothing_is_wrong(self):
        lim = dict(kind="limiter", on=True, role="main", track="Main", ceiling=-1.0, gain=2.0)
        sets = [set_(n, [lim, comp("bass", 120.0), comp("lead", 10.0), eq("lead", 90)], roles={"lead": 1}, f0=41.2)
                for n in "abcd"]
        bs = {f"/b/{n}.wav": bounce(n, -10.0 - i * 0.3, -1.2) for i, n in enumerate("abcd")}
        self.assertEqual(self.rules(sets, bs), {})

    def test_release_rule_skips_vocal_groups_and_sidechains(self):
        sets = [set_("a", [comp("group", 5.0, carries=["lead", "harmony"]), comp("bass", 5.0, sidechain=True),
                           comp("group", 5.0, carries=["bass", "drums"])])]
        ev = self.rules(sets, {})["fast-release"]["evidence"]
        self.assertEqual([(e["role"], e["release_ms"]) for e in ev], [("group", 5.0)])


class Bounces(unittest.TestCase):
    def test_measure(self):
        import soundfile as sf
        with tempfile.TemporaryDirectory() as d:
            sr = 44100
            t = np.arange(25 * sr) / sr
            y = 0.3 * np.sin(2 * np.pi * 100 * t) + 0.05 * np.random.default_rng(0).standard_normal(len(t))
            p = Path(d) / "mix.wav"
            sf.write(p, np.c_[y, y].astype(np.float32), sr)
            m = L.measure_bounce(p)
        self.assertEqual(set(m["bands"]), {k for k, _, _ in L.BANDS8})
        self.assertEqual(max(m["bands"], key=m["bands"].get), "bass")                     # the 100 Hz tone
        self.assertLess(m["true_peak"], 0.0)
        self.assertAlmostEqual(m["plr"], m["true_peak"] - m["lufs"], places=0)


class EndToEnd(unittest.TestCase):
    def test_run_and_report(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for n in ("One", "Two", "Three"):
                make_set(d / f"{n} Project" / f"{n}.als")
            old = L.CACHE
            L.CACHE = d / "cache"
            try:
                lib = L.run([d], bounces=False, jobs=1, spotlight=False)
                again = L.run([d], bounces=False, jobs=1, spotlight=False)
            finally:
                L.CACHE = old
        self.assertEqual(lib["scan"]["sets"], 3)
        self.assertEqual(again["scan"]["cache_hits"], 3)
        self.assertEqual(len(lib["questions"]), 3)
        md = L.report(lib)
        self.assertIn("## YOUR STYLE", md)
        self.assertIn("## WHERE YOU COULD IMPROVE", md)
        self.assertIn("lead · compressor in 3 sets", md)
        json.dumps(lib, default=str)
