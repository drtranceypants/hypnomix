#!/usr/bin/env python3
"""The mastering chain built into HypnomixMain: Live's own devices in a rack on Main, that you edit like any rack.

  hypnomix probe chains                 the chain templates you can build (the stock one and the ones you saved)
  hypnomix probe chains show NAME       what a template builds, device by device
  hypnomix probe chains delete NAME     forget a saved template

In Live, HypnomixMain (on Main) has a Mastering chain column:

  Build chain    puts an Audio Effect Rack called "Hypnomix Master" just before HypnomixMain, holding the chosen
                 template's devices. They are Live's own devices: open the rack and change anything (move, swap,
                 add, remove, switch off). Pressing Build again asks before it replaces the rack.
  Match target   plays (or keeps playing) and listens to Main after the chain, then turns the Limiter's Gain until the
                 loudness lands on the song card's Target LUFS (three or four rounds, about 8 s each). Play the
                 loudest part of the song. Works with any chain before HypnomixMain that has a Limiter in it.
  Save           keeps whatever is before HypnomixMain (your edited Hypnomix Master, or a rack of your own) as a
                 template under the name you type. Live's own devices and racks are kept with every setting;
                 plug-ins and Max for Live devices cannot be rebuilt by Live's API and are listed as left out.
                 Saved templates live in ~/.hypnomix/master-chains/ (one .json each; the app must be running).

While the chain is the one hypnomix built (the rack is called "Hypnomix Master"), it follows the song card: the
Ceiling sets the Limiter's ceiling and the Limiter character (clean, punch, loud) sets its lookahead and release and
the Glue Compressor's attack. A rack of your own is never changed except by Match target (the Limiter's Gain).

The stock template, in order, with why each stage is there (every gain starts at 0 dB, so the chain starts neutral
and you add only what the song needs):

  1 Tone (EQ Eight)            low cut 12 dB/oct at 25 Hz (rumble you cannot hear but the limiter reacts to),
                               then a low shelf 90 Hz, bells at 300 Hz (mud) and 3 kHz (presence or harshness) and a
                               high shelf at 10 kHz (air), all at 0 dB, ready to move
  2 Glue (Glue Compressor)     2:1, attack 30 ms (the drums' attack gets through), release Auto, threshold -12 dB,
                               Range 3 dB so it can never squash more than 3 dB
  3 Tame (Multiband Dynamics)  switched off: switch it on when one band jumps out in places (harsh highs, boomy lows)
  4 Warmth (Saturator)         switched off: Soft Sine, 1.5 dB drive, 30 % wet, for a little density
  5 Width (Utility)            bass mono below 120 Hz, width 100 %, DC filter on
  6 Limiter (Limiter)          ceiling from the song card (true peak where Live offers it), gain 0 dB until you press
                               Match target, lookahead and release from the card's character
"""
import json, re, sys
from pathlib import Path

RACK = "Hypnomix Master"
STOCK_NAME = "hypnomix stock"

# One stage per device. "set": [names Live may use for the parameter, value, how]: "raw" sets Live's own value
# (switches, menu positions), "disp" sets it so Live displays that number (Hz, dB, ms, %), "item" picks the menu item
# whose text matches (or the nearest number).
_BANDS = [  # (type, Hz, Q): EQ Eight types 1 low cut 12, 2 low shelf, 3 bell, 5 high shelf
    (1, 25, 0.71), (2, 90, 0.71), (3, 300, 0.9), (3, 3000, 0.9), (5, 10000, 0.71)]


def _eq():
    s = []
    for i in range(1, 9):
        if i <= len(_BANDS):
            t, f, q = _BANDS[i - 1]
            s += [[[f"{i} Filter On A"], 1, "raw"], [[f"{i} Filter Type A"], t, "raw"], [[f"{i} Frequency A"], f, "disp"],
                  [[f"{i} Gain A"], 0, "disp"], [[f"{i} Resonance A", f"{i} Q A"], q, "disp"]]
        else:
            s.append([[f"{i} Filter On A"], 0, "raw"])
    return s


STOCK = {
    "name": STOCK_NAME,
    "about": "Live's own devices, recommended order, every gain at 0 dB: add only what the song needs",
    "stages": [
        {"device": "EQ Eight", "name": "Tone", "on": 1, "set": _eq(),
         "why": "low cut 25 Hz; shelves and bells at 0 dB, ready to move"},
        {"device": "Glue Compressor", "name": "Glue", "on": 1,
         "set": [[["Ratio"], 2, "item"], [["Attack"], 30, "item"], [["Release"], "Auto", "item"],
                 [["Threshold"], -12, "disp"], [["Range"], 3, "disp"], [["Output", "Makeup"], 0, "disp"],
                 [["Dry/Wet"], 100, "disp"], [["Peak Clip In", "Soft Clip", "Clip"], 0, "raw"]],
         "why": "2:1, slow attack, auto release, never more than 3 dB"},
        {"device": "Multiband Dynamics", "name": "Tame", "on": 0,
         "set": [[["Amount", "Global Amount"], 30, "disp"]],
         "why": "off: switch on when one band jumps out in places"},
        {"device": "Saturator", "name": "Warmth", "on": 0,
         "set": [[["Type"], "Soft Sine", "item"], [["Drive"], 1.5, "disp"], [["Dry/Wet"], 30, "disp"],
                 [["Output"], -1, "disp"]],
         "why": "off: a little density when the song wants it"},
        {"device": "Utility", "name": "Width", "on": 1,
         "set": [[["Bass Mono"], 1, "raw"], [["Bass Freq", "Bass Mono Freq", "Bass Frequency"], 120, "disp"],
                 [["Stereo Width", "Width"], 100, "disp"], [["DC Filter"], 1, "raw"]],
         "why": "bass mono below 120 Hz, DC filter"},
        {"device": "Limiter", "name": "Limiter", "on": 1,
         "set": [[["Input Gain", "Gain"], 0, "disp"], [["Mode"], "True Peak", "item"],
                 [["Auto Release", "Auto"], 1, "raw"]],
         "why": "ceiling from the song card; gain set by Match target"},
    ],
}

# what the song card's Limiter character does to a chain hypnomix built
CHARACTER = {
    "clean": {"lookahead": 6, "auto_release": 1, "glue_attack": 30},
    "punch": {"lookahead": 3, "auto_release": 1, "glue_attack": 30},
    "loud": {"lookahead": 1.5, "auto_release": 0, "glue_attack": 10},
}

# Live's class names → the name insert_device takes (when the device was renamed in the set)
INSERT_NAMES = {
    "Eq8": "EQ Eight", "FilterEQ3": "EQ Three", "ChannelEq": "Channel EQ", "GlueCompressor": "Glue Compressor",
    "Compressor2": "Compressor", "MultibandDynamics": "Multiband Dynamics", "Limiter": "Limiter", "Gate": "Gate",
    "StereoGain": "Utility", "Saturator": "Saturator", "DrumBuss": "Drum Buss", "Roar": "Roar", "Overdrive": "Overdrive",
    "Pedal": "Pedal", "Tube": "Dynamic Tube", "Redux2": "Redux", "Erosion": "Erosion", "AutoFilter": "Auto Filter",
    "AutoPan": "Auto Pan", "Chorus2": "Chorus-Ensemble", "PhaserNew": "Phaser-Flanger", "Reverb": "Reverb",
    "Hybrid": "Hybrid Reverb", "Delay": "Delay", "Echo": "Echo", "SpectrumAnalyzer": "Spectrum", "Tuner": "Tuner",
    "Amp": "Amp", "Cabinet": "Cabinet", "Vocoder": "Vocoder", "Corpus": "Corpus", "FrequencyShifter": "Frequency Shifter",
    "Resonator": "Resonators", "Vinyl": "Vinyl Distortion", "AudioEffectGroupDevice": "Audio Effect Rack",
    "SpectralResonator": "Spectral Resonator", "SpectralTime": "Spectral Time", "Shifter": "Shifter",
}


def home():
    from hypnomix.core import paths
    d = paths.HOME / "master-chains"
    return d


def _slug(name):
    s = re.sub(r"[^A-Za-z0-9 _.-]+", "", str(name)).strip()[:60]
    return s or "my chain"


def names():
    d = home()
    saved = sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []
    return [STOCK_NAME] + [n for n in saved if n != STOCK_NAME]


def load(name):
    if name == STOCK_NAME:
        return STOCK
    f = home() / f"{_slug(name)}.json"
    if not f.exists():
        raise KeyError(name)
    return json.loads(f.read_text(encoding="utf-8"))


def save(name, chain):
    name = _slug(name)
    if name == STOCK_NAME:
        raise ValueError("that name belongs to the stock template: choose another")
    if not isinstance(chain, dict) or not isinstance(chain.get("devices"), list) or not chain["devices"]:
        raise ValueError("nothing to save: put the chain just before HypnomixMain on Main")
    chain = dict(chain, name=name)
    d = home()
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{name}.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(chain, indent=1), encoding="utf-8")
    from hypnomix.core.atomic import replace as atomic_replace
    atomic_replace(tmp, f)
    return {"name": name, "file": str(f), "devices": count(chain["devices"]), "skipped": chain.get("skipped", [])}


def delete(name):
    f = home() / f"{_slug(name)}.json"
    if name == STOCK_NAME or not f.exists():
        return False
    f.unlink()
    return True


def count(devs):
    return sum(1 + sum(count(c.get("devices", [])) for c in d.get("chains", [])) for d in devs)


def describe(chain):
    """A template, device by device, for people."""
    out = [f"{chain.get('name', '?')}" + (f": {chain['about']}" if chain.get("about") else "")]
    if "stages" in chain:
        for i, s in enumerate(chain["stages"], 1):
            out.append(f"  {i} {s['name']} ({s['device']}){'' if s.get('on', 1) else ' [off]'}  {s.get('why', '')}")
    else:
        def walk(devs, ind):
            for d in devs:
                on = next((p["v"] for p in d.get("params", []) if p["n"] == "Device On"), 1)
                out.append(f"{ind}{d.get('name') or d.get('cls')} ({INSERT_NAMES.get(d.get('cls'), d.get('cls'))})"
                           + ("" if on else " [off]"))
                for c in d.get("chains", []):
                    out.append(f"{ind}  chain {c.get('name', '')}")
                    walk(c.get("devices", []), ind + "    ")
        walk(chain.get("devices", []), "  ")
    for s in chain.get("skipped", []):
        out.append(f"  left out: {s}")
    return "\n".join(out)


# ---------------------------------------------------------------- the app's side
def handle_get(path, q):
    if path == "/api/master/chains":
        return 200, {"chains": names()}
    if path == "/api/master/chain":
        try:
            return 200, load(q.get("name", STOCK_NAME))
        except KeyError:
            return 404, {"error": "no such template"}
    return None


def handle_post(path, body):
    if path == "/api/master/chain":
        try:
            return 200, save(body.get("name", ""), body.get("chain"))
        except ValueError as e:
            return 400, {"error": str(e)}
    if path == "/api/master/chain/delete":
        return 200, {"deleted": delete(str(body.get("name", "")))}
    return None


# ---------------------------------------------------------------- the device's script (Max's JavaScript is ES5)
JS = r"""// hypnomix master chain (js): builds, saves and loudness-matches the mastering chain before HypnomixMain on Main.
autowatch = 1;
inlets = 1;
outlets = 2;            // 0: status text   1: the template menu
var BASE = "http://127.0.0.1:__APP__";
var RACK = __RACK__;
var STOCK = __STOCK__;
var CHARACTER = __CHARACTER__;
var INSERT_NAMES = __INSERT__;
var LABELS = __LABELS__;                  // the label Live shows for each song-card control -> its hm_ name
var st = {ready: false, readyAt: 0, list: [STOCK.name], pick: 0, name: "", card: {}, confirmAt: 0, v0: 0, v1: 0,
          match: null, song: null};

function now() { return new Date().getTime(); }
function str(x) { return (x instanceof Array) ? x.join(" ") : String(x); }
function say(t) { outlet(0, "set", t); }

function bang() {
    if (st.ready) return;
    st.ready = true; st.readyAt = now();
    try { readCard(); } catch (e) { }
    fillMenu([STOCK.name]);
    refreshList();
}
var dead = false, reqs = [];             // once Live frees the device nothing may touch it again
function notifydeleted() {
    dead = true;
    try { initTask.cancel(); } catch (e) { }
    for (var i = 0; i < reqs.length; i++) { try { reqs[i].abort(); } catch (e) { } }
    reqs = [];
}
var initTask = new Task(function () {
    if (dead) return;
    if (st.ready) return;
    try { var me = new LiveAPI("this_device"); if (me.id && me.id != "0") bang(); } catch (e) { }
}, this);
initTask.schedule(1500);

function fillMenu(list) {
    st.list = list;
    outlet(1, "clear");
    for (var i = 0; i < list.length; i++) outlet(1, "append", list[i]);
    st.pick = Math.min(st.pick, list.length - 1);
    outlet(1, "set", st.pick);
}
function get(path, done) {
    var r = new XMLHttpRequest(); reqs.push(r); if (reqs.length > 8) reqs.shift();
    r.open("GET", BASE + path);
    r.onreadystatechange = function () {
        if (dead || this.readyState != 4) return;
        var d = null;
        try { d = JSON.parse(this.responseText); } catch (e) { d = null; }
        done(d);
    };
    r.send();
}
function post(path, body, done) {
    var r = new XMLHttpRequest(); reqs.push(r); if (reqs.length > 8) reqs.shift();
    r.open("POST", BASE + path);
    r.onreadystatechange = function () {
        if (dead || this.readyState != 4) return;
        var d = null;
        try { d = JSON.parse(this.responseText); } catch (e) { d = null; }
        if (done) done(d);
    };
    r.send(JSON.stringify(body));
}
function refreshList() { get("/api/master/chains", function (d) { if (d && d.chains && d.chains.length) fillMenu(d.chains); }); }
function pick(i) { st.pick = Math.max(0, Math.min(st.list.length - 1, parseInt(i))); }
function tplname() { st.name = arrayfromargs(arguments).join(" "); }

// ---------------------------------------------------------------- where things are
function track() { return new LiveAPI("this_device canonical_parent"); }
function myIndex(t) {
    var me = new LiveAPI("this_device"), n = t.getcount("devices");
    for (var i = 0; i < n; i++) if (new LiveAPI(t.unquotedpath + " devices " + i).id == me.id) return i;
    return n;
}
function ours(t, idx) {                    // the rack hypnomix built, just before HypnomixMain
    if (idx < 1) return null;
    var d = new LiveAPI(t.unquotedpath + " devices " + (idx - 1));
    return (str(d.get("name")) == RACK && parseInt(d.get("can_have_chains"))) ? d : null;
}
function params(d) {
    var n = d.getcount("parameters"), out = [];
    for (var i = 0; i < n; i++) out.push(new LiveAPI(d.unquotedpath + " parameters " + i));
    return out;
}
function find(d, names) {
    var ps = params(d), want = [], i, j;
    for (i = 0; i < names.length; i++) want.push(String(names[i]).toLowerCase());
    for (j = 0; j < want.length; j++)
        for (i = 0; i < ps.length; i++) {
            var nm = str(ps[i].get("name")).toLowerCase(), on = str(ps[i].get("original_name")).toLowerCase();
            if (nm == want[j] || on == want[j]) return ps[i];
        }
    return null;
}
function num(s) {                          // "1.20 kHz" -> 1200, "0.2 s" -> 200 (ms), "-inf dB" -> -999
    s = String(s);
    if (s.indexOf("inf") >= 0) return s.indexOf("-") >= 0 ? -999 : 999;
    var m = s.match(/-?[0-9]*\.?[0-9]+/);
    if (!m) return NaN;
    var x = parseFloat(m[0]);
    if (/k\s*hz|\dk\b/i.test(s)) x *= 1000;
    else if (/[0-9.]\s*s\s*$/.test(s) && !/ms\s*$/.test(s)) x *= 1000;
    return x;
}
function shown(p, raw) { return str(p.call("str_for_value", raw)); }
function setRaw(p, x) {
    var lo = parseFloat(p.get("min")), hi = parseFloat(p.get("max"));
    p.set("value", Math.max(lo, Math.min(hi, x)));
}
function setDisp(p, target) {              // the raw value Live displays as `target`, by bisection
    var lo = parseFloat(p.get("min")), hi = parseFloat(p.get("max"));
    if (parseInt(p.get("is_quantized"))) return setItem(p, target);
    var up = num(shown(p, hi)) >= num(shown(p, lo));
    for (var k = 0; k < 40; k++) {
        var mid = (lo + hi) / 2, v = num(shown(p, mid));
        if ((v < target) == up) lo = mid; else hi = mid;
    }
    var best = Math.abs(num(shown(p, lo)) - target) <= Math.abs(num(shown(p, hi)) - target) ? lo : hi;
    p.set("value", best);
}
function setItem(p, target) {              // a menu: the item with that text, or the nearest number
    var items = p.get("value_items"), lo = parseFloat(p.get("min")), best = -1, bestD = 1e9, i;
    if (!(items instanceof Array) || !items.length) {
        items = [];
        for (i = lo; i <= parseFloat(p.get("max")); i++) items.push(shown(p, i));
    }
    for (i = 0; i < items.length; i++) {
        var s = String(items[i]);
        if (typeof target == "string") {
            if (s.toLowerCase() == target.toLowerCase()) { best = i; break; }
            if (best < 0 && s.length == 1 && s.toLowerCase() == target.charAt(0).toLowerCase()) best = i;   // "A" = Auto
            if (best < 0 && s.toLowerCase().indexOf(target.toLowerCase()) >= 0) best = i;
        } else {
            var x = num(s), d = (x > 0 && target > 0) ? Math.abs(Math.log(x / target)) : Math.abs(x - target);
            if (!isNaN(x) && d < bestD) { bestD = d; best = i; }
        }
    }
    if (best < 0) return false;
    p.set("value", lo + best);
    return true;
}
function apply(d, row, miss, label) {      // one [names, value, how] row of a stage
    var p = find(d, row[0]);
    if (!p) { miss.push(label + ": " + row[0][0]); return; }
    try {
        if (row[2] == "raw") setRaw(p, row[1]);
        else if (row[2] == "item") { if (setItem(p, row[1]) === false) miss.push(label + ": " + row[0][0] + " " + row[1]); }
        else setDisp(p, row[1]);
    } catch (e) { miss.push(label + ": " + row[0][0] + " (" + e + ")"); }
}
function insert(parent, devName, idx) {    // a stock device into a track or chain; null when Live refuses
    var before = parent.getcount("devices");
    try { parent.call("insert_device", devName, idx); } catch (e) { return null; }
    if (parent.getcount("devices") <= before) return null;
    return new LiveAPI(parent.unquotedpath + " devices " + idx);
}
function rename(d, nm) { try { d.set("name", nm); } catch (e) { } }
function clearRack(rack, miss) {           // remove what a default rack preset brought: chains, or at least their devices
    var n = rack.getcount("chains"), i;
    for (i = n - 1; i >= 0; i--) { try { rack.call("delete_chain", i); } catch (e) { } }
    n = rack.getcount("chains");
    for (i = 0; i < n; i++) {
        var ch = new LiveAPI(rack.unquotedpath + " chains " + i);
        for (var k = ch.getcount("devices") - 1; k >= 0; k--) { try { ch.call("delete_device", k); } catch (e) { } }
    }
    if (n > 1) miss.push(RACK + " kept " + (n - 1) + " empty chain(s) from your default rack preset");
}

// ---------------------------------------------------------------- Build chain
function build() {
    if (!st.ready) return;
    var t = track(), idx = myIndex(t), old = ours(t, idx);
    if (old && now() - st.confirmAt > 5000) {
        st.confirmAt = now();
        say("A Hypnomix Master rack is already here. Press Build again within 5 s to replace it (your edits go).");
        return;
    }
    st.confirmAt = 0;
    var nm = st.list[st.pick] || STOCK.name;
    if (nm == STOCK.name) return buildWith(STOCK);
    say("Loading " + nm + " from the hypnomix app…");
    get("/api/master/chain?name=" + encodeURIComponent(nm), function (d) {
        if (!d || d.error) { say("Could not load " + nm + (d && d.error ? ": " + d.error : ": is the hypnomix app running?")); return; }
        buildWith(d);
    });
}
function buildWith(tpl) {
    var t = track(), idx = myIndex(t), old = ours(t, idx), miss = [];
    if (old) { t.call("delete_device", idx - 1); idx -= 1; }
    var rack = insert(t, "Audio Effect Rack", idx), chain;
    if (rack) {
        rename(rack, RACK);
        clearRack(rack, miss);                    // Live loads the user's default rack preset: start empty
        if (!rack.getcount("chains")) {
            try { rack.call("insert_chain", 0); } catch (e) { }
            if (!rack.getcount("chains")) { try { rack.call("insert_chain"); } catch (e2) { } }
        }
        chain = rack.getcount("chains") ? new LiveAPI(rack.unquotedpath + " chains 0") : null;
        if (chain) rename(chain, tpl.name || "chain");
    }
    if (!chain) { say("This Live cannot build racks from Max for Live (needs Live 12.3 or later)."); return; }
    var n = 0, i;
    if (tpl.stages) {
        for (i = 0; i < tpl.stages.length; i++) {
            var s = tpl.stages[i], d = insert(chain, s.device, n);
            if (!d) { miss.push(s.device + " (Live refused it)"); continue; }
            n++;
            rename(d, s.name);
            for (var k = 0; k < s.set.length; k++) apply(d, s.set[k], miss, s.name);
            var on = find(d, ["Device On"]);
            if (on) on.set("value", s.on ? 1 : 0);
        }
        try { readCard(); } catch (e) { }          // the card as it is in Live right now
        followCard(true);
    } else {
        n = restore(chain, tpl.devices || [], miss);
    }
    say("Built " + (tpl.name || "the chain") + ": " + n + " devices in " + RACK + ", ceiling " + st.card.ceiling + " dB." +
        (miss.length ? " Not set: " + miss.slice(0, 4).join("; ") + (miss.length > 4 ? " …" : "") : " Open the rack to edit it."));
}
function restore(parent, devs, miss) {     // a saved template: devices with every value, racks with their chains
    var n = 0;
    for (var i = 0; i < devs.length; i++) {
        var s = devs[i], want = INSERT_NAMES[s.cls] || s.cls, d = insert(parent, want, n);
        if (!d) { miss.push((s.name || s.cls) + " (Live refused it)"); continue; }
        n++;
        if (s.name) rename(d, s.name);
        if (s.chains && parseInt(d.get("can_have_chains"))) {
            clearRack(d, miss);                            // a default rack preset may have filled it
            var reuse = d.getcount("chains") == 1 &&       // one empty chain left: use it first
                new LiveAPI(d.unquotedpath + " chains 0").getcount("devices") == 0;
            for (var c = 0; c < s.chains.length; c++) {
                var before = d.getcount("chains"), at = before;
                if (c == 0 && reuse) at = 0;
                else {
                    try { d.call("insert_chain", before); } catch (e) { }
                    if (d.getcount("chains") <= before) { try { d.call("insert_chain"); } catch (e2) { } }
                    if (d.getcount("chains") <= before) { miss.push((s.name || s.cls) + " chain " + (c + 1)); continue; }
                }
                var ch = new LiveAPI(d.unquotedpath + " chains " + at);
                if (s.chains[c].name) rename(ch, s.chains[c].name);
                restore(ch, s.chains[c].devices || [], miss);
            }
        }
        var ps = params(d), byName = {};
        for (var k = 0; k < ps.length; k++) byName[str(ps[k].get("original_name"))] = ps[k];
        for (k = 0; k < (s.params || []).length; k++) {
            var p = byName[s.params[k].n];
            if (!p) continue;
            try { if (parseInt(p.get("is_enabled")) !== 0) p.set("value", s.params[k].v); } catch (e) { }
        }
    }
    return n;
}

// ---------------------------------------------------------------- Save
function snap(d, skipped) {
    var cls = str(d.get("class_name")), o = {cls: cls, name: str(d.get("name")), params: []};
    if (/^(Plugin|AuPlugin|Mx)/.test(cls)) { skipped.push(o.name + " (" + cls.replace(/Device.*$/, "") + ")"); return null; }
    var ps = params(d);
    for (var i = 0; i < ps.length; i++) o.params.push({n: str(ps[i].get("original_name")), v: parseFloat(ps[i].get("value"))});
    if (parseInt(d.get("can_have_chains"))) {
        o.chains = [];
        var nc = d.getcount("chains");
        for (var c = 0; c < nc; c++) {
            var ch = new LiveAPI(d.unquotedpath + " chains " + c), devs = [], nd = ch.getcount("devices");
            for (var k = 0; k < nd; k++) { var x = snap(new LiveAPI(ch.unquotedpath + " devices " + k), skipped); if (x) devs.push(x); }
            o.chains.push({name: str(ch.get("name")), devices: devs});
        }
        if (o.name != RACK) skipped.push(o.name + ": macro mappings (Live's API cannot rebuild them)");
    }
    return o;
}
function capture() {
    var t = track(), idx = myIndex(t), devs = [], skipped = [];
    for (var i = 0; i < idx; i++) { var x = snap(new LiveAPI(t.unquotedpath + " devices " + i), skipped); if (x) devs.push(x); }
    if (devs.length == 1 && devs[0].name == RACK && devs[0].chains && devs[0].chains.length == 1)
        devs = devs[0].chains[0].devices;     // our own rack: keep what is inside it
    return {devices: devs, skipped: skipped};
}
function save() {
    if (!st.ready) return;
    var nm = st.name.replace(/^\s+|\s+$/g, "") || "my chain", c = capture();
    if (!c.devices.length) { say("Nothing to save: put the chain just before HypnomixMain on Main."); return; }
    post("/api/master/chain", {name: nm, chain: {about: "saved in Live", devices: c.devices, skipped: c.skipped}}, function (d) {
        if (!d) { say("Start the hypnomix app to save templates."); return; }
        if (d.error) { say(d.error); return; }
        say("Saved " + d.name + " (" + d.devices + " devices)" + (d.skipped.length ? "; left out: " + d.skipped.join(", ") : "") + ".");
        refreshList();
    });
}

// ---------------------------------------------------------------- the song card
// Live reports HypnomixMain's controls by their labels ("Ceiling dBTP"), and their first values can arrive
// before this script is ready: read them from Live once it is
function readCard() {
    var me = new LiveAPI("this_device"), n = me.getcount("parameters");
    for (var i = 0; i < n; i++) {
        var p = new LiveAPI("this_device parameters " + i), on = str(p.get("original_name")), sh = str(p.get("name"));
        var nm = LABELS[on] || LABELS[sh] || on;
        if (nm.indexOf("hm_") == 0) st.card[nm.replace(/^hm_/, "")] = parseFloat(p.get("value"));
    }
    var mi = st.card.mode;
    if (typeof mi == "number" && !isNaN(mi)) st.card.mode = MODES[Math.round(mi)] || "clean";
}
function param(nm, v) {
    nm = String(nm).replace(/^hm_/, "");
    st.card[nm] = v;
    if (st.ready && now() - st.readyAt > 3000 && (nm == "ceiling" || nm == "mode")) followCard(false);
}
var MODES = ["clean", "punch", "loud"];
function followCard(quiet) {               // only the rack hypnomix built follows the card
    var t = track(), rack = ours(t, myIndex(t));
    if (!rack) return;
    var miss = [], lim = findDevice(rack, "Limiter"), glue = findDevice(rack, "GlueCompressor");
    var mode = st.card.mode, ch = CHARACTER[typeof mode == "number" ? MODES[Math.round(mode)] : mode] || CHARACTER.clean;
    if (lim) {
        if (st.card.ceiling !== undefined) apply(lim, [["Ceiling"], parseFloat(st.card.ceiling), "disp"], miss, "Limiter");
        apply(lim, [["Lookahead"], ch.lookahead, "item"], miss, "Limiter");
        apply(lim, [["Auto Release", "Auto"], ch.auto_release, "raw"], miss, "Limiter");
    }
    if (glue) apply(glue, [["Attack"], ch.glue_attack, "item"], miss, "Glue");
    if (!quiet) say("Chain follows the song card: ceiling " + st.card.ceiling + " dB, " + (MODES.indexOf(mode) >= 0 ? mode : "clean") + ".");
}
function findDevice(d, cls, last) {        // the last device of that class in a rack or track, looking inside racks
    var hit = null, n, i, c;
    if (parseInt(d.get("can_have_chains"))) {
        n = d.getcount("chains");
        for (c = 0; c < n; c++) {
            var ch = new LiveAPI(d.unquotedpath + " chains " + c), nd = ch.getcount("devices");
            for (i = 0; i < nd; i++) {
                var x = new LiveAPI(ch.unquotedpath + " devices " + i);
                if (str(x.get("class_name")) == cls) hit = x;
                var y = parseInt(x.get("can_have_chains")) ? findDevice(x, cls) : null;
                if (y) hit = y;
            }
        }
    }
    return hit;
}
function limiterBefore() {
    var t = track(), idx = myIndex(t), hit = null;
    for (var i = 0; i < idx; i++) {
        var d = new LiveAPI(t.unquotedpath + " devices " + i);
        if (str(d.get("class_name")) == "Limiter") hit = d;
        var y = parseInt(d.get("can_have_chains")) ? findDevice(d, "Limiter") : null;
        if (y) hit = y;
    }
    return hit;
}

// ---------------------------------------------------------------- Match target
function val(i, x) { if (i == 0) st.v0 = x; else if (i == 1) st.v1 = x; }
function mainFader() {
    try {
        var vol = new LiveAPI("this_device canonical_parent mixer_device volume");
        var s = str(vol.call("str_for_value", parseFloat(vol.get("value"))));
        return s.indexOf("inf") >= 0 ? -120 : parseFloat(s);
    } catch (e) { return 0; }
}
function match() {
    if (!st.ready) return;
    if (st.match) { st.match = null; say("Match target stopped."); return; }
    var lim = limiterBefore();
    if (!lim) { say("No Limiter before HypnomixMain: build the chain, or add a Limiter to yours."); return; }
    var g = find(lim, ["Gain", "Input Gain"]);
    if (!g) { say("This Limiter has no Gain control hypnomix knows."); return; }
    try { readCard(); } catch (e) { }
    var target = parseFloat(st.card.target);
    if (isNaN(target)) target = -14;
    st.match = {lim: lim, gain: g, target: target, blocks: [], round: 0, wait: 10};
    if (!st.song) st.song = new LiveAPI("live_set");
    if (!parseInt(st.song.get("is_playing"))) st.song.call("start_playing");
    say("Matching " + target + " LUFS: play the loudest part (round 1, 8 s)…");
}
function measured(b) {                     // BS.1770 gating over 400 ms blocks (4 x 100 ms)
    var w = [], i, j;
    for (i = 3; i < b.length; i++) w.push((b[i] + b[i - 1] + b[i - 2] + b[i - 3]) / 4);
    var keep = [], s = 0;
    for (i = 0; i < w.length; i++) if (w[i] > 0 && -0.691 + 10 * Math.log(w[i]) / Math.LN10 > -70) keep.push(w[i]);
    if (!keep.length) return -120;
    for (i = 0; i < keep.length; i++) s += keep[i];
    var rel = -0.691 + 10 * Math.log(s / keep.length) / Math.LN10 - 10, s2 = 0, n2 = 0;
    for (j = 0; j < keep.length; j++) if (-0.691 + 10 * Math.log(keep[j]) / Math.LN10 > rel) { s2 += keep[j]; n2++; }
    return n2 ? -0.691 + 10 * Math.log(s2 / n2) / Math.LN10 : -120;
}
function blk() {
    if (dead) return;
    var m = st.match;
    if (!m) return;
    if (!st.song) st.song = new LiveAPI("live_set");
    if (!parseInt(st.song.get("is_playing"))) { st.match = null; say("Match target stopped: Live stopped playing."); return; }
    if (m.wait > 0) { m.wait--; return; }        // let the Limiter settle after a change
    m.blocks.push(st.v0 * st.v0 + st.v1 * st.v1);
    if (m.blocks.length < 80) return;
    var L = measured(m.blocks) + mainFader(), diff = m.target - L;
    m.round++; m.blocks = []; m.wait = 10;
    var cur = num(shown(m.gain, parseFloat(m.gain.get("value"))));
    if (L < -60) { st.match = null; say("Main is silent: play the song, then press Match target."); return; }
    if (Math.abs(diff) < 0.4 || m.round >= 4) {
        st.match = null;
        say("Main measured " + L.toFixed(1) + " LUFS (target " + m.target + "); Limiter gain " + cur.toFixed(1) + " dB." +
            (Math.abs(diff) >= 0.4 ? " The Limiter is working hard: louder needs less dynamics, or a lower target." : ""));
        return;
    }
    var step = diff > 0 ? Math.min(diff * (m.round > 1 ? 1.3 : 1), 6) : Math.max(diff, -6);
    setDisp(m.gain, cur + step);
    say("Round " + m.round + ": " + L.toFixed(1) + " LUFS, gain " + cur.toFixed(1) + " → " + (cur + step).toFixed(1) + " dB…");
}
"""


def _labels():
    from hypnomix.app.probe import CONTROLS
    return {lab: n for m in CONTROLS.values() for n, lab, _, _, _, _ in m}


def script(app_port=8791):
    return (JS.replace("__APP__", str(app_port)).replace("__RACK__", json.dumps(RACK))
            .replace("__STOCK__", json.dumps(STOCK)).replace("__CHARACTER__", json.dumps(CHARACTER))
            .replace("__INSERT__", json.dumps(INSERT_NAMES)).replace("__LABELS__", json.dumps(_labels())))


# ---------------------------------------------------------------- the patch: a column on HypnomixMain
X0 = 648          # where the column starts on the device (HypnomixMain is widened to fit it)
WIDTH = 172


def add_to_patch(P, thisdev, route_vals, blk_out, card_pres):
    """Add the chain's script and controls to HypnomixMain's patch (P is probe.Patch). route_vals: the boxes that
    send `val 0 x` and `val 1 x`; blk_out: the deferred block clock; card_pres: the song card's `prepend param` boxes."""
    js = P.add("js hypnomix_master.js", 1, 2, ["", ""], x=1200, y=60)
    P.wire(thisdev, 0, js, 0)
    for b in route_vals:
        P.wire(b, 0, js, 0)
    P.wire(blk_out, 0, js, 0)
    for b in card_pres:
        P.wire(b, 0, js, 0)

    def box(cls, rect, prect, **kw):
        P.n += 1
        bid = f"obj-{P.n}"
        b = {"id": bid, "maxclass": cls, "patching_rect": [float(v) for v in rect], "presentation": 1,
             "presentation_rect": [float(v) for v in prect]}
        b.update(kw)
        P.boxes.append({"box": b})
        return bid

    x = X0
    box("live.comment", [1200, 20, 120, 18], [x, 4, WIDTH, 14], numinlets=1, numoutlets=0, text="Mastering chain")
    menu = box("umenu", [1200, 100, 160, 22], [x, 22, WIDTH, 18], numinlets=1, numoutlets=3,
               outlettype=["int", "", ""], parameter_enable=0, items=["hypnomix stock"], fontsize=10.0)
    P.wire(js, 1, menu, 0)
    pk = P.add("prepend pick", 1, 1, [""], x=1200, y=130)
    P.wire(menu, 0, pk, 0)
    P.wire(pk, 0, js, 0)
    for word, label, px, pw in (("build", "Build chain", x, 84), ("match", "Match target", x + 88, 84)):
        b = box("message", [1300 + px - x, 160, 70, 22], [px, 44, pw, 20], numinlets=2, numoutlets=1, outlettype=[""],
                text=label, fontsize=10.0, bgcolor=[0.32, 0.30, 0.26, 1.0], textcolor=[0.95, 0.93, 0.89, 1.0])
        w = P.add(f"t {word}", 1, 1, [""], x=1300 + px - x, y=190)
        P.wire(b, 0, w, 0)
        P.wire(w, 0, js, 0)
    te = box("textedit", [1200, 220, 120, 22], [x, 70, 124, 20], numinlets=1, numoutlets=4,
             outlettype=["", "int", "", ""], parameter_enable=0, keymode=1, fontsize=10.0, text="",
             hint="template name, e.g. my master")
    rt = P.add("route text", 1, 2, ["", ""], x=1200, y=250)
    pn = P.add("prepend tplname", 1, 1, [""], x=1200, y=280)
    P.wire(te, 0, rt, 0)
    P.wire(rt, 0, pn, 0)
    P.wire(rt, 1, pn, 0)
    P.wire(pn, 0, js, 0)
    sv = box("message", [1340, 220, 50, 22], [x + 128, 70, 44, 20], numinlets=2, numoutlets=1, outlettype=[""],
             text="Save", fontsize=10.0, bgcolor=[0.32, 0.30, 0.26, 1.0], textcolor=[0.95, 0.93, 0.89, 1.0])
    ws = P.add("t save", 1, 1, [""], x=1340, y=250)
    P.wire(sv, 0, ws, 0)
    P.wire(ws, 0, js, 0)
    status = box("comment", [1200, 320, 170, 60], [x, 96, WIDTH, 70], numinlets=1, numoutlets=0, fontsize=9.0,
                 text="Build puts Live's own devices in a rack before this device; edit them freely.",
                 textcolor=[0.63, 0.60, 0.56, 1.0], linecount=5)
    P.wire(js, 0, status, 0)
    return js


# ---------------------------------------------------------------- CLI (hypnomix probe chains)
def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="hypnomix probe chains", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", default="list", choices=["list", "show", "delete"])
    ap.add_argument("name", nargs="?", default=STOCK_NAME)
    a = ap.parse_args(argv)
    if a.action == "list":
        for n in names():
            print(n + ("   (built in)" if n == STOCK_NAME else ""))
        print(f"\nsaved templates: {home()}")
    elif a.action == "show":
        try:
            print(describe(load(a.name)))
        except KeyError:
            sys.exit(f"no template called {a.name!r}: `hypnomix probe chains` lists them")
    else:
        print("deleted" if delete(a.name) else f"no saved template called {a.name!r}")


if __name__ == "__main__":
    main(sys.argv[1:])
