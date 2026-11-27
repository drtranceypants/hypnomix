"""DAW mode: the engine's meter stream relayed by the app (GET /api/daw/meters, a WebSocket on the app's own origin
with the page's token), with a stand-in engine: its MCP says where the stream is, and a small WebSocket server
checks the engine token and sends frames."""
import base64, hashlib, json, os, socket, tempfile, threading, time, unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest import mock

from hypnomix.app import daw as DW
from hypnomix.app import daw_meters as DM


class FakeStream:
    """The engine's meter WebSocket: checks the path and token, sends hello + frames, echoes what it is sent."""

    def __init__(self, token="e" * 32):
        self.token = token
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.got = []
        self.requests = []
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.one, args=(c,), daemon=True).start()

    def one(self, c):
        buf = b""
        while b"\r\n\r\n" not in buf:
            d = c.recv(4096)
            if not d:
                return c.close()
            buf += d
        head = buf.split(b"\r\n\r\n")[0].decode()
        self.requests.append(head)
        line = head.split("\r\n")[0]
        hd = {k.strip().lower(): v.strip() for k, _, v in (x.partition(":") for x in head.split("\r\n")[1:])}
        if line.split(" ")[1] != f"/meters?token={self.token}" or "origin" in hd:
            c.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            return c.close()
        c.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Accept: {DM.accept_key(hd['sec-websocket-key'])}\r\n\r\n").encode())

        def text(obj):
            data = json.dumps(obj).encode()
            n = len(data)
            c.sendall(bytes([0x81]) + (bytes([n]) if n < 126 else bytes([126]) + n.to_bytes(2, "big")) + data)

        text({"type": "hello", "version": 1, "rateHz": 20})
        c.settimeout(0.05)
        seq = 0
        rest = b""
        try:
            while seq < 200:
                seq += 1
                text({"type": "meters", "seq": seq, "sample": seq * 2400, "rolling": True, "routes": [],
                      "master": {"id": "1", "momentaryLufs": -14.0}})
                try:
                    rest += c.recv(4096)
                except socket.timeout:
                    pass
                while len(rest) >= 6:                       # a masked client frame (small)
                    n = rest[1] & 0x7F
                    if len(rest) < 6 + n:
                        break
                    mask, data = rest[2:6], rest[6:6 + n]
                    self.got.append(bytes(b ^ mask[i % 4] for i, b in enumerate(data)).decode())
                    rest = rest[6 + n:]
                    text({"type": "echo", "got": self.got[-1]})
        except OSError:
            pass
        c.close()


class FakeEngine:
    def __init__(self, stream=None, running=True):
        self.stream, self.running, self.calls = stream, running, 0

    def url(self):
        return "http://127.0.0.1:9/mcp"

    def connected(self):
        return True

    def call(self, method, params=None, timeout=8.0):
        self.calls += 1
        assert method == "tools/call" and params["name"] == "meters_stream_info"
        if not self.running or not self.stream:
            return {"structuredContent": {"running": False, "url": None, "port": None, "token": None, "rateHz": 20}}
        p = self.stream.port
        return {"structuredContent": {"running": True, "url": f"ws://127.0.0.1:{p}/meters?token={self.stream.token}",
                                      "port": p, "path": "/meters", "token": self.stream.token, "rateHz": 20}}


class Keys(unittest.TestCase):
    def test_accept_key_is_rfc_6455(self):
        self.assertEqual(DM.accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_valid_key(self):
        self.assertTrue(DM.valid_key(base64.b64encode(b"x" * 16).decode()))
        self.assertFalse(DM.valid_key("short"))
        self.assertFalse(DM.valid_key(""))


class Relay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        os.environ["HYPNOMIX_APP_HOME"] = cls.td.name
        from hypnomix.app import server as S
        cls.S = S
        cls.stream = FakeStream()
        cls.eng = FakeEngine(cls.stream)
        cls.patch = mock.patch.object(DW, "ENGINE", cls.eng)
        cls.patch.start()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(0))
        cls.port = cls.srv.server_address[1]
        cls.srv.RequestHandlerClass = S.make_handler(cls.port)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        cls.srv.shutdown()
        cls.stream.sock.close()
        cls.td.cleanup()
        os.environ.pop("HYPNOMIX_APP_HOME", None)

    def setUp(self):
        DM._info.update(t=0.0, url=None, v=None)          # no cached stream address between tests
        self.eng.running = True

    def open(self, token=None, origin="self"):
        o = f"http://127.0.0.1:{self.port}" if origin == "self" else origin
        return DM.Client("127.0.0.1", self.port, f"/api/daw/meters?t={token or self.S.TOKEN}", origin=o)

    def test_frames_come_through_and_commands_go_back(self):
        c = self.open()
        self.assertEqual(c.status, 101, c.head)
        self.assertNotIn(self.stream.token, c.head)                   # the page never sees the engine's token or port
        self.assertNotIn(str(self.stream.port), c.head)
        self.assertEqual(c.recv()["type"], "hello")
        seqs = [c.recv()["seq"] for _ in range(5)]
        self.assertEqual(seqs, sorted(seqs))
        c.send({"rate": 5})
        for _ in range(40):
            m = c.recv()
            if m.get("type") == "echo":
                self.assertEqual(json.loads(m["got"]), {"rate": 5})
                break
        else:
            self.fail("the command did not reach the engine")
        c.close()
        req = self.stream.requests[-1]
        self.assertTrue(req.startswith(f"GET /meters?token={self.stream.token} "))
        self.assertNotIn("Origin", req)                                # the engine sees the app, not the page

    def test_the_page_token_is_needed(self):
        c = self.open(token="nope")
        self.assertEqual(c.status, 403)
        c.sock.close()

    def raw(self, path, extra="", host=None):
        """A WebSocket upgrade by hand -> the status line's code."""
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        key = base64.b64encode(b"k" * 16).decode()
        sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host or '127.0.0.1:%d' % self.port}\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n{extra}\r\n").encode())
        head, _ = DM._read_head(sock)
        sock.close()
        return int(head.split(" ", 2)[1])

    def test_no_token_at_all_is_refused(self):
        self.assertEqual(self.raw("/api/daw/meters", f"Origin: http://127.0.0.1:{self.port}\r\n"), 403)
        self.assertEqual(self.raw("/api/daw/meters?t=", f"Origin: http://127.0.0.1:{self.port}\r\n"), 403)
        self.assertEqual(self.raw("/api/daw/meters?t=%C3%A9", ""), 403)          # not ASCII: refused, not a crash

    def test_a_foreign_origin_is_refused_even_with_the_token(self):
        t = self.S.TOKEN
        for origin in ("http://example.com", "null", f"http://127.0.0.1:{self.port + 1}", f"http://evil.localhost:{self.port}"):
            self.assertEqual(self.raw(f"/api/daw/meters?t={t}", f"Origin: {origin}\r\n"), 403, origin)
        self.assertEqual(self.raw(f"/api/daw/meters?t={t}", "Sec-Fetch-Site: cross-site\r\nSec-Fetch-Mode: websocket\r\n"), 403)
        self.assertEqual(self.raw(f"/api/daw/meters?t={t}", "", host=f"rebound.example:{self.port}"), 403)    # DNS rebinding
        self.assertEqual(self.raw(f"/api/daw/meters?t={t}", f"Origin: http://localhost:{self.port}\r\n",
                                  host=f"localhost:{self.port}"), 101)                                     # the app's own

    def test_a_new_stream_closes_the_oldest_when_all_places_are_taken(self):
        open_ = [self.open() for _ in range(DM.MAX_RELAYS)]
        try:
            for c in open_:
                self.assertEqual(c.status, 101, c.head)
            extra = self.open()
            self.assertEqual(extra.status, 101, extra.head)            # a stream nobody reads cannot keep the page out
            oldest = open_[0]
            oldest.sock.settimeout(5)
            with self.assertRaises((EOFError, OSError)):
                while oldest.recv() is not None:                       # it drains what was sent, then the close
                    pass
                raise EOFError("closed")
            self.assertEqual(open_[1].recv()["type"], "hello")         # the others go on
            extra.close()
        finally:
            for c in open_:
                c.close()

    def test_none_left_to_give_way_is_429(self):
        taken = [DM._relays.acquire(blocking=False) for _ in range(DM.MAX_RELAYS)]
        try:
            self.assertTrue(all(taken))
            with mock.patch.object(DM._relays, "acquire", return_value=False):
                c = self.open()
            self.assertEqual(c.status, 429)
            c.sock.close()
        finally:
            for t in taken:
                if t:
                    DM._relays.release()

    def test_another_site_is_refused(self):
        c = self.open(origin="http://example.com")
        self.assertEqual(c.status, 403)
        c.sock.close()

    def test_not_a_websocket(self):
        import urllib.request, urllib.error
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/daw/meters?t={self.S.TOKEN}", timeout=5)
        self.assertEqual(e.exception.code, 400)

    def test_no_stream_says_503_and_the_view_polls(self):
        self.eng.running = False
        c = self.open()
        self.assertEqual(c.status, 503)
        c.sock.close()

    def test_a_stale_address_is_asked_again(self):
        DM._info.update(t=time.time(), url=self.eng.url(), v={"running": True, "port": 9, "token": "x"})
        c = self.open()
        self.assertEqual(c.status, 502)                                # port 9: nothing there
        c.sock.close()
        n = self.eng.calls
        c = self.open()                                                # asked the engine again: works
        self.assertEqual(c.status, 101, c.head)
        self.assertGreater(self.eng.calls, n - 1)
        c.close()


class TheRelayNeverHangs(unittest.TestCase):
    """A quiet engine, a page that stops reading and an engine that drips its answer never hold a thread for good."""

    def pairs(self):
        a, a2 = socket.socketpair()
        b, b2 = socket.socketpair()
        self.addCleanup(lambda: [x.close() for x in (a, a2, b, b2)])
        return a, a2, b, b2

    def test_a_quiet_stream_is_closed(self):
        a, a2, b, b2 = self.pairs()
        with mock.patch("socket.socket.setsockopt"):                   # a socketpair is not TCP
            t0 = time.monotonic()
            DM.pump(a, b, idle=0.3)
        self.assertLess(time.monotonic() - t0, 3)

    def test_a_reader_that_stops_is_let_go(self):
        a, a2, b, b2 = self.pairs()
        a.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        stop = threading.Event()

        def engine():                                                  # streams on; the page (a2) never reads
            try:
                while not stop.is_set():
                    b2.sendall(b"x" * 65536)
            except OSError:
                pass
        threading.Thread(target=engine, daemon=True).start()
        with mock.patch("socket.socket.setsockopt"):
            t0 = time.monotonic()
            DM.pump(a, b, idle=5, send_timeout=0.3)
        stop.set()
        self.assertLess(time.monotonic() - t0, 4)

    def test_a_dripping_answer_runs_out_of_time(self):
        a, a2 = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(a2.close)

        def drip():
            try:
                for _ in range(40):
                    a2.sendall(b"H")
                    time.sleep(0.05)
            except OSError:
                pass
        threading.Thread(target=drip, daemon=True).start()
        t0 = time.monotonic()
        with self.assertRaises(socket.timeout):
            DM._read_head(a, timeout=0.5)                              # each byte inside the time, the whole not
        self.assertLess(time.monotonic() - t0, 1.5)

    def test_a_selector_fault_ends_the_stream_quietly(self):
        a, a2, b, b2 = self.pairs()
        with mock.patch("socket.socket.setsockopt"), \
                mock.patch.object(DM.selectors.DefaultSelector, "select", side_effect=ValueError("fd out of range")):
            self.assertIsNone(DM.pump(a, b, idle=1))                  # no ValueError for the server to answer with a 400
        src = (Path(DM.__file__)).read_text(encoding="utf-8")
        self.assertNotIn("select.select", src.replace("not select.select", ""))


class TheEnginesAddressStaysTheApps(unittest.TestCase):
    def test_the_page_cannot_ask_for_the_stream_address(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "meters_stream_info", "arguments": {}}}).encode()
        self.assertIn("the app's own", DW.check_rpc(body))
        batch = json.dumps([{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "tracks_list"}},
                            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "meters_stream_info"}}]).encode()
        self.assertTrue(DW.check_rpc(batch))
        self.assertEqual(DW.check_rpc(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                  "params": {"name": "session_get_card", "arguments": {}}}).encode()), "")

    def test_the_assistant_is_never_offered_it(self):
        from hypnomix.app import daw_assist as DA
        self.assertNotIn("meters_stream_info", DA.offered(["meters_stream_info", "session_get_info"], enabled=DA.GROUPS))

    def test_the_streams_reads_do_not_make_the_session_unsaved(self):
        for n in ("meters_stream_info", "session_get_card", "track_bounce"):
            self.assertEqual(DW._events({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": n}}), [], n)
        self.assertEqual(DW._events({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "session_set_card"}}),
                         [(1, "change")])


if __name__ == "__main__":
    unittest.main()
