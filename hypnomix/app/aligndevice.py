#!/usr/bin/env python3
"""Make the Hypnomix Align device: VocAlign-style alignment of a vocal stack, run from inside Live.

  hypnomix aligndevice                 write "Hypnomix Align.amxd" + hypnomix_align.js into your Live User Library
  hypnomix aligndevice --out FOLDER    write them somewhere else

Drag "Hypnomix Align" (User Library → Presets → Audio Effects → Max Audio Effect) onto any track (audio passes
through untouched). It needs the HypnoMix app running (`hypnomix app`, or the Mac app) and Max for Live.

  Set           Choose set: the saved .als you are working on (save first: alignset reads the saved file)
  Guide         select the guide track in Live, click "Guide ←"
  To            what the parts line up to. It is asked, never assumed: click for "To: average" (every part is
                nudged toward the group's average timing, the guide too) or "To: guide" (the parts follow the guide,
                which is never moved). "To: ?" means not chosen yet: with 2+ parts Align asks you to choose. An
                answer saved in the app's Preferences shows here as the starting choice
  Parts         select a part, click "+ Part" (repeat); "Clear" empties the list
  Range         "Brace": only the bars under the loop brace; "Song": everywhere
  Protect       puts the loop brace's span on the protected list (never moved)
  Sync here     the playhead position becomes a sync point (lined up exactly)
  dials         drag up/down: Tight (how far timing moves), Pitch (0 = off), Vibrato, Formant (semitones)
  Preset        click to step through the presets (or none: the dials alone)
  Align         measure and make previews (nothing in your set changes)
  Write set     when on, Align also writes "<set> (aligned).als" next to yours: the timing as warp markers on
                your own clips
  Open set      open the aligned set in Live (Live asks to save the current one first)
  Place         pitch / formant results are rendered files from bar 1: Place puts each on a new track under its
                original and mutes the original

The window shows each part's loudness over the range: grey is before, amber after. The guide is the top lane.
Times go to the app in seconds (from the loop brace and the playhead at the set's tempo; one tempo assumed).
Not yet verified by loading in Live: if it shows an error, the Max window (right-click the title → Open Max Window)
says which line.
"""
import argparse, sys
from pathlib import Path

from hypnomix.app import device as D

W, H = 600, 169
PORT = D.PORT

JS = r"""// Hypnomix Align (jsui): picks tracks and spans in Live, runs `hypnomix alignset` through the HypnoMix app.
autowatch = 1;
inlets = 1;
outlets = 1;
mgraphics.init();
mgraphics.relative_coords = 0;
mgraphics.autofill = 0;

var BASE = "http://127.0.0.1:__PORT__";
var W = __W__, H = __H__;
var PRESETS = ["", "gentle-stack", "natural-double", "tight-pop", "loose-folk", "rap-doubles"];
var st = {ready: false, lastOk: 0, flash: "", flashUntil: 0, guide: "", parts: [], range: "brace", protect: [], sync: [],
          tight: 0.5, pitch: 0, vibrato: 0, formant: 0, preset: 0, write: false, server: null, busy: false, ref: ""};
var REFS = ["", "average", "lead"];
function refNow() { return st.ref || (st.server && st.server.reference) || ""; }   // chosen here, else the saved answer
var hits = [], dials = [], drag = null;
var task = new Task(tick, this);

function bang() { st.ready = true; task.interval = 700; task.repeat(); }
function loadbang() { mgraphics.redraw(); }
function notifydeleted() { task.cancel(); }
function now() { return new Date().getTime(); }
function connected() { return now() - st.lastOk < 3000; }
function flash(t) { st.flash = t; st.flashUntil = now() + 4000; mgraphics.redraw(); }

function request(method, path, body, done) {
    var r = new XMLHttpRequest();
    r.open(method, BASE + path);
    r.onreadystatechange = function () {
        if (this.readyState != 4) return;
        var d = null;
        try { d = JSON.parse(this.responseText); } catch (e) { d = null; }
        if (d) st.lastOk = now();
        if (d && d.error) flash(d.error);
        if (done) done(d);
    };
    if (body) r.send(JSON.stringify(body)); else r.send();
}
function tick() {
    if (st.busy && now() - st.busyAt < 3000) return;
    st.busy = true; st.busyAt = now();
    request("GET", "/api/align/state", null, function (d) { st.busy = false; if (d && !d.error) st.server = d; mgraphics.redraw(); });
}

// ---------------------------------------------------------------- Live
function nameOf(api) { var v = api.get("name"); return (v instanceof Array) ? v.join(" ") : String(v); }
function selectedName() {
    var t = new LiveAPI("live_set view selected_track");
    return t && t.id != 0 ? nameOf(t) : "";
}
function tempo() { return parseFloat(new LiveAPI("live_set").get("tempo")); }
function beatsToSec(b) { return b * 60.0 / tempo(); }
function brace() {
    var s = new LiveAPI("live_set");
    var a = parseFloat(s.get("loop_start")), l = parseFloat(s.get("loop_length"));
    return [beatsToSec(a), beatsToSec(a + l)];
}
function playhead() { return beatsToSec(parseFloat(new LiveAPI("live_set").get("current_song_time"))); }
function findTrack(name) {
    var s = new LiveAPI("live_set"), n = s.getcount("tracks");
    for (var i = 0; i < n; i++) { var t = new LiveAPI("live_set tracks " + i); if (nameOf(t) == name) return [t, i]; }
    return null;
}
function place() {
    var r = st.server && st.server.result, done = 0;
    if (!r || !r.rendered) { flash("Nothing rendered: use Pitch or Formant, then Align"); return; }
    for (var name in r.rendered) {
        var f = findTrack(name);
        if (!f) { flash("No track called " + name); continue; }
        try {
            var s = new LiveAPI("live_set");
            s.call("create_audio_track", f[1] + 1);
            var t = new LiveAPI("live_set tracks " + (f[1] + 1));
            t.set("name", name + " (matched)");
            t.call("create_audio_clip", r.rendered[name], 0.0);
            f[0].set("mute", 1);
            done++;
        } catch (e) { flash("Could not place " + name + ": drag the file in at 1.1.1 (" + e + ")"); }
    }
    if (done) flash("Placed " + done + " track(s); originals muted");
}

// ---------------------------------------------------------------- actions
function run() {
    if (!st.guide || !st.parts.length) { flash("Choose a guide and at least one part"); return; }
    var body = {guide: st.guide, parts: st.parts, protect: st.protect, sync: st.sync, tightness: st.tight,
                pitch: st.pitch, vibrato: st.vibrato, formant: st.formant, apply: st.write, bpm: tempo()};
    if (PRESETS[st.preset]) body.preset = PRESETS[st.preset];
    if (st.ref) body.reference = st.ref;
    if (st.range == "brace") { var b = brace(); body.start_s = b[0]; body.end_s = b[1]; }
    request("POST", "/api/align/run", body, function (d) { if (d && d.job) flash("Aligning… (the app's log shows each step)"); });
}
function act(a) {
    if (a == "choose") request("POST", "/api/align/choose", {}, function (d) { if (d && !d.error) st.server = d; mgraphics.redraw(); });
    else if (a == "guide") { st.guide = selectedName(); st.parts = st.parts.filter(function (p) { return p != st.guide; }); }
    else if (a == "part") { var n = selectedName(); if (n && n != st.guide && st.parts.indexOf(n) < 0) st.parts.push(n); }
    else if (a == "clear") { st.parts = []; st.protect = []; st.sync = []; flash("Parts, protected areas and sync points cleared"); }
    else if (a == "range") st.range = st.range == "brace" ? "song" : "brace";
    else if (a == "protect") { var b = brace(); st.protect.push(b); flash("Protected " + b[0].toFixed(1) + "–" + b[1].toFixed(1) + " s"); }
    else if (a == "sync") { var t = playhead(); st.sync.push(t); flash("Sync point at " + t.toFixed(2) + " s"); }
    else if (a == "preset") st.preset = (st.preset + 1) % PRESETS.length;
    else if (a == "ref") st.ref = REFS[(REFS.indexOf(refNow()) + 1) % REFS.length] || "average";
    else if (a == "write") st.write = !st.write;
    else if (a == "align") run();
    else if (a == "open") request("POST", "/api/align/open", {}, function (d) { if (d && d.opened) flash("Opening the aligned set…"); });
    else if (a == "place") place();
    else if (a == "app") max.launchbrowser(BASE + "/");
    mgraphics.redraw();
}

// ---------------------------------------------------------------- drawing
function text(s, x, y, c, size, bold) {
    mgraphics.select_font_face(bold ? "Arial Bold" : "Arial"); mgraphics.set_font_size(size);
    mgraphics.set_source_rgba(c[0], c[1], c[2], c[3]); mgraphics.move_to(x, y); mgraphics.show_text(String(s));
}
function clip(s, width, size) {
    mgraphics.set_font_size(size); s = String(s);
    while (s.length > 1 && mgraphics.text_measure(s)[0] > width) s = s.slice(0, -2) + "…";
    return s;
}
function button(label, x, y, w, on, a) {
    mgraphics.set_source_rgba(on ? 0.62 : 0.24, on ? 0.42 : 0.24, on ? 0.16 : 0.25, 1);
    mgraphics.rectangle_rounded(x, y, w, 18, 5, 5); mgraphics.fill();
    mgraphics.select_font_face("Arial Bold"); mgraphics.set_font_size(9.5);
    var tw = mgraphics.text_measure(label)[0];
    text(label, x + (w - tw) / 2, y + 12.5, [0.95, 0.93, 0.89, 1], 9.5, true);
    hits.push({x: x, y: y, w: w, h: 18, a: a});
    return x + w + 4;
}
function dial(label, key, x, y, lo, hi, fmt) {
    var v = st[key], f = (v - lo) / (hi - lo), w = 54, h = 26;
    mgraphics.set_source_rgba(0.2, 0.19, 0.17, 1); mgraphics.rectangle_rounded(x, y, w, h, 5, 5); mgraphics.fill();
    mgraphics.set_source_rgba(0.85, 0.6, 0.25, 0.9); mgraphics.rectangle_rounded(x, y + h - 4, Math.max(2, w * f), 4, 2, 2); mgraphics.fill();
    text(label, x + 4, y + 10, [0.63, 0.6, 0.56, 1], 8.5, false);
    text(fmt(v), x + 4, y + 21, [0.95, 0.93, 0.89, 1], 10, true);
    dials.push({x: x, y: y, w: w, h: h, key: key, lo: lo, hi: hi});
}
function lanes(x, y, w, h) {
    mgraphics.set_source_rgba(0.09, 0.085, 0.08, 1); mgraphics.rectangle(x, y, w, h); mgraphics.fill();
    var r = st.server && st.server.result, e = r && r.energy;
    if (!e || !e.tracks || !e.tracks.length) {
        text(st.server && st.server.running ? "aligning: " + (st.server.step || "") : "Align to see each part before (grey) and after (amber)",
             x + 8, y + h / 2 + 4, [0.55, 0.52, 0.48, 1], 9.5, false);
        return;
    }
    var n = e.tracks.length, lh = h / n;
    for (var i = 0; i < n; i++) {
        var tr = e.tracks[i], top = y + i * lh;
        var draw = function (arr, c) {
            if (!arr) return;
            mgraphics.set_source_rgba(c[0], c[1], c[2], c[3]); mgraphics.set_line_width(1);
            for (var k = 0; k < arr.length; k++) {
                var px = x + k * w / arr.length, amp = (arr[k] + 60) / 60 * (lh - 3) * 0.5;
                mgraphics.move_to(px, top + lh / 2 - amp); mgraphics.line_to(px, top + lh / 2 + amp);
            }
            mgraphics.stroke();
        };
        draw(tr.before, [0.5, 0.5, 0.5, 0.55]);
        draw(tr.after, [0.95, 0.66, 0.25, 0.75]);
        text(clip(tr.name, 90, 8.5), x + 3, top + 9, [0.9, 0.88, 0.84, 0.9], 8.5, i == 0);
    }
}
function paint() {
    hits = []; dials = [];
    mgraphics.set_source_rgba(0.13, 0.125, 0.11, 1); mgraphics.rectangle(0, 0, W, H); mgraphics.fill();
    var ink = [0.93, 0.91, 0.87, 1], mute = [0.63, 0.6, 0.56, 1], s = st.server;
    text("HYPNOMIX ALIGN", 8, 15, ink, 10, true);
    if (!connected()) {
        text("not connected: start the HypnoMix app (or run: hypnomix app)", 110, 15, mute, 10, false);
        button("Open app", 8, 30, 70, false, "app");
        return;
    }
    text(clip("Set: " + (s && s.set_name ? s.set_name : "none (save it, then Choose set)"), 200, 10), 110, 15, s && s.set_name ? ink : mute, 10, false);
    button("Choose set", 318, 4, 66, false, "choose");
    if (s && s.status && s.status != "idle") text(s.running ? "running" : s.status, 390, 15, s.status == "failed" ? [1, 0.55, 0.5, 1] : [0.5, 0.82, 0.64, 1], 10, true);
    // left column: picks
    var x = 8, y = 26;
    button("Guide ←", x, y, 58, false, "guide");
    text(clip(st.guide || "select the guide track", 150, 10), x + 63, y + 13, st.guide ? ink : mute, 10, true);
    y += 21;
    button("+ Part", x, y, 58, false, "part");
    text(clip(st.parts.length ? st.parts.join(", ") : "select a part, then + Part", 150, 10), x + 63, y + 13, st.parts.length ? ink : mute, 10, false);
    y += 21;
    var bx = button(st.range == "brace" ? "Range: brace" : "Range: song", x, y, 78, st.range == "brace", "range");
    bx = button("Protect", bx, y, 50, st.protect.length > 0, "protect");
    bx = button("Sync here", bx, y, 58, st.sync.length > 0, "sync");
    button("Clear", bx, y, 36, false, "clear");
    y += 22;
    text(st.protect.length + " protected · " + st.sync.length + " sync", x, y + 8, mute, 9, false);
    var rn = refNow();
    button("To: " + (rn == "average" ? "average" : rn == "lead" ? "guide" : "?"), 152, y - 4, 86, rn != "", "ref");
    // dials
    y = 104;
    dial("Tight", "tight", 8, y, 0, 1, function (v) { return Math.round(v * 100) + "%"; });
    dial("Pitch", "pitch", 66, y, 0, 1, function (v) { return v < 0.01 ? "off" : Math.round(v * 100) + "%"; });
    dial("Vibrato", "vibrato", 124, y, 0, 1, function (v) { return v < 0.01 ? "off" : Math.round(v * 100) + "%"; });
    dial("Formant", "formant", 182, y, -1, 1, function (v) { return Math.abs(v) < 0.02 ? "0" : (v > 0 ? "+" : "") + v.toFixed(2); });
    button(clip("Preset: " + (PRESETS[st.preset] || "none"), 100, 9.5), 8, 145, 116, PRESETS[st.preset] != "", "preset");
    button("Write set", 128, 145, 56, st.write, "write");
    button("Align", 188, 145, 48, false, "align");
    // right: lanes and result buttons
    lanes(246, 26, W - 254, 112);
    var r = s && s.result;
    bx = 246;
    bx = button("Open set", bx, 145, 58, r && r.out_set, "open");
    bx = button("Place", bx, 145, 44, r && r.rendered && Object.keys(r.rendered).length, "place");
    bx = button("App", bx, 145, 34, false, "app");
    if (now() < st.flashUntil) text(clip(st.flash, W - bx - 8, 9.5), bx + 4, 158, [0.5, 0.82, 0.64, 1], 9.5, false);
    else if (r && r.parts) {
        var m = 0; for (var i = 0; i < r.parts.length; i++) m += r.parts[i].markers || 0;
        text(clip(m + " warp markers" + (r.out_set ? " · new set written" : " · measured only"), W - bx - 8, 9.5), bx + 4, 158, mute, 9.5, false);
    }
}

function onclick(x, y) {
    for (var i = 0; i < dials.length; i++) {
        var d = dials[i];
        if (x >= d.x && x <= d.x + d.w && y >= d.y && y <= d.y + d.h) { drag = {d: d, y0: y, v0: st[d.key]}; return; }
    }
    drag = null;
    for (var j = 0; j < hits.length; j++) {
        var b = hits[j];
        if (x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h) { act(b.a); return; }
    }
}
function ondrag(x, y, but) {
    if (!drag) return;
    var d = drag.d, v = drag.v0 + (drag.y0 - y) / 120 * (d.hi - d.lo);
    st[d.key] = Math.max(d.lo, Math.min(d.hi, v));
    if (!but) drag = null;
    mgraphics.redraw();
}
function ondblclick(x, y) {          // double-click a dial: back to its default
    for (var i = 0; i < dials.length; i++) {
        var d = dials[i];
        if (x >= d.x && x <= d.x + d.w && y >= d.y && y <= d.y + d.h) {
            st[d.key] = {tight: 0.5, pitch: 0, vibrato: 0, formant: 0}[d.key]; mgraphics.redraw(); return;
        }
    }
}
"""


def build_patch(patch):
    p = D.build_patch(patch)["patcher"]
    for b in p["boxes"]:
        if b["box"].get("maxclass") == "jsui":
            b["box"]["filename"] = "hypnomix_align.js"
            b["box"]["patching_rect"] = [160.0, 70.0, float(W), float(H)]
            b["box"]["presentation_rect"] = [0.0, 0.0, float(W), float(H)]
    p["devicewidth"] = float(W)
    p["description"] = "Hypnomix Align: align a vocal stack (timing as warp markers, optional pitch match and formant)"
    return patch


def build(out, tpl=None):
    tpl = Path(tpl) if tpl else D.template()
    if not tpl or not tpl.exists():
        raise FileNotFoundError("could not find Live's blank Max Audio Effect (is Ableton Live with Max for Live installed?); "
                                "pass --template PATH to a 'Max Audio Effect.amxd'")
    head, patch = D.read_amxd(tpl)
    out = Path(out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    js = JS.replace("__PORT__", str(PORT)).replace("__W__", str(W)).replace("__H__", str(H))
    (out / "hypnomix_align.js").write_text(js, encoding="utf-8")           # UTF-8: Max reads the script as UTF-8
    D.write_amxd(out / "Hypnomix Align.amxd", head, build_patch(patch))
    return out


def main():
    ap = argparse.ArgumentParser(prog="hypnomix aligndevice", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="folder to write into (default: your Live User Library)")
    ap.add_argument("--template", help="a blank 'Max Audio Effect.amxd' (default: the one inside your Live)")
    a = ap.parse_args()
    from hypnomix.install import user_library, user_library_words
    lib = user_library()
    out = a.out or (lib / "Presets" / "Audio Effects" / "Max Audio Effect" / "Hypnomix Align")
    if not a.out and not lib.is_dir():
        sys.exit(f"no Live User Library at {user_library_words()}: say where to write with --out FOLDER")
    try:
        od = build(out, a.template)
    except FileNotFoundError as e:
        sys.exit(str(e))
    print(f"wrote {od / 'Hypnomix Align.amxd'}\n      {od / 'hypnomix_align.js'}   (keep the two together)")
    print("In Live: drag Hypnomix Align onto any track, start the HypnoMix app, save your set, Choose set.")


if __name__ == "__main__":
    main()
