#!/usr/bin/env python3
"""Probe: measure every track while Live plays, with every plug-in on it, and nothing rendered or exported.

  hypnomix probe device                write HypnomixProbe.amxd, HypnomixMain.amxd + hypnomix_probe.js into your Live
                                       User Library
  hypnomix probe cards SET.als         what you told HypnoMix in Live (track roles, the song card), read from the set
  hypnomix probe insert SET.als        a NEW set with the probe on every track and return, and the review device and
                                       HypnomixMain on Main (no need to place one first; --probes-only for probes alone)
  hypnomix probe status                which tracks are sending, with their loudness right now
  hypnomix probe listen [--secs 60]    record what the probes measure while you play (or --bars 33-48 --play)
  hypnomix probe report CAPTURE.json   turn a capture into a review: findings.json + REVIEW.md
  hypnomix probe chains [show NAME]    the mastering chain templates HypnomixMain builds on Main (masterchain.py)

Telling HypnoMix what things are. Each track's probe has three menus: what it is (lead vocal, harmony, kick, bass,
guitar …, or "auto" to let the scan work it out by sound), its priority (focus: others give way to it; background:
it gives way) and Protect (ask before any change). HypnomixMain, on Main, is the song card: genre, key and scale
(the tuning and harmony tools use it instead of guessing; a mode becomes the major key with the same notes),
chords (typed; kept by the app), loudness target, true-peak ceiling, limiter character and amount. The menus are
Live parameters, so they are saved in the set, and `scan` reads them from the .als; the app also sees them live.

Mastering chain (HypnomixMain). Build chain puts Live's own devices (EQ Eight, Glue Compressor, Multiband Dynamics,
Saturator, Utility, Limiter) in a "HypnoMix Master" rack just before HypnomixMain; edit it like any rack. Match target
turns the Limiter's Gain until Main lands on the card's Target LUFS; Save keeps your edited chain (or a rack of your
own) as a template. See hypnomix/app/masterchain.py.

Record and review before export (HypnomixMain). Press it and Live plays; the device records Main exactly as you
hear it (a real-time bounce, 32-bit float) while every probe listens. When Live stops, the app reviews it:
loudness and true peak against the song card, the live findings, release checks (`qc`), translation (`translate`)
and the mastering moves as proposals (`master --plan`, with the card's target, ceiling, character and amount).
Live's own Export is still how you make the final file: no Live API can start an export.

How it works. The probe is a small Max for Live audio effect. Put it LAST on a track: it hears the track after
all of its devices and plug-ins (before the fader; the fader and pan are read and added). Ten times a second it
sends what it measured to the HypnoMix app on this computer (UDP, 127.0.0.1 only, port 8792; a second copy of
the app sets HYPNOMIX_PROBE_PORT to its own port before it makes its devices and starts):

  loudness   K-weighted mean square per channel (BS.1770 filters at Live's sample rate): momentary,
             short-term and integrated loudness are worked out from it
  peak       sample peak per channel (not true peak: use `measure` on a bounce for that)
  tone       energy in 8 bands (sub 20-60, bass 60-120, upper bass 120-250, low-mid 250-500, mid 500-2k,
             upper-mid 2-4k, presence 4-8k, air 8k+), the same bands as `match`
  stereo     L/R correlation, side vs mid, and correlation below 120 Hz (is the low end mono?)
  where      the song position in beats and whether Live is playing, so every number has a bar

One play of the song measures every track at once. A deep scan that renders every track (without its effects)
takes far longer and still cannot hear third-party plug-ins; the probe hears exactly what you hear.
Play only the loudest 30 seconds for a quick check, or one section while you work on it.

`listen` works with the app running (it records through the app) or on its own. `--play` starts Live at the bar
through AbletonOSC (`hypnomix install`); without it, press play yourself.

What the report finds: loudness and peak of Main against your targets, tracks that clip into the next device,
frequency fights between tracks while they play together (with the band and who should give way), the lead
vocal's level against the band section by section, a low end that is not mono, and very narrow or very wide
mixes. Everything is a proposal for the normal review; nothing is applied to the set.

The probe also takes part in the in-Live A/B (`hypnomix abset`): on Main it matches the loudness of A and B,
so the louder one does not win just for being louder.
"""
import argparse, glob, json, math, os, re, sys, threading, time
from collections import deque
from pathlib import Path

DEFAULT_UDP, DEFAULT_APP = 8792, 8791


def _port(var, default):
    """A port number from the environment variable `var` (read when asked, so a second app instance started with
    its own value works), else the default. Anything that is not a port number is ignored."""
    try:
        n = int(str(os.environ.get(var, "")).strip() or default)
        return n if 1 <= n <= 65535 else default
    except ValueError:
        return default


def probe_port():
    """The UDP port the probes send to and the hub listens on: HYPNOMIX_PROBE_PORT, default 8792. A second app
    instance needs its own (the probe devices and the REAPER relay are generated with the same value)."""
    return _port("HYPNOMIX_PROBE_PORT", DEFAULT_UDP)


def app_port():
    """The port of the HypnoMix app the devices talk to: HYPNOMIX_PORT, default 8791 (what `app --port N` uses)."""
    return _port("HYPNOMIX_PORT", DEFAULT_APP)


def port_in_use_text(port, err):
    """The status text when the probe hub cannot bind its port: which port, and how to change it."""
    return (f"UDP port {port} is in use ({err}); close the other program using it, or give this copy its own port: set "
            f"HYPNOMIX_PROBE_PORT to another number before starting the app (and open the probe devices made by that "
            f"copy; they send to the same port). It is tried again every few seconds")


PORT_UDP, PORT_APP = probe_port(), app_port()     # at import; the functions above are what the code below asks
NV = 20                                   # values per block, in this order:
FIELDS = ["kL", "kR", "pL", "pR", "rL", "rR", "mid", "side", "lr", "lowL", "lowR", "lowLR"] + [f"b{i}" for i in range(8)]
BANDS = [("sub", 20, 60), ("bass", 60, 120), ("upper bass", 120, 250), ("low-mid", 250, 500),
         ("mid", 500, 2000), ("upper-mid", 2000, 4000), ("presence", 4000, 8000), ("air", 8000, 20000)]
SPLITS = [60, 120, 250, 500, 2000, 4000, 8000]
JW, H = 300, 169                          # the drawn part of the device; controls sit to its right
W = {"track": 470, "main": 826}           # Main: the song card, then the mastering chain column (masterchain.py)
WIN = 4800
ROLES = ["auto", "lead vocal", "harmony", "double", "backing vocals", "kick", "snare", "drums", "percussion", "bass",
         "guitar", "acoustic guitar", "piano", "keys", "synth", "strings", "pad", "brass", "fx", "other"]
GENRES = ["not set", "pop", "rock", "indie", "folk", "country", "singer-songwriter", "r&b / soul", "hip-hop", "electronic",
          "dance", "ambient", "jazz", "blues", "metal", "orchestral", "world", "psychedelic", "other"]
KEYS = ["not set", "C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
SCALES = ["major", "minor", "dorian", "phrygian", "lydian", "mixolydian", "locrian"]
CONTROLS = {   # name: (label, kind, items or (min, max, default, unitstyle), x, y)
    "track": [("hm_role", "What it is", "menu", ROLES, 312, 22),
              ("hm_priority", "Priority", "menu", ["normal", "focus: others give way", "background: gives way"], 312, 62),
              ("hm_protect", "Protect", "menu", ["off", "on: ask before any change"], 312, 102)],
    "main": [("hm_genre", "Genre", "menu", GENRES, 312, 22),
             ("hm_key", "Key", "menu", KEYS, 312, 62),
             ("hm_scale", "Scale", "menu", SCALES, 392, 62),
             ("hm_mode", "Limiter", "menu", ["clean", "punch", "loud"], 312, 102),
             ("hm_target", "Target LUFS", "num", (-24.0, -6.0, -14.0, 1), 482, 22),
             ("hm_ceiling", "Ceiling dBTP", "num", (-3.0, 0.0, -1.0, 1), 562, 22),
             ("hm_amount", "Amount %", "num", (0.0, 100.0, 100.0, 1), 482, 62)],
}                                # averaging window in samples (100 ms at 48 kHz)


# ---------------------------------------------------------------- the device's script
JS = r"""// hypnomix probe (jsui): measures this track and sends it to the HypnoMix app. Audio passes through.
autowatch = 1;
inlets = 1;
outlets = 2;            // 0: OSC to udpsend   1: filter coefficients and gain
mgraphics.init();
mgraphics.relative_coords = 0;
mgraphics.autofill = 0;

var BASE = "http://127.0.0.1:__APP__";
var W = __W__, H = __H__, NV = __NV__;
var MODE = (jsarguments.length > 1 && jsarguments[1] == "main") ? "main" : "track";
var MENUS = __MENUS__;                    // control name -> labels (menus), so values are sent as words
var LABELS = __LABELS__;                  // the name Live shows for each control -> its hm_ name
var v = [];
var st = {ready: false, id: 0, name: "", main: false, fader: 0, pan: 0, sr: 0, gain: 0, lastSend: 0, lk: -120, pk: -120,
          playing: 0, beat: 0, sent: 0, ok: 0, busy: false, params: {}, chords: "", sig: "", sigAt: 0, card: false,
          rec: false, recPath: "", stopAt: 0, flash: "", flashUntil: 0};
var slow = new Task(refresh, this);
var cmdTask = new Task(askCmd, this);
for (var i = 0; i < NV; i++) v.push(0);

function bang() {                         // live.thisdevice: the Live API is ready
    if (dead) return;
    st.ready = true;
    try { readParams(); } catch (e) { st.err = "params: " + e; }
    refresh();
    slow.interval = 1000; slow.repeat();
    cmdTask.interval = 500; cmdTask.repeat();
}
var dead = false, reqs = [];             // once Live frees the device nothing may touch it again (a late timer,
function notifydeleted() {                // redraw or HTTP answer into a freed jsui crashes Live)
    dead = true;
    slow.cancel(); cmdTask.cancel(); try { initTask.cancel(); } catch (e) { }
    for (var i = 0; i < reqs.length; i++) { try { reqs[i].abort(); } catch (e) { } }
    reqs = [];
}
function redraw() { if (!dead) mgraphics.redraw(); }
function track_req(r) { reqs.push(r); if (reqs.length > 8) reqs.shift(); return r; }
// when the script is reloaded inside a device that is already running, live.thisdevice does not fire again
var initTask = new Task(function () {
    if (st.ready || dead) return;
    try { var me = new LiveAPI("this_device"); if (me.id && me.id != "0") bang(); } catch (e) { }
}, this);
initTask.schedule(1500);
function loadbang() { redraw(); }
function now() { return new Date().getTime(); }
function str(x) { return (x instanceof Array) ? x.join(" ") : String(x); }

function refresh() {
    if (dead) return;
    if (!st.ready) return;
    try {
        var t = new LiveAPI("this_device canonical_parent");
        st.id = parseInt(t.id);
        st.main = String(t.unquotedpath).indexOf("master_track") >= 0;
        st.name = st.main ? "Main" : str(t.get("name"));
        var vol = new LiveAPI(t.unquotedpath + " mixer_device volume");
        var s = str(vol.call("str_for_value", parseFloat(vol.get("value"))));
        st.fader = (s.indexOf("inf") >= 0) ? -120 : parseFloat(s);
        var pan = new LiveAPI(t.unquotedpath + " mixer_device panning");
        st.pan = parseFloat(pan.get("value"));
    } catch (e) { st.err = "refresh: " + e; }
    if (MODE == "main" && now() - st.sigAt > 5000) {
        st.sigAt = now();
        try { st.sig = signature(); loadCard(); } catch (e) { st.err = "signature: " + e; }
    }
    sendMeta();
    redraw();
}

function signature() {                    // the song, recognised by its track names (the same rule as HypnoMix's own)
    var song = new LiveAPI("live_set"), n = song.getcount("tracks"), names = [];
    for (var i = 0; i < n; i++) names.push(str(new LiveAPI("live_set tracks " + i).get("name")));
    names.sort();
    var h = 0x811c9dc5, t = names.join("\n");
    for (i = 0; i < t.length; i++) { h ^= t.charCodeAt(i); h = imul32(h, 0x01000193) >>> 0; }
    return ("00000000" + h.toString(16)).slice(-8);
}
function imul32(a, b) {                    // Math.imul is missing in Max's JavaScript engine
    var ah = (a >>> 16) & 0xffff, al = a & 0xffff, bh = (b >>> 16) & 0xffff, bl = b & 0xffff;
    return ((al * bl) + (((ah * bl + al * bh) << 16) >>> 0)) | 0;
}
function readParams() {                   // the menus' saved values, straight from Live
    var me = new LiveAPI("this_device"), n = me.getcount("parameters");
    for (var i = 0; i < n; i++) {
        var p = new LiveAPI("this_device parameters " + i), nm = str(p.get("original_name")), sh = str(p.get("name"));
        if (nm.indexOf("hm_") != 0) nm = LABELS[sh] || LABELS[nm] || nm;
        if (nm.indexOf("hm_") == 0) st.params[nm.replace(/^hm_/, "")] = word(nm, parseFloat(p.get("value")));
    }
}
function word(name, v) { var m = MENUS[name]; return m ? m[Math.max(0, Math.min(m.length - 1, Math.round(v)))] : v; }
function param(name, v) { st.params[name.replace(/^hm_/, "")] = word(name, v); sendMeta(); redraw(); }
function chords() { st.chords = arrayfromargs(arguments).join(" "); sendMeta(); saveCard(); }
function sendMeta() {
    if (dead) return;
    if (!st.ready) return;
    var pr = st.params;
    if (st.err) { pr = JSON.parse(JSON.stringify(st.params)); pr._error = st.err; }
    outlet(0, ["/hm/meta", st.id, st.name, MODE == "main" ? 1 : 0, st.sig, JSON.stringify(pr), st.chords]);
}
function post(path, body, done) {
    var r = track_req(new XMLHttpRequest());
    r.open("POST", BASE + path);
    r.onreadystatechange = function () {
        if (dead || this.readyState != 4) return;
        var d = null;
        try { d = JSON.parse(this.responseText); } catch (e) { d = null; }
        if (done) done(d);
    };
    r.send(JSON.stringify(body));
}
function loadCard() {                     // chords typed earlier are kept by the app, not in the set
    if (st.card || !st.sig) return;
    var r = track_req(new XMLHttpRequest());
    r.open("GET", BASE + "/api/probe/card?sig=" + st.sig);
    r.onreadystatechange = function () {
        if (dead || this.readyState != 4) return;
        var d = null;
        try { d = JSON.parse(this.responseText); } catch (e) { d = null; }
        if (!d) return;
        st.card = true;
        if (d.chords && !st.chords) { st.chords = d.chords; outlet(1, "chords", "set", d.chords); }
    };
    r.send();
}
function saveCard() { if (st.sig) post("/api/probe/card", {sig: st.sig, chords: st.chords, params: st.params}); }
function flash(t) { st.flash = t; st.flashUntil = now() + 4000; redraw(); }

function record() {                       // Main: record the master as it plays, then the app reviews it before export
    if (dead) return;
    if (MODE != "main" || !st.ready) return;
    if (!st.rec) {
        post("/api/master/record", {state: "start", sig: st.sig, params: st.params, chords: st.chords}, function (d) {
            if (!d || !d.path) { flash(d && d.error ? d.error : "Start the HypnoMix app first"); return; }
            st.recPath = d.path;
            outlet(1, "rec", "samptype", "float32");
            outlet(1, "rec", "open", d.path);
            outlet(1, "rec", 1);
            st.rec = true; st.stopAt = 0;
            if (!st.song) st.song = new LiveAPI("live_set");
            if (!parseInt(st.song.get("is_playing"))) st.song.call("start_playing");
            flash("Recording Main: play to the end, or press Stop");
        });
    } else {
        outlet(1, "rec", 0);
        st.rec = false;
        post("/api/master/record", {state: "stop", path: st.recPath, sig: st.sig, params: st.params, chords: st.chords}, function (d) {
            flash(d && d.job ? "Reviewing in the HypnoMix app…" : "Stopped (the app did not answer)");
        });
    }
    redraw();
}
function onclick(x, y) { if (MODE == "main" && y > H - 34 && x < 200) record(); }

function sr(x) {                          // dspstate~: Live's sample rate; set the K-weighting filters for it
    if (!x || x == st.sr) return;
    st.sr = x;
    var K = Math.tan(Math.PI * 1681.974450955533 / x), Q = 0.7071752369554196;
    var Vh = Math.pow(10, 3.999843853973347 / 20), Vb = Math.pow(Vh, 0.4996667741545416);
    var a0 = 1 + K / Q + K * K;
    outlet(1, "k1", (Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0,
           2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0);
    K = Math.tan(Math.PI * 38.13547087602444 / x); Q = 0.5003270373238773;
    a0 = 1 + K / Q + K * K;
    outlet(1, "k2", 1, -2, 1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0);
}

function val(i, x) { if (i >= 0 && i < NV) v[i] = x; }

function blk() {                          // after every 100 ms block: send it
    if (dead) return;
    if (!st.ready) return;
    if (!st.song) st.song = new LiveAPI("live_set");
    var song = st.song;
    st.playing = parseInt(song.get("is_playing"));
    st.beat = parseFloat(song.get("current_song_time"));
    if (st.rec && !st.playing) { if (!st.stopAt) st.stopAt = now(); else if (now() - st.stopAt > 1500) record(); }
    else st.stopAt = 0;
    var msg = ["/hm/probe", st.id, st.name, st.main ? 1 : 0, st.beat, st.playing, st.fader, st.pan, st.sr];
    for (var i = 0; i < NV; i++) msg.push(v[i]);
    outlet(0, msg);
    st.sent++;
    var ms = v[0] * v[0] + v[1] * v[1];
    st.lk = ms > 0 ? -0.691 + 10 * Math.log(ms) / Math.LN10 : -120;
    var p = Math.max(v[2], v[3]);
    st.pk = p > 0 ? 20 * Math.log(p) / Math.LN10 : -120;
    if (st.sent % 3 == 0) redraw();
}

function askCmd() {                       // the app may set a gain (loudness matching in the A/B)
    if (dead) return;
    if (st.busy && now() - st.busyAt < 3000) return;
    st.busy = true; st.busyAt = now();
    var r = track_req(new XMLHttpRequest());
    r.open("GET", BASE + "/api/probe/cmd?id=" + st.id + "&name=" + encodeURIComponent(st.name) + "&main=" + (st.main ? 1 : 0));
    r.onreadystatechange = function () {
        if (dead || this.readyState != 4) return;
        st.busy = false;
        var d = null;
        try { d = JSON.parse(this.responseText); } catch (e) { d = null; }
        if (!d) return;
        st.ok = now();
        var g = parseFloat(d.gain_db || 0);
        if (Math.abs(g - st.gain) > 0.01) { st.gain = g; outlet(1, "g", Math.pow(10, g / 20)); redraw(); }
    };
    r.send();
}

function paint() {
    mgraphics.set_source_rgba(0.13, 0.125, 0.11, 1);
    mgraphics.rectangle(0, 0, W, H); mgraphics.fill();
    mgraphics.select_font_face("Arial Bold"); mgraphics.set_font_size(10);
    mgraphics.set_source_rgba(0.93, 0.91, 0.87, 1);
    mgraphics.move_to(6, 14); mgraphics.show_text(MODE == "main" ? "HYPNOMIX MAIN" : "HYPNOMIX PROBE");
    mgraphics.select_font_face("Arial"); mgraphics.set_font_size(10);
    var on = now() - st.ok < 2500;
    mgraphics.set_source_rgba(on ? 0.5 : 0.63, on ? 0.82 : 0.6, on ? 0.64 : 0.56, 1);
    mgraphics.move_to(104, 14); mgraphics.show_text(on ? "app connected" : "app not running: start the HypnoMix app");
    mgraphics.set_source_rgba(0.63, 0.6, 0.56, 1);
    mgraphics.move_to(6, 30);
    mgraphics.show_text(st.name + "   " + (st.lk > -100 ? st.lk.toFixed(1) + " LUFS-M" : "silent") +
                        "   peak " + (st.pk > -100 ? st.pk.toFixed(1) : "-inf") + (st.gain ? "   match " + st.gain.toFixed(1) + " dB" : ""));
    var x = Math.max(0, Math.min(1, (st.lk + 60) / 60));
    mgraphics.set_source_rgba(0.24, 0.24, 0.25, 1); mgraphics.rectangle(6, 40, W - 12, 8); mgraphics.fill();
    mgraphics.set_source_rgba(0.56, 0.78, 0.64, 1); mgraphics.rectangle(6, 40, (W - 12) * x, 8); mgraphics.fill();
    mgraphics.set_source_rgba(0.63, 0.6, 0.56, 1);
    mgraphics.move_to(6, 66);
    if (MODE == "track") {
        mgraphics.show_text("Tell HypnoMix what this is (right). Saved in the set;");
        mgraphics.move_to(6, 80); mgraphics.show_text("'auto' lets the scan work it out by sound.");
    } else {
        mgraphics.show_text("Song card: genre, key, chords and loudness for every tool.");
        mgraphics.move_to(6, 80); mgraphics.show_text("Chords (type, then Enter) are kept by the app.");
        var bx = 6, by = H - 30;
        mgraphics.set_source_rgba(st.rec ? 0.75 : 0.56, st.rec ? 0.2 : 0.25, 0.25, 1);
        mgraphics.rectangle_rounded(bx, by, 190, 22, 6, 6); mgraphics.fill();
        mgraphics.set_source_rgba(0.95, 0.93, 0.89, 1); mgraphics.select_font_face("Arial Bold");
        mgraphics.move_to(bx + 12, by + 15);
        mgraphics.show_text(st.rec ? "Stop and review" : "Record and review before export");
        mgraphics.select_font_face("Arial");
    }
    if (now() < st.flashUntil) { mgraphics.set_source_rgba(0.5, 0.82, 0.64, 1); mgraphics.move_to(6, 100); mgraphics.show_text(st.flash); }
}
"""


# ---------------------------------------------------------------- the patch
class Patch:
    def __init__(self):
        self.boxes, self.lines, self.n = [], [], 100

    def add(self, text, ins, outs, otype=None, x=0, y=0, **extra):
        self.n += 1
        bid = f"obj-{self.n}"
        b = {"id": bid, "maxclass": "newobj", "numinlets": ins, "numoutlets": outs,
             "outlettype": otype if otype is not None else ["signal"] * outs,
             "patching_rect": [float(x), float(y), 9.0 * max(6, len(text)), 22.0], "text": text}
        b.update(extra)
        self.boxes.append({"box": b})
        return bid

    def wire(self, a, ao, b, bi):
        self.lines.append({"patchline": {"destination": [b, bi], "source": [a, ao]}})


def control(P, thisdev, js, name, label, kind, spec, x, y):
    """A Live parameter (saved with the set, automatable) whose value goes to the script as `param NAME value`."""
    P.n += 1
    bid = f"obj-{P.n}"
    if kind == "menu":
        b = {"id": bid, "maxclass": "live.menu", "numinlets": 1, "numoutlets": 3, "outlettype": ["", "", "float"],
             "parameter_enable": 1, "varname": name, "patching_rect": [float(x + 600), float(y + 400), 100.0, 15.0],
             "presentation": 1, "presentation_rect": [float(x), float(y), 150.0 if len(spec) > 8 or max(len(str(x)) for x in spec) > 10 else 75.0, 15.0],
             "saved_attribute_attributes": {"valueof": {"parameter_enum": list(spec), "parameter_longname": name,
                                                        "parameter_mmax": len(spec) - 1, "parameter_shortname": label,
                                                        "parameter_type": 2, "parameter_initial_enable": 1,
                                                        "parameter_initial": [0]}}}
    else:
        lo, hi, default, unit = spec
        b = {"id": bid, "maxclass": "live.numbox", "numinlets": 1, "numoutlets": 2, "outlettype": ["", "float"],
             "parameter_enable": 1, "varname": name, "patching_rect": [float(x + 600), float(y + 400), 44.0, 15.0],
             "presentation": 1, "presentation_rect": [float(x), float(y), 70.0, 15.0],
             "saved_attribute_attributes": {"valueof": {"parameter_longname": name, "parameter_shortname": label,
                                                        "parameter_type": 0, "parameter_mmin": lo, "parameter_mmax": hi,
                                                        "parameter_unitstyle": unit, "parameter_initial_enable": 1,
                                                        "parameter_initial": [default]}}}
    P.boxes.append({"box": b})
    P.n += 1
    P.boxes.append({"box": {"id": f"obj-{P.n}", "maxclass": "live.comment", "numinlets": 1, "numoutlets": 0,
                            "patching_rect": [float(x + 600), float(y + 380), 90.0, 18.0], "presentation": 1,
                            "presentation_rect": [float(x), float(y - 14), 90.0, 14.0], "text": label}})
    pre = P.add(f"prepend param {name}", 1, 1, [""], x=x + 600, y=y + 430)
    P.wire(bid, 0, pre, 0)
    P.wire(pre, 0, js, 0)
    P.wire(thisdev, 0, bid, 0)            # report the saved value once Live is ready


def build_patch(patch, mode="track"):
    """The probe patch on top of Live's blank Max Audio Effect: pass-through with a smoothed gain, plus meters.
    mode "track": what the track is (role, priority, protect). mode "main": the song card and Record and review."""
    p = patch["patcher"]
    keep = [b for b in p["boxes"] if b["box"].get("text") in ("plugin~", "plugout~", "Device vertical limit")]
    pin = next(b["box"]["id"] for b in keep if b["box"].get("text") == "plugin~")
    pout = next(b["box"]["id"] for b in keep if b["box"].get("text") == "plugout~")
    P = Patch()
    # pass-through with gain (1.0 unless the A/B asks Main to match loudness)
    gL, gR = P.add("*~ 1.", 2, 1, x=40, y=70), P.add("*~ 1.", 2, 1, x=100, y=70)
    line = P.add("line~", 2, 2, ["signal", "bang"], x=160, y=70)
    pk = P.add("pack f 30", 2, 1, [""], x=160, y=46)
    for ch, g in ((0, gL), (1, gR)):
        P.wire(pin, ch, g, 0)
        P.wire(g, 0, pout, ch)
        P.wire(line, 0, g, 1)
    P.wire(pk, 0, line, 0)
    # the script (display, Live API, OSC out)
    thisdev = P.add("live.thisdevice", 1, 3, ["bang", "int", "int"], x=400, y=20)
    js = P.add("", 1, 2, ["", ""], x=400, y=60)
    jsbox = P.boxes[-1]["box"]
    jsbox.update({"maxclass": "jsui", "filename": "hypnomix_probe.js", "border": 0, "parameter_enable": 0,
                  "jsarguments": [mode], "presentation": 1, "presentation_rect": [0.0, 0.0, float(JW), float(H)]})
    jsbox["patching_rect"] = [400.0, 60.0, float(JW), float(H)]
    del jsbox["text"]
    P.wire(thisdev, 0, js, 0)
    udp = P.add(f"udpsend 127.0.0.1 {probe_port()}", 1, 0, [], x=400, y=140)
    P.wire(js, 0, udp, 0)
    route = P.add("route k1 k2 g chords rec", 1, 6, ["", "", "", "", "", ""], x=600, y=140)
    P.wire(js, 1, route, 0)
    P.wire(route, 2, pk, 0)
    dsp = P.add("dspstate~", 1, 4, ["int", "float", "int", "int"], x=600, y=20)
    srp = P.add("prepend sr", 1, 1, [""], x=600, y=46)
    P.wire(dsp, 1, srp, 0)
    P.wire(srp, 0, js, 0)
    lb = P.add("loadbang", 1, 1, ["bang"], x=700, y=20)
    P.wire(lb, 0, dsp, 0)
    # clock: every 100 ms bang every snapshot~ (right outlet first), then tell the script the block is complete
    metro = P.add("metro 100", 2, 1, ["bang"], x=700, y=46)
    tog = P.add("t b b", 1, 2, ["bang", "bang"], x=700, y=70)
    P.wire(lb, 0, metro, 0)
    P.wire(metro, 0, tog, 0)
    blk = P.add("", 2, 1, [""], x=760, y=96)
    bb = P.boxes[-1]["box"]
    bb.update({"maxclass": "message", "text": "blk"})
    P.wire(tog, 0, blk, 0)
    dl = P.add("deferlow", 1, 1, [""], x=760, y=120)      # the Live API may not be called from the audio scheduler
    P.wire(blk, 0, dl, 0)
    P.wire(dl, 0, js, 0)

    y0 = 200

    def meter(sig, outlet_, idx, mode, x):
        avg = P.add(f"average~ {WIN} {mode}", 1, 1, x=x, y=y0 + 60)
        snap = P.add("snapshot~", 2, 1, [""], x=x, y=y0 + 90)
        pre = P.add(f"prepend val {idx}", 1, 1, [""], x=x, y=y0 + 120)
        P.wire(sig, outlet_, avg, 0)
        P.wire(avg, 0, snap, 0)
        P.wire(tog, 1, snap, 0)
        P.wire(snap, 0, pre, 0)
        P.wire(pre, 0, js, 0)

    # K-weighted loudness, per channel: two biquads in series
    for ch, (i0, x) in enumerate(((0, 40), (1, 140))):
        b1 = P.add("biquad~ 1. 0. 0. 0. 0.", 6, 1, x=x, y=y0)
        b2 = P.add("biquad~ 1. 0. 0. 0. 0.", 6, 1, x=x, y=y0 + 30)
        P.wire(pin, ch, b1, 0)
        P.wire(route, 0, b1, 0)
        P.wire(b1, 0, b2, 0)
        P.wire(route, 1, b2, 0)
        meter(b2, 0, i0, "rms", x)
    # sample peak
    for ch, (i0, x) in enumerate(((2, 240), (3, 300))):
        pa = P.add("peakamp~", 2, 1, [""], x=x, y=y0 + 60)
        pre = P.add(f"prepend val {i0}", 1, 1, [""], x=x, y=y0 + 120)
        P.wire(pin, ch, pa, 0)
        P.wire(tog, 1, pa, 0)
        P.wire(pa, 0, pre, 0)
        P.wire(pre, 0, js, 0)
    # raw RMS per channel
    meter(pin, 0, 4, "rms", 360)
    meter(pin, 1, 5, "rms", 420)
    # mid, side, L*R
    add = P.add("+~", 2, 1, x=480, y=y0)
    sub = P.add("-~", 2, 1, x=540, y=y0)
    mid = P.add("*~ 0.5", 2, 1, x=480, y=y0 + 30)
    side = P.add("*~ 0.5", 2, 1, x=540, y=y0 + 30)
    lr = P.add("*~", 2, 1, x=600, y=y0 + 30)
    for b in (add, sub, lr):
        P.wire(pin, 0, b, 0)
        P.wire(pin, 1, b, 1)
    P.wire(add, 0, mid, 0)
    P.wire(sub, 0, side, 0)
    meter(mid, 0, 6, "rms", 480)
    meter(side, 0, 7, "rms", 540)
    meter(lr, 0, 8, "bipolar", 600)
    # below 120 Hz: L, R and L*R
    cl, cr = P.add("cross~ 120", 2, 2, x=660, y=y0), P.add("cross~ 120", 2, 2, x=720, y=y0)
    P.wire(pin, 0, cl, 0)
    P.wire(pin, 1, cr, 0)
    llr = P.add("*~", 2, 1, x=780, y=y0 + 30)
    P.wire(cl, 0, llr, 0)
    P.wire(cr, 0, llr, 1)
    meter(cl, 0, 9, "rms", 660)
    meter(cr, 0, 10, "rms", 720)
    meter(llr, 0, 11, "bipolar", 780)
    # 8 bands of the mid signal: a chain of crossovers
    src, so = mid, 0
    for k, f in enumerate(SPLITS):
        c = P.add(f"cross~ {f}", 2, 2, x=840 + 60 * k, y=y0)
        P.wire(src, so, c, 0)
        meter(c, 0, 12 + k, "rms", 840 + 60 * k)
        src, so = c, 1
    meter(src, so, 19, "rms", 840 + 60 * 7)

    for name, label, kind, spec, x, y in CONTROLS[mode]:
        control(P, thisdev, js, name, label, kind, spec, x, y)
    if mode == "main":
        # chords: typed in the device, kept by the app
        P.n += 1
        te = f"obj-{P.n}"
        P.boxes.append({"box": {"id": te, "maxclass": "textedit", "numinlets": 1, "numoutlets": 4,
                                "outlettype": ["", "int", "", ""], "parameter_enable": 0, "keymode": 1,
                                "patching_rect": [900.0, 520.0, 200.0, 22.0], "presentation": 1,
                                "presentation_rect": [312.0, 132.0, 318.0, 22.0], "fontsize": 10.0,
                                "text": "", "hint": "chords, e.g. | Am | F | C | G |  (Enter)"}})
        P.n += 1
        P.boxes.append({"box": {"id": f"obj-{P.n}", "maxclass": "live.comment", "numinlets": 1, "numoutlets": 0,
                                "patching_rect": [900.0, 500.0, 90.0, 18.0], "presentation": 1,
                                "presentation_rect": [312.0, 118.0, 200.0, 14.0], "text": "Chords (Enter to save)"}})
        rt = P.add("route text", 1, 2, ["", ""], x=900, y=560)
        pc = P.add("prepend chords", 1, 1, [""], x=900, y=590)
        P.wire(te, 0, rt, 0)
        P.wire(rt, 0, pc, 0)
        P.wire(rt, 1, pc, 0)
        P.wire(pc, 0, js, 0)
        P.wire(route, 3, te, 0)            # chords saved earlier come back as "set ..."
        rec = P.add("sfrecord~ 2", 2, 1, ["signal"], x=1000, y=620)
        P.wire(pin, 0, rec, 0)
        P.wire(pin, 1, rec, 1)
        P.wire(route, 4, rec, 0)
        # the mastering chain column: Build chain / Match target / Save (hypnomix/app/masterchain.py)
        from hypnomix.app import masterchain as MC
        by_text = {b["box"].get("text"): b["box"]["id"] for b in P.boxes if b["box"].get("text")}
        MC.add_to_patch(P, thisdev, [by_text["prepend val 0"], by_text["prepend val 1"]], dl,
                        [by_text[f"prepend param hm_{n}"] for n in ("target", "ceiling", "mode")])

    p["boxes"] = keep + P.boxes
    p["lines"] = P.lines                   # plugin~ → gain → plugout~ replaces the direct wires
    p["openinpresentation"] = 1
    p["devicewidth"] = float(W[mode])
    p["description"] = ("HypnoMix main: the song card (genre, key, chords, loudness), a mastering chain of Live's own devices "
                        "(built, saved and loudness-matched from here) and record-and-review before export; audio passes through" if mode == "main" else
                        "HypnoMix probe: measures this track (after its devices) and says what it is; audio passes through")
    return patch


def build(out, tpl=None):
    from hypnomix.app.device import template, read_amxd, write_amxd
    tpl = Path(tpl) if tpl else template()
    if not tpl or not tpl.exists():
        raise FileNotFoundError("could not find Live's blank Max Audio Effect (is Ableton Live with Max for Live installed?); "
                                "pass --template PATH to a 'Max Audio Effect.amxd'")
    head, patch = read_amxd(tpl)
    out = Path(out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    import copy as _copy
    from hypnomix.app import masterchain as MC
    probe_js, master_js = script(), MC.script(app_port())                   # both scripts made before anything is written
    (out / "hypnomix_probe.js").write_text(probe_js, encoding="utf-8")      # UTF-8: Max reads the scripts as UTF-8
    (out / "hypnomix_master.js").write_text(master_js, encoding="utf-8")
    write_amxd(out / "HypnomixProbe.amxd", head, build_patch(_copy.deepcopy(patch), "track"))
    write_amxd(out / "HypnomixMain.amxd", head, build_patch(_copy.deepcopy(patch), "main"))
    return out


def script():
    menus = {n: list(spec) for m in CONTROLS.values() for n, _, k, spec, _, _ in m if k == "menu"}
    return (JS.replace("__APP__", str(app_port())).replace("__W__", str(JW)).replace("__H__", str(H))
            .replace("__NV__", str(NV)).replace("__MENUS__", json.dumps(menus))
            .replace("__LABELS__", json.dumps({lab: n for m in CONTROLS.values() for n, lab, _, _, _, _ in m})))


def signature(names):
    """The song, recognised by its track names: FNV-1a of the sorted names (the device computes the same)."""
    h = 0x811c9dc5
    for ch in "\n".join(sorted(names)):
        for b in [ord(ch)] if ord(ch) < 0x10000 else [0xD800 + ((ord(ch) - 0x10000) >> 10), 0xDC00 + ((ord(ch) - 0x10000) & 0x3FF)]:
            h ^= b
            h = (h * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def read_cards(set_path, cards_file=None):
    """What the person told HypnoMix in Live, read from the saved set: per track (role, priority, protect) and the
    song card on Main (genre, key, scale, limiter, target, ceiling, amount), plus chords kept by the app."""
    if str(set_path).lower().endswith(".rpp"):    # REAPER: the HypnoMix Probe / Main JSFX menus in the project
        from hypnomix.reaper.probes import read_cards as rpp_cards
        cf = Path(cards_file) if cards_file else Path(os.environ.get("HYPNOMIX_APP_HOME", "~/Documents/Hypnomix")).expanduser() / "cards.json"
        return rpp_cards(set_path, cf)
    import xml.etree.ElementTree as ET
    from hypnomix.core.gz import read_gz
    root = ET.fromstring(read_gz(set_path))            # capped: a crafted set cannot unpack without limit
    out = {"tracks": {}, "song": {}}
    names = []
    for t in root.iter():
        if t.tag not in ("AudioTrack", "MidiTrack", "GroupTrack", "ReturnTrack", "MainTrack", "MasterTrack"):
            continue
        nm = "Main" if t.tag in ("MainTrack", "MasterTrack") else (
            (t.find("./Name/UserName").get("Value") if t.find("./Name/UserName") is not None else "")
            or (t.find("./Name/EffectiveName").get("Value") if t.find("./Name/EffectiveName") is not None else t.tag))
        if t.tag in ("AudioTrack", "MidiTrack", "GroupTrack"):
            names.append(nm)
        vals = {}
        for d in t.iter():
            if not d.tag.startswith("MxDevice"):
                continue
            for e in d.iter():
                if e.tag not in ("MxDEnumParameter", "MxDFloatParameter", "MxDIntParameter"):
                    continue
                n = e.find("./Name")
                if n is None or not (n.get("Value") or "").startswith("hm_"):
                    continue
                m = e.find("./Timeable/Manual")
                if m is None:
                    continue
                v = float(m.get("Value"))
                if e.tag == "MxDEnumParameter":
                    lab = [x.find("./Name").get("Value") for x in e.findall("./Names/Name")]
                    v = lab[int(v)] if 0 <= int(v) < len(lab) else int(v)
                vals[n.get("Value")[3:]] = v
        if vals:
            (out["song"] if nm == "Main" else out["tracks"].setdefault(nm, {})).update(vals)
    out["signature"] = signature(names)
    cf = Path(cards_file) if cards_file else Path(os.environ.get("HYPNOMIX_APP_HOME", "~/Documents/Hypnomix")).expanduser() / "cards.json"
    if cf.exists():
        card = json.loads(cf.read_text(encoding="utf-8")).get(out["signature"], {})
        if card.get("chords"):
            out["song"]["chords"] = card["chords"]
    s = out["song"]
    if s.get("key") and s["key"] != "not set":
        s["key_name"] = key_name(s["key"], s.get("scale", "major"))
    return out


MODES = {"major": 0, "dorian": 2, "phrygian": 4, "lydian": 5, "mixolydian": 7, "minor": 9, "locrian": 11}
NOTES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def key_name(root, scale):
    """A key the tuning tools understand ("A minor", "Eb major"): a mode becomes the major key with the same notes."""
    if scale in ("major", "minor"):
        return f"{root} {scale}"
    i = NOTES.index(root)
    return f"{NOTES[(i - MODES[scale]) % 12]} major"


# ---------------------------------------------------------------- receiving
class Hub:
    """Collects probe blocks from every track. Thread-safe; used by the app and by `probe listen`."""

    def __init__(self, keep_s=3600):
        self.lock = threading.Lock()
        self.tracks = {}                  # id -> dict(name, main, sr, blocks: deque of (t, beat, playing, fader, pan, vals))
        self.keep = int(keep_s * 10)
        self.capture = None               # dict(started, label, blocks: {id: [...]}) while recording
        self.gain = {}                    # probe id -> dB the probe should apply (A/B loudness match)
        self.server = None
        self.meta = {}                    # id -> dict(name, main, sig, params, chords, at)
        self.on_record = None             # REAPER's Record and review: fn(event, reaper client), set by the app

    def on_meta(self, tid, name, main, sig, params, chords=""):
        try:
            pr = json.loads(params) if params else {}
        except ValueError:
            pr = {}
        with self.lock:
            self.meta[int(tid)] = dict(name=str(name), main=bool(main), sig=str(sig), params=pr, chords=str(chords), at=time.time())

    def song_card(self):
        """Everything the devices say right now: the song card from Main and what each track is."""
        with self.lock:
            m = {k: dict(v) for k, v in self.meta.items() if time.time() - v["at"] < 30}
        main = next((v for v in m.values() if v["main"]), {})
        return dict(sig=main.get("sig", ""), song=dict(main.get("params", {}), chords=main.get("chords", "")),
                    tracks={v["name"]: v["params"] for v in m.values() if not v["main"]})

    def on_block(self, tid, name, main, beat, playing, fader, pan, sr, *vals):
        if len(vals) < NV:
            return
        b = (time.time(), float(beat), int(playing), float(fader), float(pan), [float(x) for x in vals[:NV]])
        with self.lock:
            t = self.tracks.setdefault(int(tid), dict(name=str(name), main=bool(main), sr=sr, blocks=deque(maxlen=self.keep)))
            t.update(name=str(name), main=bool(main), sr=sr)
            t["blocks"].append(b)
            if self.capture is not None:
                self.capture["tracks"].setdefault(str(int(tid)), dict(name=str(name), main=bool(main), blocks=[]))
                c = self.capture["tracks"][str(int(tid))]
                c["name"] = str(name)
                c["blocks"].append([round(b[0] - self.capture["started"], 3), round(b[1], 4), b[2], round(b[3], 2),
                                    round(b[4], 3)] + [float(f"{x:.6g}") for x in b[5]])

    def start(self, port=None):
        port = port or probe_port()
        self.port = port
        from pythonosc.dispatcher import Dispatcher
        from pythonosc.osc_server import ThreadingOSCUDPServer
        d = Dispatcher()
        d.map("/hm/probe", lambda addr, *a: self.on_block(*a))
        d.map("/hm/meta", lambda addr, *a: self.on_meta(*a))
        try:
            self.server = ThreadingOSCUDPServer(("127.0.0.1", port), d)
        except OSError as e:
            raise OSError(f"{e.strerror or e} on port {port}; the environment variable HYPNOMIX_PROBE_PORT "
                          "changes the port (the devices made afterwards send to it)") from e
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        try:                              # REAPER's probes (JSFX) arrive through the HypnoMix bridge, not UDP
            from hypnomix.reaper.probes import feed
            feed(self)
        except Exception:
            pass
        return self

    def status(self, window_s=3.0):
        now = time.time()
        out = []
        with self.lock:
            for tid, t in self.tracks.items():
                bl = [b for b in t["blocks"] if now - b[0] < window_s]
                last = t["blocks"][-1][0] if t["blocks"] else 0
                row = dict(id=tid, name=t["name"], main=t["main"], live=now - last < 1.5, seen=round(now - last, 1),
                           card=self.meta.get(tid, {}).get("params", {}))
                if bl:
                    v = [b[5] for b in bl]
                    row.update(momentary=lufs_of(v[-4:]), short=lufs_of(v[-30:]), peak=db(max(max(x[2], x[3]) for x in v)),
                               fader=bl[-1][3], bands=band_db([x[12:20] for x in v]), corr=corr_of(v),
                               playing=bool(bl[-1][2]), beat=bl[-1][1])
                out.append(row)
        out.sort(key=lambda r: (not r["main"], r["name"].lower()))
        return out

    def begin(self, label=""):
        with self.lock:
            self.capture = dict(started=time.time(), label=label, fields=["t", "beat", "playing", "fader", "pan"] + FIELDS,
                                tracks={})

    def end(self, out_dir, song=""):
        with self.lock:
            cap, self.capture = self.capture, None
        if cap is None:
            raise RuntimeError("not recording")
        cap.update(ended=time.time(), song=song, card=self.song_card())
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        f = out_dir / f"capture-{time.strftime('%Y%m%d-%H%M%S')}{('-' + safe(cap['label'])) if cap['label'] else ''}.json"
        f.write_text(json.dumps(cap), encoding="utf-8")
        return f

    def last_main(self, since):
        """Main's blocks (values) after wall-clock `since`, playing only."""
        with self.lock:
            for t in self.tracks.values():
                if t["main"]:
                    return [b for b in t["blocks"] if b[0] >= since and b[2]]
        return []


def safe(s):
    return re.sub(r"[^\w.-]+", "-", str(s)).strip("-")[:40]


# ---------------------------------------------------------------- numbers
def db(x, floor=-120.0):
    return round(20 * math.log10(x), 2) if x > 0 else floor


def lufs_of(vals):
    """Loudness of a run of blocks (ungated): -0.691 + 10 log10(mean(msL + msR))."""
    if not vals:
        return -120.0
    ms = sum(v[0] ** 2 + v[1] ** 2 for v in vals) / len(vals)
    return round(-0.691 + 10 * math.log10(ms), 2) if ms > 0 else -120.0


def integrated(vals):
    """BS.1770 gating on 400 ms windows (4 blocks, 75 % overlap): -70 LUFS absolute, then -10 LU relative."""
    if len(vals) < 4:
        return lufs_of(vals)
    ms = [v[0] ** 2 + v[1] ** 2 for v in vals]
    win = [sum(ms[i:i + 4]) / 4 for i in range(0, len(ms) - 3)]
    lk = lambda m: -0.691 + 10 * math.log10(m) if m > 0 else -200
    g1 = [m for m in win if lk(m) > -70]
    if not g1:
        return -120.0
    rel = lk(sum(g1) / len(g1)) - 10
    g2 = [m for m in g1 if lk(m) > rel]
    return round(lk(sum(g2) / len(g2)), 2) if g2 else -120.0


def short_term(vals):
    return [lufs_of(vals[i:i + 30]) for i in range(0, max(1, len(vals) - 29), 5)]


def band_db(bands_rows):
    """Average energy per band (dB, absolute) over the rows."""
    if not bands_rows:
        return [-120.0] * 8
    return [db(math.sqrt(sum(r[k] ** 2 for r in bands_rows) / len(bands_rows))) for k in range(8)]


def corr_of(vals, i=(4, 5, 8)):
    num = sum(v[i[2]] for v in vals) / len(vals)
    den = math.sqrt((sum(v[i[0]] ** 2 for v in vals) / len(vals)) * (sum(v[i[1]] ** 2 for v in vals) / len(vals)))
    return round(num / den, 3) if den > 1e-12 else None


# ---------------------------------------------------------------- the report
ROLE_ORDER = ["lead", "kick", "snare", "bass", "drums", "vocal", "harmony", "guitar", "keys", "synth", "strings", "pad", "fx"]


def role(name):
    if name in TOLD:
        return TOLD[name]
    n = name.lower()
    pats = [("lead", r"\blead\b|lead vo|main vo"), ("harmony", r"harm|bgv|backing|double|dbl|choir|\bbv"),
            ("vocal", r"vox|vocal|voice|sing"), ("kick", r"kick|\bkik|\bbd\b"), ("snare", r"snare|\bsd\b|clap"),
            ("bass", r"bass|\bsub\b|808"), ("drums", r"drum|perc|hat|cymbal|overhead|\boh\b|tom|room|loop"),
            ("guitar", r"gtr|guitar|acoustic"), ("keys", r"key|piano|rhodes|organ|wurl"), ("synth", r"synth|lead syn|arp"),
            ("strings", r"string|violin|cello|viola"), ("pad", r"pad|atmos|drone"), ("fx", r"fx|riser|sweep|noise|impact")]
    for r, p in pats:
        if re.search(p, n):
            return r
    return "other"


CARD_ROLE = {"lead vocal": "lead", "harmony": "harmony", "double": "harmony", "backing vocals": "harmony", "kick": "kick",
             "snare": "snare", "drums": "drums", "percussion": "drums", "bass": "bass", "guitar": "guitar",
             "acoustic guitar": "guitar", "piano": "keys", "keys": "keys", "synth": "synth", "strings": "strings",
             "pad": "pad", "brass": "keys", "fx": "fx", "other": "other"}
TOLD = {}                                 # track name -> role told in Live (filled per report)


def rank(name):
    r = role(name)
    return ROLE_ORDER.index(r) if r in ROLE_ORDER else len(ROLE_ORDER)


def analyse(cap, prefs=None, target=None, bpb=4):
    """Findings from a capture. `target`: 8 band levels (relative dB) for Main from `tonal`, optional."""
    prefs = prefs or {}
    TOLD.clear()
    for n, v in ((cap.get("card") or {}).get("tracks") or {}).items():
        if v.get("role") in CARD_ROLE:
            TOLD[n] = CARD_ROLE[v["role"]]
    pri = {n: str(v.get("priority", "normal")) for n, v in ((cap.get("card") or {}).get("tracks") or {}).items()}
    tg = (prefs.get("targets") or {})
    t_lufs, t_tp = float(tg.get("lufs", -14)), float(tg.get("true_peak", -1))
    tracks = {}
    for tid, t in cap["tracks"].items():
        rows = [r for r in t["blocks"] if r[2]]                       # playing only
        if len(rows) < 10:
            continue
        tracks[tid] = dict(name=t["name"], main=t.get("main", False), rows=rows, vals=[r[5:] for r in rows],
                           beats=[r[1] for r in rows], fader=rows[-1][3])
    F = []
    n = 0

    def add(**f):
        nonlocal n
        n += 1
        f.setdefault("id", f"live-{n}")
        f.setdefault("tool", "probe")
        f.setdefault("group", "live")
        f.setdefault("applies", "manual")
        F.append(f)

    def bars(b0, b1):
        return f"bars {int(b0 // bpb) + 1}-{int(b1 // bpb) + 1}"

    main = next((t for t in tracks.values() if t["main"]), None)
    span = ""
    if main:
        span = bars(min(main["beats"]), max(main["beats"]))
        L = integrated(main["vals"])
        st = short_term(main["vals"])
        pk = db(max(max(v[2], v[3]) for v in main["vals"]))
        if pk > t_tp:
            add(kind="peak", severity="high" if pk > 0 else "medium", track="Main", where=span,
                problem=f"Main peaks at {pk:+.1f} dBFS (sample peak; true peak is higher) against your ceiling of {t_tp:+.1f} dBTP.",
                fix=f"Lower the limiter ceiling or the gain into it by about {pk - t_tp + 0.3:.1f} dB, then check a bounce "
                    f"with `hypnomix measure` (true peak).", value=pk)
        if abs(L - t_lufs) > 1.0:
            add(kind="loudness", severity="low", track="Main", where=span,
                problem=f"Main measured {L:.1f} LUFS over what was played (target {t_lufs:.0f}); loudest 3 s {max(st):.1f} LUFS.",
                fix=("Turn the limiter's gain " + ("up" if L < t_lufs else "down") + f" by about {abs(L - t_lufs):.1f} dB "
                     "(only if what you played is representative of the song)."), value=L)
        lc = corr_of(main["vals"], (9, 10, 11))
        if lc is not None and lc < 0.8 and db(math.sqrt(sum(v[9] ** 2 for v in main["vals"]) / len(main["vals"]))) > -40:
            add(kind="low-end-mono", severity="medium" if lc < 0.5 else "low", track="Main", where=span,
                problem=f"The low end (below 120 Hz) is not mono on Main: L/R correlation {lc:.2f} (1.0 = mono).",
                fix="Find the wide bass part (a stereo bass or synth, a widened kick) and make it mono below 120 Hz with "
                    "Utility (Bass Mono) on that track, or on Main as a last resort.", value=lc)
        c = corr_of(main["vals"])
        if c is not None and c < 0.2:
            add(kind="width", severity="medium", track="Main", where=span,
                problem=f"The mix is very wide or out of phase: L/R correlation {c:.2f}. It will lose parts in mono.",
                fix="Check `hypnomix translate` on a bounce (mono); look for a track with its polarity flipped or a wide effect.",
                value=c)
        if target:
            mb = band_db([v[12:20] for v in main["vals"]])
            tot = 10 * math.log10(sum(10 ** (x / 10) for x in mb) or 1e-12)
            rel = [x - tot for x in mb]
            gaps = [(rel[k] - target[k], k) for k in range(8)]
            med = sorted(g for g, _ in gaps)[4]
            for g, k in gaps:
                g -= med
                if abs(g) > 2.0:
                    add(kind="tonal", severity="low", track="Main", where=span,
                        problem=f"{BANDS[k][0]} ({BANDS[k][1]}-{BANDS[k][2]} Hz) is {abs(g):.1f} dB "
                                f"{'over' if g > 0 else 'under'} your tonal target.",
                        fix=f"{'Cut' if g > 0 else 'Boost'} about {min(abs(g), 3):.1f} dB around there on the part that "
                            "carries that band (or gently on Main).", value=round(g, 1))

    # tracks: clipping into the next device, frequency fights, vocal level by section
    tl = [t for t in tracks.values() if not t["main"]]
    for t in tl:
        pk = db(max(max(v[2], v[3]) for v in t["vals"]))
        if pk > 0:
            add(kind="track-peak", severity="low", track=t["name"], where=bars(min(t["beats"]), max(t["beats"])),
                problem=f"{t['name']} peaks at {pk:+.1f} dBFS after its devices. Live doesn't clip inside a track, but a "
                        "plug-in that models hardware after it (or a bounce of the track) will.",
                fix=f"Turn the last device's output (or a Utility at the end) down by {pk + 3:.0f} dB and the fader up by the same.",
                value=pk)
    # masking: for each 100 ms block shared by two tracks
    by_time = {}
    for tid, t in tracks.items():
        if t["main"]:
            continue
        for r in t["rows"]:
            by_time.setdefault(round(r[0], 1), {})[tid] = r[5 + 12:5 + 20]
    pairs = {}
    for slot in by_time.values():
        if len(slot) < 2:
            continue
        ids = sorted(slot)
        lvl = {i: [db(x) + tracks[i]["fader"] for x in slot[i]] for i in ids}
        top = [max(lvl[i][k] for i in ids) for k in range(8)]
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                A, B = ids[a], ids[b]
                key = (A, B)
                e = pairs.setdefault(key, dict(both=0, band=[0] * 8))
                if max(lvl[A]) < -60 or max(lvl[B]) < -60:
                    continue
                e["both"] += 1
                for k in range(1, 7):             # sub and air: not fights anyone hears as "mud"
                    la, lb = lvl[A][k], lvl[B][k]
                    if la > -50 and lb > -50 and abs(la - lb) < 6 and min(la, lb) > top[k] - 9:
                        e["band"][k] += 1
    fights = []
    for (A, B), e in pairs.items():
        if e["both"] < 30:
            continue
        k = max(range(8), key=lambda j: e["band"][j])
        frac = e["band"][k] / e["both"]
        if frac >= 0.3:
            fights.append((frac, A, B, k, e["both"]))
    fights.sort(reverse=True)
    for frac, A, B, k, both in fights[:10]:
        na, nb = tracks[A]["name"], tracks[B]["name"]
        give, keep = (nb, na) if rank(na) <= rank(nb) else (na, nb)
        pa, pb = pri.get(na, "normal"), pri.get(nb, "normal")
        if pa.startswith("background") or pb.startswith("focus"):
            give, keep = na, nb
        elif pb.startswith("background") or pa.startswith("focus"):
            give, keep = nb, na
        lo, hi = BANDS[k][1], BANDS[k][2]
        f0 = int(math.sqrt(lo * hi))
        add(kind="masking", severity="medium" if frac >= 0.5 else "low", track=give, where=f"{BANDS[k][0]} {lo}-{hi} Hz",
            problem=f"{na} and {nb} sit on top of each other in the {BANDS[k][0]} band ({lo}-{hi} Hz) "
                    f"{frac:.0%} of the time they play together (measured after their plug-ins).",
            fix=f"Give {keep} the room: on {give}, EQ Eight bell around {f0} Hz, -2 to -3 dB, Q 1.0 "
                f"(or a dynamic cut keyed from {keep}).", value=round(frac, 2), other=keep)
    # vocal vs band, by 8-bar section
    leads = [t for t in tl if role(t["name"]) == "lead"] or [t for t in tl if role(t["name"]) == "vocal"]
    if main and leads:
        ld = max(leads, key=lambda t: len(t["rows"]))
        sec = 8 * bpb
        def by_sec(t):
            out = {}
            for r in t["rows"]:
                out.setdefault(int(r[1] // sec), []).append(r[5:])
            return out
        ls, ms = by_sec(ld), by_sec(main)
        diffs = {}
        for s, v in ls.items():
            if s in ms and len(v) >= 20:
                lv = lufs_of(v) + ld["fader"]
                if lv > -50:
                    diffs[s] = lv - lufs_of(ms[s])
        if len(diffs) >= 3:
            med = sorted(diffs.values())[len(diffs) // 2]
            for s, d in sorted(diffs.items()):
                if abs(d - med) > 2.0:
                    add(kind="vocal-balance", severity="medium" if abs(d - med) > 3 else "low", track=ld["name"],
                        where=bars(s * sec, s * sec + sec - 1),
                        problem=f"The lead vocal is {abs(d - med):.1f} dB {'louder' if d > med else 'quieter'} against the band "
                                f"here than in the rest of the song.",
                        fix=f"A volume ride of about {med - d:+.1f} dB on {ld['name']} over these bars (or check what the band "
                            "does here).", value=round(d - med, 1))
    sev = {"high": 0, "medium": 1, "low": 2, "info": 3}
    F.sort(key=lambda f: sev.get(f.get("severity"), 4))
    for i, f in enumerate(F, 1):
        f["n"] = i
    return F, tracks


def card_prefs(prefs, card):
    """The song card typed in Live wins over the saved preferences for this song."""
    import copy as _c
    pr = _c.deepcopy(prefs or {})
    song = (card or {}).get("song", {})
    tg = pr.setdefault("targets", {})
    if isinstance(song.get("target"), (int, float)):
        tg["lufs"] = song["target"]
    if isinstance(song.get("ceiling"), (int, float)):
        tg["true_peak"] = song["ceiling"]
    prot = [n for n, v in (card or {}).get("tracks", {}).items() if str(v.get("protect", "off")).startswith("on")]
    if prot:
        pt = pr.setdefault("protect", {})
        have = pt.get("tracks") or []
        pt["tracks"] = sorted(set(have if isinstance(have, list) else str(have).split(",")) | set(prot))
    return pr


def master_findings(wav, prefs, n0=0):
    """The recorded master, checked before export: loudness and true peak against the targets."""
    from hypnomix.core import dsp
    y, sr = dsp.load(str(wav))
    tg = (prefs or {}).get("targets", {})
    t_lufs, t_tp = float(tg.get("lufs", -14)), float(tg.get("true_peak", -1))
    L, tp = dsp.lufs(y, sr), dsp.true_peak(y, sr)
    F = []
    if tp > t_tp:
        F.append(dict(kind="true-peak", severity="high" if tp > 0 else "medium", track="Main", where="",
                      problem=f"The recorded master reaches {tp:+.2f} dBTP (true peak) against your ceiling of {t_tp:+.1f}.",
                      fix=f"Lower the limiter ceiling by {tp - t_tp + 0.1:.1f} dB (codecs add peaks on top: -1 dBTP is safe).",
                      value=round(tp, 2)))
    if abs(L - t_lufs) > 0.5:
        F.append(dict(kind="loudness", severity="medium" if abs(L - t_lufs) > 2 else "low", track="Main", where="",
                      problem=f"The recorded master is {L:.1f} LUFS integrated; the song card asks for {t_lufs:.1f}.",
                      fix=f"Limiter gain {'up' if L < t_lufs else 'down'} by {abs(L - t_lufs):.1f} dB, then record again.",
                      value=round(L, 2)))
    for i, f in enumerate(F, 1):
        f.update(id=f"export-{n0 + i}", tool="probe", group="live", applies="manual")
    return F, dict(lufs=round(L, 2), true_peak=round(tp, 2), seconds=round(len(y) / sr, 1))


def report(capture, out_dir, set_path="", bpb=4, target_name=None, mix=None):
    from hypnomix.workflow import prefs as P, scan as S
    cap = json.loads(Path(capture).read_text(encoding="utf-8"))
    card = cap.get("card") or {}
    prefs = card_prefs(P.load(), card)
    target = None
    if target_name:
        try:
            from hypnomix.ears import tonal
            target = tonal.target_bands(target_name)
        except Exception as e:                    # the tonal module is optional here
            print(f"(no tonal target: {e})")
    F, tracks = analyse(cap, prefs, target, bpb)
    od = Path(out_dir)
    (od / "raw").mkdir(parents=True, exist_ok=True)
    notes = [f"Measured live by the probe: {len(tracks)} tracks over {cap.get('ended', 0) - cap.get('started', 0):.0f} s "
             "of playback. Tracks are measured after their devices, before the fader (the fader is added)."]
    song = card.get("song") or {}
    told = {k: v for k, v in song.items() if v not in ("", "not set", None)}
    if told:
        notes.append("Song card from Live: " + ", ".join(f"{k} {v}" for k, v in told.items()))
    roles = {n: v.get("role") for n, v in (card.get("tracks") or {}).items() if v.get("role") not in (None, "auto")}
    if roles:
        notes.append("Told in Live: " + ", ".join(f"{n} = {r}" for n, r in sorted(roles.items())))
    if not any(t["main"] for t in tracks.values()):
        notes.append("WARNING: no probe on Main, so loudness, peak and tone of the mix were not checked.")
    if mix and Path(mix).exists():
        mf, m = master_findings(mix, prefs, len(F))
        F = mf + F
        for i, f in enumerate(F, 1):
            f["n"] = i
        notes.insert(0, f"Recorded master: {Path(mix).name}, {m['seconds']:.0f} s, {m['lufs']} LUFS, {m['true_peak']:+} dBTP. "
                        "It is what Live played (a real-time bounce): use it as the mix for `master`, `qc` and `translate`.")
    (od / "findings.json").write_text(json.dumps({"set": set_path, "notes": notes, "findings": F}, indent=1), encoding="utf-8")
    # as a group too, so a later `master --plan` (or any merge into this folder) keeps these findings
    (od / "live.json").write_text(json.dumps({"group": "live", "set": set_path, "seconds": cap.get("ended", 0) - cap.get("started", 0),
                                              "findings": F, "notes": notes}, indent=1), encoding="utf-8")
    (od / "scan.json").write_text(json.dumps({"mode": "live", "capture": str(Path(capture).resolve()), "card": card,
                                              "mix": str(mix or ""), "set": set_path,
                                              "at": time.strftime("%Y-%m-%d %H:%M")}, indent=1), encoding="utf-8")
    S.write_review(od, set_path, F, notes, {"live": cap.get("ended", 0) - cap.get("started", 0)}, P.summary(prefs))
    return F


# ---------------------------------------------------------------- putting probes into a new set
def library_dir():
    """Live's User Library on this computer (where `hypnomix device` writes the devices)."""
    from hypnomix.install import user_library
    return user_library()


DEVICES = Path("Presets/Audio Effects/Max Audio Effect/Hypnomix")     # where `hypnomix device` / `probe device` write

# How Live saves a Max for Live audio effect that comes from a file (copied from a set Live saved with the Hypnomix
# device in it): a reference to the .amxd and nothing else. Live loads the device from the file when the set opens,
# so its parameters start at their defaults (a probe at "auto", which is what a fresh probe should be).
MX_TEMPLATE = """<MxDeviceAudioEffect Id="0"><LomId Value="0" /><LomIdView Value="0" /><IsExpanded Value="true" />
<BreakoutIsExpanded Value="false" /><On><LomId Value="0" /><Manual Value="true" /><AutomationTarget Id="0">
<LockEnvelope Value="0" /></AutomationTarget><MidiCCOnOffThresholds><Min Value="64" /><Max Value="127" />
</MidiCCOnOffThresholds></On><ModulationSourceCount Value="0" /><ParametersListWrapper LomId="0" /><Pointee Id="0" />
<LastSelectedTimeableIndex Value="0" /><LastSelectedClipEnvelopeIndex Value="0" /><LastPresetRef><Value /></LastPresetRef>
<LockedScripts /><IsFolded Value="false" /><ShouldShowPresetName Value="true" /><UserName Value="" /><Annotation Value="" />
<SourceContext><Value><BranchSourceContext Id="0"><OriginalFileRef><FileRef Id="0">{fileref}</FileRef></OriginalFileRef>
<BrowserContentPath Value="" /><LocalFiltersJson Value="" /><PresetRef />
<BranchDeviceId Value="device:ableton:audiofx:MxDeviceAudioEffect?n=Max%20Audio%20Effect" /></BranchSourceContext>
</Value></SourceContext><MpePitchBendUsesTuning Value="true" /><ViewData Value="{{}}" />
<OverwriteProtectionNumber Value="3076" /><AudioOutputsListWrapper LomId="0" /><AudioInputsListWrapper LomId="0" />
<MidiOutputsListWrapper LomId="0" /><MidiInputsListWrapper LomId="0" /><PatchSlot><Value><MxPatchRef Id="0"><FileRef>
{fileref}</FileRef><LastModDate Value="{mtime}" /><SourceContext /><SampleUsageHint Value="0" /></MxPatchRef></Value>
</PatchSlot><ParameterList><ParameterList /></ParameterList><FileDropList><FileDropList /></FileDropList>
<IdRefList><IdRefList /></IdRefList><BlobSlot><Value><MxDBlob Id="1"><Blob /><HasData Value="true" /></MxDBlob></Value>
</BlobSlot><Routables><InRoutings><MxDInRoutable Id="0"><Routable><Target Value="AudioIn/None" />
<UpperDisplayString Value="No Output" /><LowerDisplayString Value="" /><MpeSettings><ZoneType Value="0" />
<FirstNoteChannel Value="1" /><LastNoteChannel Value="15" /></MpeSettings><MpePitchBendUsesTuning Value="true" />
</Routable><LomId Value="0" /></MxDInRoutable></InRoutings><OutRoutings><MxDOutRoutable Id="0"><Routable>
<Target Value="AudioOut/None" /><UpperDisplayString Value="No Output" /><LowerDisplayString Value="" /><MpeSettings>
<ZoneType Value="0" /><FirstNoteChannel Value="1" /><LastNoteChannel Value="15" /></MpeSettings>
<MpePitchBendUsesTuning Value="true" /></Routable><LomId Value="0" /></MxDOutRoutable></OutRoutings><MidiInRoutings />
<MidiOutRoutings /></Routables><MpeEnabled Value="false" /><MpeTuningEnabled Value="false" /></MxDeviceAudioEffect>"""


def device_element(name, library=None):
    """A fresh Live device entry for one of the HypnoMix devices (HypnomixProbe, HypnomixMain, Hypnomix), pointing at
    the .amxd in the User Library. Raises FileNotFoundError when the device isn't installed there."""
    import xml.etree.ElementTree as ET
    from xml.sax.saxutils import quoteattr
    lib = Path(library).expanduser() if library else library_dir()
    f = lib / DEVICES / f"{name}.amxd"
    if not f.exists():
        raise FileNotFoundError(f"{f} is not there: run `hypnomix device` and `hypnomix probe device` once to install "
                                "the devices into your Live User Library")
    rel = (DEVICES / f"{name}.amxd").as_posix()
    fileref = (f'<RelativePathType Value="6" /><RelativePath Value={quoteattr(rel)} /><Path Value={quoteattr(str(f))} />'
               '<Type Value="2" /><LivePackName Value="" /><LivePackId Value="" /><OriginalFileSize Value="0" />'
               '<OriginalCrc Value="0" /><SourceHint Value="" />')
    return ET.fromstring(MX_TEMPLATE.format(fileref=fileref, mtime=int(f.stat().st_mtime)))


def insert(set_path, out=None, include_returns=True, main=False, review=False, library=None):
    """A NEW set with HypnomixProbe on every track and return. The probe is copied from one you already put in the set,
    or made fresh from the installed device when there is none. main=True puts HypnomixMain on Main (instead of a
    probe), review=True the HypnoMix review device on Main too. Tracks that already have one are left as they are."""
    import copy, gzip
    import xml.etree.ElementTree as ET
    from hypnomix.session import automation as A
    src = Path(set_path)
    tree = A.load(src)
    root = tree.getroot()

    def is_probe(d):
        if not d.tag.startswith("MxDevice"):
            return False
        return any("HypnomixProbe" in (e.get("Value") or "") for e in d.iter() if e.tag in ("Name", "RelativePath", "Path", "UserName"))
    def is_ours(d):
        return d.tag.startswith("MxDevice") and any("HypnomixMain" in (e.get("Value") or "") for e in d.iter()
                                                   if e.tag in ("Name", "RelativePath", "Path", "UserName"))
    proto = None
    for d in root.iter():
        if is_probe(d):
            proto = d
            break
    def is_review(d):
        return d.tag.startswith("MxDevice") and any((e.get("Value") or "").endswith("/Hypnomix.amxd") or
                                                    (e.get("Value") or "") == "Hypnomix.amxd" for e in d.iter()
                                                    if e.tag in ("RelativePath", "Path"))
    try:
        if proto is None:
            proto = device_element("HypnomixProbe", library)
        made = {k: device_element(n, library) for k, n, want in (("main", "HypnomixMain", main), ("review", "Hypnomix", review))
                if want}
    except FileNotFoundError as e:
        raise RuntimeError(str(e))
    mains = list(root.iter("MainTrack")) + list(root.iter("MasterTrack"))
    lists = []
    for t in list(root.iter("AudioTrack")) + list(root.iter("MidiTrack")) + list(root.iter("GroupTrack")) + \
            (list(root.iter("ReturnTrack")) if include_returns else []) + ([] if main else mains):
        devs = t.find("./DeviceChain/DeviceChain/Devices")
        if devs is not None and not any(is_probe(d) or is_ours(d) for d in devs):
            lists.append(devs)
    extra = []                                 # (Devices, element): the review device, then HypnomixMain last on Main
    mdevs = next((t.find("./DeviceChain/DeviceChain/Devices") for t in mains), None)
    if mdevs is not None:
        if "review" in made and not any(is_review(d) for d in root.iter() if d.tag.startswith("MxDevice")):
            extra.append((mdevs, made["review"]))
        if "main" in made and not any(is_ours(d) for d in mdevs):
            extra.append((mdevs, made["main"]))
    npi = root.find(".//NextPointeeId")
    nxt = int(npi.get("Value"))

    def renumber(new, devs):
        nonlocal nxt
        for e in new.iter():
            if (e.tag.endswith("Target") or e.tag == "Pointee") and (e.get("Id") or "").isdigit():
                e.set("Id", str(nxt))
                nxt += 1
        used = [int(d.get("Id")) for d in devs if (d.get("Id") or "").isdigit()]
        new.set("Id", str(max(used) + 1 if used else 0))
        devs.append(new)
    for devs, el in extra:
        renumber(el, devs)
    for devs in lists:
        new = copy.deepcopy(proto)
        for e in new.iter():                  # each copy starts at "auto": what the first track was told is not copied
            n = e.find("./Name")
            if e.tag.startswith("MxD") and e.tag.endswith("Parameter") and n is not None and (n.get("Value") or "").startswith("hm_"):
                dflt, m = e.find("./Default"), e.find("./Timeable/Manual")
                if dflt is not None and m is not None:
                    m.set("Value", dflt.get("Value"))
        renumber(new, devs)
    npi.set("Value", str(nxt))
    if out:
        out = Path(out)
    else:                                     # never over a copy made earlier (it may have been edited since)
        tag = "hypnomix devices" if (main or review) else "probes"
        out, k = src.with_name(f"{src.stem} ({tag}).als"), 2
        while out.exists():
            out, k = src.with_name(f"{src.stem} ({tag} {k}).als"), k + 1
    if out.resolve() == src.resolve():
        raise RuntimeError("refusing to overwrite the set: choose another --out")
    A.save(tree, src, out)
    return out, len(lists) + len(extra)


# ---------------------------------------------------------------- CLI
def app_up():
    from hypnomix.core import loopback
    try:
        with loopback.urlopen(f"http://127.0.0.1:{app_port()}/api/probe/status", timeout=1) as r:      # never through a proxy variable
            r.read()
        return True
    except Exception:
        return False


def app_token():
    """The running app's page token, read from its own page the way a browser gets it (this computer only)."""
    import urllib.request
    from hypnomix.core import loopback
    with loopback.urlopen(urllib.request.Request(f"http://127.0.0.1:{app_port()}/"), timeout=10) as r:
        m = re.search(r'const TOKEN = "([^"]+)"', r.read().decode("utf-8", "replace"))
    return m.group(1) if m else ""


def app_call(path, body=None):
    import urllib.request
    from hypnomix.core import loopback
    headers = {"Content-Type": "application/json"}
    if body is not None and path in ("/api/probe/start", "/api/probe/stop"):      # the routes that need the page's token
        headers["X-Hypnomix"] = app_token()
    req = urllib.request.Request(f"http://127.0.0.1:{app_port()}{path}", data=json.dumps(body or {}).encode() if body is not None else None,
                                 headers=headers)
    with loopback.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def out_home():
    from hypnomix.core import paths
    return paths.out("probe")


def main():
    ap = argparse.ArgumentParser(prog="hypnomix probe", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("device", help="write the probe device into your Live User Library")
    d.add_argument("--out")
    d.add_argument("--template")
    i = sub.add_parser("insert", help="a new set with the HypnoMix devices on every track (no need to place one first)")
    i.add_argument("set")
    i.add_argument("--out")
    i.add_argument("--no-returns", action="store_true")
    i.add_argument("--probes-only", action="store_true", help="only the probes (a probe on Main too); no HypnomixMain, "
                   "no review device")
    s = sub.add_parser("status", help="which tracks are sending, loudness right now")
    l = sub.add_parser("listen", help="record the probes while Live plays, then write a review")
    l.add_argument("--secs", type=float, default=0, help="stop after this many seconds (default: when Live stops)")
    l.add_argument("--bars", help="A-B: with --play, play these bars in Live (AbletonOSC)")
    l.add_argument("--play", action="store_true")
    l.add_argument("--label", default="")
    l.add_argument("--set", default="", help="the Live set being played (for the review's jump links)")
    l.add_argument("--out", help="review folder to write (default hypnomix-out/scan/<label or 'live'>)")
    l.add_argument("--target", help="tonal target name from `hypnomix tonal build`")
    r = sub.add_parser("report", help="a review from a saved capture")
    r.add_argument("capture")
    r.add_argument("--out", required=True)
    r.add_argument("--set", default="")
    r.add_argument("--bpb", type=int, default=4)
    r.add_argument("--target")
    r.add_argument("--mix", help="the master recorded by HypnomixMain (Record and review)")
    c = sub.add_parser("cards", help="what was told in Live (roles, song card), read from a saved set")
    c.add_argument("set")
    ch = sub.add_parser("chains", help="the mastering chain templates HypnomixMain can build (list | show NAME | delete NAME)")
    ch.add_argument("rest", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    if a.cmd == "chains":
        from hypnomix.app import masterchain as MC
        MC.main(a.rest)
        return
    if a.cmd == "cards":
        print(json.dumps(read_cards(a.set), indent=1))
        return

    if a.cmd == "device":
        from hypnomix.install import user_library_words
        lib = library_dir()
        out = a.out or (lib / "Presets" / "Audio Effects" / "Max Audio Effect" / "Hypnomix")
        if not a.out and not lib.is_dir():
            sys.exit(f"no Live User Library at {user_library_words()}: say where to write with --out FOLDER")
        try:
            od = build(out, a.template)
        except FileNotFoundError as e:
            sys.exit(str(e))
        print(f"wrote {od / 'HypnomixProbe.amxd'}\n      {od / 'HypnomixMain.amxd'}\n      {od / 'hypnomix_probe.js'}\n"
              f"      {od / 'hypnomix_master.js'}   (keep them together)")
        print("Then `hypnomix probe insert SET.als` (or the first pass with Live devices ticked) writes a copy of the "
              "set with the devices on every track; or drag HypnomixProbe onto the LAST slot of a track yourself.")
        return
    if a.cmd == "insert":
        try:
            full = not a.probes_only
            out, n = insert(a.set, a.out, not a.no_returns, main=full, review=full)
        except RuntimeError as e:
            sys.exit(str(e))
        from hypnomix.session import check as C
        print(f"wrote {out}: {n} device(s) added (" + ("HypnomixProbe on every track and return, the review device "
              "and HypnomixMain on Main" if full else "HypnomixProbe on every track, return and Main") +
              "). The original is unchanged. Open the new set in Live.")
        err, warn, _ = C.check(str(out), against=a.set)
        for e in err:
            print(f"CHECK ERROR: {e}")
        for w in warn[:6]:
            print(f"check: {w}")
        return
    if a.cmd == "status":
        rows = app_call("/api/probe/status") if app_up() else None
        if rows is None:
            hub = Hub().start()
            time.sleep(1.5)
            rows = hub.status()
        else:
            rows = rows["tracks"]
        if not rows:
            print("no probes are sending: is Live open with HypnomixProbe on your tracks?")
        for t in rows:
            seen = "live" if t["live"] else f"{t['seen']}s ago"
            print(f"{'*' if t['main'] else ' '} {t['name'][:28]:<28} {seen:<9}"
                  + (f" {t.get('momentary', -120):6.1f} LUFS-M  peak {t.get('peak', -120):6.1f}" if 'momentary' in t else ""))
        return
    if a.cmd == "report":
        od = Path(a.out)
        F = report(a.capture, od, a.set, a.bpb, a.target, a.mix)
        print(f"{len(F)} findings → {od / 'REVIEW.md'}")
        return
    # listen
    label = a.label or "live"
    od = Path(a.out) if a.out else Path("hypnomix-out") / "scan" / f"{safe(label)}-live"
    use_app = app_up()
    hub = None if use_app else Hub().start()
    live = None
    if a.play:
        from hypnomix.live.osc import Live
        live = Live()
        b0, b1 = (int(x) for x in (a.bars or "1-9").split("-"))
        live.play_from(b0, loop_bars=None)
    (app_call("/api/probe/start", {"label": label}) if use_app else hub.begin(label))
    print("recording what the probes hear" + (" (through the app)" if use_app else "") + "; Ctrl-C to stop")
    t0 = time.time()
    seen_play = False
    try:
        while True:
            time.sleep(0.5)
            el = time.time() - t0
            if a.secs and el >= a.secs:
                break
            if live and a.bars:
                b0, b1 = (int(x) for x in a.bars.split("-"))
                try:
                    if live.position() >= b1 * live.beats_per_bar():
                        break
                except Exception:
                    pass
            if not a.secs:
                rows = app_call("/api/probe/status")["tracks"] if use_app else hub.status()
                playing = any(r.get("playing") for r in rows)
                seen_play |= playing
                if seen_play and not playing:
                    break
    except KeyboardInterrupt:
        pass
    if live:
        live.stop()
    if use_app:
        cap = Path(app_call("/api/probe/stop", {"song": label})["capture"])
    else:
        cap = hub.end(out_home(), label)
    print(f"capture: {cap}")
    F = report(cap, od, a.set, 4, a.target)
    print(f"{len(F)} findings → {od / 'REVIEW.md'}")


if __name__ == "__main__":
    main()
