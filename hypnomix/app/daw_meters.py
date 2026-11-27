"""The engine's meter stream, relayed to the DAW view on the app's own origin.

The HypnoMix engine streams its meters over a WebSocket on a loopback port of its own (MCP `meters_stream_info`
gives `ws://127.0.0.1:PORT/meters?token=T`; the token is only given over MCP, and the engine refuses a browser
Origin that is not loopback). About 20 frames a second: per-route peak, RMS, momentary / short-term / integrated
LUFS, estimated true peak, correlation and 8 band levels, the same for the master, the playhead sample and rolling
state, and the readings of the Hypnomix Probe / Main devices.

How the page gets in, and how another web page is kept out:

  bind      the app listens on 127.0.0.1 only; the engine's stream listens on 127.0.0.1 only
  Host      the server refuses a request whose Host is not 127.0.0.1 or localhost (server.local(): a DNS-rebinding
            page has its own name in Host)
  Origin    a browser always sends Origin with a WebSocket; the server refuses any Origin but the app's own two
            (http://127.0.0.1:PORT, http://localhost:PORT), and a request a browser marks Sec-Fetch-Site: cross-site
  token     `t` must be the page's token (the one the app writes into its own page; another page cannot read it),
            compared in constant time; without it 403
  engine    the engine's port and token come from MCP `meters_stream_info`, called by the app itself. The page's POST
            /mcp refuses that tool (daw.APP_ONLY_TOOLS) and the Assistant is never offered it, so the page never learns
            either; the relay opens the engine's socket with no Origin header
  limit     at most MAX_RELAYS streams at once (each holds one of the server's threads): a new one closes the oldest
            (a stream nobody reads would otherwise keep its place for good), and only when none gives way is it 429
  time      the engine's 101 must come within HEAD_TIMEOUT in all (not per byte); a stream with nothing from either
            side for IDLE seconds is closed (the engine sends about 20 frames a second, so quiet means gone); a page
            that stops reading is dropped after SEND_TIMEOUT rather than holding the thread

The page opens `ws://<the app>/api/daw/meters?t=<the page's token>`; this module checks the token, asks the engine
over MCP where its stream is, opens the engine's WebSocket with the browser's own Sec-WebSocket-Key, answers the
browser with the 101, and then copies bytes both ways until either side closes. Nothing is parsed or buffered on
the way, so the relay costs nothing beyond the copy. With no stream (an engine without it, or attached to a window
that has none) it answers 503 and the page polls `meters_get` instead.
"""
import base64, hashlib, hmac, json, selectors, socket, threading, time

GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
INFO_TTL = 5.0
MAX_RELAYS = 4                    # streams open at once: a page opens one; each holds a server thread while it is open
_relays = threading.BoundedSemaphore(MAX_RELAYS)
IDLE = 15.0                       # seconds with nothing either way: the engine has stopped streaming
SEND_TIMEOUT = 5.0                # a side that takes no bytes for this long is let go
HEAD_TIMEOUT = 3.0                # the engine's whole 101, not each byte of it
_open = []                        # [(browser socket, engine socket)] being relayed, oldest first
_info = {"t": 0.0, "url": None, "v": None}
_lock = threading.Lock()


def accept_key(key):
    """The Sec-WebSocket-Accept for a Sec-WebSocket-Key (RFC 6455)."""
    return base64.b64encode(hashlib.sha1(key.encode("ascii") + GUID).digest()).decode("ascii")


def valid_key(key):
    try:
        return len(base64.b64decode(key or "", validate=True)) == 16
    except (ValueError, TypeError):
        return False


def stream_info(engine, fresh=False):
    """The engine's meters_stream_info (structuredContent), cached a few seconds per engine; None without one."""
    url = engine.url() if engine.connected() else None
    if not url:
        return None
    with _lock:
        if not fresh and _info["url"] == url and time.time() - _info["t"] < INFO_TTL:
            return _info["v"]
    try:
        r = engine.call("tools/call", {"name": "meters_stream_info", "arguments": {}}, timeout=3.0) or {}
        v = r.get("structuredContent") if isinstance(r, dict) else None
        if not (isinstance(v, dict) and v.get("running") and isinstance(v.get("port"), int) and isinstance(v.get("token"), str)):
            v = None
    except Exception:
        v = None
    with _lock:
        _info.update(t=time.time(), url=url, v=v)
    return v


def _refuse(handler, code, msg):
    handler.send(code, {"error": msg}, close=True)


def _read_head(sock, limit=8192, timeout=HEAD_TIMEOUT):
    """Read an HTTP response head (up to the blank line) -> (head text, any bytes after it). `timeout` is for the whole
    head: a peer that sends a byte now and then cannot hold it open (socket.timeout when it runs out)."""
    deadline = time.monotonic() + timeout
    buf = b""
    while b"\r\n\r\n" not in buf:
        left = deadline - time.monotonic()
        if left <= 0:
            raise socket.timeout("the answer's head did not come in time")
        sock.settimeout(left)
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
        if len(buf) > limit:
            break
    head, _, rest = buf.partition(b"\r\n\r\n")
    return head.decode("latin-1"), rest


def relay(handler, q, token, engine):
    """GET /api/daw/meters?t=TOKEN with a WebSocket upgrade: the engine's meter stream, same origin."""
    if not hmac.compare_digest(str(q.get("t", "")).encode("utf-8", "replace"), str(token).encode("utf-8")):
        return _refuse(handler, 403, "open the app's own page to do this")
    hd = handler.headers
    key = hd.get("Sec-WebSocket-Key", "")
    if (hd.get("Upgrade", "").lower() != "websocket" or "upgrade" not in hd.get("Connection", "").lower()
            or hd.get("Sec-WebSocket-Version") != "13" or not valid_key(key)):
        return _refuse(handler, 400, "this address is a WebSocket (the meter stream)")
    if not _relays.acquire(blocking=False):
        _close_oldest()                                    # a new view wins over one that has had its place longest
        if not _relays.acquire(timeout=2.0):
            return _refuse(handler, 429, "too many meter streams are open (close another DAW view)")
    try:
        return _relay(handler, key, engine)
    finally:
        _relays.release()


def _relay(handler, key, engine):
    info = stream_info(engine)
    if not info:
        return _refuse(handler, 503, "the engine has no meter stream (the view polls meters_get instead)")
    port, etoken = info["port"], info["token"]
    try:
        up = socket.create_connection(("127.0.0.1", port), timeout=3.0)
    except OSError:
        stream_info(engine, fresh=True)                    # the engine was restarted: ask again next time
        return _refuse(handler, 502, "the engine's meter stream did not answer")
    try:
        up.sendall((f"GET /meters?token={etoken} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                    f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode("ascii"))
        head, rest = _read_head(up)
        lines = head.split("\r\n")
        got = {k.strip().lower(): v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:])}
        if not lines or " 101 " not in lines[0] + " " or got.get("sec-websocket-accept") != accept_key(key):
            up.close()
            stream_info(engine, fresh=True)
            return _refuse(handler, 502, "the engine refused the meter stream")
    except OSError:
        up.close()
        return _refuse(handler, 502, "the engine's meter stream did not answer")

    down = handler.connection
    handler.close_connection = True
    handler.wfile.write((f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                         f"Sec-WebSocket-Accept: {accept_key(key)}\r\n\r\n").encode("ascii") + rest)
    handler.wfile.flush()
    pair = (down, up)
    with _lock:
        _open.append(pair)
    try:
        pump(down, up)
    except Exception:                                      # the socket is a WebSocket now: never an HTTP answer into it
        pass
    finally:
        with _lock:
            if pair in _open:
                _open.remove(pair)


def _close_oldest():
    """Close the stream that has been open longest (its pump ends and gives its place back)."""
    with _lock:
        pair = _open.pop(0) if _open else None
    for s in pair or ():
        try:
            s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def pump(a, b, idle=IDLE, send_timeout=SEND_TIMEOUT):
    """Copy bytes both ways between two sockets until either closes, `idle` seconds pass with nothing from either side,
    or one side takes no bytes for `send_timeout`. selectors, not select.select: no limit on the descriptor's number."""
    for s in (a, b):
        s.settimeout(send_timeout)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    peer = {a: b, b: a}
    sel = selectors.DefaultSelector()
    try:
        sel.register(a, selectors.EVENT_READ)
        sel.register(b, selectors.EVENT_READ)
        while True:
            ready = sel.select(idle)
            if not ready:
                return
            for key, _ in ready:
                data = key.fileobj.recv(65536)
                if not data:
                    return
                peer[key.fileobj].sendall(data)
    except (OSError, ValueError):
        return
    finally:
        sel.close()
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        b.close()


# ---------------------------------------------------------------- a small client (tests and tools)
class Client:
    """A minimal WebSocket client: text frames in, small text commands out (no extensions, no fragments)."""

    def __init__(self, host, port, path, origin=None, timeout=5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(bytes(range(16))).decode()
        extra = f"Origin: {origin}\r\n" if origin else ""
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n{extra}\r\n").encode())
        head, self.buf = _read_head(self.sock, timeout=timeout)
        self.status = int(head.split(" ", 2)[1]) if head.startswith("HTTP/") else 0
        self.head = head
        if self.status == 101 and accept_key(key) not in head:
            raise OSError("bad Sec-WebSocket-Accept")
        self.sock.settimeout(timeout)

    def _need(self, n):
        while len(self.buf) < n:
            c = self.sock.recv(65536)
            if not c:
                raise EOFError("closed")
            self.buf += c
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        """The next text message (dict when it is JSON); None when the server closed."""
        while True:
            b0, b1 = self._need(2)
            op, n = b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = int.from_bytes(self._need(2), "big")
            elif n == 127:
                n = int.from_bytes(self._need(8), "big")
            mask = self._need(4) if b1 & 0x80 else None
            data = self._need(n)
            if mask:
                data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
            if op == 8:
                return None
            if op == 9:
                self._send(0xA, data)
                continue
            if op in (1, 2):
                try:
                    return json.loads(data)
                except ValueError:
                    return data

    def _send(self, op, data):
        mask = b"\x11\x22\x33\x44"
        n = len(data)
        head = bytes([0x80 | op]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + n.to_bytes(2, "big"))
        self.sock.sendall(head + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))

    def send(self, obj):
        self._send(1, json.dumps(obj).encode())

    def close(self):
        try:
            self._send(8, b"")
        except OSError:
            pass
        self.sock.close()
