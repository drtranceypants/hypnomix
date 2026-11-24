#!/usr/bin/env python3
"""Control a running Ableton Live through AbletonOSC (no mouse needed).

Needs the AbletonOSC remote script (patched copy in vendor/AbletonOSC; `hypnomix install` puts it in Live's Remote Scripts folder)
selected as a Control Surface in Live > Settings > Link, Tempo & MIDI.

Tracks are addressed by name (case-insensitive, unique prefix OK) or index.
"Master" is the master track, return tracks by their name ("A-Reverb") or "A", "B", ...

Python:
    from hypnomix.live.osc import Live
    live = Live()
    live.set_db("Lead", -3.5);  live.get_db("Lead")
    live.set_send("Lead", "A-Reverb", 0.3)
    live.devices("Master");  live.params("Master", "Limiter")
    live.set_param_display("Master", "Glue Compressor", "Threshold", -18.0)   # as Live displays it (dB)
    live.play_range(bar=33, bars=16)            # loop & play bars 33-48

CLI:
    hypnomix live status
    hypnomix live tracks
    hypnomix live db Lead -3.5          (omit value to read)
    hypnomix live send Lead A-Reverb 0.3
    hypnomix live devices Master
    hypnomix live params Master Limiter
    hypnomix live param Master "Glue Compressor" "Threshold" 0.6   (raw value; omit value to read)
    hypnomix live paramd Vox "EQ Eight" "1 Frequency A" 2500   (as Live displays it: Hz, dB, ms)
    hypnomix live mute Drums 1 | solo Lead 1     (track and 0/1 both required)
    hypnomix live play 33 16 | stop
    hypnomix live snapshot [out.json]   (all faders/sends/pans → JSON)
    hypnomix live restore snap.json
    hypnomix live reenable              (Live's "Re-Enable Automation")

  Tracking:
    hypnomix live inputs Guitar                         (list audio inputs)
    hypnomix live input Guitar "Ext. In" "2"            (route interface input 2)
    hypnomix live arm Guitar 1 | monitor Guitar auto
    hypnomix live record 17 8 3                         (punch-record bars 17-24, 3 passes = 3 takes)

WARNING: setting a control that has automation (fader, send, device knob) overrides that
automation until you re-enable it — the fader then stays put instead of following the envelope.
"""
import json, queue, re, sys, threading, time
from pathlib import Path

from pythonosc.udp_client import SimpleUDPClient
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer

HOST, SEND_PORT, RECV_PORT = "127.0.0.1", 11000, 11001
MASTER = -1


class LiveError(RuntimeError):
    pass


class Live:
    def __init__(self, timeout=2.0):
        self.timeout = timeout
        self.client = SimpleUDPClient(HOST, SEND_PORT)
        self._waiting: dict[str, queue.Queue] = {}
        self._lock = threading.Lock()
        d = Dispatcher()
        d.set_default_handler(self._on_reply)
        try:
            self.server = ThreadingOSCUDPServer((HOST, RECV_PORT), d)
        except OSError as e:
            raise LiveError(f"port {RECV_PORT} busy — another live.py/client running? ({e})")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self._tracks = None

    # ---------- transport ----------
    def _on_reply(self, address, *args):
        q = self._waiting.get(address)
        if q:
            q.put(args)

    def send(self, address, *args):
        self.client.send_message(address, list(args))

    def query(self, address, *args, timeout=None):
        with self._lock:
            q = self._waiting.setdefault(address, queue.Queue())
            while not q.empty():
                q.get_nowait()
            self.send(address, *args)
            try:
                return q.get(timeout=timeout or self.timeout)
            except queue.Empty:
                raise LiveError(f"no reply to {address} {args} — is Live open with AbletonOSC enabled?")

    def ping(self):
        try:
            return self.query("/live/test", timeout=1.0)[0] == "ok"
        except LiveError:
            return False

    # ---------- tracks ----------
    def tracks(self, refresh=False):
        """List of (id, name) incl. returns (-2, -3, …) and master (-1)."""
        if self._tracks is None or refresh:
            names = list(self.query("/live/song/get/track_names"))
            rets = list(self.query("/live/song/get/return_track_names"))
            self._tracks = [(i, n) for i, n in enumerate(names)] + \
                           [(-2 - i, n) for i, n in enumerate(rets)] + [(MASTER, "Master")]
        return self._tracks

    def tid(self, track):
        if isinstance(track, int):
            return track
        if re.fullmatch(r"-?\d+", str(track)):
            return int(track)
        t = str(track).lower()
        tr = self.tracks()
        rets = [x for x in tr if x[0] <= -2]
        if len(t) == 1 and t.isalpha() and ord(t) - 97 < len(rets):   # "A", "B" → returns
            return rets[ord(t) - 97][0]
        exact = [i for i, n in tr if n.lower() == t]
        if exact:
            return exact[0]
        pre = [(i, n) for i, n in tr if n.lower().startswith(t) or re.sub(r"^\d+-", "", n.lower()).startswith(t)]
        if len(pre) == 1:
            return pre[0][0]
        sub = [(i, n) for i, n in tr if t in n.lower()]
        if len(sub) == 1:
            return sub[0][0]
        raise LiveError(f"track {track!r} {'ambiguous: ' + str([n for _, n in pre or sub]) if (pre or sub) else 'not found'}")

    def name(self, tid):
        return dict(self.tracks()).get(tid, str(tid))

    # ---------- mixer ----------
    def get_volume(self, track):
        return self.query("/live/track/get/volume", self.tid(track))[1]

    def set_volume(self, track, value):
        self.send("/live/track/set/volume", self.tid(track), float(value))

    def _vol_str(self, tid, v):
        return self.query("/live/track/get/volume_string", tid, float(v))[2]

    @staticmethod
    def _parse_db(s):
        s = str(s)
        if "inf" in s.lower():
            return float("-inf")
        return float(re.search(r"-?[\d.]+", s).group())

    def get_db(self, track):
        tid = self.tid(track)
        return self._parse_db(self._vol_str(tid, self.get_volume(tid)))

    def set_db(self, track, db):
        """Set fader to an exact dB by bisecting Live's own value→string mapping."""
        tid = self.tid(track)
        lo, hi = 0.0, 1.0
        for _ in range(22):
            mid = (lo + hi) / 2
            if self._parse_db(self._vol_str(tid, mid)) < db:
                lo = mid
            else:
                hi = mid
        self.set_volume(tid, hi)
        return self.get_db(tid)

    def nudge_db(self, track, delta):
        return self.set_db(track, self.get_db(track) + delta)

    def get_pan(self, track):
        return self.query("/live/track/get/panning", self.tid(track))[1]

    def set_pan(self, track, value):       # -1 … 1
        self.send("/live/track/set/panning", self.tid(track), float(value))

    def _send_id(self, ret):
        rets = [x for x in self.tracks() if x[0] <= -2]
        if isinstance(ret, int):
            return ret
        rid = self.tid(ret)
        return [i for i, _ in rets].index(rid)

    def get_send(self, track, ret):
        return self.query("/live/track/get/send", self.tid(track), self._send_id(ret))[2]

    def set_send(self, track, ret, value):  # 0 … 1
        self.send("/live/track/set/send", self.tid(track), self._send_id(ret), float(value))

    def mute(self, track, on=True):
        self.send("/live/track/set/mute", self.tid(track), int(bool(on)))

    def solo(self, track, on=True):
        self.send("/live/track/set/solo", self.tid(track), int(bool(on)))

    def meter(self, track):
        tid = self.tid(track)
        return (self.query("/live/track/get/output_meter_left", tid)[1],
                self.query("/live/track/get/output_meter_right", tid)[1])

    # ---------- devices ----------
    def devices(self, track):
        return list(self.query("/live/track/get/devices/name", self.tid(track))[1:])

    def did(self, track, device):
        if isinstance(device, int) or re.fullmatch(r"\d+", str(device)):
            return int(device)
        names = self.devices(track)
        hits = [i for i, n in enumerate(names) if str(device).lower() in n.lower()]
        if not hits:
            raise LiveError(f"device {device!r} not on {self.name(self.tid(track))}: {names}")
        return hits[0]

    def params(self, track, device):
        tid, did = self.tid(track), self.did(track, device)
        names = self.query("/live/device/get/parameters/name", tid, did)[2:]
        vals = self.query("/live/device/get/parameters/value", tid, did)[2:]
        mins = self.query("/live/device/get/parameters/min", tid, did)[2:]
        maxs = self.query("/live/device/get/parameters/max", tid, did)[2:]
        return [dict(id=i, name=n, value=v, min=a, max=b) for i, (n, v, a, b) in enumerate(zip(names, vals, mins, maxs))]

    def pid(self, track, device, param):
        if isinstance(param, int) or re.fullmatch(r"\d+", str(param)):
            return int(param)
        ps = self.params(track, device)
        p = str(param).lower()
        hits = [x["id"] for x in ps if x["name"].lower() == p] or [x["id"] for x in ps if p in x["name"].lower()]
        if not hits:
            raise LiveError(f"param {param!r} not found; first few: {[x['name'] for x in ps[:20]]}")
        return hits[0]

    def get_param(self, track, device, param):
        tid, did = self.tid(track), self.did(track, device)
        pid = self.pid(tid, did, param)
        v = self.query("/live/device/get/parameter/value", tid, did, pid)[3]
        s = self.query("/live/device/get/parameter/value_string", tid, did, pid)[3]
        return v, s

    def set_param(self, track, device, param, value):
        """Raw parameter value (same units Live reports in params(): often 0…1 for plugins)."""
        tid, did = self.tid(track), self.did(track, device)
        pid = self.pid(tid, did, param)
        self.send("/live/device/set/parameter/value", tid, did, pid, float(value))
        return self.get_param(tid, did, pid)

    @staticmethod
    def _num(s):
        """'1.80 kHz' -> 1800, '-2.5 dB' -> -2.5, '0.71' -> 0.71, '250 ms' -> 250."""
        m = re.search(r"-?[\d.]+", str(s))
        if not m:
            raise LiveError(f"no number in {s!r}")
        v = float(m.group())
        s = str(s)
        if re.search(r"\dk(Hz)?\b|kHz", s):
            return v * 1000                                  # kHz -> Hz
        if re.search(r"[\d.]\s*s\b", s) and "ms" not in s:
            return v * 1000                                  # seconds -> ms (targets for times are in ms)
        return v

    def set_param_display(self, track, device, param, target, lo=None, hi=None, iters=24):
        """Set a parameter so Live *displays* `target` (Hz, dB, ms, …), by bisecting the raw value.
        Assumes the display rises with the raw value (true for EQ freq/gain/Q, times, levels)."""
        tid, did = self.tid(track), self.did(track, device)
        pid = self.pid(tid, did, param)
        p = self.params(tid, did)[pid]
        lo = p["min"] if lo is None else lo
        hi = p["max"] if hi is None else hi
        for _ in range(iters):
            mid = (lo + hi) / 2
            self.send("/live/device/set/parameter/value", tid, did, pid, float(mid))
            v = self._num(self.query("/live/device/get/parameter/value_string", tid, did, pid)[3])
            if v < target:
                lo = mid
            else:
                hi = mid
        self.send("/live/device/set/parameter/value", tid, did, pid, float(hi))
        return self.get_param(tid, did, pid)

    # ---------- song / transport ----------
    def tempo(self):
        return self.query("/live/song/get/tempo")[0]

    def beats_per_bar(self):
        try:
            return self.query("/live/song/get/signature_numerator")[0]
        except LiveError:
            return 4

    def play_range(self, bar, bars, loop=True):
        """Loop bars [bar, bar+bars) in arrangement and start playback from `bar`."""
        """Returns seconds per pass. Use play_from() when you need the exact position."""
        self.play_from(bar, loop_bars=bars if loop else None)
        return bars * self.beats_per_bar() * 60.0 / self.tempo()

    def is_playing(self):
        return bool(self.query("/live/song/get/is_playing")[0])

    def position(self):
        return self.query("/live/song/get/current_song_time")[0]

    def play_from(self, bar, loop_bars=None, tries=3):
        """Start playback at `bar` and return the confirmed position in beats.
        (Live ignores or resets a position sent while stopped — start_playing jumps to the
        start marker and a second Stop rewinds to 0 — so: play, then jump while playing.)"""
        bpb = self.beats_per_bar()
        start = (bar - 1) * bpb
        if loop_bars:
            self.send("/live/song/set/loop", 0)
            self.send("/live/song/set/loop_start", float(start))
            self.send("/live/song/set/loop_length", float(loop_bars * bpb))
            self.send("/live/song/set/loop", 1)
        self.t_started = None                        # wall-clock time playback began (if we began it)
        if not self.is_playing():
            self.t_started = time.time()
            self.send("/live/song/continue_playing")
            time.sleep(0.1)
        for _ in range(tries):
            self.send("/live/song/set/current_song_time", float(start))
            time.sleep(0.12)
            pos, self.t_pos = self.position(), time.time()
            if start - 0.25 <= pos <= start + bpb:
                return pos
        self.stop()
        raise LiveError(f"asked Live to play from beat {start:g} (bar {bar}) but it is at beat {pos:.1f}")

    def play(self):
        self.send("/live/song/continue_playing")

    def stop(self):
        self.send("/live/song/stop_playing")

    def cues(self):
        c = self.query("/live/song/get/cue_points")
        return list(zip(c[::2], c[1::2]))

    # ---------- tracking (recording real instruments) ----------
    def arm(self, track, on=True):
        self.send("/live/track/set/arm", self.tid(track), int(bool(on)))

    def inputs(self, track):
        tid = self.tid(track)
        return (list(self.query("/live/track/get/available_input_routing_types", tid)[1:]),
                list(self.query("/live/track/get/available_input_routing_channels", tid)[1:]),
                self.query("/live/track/get/input_routing_type", tid)[1],
                self.query("/live/track/get/input_routing_channel", tid)[1])

    def set_input(self, track, kind=None, channel=None):
        tid = self.tid(track)
        if kind:
            self.send("/live/track/set/input_routing_type", tid, kind)
            time.sleep(0.1)
        if channel:
            self.send("/live/track/set/input_routing_channel", tid, channel)
        return self.inputs(tid)[2:]

    def monitor(self, track, mode):
        """mode: in / auto / off (Live's 0 = In, 1 = Auto, 2 = Off)."""
        self.send("/live/track/set/current_monitoring_state", self.tid(track), {"in": 0, "auto": 1, "off": 2}[mode])

    def record(self, bar, bars, passes=1, preroll=1):
        """Punch-record bars [bar, bar+bars) on every armed track, looping `passes` times (Live 12 keeps
        each pass as a take lane). Blocks until done, then stops. Returns seconds recorded."""
        bpb, tempo = self.beats_per_bar(), self.tempo()
        start = (bar - 1) * bpb
        self.send("/live/song/set/loop_start", float(start))
        self.send("/live/song/set/loop_length", float(bars * bpb))
        self.send("/live/song/set/loop", 1 if passes > 1 else 0)
        self.send("/live/song/set/punch_in", 1)
        self.send("/live/song/set/punch_out", 1)
        self.send("/live/song/set/record_mode", 1)
        self.play_from(max(1, bar - preroll))
        time.sleep((preroll + bars * passes) * bpb * 60 / tempo + 0.2)
        self.send("/live/song/set/record_mode", 0)
        self.stop()
        self.send("/live/song/set/punch_in", 0)
        self.send("/live/song/set/punch_out", 0)
        return bars * passes * bpb * 60 / tempo

    # ---------- building chains (needs hypnomix's AbletonOSC patch) ----------
    def load_stock_device(self, track, name, timeout=4.0):
        """Load a stock Live device (browser name, e.g. "EQ Eight") at the end of a track's chain.
        Returns the new device's index."""
        tid = self.tid(track)
        before = len(self.devices(tid))
        try:
            r = self.query("/live/track/load_stock_device", tid, name, timeout=3.0)
        except LiveError:
            raise LiveError("Live's AbletonOSC script is missing hypnomix's device loader: run `hypnomix install`, "
                            "then restart Live")
        if not r[1]:
            raise LiveError(f"Live has no stock device called {name!r} (Live Lite/Intro lack some devices)")
        t0 = time.time()
        while time.time() - t0 < timeout:
            names = self.devices(tid)
            if len(names) > before:
                return len(names) - 1
            time.sleep(0.15)
        raise LiveError(f"{name} didn't appear on {self.name(tid)}")

    def set_send_db(self, track, ret, db):
        """Set a send to an exact dB by bisecting Live's own display (needs hypnomix's AbletonOSC patch)."""
        tid, sid = self.tid(track), self._send_id(ret)
        lo, hi = 0.0, 1.0
        for _ in range(20):
            mid = (lo + hi) / 2
            s = self.query("/live/track/get/send_string_for", tid, sid, float(mid))[3]
            if self._parse_db(s) < db:
                lo = mid
            else:
                hi = mid
        self.send("/live/track/set/send", tid, sid, float(hi))
        return self.get_send(tid, sid)

    def find_param(self, track, device, candidates):
        """First parameter whose name matches one of `candidates` (exact, then contains). None if absent."""
        ps = self.params(track, device)
        for c in candidates:
            for p in ps:
                if p["name"].lower() == c.lower():
                    return p
        for c in candidates:
            for p in ps:
                if c.lower() in p["name"].lower():
                    return p
        return None

    # ---------- snapshots ----------
    def snapshot(self):
        rets = [x for x in self.tracks(refresh=True) if x[0] <= -2]
        out = {}
        for tid, n in self.tracks():
            d = {"id": tid, "db": self.get_db(tid), "volume": self.get_volume(tid)}
            if tid != MASTER:
                d["pan"] = self.get_pan(tid)
            if tid >= 0:
                d["sends"] = {rn: self.get_send(tid, k) for k, (_, rn) in enumerate(rets)}
            out[n] = d
        return out

    def restore(self, snap, eps=1e-4):
        """Put faders/pans/sends back — writing ONLY values that differ. Writing an automated
        control in Live overrides (disables) its automation, so untouched controls must stay untouched."""
        n = 0
        for name, d in snap.items():
            tid = d["id"]
            if abs(self.get_volume(tid) - d["volume"]) > eps:
                self.set_volume(tid, d["volume"]); n += 1
            if "pan" in d and abs(self.get_pan(tid) - d["pan"]) > eps:
                self.set_pan(tid, d["pan"]); n += 1
            for k, (rn, v) in enumerate(d.get("sends", {}).items()):
                if abs(self.get_send(tid, k) - v) > eps:
                    self.send("/live/track/set/send", tid, k, float(v)); n += 1
        return n

    def reenable_automation(self):
        """Same as Live's 'Re-Enable Automation' button: every overridden envelope plays again."""
        self.send("/live/song/re_enable_automation")

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _cli(argv):
    if not argv:
        print(__doc__); return
    live, cmd, a = Live(), argv[0], argv[1:]
    if not live.ping():
        sys.exit("Live isn't answering on port 11000. Open Live, then Settings > Link, Tempo & MIDI > "
                 "Control Surface: AbletonOSC (restart Live once after installing the script).")
    num = lambda s: float(s)
    if cmd == "status":
        print(f"connected · {live.tempo():.1f} BPM · {len(live.tracks())} tracks (incl. returns + master)")
    elif cmd == "tracks":
        for tid, n in live.tracks():
            print(f"{tid:>4}  {n:<28} {live.get_db(tid):>7.1f} dB")
    elif cmd == "db":
        print(f"{live.name(live.tid(a[0]))}: {live.set_db(a[0], num(a[1])) if len(a) > 1 else live.get_db(a[0]):.2f} dB")
    elif cmd == "nudge":
        print(f"{live.name(live.tid(a[0]))}: {live.nudge_db(a[0], num(a[1])):.2f} dB")
    elif cmd == "send":
        if len(a) > 2:
            live.set_send(a[0], a[1], num(a[2]))
        print(f"{a[0]} → {a[1]}: {live.get_send(a[0], a[1]):.3f}")
    elif cmd == "pan":
        if len(a) > 1:
            live.set_pan(a[0], num(a[1]))
        print(f"{a[0]} pan {live.get_pan(a[0]):+.2f}")
    elif cmd in ("mute", "solo"):
        # strict: TRACK and 0/1 are both required, so a missing shell variable can't turn
        # "solo $T 0" into "solo 0" (which would solo track 0)
        if len(a) != 2 or a[1] not in ("0", "1"):
            sys.exit(f"usage: {cmd} TRACK 0|1   (got {a!r})")
        getattr(live, cmd)(a[0], int(a[1]))
    elif cmd == "devices":
        for i, n in enumerate(live.devices(a[0])):
            print(f"{i:>3}  {n}")
    elif cmd == "params":
        for p in live.params(a[0], a[1]):
            print(f"{p['id']:>4}  {p['name']:<40} {p['value']:.4g}  [{p['min']:.4g} … {p['max']:.4g}]")
    elif cmd == "param":
        v = live.set_param(*a[:3], num(a[3])) if len(a) > 3 else live.get_param(*a[:3])
        print(f"{a[2]} = {v[0]:.4g}  ({v[1]})")
    elif cmd == "paramd":
        v = live.set_param_display(*a[:3], num(a[3]))
        print(f"{a[2]} = {v[0]:.4g}  ({v[1]})")
    elif cmd == "play":
        secs = live.play_range(int(a[0]), int(a[1]) if len(a) > 1 else 8)
        print(f"looping bars {a[0]}–{int(a[0]) + (int(a[1]) if len(a) > 1 else 8) - 1} ({secs:.1f} s per pass)")
    elif cmd == "stop":
        live.stop()
    elif cmd == "cues":
        for n, t in live.cues():
            print(f"bar {t / live.beats_per_bar() + 1:>6.1f}  {n}")
    elif cmd == "snapshot":
        out = Path(a[0]) if a else __import__("hypnomix.core.paths", fromlist=["out"]).out("snapshots") / f"mix-{time.strftime('%Y%m%d-%H%M%S')}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(live.snapshot(), indent=1))
        print(f"saved {out}")
    elif cmd == "restore":
        print(f"restored ({live.restore(json.loads(Path(a[0]).read_text()))} controls changed)")
    elif cmd == "arm":
        if len(a) != 2 or a[1] not in ("0", "1"):
            sys.exit(f"usage: arm TRACK 0|1   (got {a!r})")
        on = int(a[1])
        live.arm(a[0], on); print(f"{a[0]} {'armed' if on else 'disarmed'}")
    elif cmd == "inputs":
        types, chans, cur_t, cur_c = live.inputs(a[0])
        print(f"current: {cur_t} / {cur_c}\ntypes: {types}\nchannels: {chans}")
    elif cmd == "input":
        print(live.set_input(a[0], a[1] if len(a) > 1 else None, a[2] if len(a) > 2 else None))
    elif cmd == "monitor":
        live.monitor(a[0], a[1]); print(f"{a[0]} monitoring {a[1]}")
    elif cmd == "record":
        passes = int(a[2]) if len(a) > 2 else 1
        print(f"recording bars {a[0]}-{int(a[0]) + int(a[1]) - 1} on armed tracks, {passes} pass(es) ...")
        live.record(int(a[0]), int(a[1]), passes)
        print("done. Each pass is in the track's take lanes (Live 12) or the arrangement.")
    elif cmd == "reenable":
        live.reenable_automation(); print("automation re-enabled")
    else:
        print(__doc__)


if __name__ == "__main__":
    try:
        _cli(sys.argv[1:])
    except LiveError as e:
        sys.exit(str(e))
