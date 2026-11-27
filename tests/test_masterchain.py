"""HypnomixMain's mastering chain: templates, the patch column, and the device script against a simulated Live."""
import json, os, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock

from hypnomix.app import masterchain as MC
from hypnomix.app import probe as P

from tests import _jscheck

# A small Live: Main with HypnomixMain on it; insert_device makes devices with the parameter names Live uses.
FAKE = r"""
var OUT = [], NEXT = 1, HTTP = {};
function print_(x) { print(JSON.stringify(x)); }
function outlet() { OUT.push(Array.prototype.slice.call(arguments)); }
function arrayfromargs(a) { return Array.prototype.slice.call(a); }
function Task(f) { this.schedule = function () {}; this.repeat = function () {}; this.cancel = function () {}; }
function XMLHttpRequest() {
  var me = this;
  this.open = function (m, u) { me.u = u; me.m = m; };
  this.send = function (b) { HTTP.last = {u: me.u, body: b}; if (me.m == "POST") HTTP.posted = {u: me.u, body: b}; me.readyState = 4; me.responseText = HTTP.reply || "null";
                             me.onreadystatechange(); };
}
function lin(u) { return function (x) { return x.toFixed(2) + " " + u; }; }
function hz(x) { var f = 10 * Math.pow(2200, x); return f >= 1000 ? (f / 1000).toFixed(2) + " kHz" : f.toFixed(1) + " Hz"; }
function P_(n, lo, hi, v, disp, items) { return {name: n, original_name: n, min: lo, max: hi, value: v, disp: disp || lin(""), items: items, id: NEXT++}; }
function sw(n, v) { return P_(n, 0, 1, v === undefined ? 1 : v, function (x) { return x ? "on" : "off"; }, ["off", "on"]); }
function dev(name, cls, ps) { ps.unshift(sw("Device On", 1)); return {name: name, class_name: cls, params: ps, id: NEXT++, chains: null}; }
var MAKE = {
  "EQ Eight": function () { var p = []; for (var i = 1; i <= 8; i++) p.push(sw(i + " Filter On A", 1), P_(i + " Filter Type A", 0, 7, 3, lin(""), ["LC48","LC12","LS","Bell","Notch","HS","HC12","HC48"]),
      P_(i + " Frequency A", 0, 1, 0.5, hz), P_(i + " Gain A", -15, 15, 0, lin("dB")), P_(i + " Resonance A", 0.1, 18, 0.71, lin(""))); return dev("EQ Eight", "Eq8", p); },
  "Glue Compressor": function () { return dev("Glue Compressor", "GlueCompressor", [P_("Threshold", -40, 0, 0, lin("dB")), P_("Ratio", 0, 2, 0, null, ["2", "4", "10"]),
      P_("Attack", 0, 6, 0, null, ["0.01 ms", "0.1 ms", "0.3 ms", "1 ms", "3 ms", "10 ms", "30 ms"]),
      P_("Release", 0, 6, 0, null, ["0.1", "0.2", "0.4", "0.6", "0.8", "1.2", "A"]), P_("Output", 0, 20, 0, lin("dB")),
      P_("Range", 0, 70, 70, lin("dB")), P_("Dry/Wet", 0, 1, 1, function (x) { return (x * 100).toFixed(0) + " %"; }), sw("Peak Clip In", 0)]); },
  "Multiband Dynamics": function () { return dev("Multiband Dynamics", "MultibandDynamics", [P_("Amount", 0, 1, 1, function (x) { return (x * 100).toFixed(0) + " %"; })]); },
  "Saturator": function () { return dev("Saturator", "Saturator", [P_("Drive", -36, 36, 0, lin("dB")), P_("Type", 0, 6, 0, null, ["Analog Clip", "Soft Sine", "Medium Curve", "Hard Curve", "Sinoid Fold", "Digital Clip", "Waveshaper"]),
      P_("Output", -36, 0, 0, lin("dB")), P_("Dry/Wet", 0, 1, 1, function (x) { return (x * 100).toFixed(0) + " %"; })]); },
  "Utility": function () { return dev("Utility", "StereoGain", [P_("Stereo Width", 0, 4, 1, function (x) { return (x * 100).toFixed(1) + " %"; }), sw("Bass Mono", 0),
      P_("Bass Freq", 0, 1, 0.3, function (x) { return (50 + 450 * x).toFixed(0) + " Hz"; }), sw("DC Filter", 0), P_("Gain", -35, 35, 0, lin("dB"))]); },
  "Limiter": function () { return dev("Limiter", "Limiter", [P_("Input Gain", -24, 24, 0, lin("dB")), P_("Ceiling", -24, 0, -2.5, lin("dB")),
      sw("Auto", 0), P_("Lookahead", 0, 2, 1, null, ["1.5 ms", "3 ms", "6 ms"]), P_("Mode", 0, 2, 0, null, ["Standard", "Soft Clip", "True Peak"])]); },
  "Audio Effect Rack": function () { var d = dev("Audio Effect Rack", "AudioEffectGroupDevice", [P_("Macro 1", 0, 127, 0, lin(""))]); d.chains = []; return d; }
};
var ME = {name: "HypnomixMain", class_name: "MxDeviceAudioEffect", params: [], id: NEXT++, chains: null};
var NO_DELETE_CHAIN = false;
var MAIN = {name: "Main", devices: [ME], id: NEXT++, vol: P_("Volume", 0, 1, 0.85, function () { return "0.0 dB"; })};
var SONG = {is_playing: 0, id: NEXT++};
function resolve(path) {
  var t = path.split(" "), o = null, i = 0, canon = [];
  if (t[0] == "this_device") { o = ME; i = 1; canon = MECANON().split(" ");
    if (t[1] == "canonical_parent") { o = MAIN; i = 2; canon = ["live_set", "master_track"]; } }
  else if (t[0] == "live_set" && t[1] == "master_track") { o = MAIN; i = 2; canon = ["live_set", "master_track"]; }
  else if (t[0] == "live_set") { o = SONG; i = 1; canon = ["live_set"]; }
  for (; i < t.length; i++) {
    var k = t[i];
    if (k == "devices") { o = o.devices[parseInt(t[++i])]; canon.push("devices", t[i]); }
    else if (k == "chains") { o = o.chains[parseInt(t[++i])]; canon.push("chains", t[i]); }
    else if (k == "parameters") { o = o.params[parseInt(t[++i])]; canon.push("parameters", t[i]); }
    else if (k == "mixer_device") { canon.push(k); }
    else if (k == "volume") { o = MAIN.vol; canon.push(k); }
    if (!o) return [null, ""];
  }
  return [o, canon.join(" ")];
}
function MECANON() { return "live_set master_track devices " + MAIN.devices.indexOf(ME); }
function LiveAPI(path) {
  var r = resolve(path), o = r[0];
  this.id = o ? String(o.id) : "0"; this.unquotedpath = r[1]; this.path = '"' + r[1] + '"';
  this.getcount = function (k) { return k == "parameters" ? o.params.length : (o[k] || []).length; };
  this.get = function (k) {
    if (k == "can_have_chains") return [o.chains ? 1 : 0];
    if (k == "is_quantized") return [o.items ? 1 : 0];
    if (k == "value_items") return o.items || [];
    if (k == "is_enabled") return [1];
    return [o[k]];
  };
  this.set = function (k, v) { if (k == "value") o.value = Math.max(o.min, Math.min(o.max, v)); else o[k] = v; };
  this.call = function (f, a, b) {
    if (f == "str_for_value") return o.disp(a);
    if (f == "insert_device") { if (!MAKE[a]) throw "no device " + a; var d = MAKE[a](); o.devices.splice(b, 0, d); return ["id", d.id]; }
    if (f == "delete_device") { o.devices.splice(a, 1); return; }
    if (f == "delete_chain") { if (NO_DELETE_CHAIN) throw "no delete_chain"; o.chains.splice(a, 1); return; }
    if (f == "insert_chain") { o.chains.splice(a === undefined ? o.chains.length : a, 0, {name: "Chain", devices: [], id: NEXT++}); return; }
    if (f == "start_playing") { SONG.is_playing = 1; return; }
  };
}
function tree(d) {
  var o = {name: d.name, cls: d.class_name, p: {}};
  for (var i = 0; i < d.params.length; i++) o.p[d.params[i].name] = d.params[i].disp(d.params[i].items ? d.params[i].value : d.params[i].value);
  if (d.chains) { o.chains = []; for (var c = 0; c < d.chains.length; c++) o.chains.push({name: d.chains[c].name, devices: d.chains[c].devices.map(tree)}); }
  return o;
}
function itemDisp(p) { return p.items ? p.items[Math.round(p.value - p.min)] : p.disp(p.value); }
function flat(d) { var o = {name: d.name, cls: d.class_name, p: {}};
  for (var i = 0; i < d.params.length; i++) o.p[d.params[i].name] = itemDisp(d.params[i]);
  if (d.chains) o.chains = d.chains.map(function (c) { return {name: c.name, devices: c.devices.map(flat)}; });
  return o; }
function said() { for (var i = OUT.length - 1; i >= 0; i--) if (OUT[i][0] == 0 && OUT[i][1] == "set") return OUT[i][2]; return ""; }
"""


def run(script, body):
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "t.js"
        f.write_text(FAKE + "\n" + script + "\n" + body, encoding="utf-8")
        r = subprocess.run(_jscheck.runner() + [str(f)], capture_output=True, text=True, encoding="utf-8")
    if r.returncode or "Exception" in r.stdout or "Error" in r.stderr:
        raise AssertionError(r.stdout + r.stderr)
    return [json.loads(l) for l in r.stdout.splitlines() if l.strip()]


class Script(unittest.TestCase):
    def setUp(self):
        _jscheck.need_runner(self)
        self.js = MC.script()

    def test_a_rack_saved_with_the_old_spelling_is_still_ours(self):
        out = run(self.js, """
bang(); build();
MAIN.devices[0].name = "Hypnomix Master";                       // as an older version saved it
st.list = ["hypnomix stock"]; st.pick = 0;
build();                                                         // asks first: it knows the rack is its own
print_(said());
st.confirmAt = new Date().getTime(); build();
print_(MAIN.devices.map(flat).map(function (d) { return d.name; }));
""")
        self.assertIn("already here", out[0])
        self.assertEqual(out[1], ["HypnoMix Master", "HypnomixMain"])

    def test_builds_the_stock_chain_in_a_rack_before_the_device(self):
        out = run(self.js, """
bang(); param("hm_ceiling", -1.0); param("hm_mode", 1);
build();
print_(MAIN.devices.map(flat)); print_(said());
""")
        devs, msg = out
        self.assertEqual([d["name"] for d in devs], ["HypnoMix Master", "HypnomixMain"])
        inner = devs[0]["chains"][0]["devices"]
        self.assertEqual([d["name"] for d in inner], ["Tone", "Glue", "Tame", "Warmth", "Width", "Limiter"])
        eq, glue, tame, warm, util, lim = (d["p"] for d in inner)
        self.assertEqual(eq["1 Filter Type A"], "LC12")
        self.assertIn(eq["1 Frequency A"], ("25.0 Hz", "24.9 Hz", "25.1 Hz"))
        self.assertEqual(eq["4 Frequency A"][:4], "3.00")
        self.assertEqual(eq["6 Filter On A"], "off")
        self.assertEqual((glue["Ratio"], glue["Attack"], glue["Release"], glue["Range"]), ("2", "30 ms", "A", "3.00 dB"))
        self.assertEqual(tame["Device On"], "off")
        self.assertEqual((warm["Device On"], warm["Type"]), ("off", "Soft Sine"))
        self.assertEqual((util["Bass Mono"], util["Bass Freq"], util["DC Filter"]), ("on", "120 Hz", "on"))
        self.assertEqual((lim["Ceiling"], lim["Mode"], lim["Lookahead"]), ("-1.00 dB", "True Peak", "3 ms"))   # punch
        self.assertIn("6 devices", msg)

    def test_build_again_asks_then_replaces(self):
        out = run(self.js, """
bang(); build(); build(); print_(said()); print_(MAIN.devices.length);
st.confirmAt = new Date().getTime(); build(); print_(MAIN.devices.length); print_(MAIN.devices[0].chains[0].devices.length);
""")
        self.assertIn("Press Build again", out[0])
        self.assertEqual(out[1:], [2, 2, 6])

    def test_save_and_rebuild_keeps_the_edits(self):
        out = run(self.js, """
bang(); build();
var lim = MAIN.devices[0].chains[0].devices[5]; lim.params[1].value = 5.5;      // Gain edited in Live
MAIN.devices[0].chains[0].devices[3].params[0].value = 1;                       // Warmth switched on
tplname("my", "master"); HTTP.reply = '{"name": "my master", "devices": 6, "skipped": []}'; save();
var sent = JSON.parse(HTTP.posted.body); print_(sent.name); print_(sent.chain.devices.length);
HTTP.reply = JSON.stringify(sent.chain); st.list = ["HypnoMix stock", "my master"]; pick(1);
st.confirmAt = new Date().getTime(); build();
print_(MAIN.devices.map(flat)[0].chains[0].devices.map(function (d) { return [d.name, d.p["Device On"], d.p["Input Gain"] || ""]; }));
""")
        self.assertEqual(out[0], "my master")
        self.assertEqual(out[1], 6)                       # what is inside our rack, not the rack itself
        self.assertEqual(out[2][3][:2], ["Warmth", "on"])
        self.assertEqual(out[2][5], ["Limiter", "on", "5.50 dB"])

    def test_own_rack_is_saved_with_what_cannot_be_rebuilt_listed(self):
        out = run(self.js, """
bang();
var r = MAKE["Audio Effect Rack"](); r.name = "My Rack"; r.chains.push({name: "A", devices: [MAKE["Limiter"](),
         {name: "Envelope Follower", class_name: "MxDeviceAudioEffect", params: [], id: 999, chains: null}], id: 998});
MAIN.devices.unshift(r);
tplname("mine"); HTTP.reply = '{"name": "mine", "devices": 2, "skipped": []}'; save();
var sent = JSON.parse(HTTP.posted.body).chain; print_(sent.devices[0].chains[0].devices.length); print_(sent.skipped);
""")
        self.assertEqual(out[0], 1)
        self.assertTrue(any("Envelope Follower" in s for s in out[1]) and any("macro" in s for s in out[1]), out[1])

    def test_card_changes_follow_only_our_rack(self):
        out = run(self.js, """
bang(); build(); st.readyAt = 0;
param("hm_ceiling", -2.0); param("hm_mode", 2);
var lim = MAIN.devices[0].chains[0].devices[5]; print_([itemDisp(lim.params[2]), itemDisp(lim.params[4]), itemDisp(lim.params[3])]);
MAIN.devices[0].name = "Somebody's rack"; param("hm_ceiling", -0.5); print_(itemDisp(lim.params[2]));
""")
        self.assertEqual(out[0], ["-2.00 dB", "1.5 ms", "off"])       # loud: short lookahead, manual release
        self.assertEqual(out[1], "-2.00 dB")

    def test_match_target_turns_the_limiter_gain(self):
        out = run(self.js, """
bang(); build(); param("hm_target", -14);
var g = MAIN.devices[0].chains[0].devices[5].params[1];
match();
for (var i = 0; i < 600 && st.match; i++) {
  var L = -22 + g.value * 0.9;                      // the limiter gives back a little less than it is given
  var ms = Math.pow(10, (L + 0.691) / 10) / 2; val(0, Math.sqrt(ms)); val(1, Math.sqrt(ms)); blk();
}
print_(g.value); print_(said()); print_(SONG.is_playing);
""")
        gain, msg, playing = out
        self.assertAlmostEqual(-22 + gain * 0.9, -14, delta=0.5)
        self.assertIn("-14", msg)
        self.assertEqual(playing, 1)

    def test_match_needs_a_limiter(self):
        out = run(self.js, "bang(); match(); print_(said());")
        self.assertIn("No Limiter", out[0])


class Templates(unittest.TestCase):
    def test_new_names_and_old_spelling(self):
        self.assertEqual(MC.RACK, "HypnoMix Master")
        self.assertEqual(MC.STOCK_NAME, "HypnoMix stock")
        self.assertIs(MC.load("hypnomix stock"), MC.STOCK)
        self.assertIs(MC.load("HypnoMix Stock"), MC.STOCK)
        self.assertTrue(MC.is_stock("hypnomix stock"))
        with self.assertRaises(ValueError):
            MC.save("hypnomix stock", {"devices": [{"cls": "Limiter"}]})
        with tempfile.TemporaryDirectory() as d, mock.patch.object(MC, "home", lambda: Path(d)):
            self.assertFalse(MC.delete("hypnomix stock"))

    def test_js_matches_rack_ignoring_case(self):
        self.assertIn("same(d.get(\"name\"), RACK)", MC.JS)
        self.assertIn("same(nm, STOCK.name)", MC.JS)
        self.assertNotIn("== RACK", MC.JS)

    def test_save_list_show_delete(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(MC, "home", lambda: Path(d)):
            self.assertEqual(MC.names(), ["HypnoMix stock"])
            with self.assertRaises(ValueError):
                MC.save("hypnomix stock", {"devices": [{"cls": "Limiter"}]})
            with self.assertRaises(ValueError):
                MC.save("empty", {"devices": []})
            r = MC.save("My/Master!", {"devices": [{"cls": "Limiter", "name": "Lim", "params": [{"n": "Device On", "v": 0}]}],
                                       "skipped": ["Envelope Follower (Mx)"]})
            self.assertEqual(r["name"], "MyMaster")
            self.assertEqual(MC.names(), ["HypnoMix stock", "MyMaster"])
            text = MC.describe(MC.load("MyMaster"))
            self.assertIn("Lim (Limiter) [off]", text)
            self.assertIn("left out: Envelope Follower", text)
            self.assertEqual(MC.handle_get("/api/master/chains", {})[1]["chains"], ["HypnoMix stock", "MyMaster"])
            self.assertTrue(MC.delete("MyMaster"))
            self.assertEqual(MC.handle_get("/api/master/chain", {"name": "MyMaster"})[0], 404)

    def test_stock_is_described(self):
        t = MC.describe(MC.STOCK)
        for w in ("Tone (EQ Eight)", "Glue (Glue Compressor)", "Tame (Multiband Dynamics) [off]", "Limiter (Limiter)"):
            self.assertIn(w, t)


class Patch(unittest.TestCase):
    def test_main_has_the_chain_column_wired(self):
        tpl = {"patcher": {"boxes": [{"box": {"id": "obj-1", "text": "plugin~"}}, {"box": {"id": "obj-2", "text": "plugout~"}}],
                           "lines": []}}
        p = P.build_patch(tpl, "main")["patcher"]
        boxes = {b["box"]["id"]: b["box"] for b in p["boxes"]}
        js = next(i for i, b in boxes.items() if b.get("text") == "js hypnomix_master.js")
        into = {l["patchline"]["source"][0] for l in p["lines"] if l["patchline"]["destination"][0] == js}
        texts = {boxes[i].get("text") for i in into}
        for t in ("prepend val 0", "prepend val 1", "deferlow", "prepend param hm_target", "prepend param hm_ceiling",
                  "prepend param hm_mode", "prepend pick", "prepend tplname", "t build", "t match", "t save", "live.thisdevice"):
            self.assertIn(t, texts)
        for l in p["lines"]:
            self.assertIn(l["patchline"]["source"][0], boxes)
            self.assertIn(l["patchline"]["destination"][0], boxes)
        right = max(b["presentation_rect"][0] + b["presentation_rect"][2] for b in boxes.values() if b.get("presentation"))
        self.assertLessEqual(right, p["devicewidth"])
        track = P.build_patch({"patcher": {"boxes": [{"box": {"id": "obj-1", "text": "plugin~"}}, {"box": {"id": "obj-2", "text": "plugout~"}}],
                                           "lines": []}}, "track")["patcher"]
        self.assertFalse(any(b["box"].get("text") == "js hypnomix_master.js" for b in track["boxes"]))



class DefaultRackPreset(unittest.TestCase):
    """Live loads the user's default rack preset into a new rack: Build must start from an empty rack."""
    def test_preset_chains_are_removed_or_emptied(self):
        _jscheck.need_runner(self)
        js = MC.script()
        for no_delete in ("false", "true"):
            out = run(js, """
NO_DELETE_CHAIN = %s;
var make = MAKE["Audio Effect Rack"];
MAKE["Audio Effect Rack"] = function () { var d = make(); d.chains.push({name: "My preset", devices: [MAKE["Limiter"](), MAKE["Utility"]()], id: NEXT++});
    d.chains.push({name: "Other", devices: [MAKE["Utility"]()], id: NEXT++}); return d; };
bang(); build();
var rack = MAIN.devices[0];
print_(rack.chains.map(function (c) { return c.devices.length; }));
""" % no_delete)
            counts = out[0]
            self.assertEqual(sum(1 for n in counts if n == 6), 1, counts)       # one chain holds the six stages
            self.assertTrue(all(n in (0, 6) for n in counts), counts)           # nothing from the preset is left
            if no_delete == "false":
                self.assertEqual(counts, [6])

if __name__ == "__main__":
    unittest.main()
