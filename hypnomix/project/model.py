"""A DAW-neutral picture of a song project: tracks, clips, devices, automation. Times are in SECONDS.

Readers fill it from a Live set (`als.py`) or a REAPER project (`reaper.py`); tools that only need to know
what is in the song (and to render it) work from this, whatever DAW made it. Each object keeps `native`, the
element or chunk it was read from, so a DAW-specific writer can change exactly that and nothing else.
"""
from dataclasses import dataclass, field
from pathlib import Path
import math
import re

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
    kind: str = "audio"
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
    daw: str                       # "live" | "reaper"
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
        return [t for t in self.tracks if t.kind == "audio" and t.clips and (include_off or t.on)]

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
_SRC = {}


def _source(path, sr):
    key = (str(path), sr)
    if key not in _SRC:
        from hypnomix.core import dsp
        y, _ = dsp.load(path, sr)
        _SRC[key] = y.mean(1).astype(np.float64)
    return _SRC[key]


def _stretched(path, rate, sr):
    """Whole source played at `rate` with pitch kept (Rubber Band when installed)."""
    from hypnomix.session.render import stretched
    return stretched(Path(path), 1.0 / rate, sr)


def fade_curve(n, shape, rising=True):
    """REAPER fade shapes, approximately: 0 linear, 1 fast start, 2 fast end, 3/4 fast/slow S, 5/6 sharp."""
    if n <= 0:
        return np.ones(0)
    x = np.linspace(0, 1, n, endpoint=False) + 0.5 / n
    if shape == 1:
        y = 1 - (1 - x) ** 2
    elif shape == 2:
        y = x ** 2
    elif shape in (3, 4):
        y = 0.5 - 0.5 * np.cos(np.pi * x)
    elif shape in (5, 6):
        y = x ** 4 if shape == 6 else 1 - (1 - x) ** 4
    else:
        y = x
    return y if rising else y[::-1]


def render_clip(c, sr, warn, name=""):
    """One clip (its active take) as mono samples, clip-length long, gain and fades applied."""
    tk = c.take
    n = int(round(c.length * sr))
    if tk is None or tk.kind != "audio" or tk.path is None or c.muted or n <= 0:
        return None
    if not Path(tk.path).exists():
        warn.append(f"{name}: missing file {Path(tk.path).name}")
        return None
    try:
        if abs(tk.rate - 1.0) > 1e-6 and tk.preserve_pitch:
            src = _stretched(tk.path, tk.rate, sr)
            k = 1.0 / tk.rate                 # source seconds -> seconds in the stretched copy
        else:
            src = _source(tk.path, sr)
            k = 1.0
    except Exception as e:
        warn.append(f"{name}: could not read {Path(tk.path).name} ({type(e).__name__}): clip left out")
        return None
    t = np.arange(n) / sr                             # seconds since the clip starts
    pos = tk.offset + t * tk.rate                     # source seconds
    s0, slen = (tk.section if tk.section else (0.0, len(src) / sr / k))
    if c.loop and slen > 0:
        pos = s0 + np.mod(pos, slen)
    else:
        pos = s0 + pos
    idx = pos * k * sr
    if abs(tk.rate - 1.0) <= 1e-6 or tk.preserve_pitch:
        i = np.round(idx).astype(np.int64)
        ok = (i >= 0) & (i < len(src))
        seg = np.zeros(n)
        seg[ok] = src[i[ok]]
    else:                                             # varispeed: pitch follows the rate, like tape
        seg = np.interp(idx, np.arange(len(src)), src, left=0.0, right=0.0)
    seg *= c.level
    fi, fo = min(n, int(c.fade_in * sr)), min(n, int(c.fade_out * sr))
    if fi:
        seg[:fi] *= fade_curve(fi, c.fade_in_shape, True)
    if fo:
        seg[n - fo:] *= fade_curve(fo, c.fade_out_shape, False)
    return seg


def render_clips(track, N, sr, warn):
    y = np.zeros(N)
    for c in track.clips:
        seg = render_clip(c, sr, warn, track.name)
        if seg is None:
            continue
        i = int(round(c.start * sr))
        if i < 0:
            seg, i = seg[-i:], 0
        L = min(len(seg), N - i)
        if L > 0:
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
