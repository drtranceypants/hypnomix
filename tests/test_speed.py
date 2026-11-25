"""Speed: the render cache, scan --quick, incremental scans (--since) and watch.

Everything is synthesised in a temporary folder with a scratch HYPNOMIX_HOME and render cache.
"""
import gzip, json, os, re, tempfile, time, unittest
from pathlib import Path

import numpy as np

from tests.test_oversight import clicky_set, hx, py


class RenderCache(unittest.TestCase):
    def test_second_render_is_a_cache_hit_and_bit_identical(self):
        import xml.etree.ElementTree as ET
        from hypnomix.session import render as R
        with tempfile.TemporaryDirectory() as td:
            als = clicky_set(td)
            old = os.environ.get("HYPNOMIX_RENDER_CACHE")
            os.environ["HYPNOMIX_RENDER_CACHE"] = str(Path(td) / "cache")
            try:
                root = ET.fromstring(gzip.open(als).read())
                t = root.find(".//Tracks/AudioTrack")
                spb, sr = 0.5, 22050
                N = int(10 * spb * sr)
                R.CACHE_STATS.update(hits=0, misses=0, writes=0)
                a = R.render_track(t, str(als), spb, N, sr, None, 0, [])
                self.assertEqual(R.CACHE_STATS["writes"], 2)
                b = R.render_track(t, str(als), spb, N, sr, None, 0, [])
                self.assertEqual(R.CACHE_STATS["hits"], 2)
                self.assertTrue(np.array_equal(a, b))
                c = R.render_track(t, str(als), spb, N, sr, None, 0, [], cache=False)
                # the cache keeps 32-bit float, what render writes: the written samples are the same
                self.assertTrue(np.array_equal(a.astype(np.float32), c.astype(np.float32)))
                # a changed clip setting is a new key, never a stale hit
                t.find(".//AudioClip/SampleVolume").set("Value", "0.5")
                R.CACHE_STATS.update(hits=0)
                d = R.render_track(t, str(als), spb, N, sr, None, 0, [])
                self.assertEqual(R.CACHE_STATS["hits"], 1)                  # only the untouched clip
                self.assertFalse(np.array_equal(a, d))
                # a clip moved on the timeline reuses its render
                for el in t.findall(".//AudioClip"):
                    for tag in ("CurrentStart", "CurrentEnd"):
                        x = el.find(tag)
                        x.set("Value", str(float(x.get("Value")) + 1))
                R.CACHE_STATS.update(hits=0)
                R.render_track(t, str(als), spb, N, sr, None, 0, [])
                self.assertEqual(R.CACHE_STATS["hits"], 2)
                # a source file saved again is a new key
                src = Path(td) / "take.wav"
                os.utime(src, (src.stat().st_atime, src.stat().st_mtime + 5))
                R.CACHE_STATS.update(hits=0)
                R.render_track(t, str(als), spb, N, sr, None, 0, [])
                self.assertEqual(R.CACHE_STATS["hits"], 0)
                self.assertGreater(R.cache_trim(cap_mb=0), 0)                 # the cap empties it
                self.assertEqual(list((Path(td) / "cache").glob("*/*.npy")), [])
            finally:
                if old is None:
                    os.environ.pop("HYPNOMIX_RENDER_CACHE", None)
                else:
                    os.environ["HYPNOMIX_RENDER_CACHE"] = old

    def test_cli_render_twice_same_files(self):
        with tempfile.TemporaryDirectory() as td:
            td, home = Path(td), Path(td) / "home"
            als = clicky_set(td)
            hx("render", als, "--out", td / "r1", home=home)
            code, out = hx("render", als, "--out", td / "r2", home=home)
            self.assertEqual(code, 0, out)
            self.assertIn("2 clip(s) reused", out)
            import soundfile as sf
            same = lambda x, y: np.array_equal(sf.read(str(td / x / "Vox.wav"))[0], sf.read(str(td / y / "Vox.wav"))[0])
            self.assertTrue(same("r1", "r2"))                  # the samples, bit for bit (the header holds a time)
            code, out = hx("render", als, "--out", td / "r3", "--no-cache", home=home)
            self.assertNotIn("reused", out)
            self.assertTrue(same("r1", "r3"))


class QuickAndIncremental(unittest.TestCase):
    def test_quick_scan_runs_only_xml_groups(self):
        with tempfile.TemporaryDirectory() as td:
            td, home = Path(td), Path(td) / "home"
            als = clicky_set(td)
            sd = td / "scan"
            t0 = time.time()
            code, out = hx("scan", als, "--quick", "--out", sd, home=home)
            self.assertEqual(code, 0, out)
            self.assertLess(time.time() - t0, 30)
            groups = sorted(p.stem for p in sd.glob("*.json") if p.stem not in ("findings", "scan"))
            self.assertEqual(groups, ["files", "intent", "structure"])
            self.assertFalse((sd / "raw" / "names").exists())                  # nothing listened to
            self.assertTrue((sd / "raw" / "scanned.als").exists())             # kept for --since
            self.assertTrue(json.loads((sd / "scan.json").read_text())["quick"])

    def test_since_reruns_only_what_changed_and_keeps_decisions(self):
        with tempfile.TemporaryDirectory() as td:
            td, home = Path(td), Path(td) / "home"
            als = clicky_set(td)
            sd = td / "scan"
            code, out = hx("scan", als, "--only", "clips", "--only", "intent", "--only", "structure", "--out", sd, home=home)
            self.assertEqual(code, 0, out)
            first = json.loads((sd / "findings.json").read_text())["findings"]
            click = next(f for f in first if f["tool"] == "smooth" and f["where"] == "2.2.00")
            hx("fix", sd, "--decide", f"{click['id']}=approve@40", home=home)
            # nothing changed: nothing re-runs
            code, out = hx("scan", als, "--only", "clips", "--only", "intent", "--only", "structure", "--since", sd,
                           "--out", sd, home=home)
            self.assertEqual(code, 0, out)
            self.assertIn("re-ran no groups", out)
            # pan the track hard right (a mixer change): intent and structure re-run, clips carried over
            xml = gzip.open(als).read().decode()
            xml = xml.replace('<Pan><Manual Value="0"/><AutomationTarget Id="11"/>', '<Pan><Manual Value="1"/><AutomationTarget Id="11"/>')
            with gzip.open(als, "wb") as f:
                f.write(xml.encode())
            code, out = hx("scan", als, "--only", "clips", "--only", "intent", "--only", "structure", "--since", sd,
                           "--out", sd, home=home)
            self.assertEqual(code, 0, out)
            rerun = re.search(r"re-ran (.*?);", out).group(1)
            self.assertIn("intent", rerun)
            self.assertNotIn("clips", rerun)
            now = json.loads((sd / "findings.json").read_text())["findings"]
            self.assertTrue(all(f.get("carried") for f in now if f["tool"] == "smooth"))
            new = [f for f in now if f.get("new")]
            self.assertTrue(any("panned hard right" in f["problem"] for f in new), new)
            dec = json.loads((sd / "decisions.json").read_text())
            same = next(f for f in now if f["tool"] == "smooth" and f["where"] == "2.2.00")
            self.assertEqual(dec[same["id"]]["amount"], 40)                     # the decision followed its finding
            # watch --once: one more incremental quick pass, read-only
            before = als.read_bytes()
            code, out = py("hypnomix.workflow.watch", als, "--out", sd, "--once", home=home)
            self.assertEqual(code, 0, out)
            self.assertIn("nothing new", out)
            self.assertEqual(before, als.read_bytes())
            self.assertTrue((sd / "WATCH.md").exists())

    def test_changed_groups_mapping(self):
        from hypnomix.workflow import quick as Q
        groups = ["names", "files", "clips", "timing", "vocals", "effects", "devices", "noise", "intent", "structure"]
        rerun, _ = Q.changed_groups([dict(track="Lead", what="clip gain (take)")], groups, {"Lead": "Lead Vocal"})
        self.assertIn("vocals", rerun)
        self.assertIn("clips", rerun)
        self.assertNotIn("timing", rerun)
        self.assertNotIn("effects", rerun)
        rerun, _ = Q.changed_groups([dict(track="Bass", what="Compressor: Ratio")], groups, {"Bass": "Bass"})
        self.assertEqual(sorted(rerun), sorted(["effects", "devices", "intent", "structure"]))
        rerun, _ = Q.changed_groups([dict(track="Bass", what="fader")], groups, {"Bass": "Bass"})
        self.assertEqual(sorted(rerun), ["devices", "intent", "structure"])
        rerun, _ = Q.changed_groups([dict(track="(song)", what="tempo")], groups)
        self.assertEqual(rerun, groups)

    def test_watch_sees_a_save(self):
        import threading
        from hypnomix.workflow import watch as W
        with tempfile.TemporaryDirectory() as td:
            td, home = Path(td), Path(td) / "home"
            als = clicky_set(td)
            sd = td / "scan"
            old = os.environ.get("HYPNOMIX_HOME")
            os.environ["HYPNOMIX_HOME"] = str(home)
            lines, stop = [], threading.Event()
            try:
                th = threading.Thread(target=W.watch, args=(als, sd, 0.2, False, stop, lines.append, 2), daemon=True)
                th.start()
                deadline = time.time() + 60
                while not (sd / "findings.json").exists() and time.time() < deadline:
                    time.sleep(0.2)
                time.sleep(1.0)
                os.utime(als, (als.stat().st_atime, als.stat().st_mtime + 10))      # "saved again"
                th.join(timeout=90)
                stop.set()
            finally:
                if old is None:
                    os.environ.pop("HYPNOMIX_HOME", None)
                else:
                    os.environ["HYPNOMIX_HOME"] = old
            self.assertGreaterEqual(sum(1 for l in lines if l.startswith("[")), 2, lines)


if __name__ == "__main__":
    unittest.main()
