"""A DAW-neutral picture of a song project: tracks, clips, devices, automation. Times are in SECONDS.

Readers fill it from a Live set (`als.py`) or a REAPER project (`reaper.py`); tools that only need to know
what is in the song (and to render it) work from this, whatever DAW made it. Each object keeps `native`, the
element or chunk it was read from, so a DAW-specific writer can change exactly that and nothing else.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
import math
import os
import re
import threading

import numpy as np


@dataclass
class Device:
    name: str                      # what the person sees ("ReaEQ (Cockos)", "EQ Eight")
    kind: str = ""                 # "VST", "VST3", "AU", "JS", "CLAP", "Live" ...
    on: bool = True
    preset: str = ""
    params: dict = field(default_factory=dict)   # readable parameters only (name -> value)
    native: object = None


@dataclass
class Take:
    name: str
    path: Path = None              # source audio file (None for MIDI / empty)
    offset: float = 0.0            # source seconds at the clip's start
    gain: float = 1.0              # linear; negative = polarity flipped
    rate: float = 1.0
    preserve_pitch: bool = True
    section: tuple = None          # (start, length) in the source when the take plays a section of a file
    stretch: list = None           # REAPER stretch markers [(take time, source seconds)], sorted
    kind: str = "audio"
    extra_paths: list = field(default_factory=list)   # more channels of one clip, one file each (Ardour)
    native: object = None


@dataclass
class Clip:
    name: str
    start: float                   # timeline seconds
    length: float                  # timeline seconds
    takes: list = field(default_factory=list)
    active: int = 0                # index of the take that plays
    gain: float = 1.0              # clip / item volume, linear (multiplies the take's)
    loop: bool = False             # source repeats when the clip is longer than it
    fade_in: float = 0.0           # seconds
    fade_out: float = 0.0
    fade_in_shape: int = 0
    fade_out_shape: int = 0
    muted: bool = False
    stretch_markers: int = 0       # REAPER stretch markers / Live warp markers bending the timing
    fade_in_curve: list = None     # [(fraction 0..1 of the fade, gain)] when the DAW stores the curve itself
    fade_out_curve: list = None
    envelope: list = None          # clip gain envelope [(seconds from the clip start, gain)]
    opaque: bool = False           # covers the clips under it (Ardour layers) instead of mixing with them
    layer: int = 0                 # stacking order when clips overlap: higher plays on top
    native: object = None

    @property
    def end(self):
        return self.start + self.length

    @property
    def take(self):
        return self.takes[self.active] if self.takes else None

    @property
    def path(self):
        return self.take.path if self.take else None

    @property
    def kind(self):
        return self.take.kind if self.take else "empty"

    @property
    def level(self):
        """Linear gain heard (clip x take), polarity included."""
        return self.gain * (self.take.gain if self.take else 1.0)


@dataclass
class Track:
    name: str
    index: int
    kind: str = "audio"            # "audio", "midi", "folder" (a group / bus), "return", "master"
    clips: list = field(default_factory=list)
    devices: list = field(default_factory=list)
    envelopes: dict = field(default_factory=dict)  # "Volume", "Pan", "<Device>/<Param>" -> [(seconds, value)]
    volume: float = 1.0            # fader, linear
    pan: float = 0.0               # -1 left .. +1 right
    muted: bool = False
    solo: bool = False
    polarity: bool = False         # phase flipped on the track
    parent: "Track" = None         # the folder / group this track sits in
    native: object = None

    @property
    def on(self):
        """Heard: not muted, and no folder above it muted."""
        t = self
        while t is not None:
            if t.muted:
                return False
            t = t.parent
        return True

    @property
    def volume_db(self):
        return 20 * math.log10(self.volume) if self.volume > 0 else -math.inf

    @property
    def safe_name(self):
        return re.sub(r'[\\/:*?"<>|]', "-", self.name)


@dataclass
class Project:
    path: Path
    daw: str                       # "live" | "reaper" | "ardour"
    tempo: float = 120.0
    beats_per_bar: int = 4
    sample_rate: int = 44100
    tracks: list = field(default_factory=list)
    tempo_changes: int = 0         # points on a tempo map (bars are only exact with a constant tempo)
    native: object = None
    renderer: object = None        # DAW-specific track renderer, set by the reader: f(track, N, sr, warn) -> mono

    # ------------------------------------------------------------ lookups
    def track(self, name):
        low = name.lower()
        return next((t for t in self.tracks if t.name.lower() == low), None) or \
            next((t for t in self.tracks if t.name.lower().startswith(low)), None)

    def audio_tracks(self, include_off=False):
        """Tracks that play audio: audio tracks, and folder tracks with audio items of their own (REAPER)."""
        return [t for t in self.tracks if (t.kind == "audio" or (t.kind == "folder" and any(c.kind == "audio" for c in t.clips)))
                and t.clips and (include_off or t.on)]

    def children(self, folder):
        return [t for t in self.tracks if t.parent is folder]

    def end(self):
        ends = [c.end for t in self.tracks if t.on for c in t.clips if not c.muted]
        return max(ends) if ends else 0.0

    def bar(self, seconds):
        """1-based bar number at a time (constant tempo; see tempo_changes)."""
        return 1 + seconds * self.tempo / 60.0 / self.beats_per_bar

    def where(self, seconds):
        """'bar.beat.sixteenths' like the DAWs show, from seconds."""
        beats = seconds * self.tempo / 60.0
        b = int(beats // self.beats_per_bar)
        rem = beats - b * self.beats_per_bar
        return f"{b + 1}.{int(rem) + 1}.{int((rem % 1) * 4) + 1:02d}"

    def missing(self):
        """[(track, clip, path)] for every clip whose audio file can't be found."""
        out = []
        for t in self.tracks:
            for c in t.clips:
                for tk in c.takes:
                    if tk.kind == "audio" and tk.path is not None and not Path(tk.path).exists():
                        out.append((t, c, tk.path))
        return out

    # ------------------------------------------------------------ render
    def render(self, track, sr=44100, length=None, warn=None):
        """One track's clips as heard, mono float, from 0 s: clip/take gain and fades, no fader or effects."""
        n = int(((length if length is not None else self.end()) + 2.0) * sr)
        warn = warn if warn is not None else []
        if self.renderer is not None:
            return self.renderer(track, n, sr, warn)
        return render_clips(track, n, sr, warn)


# ---------------------------------------------------------------- generic renderer (seconds-based clips)
_SRC = OrderedDict()                   # (path, sr, mtime_ns, size) -> mono samples; least recently used first
_SRC_MAX_ITEMS = 48                    # a long-lived process (the app, the REAPER panel) must not grow without limit
_SRC_MAX_BYTES = 1 << 30
_SRC_LOCK = threading.Lock()


def _source(path, sr):
    """The file's mono samples at `sr`. The cache key holds the file's modified time and size, so a file that changed
    on disk is read again, and the cache keeps at most _SRC_MAX_ITEMS files / _SRC_MAX_BYTES of samples."""
    st = os.stat(path)                                       # a missing file raises here, as reading it would
    key = (str(path), sr, st.st_mtime_ns, st.st_size)
    with _SRC_LOCK:
        if key in _SRC:
            _SRC.move_to_end(key)
            return _SRC[key]
    from hypnomix.core import dsp
    y, _ = dsp.load(path, sr)
    y = y.mean(1).astype(np.float64)
    with _SRC_LOCK:
        for k in [k for k in _SRC if k[:2] == key[:2]]:      # an older version of the same file
            del _SRC[k]
        _SRC[key] = y
        while len(_SRC) > 1 and (len(_SRC) > _SRC_MAX_ITEMS or sum(v.nbytes for v in _SRC.values()) > _SRC_MAX_BYTES):
            _SRC.popitem(last=False)
    return y


def _stretched(path, rate, sr):
    """Whole source played at `rate` with pitch kept (Rubber Band when installed)."""
    from hypnomix.session.render import stretched
    return stretched(Path(path), 1.0 / rate, sr)


def fade_curve(n, shape, rising=True):
    """REAPER's fade shapes, measured from REAPER's own renders (sample i of n is at x = i/n):
    0 linear, 1 1-(1-x)^2, 2 x^2, 3 1-(1-x)^4, 4 x^4, 5 smooth S (3x^2-2x^3), 6 sharp S (power-4 halves),
    7 equal power (sin, REAPER's crossfades between overlapping items)."""
    if n <= 0:
        return np.ones(0)
    x = np.arange(n) / n
    if shape == 1:
        y = 1 - (1 - x) ** 2
    elif shape == 2:
        y = x ** 2
    elif shape == 3:
        y = 1 - (1 - x) ** 4
    elif shape == 4:
        y = x ** 4
    elif shape == 5:
        y = 3 * x ** 2 - 2 * x ** 3
    elif shape == 7:
        y = np.sin(x * np.pi / 2)
    elif shape == 6:
        y = np.where(x < 0.5, 0.5 * (2 * x) ** 4, 1 - 0.5 * (2 - 2 * x) ** 4)
    else:
        y = x
    return y if rising else y[::-1]


def _curve(n, pts, rising):
    """A stored fade curve [(fraction, gain)] resampled to n samples (sample i of n is at i/n, as fade_curve)."""
    x = np.arange(n) / n
    f, g = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
    return np.interp(x, f, g)


def fade_window(c, n, sr):
    """The clip's fade-in / fade-out gain over its n samples (1 in between)."""
    w = np.ones(n)
    fi, fo = min(n, int(c.fade_in * sr)), min(n, int(c.fade_out * sr))
    if fi:
        w[:fi] *= _curve(fi, c.fade_in_curve, True) if c.fade_in_curve else fade_curve(fi, c.fade_in_shape, True)
    if fo:
        w[n - fo:] *= _curve(fo, c.fade_out_curve, False) if c.fade_out_curve else \
            fade_curve(fo, c.fade_out_shape, False)
    return w


def stretch_map(tk, take_t):
    """Source seconds for take-time positions through REAPER stretch markers [(take time, source seconds)]: straight
    lines between markers; before the first and after the last the source runs at normal speed (measured: REAPER
    7.86 renders match this sample for sample in varispeed mode)."""
    pos = np.array([m[0] for m in tk.stretch], dtype=float)
    src = np.array([m[1] for m in tk.stretch], dtype=float)
    out = np.interp(take_t, pos, src)
    out = np.where(take_t < pos[0], src[0] + (take_t - pos[0]), out)
    return np.where(take_t > pos[-1], src[-1] + (take_t - pos[-1]), out)


def _read_take(tk, path, n, sr, loop):
    """n samples of one source file as the take plays it."""
    if tk.stretch:
        # stretch markers: every segment plays at its own speed. Read along the marker map (varispeed per segment,
        # like Live's many-warp-marker clips): timing exact; with "preserve pitch" on, REAPER keeps the pitch and
        # this reading shifts it a little where a segment is stretched a lot
        src = _source(path, sr)
        sp = stretch_map(tk, np.arange(n) / sr * tk.rate)
        if tk.section:
            sp = sp + tk.section[0]
        return np.interp(sp * sr, np.arange(len(src)), src, left=0.0, right=0.0)
    if abs(tk.rate - 1.0) > 1e-6 and tk.preserve_pitch:
        src = _stretched(path, tk.rate, sr)
        k = 1.0 / tk.rate                 # source seconds -> seconds in the stretched copy
    else:
        src = _source(path, sr)
        k = 1.0
    t = np.arange(n) / sr                             # seconds since the clip starts
    pos = tk.offset + t * tk.rate                     # source seconds
    s0, slen = (tk.section if tk.section else (0.0, len(src) / sr / k))
    if loop and slen > 0:
        pos = s0 + np.mod(pos, slen)
    else:
        pos = s0 + pos
    idx = pos * k * sr
    if abs(tk.rate - 1.0) <= 1e-6 or tk.preserve_pitch:
        i = np.round(idx).astype(np.int64)
        ok = (i >= 0) & (i < len(src))
        seg = np.zeros(n)
        seg[ok] = src[i[ok]]
        return seg
    return np.interp(idx, np.arange(len(src)), src, left=0.0, right=0.0)   # varispeed: pitch follows the rate


def render_clip(c, sr, warn, name=""):
    """One clip (its active take) as mono samples, clip-length long, gain, envelope and fades applied."""
    tk = c.take
    n = int(round(c.length * sr))
    if tk is None or tk.kind != "audio" or tk.path is None or c.muted or n <= 0:
        return None
    paths = [tk.path] + list(tk.extra_paths or [])
    gone = [p for p in paths if not Path(p).exists()]
    if gone:
        warn.append(f"{name}: missing file {Path(gone[0]).name}")
        return None
    try:
        seg = sum(_read_take(tk, p, n, sr, c.loop) for p in paths) / len(paths)
    except Exception as e:
        warn.append(f"{name}: could not read {Path(tk.path).name} ({type(e).__name__}): clip left out")
        return None
    seg *= c.level
    if c.envelope:
        t = np.arange(n) / sr
        seg *= np.interp(t, [p[0] for p in c.envelope], [p[1] for p in c.envelope])
    return seg * fade_window(c, n, sr)


def render_clips(track, N, sr, warn):
    """Clips summed onto the timeline. An opaque clip (Ardour) covers what is under it, crossfading through
    its own fades, so clips are laid down from the lowest layer up."""
    y = np.zeros(N)
    for c in sorted(track.clips, key=lambda c: (c.layer, c.start)):
        seg = render_clip(c, sr, warn, track.name)
        if seg is None:
            continue
        i = int(round(c.start * sr))
        cover = fade_window(c, len(seg), sr) if c.opaque else None
        if i < 0:
            seg, i = seg[-i:], 0
            cover = cover[-len(seg):] if cover is not None else None
        L = min(len(seg), N - i)
        if L > 0:
            if cover is not None:
                y[i:i + L] *= 1.0 - cover[:L]
            y[i:i + L] += seg[:L]
    return y


def mixdown(project, sr=44100, tracks=None, length=None, warn=None):
    """Stereo sum of tracks with faders and pans (no effects, no automation): a rough mix for key and tuning."""
    tracks = tracks if tracks is not None else project.audio_tracks()
    n = int(((length if length is not None else project.end()) + 2.0) * sr)
    out = np.zeros((n, 2))
    for t in tracks:
        y = project.render(t, sr, length, warn)[:n]
        g, p = t.volume, max(-1.0, min(1.0, t.pan))
        par = t.parent
        while par is not None:
            g *= par.volume
            par = par.parent
        if t.polarity:
            g = -g
        l, r = math.cos((p + 1) * math.pi / 4), math.sin((p + 1) * math.pi / 4)
        out[: len(y), 0] += y * g * l * math.sqrt(2)
        out[: len(y), 1] += y * g * r * math.sqrt(2)
    return out


# ---------------------------------------------------------------- envelopes as heard
_FADER = None


def _fader_table():
    global _FADER
    if _FADER is None:
        import json
        d = json.loads((Path(__file__).parent / "reaper_fader.json").read_text())
        _FADER = (np.array(d["db"]), np.array(d["fader"]))
    return _FADER


def to_fader(amp):
    """Amplitude -> REAPER's fader-scaled envelope value (from REAPER's own numbers)."""
    db, fd = _fader_table()
    a = np.maximum(np.asarray(amp, dtype=float), 1e-12)
    return np.interp(20 * np.log10(a), db, fd, left=0.0)


def from_fader(f):
    db, fd = _fader_table()
    f = np.asarray(f, dtype=float)
    return np.where(f <= fd[0], 0.0, 10 ** (np.interp(f, fd, db) / 20))


def envelope_at(points, t, fader=False):
    """Envelope value(s) at time(s) t: straight lines between points, held outside them. fader=True follows a
    REAPER volume envelope in fader-scaled mode (VOLTYPE 1), which runs straight in fader position, not amplitude."""
    xs = [p[0] for p in points]
    vs = np.array([p[1] for p in points], dtype=float)
    if not fader:
        return np.interp(t, xs, vs)
    return from_fader(np.interp(t, xs, to_fader(vs)))
