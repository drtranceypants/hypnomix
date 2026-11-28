import contextlib, gzip, io, os, tempfile, unittest
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import soundfile as sf

from hypnomix.session import loopset as LS

SR = 44100
BPM = 120.0
BEAT = 60.0 / BPM
START = 1.0                        # the clips start one beat after bar 1: not on a bar line
BARS = 16


def kick(rng, bars=BARS, tone=110.0):
    """A clip of `bars` bars whose first sample is beat START of the song: a hit on every bar line and beat 3."""
    n = int(SR * (bars * 4 * BEAT))
    y = np.zeros(n)
    for beat in range(0, bars * 4 + 4):
        t = (beat - START) * BEAT
        if t < 0 or t * SR >= n - 4000 or beat % 2:
            continue
        i = int(t * SR)
        k = np.arange(4000) / SR
        y[i: i + 4000] += 0.8 * np.sin(2 * np.pi * tone * k) * np.exp(-k * 30) * (1 if beat % 4 == 0 else 0.6)
    return y + 0.001 * rng.standard_normal(n)


def pad(rng, bars=BARS):
    n = int(SR * (bars * 4 * BEAT))
    t = np.arange(n) / SR
    y = np.zeros(n)
    for b in range(bars // 4):
        a, z = int(b * 16 * BEAT * SR), min(n, int((b + 1) * 16 * BEAT * SR))
        f = [220.0, 261.63, 220.0, 196.0][b % 4]
        y[a:z] = 0.2 * (np.sin(2 * np.pi * f * t[a:z]) + 0.5 * np.sin(2 * np.pi * f * 1.5 * t[a:z]))
    return y


def clip_xml(wav, cid, start, nbeats, name):
    secs = nbeats * BEAT
    return (f'<AudioClip Id="{cid}" Time="{start}"><LomId Value="0"/><CurrentStart Value="{start}"/>'
            f'<CurrentEnd Value="{start + nbeats}"/><Loop><LoopStart Value="0"/><LoopEnd Value="{secs}"/>'
            f'<StartRelative Value="0"/><LoopOn Value="false"/><OutMarker Value="{secs}"/><HiddenLoopStart Value="0"/>'
            f'<HiddenLoopEnd Value="{secs}"/></Loop><Name Value="{name}"/><Disabled Value="false"/><IsWarped Value="false"/>'
            '<WarpMode Value="0"/><SampleVolume Value="1"/><WarpMarkers><WarpMarker Id="0" SecTime="0" BeatTime="0"/></WarpMarkers>'
            '<Fades><FadeInLength Value="0"/><FadeOutLength Value="0"/></Fades>'
            f'<SampleRef><FileRef><Path Value="{wav}"/><RelativePath Value="{Path(wav).name}"/><OriginalFileSize Value="1"/>'
            '<OriginalCrc Value="0"/></FileRef><LastModDate Value="0"/><DefaultDuration Value="1"/>'
            '<DefaultSampleRate Value="44100"/></SampleRef></AudioClip>')


NSCENE = 3


def make_set(path, wavs):
    """wavs: {track: ([main clip wavs], [lane clip wavs])}. Three scenes; every track (and the main track) has a slot each."""
    slots = "".join(f'<ClipSlot Id="{i}"><LomId Value="0"/><ClipSlot><Value/></ClipSlot><HasStop Value="true"/></ClipSlot>'
                    for i in range(NSCENE))
    nbeats = BARS * 4

    def track(tid, name, base, main, lane):
        ev = "".join(clip_xml(w, i + 1, START + i * (nbeats + 8), nbeats, "Audio") for i, w in enumerate(main))
        tl = "".join(f'<TakeLane Id="{i}"><LomId Value="0"/><ClipAutomation><Events>{clip_xml(w, 1, START, nbeats, "take")}'
                     '</Events></ClipAutomation></TakeLane>' for i, w in enumerate(lane))
        return (f'<AudioTrack Id="{tid}"><Name><EffectiveName Value="{name}"/><UserName Value="{name}"/></Name>'
                f'<TrackGroupId Value="-1"/><AutomationEnvelopes><Envelopes/></AutomationEnvelopes><TakeLanes><TakeLanes>{tl}'
                f'</TakeLanes></TakeLanes><DeviceChain><AudioOutputRouting><Target Value="AudioOut/Main"/></AudioOutputRouting>'
                f'<Mixer><Volume><Manual Value="1"/><AutomationTarget Id="{base}"/></Volume>'
                f'<Pan><Manual Value="0"/><AutomationTarget Id="{base + 1}"/></Pan>'
                f'<Speaker><Manual Value="true"/><AutomationTarget Id="{base + 2}"/></Speaker><Sends/></Mixer>'
                f'<MainSequencer><Sample><ArrangerAutomation><Events>{ev}</Events></ArrangerAutomation></Sample>'
                f'<ClipSlotList>{slots}</ClipSlotList></MainSequencer><DeviceChain><Devices/></DeviceChain></DeviceChain></AudioTrack>')
    scenes = "".join(f'<Scene Id="{i}"><Name Value=""/><Annotation Value=""/><Color Value="-1"/><Tempo Value="120"/>'
                     '<TimeSignatureId Value="201"/><LomId Value="0"/></Scene>' for i in range(NSCENE))
    tracks = "".join(track(10 + i, n, 100 + 20 * i, m, l) for i, (n, (m, l)) in enumerate(wavs.items()))
    xml = ('<?xml version="1.0" encoding="UTF-8"?><Ableton MajorVersion="5" MinorVersion="12.0_12000" Creator="Ableton Live 12.0">'
           f'<LiveSet><NextPointeeId Value="1000"/><Tracks>{tracks}</Tracks>'
           f'<MainTrack><Name><EffectiveName Value="Main"/></Name><AutomationEnvelopes><Envelopes/></AutomationEnvelopes><DeviceChain>'
           f'<Mixer><Volume><Manual Value="1"/><AutomationTarget Id="900"/></Volume><Pan><Manual Value="0"/><AutomationTarget Id="901"/></Pan>'
           f'<Speaker><Manual Value="true"/><AutomationTarget Id="902"/></Speaker><Sends/>'
           f'<Tempo><Manual Value="{BPM}"/><AutomationTarget Id="903"/></Tempo></Mixer>'
           f'<MainSequencer><ClipSlotList>{slots}</ClipSlotList></MainSequencer><DeviceChain><Devices/></DeviceChain></DeviceChain></MainTrack>'
           f'<Scenes>{scenes}</Scenes></LiveSet></Ableton>')
    with gzip.open(path, "wb") as f:
        f.write(xml.encode())


class LoopSetTakes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._env = os.environ.get("HYPNOMIX_NO_CACHE")
        os.environ["HYPNOMIX_NO_CACHE"] = "1"
        cls.td = tempfile.TemporaryDirectory()
        d = cls.d = Path(cls.td.name)
        rng = np.random.default_rng(3)
        w = {}
        for name, fn in (("k1", lambda: kick(rng)), ("k2", lambda: kick(rng, tone=90.0)), ("p1", lambda: pad(rng)),
                         ("p2", lambda: pad(rng))):
            w[name] = d / f"{name}.wav"
            sf.write(str(w[name]), fn(), SR, subtype="PCM_16")
        cls.src = d / "Song.als"
        make_set(cls.src, {"Kick": ([w["k1"]], [w["k2"]]), "Pad": ([w["p1"]], [w["p2"]])})
        cls.before = cls.src.read_bytes()
        cls.run_kw = dict(per_track=3, bars=(2, 4), variations=2, combos=6, seed=5, log=lambda *a: None)
        with contextlib.redirect_stdout(io.StringIO()):
            cls.res, cls.out = LS.run_takes(cls.src, out=d / "out", **cls.run_kw)

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()
        if cls._env is None:
            os.environ.pop("HYPNOMIX_NO_CACHE", None)
        else:
            os.environ["HYPNOMIX_NO_CACHE"] = cls._env

    def test_takes_from_main_lane_and_take_lanes(self):
        self.assertEqual([t["name"] for t in self.res["tracks"]], ["Kick", "Pad"])
        self.assertTrue(all(t["takes"] == 2 for t in self.res["tracks"]))

    def test_picks_on_bar_lines(self):
        for t in self.res["tracks"]:
            self.assertEqual(len(t["picks"]), 3)
            for c in t["picks"]:
                self.assertIn(c["bars"], (2, 4))
                self.assertGreaterEqual(c["abs_bar"], 1)
                y, sr = sf.read(c["variations"] and next(l["file"] for l in t["loops"] if l["id"] == f"{t['id']}:{c['rank']}"))
                self.assertAlmostEqual(len(y) / sr, c["bars"] * 4 * BEAT, delta=0.06)
            for a in t["picks"]:                          # none overlapping inside a take
                for b in t["picks"]:
                    if a is not b and a["take"] == b["take"]:
                        self.assertTrue(a["abs_bar"] + a["bars"] <= b["abs_bar"] or b["abs_bar"] + b["bars"] <= a["abs_bar"])
        kick_pick = self.res["tracks"][0]["picks"][0]
        y, sr = sf.read(next(l["file"] for l in self.res["tracks"][0]["loops"] if l["id"].endswith(f":{kick_pick['rank']}")))
        self.assertGreater(float(np.abs(y[: int(0.02 * sr)]).max()), 0.3)       # the first downbeat hit starts the loop

    def test_combos_same_length_distinct(self):
        loops = {l["id"]: l for t in self.res["tracks"] for l in t["loops"]}
        self.assertEqual(len(self.res["combos"]), 6)
        keys = set()
        for c in self.res["combos"]:
            used = [loops[v] for v in c["slots"].values() if v]
            self.assertGreaterEqual(len(used), 2)
            self.assertEqual({l["bars"] for l in used}, {c["bars"]})
            keys.add(tuple(sorted(c["slots"].items(), key=lambda kv: kv[0])))
        self.assertEqual(len(keys), 6)

    def test_deterministic_per_seed(self):
        with contextlib.redirect_stdout(io.StringIO()):
            again, _ = LS.run_takes(self.src, out=self.d / "out2", **self.run_kw)
            other, _ = LS.run_takes(self.src, out=self.d / "out3", **dict(self.run_kw, seed=6))
        self.assertEqual(again["combos"], self.res["combos"])
        self.assertNotEqual(other["combos"], self.res["combos"])

    def test_tracks_filter(self):
        with contextlib.redirect_stdout(io.StringIO()):
            r, _ = LS.run_takes(self.src, tracks=["pad"], out=self.d / "out4", **self.run_kw)
        self.assertEqual([t["name"] for t in r["tracks"]], ["Pad"])

    def test_apply_adds_tracks_and_scenes(self):
        dst = self.d / "Song (loops).als"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            LS.main(["--takes", str(self.src), "--tracks", "Kick,Pad", "--per-track", "3", "--bars", "2,4", "--variations", "2",
                     "--combos", "6", "--seed", "5", "--out", str(self.d / "out5"), "--apply", str(dst)])
        self.assertEqual(self.src.read_bytes(), self.before)
        root = ET.fromstring(gzip.open(dst).read())
        names = [t.find("./Name/EffectiveName").get("Value") for t in root.find(".//Tracks")]
        self.assertEqual(names, ["Kick", "Kick loops", "Pad", "Pad loops"])
        scenes = root.find(".//Scenes")
        rows = 6 + 2 * 3 * (1 + 2)
        self.assertEqual(len(scenes), NSCENE + rows)
        sn = [s.find("./Name").get("Value") for s in scenes]
        self.assertEqual(sn[NSCENE:NSCENE + 6], [f"Combo {i}" for i in range(1, 7)])
        self.assertIn("Loops: Kick 1", sn)
        self.assertEqual(len({s.get("Id") for s in scenes}), len(scenes))
        for lst in root.iter("ClipSlotList"):
            self.assertEqual(len(lst), len(scenes))
        tr = [t for t in root.find(".//Tracks") if t.find("./Name/EffectiveName").get("Value") == "Kick loops"][0]
        slots = tr.findall("./DeviceChain/MainSequencer/ClipSlotList/ClipSlot")
        full = [s for s in slots if s.find("./ClipSlot/Value/AudioClip") is not None]
        self.assertGreaterEqual(len(full), 3 * 3)           # the picks and their variations get a row each
        c = full[0].find("./ClipSlot/Value/AudioClip")
        self.assertEqual(c.find("./Loop/LoopOn").get("Value"), "true")
        self.assertIn("bar", c.find("./Name").get("Value"))
        with self.assertRaises(SystemExit):                 # never overwrites
            LS.main(["--takes", str(self.src), "--out", str(self.d / "out6"), "--apply", str(dst)])


if __name__ == "__main__":
    unittest.main()
