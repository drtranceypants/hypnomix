#!/usr/bin/env python3
"""Make the hypnomix Max for Live device: review from inside Live, and jump Live to each finding.

  hypnomix device                 write Hypnomix.amxd + hypnomix_device.js into your Live User Library
  hypnomix device --out FOLDER    write them somewhere else

Then drag "Hypnomix" from Live's browser (User Library → Presets → Audio Effects → Max Audio Effect → Hypnomix)
onto ANY track; audio passes through it untouched. Needs Max for Live (Live Suite, or the add-on).

With the hypnomix app running (`hypnomix app`, or the Mac app) and a review open in it, the device shows the
finding you are on and has these buttons:

  Prev / Next    step through the findings; Live jumps to each one
  Next open      the next finding you have not decided yet
  Approve / Skip record your decision (saved exactly like a click in the app; nothing is applied from here)
  Brace on/off   whether the Arrangement loop brace is moved around the spot
  App            open the full review (with the before / after players) in your browser

"Jump" means: the finding's track is selected, the Arrangement playhead moves to the spot, the loop brace
is put around it (without switching looping on), and the clip under it opens in the Detail view. "Show in
Live" buttons in the app do the same through this device.

The device is built from the blank "Max Audio Effect" that ships inside your own copy of Live, plus one
script file. The two files must stay in the same folder.

Not yet verified by loading it in Live on a second machine: if it shows an error, the Max window (right-click
the device title → Open Max Window) says which line.
"""
import argparse, glob, json, sys
from pathlib import Path

W, H = 430, 169
PORT = 8791

JS = r"""// hypnomix device (jsui): talks to the hypnomix app on this computer and moves Live to each finding.
autowatch = 1;
inlets = 1;
outlets = 1;
mgraphics.init();
mgraphics.relative_coords = 0;
mgraphics.autofill = 0;

var BASE = "http://127.0.0.1:__PORT__";
var W = __W__, H = __H__;
var st = {ready: false, seq: -1, cur: null, lastOk: 0, flash: "", flashUntil: 0, brace: true, busy: false};
var buttons = [];
var task = new Task(tick, this);

function bang() {                      // live.thisdevice: the Live API is ready now
    st.ready = true;
    task.interval = 400;
    task.repeat();
}
function loadbang() { mgraphics.redraw(); }
function notifydeleted() { task.cancel(); }

function now() { return new Date().getTime(); }
function connected() { return now() - st.lastOk < 2500; }
function flash(text) { st.flash = text; st.flashUntil = now() + 3500; mgraphics.redraw(); }

function request(method, path, body, done) {
    var r = new XMLHttpRequest();
    r.open(method, BASE + path);
    r.onreadystatechange = function () {
        if (this.readyState != 4) return;
        var data = null;
        try { data = JSON.parse(this.responseText); } catch (e) { data = null; }
        if (data) st.lastOk = now();
        if (done) done(data);
    };
    if (body) r.send(JSON.stringify(body)); else r.send();
}

function tick() {
    if (st.busy && now() - st.busyAt < 3000) return;
    st.busy = true; st.busyAt = now();
    request("GET", "/api/live/poll?since=" + st.seq, null, function (d) {
        st.busy = false;
        if (!d) { mgraphics.redraw(); return; }
        var first = st.seq < 0;
        if (d.cmd && !first && d.seq > st.seq) run(d.cmd);
        st.seq = d.seq;
        st.cur = d.current;
        mgraphics.redraw();
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
    request("POST", "/api/live/step", {delta: delta, undecided: undecided}, function (d) { if (d) st.cur = d; mgraphics.redraw(); tick(); });
}
function decide(what) {
    request("POST", "/api/live/decide", {decision: what}, function (d) { if (d) { st.cur = d; flash(what == "approve" ? "Approved" : "Skipped"); } });
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
function button(label, x, w, on, act) {
    var y = H - 27, h = 20;
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
        text("Start the hypnomix app (or run: hypnomix app)", 8, 44, ink, 11, false);
        text("and open a review. This device then follows it.", 8, 60, mute, 11, false);
        button("Open app", 8, 70, false, "app");
        return;
    }
    if (!c || !c.of) {
        text("connected", 78, y, [0.5, 0.82, 0.64, 1], 10, false);
        var l = wrap(c ? c.text : "Open a review in the hypnomix app.", W - 16, 3);
        for (var k = 0; k < l.length; k++) text(l[k], 8, 44 + k * 15, ink, 11, false);
        button("Open app", 8, 70, false, "app");
        return;
    }
    text(c.song + "  ·  " + c.n + " of " + c.of + "  ·  " + c.left + " open", 78, y, mute, 10, false);
    y = 36;
    text(String(c.severity || "").toUpperCase(), 8, y, SEV[c.severity] || mute, 9, true);
    text((c.track || "") + "   " + (c.where || ""), 58, y, ink, 11, true);
    mgraphics.select_font_face("Arial"); mgraphics.set_font_size(11);
    var lines = wrap(c.problem, W - 16, 3), i;
    for (i = 0; i < lines.length; i++) { y += 15; text(lines[i], 8, y, ink, 11, false); }
    mgraphics.select_font_face("Arial"); mgraphics.set_font_size(10);
    var fx = wrap("Proposed: " + c.fix, W - 16, 2);
    y += 4;
    for (i = 0; i < fx.length; i++) { y += 13; text(fx[i], 8, y, mute, 10, false); }
    if (now() < st.flashUntil) text(st.flash, 8, H - 34, [0.5, 0.82, 0.64, 1], 10, false);
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
    else if (a == "brace") { st.brace = !st.brace; mgraphics.redraw(); }
    else if (a == "app") max.launchbrowser(BASE + "/");
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
    p["boxes"] = keep
    p["lines"] = list(p["lines"]) + [{"patchline": {"destination": ["obj-21", 0], "source": ["obj-20", 0]}}]
    p["openinpresentation"] = 1
    p["devicewidth"] = float(W)
    p["description"] = "hypnomix: review findings from inside Live and jump to each one"
    return patch


def build(out, tpl=None):
    tpl = Path(tpl) if tpl else template()
    if not tpl or not tpl.exists():
        raise FileNotFoundError("could not find Live's blank Max Audio Effect (is Ableton Live with Max for Live installed?); "
                                "pass --template PATH to a 'Max Audio Effect.amxd'")
    head, patch = read_amxd(tpl)
    out = Path(out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    write_amxd(out / "Hypnomix.amxd", head, build_patch(patch))
    (out / "hypnomix_device.js").write_text(JS.replace("__PORT__", str(PORT)).replace("__W__", str(W)).replace("__H__", str(H)))
    return out


def main():
    ap = argparse.ArgumentParser(prog="hypnomix device", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="folder to write into (default: your Live User Library)")
    ap.add_argument("--template", help="a blank 'Max Audio Effect.amxd' (default: the one inside your Live)")
    a = ap.parse_args()
    lib = Path("~/Music/Ableton/User Library").expanduser()
    out = a.out or (lib / "Presets" / "Audio Effects" / "Max Audio Effect" / "Hypnomix")
    if not a.out and not lib.is_dir():
        sys.exit("no Live User Library at ~/Music/Ableton/User Library: say where to write with --out FOLDER")
    try:
        od = build(out, a.template)
    except FileNotFoundError as e:
        sys.exit(str(e))
    print(f"wrote {od / 'Hypnomix.amxd'}\n      {od / 'hypnomix_device.js'}   (keep the two together)")
    print("In Live: drag Hypnomix from the browser onto any track, start the hypnomix app, open a review.")


if __name__ == "__main__":
    main()
