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

    def test_needs_one_probe_placed_first(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "Song.als"
            with gzip.open(src, "wb") as fh:
                fh.write(b'<Ableton><LiveSet><NextPointeeId Value="1"/><Tracks/></LiveSet></Ableton>')
            with self.assertRaises(RuntimeError):
                P.insert(src)


if __name__ == "__main__":
    unittest.main()
