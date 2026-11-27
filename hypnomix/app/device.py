#!/usr/bin/env python3
"""Make the HypnoMix Max for Live device: review from inside Live, and jump Live to each finding.

  hypnomix device                 write Hypnomix.amxd + hypnomix_device.js into your Live User Library
  hypnomix device --out FOLDER    write them somewhere else

Then drag the Hypnomix device from Live's browser (User Library → Presets → Audio Effects → Max Audio Effect → Hypnomix)
onto ANY track; audio passes through it untouched. Needs Max for Live (Live Suite, or the add-on).

With the HypnoMix app running (`hypnomix app`, or the Mac app) and a review open in it, the device shows the
finding you are on and has these buttons:

  Prev / Next    step through the findings; Live jumps to each one
  Next open      the next finding you have not decided yet
  Amount         on a fix that can scale (timing nudges, tuning, levels, device settings): click to step through 25,
                 50, 75 and 100% of the proposed move. It starts at your saved preference for timing and tuning
  Approve / Skip record your decision (saved exactly like a click in the app; nothing is applied from here)
  Brace on/off   whether the Arrangement loop brace is moved around the spot
  App            open the full review (with the before / after players) in your browser
  Float          (top right) the same panel in a small floating window. Use it while stepping: a jump selects
                 the finding's track, and Live then shows that track's clip where this device was

In an A/B set (`hypnomix abset SCAN_DIR`, opened in Live instead of the original) a second row appears:

  A · now / B · fix   switch the finding's devices or tracks, instantly, with every plug-in playing
  Blind               X and Y in random order; "I like X / Y" records your choice (blind.json), then tells you
  Match on / off      with the probe on Main (`hypnomix probe`), B is turned down or up to A's loudness

"Jump" means: the finding's track is selected, the Arrangement playhead moves to the spot, the loop brace
is put around it (without switching looping on), and the clip under it opens in the Detail view. "Show in
Live" buttons in the app do the same through this device.

The device is built from the blank "Max Audio Effect" that ships inside your own copy of Live, plus one
script file. The two files must stay in the same folder. The device talks to the app on port 8791; if the app runs
on another port (`hypnomix app --port N`), set HYPNOMIX_PORT=N before `hypnomix device` so the device is written
with that port.

Loaded in Live 12 Suite on a real set: it connects, follows the review, jumps and floats. Not yet tried on a
second machine: if it shows an error, the Max window (right-click the device title → Open Max Window) says
which line.
"""
import argparse, glob, json, os, sys
from pathlib import Path

W, H = 430, 169
DEFAULT_PORT = 8791


def app_port():
    """The HypnoMix app's port the device talks to: HYPNOMIX_PORT when it is set (read each time the device is made,
    so `hypnomix app --port N` can be matched), else 8791."""
    try:
        n = int(os.environ.get("HYPNOMIX_PORT", "").strip() or DEFAULT_PORT)
        return n if 1 <= n <= 65535 else DEFAULT_PORT
    except ValueError:
        return DEFAULT_PORT


PORT = app_port()          # at import; the device is written with app_port() read again when it is made

JS = r"""// HypnoMix device (jsui): talks to the HypnoMix app on this computer and moves Live to each finding.
autowatch = 1;
inlets = 1;
outlets = 1;
mgraphics.init();
mgraphics.relative_coords = 0;
mgraphics.autofill = 0;

var BASE = "http://127.0.0.1:__PORT__";
var W = __W__, H = __H__;
var st = {ready: false, seq: -1, cur: null, lastOk: 0, flash: "", flashUntil: 0, brace: true, busy: false,
          ab: {id: "", spec: null, state: "A", blind: null, heard: {}}};
var buttons = [];
var task = new Task(tick, this);
// The same script runs twice: in the device, and in the floating panel (jsarguments "float"). Only one of the
// two moves Live: the floating one while Float is on, the device's own otherwise. Buttons work in both.
var IS_FLOAT = typeof jsarguments != "undefined" && jsarguments.length > 1 && jsarguments[1] == "float";
var floatOn = false;
function floating(v) { floatOn = v ? true : false; redraw(); }
function active() { return IS_FLOAT == floatOn; }

// Live frees the device when the set closes or the track is deleted. A timer tick or an answer from the app that
// arrives after that must not touch the freed panel (that crashed Live once): everything checks `dead` first.
var dead = false, pending = [];
function redraw() { if (!dead) mgraphics.redraw(); }

function bang() {                      // live.thisdevice: the Live API is ready now
    st.ready = true;
    task.interval = 400;
    task.repeat();
}
function loadbang() { redraw(); }
function notifydeleted() {
    dead = true;
    task.cancel();
    for (var i = 0; i < pending.length; i++) { try { pending[i].onreadystatechange = null; pending[i].abort(); } catch (e) { } }
    pending = [];
}

function now() { return new Date().getTime(); }
function connected() { return now() - st.lastOk < 2500; }
function flash(text) { st.flash = text; st.flashUntil = now() + 3500; redraw(); }

function request(method, path, body, done) {
    if (dead) return;
    var r = new XMLHttpRequest();
    pending.push(r);
    r.open(method, BASE + path);
    r.onreadystatechange = function () {
        if (this.readyState != 4) return;
        var k = pending.indexOf(this);
        if (k >= 0) pending.splice(k, 1);
        if (dead) return;
        var data = null;
        try { data = JSON.parse(this.responseText); } catch (e) { data = null; }
        if (data) st.lastOk = now();
        if (done) done(data);
    };
    if (body) r.send(JSON.stringify(body)); else r.send();
}

function tick() {
    if (dead) return;
    if (st.busy && now() - st.busyAt < 3000) return;
    st.busy = true; st.busyAt = now();
    request("GET", "/api/live/poll?since=" + st.seq, null, function (d) {
        st.busy = false;
        if (!d) { redraw(); return; }
        var first = st.seq < 0;
        if (d.cmd && !first && d.seq > st.seq && active()) run(d.cmd);
        st.seq = d.seq;
        st.cur = d.current;
        if (active()) abFollow();
        redraw();
    });
}

function run(cmd) {
    if (cmd.type == "jump") { try { jump(cmd); } catch (e) { flash("Could not jump: " + e); } }
}

function nameOf(api) { var v = api.get("name"); return (v instanceof Array) ? v.join(" ") : String(v); }

function jump(c) {
    if (!st.ready) return;
    var song = new LiveAPI("live_set");
    var n = song.getcount("tracks"), t = null, i;
    for (i = 0; i < n; i++) {
        var x = new LiveAPI("live_set tracks " + i);
        if (nameOf(x) == c.track) { t = x; break; }
    }
    if (!t) { flash("No track called \"" + c.track + "\" in this set (renamed?)"); return; }
    var view = new LiveAPI("live_set view");
    view.set("selected_track", "id", t.id);
    var app = new LiveAPI("live_app view");
    app.call("show_view", "Arranger");
    app.call("focus_view", "Arranger");
    if (c.start === undefined || c.start === null) { flash("On track " + c.track); return; }
    song.set("current_song_time", c.start);
    if (st.brace) {
        song.set("loop_start", c.start);
        song.set("loop_length", Math.max(1, c.end - c.start));
    }
    var ids = t.get("arrangement_clips");          // ["id", 12, "id", 13, ...]
    for (i = 0; ids && i + 1 < ids.length; i += 2) {
        var clip = new LiveAPI("id " + ids[i + 1]);
        var s = parseFloat(clip.get("start_time")), e = parseFloat(clip.get("end_time"));
        if (s <= c.start + 1 && e > c.start) {
            view.set("detail_clip", "id", clip.id);
            app.call("show_view", "Detail/Clip");
            break;
        }
    }
    flash("Jumped: " + c.track + ", beat " + Math.round(c.start * 100) / 100);
}

function step(delta, undecided) {
    request("POST", "/api/live/step", {delta: delta, undecided: undecided}, function (d) { if (d) st.cur = d; redraw(); tick(); });
}
function decide(what) {
    request("POST", "/api/live/decide", {decision: what}, function (d) { if (d) { st.cur = d; flash(what == "approve" ? "Approved" : "Skipped"); } });
}

// ---------------------------------------------------------------- A / B inside Live (an A/B set from `hypnomix abset`)
function findTrack(name) {
    if (name == "Main") return new LiveAPI("live_set master_track");
    var song = new LiveAPI("live_set"), n = song.getcount("tracks");
    for (var i = 0; i < n; i++) { var x = new LiveAPI("live_set tracks " + i); if (nameOf(x) == name) return x; }
    for (i = 0; i < song.getcount("return_tracks"); i++) { var r = new LiveAPI("live_set return_tracks " + i); if (nameOf(r) == name) return r; }
    return null;
}
function devOn(track, idx, on, expectB) {
    var d = new LiveAPI(track.unquotedpath + " devices " + idx);
    if (!d.id || d.id == "0") throw "device " + idx + " is missing on " + nameOf(track);
    if (expectB && nameOf(d).indexOf("B · ") != 0) throw "this is not the A/B set (open the set hypnomix abset wrote)";
    var p = new LiveAPI(track.unquotedpath + " devices " + idx + " parameters 0");     // "Device On"
    p.set("value", on ? 1 : 0);
}
function applyAB(spec, state) {
    for (var k = 0; k < spec.parts.length; k++) {
        var part = spec.parts[k], i, t;
        if (part.mode == "devices") {
            t = findTrack(part.track);
            if (!t) throw "no track called \"" + part.track + "\"";
            for (i = 0; i < part.a.length; i++) devOn(t, part.a[i], state == "A" ? part.a_on[i] : false, false);
            for (i = 0; i < part.b.length; i++) devOn(t, part.b[i], state == "B" ? part.b_on[i] : false, true);
        } else {
            for (i = 0; i < part.a.length; i++) { t = findTrack(part.a[i]); if (!t) throw "no track called \"" + part.a[i] + "\"";
                t.set("mute", state == "A" ? (part.a_on[i] ? 0 : 1) : 1); }
            for (i = 0; i < part.b.length; i++) { t = findTrack(part.b[i]); if (!t) throw "this is not the A/B set (no track \"" + part.b[i] + "\")";
                t.set("mute", state == "B" ? (part.b_on[i] ? 0 : 1) : 1); }
        }
    }
}
function setAB(state) {
    var c = st.cur;
    if (!c || !c.ab) return;
    try { applyAB(c.ab, state); } catch (e) { flash(String(e)); return; }
    st.ab.state = state; st.ab.id = c.id; st.ab.spec = c.ab;
    st.ab.heard[state] = true;
    request("POST", "/api/ab/state", {id: c.id, state: state}, function (d) {
        if (d && d.diff !== null && d.diff !== undefined) flash((st.ab.blind ? "" : state + " · ") + "levels matched (" + (d.diff > 0 ? "+" : "") + d.diff + " dB)");
    });
    redraw();
}
function abFollow() {                     // moving to another finding puts the last one back to A
    var c = st.cur;
    if (st.ab.spec && (!c || c.id != st.ab.id)) {
        try { if (st.ab.state != "A") applyAB(st.ab.spec, "A"); } catch (e) { }
        st.ab = {id: "", spec: null, state: "A", blind: null, heard: {}};
    }
}
function blind() {
    if (!st.cur || !st.cur.ab) return;
    st.ab.blind = Math.random() < 0.5 ? {X: "A", Y: "B"} : {X: "B", Y: "A"};
    st.ab.heard = {};
    setAB(st.ab.blind.X);
    flash("Blind: listen to X and Y, then choose the one you like");
}
function choose(which) {
    var b = st.ab.blind;
    if (!b) return;
    var chose = b[which];
    request("POST", "/api/ab/blind", {id: st.cur.id, chose: chose, x: b.X}, function (d) {
        flash("You chose " + which + " = " + (chose == "B" ? "B, the fix" : "A, what you have") +
              (d && d.n > 1 ? "  (B " + d.b + " of " + d.n + " times)" : ""));
    });
    st.ab.blind = null;
    redraw();
}
function match() {
    var on = !(st.cur && st.cur.match);
    request("POST", "/api/ab/state", {id: st.cur.id, state: st.ab.state, match: on}, function () { flash(on ? "Loudness match on (needs the probe on Main)" : "Loudness match off"); tick(); });
}

// ---------------------------------------------------------------- drawing
function wrap(text, width, maxLines) {
    var words = String(text || "").split(/\s+/), lines = [], line = "";
    for (var i = 0; i < words.length; i++) {
        var probe = line ? line + " " + words[i] : words[i];
        if (mgraphics.text_measure(probe)[0] > width && line) { lines.push(line); line = words[i]; } else line = probe;
        if (lines.length == maxLines) break;
    }
    if (lines.length < maxLines && line) lines.push(line);
    if (lines.length == maxLines && i < words.length - 1) lines[maxLines - 1] = lines[maxLines - 1].replace(/.{0,3}$/, "…");
    return lines;
}
function text(str, x, y, rgba, size, bold) {
    mgraphics.select_font_face(bold ? "Arial Bold" : "Arial");
    mgraphics.set_font_size(size);
    mgraphics.set_source_rgba(rgba[0], rgba[1], rgba[2], rgba[3]);
    mgraphics.move_to(x, y);
    mgraphics.show_text(String(str));
}
function button(label, x, w, on, act, row) {
    var y = H - 27 - (row ? 24 : 0), h = 20;
    mgraphics.set_source_rgba(on ? 0.56 : 0.24, on ? 0.25 : 0.24, on ? 0.25 : 0.25, 1);
    mgraphics.rectangle_rounded(x, y, w, h, 6, 6);
    mgraphics.fill();
    mgraphics.select_font_face("Arial Bold");
    mgraphics.set_font_size(10);
    var tw = mgraphics.text_measure(label)[0];
    text(label, x + (w - tw) / 2, y + 14, [0.95, 0.93, 0.89, 1], 10, true);
    buttons.push({x: x, y: y, w: w, h: h, act: act});
    return x + w + 5;
}
var SEV = {high: [1, 0.54, 0.5, 1], medium: [0.94, 0.7, 0.33, 1], low: [0.56, 0.78, 0.64, 1], info: [0.6, 0.65, 0.71, 1]};

function paint() {
    buttons = [];
    mgraphics.set_source_rgba(0.13, 0.125, 0.11, 1);
    mgraphics.rectangle(0, 0, W, H);
    mgraphics.fill();
    var ink = [0.93, 0.91, 0.87, 1], mute = [0.63, 0.6, 0.56, 1], c = st.cur, y = 16;
    text("HYPNOMIX", 8, y, ink, 10, true);
    if (!connected()) {
        text("not connected", 78, y, mute, 10, false);
        text("Start the HypnoMix app (or run: hypnomix app)", 8, 44, ink, 11, false);
        text("and open a review. This device then follows it.", 8, 60, mute, 11, false);
        button("Open app", 8, 70, false, "app");
        return;
    }
    if (!c || !c.of) {
        text("connected", 78, y, [0.5, 0.82, 0.64, 1], 10, false);
        var l = wrap(c ? c.text : "Open a review in the HypnoMix app.", W - 16, 3);
        for (var k = 0; k < l.length; k++) text(l[k], 8, 44 + k * 15, ink, 11, false);
        button("Open app", 8, 70, false, "app");
        return;
    }
    text(c.song + "  ·  " + c.n + " of " + c.of + "  ·  " + c.left + " open" + (active() ? "" : IS_FLOAT ? "  (off)" : "  ·  floating"), 78, y, mute, 10, false);
    y = 36;
    text(String(c.severity || "").toUpperCase(), 8, y, SEV[c.severity] || mute, 9, true);
    text((c.track || "") + "   " + (c.where || ""), 58, y, ink, 11, true);
    mgraphics.select_font_face("Arial"); mgraphics.set_font_size(11);
    var lines = wrap(c.problem, W - 16, c.ab ? 2 : 3), i;
    for (i = 0; i < lines.length; i++) { y += 15; text(lines[i], 8, y, ink, 11, false); }
    mgraphics.select_font_face("Arial"); mgraphics.set_font_size(10);
    var fx = wrap("Proposed: " + c.fix, W - 16, c.ab ? 1 : 2);
    y += 4;
    for (i = 0; i < fx.length; i++) { y += 13; text(fx[i], 8, y, mute, 10, false); }
    if (now() < st.flashUntil) text(st.flash, 8, c.ab ? H - 56 : H - 34, [0.5, 0.82, 0.64, 1], 10, false);
    if (c.ab) {
        var bx = 8, bl = st.ab.blind;
        if (bl) {
            bx = button("X", bx, 30, st.ab.id == c.id && st.ab.state == bl.X, "X", 1);
            bx = button("Y", bx, 30, st.ab.id == c.id && st.ab.state == bl.Y, "Y", 1);
            bx = button("I like X", bx, 58, false, "likeX", 1);
            bx = button("I like Y", bx, 58, false, "likeY", 1);
        } else {
            bx = button("A · now", bx, 56, st.ab.id != c.id || st.ab.state == "A", "A", 1);
            bx = button("B · fix", bx, 50, st.ab.id == c.id && st.ab.state == "B", "B", 1);
            bx = button("Blind", bx, 44, false, "blind", 1);
        }
        bx = button(c.match ? "Match on" : "Match off", bx, 64, c.match, "match", 1);
    }
    // how much of the proposed move this fix gets (fixes that can scale): click steps 25, 50, 75, 100%
    if (c.scalable) button("Amount " + c.amount + "%", W - 104, 96, c.amount < 100, "amount", 1);
    var x = 8;
    x = button("Prev", x, 40, false, "prev");
    x = button("Next", x, 40, false, "next");
    x = button("Next open", x, 66, false, "open");
    x = button("Approve", x, 58, c.decision == "approve", "approve");
    x = button("Skip", x, 40, c.decision == "skip", "skip");
    x = button(st.brace ? "Brace on" : "Brace off", x, 62, false, "brace");
    x = button("App", x, 36, false, "app");
}

function onclick(x, y) {
    for (var i = 0; i < buttons.length; i++) {
        var b = buttons[i];
        if (x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h) { act(b.act); return; }
    }
    if (st.cur && st.cur.jump) run({type: "jump", track: st.cur.jump.track, start: st.cur.jump.start, end: st.cur.jump.end});
}
function act(a) {
    if (a == "prev") step(-1, false);
    else if (a == "next") step(1, false);
    else if (a == "open") step(1, true);
    else if (a == "approve" || a == "skip") decide(a);
    else if (a == "amount") request("POST", "/api/live/amount", {step: 1}, function (d) { if (d && !d.error) { st.cur = d; flash("Amount " + d.amount + "% of the proposed move"); } });
    else if (a == "brace") { st.brace = !st.brace; redraw(); }
    else if (a == "app") max.launchbrowser(BASE + "/");
    else if (a == "A" || a == "B") setAB(a);
    else if (a == "X" || a == "Y") setAB(st.ab.blind[a]);
    else if (a == "likeX") choose("X");
    else if (a == "likeY") choose("Y");
    else if (a == "blind") blind();
    else if (a == "match") match();
}
"""


def template():
    hits = sorted(glob.glob("/Applications/Ableton Live*.app/Contents/App-Resources/Misc/Max Devices/Max Audio Effect.amxd")) + \
        sorted(glob.glob("C:/ProgramData/Ableton/Live*/Resources/Misc/Max Devices/Max Audio Effect.amxd"))
    return Path(hits[-1]) if hits else None


def read_amxd(path):
    b = Path(path).read_bytes()
    i = b.index(b"ptch")
    n = int.from_bytes(b[i + 4:i + 8], "little")
    return b[:i], json.loads(b[i + 8:i + 8 + n].rstrip(b"\x00").decode("utf-8"))


def write_amxd(path, head, patch):
    body = json.dumps(patch, indent="\t").encode("utf-8") + b"\n\x00"
    Path(path).write_bytes(head + b"ptch" + len(body).to_bytes(4, "little") + body)


def build_patch(patch):
    p = patch["patcher"]
    keep = [b for b in p["boxes"] if b["box"].get("text") in ("plugin~", "plugout~") or b["box"].get("text") == "Device vertical limit"]
    keep.append({"box": {"id": "obj-20", "maxclass": "newobj", "numinlets": 1, "numoutlets": 3, "outlettype": ["bang", "int", "int"],
                         "patching_rect": [160.0, 34.0, 83.0, 22.0], "text": "live.thisdevice"}})
    keep.append({"box": {"id": "obj-21", "maxclass": "jsui", "filename": "hypnomix_device.js", "border": 0, "numinlets": 1,
                         "numoutlets": 1, "outlettype": [""], "parameter_enable": 0,
                         "patching_rect": [160.0, 70.0, float(W), float(H)], "presentation": 1,
                         "presentation_rect": [0.0, 0.0, float(W), float(H)]}})
    def box(i, text, rect, nin, outs, **kw):
        return {"box": dict({"id": i, "maxclass": "newobj", "numinlets": nin, "numoutlets": len(outs), "outlettype": outs,
                             "patching_rect": rect, "text": text}, **kw)}
    def line(a, ao, b, bi=0):
        return {"patchline": {"source": [a, ao], "destination": [b, bi]}}
    # Float: a toggle (a device parameter, so it is saved with the set) opens the same panel in a floating window
    toggle = {"box": {"id": "obj-22", "maxclass": "live.text", "mode": 1, "text": "Float", "texton": "Float", "fontsize": 9.0,
                      "numinlets": 1, "numoutlets": 2, "outlettype": ["", ""], "parameter_enable": 1,
                      "patching_rect": [640.0, 34.0, 44.0, 15.0], "presentation": 1,
                      "presentation_rect": [float(W - 48), 4.0, 44.0, 15.0],
                      "saved_attribute_attributes": {"valueof": {"parameter_enum": ["off", "on"], "parameter_longname": "Float",
                                                                 "parameter_shortname": "Float", "parameter_type": 2,
                                                                 "parameter_mmax": 1, "parameter_initial_enable": 1,
                                                                 "parameter_initial": [0]}}, "varname": "Float"}}
    sub = {"fileversion": 1, "appversion": p.get("appversion", {}), "classnamespace": "box",
           "rect": [560.0, 470.0, float(W), float(H)], "toolbarvisible": 0, "enablehscroll": 0, "enablevscroll": 0,
           "gridonopen": 2, "statusbarvisible": 0, "default_fontsize": 12.0,
           "boxes": [
               {"box": {"id": "obj-1", "maxclass": "jsui", "filename": "hypnomix_device.js", "jsarguments": ["float"], "border": 0,
                        "numinlets": 1, "numoutlets": 1, "outlettype": [""], "parameter_enable": 0,
                        "patching_rect": [0.0, 0.0, float(W), float(H)]}},
               box("obj-2", "live.thisdevice", [10.0, 200.0, 83.0, 22.0], 1, ["bang", "int", "int"]),
               box("obj-3", "r ---hypnomixfloat", [110.0, 200.0, 110.0, 22.0], 0, [""]),
               box("obj-4", "loadbang", [10.0, 240.0, 58.0, 22.0], 1, ["bang"]),
               {"box": {"id": "obj-5", "maxclass": "message", "numinlets": 2, "numoutlets": 1, "outlettype": [""],
                        "patching_rect": [10.0, 270.0, 400.0, 22.0],
                        "text": "window flags float, window flags nogrow, window flags nozoom, window flags nominimize, title HypnoMix, window exec"}},
               box("obj-6", "thispatcher", [10.0, 300.0, 69.0, 22.0], 1, ["", ""], save=["#N", "thispatcher", ";", "#Q", "end", ";"]),
               {"box": {"id": "obj-7", "maxclass": "inlet", "comment": "", "index": 1, "numinlets": 0, "numoutlets": 1,
                        "outlettype": [""], "patching_rect": [240.0, 200.0, 30.0, 30.0]}}],
           "lines": [line("obj-2", 0, "obj-1"), line("obj-3", 0, "obj-1"), line("obj-4", 0, "obj-5"), line("obj-5", 0, "obj-6")]}
    extra = [toggle,
             box("obj-23", "prepend floating", [640.0, 60.0, 98.0, 22.0], 1, [""]),
             box("obj-24", "s ---hypnomixfloat", [640.0, 90.0, 110.0, 22.0], 1, []),
             box("obj-25", "r ---hypnomixfloat", [300.0, 34.0, 110.0, 22.0], 0, [""]),
             box("obj-26", "sel 1 0", [770.0, 60.0, 46.0, 22.0], 3, ["bang", "bang", ""]),
             {"box": {"id": "obj-27", "maxclass": "message", "numinlets": 2, "numoutlets": 1, "outlettype": [""],
                      "patching_rect": [770.0, 90.0, 37.0, 22.0], "text": "open"}},
             {"box": {"id": "obj-28", "maxclass": "message", "numinlets": 2, "numoutlets": 1, "outlettype": [""],
                      "patching_rect": [815.0, 90.0, 39.0, 22.0], "text": "close"}},
             box("obj-29", "pcontrol", [770.0, 120.0, 55.0, 22.0], 1, [""]),
             box("obj-30", "p hypnomix_panel", [770.0, 150.0, 104.0, 22.0], 1, [], patcher=sub)]
    p["boxes"] = extra + keep            # the toggle is listed first: it sits in front of the panel
    p["lines"] = list(p["lines"]) + [line("obj-20", 0, "obj-21"), line("obj-25", 0, "obj-21"),
                                     line("obj-22", 0, "obj-23"), line("obj-23", 0, "obj-24"), line("obj-22", 0, "obj-26"),
                                     line("obj-26", 0, "obj-27"), line("obj-26", 1, "obj-28"),
                                     line("obj-27", 0, "obj-29"), line("obj-28", 0, "obj-29"), line("obj-29", 0, "obj-30")]
    p["openinpresentation"] = 1
    p["devicewidth"] = float(W)
    p["description"] = "HypnoMix: review findings from inside Live and jump to each one"
    return patch


def build(out, tpl=None):
    tpl = Path(tpl) if tpl else template()
    if not tpl or not tpl.exists():
        raise FileNotFoundError("could not find Live's blank Max Audio Effect (is Ableton Live with Max for Live installed?); "
                                "pass --template PATH to a 'Max Audio Effect.amxd'")
    head, patch = read_amxd(tpl)
    out = Path(out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    js = JS.replace("__PORT__", str(app_port())).replace("__W__", str(W)).replace("__H__", str(H))
    (out / "hypnomix_device.js").write_text(js, encoding="utf-8")          # UTF-8: Max reads the script as UTF-8
    write_amxd(out / "Hypnomix.amxd", head, build_patch(patch))
    return out


def main():
    ap = argparse.ArgumentParser(prog="hypnomix device", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="folder to write into (default: your Live User Library)")
    ap.add_argument("--template", help="a blank 'Max Audio Effect.amxd' (default: the one inside your Live)")
    a = ap.parse_args()
    from hypnomix.install import user_library, user_library_words
    lib = user_library()
    out = a.out or (lib / "Presets" / "Audio Effects" / "Max Audio Effect" / "Hypnomix")
    if not a.out and not lib.is_dir():
        sys.exit(f"no Live User Library at {user_library_words()}: say where to write with --out FOLDER")
    try:
        od = build(out, a.template)
    except FileNotFoundError as e:
        sys.exit(str(e))
    print(f"wrote {od / 'Hypnomix.amxd'}\n      {od / 'hypnomix_device.js'}   (keep the two together)")
    print("In Live: drag the Hypnomix device from the browser onto any track, start the HypnoMix app, open a review.")


if __name__ == "__main__":
    main()
