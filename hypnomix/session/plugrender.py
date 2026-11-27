#!/usr/bin/env python3
"""Render tracks from a Live set offline, faster than real time, through their real plug-in chains: the
third-party VST3 and Audio Unit plug-ins on each track are loaded with the settings saved in the set and the
track's audio is played through them in order, then through the track's fader and pan. Live can be closed.

Uses Spotify's pedalboard library to host the plug-ins (an optional extra, GPL-3.0, kept separate so HypnoMix
stays MIT): `uv pip install -e ".[plugins]"` or `pip install pedalboard`.

Usage:
    hypnomix plugrender SET.als [--tracks "Lead" "Bass"] [--group "Vocals"] [--out DIR] [--sr 44100]
                       [--no-stock] [--list] [--check]

  --list      just list each track's chain and whether each device can be rendered (no plug-ins loaded)
  --check     load every plug-in, restore its saved settings and report what worked (nothing rendered)
  --no-stock  third-party plug-ins only: Live's own devices are left out (and listed as left out)
  --tracks / --group   which tracks (default: every audio and group track that plays)

For each track: its clips are rendered like `hypnomix render` (clip gain, fades, warps), then every device
that is switched on runs in order:
  VST3 and AU plug-ins     loaded from the standard plug-in folders of this system (/Library/Audio/Plug-Ins and
                           ~/Library/Audio/Plug-Ins on a Mac; Common Files\\VST3 on Windows; ~/.vst3 and /usr/lib/vst3
                           on Linux), found by name (AUs, Mac only, by their component codes), with the settings
                           Live saved in the set
  Live's own devices       only those HypnoMix models: Utility gain, Compressor and Glue Compressor (also
                           with a sidechain from another track), Limiter (a hard ceiling), Gate and EQ Eight
                           (HypnoMix's own models in session/devmodel.py: plain stereo EQ Eight only, and a
                           Gate that is not in flip mode and has no sidechain; a device in a mode the model
                           does not cover is left out and the report says so). Every other Live device
                           (Saturator, reverbs, racks…) is skipped, and the report says so
Then the fader (or its volume automation) and pan. A group track is its playing tracks summed, then its own
chain and fader.

Writes <out>/<track>.wav (stereo, 32-bit float) and plugrender.json: per track, which devices ran, which were
skipped and why.

Limits, honestly:
  - sends to return tracks are not rendered (returns, the Main track and its chain are out of scope)
  - automation of plug-in or device parameters is ignored: every device plays at its saved setting
  - VST2 plug-ins are not supported (pedalboard hosts VST3 and AU only); Max for Live devices are skipped;
    MIDI tracks (instruments) are not rendered
  - an AU that cannot be loaded is retried as the VST3 of the same plug-in when its saved state is a JUCE
    state (many free plug-ins); the report says when that happened
  - each plug-in is first loaded in a separate process, so one that crashes is reported and skipped, never
    taking the render down with it. A plug-in that fails to load or restore is skipped with a warning and the
    track still renders without it
  - clips render as mono (like `hypnomix render`), fed to the chain as stereo; the pan law is an
    approximation of Live's (centre is unity, constant power)
  - the compressor models are approximations of Live's (see `hypnomix sidechain`)
"""
from hypnomix.extras import hint as extra_hint
import argparse, gzip, json, math, os, plistlib, re, struct, subprocess, sys, tempfile
from hypnomix.core.gz import read_gz
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from hypnomix.core.paths import out_at

HOME = Path.home()


def plugin_folders(platform=None, home=None):
    """(VST3 folders, Audio Unit folders) for this operating system, the person's own folder first on a Mac. Audio Units
    exist on a Mac only."""
    from hypnomix.session.plugins import system_folders
    platform = platform or sys.platform
    f = system_folders(platform, home)
    if platform == "darwin":
        return list(reversed(f["vst3"])), list(reversed(f["au"]))
    return list(f["vst3"]), []


VST3_DIRS, AU_DIRS = plugin_folders()
STOCK = {"StereoGain": "Utility (gain)", "Compressor2": "Compressor", "GlueCompressor": "Glue Compressor",
         "Limiter": "Limiter", "Eq8": "EQ Eight", "Gate": "Gate"}          # the Live devices hypnomix has a model of
RACKS = {"AudioEffectGroupDevice", "InstrumentGroupDevice", "MidiEffectGroupDevice", "DrumGroupDevice"}
JUCE_XML_MAGIC = 0x21324356          # JUCE AudioProcessor::copyXmlToBinary ("VC2!" little-endian)
UNSET = 0.1234567687                 # the value Live writes for plug-in parameters it has no value for
JUCE_B64 = ".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+"


def v(n, p, default=None):
    e = n.find(p) if n is not None else None
    return e.get("Value") if e is not None and e.get("Value") is not None else default


def have_pedalboard():
    try:
        import pedalboard  # noqa: F401
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- state blobs (the bytes pedalboard's raw_state takes)
def juce_b64encode(b):
    """JUCE MemoryBlock::toBase64Encoding: '<size>.' then 6 bits per character, least significant bits first,
    in JUCE's own alphabet (not RFC 4648)."""
    n = len(b)
    bits = int.from_bytes(b, "little")
    return f"{n}." + "".join(JUCE_B64[(bits >> (6 * i)) & 63] for i in range((n * 8 + 5) // 6))


def juce_b64decode(s):
    n, dot, body = s.strip().partition(".")
    if not dot or not n.isdigit():
        raise ValueError("not a JUCE base64 block (no '<size>.' prefix)")
    n, bits = int(n), 0
    for i, c in enumerate(body):
        k = JUCE_B64.find(c)
        if k < 0:
            raise ValueError(f"bad character {c!r} in a JUCE base64 block")
        bits |= k << (6 * i)
    return (bits & ((1 << (8 * n)) - 1)).to_bytes(n, "little")


def xml_to_binary(xml):
    """JUCE copyXmlToBinary: magic, UTF-8 length, the XML, a NUL."""
    body = xml.encode("utf-8")
    return struct.pack("<II", JUCE_XML_MAGIC, len(body)) + body + b"\0"


def binary_to_xml(blob):
    if len(blob) < 9:
        raise ValueError("state too short")
    magic, size = struct.unpack("<II", blob[:8])
    if magic != JUCE_XML_MAGIC:
        raise ValueError("not a JUCE XML state (wrong magic number)")
    return blob[8:8 + size].decode("utf-8")


def vst3_state(processor, controller=None):
    """The blob JUCE's VST3 host reads in setStateInformation: <VST3PluginState> with the component (processor)
    and edit-controller streams, each JUCE-base64 encoded, wrapped by copyXmlToBinary."""
    x = '<?xml version="1.0" encoding="UTF-8"?> <VST3PluginState>'
    if processor:
        x += f"<IComponent>{juce_b64encode(processor)}</IComponent>"
    if controller:
        x += f"<IEditController>{juce_b64encode(controller)}</IEditController>"
    return xml_to_binary(x + "</VST3PluginState>")


def vst3_parts(blob):
    """(processor bytes, controller bytes or None) from a VST3 raw_state blob."""
    root = ET.fromstring(binary_to_xml(blob))
    get = lambda tag: juce_b64decode(root.find(tag).text or "0.") if root.find(tag) is not None else None
    return get("IComponent"), get("IEditController")


def au_state(buffer):
    """Live saves an AU's state as its ClassInfo property list (XML); JUCE's AU host reads a property list too
    (it writes binary ones). Re-encoded as a binary plist so it matches what the host itself produces."""
    return plistlib.dumps(plistlib.loads(buffer), fmt=plistlib.FMT_BINARY)


def hexbuf(el):
    txt = re.sub(r"\s", "", el.text or "") if el is not None else ""
    return bytes.fromhex(txt) if txt else b""


def fourcc(n):
    try:
        return struct.pack(">I", int(n) & 0xFFFFFFFF).decode("mac_roman")
    except Exception:
        return ""


# ---------------------------------------------------------------- reading a chain from the set
def device_info(d):
    """What a device is and what is needed to play it: a dict with kind (vst3 / au / vst2 / stock / m4l / rack /
    live), name, on, and for plug-ins the saved state."""
    on = v(d, "./On/Manual", "true") == "true"
    user = v(d, "./UserName") or ""
    info = dict(tag=d.tag, on=on, label=user, el=d)
    if d.tag == "PluginDevice":
        v3 = d.find("./PluginDesc/Vst3PluginInfo")
        if v3 is not None:
            pre = v3.find("./Preset/Vst3Preset")
            u = v3.find("./Uid") if v3.find("./Uid") is not None else (pre.find("./Uid") if pre is not None else None)
            uid = [int(v(u, f"./Fields.{i}", 0)) & 0xFFFFFFFF for i in range(4)]
            info.update(kind="vst3", name=v(v3, "./Name", "?"), uid="".join(f"{x:08X}" for x in uid),
                        processor=hexbuf(pre.find("./ProcessorState")) if pre is not None else b"",
                        controller=hexbuf(pre.find("./ControllerState")) if pre is not None else b"")
        else:
            v2 = d.find("./PluginDesc/VstPluginInfo")
            info.update(kind="vst2", name=v(v2, "./PlugName", "?"),
                        chunk=hexbuf(v2.find("./Preset/VstPreset/Buffer")) if v2 is not None else b"")
    elif d.tag == "AuPluginDevice":
        au = d.find("./PluginDesc/AuPluginInfo")
        info.update(kind="au", name=v(au, "./Name", "?"), maker=v(au, "./Manufacturer", ""),
                    codes=(fourcc(v(au, "./ComponentType", 0)), fourcc(v(au, "./ComponentSubType", 0)),
                           fourcc(v(au, "./ComponentManufacturer", 0))),
                    buffer=hexbuf(au.find("./Preset/AuPreset/Buffer")) if au is not None else b"")
    elif d.tag in STOCK:
        info.update(kind="stock", name=STOCK[d.tag])
    elif d.tag.startswith("MxDevice"):
        info.update(kind="m4l", name=user or "Max for Live device")
    elif d.tag in RACKS:
        info.update(kind="rack", name=user or d.tag)
    else:
        info.update(kind="live", name=d.tag)
    info["saved_params"] = saved_params(d) if info["kind"] in ("vst3", "au", "vst2") else {}
    return info


def saved_params(d):
    """{parameter name: normalised value} as Live saved them in the device's parameter list."""
    out = {}
    pl = d.find("./ParameterList")
    for p in (list(pl) if pl is not None else []):
        if p.tag != "PluginFloatParameter":
            continue
        nm, val = v(p, "./ParameterName"), v(p, "./ParameterValue/Manual")
        try:
            x = float(val)
        except (TypeError, ValueError):
            continue
        if nm and abs(x - UNSET) > 1e-9:          # Live's placeholder for a parameter it never read
            out[nm] = x
    return out


def plugin_state(info):
    """The raw_state bytes for a plug-in device, or b'' when there is nothing saved."""
    if info["kind"] == "vst3":
        return vst3_state(info["processor"], info["controller"]) if info["processor"] else b""
    if info["kind"] == "au":
        return au_state(info["buffer"]) if info["buffer"] else b""
    return b""


def chain_of(t):
    devs = t.find("./DeviceChain/DeviceChain/Devices")
    return [device_info(d) for d in (list(devs) if devs is not None else [])]


# ---------------------------------------------------------------- finding plug-in files
_AU_INDEX = None


def _tidy(d):
    """A folder as the person knows it: ~/Library/... for one under their home."""
    try:
        return "~/" + Path(d).relative_to(HOME).as_posix()
    except ValueError:
        return str(d)


def au_index():
    """[(path, type, subtype, manufacturer, plugin name)] for every installed Audio Unit bundle."""
    global _AU_INDEX
    if _AU_INDEX is None:
        _AU_INDEX = []
        for d in AU_DIRS:
            for comp in sorted(d.glob("*.component")) if d.exists() else []:
                try:
                    pl = plistlib.loads((comp / "Contents" / "Info.plist").read_bytes())
                except Exception:
                    continue
                for c in pl.get("AudioComponents") or []:
                    nm = str(c.get("name", ""))
                    _AU_INDEX.append((comp, c.get("type"), c.get("subtype"), c.get("manufacturer"),
                                      nm.split(": ", 1)[-1]))
    return _AU_INDEX


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def find_vst3(name):
    want = norm(name)
    cands = [p for d in VST3_DIRS if d.exists() for p in sorted(d.glob("*.vst3"))]
    if sys.platform != "darwin":                # Windows and Linux installers often put each maker's plug-ins in a folder of their own
        cands += [p for d in VST3_DIRS if d.exists() for p in sorted(d.glob("*/*.vst3"))]
    hit = [p for p in cands if norm(p.stem) == want]
    if not hit:
        for p in cands:                         # newer bundles list their classes in moduleinfo.json
            mi = p / "Contents" / "Resources" / "moduleinfo.json"
            try:
                classes = json.loads(mi.read_text(encoding="utf-8")).get("Classes", []) if mi.exists() else []
            except Exception:
                classes = []
            if any(norm(c.get("Name")) == want for c in classes):
                hit.append(p)
    return (hit[0], name) if hit else None


def find_au(info):
    t, st, m = info["codes"]
    idx = au_index()
    hit = [r for r in idx if (r[1], r[2], r[3]) == (t, st, m)] or [r for r in idx if norm(r[4]) == norm(info["name"])]
    return (hit[0][0], hit[0][4]) if hit else None


def locate(info):
    """(path, plugin name inside the bundle, format used, note) or None."""
    if info["kind"] == "vst3":
        r = find_vst3(info["name"])
        return (r[0], r[1], "vst3", "") if r else None
    if info["kind"] == "au":
        r = find_au(info)
        return (r[0], r[1], "au", "") if r else None
    return None


def juce_state_of_au(info):
    """The plug-in's own JUCE state inside a saved AU state, or None (not a JUCE plug-in)."""
    try:
        return plistlib.loads(info["buffer"]).get("jucePluginState")
    except Exception:
        return None


# ---------------------------------------------------------------- loading, safely
def _probe_main(job_file):
    """Child-process side of probe(): load, restore, report. Runs in its own process so a crash stays there."""
    job = json.loads(Path(job_file).read_text(encoding="utf-8"))
    import pedalboard
    res = dict(ok=False)
    p = pedalboard.load_plugin(job["path"], plugin_name=job.get("plugin_name") or None)
    res.update(loaded=True, instrument=bool(getattr(p, "is_instrument", False)))
    if job.get("state_file"):
        st = Path(job["state_file"]).read_bytes()
        p.raw_state = st
        back = p.raw_state
        set_params(p, job.get("set_params") or {})
        res["state_bytes"], res["readback_bytes"] = len(st), len(back)
        res["readback_same"] = back == st
        Path(job["state_file"] + ".back").write_bytes(back)
    res["params"] = {pp.name: float(pp.raw_value) for pp in p.parameters.values()}
    res["ok"] = True
    print("PROBE " + json.dumps(res))


def set_params(p, values):
    """Set parameters by their display name (normalised values)."""
    for pp in p.parameters.values():
        if pp.name in values:
            try:
                pp.raw_value = float(values[pp.name])
            except Exception:
                pass


def bypass_params(info):
    """A plug-in's own Bypass parameter as Live saved it. Some plug-ins save their state with Bypass on when the
    device was off in Live at some point; the value in Live's parameter list is the one Live plays."""
    return {k: x for k, x in info["saved_params"].items() if k.strip().lower() == "bypass"}


def probe(path, plugin_name, state, timeout=120, set_params_=None):
    """Load a plug-in and restore its state in a separate process. dict(ok, error, params, …)."""
    with tempfile.TemporaryDirectory(prefix="hypnomix-work-") as td:
        job = dict(path=str(path), plugin_name=plugin_name, set_params=set_params_ or {})
        if state:
            sp = Path(td) / "state.bin"
            sp.write_bytes(state)
            job["state_file"] = str(sp)
        jp = Path(td) / "job.json"
        jp.write_text(json.dumps(job), encoding="utf-8")
        try:
            pkg = str(Path(__file__).resolve().parents[2])
            env = dict(os.environ, PYTHONPATH=pkg + os.pathsep + os.environ.get("PYTHONPATH", ""))
            r = subprocess.run([sys.executable, "-m", "hypnomix.session.plugrender", "--probe", str(jp)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            return dict(ok=False, error=f"did not load within {timeout} s")
        line = next((l for l in (r.stdout or "").splitlines() if l.startswith("PROBE ")), None)
        if line:
            res = json.loads(line[6:])
            bp = Path(td) / "state.bin.back"
            if state and bp.exists():
                res["settings"] = settings_match(state, bp.read_bytes())
            return res
    if r.returncode < 0:
        return dict(ok=False, error=f"the plug-in crashed while loading (signal {-r.returncode})")
    tail = ((r.stderr or "").strip().splitlines() or ["no output"])[-1]
    return dict(ok=False, error=tail[-200:])


def juce_settings(blob):
    """{name: value} from the JUCE XML state inside a plug-in state blob (VST3 or AU), or None. Most JUCE
    plug-ins save their settings as XML attributes, which makes a restore checkable setting by setting."""
    try:
        if blob[:6] == b"bplist" or blob[:5] == b"<?xml":
            pl = plistlib.loads(blob)
            inner = pl.get("jucePluginState") or pl.get("data") or b""
        else:
            inner = vst3_parts(blob)[0] or b""
        i = inner.find(b"VC2!")
        if i < 0:
            return None
        root = ET.fromstring(binary_to_xml(inner[i:]))
    except Exception:
        return None
    out = {}
    for el in root.iter():
        for k, val in el.attrib.items():
            out[f"{el.tag}.{k}"] = val
    return out


def settings_match(sent, back):
    """dict(matched, compared, differ=[...]) between the settings handed to a plug-in and those it saves back;
    None when the state isn't readable (not a JUCE XML state)."""
    a, b = juce_settings(sent), juce_settings(back)
    if not a or b is None:
        return None
    same = lambda x, y: x == y or _close(x, y)
    keys = [k for k in a if k in b]
    differ = [f"{k.split('.', 1)[-1]}: {a[k]} -> {b[k]}" for k in keys if not same(a[k], b[k])]
    return dict(matched=len(keys) - len(differ), compared=len(a), differ=differ[:12])


def _close(x, y):
    try:
        return abs(float(x) - float(y)) <= 1e-4 * max(1.0, abs(float(x)))
    except ValueError:
        return False


def param_match(saved, params, tol=1e-3):
    """(matched, compared) between Live's saved parameter values and the plug-in's after restoring."""
    both = [k for k in saved if k in params]
    return sum(abs(saved[k] - params[k]) <= tol for k in both), len(both)


_PROBED = {}


def prepare(info, do_probe=True):
    """Find, probe and describe how a plug-in device will be played. Returns a plan dict:
    ok, path, plugin_name, fmt, state, note, error, check."""
    if info["kind"] == "vst2":
        return dict(ok=False, error="VST2 plug-in: not supported (pedalboard hosts VST3 and AU only)")
    loc = locate(info)
    state = plugin_state(info) if loc else b""
    tries = []
    if loc:
        tries.append((loc[0], loc[1], loc[2], state, ""))
    if info["kind"] == "au":                                   # AU missing or crashing: its VST3 twin, if JUCE
        js = juce_state_of_au(info)
        twin = find_vst3(info["name"]) if js else None
        if twin:
            tries.append((twin[0], twin[1], "vst3", vst3_state(js), "played as the VST3 of the same plug-in "
                          "(the AU did not load; its saved JUCE state was handed to the VST3)"))
    if not tries:
        looked = VST3_DIRS if info["kind"] == "vst3" else AU_DIRS
        where = "VST3 folders" if info["kind"] == "vst3" else "Audio Unit folders"
        if not looked:
            return dict(ok=False, error=f"not installed ({where} exist on a Mac only)")
        return dict(ok=False, error=f"not installed (looked in the {where}: {', '.join(_tidy(d) for d in looked)})")
    errs = []
    for path, pname, fmt, st, note in tries:
        if not do_probe:
            return dict(ok=True, path=path, plugin_name=pname, fmt=fmt, state=st, note=note, check=None,
                        set_params=bypass_params(info) if fmt == info["kind"] else {})
        fixp = bypass_params(info) if fmt == info["kind"] else {}
        key = (str(path), pname, st, tuple(sorted(fixp.items())))
        res = _PROBED.get(key) or probe(path, pname, st, set_params_=fixp)
        _PROBED[key] = res
        if res.get("ok"):
            if res.get("instrument"):
                return dict(ok=False, error="an instrument, not an effect: not rendered")
            m, n = param_match(info["saved_params"], res.get("params") or {})
            return dict(ok=True, path=path, plugin_name=pname, fmt=fmt, state=st, note=note, set_params=fixp,
                        check=dict(matched=m, compared=n, readback_same=res.get("readback_same"),
                                   state_bytes=res.get("state_bytes", 0), settings=res.get("settings")))
        errs.append(f"{fmt.upper()} {path.name}: {res.get('error')}")
    return dict(ok=False, error="; ".join(errs))


def load(plan):
    import pedalboard
    p = pedalboard.load_plugin(str(plan["path"]), plugin_name=plan["plugin_name"] or None)
    if plan["state"]:
        p.raw_state = plan["state"]
    set_params(p, plan.get("set_params") or {})
    return p


# ---------------------------------------------------------------- Live's own devices (hypnomix's models)
def _comp_gain(x, sr, c):
    """Linear gain per sample for compressor settings c, with detector audio x (mono, at sr). The model runs at
    the sidechain module's analysis rate and the gain curve is brought back to sr."""
    from hypnomix.engineer import sidechain as SC
    xd = SC.to_sr(x, sr) if sr != SC.SR else x
    gr = SC.gain_reduction(SC.detector(xd, c), c)
    if sr != SC.SR:
        gr = np.interp(np.arange(len(x)) * (SC.SR / sr), np.arange(len(gr)), gr)
    return 10 ** (gr[: len(x)] / 20)


def run_stock(info, y, sr, sidechain_audio):
    """Apply one of Live's devices that HypnoMix models. y is (n, 2). Returns (y, note or None)."""
    from hypnomix.engineer import devices as D, sidechain as SC
    d = info["el"]
    if d.tag == "StereoGain":
        return y * float(D.manual(d, "Gain", 1.0) or 1.0), None          # Utility's gain is linear
    if d.tag == "Limiter":
        gain, ceil = D.manual(d, "Gain", 0.0), D.manual(d, "Ceiling", -0.3)
        lim = 10 ** (ceil / 20)
        return np.clip(y * 10 ** (gain / 20), -lim, lim), "modelled as a hard ceiling (no release)"
    if d.tag in ("Compressor2", "GlueCompressor"):
        c = SC.read_glue(d) if d.tag == "GlueCompressor" else SC.read_compressor(d)
        _, outgain = D.comp_settings(d)
        note = None
        det = y.mean(1)
        if c.get("sc_on") and "Track." in (c.get("source_target") or ""):
            if sidechain_audio is None:
                note = "its sidechain source could not be rendered: compressing its own signal instead"
                c["sc_gain_db"] = 0.0
            else:
                det = sidechain_audio[: len(y)]
                det = np.pad(det, (0, len(y) - len(det)))
        else:
            c["sc_gain_db"] = 0.0
        g = _comp_gain(det, sr, c) * 10 ** (outgain / 20)
        wet = float(c.get("dry_wet", 1.0) or 1.0)
        return y * (wet * g + (1 - wet))[:, None], note
    if d.tag == "Eq8":
        from hypnomix.session import devmodel
        return devmodel.eq8(y, sr, d)
    if d.tag == "Gate":
        from hypnomix.session import devmodel
        return devmodel.gate(y, sr, d)
    return y, "no model: this device is not modelled"


# ---------------------------------------------------------------- the set
class SetRenderer:
    """Renders tracks of one set through their chains, caching each track at each tap (pre FX, post FX, post
    mixer) so sidechain sources and group members are only rendered once."""

    plugins = True

    def __init__(self, als, sr=44100, no_stock=False, do_probe=True, log=None, plugins=True, sample_als=None):
        from hypnomix.session import automation as aa
        from hypnomix.session import render as R
        self.R, self.aa = R, aa
        self.als, self.sr, self.no_stock, self.do_probe = str(als), sr, no_stock, do_probe
        self.sample_als = str(sample_als or als)       # relative sample paths resolve against the original set's folder
        self.plugins = plugins                         # False: real plug-ins are left out, only hypnomix's models play
        self.root = aa.load(als).getroot()
        self.spb = 60.0 / float(R.v(self.root, ".//Tempo/Manual"))
        self.tracks = [t for t in self.root.find(".//Tracks")]
        self.by_id = {t.get("Id"): t for t in self.tracks}
        end, _ = R.song_end(self.root)
        ends = [float(R.v(c, "./CurrentEnd")) for t in self.tracks if t.tag == "AudioTrack" for c in t.iter("AudioClip")]
        end = end if end > 0 else max(ends, default=0.0)
        self.N = int((end + 8) * self.spb * sr)
        self.cache, self.report, self.warn = {}, {}, []
        self.log = log or (lambda s: None)
        self._busy = set()

    def name(self, t):
        return self.R.v(t, "./Name/EffectiveName") or "?"

    def find(self, name):
        hits = [t for t in self.tracks if self.name(t).lower() == name.lower()]
        return hits[0] if hits else None

    def members(self, g):
        return [t for t in self.tracks if self.R.v(t, "./TrackGroupId") == g.get("Id")]

    @staticmethod
    def playing(t):
        return v(t, "./DeviceChain/Mixer/Speaker/Manual", "true") != "false"

    # -- stages
    def pre_fx(self, t):
        key = (t.get("Id"), "pre")
        if key in self.cache:
            return self.cache[key]
        y = None
        if t.tag == "AudioTrack":
            w = []
            m = self.R.render_track(t, self.sample_als, self.spb, self.N, self.sr, None, 0, w)
            self.warn += w
            y = np.repeat(m[:, None], 2, axis=1) if np.any(m) else None
        elif t.tag == "GroupTrack":
            parts = []
            for k in self.members(t):
                if not self.playing(k):
                    continue
                if k.tag == "MidiTrack":
                    self.warn.append(f"{self.name(t)}: MIDI track '{self.name(k)}' is left out of the group sum")
                    continue
                if k.tag in ("AudioTrack", "GroupTrack"):
                    yk = self.post_mixer(k)
                    if yk is not None:
                        parts.append(yk)
            y = np.sum(parts, axis=0) if parts else None
        self.cache[key] = y
        return y

    def post_fx(self, t):
        key = (t.get("Id"), "fx")
        if key in self.cache:
            return self.cache[key]
        if key in self._busy:                          # a sidechain loop: give up on this one
            return None
        self._busy.add(key)
        try:
            y = self.pre_fx(t)
            y = None if y is None else self.run_chain(t, y)
        finally:
            self._busy.discard(key)
        self.cache[key] = y
        return y

    def post_mixer(self, t):
        key = (t.get("Id"), "mix")
        if key in self.cache:
            return self.cache[key]
        y = self.post_fx(t)
        y = None if y is None else self.mixer(t, y)
        self.cache[key] = y
        return y

    def tap(self, target):
        """Audio for a sidechain source like 'AudioIn/Track.12/PostFxOut' (mono)."""
        m = re.search(r"Track\.(\d+)/?(\w*)", target or "")
        t = self.by_id.get(m.group(1)) if m else None
        if t is None:
            return None
        stage = m.group(2).lower()
        y = self.pre_fx(t) if stage.startswith("pre") else self.post_mixer(t) if "mixer" in stage else self.post_fx(t)
        return None if y is None else y.mean(1)

    # -- the chain and the mixer
    def run_chain(self, t, y):
        name = self.name(t)
        rows = self.report.setdefault(name, dict(type=t.tag, devices=[]))["devices"]
        rows.clear()
        for info in chain_of(t):
            row = dict(device=info["name"], label=info["label"], kind=info["kind"], id=info["el"].get("Id"), tag=info["tag"])
            rows.append(row)
            if not info["on"]:
                row["status"] = "skipped: switched off"
                continue
            if info["kind"] == "stock":
                if self.no_stock:
                    row["status"] = "skipped: --no-stock"
                    continue
                sc = None
                if info["tag"] in ("Compressor2", "GlueCompressor"):
                    from hypnomix.engineer import sidechain as SC
                    c = SC.read_glue(info["el"]) if info["tag"] == "GlueCompressor" else SC.read_compressor(info["el"])
                    if c.get("sc_on") and "Track." in (c.get("source_target") or ""):
                        sc = self.tap(c["source_target"])
                        row["sidechain"] = c.get("source_name") or c["source_target"]
                y, note = run_stock(info, y, self.sr, sc)
                row["status"] = ("skipped: " + note if note and note.startswith("no model") else
                                 "rendered (HypnoMix model)" + (f": {note}" if note else ""))
                continue
            if info["kind"] in ("vst3", "au", "vst2"):
                if not self.plugins:
                    row["status"] = "skipped: real plug-ins are only played with --plugins"
                    continue
                if not have_pedalboard():
                    row["status"] = "skipped: pedalboard is not installed (" + extra_hint("plugins") + ")"
                    continue
                plan = prepare(info, self.do_probe)
                if not plan["ok"]:
                    row["status"] = f"skipped: {plan['error']}"
                    self.warn.append(f"{name}: '{info['name']}' skipped ({plan['error']})")
                    continue
                try:
                    p = load(plan)
                    out = p.process(np.ascontiguousarray(y.T, dtype=np.float32), float(self.sr), reset=True)
                    out = np.asarray(out, dtype=np.float64).T
                    if out.ndim == 1:
                        out = out[:, None]
                    if out.shape[1] == 1:
                        out = np.repeat(out, 2, axis=1)
                    y = np.pad(out[:, :2], ((0, max(0, len(y) - len(out))), (0, 0)))[: len(y)]
                    ck = plan.get("check") or {}
                    row["status"] = "rendered" + (f" ({plan['note']})" if plan["note"] else "")
                    row["plugin"] = f"{plan['fmt'].upper()} {Path(plan['path']).name}"
                    if ck.get("compared"):
                        row["saved_params_match"] = f"{ck['matched']}/{ck['compared']}"
                    if not np.all(np.isfinite(y)):
                        y = np.nan_to_num(y)
                        self.warn.append(f"{name}: '{info['name']}' produced invalid samples (zeroed)")
                except Exception as e:
                    row["status"] = f"skipped: failed while playing ({type(e).__name__}: {str(e)[:120]})"
                    self.warn.append(f"{name}: '{info['name']}' failed while playing; left out")
                continue
            why = {"m4l": "Max for Live devices are not rendered", "rack": "racks are not rendered",
                   "live": "no HypnoMix model of this Live device"}[info["kind"]]
            row["status"] = f"skipped: {why}"
        return y

    def mixer(self, t, y):
        mx = t.find("./DeviceChain/Mixer")
        vol = float(v(mx, "./Volume/Manual", 1.0))
        g = np.full(len(y), vol)
        try:                                            # volume automation wins over the fader, as in Live
            envs, _ = self.aa.envelopes(t)
            env = next((e for lab, e, _ in envs if lab == "Volume"), None)
            if env is not None:
                _, pts = self.aa.events(env)
                if len(pts) > 1:
                    tb, vb = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
                    g = np.interp(np.arange(len(y)) / self.sr / self.spb, tb, vb)
        except Exception:
            pass
        pan = float(v(mx, "./Pan/Manual", 0.0))
        a = (np.clip(pan, -1, 1) + 1) * math.pi / 4
        gl, gr = math.cos(a) * math.sqrt(2), math.sin(a) * math.sqrt(2)
        rep = self.report.setdefault(self.name(t), dict(type=t.tag, devices=[]))
        rep["fader_db"] = round(20 * math.log10(max(vol, 1e-9)), 2)
        rep["pan"] = round(pan, 2)
        return y * g[:, None] * np.array([gl, gr])


def pick_tracks(root, tracks=None, group=None):
    ts = list(root.find(".//Tracks"))
    nm = lambda t: v(t, "./Name/EffectiveName") or "?"
    pick = [t for t in ts if t.tag in ("AudioTrack", "GroupTrack")]
    if group:
        g = [t for t in ts if t.tag == "GroupTrack" and nm(t).lower() == group.lower()]
        if not g:
            sys.exit(f"no group {group!r}; groups: {[nm(t) for t in ts if t.tag == 'GroupTrack']}")
        pick = [t for t in pick if v(t, "./TrackGroupId") == g[0].get("Id")]
    if tracks:
        want = {x.lower() for x in tracks}
        pick = [t for t in ts if nm(t).lower() in want]
    return pick


def describe(info):
    """One line of --list: what the device is and whether it can be rendered (no plug-in is loaded)."""
    lab = info["name"] + (f" [{info['label']}]" if info["label"] and info["label"] != info["name"] else "")
    if not info["on"]:
        return lab, "off: skipped"
    k = info["kind"]
    if k == "stock":
        return lab, "Live device: HypnoMix model"
    if k == "vst2":
        return lab, "VST2: not supported"
    if k in ("vst3", "au"):
        loc = locate(info)
        if loc:
            return lab, f"{k.upper()}: found ({loc[0].name})" + ("" if have_pedalboard() else ", needs pedalboard")
        if k == "au" and juce_state_of_au(info) and find_vst3(info["name"]):
            return lab, "AU not installed: will try its VST3"
        return lab, f"{k.upper()}: not installed"
    return lab, {"m4l": "Max for Live: skipped", "rack": "rack: skipped", "live": "Live device: no model, skipped"}[k]


# ---------------------------------------------------------------- for `hypnomix ab`: device-change previews
DEVICE_TOOLS = ("devices", "duck", "sidechain", "distortion")


def devices_of(t):
    d = t.find("./DeviceChain/DeviceChain/Devices")
    return list(d) if d is not None else []


def changed_devices(before_t, after_t):
    """The devices of one track's chain (elements of the AFTER version) that a fix changed or added, by device Id."""
    old = {d.get("Id"): ET.tostring(d) for d in devices_of(before_t)}
    return [d for d in devices_of(after_t) if old.get(d.get("Id")) != ET.tostring(d)]


def device_preview(f, orig, scan, sd, sr, hx, before_cache, plugins=False):
    """A before / after pair for one device-change finding, from HypnoMix's own models of Live's devices (and, with
    `plugins`, real plug-ins through pedalboard): the track rendered through its chain in the set as it is and in a
    temporary copy with only this fix applied. Returns dict(before, after, note, model) stereo arrays, or
    dict(note=why) when it cannot be previewed honestly: the changed device has no model, is a plug-in that is not
    played, is in a rack, or the fix changes something outside the track's own chain (a send, another track)."""
    track = f.get("host") if f["tool"] == "sidechain" else f.get("track")
    sr_ = SetRenderer(orig, sr, plugins=plugins)
    t = sr_.find(track or "")
    if t is None or t.tag not in ("AudioTrack", "GroupTrack"):
        kind = {"ReturnTrack": "a return track (fed by sends, which are not rendered)",
                "MidiTrack": "a MIDI track (instruments are not rendered)"}.get(getattr(t, "tag", ""), "not an audio or group track")
        return dict(note=f"no preview: '{track}' is {kind}")
    tmp_root = Path(sd) / "ab"
    tmp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=tmp_root, prefix="hypnomix-ab-tmp-") as td:
        tmp = Path(td) / f"{orig.stem} (ab preview {re.sub(r'[^A-Za-z0-9-]', '', f['id'])}).als"
        if f["tool"] == "sidechain":
            args = ["sidechain", orig, "--host", f["host"], "--apply", tmp] + (["--glue-to-compressor"] if f.get("glue") else [])
        else:
            args = [f["tool"], orig, "--apply", tmp, "--ids", f["id"]]
            if f["tool"] in ("devices", "duck") and (sd / "raw" / "names" / "names.json").exists():
                args += ["--names", sd / "raw" / "names" / "names.json"]
            if f["tool"] == "distortion" and scan.get("mix"):
                args += ["--mix", scan["mix"]]
        code, txt = hx(*args)
        if code != 0 or not tmp.exists():
            return dict(note="preview failed: the fix could not be built (" + txt.strip()[-120:] + ")")
        after_r = SetRenderer(tmp, sr, plugins=plugins, sample_als=orig)
        ta = after_r.find(track)
        changed = changed_devices(t, ta) if ta is not None else []
        if not changed:
            return dict(note="no preview: this fix changes something outside the track's own device chain "
                             "(a send, a return or another track), which is not rendered here")
        infos = [device_info(d) for d in changed]
        blocked = []
        for i in infos:
            if i["kind"] == "stock":
                continue
            if i["kind"] in ("vst3", "au") and plugins and have_pedalboard():
                continue
            why = {"vst3": "a plug-in: previews play real plug-ins only with --plugins (and pedalboard)",
                   "au": "a plug-in: previews play real plug-ins only with --plugins (and pedalboard)",
                   "vst2": "a VST2 plug-in, which is not supported", "m4l": "a Max for Live device, which is not rendered",
                   "rack": "a rack, whose inside is not rendered",
                   "live": "a Live device HypnoMix has no model of"}.get(i["kind"], "not modelled")
            blocked.append(f"'{i['name']}' is {why}")
        if blocked:
            return dict(note="no offline preview: " + "; ".join(blocked) + ". Apply this one fix into a new set "
                                                                         "(fix --approve) and listen in Live.")
        if track not in before_cache:
            y = sr_.post_mixer(t)
            before_cache[track] = (y, [r["device"] for r in sr_.report.get(track, {}).get("devices", [])
                                       if r["status"].startswith("skipped") and not r["status"].endswith("switched off")])
        b = after_r.post_mixer(ta)
        for r in after_r.report.get(track, {}).get("devices", []):       # a changed device that was left out of the render
            if r.get("id") in {d.get("Id") for d in changed} and r["status"].startswith("skipped"):
                return dict(note=f"no offline preview: '{r['device']}' {r['status'].replace('skipped: ', 'was left out: ')}")
    a, skipped = before_cache[track]
    if a is None or b is None:
        return dict(note="no preview: the track has no audio to render")
    names = sorted({STOCK[i["tag"]] for i in infos if i["kind"] == "stock"})
    parts = []
    if names:
        parts.append("a MODEL of Live's " + ", ".join(names) + ", not Live itself")
    if any(i["kind"] != "stock" for i in infos):
        parts.append("the real plug-in played through pedalboard")
    note = "the track through its chain (no sends): " + "; ".join(parts)
    others = [x for x in skipped if x not in {i["name"] for i in infos}]
    if others:
        note += "; not rendered: " + ", ".join(others[:4])
    return dict(before=a, after=b, note=note, model=bool(names))


def loudest_at(y, sr, span):
    """Centre (s) of the loudest `span` seconds: where a dynamics change is easiest to hear."""
    m = y.mean(1) if y.ndim > 1 else y
    blk = int(sr * 0.5)
    n = len(m) // blk
    if n < 2:
        return 0.0
    e = (m[: n * blk].reshape(n, blk) ** 2).mean(1)
    k = max(1, int(span / 0.5))
    s = np.convolve(e, np.ones(k), "valid")
    return (int(np.argmax(s)) + k / 2) * 0.5


# ---------------------------------------------------------------- command line
def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--probe":
        try:
            _probe_main(sys.argv[2])
        except Exception as e:
            print("PROBE " + json.dumps(dict(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}")))
        return
    ap = argparse.ArgumentParser(prog="hypnomix plugrender", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als")
    ap.add_argument("--tracks", nargs="*")
    ap.add_argument("--group")
    ap.add_argument("--out")
    ap.add_argument("--sr", type=int, default=44100)
    ap.add_argument("--no-stock", action="store_true", help="third-party plug-ins only")
    ap.add_argument("--list", action="store_true", help="list each chain and what can be rendered")
    ap.add_argument("--check", action="store_true", help="load every plug-in and restore its state; no render")
    a = ap.parse_args()

    root = ET.fromstring(read_gz(a.als))
    pick = pick_tracks(root, a.tracks, a.group)
    if not pick:
        sys.exit("no tracks match")
    nm = lambda t: v(t, "./Name/EffectiveName") or "?"

    if a.list:
        for t in pick:
            ch = chain_of(t)
            print(f"{nm(t)}  ({t.tag.replace('Track', '').lower()})" + ("" if ch else ": no devices"))
            for info in ch:
                lab, st = describe(info)
                print(f"    {lab[:44]:<44} {st}")
        print("(sends to return tracks are not rendered)")
        return

    if not have_pedalboard():
        print(f"NOTE: pedalboard is not installed ({extra_hint('plugins')}): plug-ins will be skipped, only Live's "
              "modelled devices and the mixer are rendered.", file=sys.stderr)

    if a.check:
        if not have_pedalboard():
            sys.exit("--check needs pedalboard: " + extra_hint("plugins"))
        rows, bad = [], 0
        for t in pick:
            for info in chain_of(t):
                if info["kind"] not in ("vst3", "au", "vst2"):
                    continue
                plan = prepare(info)
                ck = plan.get("check") or {}
                row = dict(track=nm(t), device=info["name"], on=info["on"], ok=plan["ok"],
                           error=plan.get("error"), note=plan.get("note"), **ck)
                if plan["ok"]:
                    row["plugin"] = f"{plan['fmt'].upper()} {Path(plan['path']).name}"
                rows.append(row)
                bad += not plan["ok"]
                if plan["ok"]:
                    m = (f"; {ck['matched']} of {ck['compared']} saved parameters read back the same"
                         if ck.get("compared") else "")
                    se = ck.get("settings")
                    if se:
                        m += f"; {se['matched']} of {se['compared']} settings in its own state read back the same"
                    elif ck.get("readback_same"):
                        m += "; its state reads back byte for byte"
                    st = f"OK  state restored ({ck.get('state_bytes', 0)} bytes){m}" + (f"; {plan['note']}" if plan["note"] else "")
                else:
                    st = f"FAIL {plan['error']}"
                print(f"{nm(t)[:22]:<22} {info['name'][:26]:<26} {'' if info['on'] else '(off) '}{st}")
        od = out_at(a.out, "plugrender", Path(a.als).stem)
        (od / "check.json").write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
        print(f"{len(rows) - bad} of {len(rows)} plug-in(s) load and restore → {od / 'check.json'}")
        return

    import soundfile as sf
    od = out_at(a.out, "plugrender", Path(a.als).stem)
    sr_ = SetRenderer(a.als, a.sr, a.no_stock, log=print)
    for t in pick:
        t2 = sr_.by_id.get(t.get("Id"))
        t2 = sr_.find(nm(t)) if t2 is None else t2
        if t2.tag not in ("AudioTrack", "GroupTrack"):
            print(f"{nm(t):<30} skipped: {t2.tag.replace('Track', '').lower()} tracks are not rendered")
            continue
        y = sr_.post_mixer(t2)
        if y is None or not np.any(y):
            print(f"{nm(t):<30} no audio")
            continue
        sf.write(str(od / (re.sub(r'[\\/:*?"<>|]', "-", nm(t)) + ".wav")), y.astype(np.float32), a.sr, subtype="FLOAT")
        rep = sr_.report.get(nm(t), {})
        ran = sum(r["status"].startswith("rendered") for r in rep.get("devices", []))
        skip = [r for r in rep.get("devices", []) if r["status"].startswith("skipped") and "switched off" not in r["status"]]
        print(f"{nm(t):<30} peak {20 * np.log10(np.abs(y).max() + 1e-9):6.1f} dBFS   {ran} device(s) rendered"
              + (f", {len(skip)} skipped" if skip else ""))
        for r in skip:
            print(f"    skipped {r['device']}: {r['status'][9:]}")
    (od / "plugrender.json").write_text(json.dumps(dict(set=str(a.als), sr=a.sr, tracks=sr_.report,
                                                         warnings=sorted(set(sr_.warn)),
                                                         not_rendered="sends to return tracks; the Main track"),
                                                    indent=1, default=str), encoding="utf-8")
    for w_ in sorted(set(sr_.warn)):
        print("  !", w_, file=sys.stderr)
    print("(sends to return tracks are not rendered)")
    print(f"→ {od}")


if __name__ == "__main__":
    main()
