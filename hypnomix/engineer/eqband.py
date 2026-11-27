"""One EQ band written onto a track of a Live set, on Live's own EQ Eight, into a NEW set.

Used by `hypnomix masking SET.als --apply NEW.als` (and so by `fix` for an approved frequency-fight finding): the
part that should give way gets a bell cut at the fight's frequency.

  - an EQ Eight already on the track is reused when it is switched on, in its plain stereo mode, and has a free band
    (one that is switched off, or a bell or shelf sitting at 0 dB); that band becomes the cut. Nothing else in it
    changes, and a band that is automated is never taken.
  - otherwise a new EQ Eight (Live's own default preset) goes at the END of the chain with just that one band
    set, named "Masking cut (HypnoMix)" so it can be found and removed.
  - a cut that is already there (an enabled bell near that frequency, at least three quarters as deep) is left alone
    and reported, so running the same fix twice changes nothing.

The new set is a copy: the original is never touched.
"""
import copy
import glob
import math
import xml.etree.ElementTree as ET
from pathlib import Path

DEVICE_NAME = "Masking cut (HypnoMix)"
BELL = 3                                         # EQ Eight band modes: 0 low cut 48, 1 low cut 12, 2 low shelf, 3 bell,
FLAT_OK = (2, 3, 5)                              # 4 notch, 5 high shelf, 6 high cut 12, 7 high cut 48
PRESET = "Core Library/Defaults/Audio Effects/EQ Eight.adv"


def find_template():
    """Live's own default EQ Eight (the preset Live loads when you drop one on a track), or None. The environment
    variable HYPNOMIX_EQ8_TEMPLATE can name another file (a Live preset or plain XML holding an <Eq8>)."""
    from hypnomix.core.gz import read_gz
    import os
    custom = os.environ.get("HYPNOMIX_EQ8_TEMPLATE")
    if custom:
        try:
            raw = read_gz(Path(custom).expanduser())
        except OSError:                              # plain XML, not gzipped
            raw = Path(custom).expanduser().read_bytes()
        el = ET.fromstring(raw)
        return el if el.tag == "Eq8" else el.find(".//Eq8")
    hits = glob.glob(f"/Applications/Ableton Live*/Contents/App-Resources/{PRESET}") + \
        glob.glob(f"C:/ProgramData/Ableton/Live*/Resources/{PRESET}")
    for p in sorted(hits, reverse=True):
        try:
            el = ET.fromstring(read_gz(p)).find(".//Eq8")
        except Exception:
            continue
        if el is not None:
            return el
    return None


def _v(el, path, default=None):
    e = el.find(path)
    return e.get("Value") if e is not None and e.get("Value") is not None else default


def _set(el, path, value):
    e = el.find(path)
    if e is None:
        raise ValueError(f"EQ Eight has no {path}")
    e.set("Value", value if isinstance(value, str) else repr(float(value)))


def automated_ids(root):
    """Ids of every control some automation envelope drives (those are never repurposed)."""
    return {e.get("Value") for e in root.iter("PointeeId") if e.get("Value")}


def band_a(d, i):
    return d.find(f"./Bands.{i}/ParameterA")


def band_info(b):
    return dict(on=_v(b, "./IsOn/Manual", "true") == "true", mode=int(float(_v(b, "./Mode/Manual", 3))),
                freq=float(_v(b, "./Freq/Manual", 1000)), gain=float(_v(b, "./Gain/Manual", 0)),
                q=float(_v(b, "./Q/Manual", 0.71)))


def band_automated(b, auto):
    return any((e.get("Id") or "") in auto for e in b.iter() if e.tag in ("AutomationTarget", "ModulationTarget"))


def usable(d):
    """An EQ Eight that is on and in plain stereo mode (band A is then the whole signal)."""
    return _v(d, "./On/Manual", "true") == "true" and int(float(_v(d, "./Mode", "0") or 0)) == 0


def already_cut(d, freq, gain_db):
    """The band of this EQ Eight that already does (about) this cut, as a number, or None."""
    for i in range(8):
        b = band_a(d, i)
        if b is None:
            continue
        s = band_info(b)
        if s["on"] and s["mode"] == BELL and abs(math.log2(max(s["freq"], 1) / freq)) <= 1 / 6 \
                and s["gain"] <= 0.75 * gain_db:
            return i + 1
    return None


def free_band(d, auto):
    """Index of a band that can take the cut, or None: switched off first, then a flat bell or shelf."""
    flat = None
    for i in range(8):
        b = band_a(d, i)
        if b is None or band_automated(b, auto):
            continue
        s = band_info(b)
        if not s["on"]:
            return i
        if flat is None and s["mode"] in FLAT_OK and abs(s["gain"]) < 0.05:
            flat = i
    return flat


def write_band(d, i, freq, gain_db, q):
    b = band_a(d, i)
    _set(b, "./IsOn/Manual", "true")
    _set(b, "./Mode/Manual", "3")
    _set(b, "./Freq/Manual", round(float(freq), 2))
    _set(b, "./Gain/Manual", round(float(gain_db), 2))
    _set(b, "./Q/Manual", round(float(q), 3))
    sel = d.find("./SelectedBand")
    if sel is not None:
        sel.set("Value", str(i))


def new_eq8(root, devs, template):
    """A fresh EQ Eight from the template, with new ids, appended at the end of the chain `devs`."""
    el = copy.deepcopy(template)
    nxt = root.find(".//NextPointeeId")
    nid = int(nxt.get("Value"))
    for e in el.iter():
        if e.tag in ("AutomationTarget", "ModulationTarget", "Pointee") and e.get("Id") is not None:
            e.set("Id", str(nid))
            nid += 1
    nxt.set("Value", str(nid))
    used = [int(x.get("Id")) for x in devs if (x.get("Id") or "").isdigit()]
    el.set("Id", str(max(used) + 1 if used else 0))
    un = el.find("./UserName")
    if un is not None:
        un.set("Value", DEVICE_NAME)
    devs.append(el)
    return el


def track_by_name(root, name):
    """The audio track called `name`, matching the name as a rendered file would carry it (slashes and the like
    become '-'). (track, why): why is set when there is none or more than one."""
    import re
    key = re.sub(r'[\\/:*?"<>|]', "-", name)
    hits = []
    for t in root.find(".//Tracks"):
        if t.tag != "AudioTrack":
            continue
        n = t.find("./Name/EffectiveName")
        if n is not None and (n.get("Value") == name or re.sub(r'[\\/:*?"<>|]', "-", n.get("Value") or "") == key):
            hits.append(t)
    if len(hits) == 1:
        return hits[0], None
    return None, (f"no audio track called '{name}' in this set" if not hits else f"{len(hits)} tracks are called '{name}'")


def apply_cut(root, track_name, freq, gain_db, q, template=None):
    """Write one cut on the named track. Returns (message, None) or (None, why it was not written)."""
    t, why = track_by_name(root, track_name)
    if t is None:
        return None, why
    devs = t.find("./DeviceChain/DeviceChain/Devices")
    if devs is None:
        return None, f"'{track_name}' has no device chain"
    eqs = [d for d in devs if d.tag == "Eq8"]
    for d in eqs:
        if usable(d):
            n = already_cut(d, freq, gain_db)
            if n:
                return None, f"already there: band {n} of the EQ Eight on '{track_name}' cuts about this"
    auto = automated_ids(root)
    for d in eqs:
        if usable(d):
            i = free_band(d, auto)
            if i is not None:
                write_band(d, i, freq, gain_db, q)
                return f"{track_name}: EQ Eight band {i + 1}: {gain_db:+.1f} dB at {freq:.0f} Hz (Q {q:g}), an existing EQ Eight", None
    template = template if template is not None else find_template()
    if template is None:
        return None, "Live's own EQ Eight preset was not found on this computer (Live is not installed?)"
    d = new_eq8(root, devs, template)
    i = 1
    write_band(d, i, freq, gain_db, q)
    return f"{track_name}: new EQ Eight at the end of the chain, band {i + 1}: {gain_db:+.1f} dB at {freq:.0f} Hz (Q {q:g})", None
