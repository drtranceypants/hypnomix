"""Probe: the device patch is complete, the hub receives blocks, the report finds fights, peaks and vocal rides."""
import gzip, json, math, socket, tempfile, time, unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from hypnomix.app import probe as P


def block(k=0.05, peak=0.3, bands=None, lr=None, low=0.0):
    r = k * 1.2
    b = bands or [0.0] * 8
    lr = r * r if lr is None else lr
    return [k, k, peak, peak, r, r, r, r * 0.1, lr, low, low, low * low] + list(b)


def capture(tracks):
    out = {"started": 0, "ended": 60, "tracks": {}}
    for tid, (name, main, rows) in enumerate(tracks):
        out["tracks"][str(tid)] = dict(name=name, main=main, blocks=rows)
    return out


def rows(vals_fn, n=600, fader=0.0):
    return [[i / 10, i * 0.2, 1, fader, 0.0] + vals_fn(i) for i in range(n)]


class Numbers(unittest.TestCase):
    def test_loudness_of_known_mean_square(self):
        v = [block(k=10 ** (-20 / 20) / math.sqrt(2))] * 40     # msL + msR = 0.01
        self.assertAlmostEqual(P.lufs_of(v), -20.691, places=2)
        self.assertAlmostEqual(P.integrated(v), -20.691, places=2)

    def test_gating_ignores_silence(self):
        v = [block(k=0.05)] * 40 + [block(k=0.0)] * 400
        self.assertAlmostEqual(P.integrated(v), P.lufs_of([block(k=0.05)] * 40), delta=0.3)   # edge windows count, as in BS.1770

    def test_correlation(self):
        self.assertAlmostEqual(P.corr_of([block(k=0.05)] * 10), 1.0, places=3)
        self.assertAlmostEqual(P.corr_of([block(k=0.05, lr=0.0)] * 10), 0.0, places=3)


class Report(unittest.TestCase):
    def test_masking_main_peak_and_vocal_ride(self):
        mid = [0.0, 0.0, 0.0, 0.05, 0.0, 0.0, 0.0, 0.0]          # both live in 250-500 Hz
        guitar = rows(lambda i: block(bands=mid))
        keys = rows(lambda i: block(bands=[0, 0, 0, 0.045, 0, 0, 0, 0]))
        # lead: 6 dB quieter in bars 17-24 (beats 64-96 → blocks 320-479 at 0.2 beat per block)
        lead = rows(lambda i: block(k=0.025 if 320 <= i < 480 else 0.05, bands=[0, 0, 0, 0, 0.05, 0, 0, 0]))
        main = rows(lambda i: block(k=0.2, peak=1.2))
        cap = capture([("Lead Vox", False, lead), ("Gtr", False, guitar), ("Keys", False, keys), ("Main", True, main)])
        F, _ = P.analyse(cap, {"targets": {"lufs": -14, "true_peak": -1}})
        kinds = [f["kind"] for f in F]
        self.assertIn("peak", kinds)
        fight = next(f for f in F if f["kind"] == "masking")
        self.assertEqual(fight["track"], "Keys")                  # keys give way to the guitar (role order)
        self.assertIn("250-500", fight["where"])
        ride = [f for f in F if f["kind"] == "vocal-balance"]
        self.assertTrue(ride and "17-24" in ride[0]["where"], ride)
        self.assertEqual([f["n"] for f in F], list(range(1, len(F) + 1)))

    def test_report_writes_a_review(self):
        cap = capture([("Main", True, rows(lambda i: block(k=0.2, peak=0.5)))])
        with tempfile.TemporaryDirectory() as d:
            cf = Path(d) / "c.json"
            cf.write_text(json.dumps(cap))
            P.report(cf, Path(d) / "scan")
            data = json.loads((Path(d) / "scan" / "findings.json").read_text())
            self.assertTrue((Path(d) / "scan" / "REVIEW.md").exists())
            self.assertEqual(json.loads((Path(d) / "scan" / "scan.json").read_text())["mode"], "live")
            self.assertIsInstance(data["findings"], list)


class Hub(unittest.TestCase):
    def test_receives_osc_blocks(self):
        from pythonosc.udp_client import SimpleUDPClient
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        hub = P.Hub().start(port)
        try:
            hub.begin("t")
            c = SimpleUDPClient("127.0.0.1", port)
            for i in range(20):
                c.send_message("/hm/probe", [7, "Bass", 0, float(i), 1, -3.0, 0.0, 48000.0] + block(k=0.05))
            time.sleep(0.5)
            st = hub.status()
            self.assertEqual(st[0]["name"], "Bass")
            self.assertTrue(st[0]["live"])
            with tempfile.TemporaryDirectory() as d:
                f = hub.end(d, "song")
                cap = json.loads(Path(f).read_text())
                self.assertEqual(len(cap["tracks"]["7"]["blocks"]), 20)
        finally:
            hub.server.shutdown()
            hub.server.server_close()


class Device(unittest.TestCase):
    def test_patch_is_wired(self):
        tpl = {"patcher": {"boxes": [{"box": {"id": "obj-1", "text": "plugin~"}}, {"box": {"id": "obj-2", "text": "plugout~"}}],
                           "lines": []}}
        p = P.build_patch(tpl)["patcher"]
        ids = {b["box"]["id"] for b in p["boxes"]}
        for l in p["lines"]:
            self.assertIn(l["patchline"]["source"][0], ids)
            self.assertIn(l["patchline"]["destination"][0], ids)
        # every one of the 20 values reaches the script
        idx = sorted(int(b["box"]["text"].split()[-1]) for b in p["boxes"] if b["box"].get("text", "").startswith("prepend val"))
        self.assertEqual(idx, list(range(P.NV)))
        self.assertEqual(len(P.FIELDS), P.NV)


class Insert(unittest.TestCase):
    def test_copies_the_probe_to_every_track_in_a_new_set(self):
        probe = '<MxDeviceAudioEffect Id="0"><UserName Value=""/><Path Value="/x/HypnomixProbe.amxd"/>' \
                '<On><AutomationTarget Id="500"/></On></MxDeviceAudioEffect>'

        def tr(tid, devs=""):
            return (f'<AudioTrack Id="{tid}"><Name><EffectiveName Value="T{tid}"/></Name>'
                    f'<DeviceChain><DeviceChain><Devices>{devs}</Devices></DeviceChain></DeviceChain></AudioTrack>')
        xml = (f'<Ableton><LiveSet><NextPointeeId Value="900"/><Tracks>{tr(1, probe)}{tr(2)}{tr(3)}</Tracks>'
               f'<MainTrack><DeviceChain><DeviceChain><Devices/></DeviceChain></DeviceChain></MainTrack></LiveSet></Ableton>')
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "Song.als"
            with gzip.open(src, "wb") as fh:
                fh.write(xml.encode())
            out, n = P.insert(src)
            self.assertEqual(n, 3)                                  # tracks 2, 3 and Main
            root = ET.fromstring(gzip.open(out).read())
            self.assertEqual(len(root.findall(".//MxDeviceAudioEffect")), 4)
            ids = [e.get("Id") for e in root.iter("AutomationTarget")]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(gzip.open(src).read().decode(), xml)   # original untouched

    def test_without_the_installed_devices_it_says_how_to_install(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "Song.als"
            with gzip.open(src, "wb") as fh:
                fh.write(b'<Ableton><LiveSet><NextPointeeId Value="1"/><Tracks/></LiveSet></Ableton>')
            with self.assertRaisesRegex(RuntimeError, "hypnomix device"):
                P.insert(src, library=Path(d) / "no library")

    def test_every_device_from_the_library_with_no_probe_placed(self):
        """The first-pass option: probes everywhere, the review device and HypnomixMain (last) on Main, made fresh."""
        def tr(tid, kind="AudioTrack"):
            return (f'<{kind} Id="{tid}"><Name><EffectiveName Value="T{tid}"/></Name>'
                    f'<DeviceChain><DeviceChain><Devices/></DeviceChain></DeviceChain></{kind}>')
        xml = (f'<Ableton><LiveSet><NextPointeeId Value="900"/><Tracks>{tr(1)}{tr(2, "MidiTrack")}{tr(3, "ReturnTrack")}'
               f'</Tracks><MainTrack><DeviceChain><DeviceChain><Devices><Eq8 Id="0"/></Devices></DeviceChain>'
               f'</DeviceChain></MainTrack></LiveSet></Ableton>')
        with tempfile.TemporaryDirectory() as d:
            lib = Path(d) / "User Library"
            (lib / P.DEVICES).mkdir(parents=True)
            for n in ("HypnomixProbe", "HypnomixMain", "Hypnomix"):
                (lib / P.DEVICES / f"{n}.amxd").write_bytes(b"ampf")
            src = Path(d) / "Song.als"
            with gzip.open(src, "wb") as fh:
                fh.write(xml.encode())
            out, n = P.insert(src, main=True, review=True, library=lib)
            self.assertEqual(out.name, "Song (hypnomix devices).als")
            self.assertEqual(n, 5)                                  # 3 probes + review + HypnomixMain
            root = ET.fromstring(gzip.open(out).read())
            def names(devs):
                return [Path(e.find(".//PatchSlot//FileRef/Path").get("Value")).stem if e.tag.startswith("MxDevice")
                        else e.tag for e in devs]
            for t in ("AudioTrack", "MidiTrack", "ReturnTrack"):
                self.assertEqual(names(root.find(f".//{t}/DeviceChain/DeviceChain/Devices")), ["HypnomixProbe"])
            self.assertEqual(names(root.find(".//MainTrack/DeviceChain/DeviceChain/Devices")),
                             ["Eq8", "Hypnomix", "HypnomixMain"])
            rel = root.find(".//MainTrack//PatchSlot//FileRef/RelativePath").get("Value")
            self.assertEqual(rel, (P.DEVICES / "Hypnomix.amxd").as_posix())
            ids = [e.get("Id") for e in root.iter() if e.tag in ("AutomationTarget", "Pointee")]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertGreater(int(root.find(".//NextPointeeId").get("Value")), max(map(int, ids)))
            self.assertEqual(gzip.open(src).read().decode(), xml)   # original untouched
            again, n2 = P.insert(src, main=True, review=True, library=lib)
            self.assertEqual(again.name, "Song (hypnomix devices 2).als")   # an earlier copy is never overwritten
            third, n3 = P.insert(out, out=Path(d) / "Third.als", main=True, review=True, library=lib)
            self.assertEqual(n3, 0)                                 # nothing doubled on a set that has them all


if __name__ == "__main__":
    unittest.main()


class Cards(unittest.TestCase):
    def test_read_cards_from_a_saved_set(self):
        def enum(name, idx, labels):
            names = "".join(f'<Name Id="{i}"><Name Value="{l}"/></Name>' for i, l in enumerate(labels))
            return (f'<MxDEnumParameter><Name Value="{name}"/><Default Value="0"/><Timeable><Manual Value="{idx}"/></Timeable>'
                    f'<Names>{names}</Names></MxDEnumParameter>')

        def fl(name, v):
            return f'<MxDFloatParameter><Name Value="{name}"/><Timeable><Manual Value="{v}"/></Timeable></MxDFloatParameter>'
        dev = lambda body: f'<MxDeviceAudioEffect Id="0"><ParameterList>{body}</ParameterList></MxDeviceAudioEffect>'
        tr = lambda n, body: (f'<AudioTrack Id="1"><Name><UserName Value="{n}"/></Name><DeviceChain><DeviceChain><Devices>'
                              f'{dev(body)}</Devices></DeviceChain></DeviceChain></AudioTrack>')
        xml = ('<Ableton><LiveSet><Tracks>' + tr("Vox 1", enum("hm_role", 1, P.ROLES) + enum("hm_protect", 1, ["off", "on: ask"]))
               + tr("Gtr", enum("hm_role", 0, P.ROLES)) + '</Tracks><MainTrack><DeviceChain><DeviceChain><Devices>'
               + dev(enum("hm_key", 10, P.KEYS) + enum("hm_scale", 2, P.SCALES) + fl("hm_target", -10))
               + '</Devices></DeviceChain></DeviceChain></MainTrack></LiveSet></Ableton>')
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "Song.als"
            with gzip.open(src, "wb") as fh:
                fh.write(xml.encode())
            sig = P.signature(["Vox 1", "Gtr"])
            (Path(d) / "cards.json").write_text(json.dumps({sig: {"chords": "| Am | F | C | G |"}}))
            c = P.read_cards(src, Path(d) / "cards.json")
        self.assertEqual(c["tracks"]["Vox 1"], {"role": "lead vocal", "protect": "on: ask"})
        self.assertEqual(c["tracks"]["Gtr"], {"role": "auto"})
        self.assertEqual(c["song"]["key_name"], "G major")            # A dorian has the notes of G major
        self.assertEqual(c["song"]["target"], -10.0)
        self.assertEqual(c["song"]["chords"], "| Am | F | C | G |")

    def test_keys_and_card_prefs(self):
        self.assertEqual(P.key_name("A", "minor"), "A minor")
        self.assertEqual(P.key_name("E", "phrygian"), "C major")
        pr = P.card_prefs({"targets": {"lufs": -14}}, {"song": {"target": -9.5, "ceiling": -1.5},
                                                       "tracks": {"Lead": {"protect": "on: ask before any change"}}})
        self.assertEqual(pr["targets"], {"lufs": -9.5, "true_peak": -1.5})
        self.assertEqual(pr["protect"]["tracks"], ["Lead"])

    def test_told_roles_and_priority_decide_who_gives_way(self):
        mid = [0.0, 0.0, 0.0, 0.05, 0.0, 0.0, 0.0, 0.0]
        a = rows(lambda i: block(bands=mid))
        b = rows(lambda i: block(bands=[0, 0, 0, 0.045, 0, 0, 0, 0]))
        cap = capture([("Audio 3", False, a), ("Audio 7", False, b)])
        cap["card"] = {"tracks": {"Audio 3": {"role": "pad", "priority": "normal"},
                                  "Audio 7": {"role": "guitar", "priority": "background: gives way"}}}
        F, _ = P.analyse(cap, {})
        self.assertEqual(next(f for f in F if f["kind"] == "masking")["track"], "Audio 7")

    def test_master_findings_on_a_recorded_master(self):
        import numpy as np, soundfile as sf
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "m.wav"
            t = np.arange(48000 * 4) / 48000
            sf.write(str(f), np.stack([0.99 * np.sin(2 * np.pi * 997 * t)] * 2, 1).astype(np.float32), 48000, subtype="FLOAT")
            F, m = P.master_findings(f, {"targets": {"lufs": -14, "true_peak": -1}})
        self.assertEqual({x["kind"] for x in F}, {"true-peak", "loudness"})

    def test_device_and_python_recognise_the_song_the_same_way(self):
        import subprocess
        from tests import _jscheck
        runner = _jscheck.need_runner(self)
        names = ["Lead Vox", "Bass", "Drüms", "Gtr · B smooth-2"]
        body = P.script()
        sig_fn = "function signature()" + body.split("function signature()")[1].split("function word")[0]
        prog = ("function str(x){return (x instanceof Array)?x.join(' '):String(x)}\nvar N=%s;\nfunction LiveAPI(p){this.getcount="
                "function(){return N.length};this.get=function(){return [N[parseInt(p.split(' ')[2])]]}}\n" % json.dumps(names)
                + sig_fn + "\nprint(signature());")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "s.js"
            f.write_text(prog, encoding="utf-8")
            out = subprocess.run(runner + [str(f)], capture_output=True, text=True, encoding="utf-8").stdout.strip()
        self.assertEqual(out, P.signature(names))


class ScanReadsCards(unittest.TestCase):
    def test_key_lead_and_protect_from_live_win_over_guessing(self):
        import types
        from hypnomix.workflow import scan as S
        orig = P.read_cards
        P.read_cards = lambda als: {"song": {"key_name": "G major", "target": -10.0, "genre": "not set"},
                                    "tracks": {"Vox 1": {"role": "lead vocal", "protect": "on: ask"}, "Gtr": {"role": "auto"},
                                               "Pad": {"role": "pad", "priority": "background: gives way"}}}
        try:
            a = types.SimpleNamespace(key=None, lead_track=None)
            told = S.told_in_live("x.als", a)
        finally:
            P.read_cards = orig
        self.assertEqual((a.key, a.lead_track), ("G major", "Vox 1"))
        self.assertEqual(told["protect"], ["Vox 1"])
        self.assertEqual(told["priority"], {"Pad": "background"})
        self.assertEqual(told["roles"], {"Vox 1": "lead vocal", "Pad": "pad"})
        self.assertNotIn("genre", told)
        a = types.SimpleNamespace(key="A minor", lead_track="Lead")       # what was typed on the command line wins
        P.read_cards = lambda als: {"song": {"key_name": "G major"}, "tracks": {"Vox 1": {"role": "lead vocal"}}}
        try:
            S.told_in_live("x.als", a)
        finally:
            P.read_cards = orig
        self.assertEqual((a.key, a.lead_track), ("A minor", "Lead"))


class ReportSurvivesMerge(unittest.TestCase):
    def test_master_plan_into_the_same_folder_keeps_live_findings(self):
        from hypnomix.workflow import scan as S
        cap = capture([("Main", True, rows(lambda i: block(k=0.2, peak=1.2)))])
        with tempfile.TemporaryDirectory() as d:
            cf = Path(d) / "c.json"
            cf.write_text(json.dumps(cap))
            od = Path(d) / "scan"
            F = P.report(cf, od)
            (od / "master.json").write_text(json.dumps({"group": "master", "set": "", "seconds": 1,
                                                        "findings": [dict(id="master-1", tool="master", kind="limiter",
                                                                          severity="info", track="mix", where="",
                                                                          problem="x", fix="y", applies="audio")],
                                                        "notes": []}))
            merged, _ = S.merge(od)
            ids = {f["id"] for f in merged}
            self.assertIn("master-1", ids)
            self.assertTrue({f["id"] for f in F} <= ids)
