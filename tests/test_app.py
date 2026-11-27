"""The hypnomix app server (first pass in a window) and the Max for Live device builder."""
import json, os, shutil, subprocess, sys, tempfile, threading, time, unittest, urllib.error, urllib.request
from unittest import mock
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
        (d / "findings.json").write_text(json.dumps(dict(set="/nowhere/Song.als", findings=findings, notes=[])), encoding="utf-8")
        sf.write(str(d / "ab" / "smooth-1 A (now).wav"), np.zeros(4410, dtype=np.float32), 44100)
        (d / "ab" / "ab.json").write_text(json.dumps({"smooth-1": {"a": "smooth-1 A (now).wav", "b": "smooth-1 A (now).wav"}}), encoding="utf-8")
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
        self.assertNotIn("commands", st)                                    # the 14 KB list is not sent every second
        _, cm, _ = call(self.base, "/api/commands")
        self.assertEqual(cm["rev"], st["commands_rev"])
        names = [c["name"] for c in cm["commands"]]
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
        self.assertEqual(json.loads((Path(self.dir) / "decisions.json").read_text(encoding="utf-8"))["smooth-1"]["decision"], "approve")
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
        sources = [ui.PAGE] + [p.read_text(encoding="utf-8") for p in Path(ui.__file__).parent.glob("*.js")]
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
        (bounces / "notes.txt").write_text("x", encoding="utf-8")
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
        txt.write_text("x", encoding="utf-8")
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


def F(id, tool="smooth", kind="click", severity="low", track="Vox", where="1.1.00", applies="set", **kw):
    return dict(dict(id=id, n=1, tool=tool, kind=kind, severity=severity, track=track, where=where, applies=applies,
                     problem="a problem", fix="a fix"), **kw)


DEFAULTS = [F("order-1", "order", "track-order", track="(all tracks)", where="", default="approve",
              fix="reorder the tracks. ON BY DEFAULT: skip this item to keep the current order"),
            F("retire-1", "tidy", "retire-off", track="Old A, Old B", where="2 switched-off track(s)", default="approve", retire=["Old A", "Old B"]),
            F("merge-1", "tidy", "consolidate", track="Gtr 2 -> Gtr 1", where="4 clip(s)", default="approve", removes=True)]


class AppFlow(unittest.TestCase):
    """What the review and Apply pages are told, and what the app starts when they are pressed: the commands themselves are
    stood in for here (the audit that found these ran the real ones)."""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.root = Path(cls.td.name)
        cls.work = cls.root / "work"
        cls.music = cls.root / "music"
        cls.music.mkdir()
        os.environ["HYPNOMIX_APP_HOME"] = str(cls.work)
        from hypnomix.app import server as S
        cls.S = S
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(0))
        port = cls.srv.server_address[1]
        cls.srv.RequestHandlerClass = S.make_handler(port)
        cls.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.td.cleanup()
        os.environ.pop("HYPNOMIX_APP_HOME", None)

    def setUp(self):
        shutil.rmtree(self.work / "scan", ignore_errors=True)
        for f in self.music.iterdir():
            shutil.rmtree(f) if f.is_dir() else f.unlink()
        self.S.JOB.update(status="idle", log=[], files=[], reason="", stopped=False, dir="", kind="")
        self.runs = []                                            # (kind, title, steps, sdir, watch) of every job the app started
        self._run_job = self.S.run_job
        self.S.run_job = lambda kind, title, steps, sdir="", watch=(): (self.runs.append((kind, title, steps, str(sdir), list(watch))), 1)[1]

    def tearDown(self):
        self.S.run_job = self._run_job

    def post(self, path, body):
        return call(self.base, path, body, self.S.TOKEN)

    def scan(self, name, source, findings, dec=None, mode="set", **meta):
        d = self.work / "scan" / name
        (d / "ab").mkdir(parents=True)
        (d / "findings.json").write_text(json.dumps(dict(set=str(source), notes=[], findings=findings)), encoding="utf-8")
        was = Path(source).stat().st_mtime if Path(source).is_file() else None
        (d / "scan.json").write_text(json.dumps(dict(dict(set=str(source), mode=mode, set_mtime=was), **meta)), encoding="utf-8")
        if dec is not None:
            (d / "decisions.json").write_text(json.dumps(dec), encoding="utf-8")
        return d

    def source(self, name, text="x"):
        p = self.music / name
        p.write_text(text, encoding="utf-8")
        return p

    def review(self, d):
        code, r, _ = call(self.base, "/api/review?dir=" + urllib.request.quote(str(d)))
        self.assertEqual(code, 200, r)
        return r

    # ---- 1. the Apply card tells the truth about on-by-default items
    def test_on_by_default_items_are_in_the_page_and_in_what_apply_counts(self):
        als = self.source("Song.als")
        d = self.scan("Song", als, [F("smooth-1"), F("eq-1", "audit", "eq", applies="manual")] + DEFAULTS)
        r = self.review(d)
        by = {f["id"]: f for f in r["findings"]}
        self.assertTrue(by["order-1"]["on_by_default"])
        self.assertEqual((by["order-1"]["default"], by["order-1"]["applies"]), ("approve", "set"))
        self.assertEqual(by["retire-1"]["retire_n"], 2)
        self.assertFalse(by["smooth-1"]["on_by_default"])
        self.assertEqual(r["archive_name"], "Song (archive, all takes).als")
        plan = self.S.apply_plan(r["findings"], r["decisions"])
        self.assertEqual([f["id"] for f in plan["auto"]], ["order-1", "retire-1", "merge-1"])      # nothing approved, three steps run
        self.assertEqual([f["id"] for f in plan["defaults"]], ["order-1", "retire-1", "merge-1"])
        # approving one by-hand item changes nothing about what is written: it is listed, not applied
        self.assertEqual(self.post("/api/decide", dict(dir=str(d), id="eq-1", decision="approve"))[0], 200)
        plan = self.S.apply_plan(self.review(d)["findings"], self.review(d)["decisions"])
        self.assertEqual([f["id"] for f in plan["manual"]], ["eq-1"])
        self.assertEqual(len(plan["auto"]), 3)
        # turning one off records a skip through the usual route, and it is no longer in the plan
        self.assertEqual(self.post("/api/decide", dict(dir=str(d), id="retire-1", decision="skip"))[0], 200)
        r = self.review(d)
        self.assertEqual(r["decisions"]["retire-1"]["decision"], "skip")
        self.assertEqual([f["id"] for f in self.S.apply_plan(r["findings"], r["decisions"])["auto"]], ["order-1", "merge-1"])
        # the song list counts them too
        row = call(self.base, "/api/state")[1]["scans"][0]
        self.assertEqual((row["approved"], row["on_default"]), (1, 2))

    def test_apply_refuses_when_nothing_can_be_written_and_names_what_will_be(self):
        als = self.source("Song.als")
        d = self.scan("Song", als, [F("smooth-1"), F("eq-1", "audit", "eq", applies="manual")] + DEFAULTS,
                      {"eq-1": {"decision": "approve"}, "order-1": {"decision": "skip"}, "retire-1": {"decision": "skip"}, "merge-1": {"decision": "skip"}})
        code, r, _ = self.post("/api/fix", dict(dir=str(d)))                         # only a by-hand item is approved
        self.assertEqual(code, 409)
        self.assertIn("Nothing here can be applied automatically", r["error"])
        self.assertIn("handoff", r["error"])
        self.assertEqual(self.runs, [])
        self.assertEqual(self.post("/api/decide", dict(dir=str(d), id="smooth-1", decision="approve"))[0], 200)
        code, r, _ = self.post("/api/fix", dict(dir=str(d), out="Song (fixed)"))
        self.assertEqual(code, 200, r)
        kind, title, steps, sdir, watch = self.runs[-1]
        argv = steps[0][1]
        self.assertEqual(argv[:2], ["fix", str(d.resolve())])
        self.assertIn("--approved", argv)
        self.assertEqual(Path(argv[argv.index("--out") + 1]), self.music / "Song (fixed).als")      # the suffix is enforced
        self.assertIn(self.music.resolve(), {Path(w).resolve() for w in watch})

    def test_only_on_by_default_steps_are_enough_to_apply(self):
        als = self.source("Song.als")
        d = self.scan("Song", als, DEFAULTS)
        self.assertEqual(self.post("/api/fix", dict(dir=str(d)))[0], 200)

    # ---- 2. the new file's name and ending follow the kind of project
    def test_the_new_files_ending_follows_the_scan_and_the_name_is_free(self):
        S = self.S
        self.assertEqual(S.source_kind("/x/Song.als"), "als")
        self.assertEqual(S.source_kind("/x/Song.rpp"), "rpp")
        self.assertEqual(S.source_kind("/x/Sess.ardour", "ardour"), "ardour")
        self.assertEqual(S.source_kind("/x/Stems", "folder"), "folder")
        als = self.source("Song.als")
        self.assertEqual(S.free_out(als, "als"), "Song (fixed).als")
        (self.music / "Song (fixed).als").write_text("x", encoding="utf-8")
        (self.music / "Song (fixed 2).als").write_text("x", encoding="utf-8")
        self.assertEqual(S.free_out(als, "als"), "Song (fixed 3).als")
        self.assertEqual(S.free_out(self.music / "R.rpp", "rpp"), "R (fixed).rpp")
        self.assertEqual(S.free_out(self.music / "S.ardour", "ardour"), "S (fixed).ardour")
        self.assertEqual(S.clean_out("My copy", "rpp", als), "My copy.rpp")
        self.assertEqual(S.clean_out("My copy.als", "rpp", als), "My copy.rpp")                 # the wrong ending is replaced, not stacked
        self.assertEqual(S.clean_out("Song.rpp.als", "als", als), "Song.als")
        self.assertEqual(S.clean_out("../../etc/passwd", "als", als), "-..-etc-passwd.als")     # no folders
        self.assertEqual(S.clean_out("  ", "ardour", self.music / "S.ardour"), "S (fixed).ardour")
        for name, mode, suffix in (("Rsong.rpp", "reaper", ".rpp"), ("Sess.ardour", "ardour", ".ardour")):
            src = self.source(name)
            d = self.scan(name.split(".")[0], src, [F("fade-1", edit=dict(op="fade", item="r1"))], {"fade-1": {"decision": "approve"}}, mode=mode)
            r = self.review(d)
            self.assertEqual((r["kind"], r["suffix"]), ({".rpp": "rpp", ".ardour": "ardour"}[suffix], suffix))
            self.assertEqual(r["suggested_out"], f"{src.stem} (fixed){suffix}")
            code, j, _ = self.post("/api/fix", dict(dir=str(d), out="Mine.als"))
            self.assertEqual(code, 200, j)
            self.assertEqual(Path(j["out"]).name, "Mine" + suffix, j)                              # never "Rsong (fixed).rpp.als"
        (self.music / "Taken.als").write_text("x", encoding="utf-8")
        d = self.scan("Song", als, [F("smooth-1")], {"smooth-1": {"decision": "approve"}})
        code, j, _ = self.post("/api/fix", dict(dir=str(d), out="Taken"))
        self.assertEqual(code, 409)
        self.assertIn("already exists", j["error"])
        # a folder scan writes no project file: repaired copies go to the scan's fixed folder
        stems = self.music / "Stems"
        stems.mkdir()
        d = self.scan("Stems", stems, [F("clip-1", "repair", "clip", applies="audio")], {"clip-1": {"decision": "approve"}}, mode="folder")
        r = self.review(d)
        self.assertEqual((r["kind"], r["suggested_out"]), ("folder", ""))
        code, j, _ = self.post("/api/fix", dict(dir=str(d)))
        self.assertEqual((code, j["out"]), (200, ""))
        self.assertNotIn("--out", self.runs[-1][2][0][1])

    def test_an_ardour_session_does_not_promise_what_fix_cannot_write(self):
        src = self.source("Sess.ardour")
        fade = F("clips-1", "clips", "click", edit=dict(op="fade", item="r1"))
        d = self.scan("Sess", src, [fade, F("order-1", "order", "track-order", default="approve", track="(all tracks)"),
                                    F("tune-Lead", "tune", "pitch", applies="audio")], mode="ardour")
        r = self.review(d)
        by = {f["id"]: f for f in r["findings"]}
        self.assertEqual((by["clips-1"]["applies_here"], by["order-1"]["applies_here"], by["tune-Lead"]["applies_here"]), ("set", "manual", "blocked"))
        plan = self.S.apply_plan(r["findings"], r["decisions"])
        self.assertEqual(([f["id"] for f in plan["auto"]], [f["id"] for f in plan["defmanual"]]), ([], ["order-1"]))
        self.post("/api/decide", dict(dir=str(d), id="tune-Lead", decision="approve"))
        self.post("/api/decide", dict(dir=str(d), id="clips-1", decision="approve"))
        code, j, _ = self.post("/api/fix", dict(dir=str(d)))
        self.assertEqual(code, 409)
        self.assertIn("tune-Lead", j["error"])

    # ---- 3. the song chooser and the file manager
    def test_the_chooser_takes_every_kind_of_project_and_never_fails_silently(self):
        S = self.S
        calls = []

        def fake(argv, **kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, self.rc, self.out, self.err)
        real_run, real_plat = S.subprocess.run, S.sys.platform
        S.subprocess.run = fake
        try:
            S.sys.platform = "darwin"
            self.rc, self.out, self.err = 0, "/x/Song.rpp\n", ""
            self.assertEqual(S.pick("song"), "/x/Song.rpp")
            script = calls[-1][2]
            for ext in ('"als"', '"rpp"', '"ardour"'):
                self.assertIn(ext, script)
            S.pick("folder")
            self.assertIn("choose folder", calls[-1][2])
            self.rc, self.out, self.err = 1, "", "execution error: User canceled. (-128)"
            self.assertEqual(S.pick("song"), "")                                       # Cancel is not an error
            self.rc, self.err = 1, "execution error: something else (-1)"
            with self.assertRaises(S.PickUnavailable) as cm:
                S.pick("song")
            self.assertIn("paste the path", str(cm.exception))
            S.sys.platform = "win32"                                                 # Windows: the standard library's own chooser, in a process of its own
            self.rc, self.out, self.err = 0, "C:/Music/Song.rpp", ""
            self.assertEqual(S.pick("song"), "C:/Music/Song.rpp")
            self.assertEqual(calls[-1][1], "-c")
            self.assertEqual(calls[-1][3], "song")
            self.rc, self.out, self.err = 3, "", "tkinter is not installed (No module named 'tkinter')"
            with self.assertRaises(S.PickUnavailable) as cm:
                S.pick("song")
            self.assertIn("Path box", str(cm.exception))
            with self.assertRaises(ValueError):
                S.pick("../../etc")
        finally:
            S.subprocess.run, S.sys.platform = real_run, real_plat
        self.assertIn("*.ardour", S._TK)
        # the route says why in a plain sentence (409), a bad kind is a 400
        real_pick = S.pick
        S.pick = lambda kind: (_ for _ in ()).throw(S.PickUnavailable("the file chooser is not available here: type or paste the path in the Path box instead"))
        try:
            code, r, _ = self.post("/api/pick", dict(kind="song"))
        finally:
            S.pick = real_pick
        self.assertEqual(code, 409)
        self.assertIn("Path box", r["error"])
        self.assertEqual(self.post("/api/pick", dict(kind="nope"))[0], 400)
        self.assertEqual(self.post("/api/pick", {})[0], 400)

    def test_show_files_works_off_macos_and_says_when_it_cannot(self):
        S = self.S
        f = self.source("a.als")
        opened = []
        real_popen, real_run, real_plat, real_win, real_which = S.subprocess.Popen, S.subprocess.run, S.sys.platform, S.is_windows, S.shutil.which
        S.subprocess.Popen = lambda argv, **kw: opened.append(argv)
        S.subprocess.run = lambda argv, **kw: opened.append(argv) or subprocess.CompletedProcess(argv, 0)
        try:
            S.sys.platform, S.is_windows = "linux", lambda: False            # a real Windows answers is_windows() from os.name
            S.shutil.which = lambda n: None
            ok, why = S.reveal(f)
            self.assertFalse(ok)
            self.assertIn("xdg-open", why)
            self.assertIn(str(self.music), why)
            S.shutil.which = lambda n: "/usr/bin/xdg-open"
            self.assertTrue(S.reveal(f)[0])
            self.assertEqual(opened[-1], ["/usr/bin/xdg-open", str(self.music)])        # the folder, never the file itself
            S.sys.platform, S.is_windows = "win32", lambda: True
            self.assertTrue(S.reveal(f)[0])
            self.assertEqual(opened[-1], f'explorer /select,"{f}"')          # the quotes go round the path alone, not the whole argument
            S.sys.platform, S.is_windows = "darwin", lambda: False
            self.assertTrue(S.reveal(f)[0])
            self.assertEqual(opened[-1][:2], ["open", "-R"])
        finally:
            S.subprocess.Popen, S.subprocess.run, S.sys.platform, S.is_windows, S.shutil.which = real_popen, real_run, real_plat, real_win, real_which
        code, r, _ = self.post("/api/reveal", dict(path=str(self.music / "gone.als")))
        self.assertEqual((code, r["shown"]), (200, False))
        self.assertIn("not there any more", r["message"])
        self.assertEqual(self.post("/api/reveal", {})[0], 400)

    # ---- 4. scan folders
    def test_the_same_path_goes_back_to_its_folder_and_a_different_one_never_shares(self):
        a = self.source("Song.als")
        (self.music / "Elsewhere").mkdir()
        b = self.music / "Elsewhere" / "Song.als"
        b.write_text("y", encoding="utf-8")
        ard = self.music / "Song"                                  # an Ardour session folder with the same name
        ard.mkdir()
        (ard / "Song.ardour").write_text("z", encoding="utf-8")
        stems1, stems2 = self.music / "x" / "Stems", self.music / "y" / "Stems"
        for s in (stems1, stems2):
            s.mkdir(parents=True)
        dirs = []
        for src in (a, b, ard, stems1, stems2, a, stems2):
            code, r, _ = self.post("/api/scan", dict(source=str(src)))
            self.assertEqual(code, 200, r)
            d = Path(r["dir"])
            if not d.exists() or not (d / "scan.json").exists():                        # the stand-in scan: record what a real one would
                (d / "raw").mkdir(parents=True, exist_ok=True)
                (d / "scan.json").write_text(json.dumps(dict(set=str(src.resolve()), mode="set")), encoding="utf-8")
                (d / "findings.json").write_text(json.dumps(dict(set=str(src.resolve()), findings=[])), encoding="utf-8")
            dirs.append((r["dir"], r["reused"]))
        names = [Path(d).name for d, _ in dirs]
        self.assertEqual(names, ["Song", "Song (2)", "Song (3)", "Stems", "Stems (2)", "Song", "Stems (2)"])
        self.assertEqual([re for _, re in dirs], [False, False, False, False, False, True, True])
        rows = {r["name"]: r for r in call(self.base, "/api/state")[1]["scans"]}
        self.assertTrue(all(rows[n]["same_name"] for n in ("Song", "Song (2)", "Stems", "Stems (2)")))
        self.assertEqual(rows["Song (2)"]["parent"], str(b.resolve().parent))
        self.assertEqual(rows["Stems"]["parent"], str(stems1.resolve().parent))
        # decisions and the fix log of one never turn up in another
        (self.work / "scan" / "Song" / "decisions.json").write_text('{"x": {"decision": "approve"}}', encoding="utf-8")
        self.assertEqual(self.review(self.work / "scan" / "Song (2)")["decisions"], {})

    def test_scan_asks_for_a_song_that_can_be_scanned(self):
        self.assertEqual(self.post("/api/scan", {})[0], 400)
        code, r, _ = self.post("/api/scan", dict(source=str(self.music / "nope.als")))
        self.assertEqual(code, 400)
        self.assertIn("not found", r["error"])
        notes = self.source("notes.txt")
        code, r, _ = self.post("/api/scan", dict(source=str(notes)))
        self.assertEqual(code, 400)
        self.assertIn(".ardour", r["error"])
        self.assertEqual(self.post("/api/scan", dict(source=str(self.source("S.rpp")), mix=5))[0], 400)

    # ---- 5. re-scans and the saved-after-the-scan banner
    def test_a_rescan_of_a_live_set_carries_decisions_and_others_set_them_aside(self):
        als = self.source("Song.als")
        d = self.scan("Song", als, [F("smooth-1")], {"smooth-1": {"decision": "approve"}}, mix="/m/mix.wav", key="F# major")
        (d / "app-scan.json").write_text(json.dumps(dict(source=str(als), deep=True, like="/m/like.wav")), encoding="utf-8")
        code, r, _ = self.post("/api/rescan", dict(dir=str(d)))
        self.assertEqual((code, r["reused"], r["carries_decisions"]), (200, True, True))
        steps = self.runs[-1][2]
        argv = next(a for _, a, _ in steps if isinstance(a, list) and a[0] == "scan")
        self.assertEqual(Path(argv[argv.index("--since") + 1]).resolve(), d.resolve())
        self.assertEqual(Path(argv[argv.index("--out") + 1]).resolve(), d.resolve())
        for flag, v in (("--mix", "/m/mix.wav"), ("--key", "F# major"), ("--like", "/m/like.wav")):
            self.assertEqual(argv[argv.index(flag) + 1], v)
        self.assertIn("--deep", argv)
        self.assertTrue((d / "decisions.json").exists())                                   # kept: scan --since carries them by identity
        # a REAPER project cannot (scan --since reads a Live set's copy): the old answers are kept aside, not reused
        rpp = self.source("R.rpp")
        d2 = self.scan("R", rpp, [F("fade-1")], {"fade-1": {"decision": "approve"}}, mode="reaper")
        code, r, _ = self.post("/api/rescan", dict(dir=str(d2)))
        self.assertEqual((code, r["carries_decisions"]), (200, False))
        steps = self.runs[-1][2]
        argv = next(a for _, a, _ in steps if isinstance(a, list) and a[0] == "scan")
        self.assertNotIn("--since", argv)
        next(a for _, a, _ in steps if callable(a))()                                       # the first step: get ready
        self.assertFalse((d2 / "decisions.json").exists())
        self.assertEqual(json.loads((d2 / "decisions before re-scan.json").read_text(encoding="utf-8"))["fade-1"]["decision"], "approve")
        self.assertEqual(self.post("/api/rescan", dict(dir=str(self.work / "scan")))[0], 400)
        # two folders hold scans of the same set (an older app made them): Re-scan on one card goes into THAT folder
        d3 = self.scan("Song (older)", als, [F("smooth-1")])
        os.utime(d3, (time.time() + 500, time.time() + 500))
        code, r, _ = self.post("/api/rescan", dict(dir=str(d)))
        self.assertEqual(Path(r["dir"]).resolve(), d.resolve())

    def test_a_set_saved_after_the_scan_is_said_so_before_apply(self):
        als = self.source("Song.als")
        d = self.scan("Song", als, [F("smooth-1")], {"smooth-1": {"decision": "approve"}})
        self.assertFalse(self.review(d)["stale"]["newer"])
        os.utime(als, (als.stat().st_atime, als.stat().st_mtime + 120))
        self.assertTrue(self.review(d)["stale"]["newer"])
        self.assertTrue(call(self.base, "/api/state")[1]["scans"][0]["stale"])
        als.unlink()
        self.assertTrue(self.review(d)["stale"]["missing"])
        self.assertTrue(call(self.base, "/api/state")[1]["scans"][0]["source_missing"])

    # ---- 6. the handoff list
    def test_the_handoff_list_is_a_job_and_lists_what_it_made(self):
        als = self.source("Song.als")
        d = self.scan("Song", als, [F("eq-1", "audit", "eq", applies="manual")], {"eq-1": {"decision": "approve"}})
        code, r, _ = self.post("/api/handoff", dict(dir=str(d)))
        self.assertEqual(code, 200)
        kind, title, steps, sdir, watch = self.runs[-1]
        self.assertEqual((kind, steps[0][1]), ("handoff", ["handoff", str(d.resolve())]))
        self.assertIn(d.resolve() / "handoff", {Path(w).resolve() for w in watch})
        self.assertIn(self.music.resolve(), {Path(w).resolve() for w in watch})
        self.assertEqual(self.post("/api/handoff", {})[0], 400)

    # ---- 7. what an apply did
    LOG = """
## fix run 2026-11-26 10:00

approved: smooth-1, order-1

### smooth: applied (1 approved)

```
edits 1 of 1 written
```

### Also applied because they are on by default

- order-1: tracks put in working order

### Not applied

- merge-1 Gtr 2 -> Gtr 1 4 clip(s): no longer found in this set

### by hand

- eq-1 Bass 12.1.00: cut 250 Hz by hand

### FAILED (not done)

- tune-Lead: no key

history: logged as v1 (`hypnomix history "x"`)
"""

    def test_the_log_is_grouped_by_its_own_headings_whatever_they_say(self):
        run = self.S.parse_fix_log("## fix run 2026-11-25 09:00\n\napproved: old\n\n### old section\n\n- x\n" + self.LOG)
        self.assertEqual(run["when"], "2026-11-26 10:00")                                  # the last run only
        self.assertEqual([(x["title"], x["group"]) for x in run["sections"]],
                         [("smooth: applied (1 approved)", "applied"), ("Also applied because they are on by default", "default"),
                          ("Not applied", "not_applied"), ("by hand", "not_applied"), ("FAILED (not done)", "failed")])
        self.assertEqual(run["intro"], ["approved: smooth-1, order-1"])
        self.assertTrue(run["history"].startswith("history:"))
        sec = run["sections"][-1]
        self.assertTrue(all(l["bad"] for l in sec["lines"]))                                # everything under FAILED is marked
        self.assertFalse(any(l["bad"] for l in run["sections"][0]["lines"]))
        self.assertTrue(any(l["bad"] for l in self.S.parse_fix_log("## fix run x\n\n### odd\n\n- tune: FAILED to read\n")["sections"][0]["lines"]))
        # a heading nobody has written yet still shows, as text under "applied"
        run = self.S.parse_fix_log("## fix run now\n\n### something new\n\nhello\n")
        self.assertEqual((run["sections"][0]["group"], run["sections"][0]["lines"][0]["t"]), ("applied", "hello"))
        self.assertIsNone(self.S.parse_fix_log(""))

    def test_the_result_names_the_new_file_what_was_not_applied_and_where_to_listen(self):
        als = self.source("Song.als")
        new = self.source("Song (fixed).als")
        d = self.scan("Song", als, [F("smooth-1", where="12.3.50"), F("smooth-2", where="1 clip(s)"), F("order-1", "order", "track-order", where="", default="approve"),
                                    F("merge-1", "tidy", "consolidate", default="approve"), F("eq-1", applies="manual"), F("tune-Lead", "tune", applies="audio")])
        (d / "fix-log.md").write_text(self.LOG, encoding="utf-8")
        (d / "history").mkdir()
        (d / "history" / "v1-input.als").write_text("x", encoding="utf-8")
        (d / "history" / "history.json").write_text(json.dumps({"versions": [dict(
            n=1, kind="fix", at="2026-11-26 10:00:00", input=str(als), output=str(new), input_snapshot="v1-input.als", changes=3,
            failed=[], approved=[dict(id=i) for i in ("smooth-1", "smooth-2", "order-1", "merge-1", "eq-1", "tune-Lead")])]}), encoding="utf-8")
        code, r, _ = call(self.base, "/api/fix/result?dir=" + urllib.request.quote(str(d)))
        self.assertEqual(code, 200, r)
        self.assertEqual([f["name"] for f in r["files"]], ["Song (fixed).als"])
        self.assertEqual(r["files"][0]["folder"], str(self.music))
        self.assertEqual([x["id"] for x in r["applied"]], ["smooth-1", "smooth-2", "order-1"])             # not merge-1 (not applied), eq-1 (by hand), tune-Lead (failed)
        self.assertEqual([x["where"] for x in r["listen"]], ["12.3.50"])                         # a spot to listen at: only a real position, not a count like "1 clip(s)"
        self.assertTrue(r["undo"]["can_undo"])
        self.assertEqual(r["undo"]["undo_name"], "Song (back to v1 input).als")
        self.assertTrue(any(s["group"] == "failed" for s in r["run"]["sections"]))
        self.assertEqual(self.review(d)["last_run"]["when"], "2026-11-26 10:00")

    def test_a_failed_job_says_why_in_the_commands_own_words(self):
        S = self.S
        why = S.job_reason(["$ hypnomix fix X", "Song (fixed).als already exists: choose a new name (nothing is ever overwritten)",
                            "(Applying only what you approved: exit code 1)"])
        self.assertEqual(why, "Song (fixed).als already exists: choose a new name (nothing is ever overwritten)")
        why = S.job_reason(["$ hypnomix fix X", "lots of output", "", "FAILED (not done):", "- order-1: could not re-check", "- tune: no key", "", "log: x",
                            "(Applying only what you approved: exit code 1)"])
        self.assertEqual(why, "order-1: could not re-check; tune: no key")
        self.assertEqual(S.job_reason(["$ hypnomix x"]), "")

    def test_a_run_that_wrote_nothing_is_not_called_applied(self):
        als = self.source("Song.als")
        d = self.scan("Song", als, [F("smooth-1")], {"smooth-1": {"decision": "approve"}})
        (d / "fix-log.md").write_text("\n## fix run now\n\napproved: smooth-1\n\n### skipped (not applied)\n\n- smooth-1: gone\n", encoding="utf-8")
        S = self.S
        S.JOB.update(id=7, status="done", kind="fix", dir=str(d.resolve()), files=[], stopped=False, reason="",
                     log=["$ hypnomix fix", "no set changes could be applied; see fix-log.md"])
        r = call(self.base, "/api/fix/result?dir=" + urllib.request.quote(str(d)))[1]
        self.assertTrue(r["wrote_nothing"])
        self.assertIn("no set changes", r["note"])
        S.JOB.update(status="failed", reason="Song (fixed).als already exists: choose a new name", log=["x"] * 3)
        r = call(self.base, "/api/fix/result?dir=" + urllib.request.quote(str(d)))[1]
        self.assertEqual((r["status"], r["reason"]), ("failed", "Song (fixed).als already exists: choose a new name"))

    # ---- 8. history and undo
    def test_history_lists_versions_and_only_offers_undo_where_a_snapshot_exists(self):
        als = self.source("Song.als")
        d = self.scan("Song", als, [F("smooth-1")])
        (d / "history").mkdir()
        (d / "history" / "v1-input.als").write_text("x", encoding="utf-8")
        (d / "history" / "history.json").write_text(json.dumps({"versions": [
            dict(n=1, kind="fix", at="t1", input=str(als), output=str(self.music / "Song (fixed).als"), input_snapshot="v1-input.als", approved=[dict(id="smooth-1")], failed=[]),
            dict(n=2, kind="fix", at="t2", input=str(als), output=None, approved=[dict(id="x")], failed=["x: stopped"])]}), encoding="utf-8")
        code, r, _ = call(self.base, "/api/history?dir=" + urllib.request.quote(str(d)))
        self.assertEqual(code, 200)
        self.assertEqual([(e["n"], e["can_undo"]) for e in r["entries"]], [(2, False), (1, True)])
        self.assertIn("no new set", r["entries"][0]["why_not"])
        self.assertEqual(r["entries"][1]["undo_name"], "Song (back to v1 input).als")
        code, j, _ = self.post("/api/undo", dict(dir=str(d), n=1))
        self.assertEqual((code, j["writes"]), (200, "Song (back to v1 input).als"))
        steps = self.runs[-1][2]
        self.assertEqual(steps[0][1], ["history", str(d.resolve()), "--undo", "1"])
        self.assertEqual(self.post("/api/undo", dict(dir=str(d), n=2))[0], 409)           # nothing to go back to
        self.assertEqual(self.post("/api/undo", dict(dir=str(d), n=9))[0], 400)
        self.assertEqual(self.post("/api/undo", dict(dir=str(d), n="x"))[0], 400)
        self.assertEqual(self.post("/api/undo", dict(dir=str(d)))[0], 400)
        # REAPER, Ardour and folders keep no snapshot: the page says so in words instead of offering a button
        for name, mode in (("R.rpp", "reaper"), ("S.ardour", "ardour")):
            src = self.source(name)
            d2 = self.scan(name.split(".")[0], src, [F("fade-1")], mode=mode)
            (d2 / "history").mkdir()
            (d2 / "history" / "history.json").write_text(json.dumps({"versions": [dict(n=1, kind="fix", at="t", input=str(src), output=str(self.music / "o"), approved=[dict(id="fade-1")])]}), encoding="utf-8")
            e = call(self.base, "/api/history?dir=" + urllib.request.quote(str(d2)))[1]["entries"][0]
            self.assertFalse(e["can_undo"])
            self.assertIn("no snapshot", e["why_not"])
            self.assertIn("never changed", e["why_not"])
            code, j, _ = self.post("/api/undo", dict(dir=str(d2), n=1))
            self.assertEqual(code, 409)
        self.assertEqual(call(self.base, "/api/history?dir=" + urllib.request.quote(str(d)))[1]["note"], "")

    # ---- 9. damaged files
    def test_a_damaged_decisions_file_keeps_the_song_in_the_list_and_can_be_restored(self):
        als = self.source("Song.als")
        d = self.scan("Song", als, [F("smooth-1"), F("eq-1", applies="manual")])
        (d / "decisions.json").write_text('{"smooth-1": {"decision": "appr', encoding="utf-8")
        row = call(self.base, "/api/state")[1]["scans"][0]
        self.assertEqual((row["name"], row["damaged"], row["can_restore"]), ("Song", "decisions.json", False))
        r = self.review(d)
        self.assertEqual(r["damaged"]["file"], "decisions.json")
        self.assertFalse(r["damaged"]["backup"])
        self.assertEqual(len(r["findings"]), 2)
        code, j, _ = self.post("/api/decide", dict(dir=str(d), id="smooth-1", decision="approve"))
        self.assertEqual(code, 409)
        self.assertIn("damaged", j["error"])
        self.assertEqual(self.post("/api/fix", dict(dir=str(d)))[0], 409)
        self.assertEqual(self.post("/api/restore-decisions", dict(dir=str(d)))[0], 409)          # no backup to restore
        (d / "decisions.json.bak").write_text(json.dumps({"smooth-1": {"decision": "skip"}}), encoding="utf-8")
        row = call(self.base, "/api/state")[1]["scans"][0]
        self.assertTrue(row["can_restore"])
        code, j, _ = self.post("/api/restore-decisions", dict(dir=str(d)))
        self.assertEqual((code, j["restored"], j["kept"]), (200, True, "decisions.damaged.json"))
        self.assertEqual(self.review(d)["decisions"]["smooth-1"]["decision"], "skip")
        self.assertEqual((d / "decisions.damaged.json").read_text(encoding="utf-8"), '{"smooth-1": {"decision": "appr')     # the damaged file is kept
        self.assertEqual(self.post("/api/restore-decisions", dict(dir=str(d)))[0], 400)         # no longer damaged
        # no backup: start again (the damaged file is still kept)
        (d / "decisions.json.bak").unlink()
        (d / "decisions.json").write_text("{nope", encoding="utf-8")
        code, j, _ = self.post("/api/restore-decisions", dict(dir=str(d), fresh=True))
        self.assertEqual((code, j["restored"], j["kept"]), (200, False, "decisions.damaged 2.json"))
        self.assertEqual(self.review(d)["decisions"], {})
        self.assertEqual(self.post("/api/decide", dict(dir=str(d), id="smooth-1", decision="approve"))[0], 200)

    def test_a_cut_off_decisions_file_written_by_the_real_writer_is_restored_from_its_real_backup(self):
        als = self.source("Song.als")
        d = self.scan("Song", als, [F("smooth-1"), F("smooth-2"), F("smooth-3")])
        self.assertEqual(self.post("/api/decide", dict(dir=str(d), id="smooth-1", decision="approve"))[0], 200)
        self.assertFalse((d / "decisions.json.bak").exists())                         # one write: nothing before it to keep
        self.assertEqual(self.post("/api/decide", dict(dir=str(d), id="smooth-2", decision="skip"))[0], 200)
        self.assertEqual(self.post("/api/decide", dict(dir=str(d), ids=["smooth-3"], decision="approve"))[0], 200)
        self.assertEqual(sorted(json.loads((d / "decisions.json.bak").read_text(encoding="utf-8"))), ["smooth-1", "smooth-2"])   # the writer's own name
        full = (d / "decisions.json").read_text(encoding="utf-8")
        (d / "decisions.json").write_text(full[:len(full) // 2], encoding="utf-8")                      # a crash in the middle of a write
        row = call(self.base, "/api/state")[1]["scans"][0]
        self.assertEqual((row["name"], row["damaged"], row["can_restore"]), ("Song", "decisions.json", True))   # still listed, Restore offered
        r = self.review(d)
        self.assertEqual((r["damaged"]["file"], r["damaged"]["backup"], len(r["findings"])), ("decisions.json", True, 3))
        self.assertEqual(self.post("/api/decide", dict(dir=str(d), id="smooth-1", decision="skip"))[0], 409)
        code, j, _ = self.post("/api/restore-decisions", dict(dir=str(d)))
        self.assertEqual((code, j["restored"], j["decisions"]), (200, True, 2))
        r = self.review(d)
        self.assertIsNone(r["damaged"])
        self.assertEqual({k: v["decision"] for k, v in r["decisions"].items()}, {"smooth-1": "approve", "smooth-2": "skip"})
        self.assertEqual(self.post("/api/decide", dict(dir=str(d), id="smooth-3", decision="approve"))[0], 200)

    def test_a_cut_off_scan_json_is_read_from_its_backup_and_a_cut_off_one_with_none_gives_nothing(self):
        from hypnomix.core import atomic
        d = self.work / "scan" / "Song"
        d.mkdir(parents=True)
        atomic.write_json(d / "scan.json", dict(mode="folder", group_seconds=dict(mix=7)))
        atomic.write_json(d / "scan.json", dict(mode="folder", group_seconds=dict(mix=8)))       # the first one is now scan.json.bak
        (d / "scan.json").write_text('{"mode": "fol', encoding="utf-8")
        self.assertEqual(self.S.read_scan_json(d), dict(mode="folder", group_seconds=dict(mix=7)))
        self.assertEqual(self.S.prior_times(d)["groups"], dict(mix=7.0))
        (d / "scan.json.bak").unlink()
        self.assertEqual(self.S.read_scan_json(d), {})
        self.assertEqual(self.S.read_scan_json(d / "nowhere"), {})

    def test_a_damaged_findings_file_is_listed_not_dropped(self):
        als = self.source("Song.als")
        d = self.scan("Song", als, [F("smooth-1")])
        (d / "findings.json").write_text('{"findings": [ {"id"', encoding="utf-8")
        row = call(self.base, "/api/state")[1]["scans"][0]
        self.assertEqual((row["name"], row["damaged"], row["can_rescan"]), ("Song", "findings.json", True))
        r = self.review(d)
        self.assertEqual((r["damaged"]["file"], r["findings"]), ("findings.json", []))
        code, j, _ = self.post("/api/rescan", dict(dir=str(d)))                                  # a re-scan does not lean on the damaged file
        self.assertEqual(code, 200, j)
        argv = next(a for _, a, _ in self.runs[-1][2] if isinstance(a, list) and a[0] == "scan")
        self.assertNotIn("--since", argv)
        # a scan that never finished is listed too
        d2 = self.work / "scan" / "Half"
        d2.mkdir()
        (d2 / "scan.json").write_text(json.dumps(dict(set=str(als), mode="set")), encoding="utf-8")
        rows = {r["name"]: r for r in call(self.base, "/api/state")[1]["scans"]}
        self.assertTrue(rows["Half"]["incomplete"])

    # ---- 10. plain errors
    def test_missing_fields_are_answered_in_a_sentence(self):
        als = self.source("Song.als")
        d = self.scan("Song", als, [F("smooth-1")])
        bad = [("GET", "/audio", None), ("GET", "/audio?dir=" + urllib.request.quote(str(d)), None), ("GET", "/api/review", None),
               ("GET", "/api/job?since=abc", None), ("GET", "/api/live/poll?since=x", None),
               ("POST", "/api/decide", {}), ("POST", "/api/decide", dict(dir=str(d))), ("POST", "/api/decide", dict(dir=str(d), id="smooth-1")),
               ("POST", "/api/decide", dict(dir=str(d), id="smooth-1", decision="approve", amount="lots")),
               ("POST", "/api/decide", dict(dir=str(d), id="smooth-1", decision="maybe")), ("POST", "/api/decide-like", {}),
               ("POST", "/api/note", {}), ("POST", "/api/note", dict(dir=str(d), id="smooth-1")), ("POST", "/api/scan", {}),
               ("POST", "/api/reveal", {}), ("POST", "/api/fix", {}), ("POST", "/api/ab/build", {}), ("POST", "/api/probe/report", {}),
               ("POST", "/api/live/jump", {}), ("POST", "/api/ab/state", {}), ("POST", "/api/probe/card", {}),
               ("POST", "/api/tool", dict(cmd="scan", args="'never closed")),
               # a field of the wrong kind (a list where text belongs) is a sentence too, never a dropped connection
               ("POST", "/api/tool", dict(cmd=["scan"])), ("POST", "/api/decide-low", dict(dir=str(d), ids=[["a"]], dry_run=False)),
               ("POST", "/api/decide-low", dict(dir=str(d), ids="smooth-1", dry_run=False)), ("POST", "/api/decide-low", dict(dir=[1])),
               ("POST", "/api/master/record", dict(params=[["x"]], path=["p"])), ("POST", "/api/master/record", dict(state=["start"], path=["x"])),
               ("POST", "/api/decide", dict(dir=str(d), id=["smooth-1"], decision="approve"))]
        for method, path, body in bad:
            code, r = (call(self.base, path)[:2] if method == "GET" else self.post(path, body)[:2])
            self.assertEqual(code, 400, (path, body, r))
            self.assertTrue(r["error"], (path, body))
            self.assertNotRegex(r["error"], r"^'\w+'$", (path, body))                          # not the Python word for the missing key
            self.assertNotIn("KeyError", r["error"])
            self.assertNotIn("invalid literal", r["error"])

    def test_a_number_that_is_out_of_range_never_says_none(self):
        code, r, _ = call(self.base, "/api/job?since=-5")
        self.assertEqual(code, 400)
        self.assertNotIn("None", r["error"])
        self.assertIn("0 or more", r["error"])
        self.assertEqual(self.S.whole(5, "n", 1, 3 - 3 + 9), 5)
        with self.assertRaises(ValueError) as e:
            self.S.whole(50, "n", 1, 9)
        self.assertIn("between 1 and 9", str(e.exception))

    def test_stopping_the_probe_before_it_started_is_answered_plainly(self):
        S = self.S
        hub, S.PROBE["hub"] = S.PROBE["hub"], None
        try:
            code, r, _ = call(self.base, "/api/probe/stop", {}, S.TOKEN)         # the page's own call sends its token
        finally:
            S.PROBE["hub"] = hub
        self.assertEqual(code, 409)
        self.assertIn("not running", r["error"])
        S.PROBE["hub"] = type("Hub", (), {"capture": None})()
        try:
            code, r, _ = call(self.base, "/api/probe/stop", {}, S.TOKEN)         # the page's own call sends its token
        finally:
            S.PROBE["hub"] = hub
        self.assertEqual(code, 409)
        self.assertIn("Record first", r["error"])

    def test_align_run_is_checked_before_it_starts_anything(self):
        for body in (dict(guide="Lead", parts=[1]), dict(guide="Lead", parts="x"), dict(parts=["a"]), dict(guide="Lead", parts=[["a"]], set="/x.als")):
            code, r, _ = call(self.base, "/api/align/run", body)
            self.assertEqual(code, 400, body)
            self.assertIn("parts", r["error"])

    # ---- the port the app runs on is the port its devices and jobs use
    def _main_with(self, argv, env):
        from hypnomix.app import update as UP, diskcare as DC, reporting as RP

        class FakeServer:
            def __init__(self, *a, **k): pass
            def serve_forever(self): raise KeyboardInterrupt
        saved = {k: os.environ.get(k) for k in ("HYPNOMIX_PORT", "HYPNOMIX_APP_HOME")}
        os.environ.pop("HYPNOMIX_PORT", None)
        os.environ.update({k: v for k, v in env.items() if v is not None})
        try:
            with mock.patch.object(self.S, "LocalServer", FakeServer), mock.patch.object(self.S, "start_probe_hub"), \
                    mock.patch.object(UP, "check_in_background"), mock.patch.object(DC, "start_in_background"), \
                    mock.patch.object(RP, "install_hooks"), \
                    mock.patch.object(sys, "argv", ["hypnomix-app"] + argv), mock.patch("builtins.print"):
                self.S.main()
            return os.environ.get("HYPNOMIX_PORT")
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_app_port_n_is_exported_so_devices_and_jobs_use_it(self):
        self.assertEqual(self._main_with(["--port", "8931", "--no-open"], {}), "8931")
        from hypnomix.app import probe
        with mock.patch.dict(os.environ, {"HYPNOMIX_PORT": "8931"}):
            self.assertEqual(probe.app_port(), 8931)
            from hypnomix.app import device
            self.assertEqual(device.app_port(), 8931)
        os.environ["HYPNOMIX_PORT"] = "1234"                                        # a stale value from outside never wins
        try:
            self.assertEqual(self._main_with(["--port", "8940", "--no-open"], {"HYPNOMIX_PORT": "1234"}), "8940")
            self.assertIsNone(self._main_with(["--no-open"], {"HYPNOMIX_PORT": "1234"}))      # the default port: nothing set
        finally:
            os.environ.pop("HYPNOMIX_PORT", None)

    def test_the_probe_hubs_busy_port_message_names_the_port_in_use(self):
        from hypnomix.app import probe
        saved = dict(self.S.PROBE)
        try:
            with mock.patch.dict(os.environ, {"HYPNOMIX_PROBE_PORT": "9123"}), \
                    mock.patch.object(probe, "Hub", side_effect=OSError("Address already in use")):
                self.S.start_probe_hub()
            self.assertIn("UDP port 9123 is in use", self.S.PROBE["error"])
            self.assertNotIn("8792", self.S.PROBE["error"])
            self.assertIn("HYPNOMIX_PROBE_PORT", self.S.PROBE["error"])
        finally:
            self.S.PROBE.clear()
            self.S.PROBE.update(saved)

    # ---- 12. the demo song
    def test_the_demo_button_only_exists_where_the_command_does(self):
        from hypnomix import cli
        self.assertEqual(call(self.base, "/api/state")[1]["demo"], "demo" in cli.COMMANDS)
        had = cli.COMMANDS.pop("demo", None)
        try:
            self.assertFalse(call(self.base, "/api/state")[1]["demo"])
            code, r, _ = self.post("/api/demo", {})
            self.assertEqual(code, 400)
            self.assertIn("no demo", r["error"])
            cli.COMMANDS["demo"] = ("x", "demo", "a demo song")
            self.assertTrue(call(self.base, "/api/state")[1]["demo"])
            self.assertEqual(self.post("/api/demo", {})[0], 200)
            kind, title, steps, sdir, watch = self.runs[-1]
            argv = steps[0][1]
            self.assertEqual((kind, argv[0], argv[1]), ("scan", "demo", "--out"))
            self.assertEqual(Path(argv[2]).parent, self.work)                                  # into the app's own folder
            # once the demo has run, the second step finds the song it wrote and starts the scan on it
            out = Path(argv[2])
            out.mkdir(parents=True)
            (out / "Demo.als").write_text("x", encoding="utf-8")
            self.S.JOB["log"] = ["$ hypnomix demo", f"wrote {out / 'Demo.als'}"]
            more = steps[1][1]()
            self.assertEqual(more[0][0], "Getting ready")
            self.assertEqual([a[0] for _, a, _ in more if isinstance(a, list)], ["scan", "ab"])
            self.assertEqual(self.S.JOB["dir"], str(self.work / "scan" / "Demo"))
            # what `hypnomix demo` really prints: a folder of stems (the default kind), named on its "written to" line
            folder = out / "Hypnomix Demo Song"
            folder.mkdir()
            (out / "Demo.als").unlink()
            self.S.JOB["log"] = ["$ hypnomix demo", f"demo song (folder) written to {folder}", f"problems, with times: {folder / 'DEMO.md'}"]
            more = steps[1][1]()
            self.assertEqual(Path(next(a for _, a, _ in more if isinstance(a, list) and a[0] == "scan")[1]), folder.resolve())
            self.assertEqual(self.S.JOB["dir"], str(self.work / "scan" / "Hypnomix Demo Song"))
        finally:
            cli.COMMANDS.pop("demo", None)
            if had:
                cli.COMMANDS["demo"] = had
        self.assertIn("Try it on a demo song", __import__("hypnomix.app.ui", fromlist=["PAGE"]).PAGE)

    # ---- 11. stop ends everything a job started
    @unittest.skipIf(os.name == "nt", "process groups are POSIX; Windows uses taskkill /T")
    def test_stop_ends_the_whole_process_group_and_removes_temporary_sets(self):
        S = self.S
        S.run_job = self._run_job
        als = self.source("Song.als")
        d = self.scan("Song", als, [F("smooth-1")])
        pidfile = self.root / "child.pid"
        step_file = self.music / "Song (fix step 1).als"
        keep = self.source("Song (fixed).als")                                                # a real result next to it is never touched

        def fake(argv):
            step_file.write_text("temp", encoding="utf-8")
            return subprocess.Popen(["sh", "-c", f"sleep 120 & echo $! > '{pidfile}'; wait"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, start_new_session=True, encoding="utf-8")
        real = S.popen_job
        S.popen_job = fake
        try:
            S.run_job("fix", "Applying", [("Applying", ["fix", str(d)], True)], d)
            for _ in range(100):
                if pidfile.exists() and pidfile.read_text(encoding="utf-8").strip():
                    break
                time.sleep(0.05)
            child = int(pidfile.read_text(encoding="utf-8"))
            os.kill(child, 0)                                                                    # the grandchild is running
            self.assertEqual(call(self.base, "/api/stop", {}, S.TOKEN)[1], {"stopped": True})
            for _ in range(100):
                if S.JOB["status"] != "running":
                    break
                time.sleep(0.05)
            self.assertEqual((S.JOB["status"], S.JOB["stopped"], S.JOB["reason"]), ("failed", True, "Stopped by you."))
            for _ in range(60):                                                                  # the grandchild went with it
                try:
                    os.kill(child, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail("the process the job's command started is still running")
            self.assertFalse(step_file.exists())
            self.assertTrue(keep.exists())
            self.assertTrue(any("removed the temporary set" in l for l in S.JOB["log"]))
            self.assertEqual(call(self.base, "/api/stop", {}, S.TOKEN)[1], {"stopped": False})     # nothing running: said, not crashed
        finally:
            S.popen_job = real

    def test_jobs_start_in_their_own_group(self):
        import inspect
        src = inspect.getsource(self.S.popen_job)
        self.assertIn("start_new_session", src)
        self.assertIn("CREATE_NEW_PROCESS_GROUP", src)
        self.assertIn("taskkill", inspect.getsource(self.S.kill_tree))
        self.assertIn("PYTHONPATH", inspect.getsource(self.S.cli_env))

    def test_jobs_import_this_hypnomix(self):
        # a job runs in work(): a relative PYTHONPATH (PYTHONPATH=. in a checkout) must not send it to another hypnomix
        import hypnomix
        root = str(Path(hypnomix.__file__).resolve().parents[1])
        old = os.environ.get("PYTHONPATH")
        try:
            os.environ["PYTHONPATH"] = os.pathsep.join([".", "/some/where"])
            parts = self.S.cli_env()["PYTHONPATH"].split(os.pathsep)
        finally:
            if old is None:
                os.environ.pop("PYTHONPATH", None)
            else:
                os.environ["PYTHONPATH"] = old
        self.assertEqual(parts[0], root)
        self.assertIn(str(Path("/some/where").resolve()), parts)
        self.assertTrue(all(os.path.isabs(x) for x in parts))


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
            js = (out / "hypnomix_device.js").read_text(encoding="utf-8")
            self.assertIn("127.0.0.1:8791", js)
            self.assertNotIn("__", js.replace("__PORT__", ""))                            # every placeholder filled
            for fn in ("function paint()", "function onclick(", "function bang()", "function jump("):
                self.assertIn(fn, js)


class ReviewB(unittest.TestCase):
    """The review made fast and safe: one write for a batch, what was played, a bulk approve that shows its list and leaves taste
    calls alone, caches for what the page asks every second, and the progress of a running job."""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.root = Path(cls.td.name)
        cls.work = cls.root / "work"
        os.environ["HYPNOMIX_APP_HOME"] = str(cls.work)
        from hypnomix.app import server as S
        cls.S = S
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(0))
        port = cls.srv.server_address[1]
        cls.srv.RequestHandlerClass = S.make_handler(port)
        cls.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.td.cleanup()
        os.environ.pop("HYPNOMIX_APP_HOME", None)

    def setUp(self):
        shutil.rmtree(self.work, ignore_errors=True)
        self.S.JOB.update(status="idle", log=[], files=[], reason="", stopped=False, dir="", kind="", step="")
        self.S.LIVE.update(dir="", cursor=-1)
        self.S._SCAN_CACHE.clear()

    def post(self, path, body):
        return call(self.base, path, body, self.S.TOKEN)

    def scan(self, name, findings, dec=None, ab=None, source="/nowhere/Song.als"):
        d = self.work / "scan" / name
        (d / "ab").mkdir(parents=True)
        (d / "findings.json").write_text(json.dumps(dict(set=source, notes=[], findings=findings)), encoding="utf-8")
        (d / "scan.json").write_text(json.dumps(dict(set=source, mode="set")), encoding="utf-8")
        if dec is not None:
            (d / "decisions.json").write_text(json.dumps(dec), encoding="utf-8")
        if ab is not None:
            (d / "ab" / "ab.json").write_text(json.dumps(ab), encoding="utf-8")
        return d

    def saved(self, d):
        return json.loads((d / "decisions.json").read_text(encoding="utf-8"))

    def tiny_set(self, path, tempo):
        import gzip
        with gzip.open(path, "wb") as f:
            f.write(f'<Ableton><LiveSet><MainTrack><DeviceChain><Mixer><Tempo><Manual Value="{tempo}"/></Tempo></Mixer></DeviceChain></MainTrack></LiveSet></Ableton>'.encode())
        return path

    # ---- 2. a batch is one request and one write
    def test_a_batch_of_decisions_is_one_request_and_one_write(self):
        d = self.scan("Song", [F(f"smooth-{i}") for i in range(30)])
        ids = [f"smooth-{i}" for i in range(30)]
        writes = []
        from hypnomix.core import atomic
        real = atomic.write_json
        atomic.write_json = lambda p, o, **kw: (writes.append(Path(p).name), real(p, o, **kw))[1]
        try:
            code, r, _ = self.post("/api/decide", dict(dir=str(d), ids=ids, decision="approve", note="batch: like smooth-1", via="batch"))
        finally:
            atomic.write_json = real
        self.assertEqual(code, 200)
        self.assertEqual(sorted(r["ids"]), sorted(ids))
        self.assertEqual(writes, ["decisions.json"])                                  # not 30 writes
        dec = self.saved(d)
        self.assertEqual({k: v["decision"] for k, v in dec.items()}, {i: "approve" for i in ids})
        self.assertEqual(dec["smooth-3"]["via"], "batch")
        self.assertEqual(r["entries"]["smooth-3"]["note"], "batch: like smooth-1")

    def test_one_unknown_id_stops_the_whole_batch_with_nothing_recorded(self):
        d = self.scan("Song", [F("smooth-1"), F("smooth-2")])
        code, r, _ = self.post("/api/decide", dict(dir=str(d), ids=["smooth-1", "nope-9"], decision="approve"))
        self.assertEqual(code, 400)
        self.assertIn("nope-9", r["error"])
        self.assertFalse((d / "decisions.json").exists())
        self.assertEqual(self.post("/api/decide", dict(dir=str(d), ids="smooth-1", decision="approve"))[0], 400)
        self.assertEqual(self.post("/api/decide", dict(dir=str(d), ids=["smooth-1"], decision="maybe"))[0], 400)
        self.assertEqual(self.post("/api/decide", dict(dir=str(d), ids=["smooth-1"], decision="approve", amount=101))[0], 400)

    def test_a_batch_keeps_an_unsettled_conflict_and_a_damaged_file_refuses_it(self):
        d = self.scan("Song", [F("smooth-1"), F("smooth-2")], dec={"smooth-1": dict(decision="skip", conflicts=[dict(by="ann", decision="approve")])})
        self.assertEqual(self.post("/api/decide", dict(dir=str(d), ids=["smooth-1", "smooth-2"], decision="approve"))[0], 200)
        self.assertEqual(self.saved(d)["smooth-1"]["conflicts"][0]["by"], "ann")
        (d / "decisions.json").write_text("{broken", encoding="utf-8")
        code, r, _ = self.post("/api/decide", dict(dir=str(d), ids=["smooth-1"], decision="approve"))
        self.assertEqual(code, 409)
        self.assertEqual((d / "decisions.json").read_text(encoding="utf-8"), "{broken")                # nothing was written over it

    def test_the_single_decision_still_works_and_says_what_it_recorded(self):
        d = self.scan("Song", [F("smooth-1")])
        code, r, _ = self.post("/api/decide", dict(dir=str(d), id="smooth-1", decision="change", note="softer", amount=40))
        self.assertEqual(code, 200)
        self.assertEqual((r["entry"]["decision"], r["entry"]["note"], r["entry"]["amount"]), ("change", "softer", 40))

    # ---- 3. what was played
    def test_playing_a_clip_is_remembered_with_the_decision_and_never_blocks_one(self):
        ab = {"smooth-1": dict(a="a.wav", b="b.wav"), "order-1": dict(a="a.wav", b="b.wav")}
        d = self.scan("Song", [F("smooth-1"), F("order-1", "order", "track-order", default="approve")], ab=ab)
        self.assertEqual(self.post("/api/heard", dict(dir=str(d), id="smooth-1", which="a"))[1]["heard"], ["a"])
        self.assertEqual(self.post("/api/heard", dict(dir=str(d), id="smooth-1", which="b"))[1]["heard"], ["a", "b"])
        self.assertEqual(self.post("/api/heard", dict(dir=str(d), id="smooth-1", which="b"))[1]["heard"], ["a", "b"])       # idempotent
        self.assertFalse((d / "decisions.json").exists())                             # an entry with no decision would turn off a default
        self.assertEqual(self.post("/api/heard", dict(dir=str(d), id="order-1", which="a"))[0], 200)
        self.assertFalse((d / "decisions.json").exists())
        _, r, _ = call(self.base, "/api/review?dir=" + urllib.request.quote(str(d)))
        self.assertEqual(r["heard"], {"smooth-1": ["a", "b"], "order-1": ["a"]})
        self.assertEqual(self.post("/api/decide", dict(dir=str(d), id="smooth-1", decision="approve"))[1]["entry"]["heard"], ["a", "b"])
        self.assertEqual(self.saved(d)["smooth-1"]["heard"], ["a", "b"])               # in the same file, with the decision
        self.post("/api/heard", dict(dir=str(d), id="smooth-1", which="a"))
        self.assertEqual(self.post("/api/decide", dict(dir=str(d), ids=["smooth-1"], decision="skip"))[1]["entries"]["smooth-1"]["heard"], ["a", "b"])

    def test_a_play_can_be_added_after_the_decision_and_bad_ones_are_refused(self):
        d = self.scan("Song", [F("smooth-1")], dec={"smooth-1": dict(decision="approve", note="")})
        self.post("/api/heard", dict(dir=str(d), id="smooth-1", which="b"))
        self.assertEqual(self.saved(d)["smooth-1"]["heard"], ["b"])
        self.assertEqual(self.saved(d)["smooth-1"]["decision"], "approve")
        self.assertEqual(self.post("/api/heard", dict(dir=str(d), id="smooth-1", which="c"))[0], 400)
        self.assertEqual(self.post("/api/heard", dict(dir=str(d), id="nope", which="a"))[0], 400)
        self.assertEqual(call(self.base, "/api/heard", dict(dir=str(d), id="smooth-1", which="a"))[0], 403)       # needs the page's token

    def test_the_device_decision_keeps_what_was_heard(self):
        d = self.scan("Song", [F("smooth-1")], ab={"smooth-1": dict(a="a.wav", b="b.wav")})
        self.post("/api/heard", dict(dir=str(d), id="smooth-1", which="a"))
        call(self.base, "/api/review?dir=" + urllib.request.quote(str(d)))
        call(self.base, "/api/live/step", dict(delta=1))
        call(self.base, "/api/live/decide", dict(decision="approve"))
        self.assertEqual(self.saved(d)["smooth-1"]["heard"], ["a"])

    # ---- 4. "Approve all low" is not allowed to take a taste call
    def low_scan(self):
        fs = [F("smooth-1"), F("smooth-2", where="2.1.00"),
              F("tune-1", "tune", "pitch", applies="audio"), F("voices-1", "voices", "balance", applies="audio"),
              F("motion-1", "motion", "move"), F("colour-1", "colour", "tone"), F("borrow-1", "borrow", "move"), F("variations-1", "variations", "v"),
              F("taste-1", "devices", "x", taste=True),
              F("order-1", "order", "track-order", default="approve"), F("order-2", "order", "vocal-stack"),
              F("retire-1", "tidy", "retire-off", default="approve"), F("merge-1", "tidy", "consolidate"),
              F("smooth-3", track="Lead", protected=True), F("eq-1", "audit", "eq", applies="manual"), F("q-1", "key", "q", applies="answer"),
              F("mix-1", "measure", "loudness", "info", applies="info"), F("smooth-4", severity="medium"), F("smooth-5", severity="high"),
              F("smooth-6")]
        ab = {"smooth-1": dict(a="a.wav", b="b.wav"), "tune-1": dict(a="a.wav", b="b.wav")}
        d = self.scan("Song", fs, dec={"smooth-6": dict(decision="skip")}, ab=ab)
        self.post("/api/heard", dict(dir=str(d), id="smooth-1", which="a"))
        return d

    def test_approve_all_low_lists_what_it_would_approve_and_leaves_taste_and_tidy_steps_out(self):
        d = self.low_scan()
        code, r, _ = self.post("/api/decide-low", dict(dir=str(d), dry_run=True))
        self.assertEqual(code, 200)
        self.assertEqual(sorted(x["id"] for x in r["items"]), ["smooth-1", "smooth-2"])
        self.assertEqual((r["n"], r["with_preview"], r["heard"]), (2, 1, 1))
        row = next(x for x in r["items"] if x["id"] == "smooth-1")
        self.assertEqual((row["track"], row["where"], row["fix"], row["preview"], row["heard"]), ("Vox", "1.1.00", "a fix", True, True))
        self.assertEqual(r["left_out"], dict(taste=7, tidy=4, protected=1, by_hand=1))
        self.assertEqual(self.saved(d), {"smooth-6": dict(decision="skip")})          # listing records nothing

    def test_approve_all_low_records_only_what_it_listed_and_refuses_anything_else(self):
        d = self.low_scan()
        code, r, _ = self.post("/api/decide-low", dict(dir=str(d), ids=["smooth-1", "smooth-2", "tune-1", "order-1", "smooth-3", "smooth-4", "smooth-6"]))
        self.assertEqual(code, 200)
        self.assertEqual(sorted(r["ids"]), ["smooth-1", "smooth-2"])
        self.assertEqual(sorted(r["refused"]), ["order-1", "smooth-3", "smooth-4", "smooth-6", "tune-1"])
        dec = self.saved(d)
        self.assertEqual({k: v["decision"] for k, v in dec.items()}, {"smooth-1": "approve", "smooth-2": "approve", "smooth-6": "skip"})
        self.assertEqual(dec["smooth-1"]["via"], "bulk-low")
        self.assertEqual(dec["smooth-1"]["heard"], ["a"])
        r = self.post("/api/decide-low", dict(dir=str(d), dry_run=True))[1]               # what is left to approve in bulk: nothing
        self.assertEqual((r["n"], r["items"]), (0, []))

    def test_approve_all_low_is_asked_for_by_id_so_a_bare_call_only_lists(self):
        d = self.low_scan()
        self.assertEqual(self.post("/api/decide-low", dict(dir=str(d)))[1]["n"], 2)
        self.assertEqual(self.saved(d), {"smooth-6": dict(decision="skip")})

    def test_an_ardour_session_does_not_count_unwritable_edits_as_approvable(self):
        d = self.work / "scan" / "Mix"
        (d / "ab").mkdir(parents=True)
        (d / "findings.json").write_text(json.dumps(dict(set="/nowhere/Mix.ardour", notes=[], findings=[
            F("smooth-1", edit=dict(op="fade")), F("timing-1", "timing", "late", edit=dict(op="nudge"))])), encoding="utf-8")
        (d / "scan.json").write_text(json.dumps(dict(set="/nowhere/Mix.ardour", mode="ardour")), encoding="utf-8")
        r = self.post("/api/decide-low", dict(dir=str(d), dry_run=True))[1]
        self.assertEqual([x["id"] for x in r["items"]], ["smooth-1"])
        self.assertEqual(r["left_out"]["by_hand"], 1)

    def test_approve_the_n_like_this_lists_first_and_then_uses_the_examples_amount(self):
        fs = [F(f"smooth-{i}", size=2.0) for i in range(1, 5)] + [F("smooth-9", size=40.0)]
        d = self.scan("Song", fs, dec={"smooth-4": dict(decision="skip")}, ab={"smooth-2": dict(a="a.wav", b="b.wav")})
        self.post("/api/heard", dict(dir=str(d), id="smooth-2", which="b"))
        code, r, _ = self.post("/api/decide-like", dict(dir=str(d), id="smooth-1", decision="approve", dry_run=True))
        self.assertEqual(code, 200)
        self.assertEqual(sorted(x["id"] for x in r["items"]), ["smooth-1", "smooth-2", "smooth-3"])
        self.assertTrue(r["includes_example"])
        self.assertEqual((r["with_preview"], r["heard"]), (1, 1))
        self.assertEqual(self.saved(d), {"smooth-4": dict(decision="skip")})               # nothing recorded by the listing
        code, r, _ = self.post("/api/decide-like", dict(dir=str(d), id="smooth-1", decision="approve", amount=60))
        self.assertEqual(sorted(r["ids"]), ["smooth-1", "smooth-2", "smooth-3"])
        dec = self.saved(d)
        self.assertEqual([dec[i]["amount"] for i in r["ids"]], [60, 60, 60])
        self.assertEqual(dec["smooth-2"]["heard"], ["b"])
        self.assertEqual(r["entries"]["smooth-3"]["via"], "like:smooth-1")
        self.assertNotIn("smooth-9", dec)
        again = self.post("/api/decide-like", dict(dir=str(d), id="smooth-1", decision="skip", dry_run=True))[1]       # the example is decided now
        self.assertFalse(again["includes_example"])
        self.assertEqual(again["items"], [])
        self.assertEqual(self.post("/api/decide-like", dict(dir=str(d), id="nope-1", decision="skip", dry_run=True))[0], 400)

    # ---- 8. what the page asks every second is kept
    def test_the_songs_list_does_not_parse_every_scan_again_until_one_changes(self):
        ds = [self.scan(f"Song {i}", [F("smooth-1"), F("smooth-2")], source=f"/nowhere/S{i}.als") for i in range(5)]
        n = []
        real = self.S.inspect_scan
        self.S.inspect_scan = lambda d: (n.append(str(d)), real(d))[1]
        try:
            self.assertEqual(len(self.S.scans()), 5)
            first = len(n)
            for _ in range(4):
                self.S.scans()
            self.assertEqual(len(n), first)                                                    # four more asks, no more parsing
            self.assertEqual(self.post("/api/decide", dict(dir=str(ds[2]), id="smooth-1", decision="approve"))[0], 200)
            del n[:]
            rows = {r["name"]: r for r in self.S.scans()}
            self.assertEqual(n, [str(ds[2])])                                                  # only the folder that changed
            first = 0
            self.assertEqual((rows["Song 2"]["approved"], rows["Song 1"]["approved"]), (1, 0))
            shutil.rmtree(ds[0])
            self.assertEqual(len(self.S.scans()), 4)
            self.assertNotIn(str(ds[0]), self.S._SCAN_CACHE)
        finally:
            self.S.inspect_scan = real

    def test_the_songs_list_still_notices_a_song_saved_after_the_scan(self):
        src = self.root / "Song.als"
        src.write_text("x", encoding="utf-8")
        d = self.scan("Song", [F("smooth-1")], source=str(src))
        (d / "scan.json").write_text(json.dumps(dict(set=str(src), mode="set", set_mtime=src.stat().st_mtime)), encoding="utf-8")
        self.assertFalse(self.S.scans()[0]["stale"])
        os.utime(src, (time.time() + 50, time.time() + 50))
        self.assertTrue(self.S.scans()[0]["stale"])                                            # the song is looked at on every ask
        src.unlink()
        self.assertTrue(self.S.scans()[0]["source_missing"])

    def test_the_command_list_is_sent_once_not_with_every_state(self):
        _, st, _ = call(self.base, "/api/state")
        self.assertNotIn("commands", st)
        _, cm, _ = call(self.base, "/api/commands")
        self.assertEqual(cm["rev"], st["commands_rev"])
        self.assertGreater(len(cm["commands"]), 20)
        self.assertEqual(len(json.dumps(st)) < len(json.dumps(cm)), True)

    def test_a_set_is_unzipped_once_for_as_long_as_it_does_not_change(self):
        import gzip
        from hypnomix.session import automation as aa
        als = self.tiny_set(self.root / "Big.als", 120)
        n = []
        real = aa.load
        aa.load = lambda p: (n.append(p), real(p))[1]
        try:
            self.assertEqual(self.S.set_grid(str(als))[0], 120.0)
            for _ in range(5):
                self.S.set_grid(str(als))
            self.assertEqual(len(n), 1)
            self.tiny_set(als, 90)
            os.utime(als, (time.time() + 5, time.time() + 5))
            self.assertEqual(self.S.set_grid(str(als))[0], 90.0)                              # saved again: read again
            self.assertEqual(len(n), 2)
        finally:
            aa.load = real
        self.assertEqual(self.S.set_grid(str(self.root / "missing.als")), (None, 4))

    def test_the_device_poll_and_the_review_do_not_read_the_set_every_time(self):
        from hypnomix.session import automation as aa
        als = self.tiny_set(self.root / "Song.als", 120)
        d = self.scan("Song", [F("smooth-1", where="3.1.00"), F("smooth-2", where="bars 5-6")], source=str(als))
        n = []
        real = aa.load
        aa.load = lambda p: (n.append(p), real(p))[1]
        try:
            call(self.base, "/api/review?dir=" + urllib.request.quote(str(d)))
            for _ in range(5):
                call(self.base, "/api/live/poll?since=-1")
                call(self.base, "/api/review?dir=" + urllib.request.quote(str(d)))
            call(self.base, "/api/live/step", dict(delta=1))
            self.assertEqual(len(n), 1)
        finally:
            aa.load = real
        _, p, _ = call(self.base, "/api/live/poll?since=-1")
        self.assertEqual(p["current"]["id"], "smooth-1")
        self.post("/api/decide", dict(dir=str(d), id="smooth-1", decision="skip"))             # a decision is seen by the device at once
        self.assertEqual(call(self.base, "/api/live/poll?since=-1")[1]["current"]["decision"], "skip")

    def test_a_commands_help_runs_once(self):
        calls = []
        real = self.S.subprocess.run
        self.S.subprocess.run = lambda *a, **k: (calls.append(a[0]), type("R", (), dict(stdout="usage: hypnomix scan", stderr=""))())[1]
        self.S._HELP.clear()
        try:
            for _ in range(3):
                code, r, _ = call(self.base, "/api/help?cmd=scan")
                self.assertEqual((code, r["help"]), (200, "usage: hypnomix scan"))
            self.assertEqual(len(calls), 1)
            self.assertEqual(call(self.base, "/api/help?cmd=install")[0], 404)
        finally:
            self.S.subprocess.run = real
            self.S._HELP.clear()

    # ---- 6. how far a job has got
    def running(self, step, log, **kw):
        self.S.JOB.update(status="running", step=step, log=log, step_at=time.time() - kw.pop("elapsed", 10), t0=time.time() - 12, **kw)

    SCAN_LOG = ["$ hypnomix scan Song.als", "scanning Song.als: names, files, clips, timing → /x/scan/Song", "  track roles from `name`: 1 vocal, 2 other",
                "  names       3 findings  (2 s)", "  files       0 findings  (1 s)"]

    def test_a_scan_says_how_many_checks_are_done_and_which_are_still_running(self):
        self.running("Scanning (changes nothing)", self.SCAN_LOG, prior={})
        p = self.S.job_progress()
        self.assertEqual((p["kind"], p["done"], p["total"], p["pending"]), ("scan", 2, 4, ["clips", "timing"]))
        self.assertIsNone(p["eta"])                                                            # a first scan: no honest estimate
        self.assertNotIn("percent", p)

    def test_the_estimate_comes_from_the_last_scans_own_seconds_and_says_when_it_is_over(self):
        prior = dict(groups=dict(names=2, files=1, clips=30, timing=20), wall=45.0, names=["names", "files", "clips", "timing"], ab_wall=None)
        self.running("Scanning (changes nothing)", self.SCAN_LOG, prior=prior, elapsed=10)
        p = self.S.job_progress()
        self.assertEqual((p["eta"], p["last_total"], p["over"]), (35, 45, False))
        self.assertEqual(p["last"], dict(clips=30, timing=20))
        self.running("Scanning (changes nothing)", self.SCAN_LOG, prior=prior, elapsed=60)
        p = self.S.job_progress()
        self.assertEqual((p["eta"], p["over"]), (0, True))
        # a different set of groups (a re-scan that re-runs a few): from the groups' own seconds, over the 4 workers a scan uses
        prior2 = dict(groups=dict(names=2, files=1, clips=30, timing=20), wall=None, names=None, ab_wall=None)
        self.running("Scanning (changes nothing)", self.SCAN_LOG, prior=prior2, elapsed=5)
        self.assertEqual(self.S.job_progress()["last_total"], 30)                               # the longest group bounds it
        # a group that has never run has no past time: no estimate rather than a made-up one
        self.running("Scanning (changes nothing)", self.SCAN_LOG, prior=dict(groups=dict(names=2, files=1, clips=30), wall=40.0, names=None, ab_wall=None))
        self.assertIsNone(self.S.job_progress()["eta"])

    def test_the_other_steps_show_what_their_output_allows(self):
        self.running("Building before / after clips", ["rendering 3 track(s) with and without 2 nudge(s) …", "rendering 3 track(s) with and without 1 cut(s) …"],
                     prior=dict(groups={}, wall=None, ab_wall=50.0), elapsed=20)
        p = self.S.job_progress()
        self.assertEqual((p["kind"], p["done"], p["total"], p["eta"], p["last_total"]), ("ab", 2, None, 30, 50))
        self.running("Applying only what you approved", ["$ hypnomix fix X", "smooth      ok  (3 approved)", "check      structure OK", "timing      FAILED  (re-check did not run)"], expect=3)
        p = self.S.job_progress()
        self.assertEqual((p["kind"], p["done"], p["total"]), ("fix", 2, 3))
        self.running("Something else", [], elapsed=7)
        self.assertEqual(self.S.job_progress()["kind"], "other")
        self.S.JOB["status"] = "idle"
        self.assertIsNone(self.S.job_progress())

    def test_a_scans_times_are_kept_for_the_next_estimate_and_a_do_nothing_rescan_does_not_erase_them(self):
        d = self.work / "scan" / "Song"
        d.mkdir(parents=True)
        self.S.JOB.update(log=self.SCAN_LOG, walls={"Scanning (changes nothing)": 12.34, "Building before / after clips": 3.0})
        self.S.save_times(d)
        t = json.loads((d / "app-scan.json").read_text(encoding="utf-8"))["times"]
        self.assertEqual((t["groups"], t["wall"], t["names"], t["ab_wall"]), (dict(names=2, files=1), 12.3, ["names", "files", "clips", "timing"], 3.0))
        pr = self.S.prior_times(d)
        self.assertEqual((pr["groups"], pr["wall"], pr["ab_wall"]), (dict(names=2.0, files=1.0), 12.3, 3.0))
        self.S.JOB.update(log=["scanning Song.als: nothing changed → /x"], walls={"Scanning again (changes nothing)": 0.2})
        self.S.save_times(d)
        self.assertEqual(json.loads((d / "app-scan.json").read_text(encoding="utf-8"))["times"]["wall"], 12.3)
        (d / "scan.json").write_text(json.dumps(dict(group_seconds=dict(mix=9))), encoding="utf-8")               # a scan that writes its own seconds wins
        self.assertEqual(self.S.prior_times(d)["groups"], dict(mix=9.0))

    def test_the_old_per_group_files_give_a_first_estimate_for_a_scan_the_command_line_made(self):
        d = self.work / "scan" / "Song"
        d.mkdir(parents=True)
        (d / "mix.json").write_text(json.dumps(dict(group="mix", seconds=8.2, findings=[])), encoding="utf-8")
        (d / "decisions.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.S.prior_times(d)["groups"], dict(mix=8.2))

    def test_the_job_route_carries_the_progress_and_the_page_never_shows_a_percentage(self):
        self.running("Scanning (changes nothing)", self.SCAN_LOG, prior={})
        _, j, _ = call(self.base, "/api/job?since=0")
        self.assertEqual(j["progress"]["kind"], "scan")
        from hypnomix.app import ui
        self.assertNotIn("%", ui.PAGE[ui.PAGE.index("function progressHTML"):ui.PAGE.index("function jobView")])

    # ---- 1, 5, 7, 9: the page
    def test_the_review_screen_is_served_and_wired_into_the_page(self):
        code, h, body = RawGet(self.base, "/review.js")
        self.assertEqual((code, h["content-type"]), (200, "text/javascript; charset=utf-8"))
        js = body.decode()
        for want in ("'keydown'", "'j'", "'k'", "']'", "'['", "' '", "'?'", "abSwitch", "approveAllLow", "By hand in your DAW", "api/heard",
                     "never played", "hx.filter.", "hx.cur.", "decide-low", "dry_run: true"):
            self.assertIn(want, js)
        self.assertIn('src="/review.js"', RawGet(self.base, "/")[2].decode())

    def test_one_player_per_card_switches_between_a_and_b_in_place(self):
        js = (Path(self.S.__file__).with_name("review.js")).read_text(encoding="utf-8")
        self.assertEqual(js.count("<audio"), 1)                                                  # one element in a card, not two
        self.assertIn("au.currentTime", js)
        self.assertIn("au.dataset[side]", js)

    def test_a_decision_patches_a_card_and_never_redraws_the_list(self):
        js = (Path(self.S.__file__).with_name("review.js")).read_text(encoding="utf-8")
        body = js[js.index("function decideOne"):js.index("function batchDecide")]
        self.assertNotIn("innerHTML", body)
        for name in ("function patchCard", "function patchMany"):
            seg = js[js.index(name):js.index(name) + 1400]
            self.assertNotIn("#rvlist').innerHTML", seg)
            self.assertNotIn("getElementById('rvlist').innerHTML", seg)
        from hypnomix.app import ui
        self.assertNotIn("reviewView()", ui.PAGE.replace("m.innerHTML = reviewView(); rvMounted();", ""))      # only the opening draws the screen
        self.assertNotIn("for (const id of ids) await post", js + ui.PAGE)                       # no request per id

    def test_the_served_page_and_every_script_have_no_inline_event_handlers(self):
        import re
        pages = [RawGet(self.base, p) for p in ("/", "/review.js", "/chat.js", "/wiki.js", "/teacher.js", "/setup.js", "/update.js", "/diskcare.js")]
        for code, h, body in pages:
            self.assertEqual(code, 200)
            text = body.decode()
            self.assertEqual(re.findall(r"""<[a-z][^>]*\son[a-z]+\s*=""", text), [])
            self.assertNotIn("javascript:", text)
            self.assertNotIn("eval(", text)
        self.assertEqual(re.findall(r"<script(?![^>]*\ssrc=)[^>]*>", pages[0][2].decode()).__len__(), 1)       # one inline script, the nonce'd one

    def test_every_page_script_still_parses(self):
        """Every script of the app's pages (hypnomix/app and hypnomix/app/daw/js, and the inline ones): node when it is
        installed, else macOS's JavaScript engine; with neither, a visible skip that names what is missing."""
        from tests import _jscheck
        _jscheck.check(self)

    def test_the_page_is_a_list_with_headings_live_regions_and_a_message_region_instead_of_alerts(self):
        from hypnomix.app import ui
        page = ui.PAGE
        js = (Path(self.S.__file__).with_name("review.js")).read_text(encoding="utf-8")
        for want in ('id="msg" role="alert"', 'id="sr"', 'aria-live', 'role="status"', ':focus-visible', 'prefers-reduced-motion', 'class="skiplink"', 'aria-label="Main"',
                     'id="jobprog" role="status" aria-live="polite"', 'role="log"'):
            self.assertIn(want, page)
        for want in ('role="list"', 'role="listitem"', '<h2 id="sh-', '<h3 class="sevhead', '<h4 class="title"', 'aria-pressed', 'aria-label="Keyboard shortcuts"',
                     'id="rvcount" role="status" aria-live="polite"', 'aria-label="Hear A', 'aria-label="Hear B', 'role="dialog" aria-modal="true"'):
            self.assertIn(want, js)
        import re
        self.assertIsNone(re.search(r"(?:^|[}\n,])\.skip[{:,]", page, re.M))                    # the decision buttons are class "skip" too: the skip link must not share it
        self.assertNotIn("alert(", js)
        self.assertEqual([l for l in page.split("\n") if "alert(" in l and "window.alert" not in l and "showMsg" not in l], [])
        self.assertNotIn("confirm(", js)
        self.assertEqual(page.count("window.alert = "), 1)                                       # the other tabs' alert() lands in the message region too

    def test_every_text_colour_has_at_least_4_5_to_1_against_its_background_in_both_schemes(self):
        import re
        from hypnomix.app import ui
        css = ui.PAGE[:ui.PAGE.index("</style>")]
        light = dict(re.findall(r"--([\w-]+):(#[0-9a-fA-F]{3,6})", css[css.index(":root{"):css.index("@media (prefers-color-scheme:dark)")]))
        dark_block = css[css.index("@media (prefers-color-scheme:dark)"):]
        dark = dict(light, **dict(re.findall(r"--([\w-]+):(#[0-9a-fA-F]{3,6})", dark_block[:dark_block.index("}}")])))

        def lum(h):
            h = h.lstrip("#")
            h = "".join(c * 2 for c in h) if len(h) == 3 else h
            r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
            f = lambda c: c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4
            return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)

        def ratio(a, b):
            la, lb = sorted((lum(a), lum(b)), reverse=True)
            return (la + .05) / (lb + .05)
        for name, t in (("light", light), ("dark", dark)):
            for fg in ("ink", "mute", "hi", "med", "low", "info", "ok", "skip", "chg", "accent"):
                for bg in ("bg", "card"):
                    self.assertGreaterEqual(ratio(t[fg], t[bg]), 4.5, f"{name}: --{fg} on --{bg}")
            for bg in ("ok", "skip", "chg", "accent"):                                           # the text on a filled button
                self.assertGreaterEqual(ratio(t["accent-ink"], t[bg]), 4.5, f"{name}: --accent-ink on --{bg}")


def RawGet(base, path):
    import http.client
    host, port = base[len("http://"):].split(":")
    c = http.client.HTTPConnection(host, int(port), timeout=5)
    c.request("GET", path)
    r = c.getresponse()
    data = r.read()
    out = (r.status, dict((k.lower(), v) for k, v in r.getheaders()), data)
    c.close()
    return out


class Naming(unittest.TestCase):
    """The words a person reads in the app: the product is HypnoMix, the third DAW is HypnoMix DAW, and the name of the
    program under it appears in the one place the app discloses it (the add-on's card). Names that other programs look
    up (the devices, the REAPER effects) and the X-Hypnomix header are identifiers and stay as they are."""
    ROOT = Path(__file__).resolve().parent.parent / "hypnomix"
    KEEP = r"X-Hypnomix|Hypnomix (?:Main|Probe|Align|Master|Library)\b|Hypnomix\.(?:app|amxd)"

    def code_lines(self, path):
        inside = False                                    # between /* and */ (a comment that runs over several lines)
        for n, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
            was = inside
            if line.lstrip().startswith("/*") or inside:
                inside = "*/" not in line
            if not was and not line.lstrip().startswith(("//", "/*", "#")):
                yield n, line

    def test_the_screens_say_hypnomix_with_a_capital_m_and_never_ardour(self):
        import re
        files = sorted((self.ROOT / "app").glob("*.js")) + sorted((self.ROOT / "app" / "daw" / "js").glob("*.js")) + [
            self.ROOT / "app" / "daw" / "index.html", self.ROOT / "app" / "ui.py"]
        files = [f for f in files if not f.name.startswith(("teacher", "wiki"))]
        for f in files:
            for n, line in self.code_lines(f):
                self.assertNotRegex(line, r"\bArdour\b", f"{f.name}:{n}")
                bare = re.sub(self.KEEP, "", line)
                self.assertNotRegex(bare, r"\bHypnomix\b(?!\.)", f"{f.name}:{n}")

    def test_the_daw_question_and_the_prompt_use_the_three_names(self):
        from hypnomix.app import chat as CH, setup as SU
        self.assertEqual([d["title"] for d in SU.DAWS], ["Ableton Live", "REAPER", "HypnoMix DAW", "Something else"])
        self.assertNotIn("Ardour", " ".join(d["note"] for d in SU.DAWS))
        prompt = CH.system_prompt().split("Reference (written for terminal agents")[0]
        self.assertIn("HypnoMix DAW", prompt)
        self.assertNotRegex(prompt, r"\bArdour\b")


if __name__ == "__main__":
    unittest.main()
