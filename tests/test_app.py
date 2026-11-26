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

    # ---- what the browser is told, who may ask, and what a request may be
    def raw(self, method, path, headers=None, body=b""):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=5)
        c.putrequest(method, path, skip_accept_encoding=True)
        for k, v in (headers or {}).items():
            c.putheader(k, v)
        c.endheaders(body)
        r = c.getresponse()
        data = r.read()
        out = (r.status, dict((k.lower(), v) for k, v in r.getheaders()), data)
        c.close()
        return out

    def test_every_response_says_it_may_not_be_framed_sniffed_or_scripted(self):
        for path in ("/", "/api/state", "/wiki.js", "/nope", "/wiki/assets/none.png"):
            code, h, _ = self.raw("GET", path)
            self.assertEqual(h["x-frame-options"], "DENY", path)
            self.assertEqual(h["x-content-type-options"], "nosniff", path)
            self.assertEqual(h["referrer-policy"], "no-referrer", path)
            self.assertEqual(h["cross-origin-resource-policy"], "same-origin", path)
            csp = h["content-security-policy"]
            for want in ("default-src 'self'", "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'", "form-action 'self'",
                         "connect-src 'self'", "style-src 'self' 'unsafe-inline'", "script-src-attr 'none'",
                         "img-src 'self' data: https://hypnomix.bradfieldenterprises.org",
                         "media-src 'self' blob: https://hypnomix.bradfieldenterprises.org"):
                self.assertIn(want, csp, path)
            self.assertNotIn("unsafe-eval", csp)
        code, h, _ = self.raw("POST", "/api/decide", {"Content-Length": "2"}, b"{}")       # a refusal is covered too
        self.assertEqual((code, h["x-frame-options"]), (403, "DENY"))

    def test_the_pages_one_inline_script_has_a_fresh_nonce(self):
        import re
        pages = [self.raw("GET", "/") for _ in range(2)]
        nonces = []
        for code, h, body in pages:
            m = re.search(r"script-src 'self' 'nonce-([\w-]+)'", h["content-security-policy"])
            nonces.append(m.group(1))
            html = body.decode()
            self.assertEqual(re.findall(r"<script(?![^>]*\ssrc=)[^>]*>", html), [f'<script nonce="{m.group(1)}">'])
        self.assertNotEqual(nonces[0], nonces[1])
        self.assertNotIn("nonce", self.raw("GET", "/api/state")[1]["content-security-policy"])

    def test_the_app_has_no_inline_event_handlers_for_the_policy_to_break(self):
        import re
        from hypnomix.app import ui
        sources = [ui.PAGE] + [p.read_text() for p in Path(ui.__file__).parent.glob("*.js")]
        for src in sources:
            self.assertEqual(re.findall(r"""<[a-z][^>]*\son[a-z]+\s*=\s*["'{\\]""", src), [])
            self.assertNotIn("javascript:", src)

    def test_another_website_may_open_the_page_and_nothing_else(self):
        cross = {"Sec-Fetch-Site": "cross-site"}
        nav = dict(cross, **{"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"})
        self.assertEqual(self.raw("GET", "/", nav)[0], 200)                                   # a link from elsewhere still opens it
        self.assertEqual(self.raw("GET", "/", dict(nav, **{"Sec-Fetch-Dest": "iframe"}))[0], 403)
        self.assertEqual(self.raw("GET", "/", dict(cross, **{"Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "script"}))[0], 403)
        for path in ("/api/state", "/wiki.js", "/api/live/poll?since=-1", "/audio?dir=x&f=y", "/api/wiki"):
            self.assertEqual(self.raw("GET", path, nav)[0], 403, path)
            self.assertEqual(self.raw("GET", path, cross)[0], 403, path)
        self.assertEqual(self.raw("POST", "/api/live/step", dict(cross, **{"Content-Length": "2"}), b"{}")[0], 403)
        self.assertEqual(self.raw("POST", "/api/master/record", dict(cross, **{"Content-Length": "2"}), b"{}")[0], 403)
        # the page itself, a tab on another port, and clients that send no browser headers keep working
        for h in ({"Sec-Fetch-Site": "same-origin"}, {"Sec-Fetch-Site": "none"}, {}):
            self.assertEqual(self.raw("GET", "/api/state", h)[0], 200, h)
        self.assertEqual(self.raw("POST", "/api/ab/state", {"Content-Length": "10"}, b'{"id":"x"}')[0], 200)

    def test_a_request_body_has_to_be_sane_and_early_refusals_close_the_connection(self):
        for length, code in (("-5", 400), ("abc", 400), ("1e3", 400), (str(self.S.MAX_BODY + 1), 413)):
            c, h, body = self.raw("POST", "/api/live/step", {"Content-Length": length})
            self.assertEqual((c, h.get("connection")), (code, "close"), length)
            self.assertIn("error", json.loads(body))
        c, h, _ = self.raw("POST", "/api/live/step", {"Content-Length": "5"}, b"[1,2]")                  # JSON, but not an object
        self.assertEqual(c, 400)
        c, h, _ = self.raw("POST", "/api/live/step", {"Content-Length": "9", "Origin": "http://evil.example"}, b"{}")
        self.assertEqual((c, h.get("connection")), (403, "close"))
        big = b'{"id":"x","pad":"' + b"a" * (self.S.MAX_BODY - 20) + b'"}'
        c, h, _ = self.raw("POST", "/api/ab/state", {"Content-Length": str(len(big))}, big)
        self.assertEqual((c, len(big)), (200, self.S.MAX_BODY - 1))                              # a body just under the limit is taken
        self.assertEqual(self.S.make_handler(1).timeout, self.S.IDLE_SECONDS)

    def test_the_librarys_own_error_pages_carry_the_headers_too(self):
        for method, path in (("OPTIONS", "/"), ("PUT", "/api/state"), ("DELETE", "/"), ("HEAD", "/")):
            code, h, body = self.raw(method, path)
            self.assertEqual(code, 501, method)
            self.assertEqual(h["x-frame-options"], "DENY", method)
            self.assertEqual(h["x-content-type-options"], "nosniff", method)
            self.assertIn("frame-ancestors 'none'", h["content-security-policy"], method)
        import socket
        s = socket.create_connection(("127.0.0.1", self.srv.server_address[1]), timeout=5)
        s.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nX: " + b"a" * 70000 + b"\r\n\r\n")                  # a header line the library refuses
        head = s.recv(4000).lower()
        s.close()
        self.assertIn(b"431", head.split(b"\r\n")[0])
        self.assertIn(b"x-frame-options: deny", head)

    def test_content_length_must_be_plain_digits_and_chunked_bodies_are_refused(self):
        for length in ("1_0", "+5", " ", "0x10", "\xb2", "5 5"):
            c, h, body = self.raw("POST", "/api/live/step", {"Content-Length": length}, b"")
            self.assertEqual((c, h.get("connection")), (400, "close"), repr(length))
        c, h, body = self.raw("POST", "/api/live/step", {"Content-Length": "9" * 40})
        self.assertEqual((c, h.get("connection")), (413, "close"))
        c, h, body = self.raw("POST", "/api/live/step", {"Transfer-Encoding": "chunked"}, b"2\r\n{}\r\n0\r\n\r\n")
        self.assertEqual((c, h.get("connection")), (400, "close"))
        self.assertIn("Content-Length", json.loads(body)["error"])
        self.assertEqual(self.raw("POST", "/api/ab/state", {"Content-Length": "10"}, b'{"id":"x"}')[0], 200)     # an ordinary request is unchanged

    def test_a_request_that_drips_in_is_cut_off_after_a_total_time_not_a_time_per_read(self):
        """The reviewer's case: one byte every few seconds kept a handler thread for as long as the client liked."""
        import socket, time
        from unittest import mock
        with mock.patch.object(self.S, "READ_SECONDS", 0.8):
            for head in (b"POST /api/live/step HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 6\r\n\r\n",     # the body drips
                         b"GET /api/state HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Slow: "):                                # the head drips
                s = socket.create_connection(("127.0.0.1", self.srv.server_address[1]), timeout=5)
                t = time.time()
                s.sendall(head)
                closed = None
                for _ in range(12):                                   # one byte every 0.3 s, so each read is well inside any per-read limit
                    time.sleep(0.3)
                    try:
                        s.sendall(b"a")
                    except OSError:
                        closed = time.time() - t
                        break
                    s.settimeout(0.01)
                    try:
                        if s.recv(1000) is not None:
                            closed = time.time() - t
                            break
                    except socket.timeout:
                        pass
                    except OSError:
                        closed = time.time() - t
                        break
                s.close()
                self.assertIsNotNone(closed, head[:8])
                self.assertLess(closed, 2.5, head[:8])
            # a request that arrives in time is answered, and a slow answer is not cut by the clock that guards the arriving
            real = self.S.ab_set_state

            def slow(*a):
                time.sleep(1.4)
                return real(*a)
            with mock.patch.object(self.S, "ab_set_state", slow):
                c, h, body = self.raw("POST", "/api/ab/state", {"Content-Length": "10"}, b'{"id":"x"}')
            self.assertEqual(c, 200)

    def test_a_silent_connection_is_let_go(self):
        import socket, time
        old = self.S.IDLE_SECONDS
        h = self.S.make_handler(self.srv.server_address[1])
        h.timeout = 0.4
        srv = ThreadingHTTPServer(("127.0.0.1", 0), h)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            s = socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=5)
            s.sendall(b"POST /api/live/step HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 50\r\n\r\n{")      # promises 50 bytes, sends 1
            t = time.time()
            self.assertEqual(s.recv(100), b"")                                                          # the server hung up
            self.assertLess(time.time() - t, 4)
            s.close()
        finally:
            srv.shutdown()
        self.assertEqual(self.S.IDLE_SECONDS, old)

    def test_the_devices_may_only_point_at_files_of_the_right_kind(self):
        from hypnomix.app import align as AL
        bounces = Path(self.td.name) / "bounces"
        bounces.mkdir(exist_ok=True)
        good = bounces / "master-1.wav"
        good.write_bytes(b"RIFF")
        self.assertEqual(self.S.bounce_file(str(good)), str(good.resolve()))
        outside = Path(self.td.name) / "elsewhere.wav"
        outside.write_bytes(b"RIFF")
        (bounces / "notes.txt").write_text("x")
        link = bounces / "link.wav"
        link.symlink_to(outside)
        for bad in (str(outside), "/etc/passwd", str(bounces / "notes.txt"), str(bounces / "nope.wav"), str(bounces / ".." / "elsewhere.wav"),
                    str(link), "~/x.wav", "", str(bounces)):
            if bad:
                with self.assertRaises(ValueError, msg=bad):
                    self.S.bounce_file(bad)
        code, r, _ = call(self.base, "/api/master/record", dict(state="stop", path=str(outside)))
        self.assertEqual(code, 400)
        self.assertIn("recording this app made", r["error"])
        # Align: the set named in a request gets the same check as Choose set
        als = Path(self.td.name) / "My Song.als"
        als.write_bytes(b"x")
        txt = Path(self.td.name) / "notes.txt"
        txt.write_text("x")
        lnk = Path(self.td.name) / "sneaky.als"
        lnk.symlink_to(txt)
        run = dict(guide="Lead", parts=["Double"])
        for bad in ("/etc/passwd", str(txt), str(lnk), str(Path(self.td.name) / "missing.als"), str(Path(self.td.name))):
            code, r, _ = call(self.base, "/api/align/run", dict(run, set=bad))
            self.assertEqual(code, 400, bad)
            self.assertIn("not a Live set or REAPER project", r["error"])
        self.assertEqual(AL.set_file(str(als)), str(als.resolve()))
        before = AL.ALIGN["set"]
        for body in (dict(guide="Lead", parts=[1, 2]), dict(guide="Lead", parts=[["a"]]), dict(guide="Lead", parts="Double"), dict(guide=7, parts=["Double"]),
                     dict(guide=["Lead"], parts=["Double"]), dict(parts=["Double"]), dict(guide="Lead", parts={"a": 1}), dict(guide="Lead", parts=[None])):
            code, r, _ = call(self.base, "/api/align/run", dict(body, set=str(als)))                       # a clear 400, not a dropped connection
            self.assertEqual(code, 400, body)
            self.assertTrue(r["error"], body)
        self.assertEqual(AL.ALIGN["set"], before)                                                       # and nothing was remembered from it
        self.assertEqual(AL.track_names(dict(guide=" Lead ", parts=["Lead", " Double ", ""])), ("Lead", ["Double"]))
        for body, why in ((dict(guide="-x", parts=["Double"]), "dash"), (dict(guide="Lead", parts=["--apply"]), "dash"),
                          (dict(guide="Lead", parts=["Double"], protect=[[0, "inf"]]), "between"), (dict(guide="Lead", parts=["Double"], protect=5), "list"),
                          (dict(guide="Lead", parts=["Double"], chords="-h"), "dash")):
            code, r, _ = call(self.base, "/api/align/run", dict(body, set=str(als)))
            self.assertEqual(code, 400, body)
            self.assertIn(why, r["error"])


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
            for k in ("plugin~", "plugout~", "live.thisdevice", "jsui"):               # audio still passes through
                self.assertIn(k, kinds)
            self.assertIn("Float", kinds)                                             # the floating-panel toggle
            sub = next(b["box"]["patcher"] for b in patch["patcher"]["boxes"] if b["box"].get("text") == "p hypnomix_panel")
            self.assertEqual([b["box"].get("jsarguments") for b in sub["boxes"] if b["box"]["maxclass"] == "jsui"], [["float"]])
            self.assertEqual(len(patch["patcher"]["lines"]), 11)
            js = (out / "hypnomix_device.js").read_text()
            self.assertIn("127.0.0.1:8791", js)
            self.assertNotIn("__", js.replace("__PORT__", ""))                            # every placeholder filled
            for fn in ("function paint()", "function onclick(", "function bang()", "function jump("):
                self.assertIn(fn, js)


if __name__ == "__main__":
    unittest.main()
