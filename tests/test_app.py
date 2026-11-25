"""The hypnomix app server (first pass in a window) and the Max for Live device builder."""
import json, os, tempfile, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np
import soundfile as sf


def call(base, path, body=None, token=None, headers=None):
    h = dict(headers or {})
    if token:
        h["X-Hypnomix"] = token
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=h,
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if r.headers.get("Content-Type", "").startswith("application/json") else raw), r.headers
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), e.headers


class App(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        os.environ["HYPNOMIX_APP_HOME"] = cls.td.name
        from hypnomix.app import server as S
        cls.S = S
        d = Path(cls.td.name) / "scan" / "Song"
        (d / "ab").mkdir(parents=True)
        findings = [
            dict(id="smooth-1", tool="smooth", kind="click", severity="low", track="Bass", where="12.3.50", problem="click at a clip edge", fix="4 ms fade", applies="set"),
            dict(id="tune-Lead", tool="tune", kind="pitch", severity="medium", track="Lead", where="bars 17-24", problem="flat notes", fix="tune", applies="audio"),
            dict(id="mix-1", tool="measure", kind="loudness", severity="info", track="mix", where="", problem="-12 LUFS", fix="", applies="info"),
        ]
        (d / "findings.json").write_text(json.dumps(dict(set="/nowhere/Song.als", findings=findings, notes=[])))
        sf.write(str(d / "ab" / "smooth-1 A (now).wav"), np.zeros(4410, dtype=np.float32), 44100)
        (d / "ab" / "ab.json").write_text(json.dumps({"smooth-1": {"a": "smooth-1 A (now).wav", "b": "smooth-1 A (now).wav"}}))
        cls.dir = str(d)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(0))
        port = cls.srv.server_address[1]
        cls.srv.RequestHandlerClass = S.make_handler(port)
        cls.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.td.cleanup()
        os.environ.pop("HYPNOMIX_APP_HOME", None)

    def test_page_and_state(self):
        code, page, _ = call(self.base, "/")
        self.assertEqual(code, 200)
        self.assertIn(self.S.TOKEN.encode(), page)
        code, st, _ = call(self.base, "/api/state")
        self.assertEqual([s["name"] for s in st["scans"]], ["Song"])
        self.assertEqual(st["scans"][0]["findings"], 2)                     # the info item is not a decision
        names = [c["name"] for c in st["commands"]]
        self.assertIn("scan", names)
        self.assertNotIn("install", names)

    def test_where_becomes_a_place_in_the_set(self):
        L = self.S.locate
        self.assertEqual(L({"where": "12.3.50"}, 120, 4), (45.5, 49.5))
        self.assertEqual(L({"where": "bars 17-24"}, 120, 4), (64, 96))
        self.assertEqual(L({"where": "1:30"}, 120, 4), (179.0, 183.0))
        self.assertIsNone(L({"where": ""}, 120, 4))

    def test_changes_need_the_pages_token_and_stay_inside_the_scan_folder(self):
        body = dict(dir=self.dir, id="smooth-1", decision="approve")
        self.assertEqual(call(self.base, "/api/decide", body)[0], 403)
        self.assertEqual(call(self.base, "/api/decide", body, self.S.TOKEN, {"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(call(self.base, "/api/decide", body, self.S.TOKEN)[0], 200)
        self.assertEqual(json.loads((Path(self.dir) / "decisions.json").read_text())["smooth-1"]["decision"], "approve")
        self.assertEqual(call(self.base, "/api/decide", dict(body, dir="/etc"), self.S.TOKEN)[0], 400)
        self.assertEqual(call(self.base, "/api/review?dir=/etc")[0], 400)
        self.assertEqual(call(self.base, "/api/tool", dict(cmd="install", args=""), self.S.TOKEN)[0], 400)

    def test_review_and_audio(self):
        code, r, _ = call(self.base, "/api/review?dir=" + urllib.request.quote(self.dir))
        self.assertEqual(code, 200)
        self.assertEqual(r["suggested_out"], "Song (fixed).als")
        self.assertEqual(r["findings"][0]["jump"]["track"], "Bass")
        q = "/audio?dir=" + urllib.request.quote(self.dir) + "&f=" + urllib.request.quote("smooth-1 A (now).wav")
        code, data, h = call(self.base, q, headers={"Range": "bytes=0-99"})
        self.assertEqual((code, len(data)), (206, 100))
        self.assertEqual(call(self.base, q.replace("smooth-1%20A", "..%2F..%2Fx"))[0], 404)

    def test_live_device_steps_decides_and_gets_jumps(self):
        call(self.base, "/api/review?dir=" + urllib.request.quote(self.dir))          # the app opened this review
        _, p, _ = call(self.base, "/api/live/poll?since=-1")
        self.assertIsNone(p["cmd"])                                                     # nothing replayed on connect
        seq = p["seq"]
        _, cur, _ = call(self.base, "/api/live/step", dict(delta=1))
        self.assertEqual(cur["id"], "smooth-1")
        _, p, _ = call(self.base, f"/api/live/poll?since={seq}")
        self.assertEqual(p["cmd"]["type"], "jump")
        self.assertEqual(p["cmd"]["track"], "Bass")
        _, cur, _ = call(self.base, "/api/live/decide", dict(decision="skip"))
        self.assertEqual(cur["decision"], "skip")
        _, cur, _ = call(self.base, "/api/live/step", dict(delta=1, undecided=True))
        self.assertEqual(cur["id"], "tune-Lead")
        _, st, _ = call(self.base, "/api/state")
        self.assertTrue(st["live"])
        code, r, _ = call(self.base, "/api/live/jump", dict(dir=self.dir, id="mix-1"), self.S.TOKEN)
        self.assertEqual(code, 400)                                                     # the mix has no place to jump to


class Device(unittest.TestCase):
    def test_builds_a_device_live_can_read(self):
        from hypnomix.app import device as D
        blank = {"patcher": {"boxes": [{"box": {"id": "obj-1", "maxclass": "newobj", "text": "plugin~"}},
                                       {"box": {"id": "obj-2", "maxclass": "newobj", "text": "plugout~"}},
                                       {"box": {"id": "obj-6", "maxclass": "live.comment", "text": "Build your Audio Effect here"}}],
                             "lines": [{"patchline": {"destination": ["obj-2", 0], "source": ["obj-1", 0]}}],
                             "openinpresentation": 0, "devicewidth": 0.0}}
        with tempfile.TemporaryDirectory() as td:
            tpl = Path(td) / "Max Audio Effect.amxd"
            D.write_amxd(tpl, b"ampf\x04\x00\x00\x00aaaameta\x04\x00\x00\x00\x00\x00\x00\x00", blank)
            out = D.build(Path(td) / "out", tpl)
            raw = (out / "Hypnomix.amxd").read_bytes()
            self.assertTrue(raw.startswith(b"ampf") and raw.endswith(b"\x00"))
            i = raw.index(b"ptch")
            self.assertEqual(int.from_bytes(raw[i + 4:i + 8], "little"), len(raw) - i - 8)
            head, patch = D.read_amxd(out / "Hypnomix.amxd")
            kinds = [b["box"].get("text") or b["box"]["maxclass"] for b in patch["patcher"]["boxes"]]
            self.assertEqual(kinds, ["plugin~", "plugout~", "live.thisdevice", "jsui"])   # audio still passes through
            self.assertEqual(len(patch["patcher"]["lines"]), 2)
            js = (out / "hypnomix_device.js").read_text()
            self.assertIn("127.0.0.1:8791", js)
            self.assertNotIn("__", js.replace("__PORT__", ""))                            # every placeholder filled
            for fn in ("function paint()", "function onclick(", "function bang()", "function jump("):
                self.assertIn(fn, js)


if __name__ == "__main__":
    unittest.main()
