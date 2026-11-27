"""Import a Live set (.als) into a NEW HypnoMix Studio session folder. The Live project is only read.

    hypnomix als2ardour SET.als OUTDIR [--sr 48000]

OUTDIR becomes the session folder (it must not exist yet, or be empty, and must not be inside the Live project);
the session takes OUTDIR's name: OUTDIR/<name>.ardour, the audio in OUTDIR/interchange/<name>/audiofiles, MIDI in
.../midifiles, and IMPORT-REPORT.md next to the .ardour file listing everything that was NOT carried.

The session is built in a hidden temporary folder next to OUTDIR (inside it, when OUTDIR is an empty folder you made)
and moved into place only when it is complete, so a
failure (a damaged set, a full disk, Ctrl-C) never leaves a half-made session: OUTDIR is then not created and you can
simply run it again. Only real audio files are copied (the file's own container is checked, never just its name), and
a sample that lives outside the Live project folder is listed in the report.

What is carried
  tracks      name, order, colour (Live's 70-colour palette), fader, pan, mute (track switched off), solo, and
              their automation (volume, pan, track on/off); audio tracks are stereo, like Live's
  audio clips the Arrangement's main lane as regions: position, length, start in the file, clip gain, fades
              (Live's ~3 ms edge fades included), clip switched off -> region muted, looped clips unrolled into one
              region per pass, a clip volume envelope -> the region's gain envelope
  audio files COPIED into interchange/<name>/audiofiles (split into one mono file per channel, as HypnoMix Studio's own
              import does; a file at another sample rate is resampled). Nothing points back into the Live project
  warping     a clip whose warp markers make one straight line plays at one speed: at the set's own tempo it is
              carried exactly; at another speed it is carried as a stretched copy (Rubber Band, pitch kept), and
              said so. Clips with real warp markers (the timing bends between markers) are NOT carried as warps
              (HypnoMix Studio has no warp maps yet): they are placed along the straight line from their first to last
              marker and listed with how far that drifts from what Live plays
  MIDI clips  notes (one .mid file per clip, loops unrolled); the instrument is not carried
  groups      a Live group becomes a HypnoMix Studio route group of its tracks, and a bus (its children feed it) when the
              group has devices, a fader, pan, sends or automation of its own; otherwise its tracks feed the
              master (or the group above) directly
  returns     buses, with an aux send from every track that sends to them at the same level (pre/post as Live)
  tempo       the set's tempo and time signature; tempo automation as tempo points: steps exactly, and a ramp as a
              run of small constant steps (a quarter of a beat each) that are exact in time at every step, so the
              tempo map agrees with itself and a MIDI region placed in beats lands where Live plays it, to within
              the (tiny) amount the report states. Audio regions are placed in seconds exactly as Live plays them

What is NOT carried (all listed in IMPORT-REPORT.md): devices and plug-ins (never guessed: each track's Live
devices are listed), take lanes, Session-view clips, real warp maps, device automation, MIDI instruments, and the
Live features that change what you hear and have no equivalent here: a clip's transpose (Transpose / Detune), the
Re-Pitch warp mode (speed and pitch together), track delay, split stereo pan, clip grooves, the crossfader's A / B
assignment, fade curve shapes and crossfades, MIDI note probability and controller envelopes, time-signature changes,
and locators.
"""
import argparse
import errno
import math
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix.core import atomic

SCPS = 282240000                 # Ardour superclock ticks per second
TICKS = 1920                     # Ardour ticks per beat
LIVE_EARLY = -1e6                # Live's "before the song" automation event time (-63072000)
SEND_OFF = 0.000316228 * 1.01    # Live's send minimum (-70 dB) = off
DEFAULT_FADE = 0.003             # Live's default clip-edge fade (as `hypnomix render` plays it)
RAMP_STEP = 0.25                 # a tempo ramp is written as constant steps this many beats long ...
RAMP_MAX_STEPS = 400             # ... at most this many per ramp (a very long ramp gets longer steps)
NAME_BYTES = 100                 # the longest file name stem we write (file systems stop at 255 bytes, with the suffixes)
TRACK_NAME_CHARS = 80            # the longest track / group name here (the report shows the full Live name)

# Live's 70 clip / track colours (Color index -> RGB), Live 10 to 12
LIVE_COLOURS = [
    0xFF94A6, 0xFFA529, 0xCC9927, 0xF7F47C, 0xBFFB00, 0x1AFF2F, 0x25FFA8, 0x5CFFE8, 0x8BC5FF, 0x5480E4,
    0x92A7FF, 0xD86CE4, 0xE553A0, 0xFFFFFF, 0xFF3636, 0xF66C03, 0x99724B, 0xFFF034, 0x87FF67, 0x3DC300,
    0x00BFAF, 0x19E9FF, 0x10A4EE, 0x007DC0, 0x886CE4, 0xB677C6, 0xFF39D4, 0xD0D0D0, 0xE2675A, 0xFFA374,
    0xD3AD71, 0xEDFFAE, 0xD2E498, 0xBAD074, 0x9BC48D, 0xD4FDE1, 0xCDF1F8, 0xB9C1E3, 0xCDBBE4, 0xAE98E5,
    0xE5DCE1, 0xA9A9A9, 0xC6928B, 0xB78256, 0x99836A, 0xBFBA69, 0xA6BE00, 0x7DB04D, 0x88C2BA, 0x9BB3C4,
    0x85A5C2, 0x8393CC, 0xA595B5, 0xBF9FBE, 0xBC7196, 0x7B7B7B, 0xAF3333, 0xA95131, 0x724F41, 0xDBC300,
    0x85961F, 0x539F31, 0x0A9C8E, 0x236384, 0x1A2F96, 0x2F52A2, 0x624BAD, 0xA34BAD, 0xCC2E6E, 0x3C3C3C,
]
DEVICE_NAMES = {
    "Eq8": "EQ Eight", "Compressor2": "Compressor", "GlueCompressor": "Glue Compressor", "StereoGain": "Utility",
    "MultibandDynamics": "Multiband Dynamics", "AutoFilter": "Auto Filter", "Reverb": "Reverb", "Delay": "Delay",
    "FilterDelay": "Filter Delay", "Saturator": "Saturator", "Limiter": "Limiter", "Gate": "Gate",
    "AudioEffectGroupDevice": "Audio Effect Rack", "InstrumentGroupDevice": "Instrument Rack",
    "DrumGroupDevice": "Drum Rack", "MidiEffectGroupDevice": "MIDI Effect Rack", "OriginalSimpler": "Simpler",
    "MultiSampler": "Sampler", "MidiPitcher": "Pitch", "Tuner": "Tuner", "Echo": "Echo", "Chorus2": "Chorus-Ensemble",
    "PhaserNew": "Phaser-Flanger", "Redux2": "Redux", "DrumBuss": "Drum Buss", "Pedal": "Pedal", "Amp": "Amp",
    "Cabinet": "Cabinet", "Overdrive": "Overdrive", "Vinyl": "Vinyl Distortion", "Erosion": "Erosion",
    "ChannelEq": "Channel EQ", "SpectralTime": "Spectral Time", "Hybrid": "Hybrid Reverb", "Shifter": "Shifter",
    "Roar": "Roar", "Transmute": "Transmute", "Corpus": "Corpus", "Resonator": "Resonators",
}


# ---------------------------------------------------------------- Live XML helpers
def _v(el, path, cast=str, default=None):
    e = el.find(path) if el is not None else None
    if e is None or e.get("Value") is None:
        return default
    try:
        x = cast(e.get("Value"))
    except ValueError:
        return default
    if isinstance(x, float) and not math.isfinite(x):          # "nan" / "inf" in a damaged set: as if it were not there
        return default
    return x


def _true(x):
    return str(x).lower() == "true"


def _f(x, default=0.0):
    """A float from an attribute, or `default` when it is missing, damaged or not a finite number."""
    try:
        y = float(x)
    except (TypeError, ValueError):
        return default
    return y if math.isfinite(y) else default


def device_label(d):
    user = _v(d, "./UserName", str, "")
    if user:
        return user
    for p in ("./PluginDesc//PlugName", "./PluginDesc//Name"):
        n = _v(d, p, str, "")
        if n:
            maker = _v(d, "./PluginDesc//Manufacturer", str, "")
            kind = {"AuPluginDevice": "AU", "PluginDevice": "VST"}.get(d.tag, "plug-in")
            return f"{n} ({kind}{', ' + maker if maker else ''})"
    if d.tag.startswith("MxDevice"):
        path = _v(d, ".//PatchSlot//Path", str, "") or _v(d, ".//PatchSlot//RelativePath", str, "")
        return f"{Path(path).stem} (Max device)" if path else "Max device"
    return DEVICE_NAMES.get(d.tag, d.tag)


def devices(t):
    chain = t.find("./DeviceChain/DeviceChain/Devices")
    out = []
    for d in (list(chain) if chain is not None else []):
        on = _v(d, "./On/Manual", _true, True)
        out.append(device_label(d) + ("" if on else " (off)"))
    return out


def events(env):
    ev = env.find("./Automation/Events")
    pts = []
    for e in (list(ev) if ev is not None else []):
        if e.get("Value") is None or e.get("Time") is None:
            continue
        val = e.get("Value")
        try:
            val = (1.0 if val == "true" else 0.0) if val in ("true", "false") else float(val)
            tm = float(e.get("Time"))
        except ValueError:
            continue
        if not (math.isfinite(val) and math.isfinite(tm)):     # a damaged point is left out, never written as "nan"
            continue
        pts.append((max(0.0, tm) if tm > LIVE_EARLY else 0.0, val))
    return pts


def targets(el, ids):
    """{AutomationTarget id: label} for the mixer parameters we carry."""
    return {i.get("Id"): lab for lab, i in ids if i is not None and i.get("Id")}


class Tempo:
    """Live's tempo over beats: [(beat, bpm)] with Live's straight lines between points (a pair of points at one
    beat is a step). Beats -> seconds exactly, by integrating."""

    def __init__(self, bpm, points=None):
        pts = sorted(points or [], key=lambda p: p[0])      # stable: a step is two points at one beat
        pts = [(b, v) for b, v in pts if v > 0]
        if not pts:
            pts = [(0.0, bpm)]
        if pts[0][0] > 0:
            pts.insert(0, (0.0, pts[0][1]))
        self.pts = pts
        self._beats = [b for b, _ in pts]
        self.bpm = [v for b, v in pts if b <= 0][-1]
        self.ramps = [(a, b) for a, b in zip(pts, pts[1:]) if b[0] > a[0] and abs(b[1] - a[1]) > 1e-6]
        self.steps = [b for a, b in zip(pts, pts[1:]) if b[0] == a[0] and abs(b[1] - a[1]) > 1e-6]
        self._cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            self._cum.append(self._cum[-1] + self._seg(a, b, b[0]))

    @staticmethod
    def _seg(a, b, x):
        """Seconds from a[0] to beat x (<= b[0]) on the line a -> b."""
        db = x - a[0]
        if db <= 0:
            return 0.0
        if b[0] <= a[0] or abs(b[1] - a[1]) < 1e-9:
            return db * 60.0 / a[1]
        m = (b[1] - a[1]) / (b[0] - a[0])
        return 60.0 / m * math.log((a[1] + m * db) / a[1])

    @property
    def constant(self):
        return not self.ramps and not self.steps

    def seconds(self, beat):
        pts = self.pts
        import bisect
        i = max(0, bisect.bisect_right(self._beats, beat) - 1)   # the last point at or before `beat` (fast for many)
        if i == len(pts) - 1:
            return self._cum[i] + (beat - pts[i][0]) * 60.0 / pts[i][1]
        return self._cum[i] + self._seg(pts[i], pts[i + 1], beat)

    def bpm_at(self, beat):
        pts = self.pts
        for a, b in zip(pts, pts[1:]):
            if a[0] <= beat < b[0]:
                return a[1] + (b[1] - a[1]) * (beat - a[0]) / (b[0] - a[0])
        return pts[-1][1]

    def segments(self, step=RAMP_STEP, max_steps=RAMP_MAX_STEPS):
        """The map as constant-tempo segments [(beat, bpm)], each holding until the next one (the last for ever): what a
        tempo map of constant tempos can say. A step stays a step. A ramp becomes small steps whose tempo is chosen so
        that the time across each one is exactly Live's (the integral), so the written map agrees with itself at every
        step and nothing downstream (a MIDI region placed in beats) can drift."""
        out = []

        def put(beat, bpm):
            if out and out[-1][0] == beat:
                out[-1] = (beat, bpm)                      # two points at one beat: the later one rules
            elif not out or abs(out[-1][1] - bpm) > 1e-7 * max(1.0, bpm):
                out.append((beat, bpm))
        pts = self.pts
        for a, b in zip(pts, pts[1:]):
            if b[0] <= a[0]:
                continue
            if abs(b[1] - a[1]) <= 1e-6:
                put(a[0], a[1])
                continue
            n = max(1, min(max_steps, int(math.ceil((b[0] - a[0]) / step))))
            xs = sorted({round((a[0] + (b[0] - a[0]) * k / n) * TICKS) / TICKS for k in range(n + 1)})   # on the tick grid
            for x0, x1 in zip(xs, xs[1:]):
                dt = self.seconds(x1) - self.seconds(x0)
                put(x0, 60.0 * (x1 - x0) / dt if dt > 0 else a[1])
        put(pts[-1][0], pts[-1][1])
        return out

    def ramp_error(self, segs=None):
        """The most (in milliseconds) the stepped map can differ from Live's smooth ramps anywhere (0 with no ramp)."""
        if not self.ramps:
            return 0.0
        segs = segs or self.segments()
        worst, ramps, i = 0.0, sorted(self.ramps, key=lambda r: r[0][0]), 0
        for (b0, v0), nxt in zip(segs, segs[1:] + [None]):
            if nxt is None:
                break
            while i < len(ramps) and ramps[i][1][0] <= b0:     # ramps that end before this step: done with them
                i += 1
            for a, b in ramps[i:]:                             # only the ramps this step overlaps (both are sorted)
                if a[0] >= nxt[0]:
                    break
                lo, hi = max(a[0], b0), min(b[0], nxt[0])
                for j in range(1, 8):
                    x = lo + (hi - lo) * j / 8 if hi > lo else None
                    if x is not None:
                        worst = max(worst, abs(self.seconds(b0) + (x - b0) * 60.0 / v0 - self.seconds(x)) * 1000)
        return worst


# ---------------------------------------------------------------- reading the set
MAX_SET_ELEMENTS = 10_000_000       # elements in a set's XML (a big real set has a few million)


class XMLRefused(ValueError):
    """A project's XML declares a DTD or entities, or has too many elements: refused while parsing."""


def parse_xml(raw, max_elements=None):
    """Parse a project's XML, whatever its encoding, with expat itself: a DTD or an entity declaration is refused by
    the parser (a byte search would miss UTF-16), so no entity is ever expanded; past `max_elements` elements it
    stops. -> the root element (an ElementTree Element, as ET.fromstring gives)."""
    import pyexpat
    tb, count = ET.TreeBuilder(), [0]
    parser = pyexpat.ParserCreate()
    parser.buffer_text = True

    def refuse(*_a):
        raise XMLRefused("it declares a DTD or entities, which a project file never has")

    def start(tag, attrs):
        count[0] += 1
        if max_elements and count[0] > max_elements:
            raise XMLRefused(f"it has more than {max_elements} elements")
        tb.start(tag, attrs)
    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    parser.StartElementHandler = start
    parser.EndElementHandler = tb.end
    parser.CharacterDataHandler = tb.data
    try:
        for k in range(0, len(raw), 1 << 20):
            parser.Parse(raw[k:k + (1 << 20)], False)
        parser.Parse(b"", True)
    except pyexpat.ExpatError as e:
        raise ET.ParseError(str(e)) from e
    return tb.close()


def load_xml(path):
    """The set's XML root: Live writes gzip; a plain-XML .als is read too (both under the same size cap). Anything
    else stops with a message. A set saved by a later Live than HypnoMix has been tested with prints one warning line,
    as every reader does (it is only read here, so it is never refused)."""
    from hypnomix.core.gz import CAP, read_gz
    try:
        with open(path, "rb") as fh:
            gz = fh.read(2) == b"\x1f\x8b"
        if gz:
            raw = read_gz(path)                                     # a size cap on what it unpacks to
        else:
            if os.path.getsize(path) > CAP:                         # the same cap for plain XML, before reading it
                raise ValueError(f"this file is larger than {CAP >> 30} GB: it is not a project HypnoMix will open")
            raw = Path(path).read_bytes()
        root = parse_xml(raw, MAX_SET_ELEMENTS)                     # a DTD or entities are refused while parsing
    except (OSError, EOFError, ValueError, ET.ParseError) as e:
        raise SystemExit(f"{path}: not a readable Live set ({e})")
    if root.tag != "Ableton":
        raise SystemExit(f"{path}: not a Live set (top element <{root.tag}>)")
    from hypnomix.session import liveversion as LV
    LV.warn_read(root)
    return root


def read_set(path):
    """The set as plain data for the writer: tempo, time signature, tracks (main lane clips only), master."""
    path = Path(path).expanduser().resolve()
    root = load_xml(path)
    main = root.find(".//MainTrack")
    if main is None:
        main = root.find(".//MasterTrack")
    tempo_el = main.find(".//Mixer/Tempo") if main is not None else None
    bpm = _v(tempo_el, "./Manual", float, None) or _v(root, ".//Tempo/Manual", float, 120.0)
    ts = _v(main, ".//Mixer/TimeSignature/Manual", int, None) if main is not None else None
    if ts is not None:
        num, den = ts % 99 + 1, 2 ** (ts // 99)
    else:
        num = _v(root, ".//TimeSignatures/RemoteableTimeSignature/Numerator", int, 4)
        den = _v(root, ".//TimeSignatures/RemoteableTimeSignature/Denominator", int, 4)
    tpts = []
    if main is not None and tempo_el is not None:
        tid = tempo_el.find("./AutomationTarget")
        for env in main.findall("./AutomationEnvelopes/Envelopes/AutomationEnvelope"):
            if tid is not None and _v(env, "./EnvelopeTarget/PointeeId") == tid.get("Id"):
                tpts = events(env)
    tempo = Tempo(bpm, tpts)
    from hypnomix.session import liveversion as LV
    ver = LV.version_of(root)
    song = dict(path=path, name=path.stem, tempo=tempo, num=num, den=den, tracks=[], warnings=[], root=root,
                live=ver[3] if ver else None, meter_changes=meter_changes(main, num, den),
                locators=locators(root))
    song["main"] = mixer(main, "Main") if main is not None else mixer(None, "Main")
    song["groove_amount"] = _v(main, "./DeviceChain/Mixer/GlobalGrooveAmount/Manual", float, 100.0) if main is not None else 100.0
    song["crossfader"] = _v(main, "./DeviceChain/Mixer/CrossFade/Manual", float, 0.0) if main is not None else 0.0
    song["grooves"] = {g.get("Id"): (_v(g, "./Name", str, "") or "groove",
                                     any(_v(g, f"./{k}", float, 0.0) > 0 for k in ("TimingAmount", "RandomAmount", "VelocityAmount",
                                                                                   "QuantizationAmount")))
                       for g in root.findall(".//GroovePool/Grooves/Groove")}
    sends_pre = [_true(e.get("Value")) for e in root.findall(".//SendsPre/SendPreBool")]
    tracks_el = root.find("./LiveSet/Tracks")
    tracks_el = list(tracks_el) if tracks_el is not None else []
    returns = [t for t in tracks_el if t.tag == "ReturnTrack"]
    for i, t in enumerate(tracks_el):
        kind = {"AudioTrack": "audio", "MidiTrack": "midi", "GroupTrack": "group", "ReturnTrack": "return"}.get(t.tag)
        if kind is None:
            continue
        name = _v(t, "./Name/EffectiveName", str, "") or f"Track {i + 1}"
        tr = mixer(t, name)
        tr.update(kind=kind, live_id=t.get("Id"), group=_v(t, "./TrackGroupId", str, "-1"),
                  colour=_v(t, "./Color", int, None), devices=devices(t), el=t, delay=track_delay(t),
                  output=_v(t, "./DeviceChain/AudioOutputRouting/Target", str, "") or
                  _v(t, "./DeviceChain/MidiOutputRouting/Target", str, ""))
        tr["return_index"] = returns.index(t) if t in returns else None
        for s in tr["sends"]:
            s["pre"] = sends_pre[s["index"]] if s["index"] < len(sends_pre) else False
        if kind == "audio":
            lane = t.find("./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events")
            tr["clips"] = [c for c in (list(lane) if lane is not None else []) if c.tag == "AudioClip"]
        elif kind == "midi":
            lane = t.find("./DeviceChain/MainSequencer/ClipTimeable/ArrangerAutomation/Events")
            tr["clips"] = [c for c in (list(lane) if lane is not None else []) if c.tag == "MidiClip"]
        else:
            tr["clips"] = []
        tr["take_lanes"] = sum(len(tl.findall(".//AudioClip")) + len(tl.findall(".//MidiClip"))
                               for tl in t.findall("./TakeLanes/TakeLanes/TakeLane"))
        tr["session_clips"] = sum(1 for cs in t.findall(".//ClipSlotList/ClipSlot")
                                  if cs.find(".//AudioClip") is not None or cs.find(".//MidiClip") is not None)
        song["tracks"].append(tr)
    return song


def meter_changes(main, num, den):
    """Time-signature changes of the arrangement: [(beat, numerator, denominator)] after the first meter (the only one
    the session gets)."""
    tid = main.find("./DeviceChain/Mixer/TimeSignature/AutomationTarget") if main is not None else None
    if tid is None or not tid.get("Id"):
        return []
    out, cur = [], (num, den)
    for env in main.findall("./AutomationEnvelopes/Envelopes/AutomationEnvelope"):
        if _v(env, "./EnvelopeTarget/PointeeId") != tid.get("Id"):
            continue
        for b, v in sorted(events(env), key=lambda p: p[0]):
            m = (int(v) % 99 + 1, 2 ** (int(v) // 99))
            if m != cur:
                out.append((b, m[0], m[1]))
                cur = m
    return out


def locators(root):
    """The set's locators [(beat, name)] in time order."""
    out = []
    for l in root.findall("./LiveSet/Locators/Locators/Locator"):
        b = _v(l, "./Time", float, None)
        if b is not None:
            out.append((b, _v(l, "./Name", str, "") or ""))
    return sorted(out)


def track_delay(t):
    """(value, in samples?) of a track's delay compensation, or None when it is zero."""
    v = _v(t, "./TrackDelay/Value", float, 0.0)
    return (v, _v(t, "./TrackDelay/IsValueSampleBased", _true, False)) if v else None


def mixer(t, name):
    """Fader, pan, on/off, solo, sends and the automation of each, from a Live track (or the main track)."""
    m = t.find("./DeviceChain/Mixer") if t is not None else None
    out = dict(name=name, volume=1.0, pan=0.0, muted=False, solo=False, sends=[], auto={}, other_auto=[],
               split_pan=None, xfade=None)
    if m is None:
        return out
    out["volume"] = _v(m, "./Volume/Manual", float, 1.0)
    out["pan"] = _v(m, "./Pan/Manual", float, 0.0)
    out["muted"] = not _v(m, "./Speaker/Manual", _true, True)
    out["solo"] = _v(m, "./SoloSink", _true, False) or _v(m, "./Solo/Manual", _true, False) or False
    if _v(m, "./PanMode", int, 0) == 1:                      # split stereo pan: left and right panned on their own
        out["split_pan"] = (_v(m, "./SplitStereoPanL/Manual", float, -1.0), _v(m, "./SplitStereoPanR/Manual", float, 1.0))
    out["xfade"] = {0: "A", 2: "B"}.get(_v(m, "./CrossFadeState/Manual", int, 1))       # the crossfader's A / B side
    ids = [("volume", m.find("./Volume/AutomationTarget")), ("pan", m.find("./Pan/AutomationTarget")),
           ("speaker", m.find("./Speaker/AutomationTarget"))]
    mods = {}
    vm = m.find("./Volume/ModulationTarget")
    if vm is not None:
        mods[vm.get("Id")] = "volume"
    for i, h in enumerate(m.findall("./Sends/TrackSendHolder")):
        val = _v(h, "./Send/Manual", float, 0.0)
        out["sends"].append(dict(index=i, value=val, auto=None))
        ids.append((f"send{i}", h.find("./Send/AutomationTarget")))
    tg = targets(m, ids)
    out["volume_mod"] = mods
    for env in t.findall("./AutomationEnvelopes/Envelopes/AutomationEnvelope"):
        pid = _v(env, "./EnvelopeTarget/PointeeId")
        pts = events(env)
        if pid in tg and pts:
            lab = tg[pid]
            if lab.startswith("send"):
                out["sends"][int(lab[4:])]["auto"] = pts
            else:
                out["auto"][lab] = pts
        elif pts:
            out["other_auto"].append(pid)
    return out


# ---------------------------------------------------------------- clips -> pieces
def warp_line(markers):
    """(constant, slope sec/beat, b0, s0, worst ms off the first-to-last line)."""
    (b0, s0), (b1, s1) = markers[0], markers[-1]
    slope = (s1 - s0) / (b1 - b0) if b1 != b0 else 0.0
    worst = 0.0
    for b, s in markers[1:-1]:
        worst = max(worst, abs(s0 + (b - b0) * slope - s) * 1000)
    slopes = [(y1 - y0) / (x1 - x0) for (x0, y0), (x1, y1) in zip(markers, markers[1:]) if x1 != x0]
    constant = all(abs(sl - slope) <= 1e-6 * max(1.0, abs(slope)) for sl in slopes)
    return constant, slope, b0, s0, worst


def clip_pieces(c, tempo):
    """How an audio clip plays: [(timeline seconds, length seconds, source seconds, content position, start beat)] at
    speed `rate` (source seconds per timeline second), plus notes about warping. Loops are unrolled, one piece per
    pass. The content position is in the clip's own units: beats when warped, seconds when not (as Live keeps it)."""
    s, e = _v(c, "./CurrentStart", float), _v(c, "./CurrentEnd", float)
    ls, le = _v(c, "./Loop/LoopStart", float, 0.0), _v(c, "./Loop/LoopEnd", float, 0.0)
    rel = _v(c, "./Loop/StartRelative", float, 0.0)
    loop_on = _v(c, "./Loop/LoopOn", _true, False)
    warped = _v(c, "./IsWarped", _true, False)
    markers = sorted((float(w.get("BeatTime")), float(w.get("SecTime"))) for w in c.findall("./WarpMarkers/WarpMarker"))
    info = dict(warped=warped, markers=len(markers), rate=1.0, kind="unwarped", drift_ms=0.0)
    t0, t1 = tempo.seconds(s), tempo.seconds(e)
    if warped and len(markers) >= 2:
        constant, slope, b0, s0, worst = warp_line(markers)
        spb = 60.0 / tempo.bpm_at(s)
        rate = slope / spb if spb > 0 else 1.0                    # source seconds per timeline second
        info.update(rate=rate, drift_ms=worst, kind="straight" if constant else "bent",
                    tempo_follow=not tempo.constant)
        to_src = lambda cb: s0 + (cb - b0) * slope                 # clip beats -> source seconds
        pos_unit, span_len = "beats", e - s                         # loop/start values are in beats
    else:
        rate = 1.0
        to_src = lambda x: x
        pos_unit, span_len = "seconds", t1 - t0
    pieces = []
    pos, need, done = ls + rel, span_len, 0.0
    guard = 0
    while need > 1e-9 and guard < 10000:
        guard += 1
        stop = le if (loop_on and le > pos) else pos + need
        take = min(need, stop - pos)
        if take <= 1e-12:
            break
        if pos_unit == "beats":
            ts, te = tempo.seconds(s + done), tempo.seconds(s + done + take)
            src = to_src(pos)
        else:
            ts, te = t0 + done, t0 + done + take
            src = pos
        pieces.append([ts, te - ts, src, pos, s + done])   # + where the content is, and the beat it starts on
        done += take
        need -= take
        pos = ls if loop_on else pos + take
    info["looped"] = len(pieces) > 1
    return pieces, info


def clip_fades(c, tempo):
    s = _v(c, "./CurrentStart", float)
    spb = 60.0 / tempo.bpm_at(s)
    fi = _v(c, "./Fades/FadeInLength", float, 0.0) * spb
    fo = _v(c, "./Fades/FadeOutLength", float, 0.0) * spb
    if _v(c, "./Fades/IsDefaultFadeIn", str, "true") != "false" or fi > 0:
        fi = max(fi, DEFAULT_FADE)
    if _v(c, "./Fades/IsDefaultFadeOut", str, "true") != "false" or fo > 0:
        fo = max(fo, DEFAULT_FADE)
    return fi, fo


def clip_source(c, als_dir):
    fr = c.find("./SampleRef/FileRef")
    p = _v(fr, "./Path", str, "")
    rel = _v(fr, "./RelativePath", str, "")
    if p and Path(p).is_file():
        return Path(p)
    if rel and (als_dir / rel).is_file():
        return als_dir / rel
    return Path(p) if p else (als_dir / rel if rel else None)


def clip_volume_envelope(c, track):
    """A clip envelope on the track's volume -> [(beats from the clip's content start, factor)] or None."""
    for env in c.findall("./Envelopes/Envelopes/ClipEnvelope"):
        pid = _v(env, "./EnvelopeTarget/PointeeId")
        if pid in track.get("volume_mod", {}) or pid == _v(track["el"], "./DeviceChain/Mixer/Volume/AutomationTarget",
                                                             str, None):
            return events(env)
    return None


def other_clip_envelopes(c, track):
    n = len(c.findall("./Envelopes/Envelopes/ClipEnvelope"))
    return n - (1 if clip_volume_envelope(c, track) else 0)


# ---------------------------------------------------------------- MIDI
def _vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.insert(0, (n & 0x7F) | 0x80)
        n >>= 7
    return bytes(out)


def write_smf(path, notes, length_beats):
    """notes [(beat, duration beats, key, velocity)] -> a type-0 Standard MIDI File at 1920 ticks per beat."""
    ev = []
    for b, d, k, vel in notes:
        on, off = int(round(b * TICKS)), int(round((b + max(d, 1e-3)) * TICKS))
        ev.append((on, 1, bytes([0x90, k & 0x7F, max(1, min(127, int(round(vel))))])))
        ev.append((max(off, on + 1), 0, bytes([0x80, k & 0x7F, 64])))
    ev.sort(key=lambda x: (x[0], x[1]))
    data, last = b"", 0
    for t, _, msg in ev:
        data += _vlq(t - last) + msg
        last = t
    end = max(last, int(round(length_beats * TICKS)))
    data += _vlq(end - last) + b"\xff\x2f\x00"
    path.write_bytes(b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big") + (1).to_bytes(2, "big") +
                     TICKS.to_bytes(2, "big") + b"MTrk" + len(data).to_bytes(4, "big") + data)


def midi_notes(c):
    """Notes as the clip plays them from its start: [(beat from the clip start, duration, key, velocity)]."""
    s, e = _v(c, "./CurrentStart", float), _v(c, "./CurrentEnd", float)
    ls, le = _v(c, "./Loop/LoopStart", float, 0.0), _v(c, "./Loop/LoopEnd", float, 0.0)
    rel = _v(c, "./Loop/StartRelative", float, 0.0)
    loop_on = _v(c, "./Loop/LoopOn", _true, False)
    raw = []
    for kt in c.findall("./Notes/KeyTracks/KeyTrack"):
        key = _v(kt, "./MidiKey", int, 60)
        for n in kt.findall("./Notes/MidiNoteEvent"):
            if n.get("IsEnabled", "true") == "false":
                continue
            try:
                t_, d_, v_ = float(n.get("Time")), float(n.get("Duration")), float(n.get("Velocity", 100))
            except (TypeError, ValueError):
                continue                                         # a damaged note is left out
            if math.isfinite(t_ + d_ + v_):
                raw.append((t_, d_, key, v_))
    out, pos, need, done = [], ls + rel, e - s, 0.0
    guard = 0
    while need > 1e-9 and guard < 10000:
        guard += 1
        stop = le if (loop_on and le > pos) else pos + need
        take = min(need, stop - pos)
        if take <= 1e-12:
            break
        for t, d, k, vel in raw:
            if pos - 1e-9 <= t < pos + take - 1e-9:
                out.append((done + t - pos, min(d, need - (t - pos)), k, vel))
        done += take
        need -= take
        pos = ls if loop_on else pos + take
    return sorted(out)


# ---------------------------------------------------------------- audio files
BLOCK = 65536                      # frames per block when a file is copied


def audio_container(path):
    """What audio container a file really is, from its first bytes (never from its name): "wav", "aiff", "flac", "ogg",
    "mp3", "aac", "m4a", "caf", ... or None. A text file called hist.sw, or any other file that only a raw-audio
    guess would play, is None: it is not copied into the session."""
    try:
        with open(path, "rb") as fh:
            h = fh.read(16)
    except OSError:
        return None
    if h[:4] in (b"RIFF", b"RF64") and h[8:12] == b"WAVE":
        return "wav"
    if h[:4] == b"FORM" and h[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    for magic, name in ((b"fLaC", "flac"), (b"OggS", "ogg"), (b"caff", "caf"), (b"wvpk", "wavpack"), (b"MAC ", "ape"),
                        (b".snd", "au"), (b"ID3", "mp3"), (b"\x1aE\xdf\xa3", "matroska"),
                        (b"0&\xb2u\x8ef\xcf\x11", "wma"), (b"riff\x2e\x91\xcf\x11", "w64")):
        if h.startswith(magic):
            return name
    if h[4:8] == b"ftyp":
        return "m4a"
    if len(h) >= 3 and h[0] == 0xFF and h[1] & 0xE0 == 0xE0 and Path(path).suffix.lower() in (".mp3", ".mp2", ".aac"):
        layer, bitrate, rate = (h[1] >> 1) & 3, h[2] >> 4, (h[2] >> 2) & 3
        if (h[1] >> 3) & 3 != 1 and layer != 0 and bitrate not in (0, 15) and rate != 3:
            return "mp3"                                       # an MPEG frame header, not just any 0xFF byte
        if h[1] & 0xF0 == 0xF0 and layer == 0 and (h[2] >> 2) & 0xF <= 12 and Path(path).suffix.lower() == ".aac":
            return "aac"                                       # a raw ADTS stream: sync, layer bits 00, a real sample-rate index
    return None


def short_stem(stem, limit=NAME_BYTES):
    """A file name stem cut to at most `limit` UTF-8 bytes (never in the middle of a character)."""
    b = stem.encode("utf-8")
    return stem if len(b) <= limit else b[:limit].decode("utf-8", "ignore").rstrip()


MAX_FILE_SECONDS = 4 * 3600         # a file that must be converted, or is compressed: longer is not copied in
PCM_FORMATS = ("WAV", "WAVEX", "AIFF", "W64", "RF64", "CAF")   # their size follows their length: copied at any length
MAX_MEMORY_SAMPLES = 1 << 26        # a file converted in memory (a stretch, or no ffmpeg): samples x channels at most
MAX_UPSAMPLE = 8                    # the session rate at most 8x a file's own
MAX_CONVERT_FILE = 8 << 30          # bytes ffmpeg may write for one converted file (a hard limit on the process)
DISK_MARGIN = 2 << 30               # what a copy must leave free on the disk


FFMPEG_TIMEOUT = 1800                # a conversion that takes longer than 30 minutes is stopped


def _probe_seconds(path):
    """The length of a file libsndfile cannot open (mp3, m4a ...), from ffprobe when it is there, or None."""
    import shutil
    import subprocess
    exe = shutil.which("ffprobe")
    if exe is None:
        return None
    try:
        cp = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
                             str(path)], capture_output=True, timeout=30)
        v = float(cp.stdout.decode("ascii", "replace").strip() or "nan")
        return v if math.isfinite(v) else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class Sources:
    """Copies each source file once into the session, one mono file per channel. Files are copied in blocks, so a long
    recording never has to fit in memory twice; only a file that needs another sample rate or a stretch is read whole
    (one channel at a time, as 32-bit floats)."""

    def __init__(self, audio_dir, sr, warn):
        self.dir, self.sr, self.warn = audio_dir, sr, warn
        self.done = {}           # (path, rate) -> (names, seconds)
        self.used = set()
        self.next = {}

    def _name(self, stem):
        stem = re.sub(r"[\x00-\x1f\x7f\ufffe\uffff]|[\ud800-\udfff]", "", stem)   # XML cannot hold these
        stem = short_stem(re.sub(r'[\\/:*?"<>|%]', "-", stem).strip() or "audio")
        name, i = stem, self.next.get(stem.lower(), 2)
        while name.lower() in self.used:          # macOS volumes ignore case: Vox.wav would overwrite vox.wav
            name, i = f"{stem}-{i}", i + 1
        self.next[stem.lower()] = i               # a counter per stem: many files of one name stay fast
        self.used.add(name.lower())
        return name

    def _unfit(self, path, rate, info, streamed):
        """Why this file is not converted (too long, too much resampling, too big for memory or the disk), or None.
        A file that compresses well can declare hours of audio in a few kilobytes. `streamed`: ffmpeg converts it
        file to file (constant memory); otherwise it is read whole."""
        if info is not None:
            secs, fr, ch = float(info.duration), int(info.samplerate), int(info.channels)
        else:
            secs, fr, ch = _probe_seconds(path), None, 2
        if secs is None and not streamed:
            return "its length cannot be read before decoding it (ffprobe is not installed)"
        if secs is not None and secs > MAX_FILE_SECONDS:
            return f"it is {secs / 3600:.1f} hours long; files that must be converted are taken up to " \
                   f"{MAX_FILE_SECONDS // 3600} hours"
        if fr and self.sr > fr * MAX_UPSAMPLE:
            return f"it is at {fr} Hz and would need resampling to {self.sr} Hz, more than {MAX_UPSAMPLE}x"
        if not streamed and secs * max(fr or self.sr, self.sr) * ch / max(rate, 1e-3) > MAX_MEMORY_SAMPLES:
            return f"it is too long to convert in memory ({secs / 60:.0f} minutes, {ch} channel(s))"
        if secs is not None:
            return self._no_room(secs * self.sr * ch * 4 / max(rate, 1e-3))
        return None

    def _no_room(self, need):
        try:
            free = shutil.disk_usage(self.dir).free
        except OSError:
            return None
        if need > free - DISK_MARGIN:
            return f"it would need {need / 2**30:.1f} GB in the session, more than the disk has free"
        return None

    def _ffmpeg(self, path, stem, written, label, fr=None):
        """Resample or decode with ffmpeg, file to file (constant memory, at most MAX_FILE_SECONDS and
        MAX_CONVERT_FILE bytes), then copy the result in blocks. None when ffmpeg is not there or fails."""
        import subprocess
        import tempfile
        exe = shutil.which("ffmpeg")
        if exe is None:
            return None

        def limit():                                            # a hard cap on what ffmpeg may write (never above
            import resource                                     # a lower limit already set: that one stays)
            soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
            cap = MAX_CONVERT_FILE if hard == resource.RLIM_INFINITY else min(MAX_CONVERT_FILE, hard)
            if soft != resource.RLIM_INFINITY:
                cap = min(cap, soft)
            resource.setrlimit(resource.RLIMIT_FSIZE, (cap, hard))
        # Windows has no rlimits (and no preexec_fn): there the file is bounded by -t (at most MAX_FILE_SECONDS at the
        # session rate) and by FFMPEG_TIMEOUT, and the disk room was checked before (_no_room)
        with tempfile.TemporaryDirectory(prefix="hypnomix-convert-") as td:
            tmp = Path(td) / "x.wav"
            try:
                cp = subprocess.run([exe, "-nostdin", "-y", "-loglevel", "error", "-i", str(path), "-vn",
                                     "-t", str(MAX_FILE_SECONDS), "-ar", str(self.sr), "-c:a", "pcm_f32le",
                                     "-rf64", "auto", str(tmp)], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=FFMPEG_TIMEOUT,
                                    preexec_fn=limit if os.name == "posix" else None)
            except subprocess.TimeoutExpired as e:
                raise ValueError(f"converting it took longer than {FFMPEG_TIMEOUT // 60} minutes: stopped") from e
            except (OSError, subprocess.SubprocessError) as e:
                raise ValueError(f"ffmpeg could not be started to convert it ({type(e).__name__})") from e
            if cp.returncode != 0 or not tmp.is_file():
                return None
            info = sf.info(str(tmp))
            if info.duration >= MAX_FILE_SECONDS - 1:
                raise ValueError(f"it is longer than {MAX_FILE_SECONDS // 3600} hours")
            got = self._copy(tmp, info, stem, written)
        if fr and fr != self.sr:
            self.warn.append(f"{label}: {fr} Hz, resampled to the session's {self.sr} Hz (file to file, by ffmpeg)")
        elif not fr:
            self.warn.append(f"{label}: decoded to the session's {self.sr} Hz (file to file, by ffmpeg)")
        return got

    def add(self, path, rate=1.0):
        """-> ([file names, one per channel], length in seconds) or None when the file can't be read."""
        key = (str(path), round(rate, 9))
        if key in self.done:
            return self.done[key]
        self.done[key] = None
        stem = Path(path).stem + (f" (x{rate:.4f})" if abs(rate - 1.0) > 1e-9 else "")
        written = []
        try:
            if not Path(path).is_file():
                raise ValueError("not a file")
            container = audio_container(path)
            if container is None:
                raise ValueError("not an audio file (its contents are not a known audio container)")
            try:
                info = sf.info(str(path))
            except Exception:
                info = None
            stretchy = abs(rate - 1.0) > 1e-9
            if info is not None and not stretchy and info.samplerate == self.sr:
                why = self._no_room(info.frames * info.channels * 4)
                if not why and info.format not in PCM_FORMATS and info.duration > MAX_FILE_SECONDS:
                    why = (f"it is {info.duration / 3600:.1f} hours long; a compressed file is taken up to "
                           f"{MAX_FILE_SECONDS // 3600} hours (a few kilobytes can declare hours of silence)")
                if why:
                    raise ValueError(why)
                got = self._copy(path, info, stem, written)    # same rate, same speed: streamed, any length
            else:
                streamed = not stretchy and shutil.which("ffmpeg") is not None
                why = self._unfit(path, rate, info, streamed)
                if why:
                    raise ValueError(why)
                got = self._ffmpeg(path, stem, written, Path(path).name,
                                   info.samplerate if info is not None else None) if streamed else None
                if got is None:
                    self._drop(written)
                    why = self._unfit(path, rate, info, False) if streamed else None   # now read whole: its limits
                    if why:
                        raise ValueError(why)
                    try:
                        if info is None:
                            raise ValueError("not for libsndfile")
                        got = self._convert(path, info, rate, stem, written)
                    except (StretchError, MemoryError):
                        raise
                    except OSError as e:
                        if e.errno == errno.ENOSPC:             # the disk is full: stop, never carry on without audio
                            raise
                        got = None
                    except Exception:
                        got = None
                if got is None:                                 # not for libsndfile (mp3, m4a ...): decode with ffmpeg
                    self._drop(written)
                    from hypnomix.core import dsp
                    y, sr = dsp.load(path)
                    y = np.asarray(y, dtype=np.float32)
                    y = y[:, None] if y.ndim == 1 else y
                    got = self._write(y, sr, rate, stem, written, "FLOAT", Path(path).name)
            self.done[key] = got
        except (StretchError, MemoryError):
            self._drop(written)
            self.done.pop(key, None)
            raise
        except Exception as e:
            self._drop(written)                                 # a half-copied file is never left behind
            if isinstance(e, OSError) and e.errno == errno.ENOSPC:
                raise
            self.warn.append(f"could not read {Path(path).name} ({e if isinstance(e, ValueError) else type(e).__name__}): "
                             f"its clips are left out")
        return self.done.get(key)

    def _drop(self, written):
        for fn in written:
            try:
                (self.dir / fn).unlink()
            except OSError:
                pass
        written.clear()

    @staticmethod
    def _subtype(info):
        return info.subtype if info.subtype in ("PCM_16", "PCM_24", "PCM_32", "FLOAT", "DOUBLE") else "FLOAT"

    def _names(self, base, chans):
        sfx = [""] if chans == 1 else (["%L", "%R"] if chans == 2 else [f"%{chr(97 + i)}" for i in range(chans)])
        return [f"{base}{x}.wav" for x in sfx]

    def _copy(self, path, info, stem, written):
        """Same rate, same speed: copy block by block, keeping the file's own sample format."""
        base = self._name(stem)
        names = self._names(base, info.channels)
        subtype = self._subtype(info)
        outs = []
        try:
            for fn in names:
                outs.append(sf.SoundFile(str(self.dir / fn), "w", samplerate=self.sr, channels=1, subtype=subtype,
                                         format="WAV"))
                written.append(fn)
            frames = 0
            with sf.SoundFile(str(path)) as src:
                for blk in src.blocks(blocksize=BLOCK, dtype="float64", always_2d=True):
                    for ch, o in enumerate(outs):
                        o.write(blk[:, ch])
                    frames += len(blk)
        finally:
            for o in outs:
                o.close()
        return names, frames / self.sr

    def _convert(self, path, info, rate, stem, written):
        """Another rate or another speed: one channel at a time, 32-bit floats."""
        subtype = "FLOAT"
        base = self._name(stem)
        names = self._names(base, info.channels)
        frames = 0
        for ch, fn in enumerate(names):
            y = np.empty(info.frames, dtype=np.float32)
            n = 0
            with sf.SoundFile(str(path)) as src:
                for blk in src.blocks(blocksize=BLOCK, dtype="float32", always_2d=True):
                    y[n:n + len(blk)] = blk[:, ch]
                    n += len(blk)
            y = y[:n]
            if abs(rate - 1.0) > 1e-9:
                y = stretch(y[:, None], info.samplerate, 1.0 / rate)[:, 0]
            if info.samplerate != self.sr:
                y = self._resample(y, info.samplerate)
            sf.write(str(self.dir / fn), y, self.sr, subtype=subtype)
            written.append(fn)
            frames = len(y)
        if info.samplerate != self.sr:
            self.warn.append(f"{Path(path).name}: {info.samplerate} Hz, resampled to the session's {self.sr} Hz")
        return names, frames / self.sr

    def _resample(self, y, sr):
        from scipy.signal import resample_poly
        r = Fraction(self.sr, sr).limit_denominator(2000)
        return resample_poly(y, r.numerator, r.denominator).astype(np.float32)

    def _write(self, y, sr, rate, stem, written, subtype, label):
        """An already decoded array (ffmpeg's way in): stretch, resample, write one file per channel."""
        if abs(rate - 1.0) > 1e-9:
            y = stretch(y, sr, 1.0 / rate)
        if sr != self.sr:
            y = np.stack([self._resample(y[:, ch], sr) for ch in range(y.shape[1])], axis=1)
            self.warn.append(f"{label}: {sr} Hz, resampled to the session's {self.sr} Hz")
        base = self._name(stem)
        names = self._names(base, y.shape[1])
        for ch, fn in enumerate(names):
            sf.write(str(self.dir / fn), y[:, ch], self.sr, subtype=subtype)
            written.append(fn)
        return names, len(y) / self.sr


class StretchError(RuntimeError):
    """The stretched copy of a clip's audio could not be made (the caller places the clip unstretched and says so)."""


def stretch(y, sr, k):
    """Every channel `k` times longer, pitch kept (Rubber Band R3)."""
    if not shutil.which("rubberband"):
        raise StretchError("the rubberband command is not installed (brew install rubberband)")
    try:
        with tempfile.TemporaryDirectory(prefix="hypnomix-work-") as td:
            fi, fo = Path(td) / "i.wav", Path(td) / "o.wav"
            sf.write(str(fi), y.astype(np.float32, copy=False), sr, subtype="FLOAT")
            subprocess.run(["rubberband", "-3", "-q", "-t", f"{k:.9f}", str(fi), str(fo)], check=True,
                           capture_output=True)
            return sf.read(str(fo), always_2d=True, dtype="float32")[0]
    except (subprocess.CalledProcessError, OSError, RuntimeError) as e:
        raise StretchError(str(e) or type(e).__name__) from e


def session_rate(song, override=None):
    if override:
        return int(override)
    rates = {}
    for t in song["tracks"]:
        for c in t["clips"]:
            if c.tag != "AudioClip":
                continue
            p = clip_source(c, song["path"].parent)
            if p is not None and p.is_file():
                try:
                    r = sf.info(str(p)).samplerate
                except Exception:
                    continue
                rates[r] = rates.get(r, 0) + 1
    return max(rates, key=rates.get) if rates else 48000


# ---------------------------------------------------------------- the Ardour session XML
class Ids:
    def __init__(self, start=100):
        self.n = start

    def __call__(self):
        self.n += 1
        return str(self.n)


_SR = [48000]


def a(sec):
    """Seconds -> an Ardour audio time, on a sample (Ardour keeps regions on samples; so it reads back exactly)."""
    sr = _SR[0]
    return f"a{int(round(sec * sr)) * (SCPS // sr)}" if SCPS % sr == 0 else f"a{int(round(sec * SCPS))}"


def legal(name):
    """Ardour's own rule for track names (Route::ensure_track_or_route_name): these characters become '_'. Control
    characters (which XML cannot hold) and line breaks go. A very long name is cut (the report keeps Live's full name)."""
    n = re.sub(r"[\x00-\x1f\x7f\ufffe\uffff]|[\ud800-\udfff]", " ", str(name))
    n = re.sub(r'[<>:"/\\|?*]', "_", n)[:TRACK_NAME_CHARS].rstrip(" .").strip()
    return n or "Track"


def sub(parent, tag, **attrs):
    return ET.SubElement(parent, tag, {k.replace("_", "-"): str(v) for k, v in attrs.items()})


def alist(parent, ids, aid, pts=None, style="Linear", play=False):
    al = sub(parent, "AutomationList", automation_id=aid, id=ids(), interpolation_style=style,
             time_domain="AudioTime", state="Play" if (play and pts) else "Off")
    if pts:
        ev = sub(al, "events")
        ev.text = "".join(f"{a(t)} {v:.12g}\n" for t, v in pts)
    return al


def dedupe_points(pts):
    """Automation: sorted by time; Live writes a jump as two points at one time, Ardour keeps both."""
    return sorted(pts, key=lambda p: p[0])


class Writer:
    def __init__(self, song, out, sr, log, name=None):
        """`out` is the folder written into (a temporary one while building); `name` is the session's name (the final
        folder's name)."""
        self.song, self.out, self.sr, self.log = song, out, sr, log
        self.name = name or out.name
        _SR[0] = int(sr)
        self.ids = Ids()
        self.tempo = song["tempo"]
        self.at = ""                                  # what is being built now, for the message if it fails
        self.outside = {}                             # sample outside the project folder -> clips that use it
        self.report = dict(tracks=[], warped=[], bent=[], missing=[], notes=[], uncarried_env=[], clamped=[],
                           pitch=[], repitch=[], fadeshape=[], delay=[], midi_extra=[], split_pan=[], groove=[], crossfade=[])

    # ---- small parts
    def controllables(self, rt, tr, kind):
        sub(rt, "Controllable", name="solo", id=self.ids(), flags="Toggle,RealTime", value=int(tr["solo"]),
            self_solo=int(tr["solo"]), soloed_by_upstream=0, soloed_by_downstream=0)
        sub(rt, "Controllable", name="solo-iso", id=self.ids(), flags="Toggle,RealTime", value=0, solo_isolated=0)
        sub(rt, "Controllable", name="solo-safe", id=self.ids(), flags="Toggle", value=0, solo_safe=0)

    def io(self, rt, name, direction, n, dtype, connect=None):
        io = sub(rt, "IO", name=name, id=self.ids(), direction=direction, default_type=dtype)
        word = "in" if direction == "Input" else "out"
        for i in range(n):
            p = sub(io, "Port", name=f"{name}/{dtype}_{word} {i + 1}", type=dtype, direction=direction)
            for other in (connect or {}).get(i, []):
                sub(p, "Connection", other=other)
        return io

    def pannable(self, parent, pan, pan_pts=None):
        pn = sub(parent, "Pannable")
        sub(pn, "Controllable", name="pan-azimuth", id=self.ids(), flags="", value=f"{(pan + 1) / 2:.9g}")
        sub(pn, "Controllable", name="pan-width", id=self.ids(), flags="", value=1)
        au = sub(pn, "Automation")
        pts = [(t, (v + 1) / 2) for t, v in pan_pts] if pan_pts else None
        alist(au, self.ids, "pan-azimuth", pts, "Linear", play=True)
        return pn

    def secs(self, pts):
        return dedupe_points([(self.tempo.seconds(b), v) for b, v in pts])

    # ---- routes
    def route(self, routes, tr, kind, order, out_to, n_in=2):
        """kind: audio | midi | bus | master. out_to: route name whose inputs this route feeds (None = nothing)."""
        name = tr["ardour_name"]
        flags = {"audio": "AudioTrack,OrderSet", "midi": "MidiTrack,OrderSet", "bus": "AudioBus,OrderSet",
                 "master": "MasterOut,OrderSet"}[kind]
        rid = tr.setdefault("rid", self.ids())
        attrs = dict(version="7004", id=rid, name=name, default_type="midi" if kind == "midi" else "audio",
                     strict_io="1" if kind in ("master", "midi") else "0", active="1", denormal_protection="0",
                     meter_point="MeterOutput" if kind == "master" else "MeterPostFader",
                     disk_io_point="DiskIOPreFader", meter_type="MeterK14" if kind == "master" else "MeterPeak")
        if tr.get("route_group"):
            attrs["route_group"] = tr["route_group"]
        if kind in ("audio", "midi"):
            attrs[f"{'midi' if kind == 'midi' else 'audio'}_playlist"] = tr["playlist_id"]
            attrs.update(alignment_choice="Automatic", mode="Normal")
        if kind == "master":
            attrs["volume_applies_to_output"] = "1"
        rt = sub(routes, "Route", **attrs)
        colour = tr.get("colour")
        rgba = (LIVE_COLOURS[colour] << 8 | 0xFF) if colour is not None and 0 <= colour < len(LIVE_COLOURS) else 0
        sub(rt, "PresentationInfo", order=order, flags=flags, color=rgba)
        self.controllables(rt, tr, kind)
        dtype = "midi" if kind == "midi" else "audio"
        if kind == "midi":
            self.io(rt, name, "Input", 1, "midi")
            self.io(rt, name, "Output", 1, "midi")
        else:
            self.io(rt, name, "Input", n_in, "audio", tr.get("inputs"))
            con = {0: [f"{out_to}/audio_in 1"], 1: [f"{out_to}/audio_in 2"]} if out_to else None
            self.io(rt, name, "Output", 2, "audio", con)
        sub(rt, "MuteMaster", mute_point="PostFader,Listen,Main,SurroundSend", muted=int(tr["muted"]))
        sub(rt, "Controllable", name="mute", id=self.ids(), flags="Toggle,RealTime", value=int(tr["muted"]))
        sub(rt, "Controllable", name="phase", id=self.ids(), flags="Toggle", value=0,
            phase_invert="" if kind == "midi" else "00")
        au = sub(rt, "Automation")
        mute_pts = [(t, 0.0 if v > 0.5 else 1.0) for t, v in self.secs(tr["auto"]["speaker"])] \
            if tr["auto"].get("speaker") else None
        alist(au, self.ids, "mute", mute_pts, "Discrete", play=True)
        pan_pts = self.secs(tr["auto"]["pan"]) if tr["auto"].get("pan") else None
        self.pannable(rt, tr["pan"], pan_pts)
        if kind in ("audio", "midi"):
            sub(rt, "Processor", id=self.ids(), name=f"recorder:{name}", active=1, user_latency=0,
                use_user_latency=0, type="diskwriter", record_safe=0)
            sub(rt, "Processor", id=self.ids(), name=f"player:{name}", active=1, user_latency=0,
                use_user_latency=0, type="diskreader")
        if kind == "bus" and tr.get("is_return"):
            sub(rt, "Processor", id=self.ids(), name="Return", active=1, user_latency=0, use_user_latency=0,
                type="intreturn")
        sub(rt, "Processor", id=self.ids(), name="Polarity", active=1, user_latency=0, use_user_latency=0,
            type="polarity")
        if kind != "midi":
            tp = sub(rt, "Processor", id=self.ids(), name="Amp", active=1, user_latency=0, use_user_latency=0,
                     type="trim")
            alist(sub(tp, "Automation"), self.ids, "trim", None, "Logarithmic")
            sub(tp, "Controllable", name="trimcontrol", id=self.ids(), flags="GainLike", value=1)
        sends = tr.get("aux", []) if kind != "midi" else []      # no instrument here: nothing to send yet
        for s in [s for s in sends if s["pre"]]:
            self.send(rt, s)
        amp = sub(rt, "Processor", id=self.ids(), name="Amp", active=1, user_latency=0, use_user_latency=0, type="amp")
        vol_pts = self.secs(tr["auto"]["volume"]) if tr["auto"].get("volume") else None
        alist(sub(amp, "Automation"), self.ids, "gain", vol_pts, "Exponential", play=True)
        vol = vol_pts[0][1] if vol_pts else tr["volume"]
        sub(amp, "Controllable", name="gaincontrol", id=self.ids(), flags="GainLike", value=f"{min(2.0, vol):.12g}")
        for s in [s for s in sends if not s["pre"]]:
            self.send(rt, s)
        sub(rt, "Processor", id=self.ids(), name=f"meter-{name}", active=1, user_latency=0, use_user_latency=0,
            type="meter")
        mo = sub(rt, "Processor", id=self.ids(), name=name, active=1, user_latency=0, use_user_latency=0,
                 own_input=1, own_output=0, output=name, type="main-outs", role="Main")
        sub(mo, "PannerShell", bypassed=0, user_panner="", linked_to_route=1)
        sub(rt, "Slavable")
        if kind in ("audio", "midi"):
            sub(rt, "Controllable", name="monitor", id=self.ids(), flags="RealTime", value=0, monitoring="")
            sub(rt, "Controllable", name="rec-safe", id=self.ids(), flags="Toggle,RealTime", value=0)
            sub(rt, "Controllable", name="rec-enable", id=self.ids(), flags="Toggle,RealTime", value=0)
        return rt

    def send(self, rt, s):
        p = sub(rt, "Processor", id=self.ids(), name=s["target_name"], active=1, user_latency=0, use_user_latency=0,
                own_input=1, own_output=1, type="intsend", role="Aux", bitslot=s["bitslot"], selfdestruct=0,
                target=s["target_id"], allow_feedback=0)
        au = sub(p, "Automation")
        pts = self.secs(s["auto"]) if s.get("auto") else None
        alist(au, self.ids, "send", pts, "Exponential", play=True)
        sh = sub(p, "PannerShell", bypassed=0, user_panner="", linked_to_route=1)
        sub(sh, "Panner", uri="http://ardour.org/plugin/panner_2in2out", type="Equal Power Stereo")
        self.pannable(p, 0.0)
        sub(p, "Controllable", name="polarity-invert", id=self.ids(), flags="Toggle", value=0)
        val = pts[0][1] if pts else s["value"]
        sub(p, "Controllable", name="gaincontrol", id=self.ids(), flags="GainLike,InlineControl",
            value=f"{min(2.0, val):.12g}")

    # ---- regions
    def audio_regions(self, tr, playlist, sources_el, regions_el, srcs):
        als_dir = self.song["path"].parent
        made = 0
        for c in tr["clips"]:
            cname = _v(c, "./Name", str, "") or "clip"
            self.at = f"track {tr['name']!r}, clip {cname!r}"
            path = clip_source(c, als_dir)
            s_beat, e_beat = _v(c, "./CurrentStart", float), _v(c, "./CurrentEnd", float)
            if s_beat is None or e_beat is None:
                self.report["notes"].append(f"{tr['name']} / {cname}: the set gives it no readable start or end: left out")
                continue
            where = f"{tr['name']} / {cname} (bar {s_beat / (self.song['num'] * 4 / self.song['den']) + 1:.0f})"
            self.groove_note(c, where)
            if path is None or not path.is_file():
                self.report["missing"].append(f"{where}: {path.name if path else 'no file'}")
                continue
            pieces, info = clip_pieces(c, self.tempo)
            rate = info["rate"]
            straight = abs(rate - 1.0) <= 1e-6
            self.sound_changes(c, where, info, straight)
            try:
                path.resolve().relative_to(als_dir.resolve())
            except ValueError:
                self.outside[str(path)] = self.outside.get(str(path), 0) + 1
            if info["warped"] and info["markers"] >= 2:
                if info["kind"] == "bent":
                    self.report["bent"].append(dict(where=where, markers=info["markers"], drift=info["drift_ms"],
                                                    rate=rate))
                elif not straight:
                    self.report["warped"].append(dict(where=where, rate=rate))
                if info.get("tempo_follow"):
                    self.report["notes"].append(f"{where}: warped, and the set's tempo changes: the clip is "
                                                f"placed at its start tempo's speed (Live would follow the tempo)")
            use_rate = 1.0 if straight else rate
            got = None
            if not straight:
                try:
                    got = srcs.add(path, use_rate)
                except Exception as e:
                    self.report["notes"].append(f"{where}: could not make the stretched copy ({e}); placed "
                                                f"unstretched")
                    use_rate = 1.0
            if got is None:
                got = srcs.add(path, 1.0)
                use_rate = 1.0
            if got is None:
                self.report["missing"].append(f"{where}: {path.name} could not be read")
                continue
            names, src_len = got
            sids = self.source_ids(names, sources_el, regions_el, src_len)
            if len(sids) == 1:
                sids = sids * 2                      # a mono file plays on both sides of the stereo track, as in Live
            fi, fo = clip_fades(c, self.tempo)
            gain = _v(c, "./SampleVolume", float, 1.0)
            muted = _v(c, "./Disabled", _true, False)
            env = clip_volume_envelope(c, tr)
            if other_clip_envelopes(c, tr):
                self.report["uncarried_env"].append(f"{where}: {other_clip_envelopes(c, tr)} clip envelope(s) "
                                                    f"other than volume")
            for k, (ts, length, src, cpos, cbeat) in enumerate(pieces):
                src = src / use_rate if use_rate != 1.0 else src
                if src < 0:                          # the clip starts before its file: silence until the file starts
                    ts, length, src = ts - src, length + src, 0.0
                if src + length > src_len + 1e-6:
                    cut = src + length - src_len
                    if cut > 0.005:
                        self.report["clamped"].append(f"{where}: runs {cut:.2f} s past the end of its file (silence "
                                                      f"in Live): region ends with the file")
                    length = src_len - src
                if length <= 1.0 / self.sr:
                    continue
                first, last = k == 0, k == len(pieces) - 1
                renv = None
                if env:
                    renv = self.region_envelope(env, info["warped"] and info["markers"] >= 2, cpos, cbeat,
                                                ts, length)
                self.region(playlist, cname, sids, ts, length, src, gain, muted,
                            fi if first else 0.0, fo if last else 0.0, renv)
                made += 1
        return made

    def mixer_extras(self, tr):
        """Track settings that change what you hear and have no equivalent here (split stereo pan, the crossfader's
        A / B side): listed in the report."""
        if tr.get("split_pan"):
            left, right = tr["split_pan"]
            self.report["split_pan"].append(f"{tr['name']}: left channel panned {left:+.2f}, right channel {right:+.2f} "
                                            f"(-1 = full left, +1 = full right); here the plain Pan value is used")
        if tr.get("xfade"):
            self.report["crossfade"].append(f"{tr['name']}: assigned to crossfader side {tr['xfade']}")

    def groove_note(self, c, where):
        """A clip with a groove from Live's groove pool: Live moves its notes or audio in time (and in velocity) by the
        groove, scaled by the set's global groove amount. Not carried: the clip plays as placed."""
        gid = _v(c, "./GrooveSettings/GrooveId", str, "-1")
        if gid in (None, "-1", ""):
            return
        name, active = self.song.get("grooves", {}).get(gid, ("a groove not in the set's pool", True))
        amount = self.song.get("groove_amount", 100.0)
        if active and amount > 0:
            self.report["groove"].append(f"{where}: groove {name!r} (global groove amount {amount:g})")

    def sound_changes(self, c, where, info, straight):
        """Live settings of an audio clip that change what it sounds like and that this session does not carry."""
        pc, pf = _v(c, "./PitchCoarse", float, 0.0), _v(c, "./PitchFine", float, 0.0)
        if abs(pc) > 1e-9 or abs(pf) > 1e-9:
            self.report["pitch"].append(f"{where}: transposed {pc:+g} semitones" + (f", detune {pf:+g} cents" if pf else ""))
        if info["warped"] and info["markers"] >= 2 and not straight and _v(c, "./WarpMode", int, None) == 3:
            self.report["repitch"].append(f"{where}: Re-Pitch plays it x{info['rate']:.4f} with its pitch moving "
                                          f"{12 * math.log2(info['rate']):+.2f} semitones; here it is stretched with the pitch kept")
        if any(abs(_v(c, f"./Fades/{k}", float, 0.0)) > 1e-9 for k in
               ("FadeInCurveSkew", "FadeInCurveSlope", "FadeOutCurveSkew", "FadeOutCurveSlope")):
            self.report["fadeshape"].append(f"{where}: fade curve shape (skew / slope): straight-line fades here")
        if _v(c, "./Fades/CrossfadeInState", int, 0):
            self.report["fadeshape"].append(f"{where}: crossfade into the clip before it: plain fades here")

    def region_envelope(self, env, warped, cpos, cbeat, ts, length):
        """Clip envelope points (in the clip's own time: beats when warped, seconds when not) -> region seconds.
        cpos is where in the clip's content this region starts, cbeat the song beat it starts on."""
        env = dedupe_points(env)
        if warped:
            ts_ = np.array([self.tempo.seconds(cbeat + (b - cpos)) - ts for b, _ in env])
        else:
            ts_ = np.array([b - cpos for b, _ in env])
        vs = np.array([max(0.0, min(2.0, v)) for _, v in env])
        inner = [(float(t), float(v)) for t, v in zip(ts_, vs) if 0.0 < t < length]
        pts = [(0.0, float(np.interp(0.0, ts_, vs)))] + inner + [(length, float(np.interp(length, ts_, vs)))]
        return pts

    def source_ids(self, names, sources_el, regions_el, src_len):
        key = tuple(names)
        if key in self.src_ids:
            return list(self.src_ids[key])
        ids = []
        for fn in names:
            sid = self.ids()
            sub(sources_el, "Source", name=fn, take_id="", type="audio", flags="", id=sid, natural_position="a0",
                channel=0, origin="", gain=1)
            ids.append(sid)
        attrs = dict(name=Path(names[0]).stem.split("%")[0], muted=0, opaque=1, locked=0, video_locked=0, automatic=0,
                     whole_file=1, import_=0, external=0, sync_marked=0, left_of_split=0, right_of_split=0, hidden=0,
                     position_locked=0, valid_transients=0, start="a0", length=f"{a(src_len)}@a0",
                     sync_position="a0", ancestral_start="a0", ancestral_length="a0@a0", stretch=1, shift=1,
                     layering_index=0, tags="", contents=0, rgroup=0, envelope_active=0, default_fade_in=0,
                     default_fade_out=0, fade_in_active=1, fade_out_active=1, fade_before_fx=0, scale_amplitude=1,
                     id=self.ids(), type="audio", first_edit="nothing")
        rg = sub(regions_el, "Region", **{k.rstrip("_"): v for k, v in attrs.items()})
        for i, sid in enumerate(ids):
            rg.set(f"source-{i}", sid)
            rg.set(f"master-source-{i}", sid)
        rg.set("channels", str(len(ids)))
        self.src_ids[key] = ids
        return list(ids)

    def region(self, playlist, name, sids, ts, length, src, gain, muted, fi, fo, env):
        if fi + fo > length:                       # Live never lets the two fades overlap; keep their proportion
            k = length / (fi + fo)
            fi, fo = fi * k, fo * k
        attrs = dict(name=name, muted=int(muted), opaque=1, locked=0, video_locked=0, automatic=0, whole_file=0,
                     import_=0, external=0, sync_marked=0, left_of_split=0, right_of_split=0, hidden=0,
                     position_locked=0, valid_transients=0, start=a(src), length=f"{a(length)}@{a(ts)}",
                     sync_position="a0", ancestral_start="a0", ancestral_length="a0@a0", stretch=1, shift=1,
                     layering_index=self.layer, tags="", contents=0, rgroup=0, envelope_active=int(bool(env)),
                     default_fade_in=0, default_fade_out=0, fade_in_active=int(fi > 0), fade_out_active=int(fo > 0),
                     fade_before_fx=0, scale_amplitude=f"{gain:.12g}", id=self.ids(), type="audio",
                     first_edit="nothing")
        self.layer += 1
        rg = sub(playlist, "Region", **{k.rstrip("_"): v for k, v in attrs.items()})
        for i, sid in enumerate(sids):
            rg.set(f"source-{i}", sid)
            rg.set(f"master-source-{i}", sid)
        rg.set("channels", str(len(sids)))
        e = sub(rg, "Envelope")
        if env:
            alist(e, self.ids, "envelope", env, "Exponential")
        else:
            e.set("default", "yes")
        for tag, L, rising in (("FadeIn", fi, True), ("FadeOut", fo, False)):
            node = sub(rg, tag)
            if L <= 0:
                node.set("default", "yes")
                continue
            from hypnomix.project.ardour_edit import fade_curve
            pts = [(x * L, g if rising else 1.0 - g) for x, g in fade_curve("linear")]
            alist(node, self.ids, "fadein" if rising else "fadeout", pts, "Curved")
        return rg

    def midi_extras(self, tr, c, k):
        """MIDI clip settings that shape how the notes play and are not carried (the notes themselves are)."""
        part = []
        notes = c.findall("./Notes/KeyTracks/KeyTrack/Notes/MidiNoteEvent")
        if any(_f(n.get("Probability"), 1.0) < 0.999 for n in notes):
            part.append("note probabilities below 100%")
        if any(abs(_f(n.get("VelocityDeviation"), 0.0)) > 1e-9 for n in notes):
            part.append("velocity deviations")
        envs = len(c.findall("./Envelopes/Envelopes/ClipEnvelope"))
        if envs:
            part.append(f"{envs} controller envelope(s) (pitch bend, mod wheel ...)")
        if part:
            self.report["midi_extra"].append(f"{tr['name']} / MIDI clip {k + 1}: " + ", ".join(part))

    def midi_regions(self, tr, playlist, sources_el, midi_dir):
        made = 0
        for k, c in enumerate(tr["clips"]):
            s, e = _v(c, "./CurrentStart", float), _v(c, "./CurrentEnd", float)
            self.at = f"track {tr['name']!r}, MIDI clip {k + 1}"
            if s is None or e is None:
                self.report["notes"].append(f"{tr['name']} / MIDI clip {k + 1}: the set gives it no readable start or "
                                            f"end: left out")
                continue
            if e <= s:
                continue
            notes = midi_notes(c)
            self.midi_extras(tr, c, k)
            self.groove_note(c, f"{tr['name']} / MIDI clip {k + 1}")
            # not <track>-N.mid: Ardour's own capture files. Unique (case-insensitively), so two tracks whose
            # names clean to the same text (non-ASCII names, say) never share or overwrite a file
            stem = short_stem(re.sub(r'[^\w ().-]', '-', tr['ardour_name']).strip() or "MIDI")
            fn, i = f"{stem} (Live clip {k + 1}).mid", 2
            while fn.lower() in self.midi_names:
                fn, i = f"{stem} (Live clip {k + 1}) {i}.mid", i + 1
            self.midi_names.add(fn.lower())
            write_smf(midi_dir / fn, notes, e - s)
            sid = self.ids()
            sub(sources_el, "Source", name=fn, take_id="", type="midi", flags="Writable,CanRename", id=sid, origin="")
            name = _v(c, "./Name", str, "") or tr["name"]
            rg = sub(playlist, "Region", name=name, muted=int(_v(c, "./Disabled", _true, False)), opaque=0, locked=0,
                     video_locked=0, automatic=0, whole_file=0, external=0, sync_marked=0, left_of_split=0,
                     right_of_split=0, hidden=0, position_locked=0, valid_transients=0, start="b0",
                     length=f"b{int(round((e - s) * TICKS))}@b{int(round(s * TICKS))}", sync_position="b0",
                     ancestral_start="b0", ancestral_length="b0@b0", stretch=1, shift=1, layering_index=self.layer,
                     tags="", contents=0, rgroup=0, id=self.ids(), type="midi", first_edit="nothing")
            rg.set("source-0", sid)
            rg.set("master-source-0", sid)
            self.layer += 1
            tr.setdefault("notes", 0)
            tr["notes"] += len(notes)
            made += 1
        return made

    # ---- the whole session
    def build(self):
        song, out = self.song, self.out
        audio_dir = out / "interchange" / self.name / "audiofiles"
        midi_dir = out / "interchange" / self.name / "midifiles"
        for d in (audio_dir, midi_dir, out / "analysis", out / "dead", out / "export", out / "externals",
                  out / "peaks", out / "plugins"):
            d.mkdir(parents=True, exist_ok=True)
        warn = song["warnings"]
        srcs = Sources(audio_dir, self.sr, warn)
        self.src_ids = {}
        self.midi_names = set()
        self.layer = 0

        root = ET.Element("Session", version="7004", sample_rate=str(self.sr))
        root.attrib = {"version": "7004", "sample-rate": str(self.sr), "name": self.name,
                       "uuid": str(uuid.uuid4()), "session-range-is-free": "1"}
        sub(root, "ProgramVersion", created_with="hypnomix als2ardour", modified_with="hypnomix als2ardour")
        cfg = sub(root, "Config")
        sub(cfg, "Option", name="use-region-fades", value=1)
        sub(cfg, "Option", name="native-file-data-format", value="FormatFloat")
        sub(cfg, "Option", name="native-file-header-format", value="WAVE")
        sub(root, "Metadata")
        sources_el = sub(root, "Sources")
        regions_el = sub(root, "Regions")
        locations = sub(root, "Locations")
        sub(root, "Bundles")
        sub(root, "VCAManager")
        routes = sub(root, "Routes")
        playlists = sub(root, "Playlists")
        sub(root, "UnusedPlaylists")
        groups_el = sub(root, "RouteGroups")

        # names Ardour can use, unique
        used = {"Master"}
        tracks = song["tracks"]
        for tr in tracks:
            base = legal(tr["name"])
            n, i = base, 2
            while n.lower() in {u.lower() for u in used}:
                n, i = f"{base} {i}", i + 1
            used.add(n)
            tr["ardour_name"] = n
            if tr.get("delay"):
                v, samples = tr["delay"]
                self.report["delay"].append(f"{tr['name']}: {v:+g} {'samples' if samples else 'ms'} "
                                            f"({'later' if v > 0 else 'earlier'} than the others in Live)")
        for tr in tracks + [dict(self.song["main"], name="Main track")]:
            self.mixer_extras(tr)
        by_live = {tr["live_id"]: tr for tr in tracks}
        for tr in tracks:
            tr["parent"] = by_live.get(tr["group"]) if tr["group"] not in (None, "-1") else None

        # groups: a bus when the group does something to the sound of its own
        for tr in tracks:
            if tr["kind"] != "group":
                continue
            own = bool(tr["devices"]) or abs(tr["volume"] - 1) > 1e-6 or abs(tr["pan"]) > 1e-6 or tr["muted"] or \
                any(s["value"] > SEND_OFF or s["auto"] for s in tr["sends"]) or any(tr["auto"].values())
            tr["bus"] = own
        returns = [tr for tr in tracks if tr["kind"] == "return"]
        for r in returns:
            r["is_return"] = True
            r["rid"] = self.ids()

        def dest(tr):
            """Which route's inputs this one feeds: the nearest group bus above it, else the master."""
            p = tr["parent"]
            while p is not None and not p.get("bus"):
                p = p["parent"]
            return p

        master = dict(song["main"], ardour_name="Master", colour=None, rid=self.ids(), inputs={}, devices=[])
        master_ins = {0: [], 1: []}
        bus_ins = {}
        out_of = {}
        for tr in tracks:
            if tr["kind"] == "group" and not tr["bus"]:
                continue
            if tr["kind"] == "midi":
                out_of[tr["ardour_name"]] = None
                continue
            target = tr["output"] or ""
            if tr["kind"] != "return" and target and not (target.startswith("AudioOut/GroupTrack") or
                                                         target.startswith("AudioOut/Main") or
                                                         target.startswith("AudioOut/Master") or
                                                         target == "AudioOut/None"):
                self.report["notes"].append(f"{tr['name']}: Live sends its output to {target!r}; here it feeds "
                                            f"the {'group' if dest(tr) else 'master'} like the others: check it")
            # a track in a group whose output Live sets to the Main track skips the group
            to_main = target.startswith("AudioOut/Main") or target.startswith("AudioOut/Master")
            d = dest(tr) if tr["kind"] != "return" and not to_main else None
            if target == "AudioOut/None":
                out_of[tr["ardour_name"]] = None
                continue
            to = d["ardour_name"] if d else "Master"
            out_of[tr["ardour_name"]] = to
            ins = master_ins if d is None else bus_ins.setdefault(to, {0: [], 1: []})
            ins[0].append(f"{tr['ardour_name']}/audio_out 1")
            ins[1].append(f"{tr['ardour_name']}/audio_out 2")
        master["inputs"] = master_ins
        for tr in tracks:
            if tr["kind"] == "group" and tr["bus"]:
                tr["inputs"] = bus_ins.get(tr["ardour_name"], {0: [], 1: []})
            elif tr["kind"] == "return":
                tr["inputs"] = {}

        # aux sends
        slot = 0
        for tr in tracks:
            tr["aux"] = []
            if tr["kind"] == "group" and not tr["bus"]:
                continue
            for s in tr["sends"]:
                if s["index"] >= len(returns) or (s["value"] <= SEND_OFF and not s["auto"]):
                    continue
                r = returns[s["index"]]
                if r is tr:
                    continue
                slot += 1
                tr["aux"].append(dict(s, target_id=r["rid"], target_name=r["ardour_name"], bitslot=slot))

        # route groups
        for tr in tracks:
            if tr["kind"] != "group":
                continue
            kids = [k for k in tracks if k["parent"] is tr]
            if not kids:
                continue
            tr["rg_id"] = self.ids()
            for k in kids:
                k["route_group"] = tr["ardour_name"]

        # routes, in Live's order (master first)
        self.route(routes, master, "master", 0, None)
        order = 1
        for tr in tracks:
            kind = tr["kind"]
            if kind == "group" and not tr["bus"]:
                continue
            self.at = f"track {tr['name']!r}"
            if kind in ("audio", "midi"):
                tr["playlist_id"] = self.ids()
            rkind = {"audio": "audio", "midi": "midi", "group": "bus", "return": "bus"}[kind]
            self.route(routes, tr, rkind, order, out_of.get(tr["ardour_name"]))
            order += 1
            if kind in ("audio", "midi"):
                pl = sub(playlists, "Playlist", id=tr["playlist_id"], name=f"{tr['ardour_name']}.1", type=kind,
                         orig_track_id=tr["rid"], pgroup_id="", shared_with_ids="", frozen=0, combine_ops=0)
                if kind == "audio":
                    tr["regions"] = self.audio_regions(tr, pl, sources_el, regions_el, srcs)
                else:
                    tr["regions"] = self.midi_regions(tr, pl, sources_el, midi_dir)

        for tr in tracks:
            if tr.get("rg_id"):
                kids = [k for k in tracks if k["parent"] is tr and k.get("rid")]
                rgba = (LIVE_COLOURS[tr["colour"]] << 8 | 0xFF) if tr.get("colour") is not None and \
                    0 <= tr["colour"] < len(LIVE_COLOURS) else 0
                g = sub(groups_el, "RouteGroup", id=tr["rg_id"], rgba=rgba, used_to_share_gain=0, name=tr["ardour_name"],
                        relative=1, active=1, hidden=0, gain=0, mute=0, solo=0, recenable=1, select=1,
                        route_active=1, color=0, monitoring=1, group_master_number=-1,
                        routes=" ".join(k["rid"] for k in kids) + " ")
                g.set("sursend_enable", "1")
                if tr.get("bus"):
                    g.set("subgroup-bus", tr["rid"])

        # session range, tempo map
        end = 0.0
        for pl in playlists.iter("Region"):
            L, at = pl.get("length").split("@")
            if L.startswith("a"):
                end = max(end, (int(L[1:]) + int(at[1:])) / SCPS)
            else:
                end = max(end, self.tempo.seconds((int(L[1:]) + int(at[1:])) / TICKS))
        sub(locations, "Location", id=self.ids(), name="session", start="a0", end=a(max(end, 1.0)),
            flags="IsSessionRange", locked=0, timestamp=0, cue=0)
        self.tempo_map(root)
        root.set("id-counter", str(self.ids.n + 1))
        root.set("name-counter", "1")
        root.set("event-counter", "0")
        root.set("vca-counter", "1")
        # no indentation: Ardour (libxml2) keeps whitespace inside an element as a child node, and some loaders
        # (Locations, Sources) treat every child as an element
        f = out / f"{self.name}.ardour"
        atomic.write_text(f, '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n",
                          backup=False)
        self.master = master
        return f

    def tempo_map(self, root):
        tm = sub(root, "TempoMap", superclocks_per_second=SCPS)
        tempos = sub(tm, "Tempos")
        tp = self.tempo
        bar_q = self.song["num"] * 4.0 / self.song["den"]
        for b, v in tp.segments():                  # constant tempos only: a ramp is already a run of small exact steps
            q = int(round(b * TICKS))
            b = q / TICKS                           # the position as Ardour will hold it; its time is exact for that
            bar = int(b // bar_q)
            beat_in = b - bar * bar_q
            bbt = f"{bar + 1}|{int(beat_in * self.song['den'] / 4) + 1}|{int(round((beat_in % 1) * TICKS))}"
            sub(tempos, "Tempo", npm=f"{v:.9g}", enpm=f"{v:.9g}", note_type=4, type="Constant", locked_to_meter=0,
                continuing=0, active=1, sclock=int(round(tp.seconds(b) * SCPS)), quarters=f"{q // TICKS}:{q % TICKS}",
                bbt=bbt, omega=0)
        meters = sub(tm, "Meters")
        sub(meters, "Meter", note_value=self.song["den"], divisions_per_bar=self.song["num"], sclock=0,
            quarters="0:0", bbt="1|1|0")
        sub(tm, "MusicTimes")


# ---------------------------------------------------------------- report
def report_md(song, w, f, sr):
    tp = song["tempo"]
    barq = song["num"] * 4.0 / song["den"]
    bar = lambda beat: f"bar {beat / barq + 1:.0f}"
    L = [f"# Import report: {song['path'].name} -> {f.name}", "",
         f"Made by `hypnomix als2ardour` from `{song['path']}` (read only; nothing was written next to it)"
         + (f", a set saved by Live {song['live']}." if song.get("live") else "."),
         f"Session: {sr} Hz, {tp.bpm:g} BPM, {song['num']}/{song['den']}. Audio files were COPIED into "
         f"`interchange/{w.name}/audiofiles` (one mono file per channel), so this session does not depend on the "
         f"Live project folder.", ""]
    if not tp.constant:
        segs = tp.segments()
        L += [f"**Tempo automation:** {len(tp.steps)} step(s) and {len(tp.ramps)} ramp(s). Every audio region is "
              f"placed in seconds exactly where Live plays it, and a tempo step is written as a step."]
        if tp.ramps:
            where = ", ".join(f"{bar(a[0])} to {bar(b[0])} ({a[1]:g} to {b[1]:g} BPM)" for a, b in tp.ramps[:12])
            L += [f"Tempo ramps ({where}{', ...' if len(tp.ramps) > 12 else ''}) are written as runs of small constant "
                  f"tempos ({len(segs)} tempo points in all), each exact in time at its ends, so the tempo map agrees "
                  f"with itself and MIDI regions (which HypnoMix Studio keeps in beats) follow the same clock as the audio. "
                  f"Inside a ramp the written tempo differs from Live's smooth curve: a point between two steps can be "
                  f"up to {tp.ramp_error(segs):.2f} ms from where Live has it. This was not opened in HypnoMix Studio itself; "
                  f"check MIDI regions that follow a ramp."]
        L += [""]
    L += ["## Not carried: rebuild by hand", "",
          "- **Devices and plug-ins are not carried.** Each track's Live devices are listed below; no equivalent "
          "was guessed. Levels here are the faders and clip gains only, so the session will not sound like the "
          "Live mix until the processing is rebuilt.",
          "- **Pan law:** Live's pan and HypnoMix Studio's stereo panner differ off-centre; positions are carried as they "
          "are (centred tracks are identical).",
          "- Take lanes, Session-view clips and device automation are not carried (counts below).",
          "- **MIDI tracks** carry their notes but no instrument (and so no sends yet): load one and add the sends.",
          "- **Automation** keeps every point; between points HypnoMix Studio's curve can differ a little from Live's.",
          "- **Clip volume envelopes** become region gain envelopes (Live's value read as a gain factor); this has "
          "not been checked against Live's own playback yet.",
          "- **Master output:** if you hear nothing when it opens, connect the Master to your outputs once "
          "(Window > Audio Connections) and save.", ""]
    sc = []
    if w.report["pitch"]:
        sc += [f"- **Clip transpose / detune is NOT carried ({len(w.report['pitch'])}):** Live plays these clips "
               f"at another pitch; here they play at the recorded pitch.", *[f"  - {x}" for x in w.report["pitch"]]]
    if w.report["repitch"]:
        sc += [f"- **Re-Pitch warp mode is NOT carried ({len(w.report['repitch'])}):** in Live the speed and the pitch "
               f"change together.", *[f"  - {x}" for x in w.report["repitch"]]]
    if w.report["delay"]:
        sc += [f"- **Track delay is NOT carried ({len(w.report['delay'])}):** Live moves these tracks in time against "
               f"the rest; here they are not moved.", *[f"  - {x}" for x in w.report["delay"]]]
    if w.report["split_pan"]:
        sc += [f"- **Split stereo pan is NOT carried ({len(w.report['split_pan'])}):** Live pans these tracks' left and "
               f"right channels separately.", *[f"  - {x}" for x in w.report["split_pan"]]]
    if w.report["groove"]:
        sc += [f"- **Grooves are NOT carried ({len(w.report['groove'])}):** Live moves these clips' notes or audio in "
               f"time (and velocity) by the groove; here they play exactly as placed.",
               *[f"  - {x}" for x in w.report["groove"]]]
    if w.report["crossfade"]:
        pos = song.get("crossfader") or 0.0
        sc += [f"- **Crossfader A/B assignments are NOT carried ({len(w.report['crossfade'])}):** the crossfader is at "
               f"{pos:+.2f} in this set (-1 = side A, +1 = side B)"
               + (", so in Live it turns down the side it moves away from; here nothing is turned down."
                  if abs(pos) > 1e-3 else "; at the centre this sounds the same, but it will not once the crossfader is "
                  "moved (and nothing here takes the crossfader's automation)."),
               *[f"  - {x}" for x in w.report["crossfade"]]]
    if w.report["fadeshape"]:
        sc += [f"- **Fade curve shapes and crossfades are approximated ({len(w.report['fadeshape'])}):**",
               *[f"  - {x}" for x in w.report["fadeshape"]]]
    if w.report["midi_extra"]:
        sc += [f"- **MIDI clip settings NOT carried ({len(w.report['midi_extra'])}):** these change how the notes "
               f"play once an instrument is loaded.", *[f"  - {x}" for x in w.report["midi_extra"]]]
    if song.get("meter_changes"):
        ch = ", ".join(f"{bar(b)} (beat {b:g}) to {n}/{d}" for b, n, d in song["meter_changes"][:12])
        sc += [f"- **Time-signature changes are NOT carried ({len(song['meter_changes'])}):** the session stays in "
               f"{song['num']}/{song['den']}; Live changes at {ch}. Audio and MIDI do not move, only the bar grid "
               f"differs from Live's from there on."]
    if song.get("locators"):
        names = ", ".join(f"{n or '(no name)'} ({bar(b)})" for b, n in song["locators"][:40])
        sc += [f"- **Locators are NOT carried ({len(song['locators'])}):** {names}"
               + (", ..." if len(song["locators"]) > 40 else "") + "."]
    if sc:
        L += ["## Live settings that change what you hear and are not carried", "", *sc, ""]
    if w.outside:
        shown = sorted(w.outside)[:40]
        L += ["## Samples from outside the Live project folder", "",
              f"{len(w.outside)} sample file(s) are not inside the set's own folder (Live's library, a pack or another "
              f"drive). They were copied into the session like the rest, so nothing here points back to them:", "",
              *[f"- `{x}` ({w.outside[x]} clip(s))" for x in shown],
              *([f"- ... and {len(w.outside) - 40} more"] if len(w.outside) > 40 else []), ""]
    L += ["## Tracks", "", "| # | Track | Kind | Here | Fader | Regions | Live devices (not carried) | Other |",
          "|---|---|---|---|---|---|---|---|"]
    for i, tr in enumerate(song["tracks"], 1):
        here = {"audio": "audio track", "midi": "MIDI track (no instrument)", "return": "bus + aux sends",
                "group": "route group + bus" if tr.get("bus") else "route group only"}[tr["kind"]]
        if tr.get("parent"):
            here += f", in {tr['parent']['name']}"
        other = []
        if tr["take_lanes"]:
            other.append(f"{tr['take_lanes']} take-lane clip(s)")
        if tr["session_clips"]:
            other.append(f"{tr['session_clips']} Session clip(s)")
        if tr.get("other_auto"):
            other.append(f"{len(tr['other_auto'])} device automation lane(s)")
        if tr["kind"] == "midi":
            other.append(f"{tr.get('notes', 0)} notes carried")
        sends = [f"to {s['target_name']} {20 * math.log10(max(s['value'], 1e-9)):+.1f} dB{' pre' if s['pre'] else ''}"
                 for s in tr.get("aux", [])]
        if sends:
            other.append("sends " + ", ".join(sends))
        if tr["muted"]:
            other.append("switched off (muted)")
        fader = f"{20 * math.log10(tr['volume']):+.1f} dB" if tr["volume"] > 0 else "-inf"
        devs = ", ".join(tr["devices"]) or "none"
        nm = tr["name"] + (f" (here: {tr['ardour_name']})" if tr.get("ardour_name", tr["name"]) != tr["name"] else "")
        esc = lambda x: x.replace("|", "\\|")
        L.append(f"| {i} | {esc(nm)} | {tr['kind']} | {esc(here)} | {fader} | {tr.get('regions', 0)} | {esc(devs)} | "
                 f"{esc('; '.join(other))} |")
    m = song["main"]
    L += ["", f"Master: fader {20 * math.log10(m['volume']) if m['volume'] > 0 else -math.inf:+.1f} dB. "
          f"Main-track devices (not carried): {', '.join(song.get('main_devices', [])) or 'none'}.", ""]
    L += ["## Warped clips", ""]
    if not w.report["warped"] and not w.report["bent"]:
        L += ["Every warped clip plays at the set's own tempo along one straight line: carried exactly, no "
              "stretching.", ""]
    if w.report["warped"]:
        L += [f"**Plain constant ratio ({len(w.report['warped'])}):** one straight line, at another speed than "
              "recorded. Carried as a stretched copy of the file (Rubber Band, pitch kept), so timing matches; the "
              "copy is new audio, not the original file.", ""]
        L += [f"- {x['where']}: plays at x{x['rate']:.4f}" for x in w.report["warped"]] + [""]
    if w.report["bent"]:
        L += [f"**Real warp markers: NOT carried ({len(w.report['bent'])}).** HypnoMix Studio has no warp maps yet; these "
              "are placed along the straight line from their first to last marker, so their timing drifts from "
              "Live between markers by up to the amount shown.", ""]
        L += [f"- {x['where']}: {x['markers']} markers, up to {x['drift']:.0f} ms off" for x in w.report["bent"]]
        L += [""]
    L += ["Live's own warp algorithms (Beats, Tones, Texture, Complex) are not Rubber Band, so a stretched copy "
          "sounds a little different from Live's playback of the same clip.", ""] if w.report["warped"] else []
    for key, title in (("missing", "Missing or unreadable audio (left out)"),
                       ("clamped", "Clips longer than their file"),
                       ("uncarried_env", "Clip envelopes not carried"), ("notes", "Check these")):
        if w.report[key]:
            L += [f"## {title}", ""] + [f"- {x}" for x in w.report[key]] + [""]
    if song["warnings"]:
        L += ["## Warnings", ""] + [f"- {x}" for x in song["warnings"]] + [""]
    return "\n".join(L)


# ---------------------------------------------------------------- entry
def _remove_empty(folders):
    """Take away folders this run made (deepest first), as far as they are still empty."""
    for d in folders:
        try:
            d.rmdir()
        except OSError:
            break


def _move_up(tmp, out):
    """Move what was built in `tmp` (a folder inside `out`) up into `out`, and remove `tmp`. If a move fails, what was
    already moved goes back, so `out` is left empty."""
    moved = []
    try:
        for item in sorted(tmp.iterdir()):
            os.replace(item, out / item.name)
            moved.append(item.name)
        tmp.rmdir()
    except BaseException:
        for n in moved:
            try:
                os.replace(out / n, tmp / n)
            except OSError:
                pass
        raise


def convert(als, out, sr=None, log=print):
    """Make the new session at `out`. It is built in a hidden folder next to `out` and renamed into place at the end:
    on any failure nothing is left behind (`out` is not created). Returns (the .ardour file, the report, the Writer)."""
    als = Path(als).expanduser().resolve()
    out = Path(out).expanduser().resolve()
    if sr is not None and sr <= 0:
        raise SystemExit(f"--sr {sr}: the sample rate must be a positive number of Hz (for example 48000)")
    if not als.exists():
        raise SystemExit(f"{als}: no such set")
    if out.exists() and not out.is_dir():
        raise SystemExit(f"{out}: is a file, not a folder (choose a new folder)")
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out}: already exists and is not empty (choose a new folder)")
    if out == als.parent or als.parent in out.parents:
        raise SystemExit(f"{out}: inside the Live project folder; write the new session somewhere else")
    song = read_set(als)
    main_el = song["root"].find(".//MainTrack")
    if main_el is None:
        main_el = song["root"].find(".//MasterTrack")
    song["main_devices"] = devices(main_el) if main_el is not None else []
    rate = session_rate(song, sr)
    existed = out.exists()                              # an empty folder the person made: its parent may not be writable
    made = []                                           # parent folders this run creates (taken away again on failure)
    try:
        if existed:
            tmp = out / f".hypnomix-tmp-{os.getpid()}"  # built inside it and moved up: the folder itself never goes away
        else:
            up = out.parent
            while not up.exists():
                made.append(up)
                up = up.parent
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.parent / f".{out.name}.tmp-{os.getpid()}"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
    except OSError as e:
        _remove_empty(made)
        raise SystemExit(f"{out}: cannot be created here ({e.strerror or e}); choose a folder you can write to") from e
    w = Writer(song, tmp, rate, log, name=out.name)
    try:
        f_tmp = w.build()
        atomic.write_text(tmp / "IMPORT-REPORT.md", report_md(song, w, out / f_tmp.name, rate), backup=False)
        if existed:
            _move_up(tmp, out)
        else:
            os.replace(tmp, out)
    except BaseException as e:
        shutil.rmtree(tmp, ignore_errors=True)
        _remove_empty(made)
        if isinstance(e, (SystemExit, KeyboardInterrupt)):
            raise
        if isinstance(e, OSError) and e.errno == errno.ENOSPC:
            why = "the disk is full"
        else:
            why = f"{type(e).__name__}: {e}"
        raise SystemExit(f"{als.name}: could not be converted ({w.at or 'reading the set'}): {why}. Nothing was "
                         f"written: {out} {'is as it was (empty)' if existed else 'was not created'}, so you can run it "
                         f"again.") from e
    return out / f_tmp.name, out / "IMPORT-REPORT.md", w


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix als2ardour", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als", help="the Live set (.als); only read")
    ap.add_argument("out", help="the new session folder (must not exist yet, or be empty)")
    ap.add_argument("--sr", type=int, help="session sample rate in Hz (default: the rate most of the set's audio uses)")
    a_ = ap.parse_args(argv)
    f, rep, w = convert(a_.als, a_.out, a_.sr)
    n = sum(tr.get("regions", 0) for tr in w.song["tracks"])
    print(f"wrote {f}")
    print(f"  {len(w.song['tracks'])} Live tracks -> {n} regions; report: {rep}")
    for key, label in (("bent", "clips with real warp markers NOT carried as warps"),
                       ("warped", "constant-ratio warped clips carried as stretched copies"),
                       ("missing", "clips left out (missing audio)"),
                       ("pitch", "transposed clips (the transpose is NOT carried)"),
                       ("repitch", "Re-Pitch clips (not carried)"),
                       ("delay", "tracks with a track delay (not carried)"),
                       ("split_pan", "tracks in split stereo pan (not carried)"),
                       ("groove", "clips with a groove (not carried)"),
                       ("crossfade", "tracks on the crossfader's A or B side (not carried)"),
                       ("fadeshape", "clips with a fade curve shape or crossfade (approximated)"),
                       ("midi_extra", "MIDI clips with settings that are not carried")):
        if w.report[key]:
            print(f"  ! {len(w.report[key])} {label} (listed in the report)")
    for n, label in ((len(w.song.get("meter_changes") or []), "time-signature changes (not carried)"),
                     (len(w.song.get("locators") or []), "locators (not carried)"),
                     (len(w.outside), "samples from outside the project folder (copied)")):
        if n:
            print(f"  ! {n} {label} (listed in the report)")
    print("  devices are not carried: each track's Live devices are listed in the report")


if __name__ == "__main__":
    main()
