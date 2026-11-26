#!/usr/bin/env python3
"""Render audio tracks straight from a Live set (.als) to full-length WAVs from bar 1, without opening Live:
clip gain, clip fades and straight-line warps (offset + tempo stretch) baked in; no faders or effects.

Use it to get clean stems for `hypnomix prep` / `automix`, or to re-render after replacing source files
(for example with de-hissed versions).

Usage:
    hypnomix render SET.als [--group "Vocals"] [--tracks "Lead" "Double"] [--out DIR]
                   [--sources DIR] [--tighten 35] [--sr 44100]

  --group     only the audio tracks inside this group (default: every audio track)
  --sources   folder of replacement files named like the originals (<original name>.wav), used when present
  --tighten   auto-fade each clip where it is this many dB below its own peak (silences the hiss before and
              after the performance inside each clip; 35 is a good start for vocals)

Warped clips are stretched WITHOUT changing pitch, like Live's warp modes (Rubber Band R3 when the
`rubberband` CLI is installed, `brew install rubberband`; otherwise a phase vocoder). Resampling instead
would detune them: a 3% tempo difference is 55 cents. Verified against Live 12 captures: 0 cents, +-0.05 LU.
Every clip edge gets Live's default ~3 ms fade so cuts don't click.

Clips are played like Live: from the start marker, and looped clips wrap from loop end to loop start
(missing this put whole phrases in the wrong place on sets that use looped vocal clips).

Render cache: each rendered clip is kept (hypnomix home/cache/render, capped at HYPNOMIX_RENDER_CACHE_MB, default
2048) keyed by its source file, its settings, the tempo and the sample rate, so rendering the same set again only
renders what changed, bit for bit the same. --no-cache (or HYPNOMIX_NO_CACHE=1) renders everything again.

Limits: warped clips are rendered from their first and last warp markers (a straight-line stretch); clips
with several warp markers that bend the timing will drift between markers. Unwarped clips are exact.
Output is 32-bit float, so nothing clips. Write re-renders to a NEW folder: Live caches audio by file
path and keeps playing the old audio if you overwrite a file it has loaded.
"""
import argparse, gzip, heapq, os, re, shutil, subprocess, sys, tempfile, threading, time
from hypnomix.core.gz import read_gz
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from hypnomix.core.paths import out_at


def v(n, p):
    e = n.find(p) if n is not None else None
    return e.get("Value") if e is not None else None


def clip_source(c, als, sources):
    fr = c.find("./SampleRef/FileRef")
    path = v(fr, "./Path") or ""
    rel = v(fr, "./RelativePath") or ""
    cand = Path(path) if path and Path(path).exists() else (Path(als).parent / rel)
    if sources:
        alt = Path(sources) / (Path(path or rel).stem + ".wav")
        if alt.exists():
            return alt
    return cand


# ---------------------------------------------------------------- render cache
# Each rendered clip is kept under <hypnomix home>/cache/render/, keyed by a hash of: the source file (path, mtime,
# size), the clip's XML (warp markers, loop, fades, gain: everything but where it sits on the timeline), its
# length, the tempo, the sample rate, --tighten and the stretcher in use. A changed clip or file is a new key, so
# a stale render is never reused. Size cap: HYPNOMIX_RENDER_CACHE_MB (default 2048), oldest-used removed first,
# kept with a running total (CacheIndex below): the folder is listed once, not again every few writes.
# Off with --no-cache or HYPNOMIX_NO_CACHE=1. Clips are kept as 32-bit float (what render writes; clips on one
# Arrangement track never overlap, so the written files are bit for bit the same with or without the cache).
CACHE_VERSION = 1
CACHE_STATS = {"hits": 0, "misses": 0, "writes": 0, "scans": 0}      # scans: full listings of the cache folder
_PUTS = [0]
_HAVE_RB = [bool(shutil.which("rubberband"))]       # the stretcher in use is part of every key
# A preview of timing nudges (`hypnomix ab`) turns this on: every warped clip is then stretched ALONG its markers by
# Rubber Band (a time map: each stretch between two markers plays at its own speed, the pitch stays), the same way
# for the clip before and after a nudge, instead of read at a varying speed (which moves the pitch where a stretch
# is large). Looped clips and files that cannot be mapped keep the plain read.
WARP_TIMEMAP = [False]


def cache_dir():
    d = os.environ.get("HYPNOMIX_RENDER_CACHE")
    if d:
        return Path(d).expanduser()
    from hypnomix.core.atomic import cache_root          # the same hypnomix home as every other cache (HYPNOMIX_HOME)
    return cache_root() / "render"


def cache_enabled(flag=None):
    if flag is not None:
        return bool(flag)
    return os.environ.get("HYPNOMIX_NO_CACHE", "") in ("", "0")


def cache_key(c, src, spb, SR, tighten, beats, ls, le, start_rel, loop_on):
    import copy, hashlib, tempfile
    try:
        st = Path(src).stat()
    except OSError:
        return None
    if not os.environ.get("HYPNOMIX_RENDER_CACHE") and \
            str(Path(src).resolve()).startswith(str(Path(tempfile.gettempdir()).resolve())):
        return None                      # throwaway files (tests, previews) are not worth keeping
    cc = copy.deepcopy(c)
    cc.tail = None
    cc.attrib.pop("Time", None)
    for tag in ("CurrentStart", "CurrentEnd"):
        el = cc.find(tag)
        if el is not None:
            cc.remove(el)
    h = hashlib.sha256(ET.tostring(cc))
    h.update(repr((CACHE_VERSION, str(Path(src).resolve()), st.st_mtime_ns, st.st_size, round(spb, 12), SR,
                   float(tighten or 0), round(beats, 9), ls, le, start_rel, loop_on, _HAVE_RB[0])
                  + (("timemap",) if WARP_TIMEMAP[0] else ())).encode())
    return h.hexdigest()


def cache_get(key):
    if not key:
        return None
    p = cache_dir() / key[:2] / f"{key}.npy"
    try:
        a = np.load(p, allow_pickle=False)
    except (OSError, ValueError):
        CACHE_STATS["misses"] += 1
        return None
    try:
        os.utime(p)                      # recently used: kept longest when the cache is trimmed
    except OSError:
        pass
    CACHE_STATS["hits"] += 1
    return a


def cache_put(key, seg):
    if not key:
        return
    d = cache_dir() / key[:2]
    try:
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".{key}.{os.getpid()}.tmp.npy"
        np.save(tmp, np.asarray(seg, dtype=np.float32), allow_pickle=False)
        final = d / f"{key}.npy"
        os.replace(tmp, final)
        CACHE_STATS["writes"] += 1
    except OSError:
        return
    _PUTS[0] += 1
    _after_put(final)


class CacheIndex:
    """What the render cache holds, kept in memory so a write does not list the whole folder again: path -> (mtime,
    size), a heap of (mtime, size, path) with the least recently used first, and the running total in bytes. ONE scan
    builds it (`scan`); after that each write adds to it (`add`) and `trim` removes the oldest entries while the total
    is over the cap, checking each one on disk first (a file used or replaced since is newer now and is put back;
    one another program already removed is just forgotten). The result is the same set of removals a full scan would
    pick."""

    def __init__(self, root):
        self.root, self.files, self.heap, self.total, self.seen = Path(root), {}, [], 0, time.monotonic()
        self.lock = threading.Lock()

    def scan(self):
        files = {}
        try:
            subs = [e.path for e in os.scandir(self.root) if e.is_dir(follow_symlinks=False)]
        except OSError:
            subs = []
        for sd in subs:
            try:
                with os.scandir(sd) as it:
                    for e in it:
                        if e.name.endswith(".npy"):
                            try:
                                st = e.stat()
                                files[e.path] = (st.st_mtime, st.st_size)
                            except OSError:
                                pass
            except OSError:
                pass
        self.files = files
        self.heap = [(mt, sz, p) for p, (mt, sz) in files.items()]
        heapq.heapify(self.heap)
        self.total = sum(sz for _, sz in files.values())
        self.seen = time.monotonic()
        CACHE_STATS["scans"] = CACHE_STATS.get("scans", 0) + 1

    def add(self, path, mtime, size):
        old = self.files.get(path)
        if old:
            self.total -= old[1]
        self.files[path] = (mtime, size)
        self.total += size
        heapq.heappush(self.heap, (mtime, size, path))

    def drop(self, path):
        old = self.files.pop(path, None)
        if old:
            self.total -= old[1]

    def trim(self, cap):
        removed = 0
        while self.total > cap and self.heap:
            mt, sz, p = heapq.heappop(self.heap)
            if self.files.get(p) != (mt, sz):
                continue                                    # an old heap entry: that file was added again or is gone
            try:
                st = os.stat(p)
            except OSError:
                self.drop(p)                                # another program removed it
                continue
            if st.st_mtime != mt or st.st_size != sz:
                self.add(p, st.st_mtime, st.st_size)        # used or replaced since we looked: newer, so it waits
                continue
            try:
                os.unlink(p)
                removed += sz
            except OSError:
                pass
            self.drop(p)
        return removed


_INDEX = [None]
_INDEX_LOCK = threading.Lock()
RESCAN_S = 600.0              # look at the whole folder again after this long, for what other programs wrote or removed


def _cap_bytes(cap_mb=None):
    return float(cap_mb if cap_mb is not None else os.environ.get("HYPNOMIX_RENDER_CACHE_MB", 2048)) * 1e6


def _after_put(final):
    """A clip was just written: keep the running total, and trim (oldest first) only when it is over the cap. The folder is
    listed once, at the first write and then at most every RESCAN_S seconds, never every few writes."""
    root = cache_dir()
    with _INDEX_LOCK:
        ix = _INDEX[0]
        if ix is None or ix.root != root or time.monotonic() - ix.seen > RESCAN_S:
            ix = _INDEX[0] = CacheIndex(root)
            ix.scan()                                       # lists the file just written too
        else:
            try:
                st = os.stat(final)
                ix.add(str(final), st.st_mtime, st.st_size)
            except OSError:
                pass
        ix.trim(_cap_bytes())


def cache_trim(cap_mb=None):
    """Remove the least recently used entries until the cache is under its cap (one full look at the folder). Returns
    bytes removed. Called once when a render command ends; writes use the running total instead (`_after_put`)."""
    root = cache_dir()
    if not root.exists():
        return 0
    with _INDEX_LOCK:
        ix = _INDEX[0] = CacheIndex(root)
        ix.scan()
        return ix.trim(_cap_bytes(cap_mb))


_STRETCH = {}


def stretched(src, k, SR):
    """Whole source file (mono) time-stretched by factor k (output = k x input length), pitch unchanged, at SR."""
    key = (str(src), round(k, 6), SR)
    if key in _STRETCH:
        return _STRETCH[key]
    from hypnomix.core import dsp
    a, sr = dsp.load(src)                  # falls back to ffmpeg for formats soundfile can't read (some .aif loops)
    a = a.mean(1)
    if abs(k - 1) >= 1e-5:
        if shutil.which("rubberband"):
            with tempfile.TemporaryDirectory(prefix="hypnomix-work-") as td:
                fi, fo = os.path.join(td, "i.wav"), os.path.join(td, "o.wav")
                sf.write(fi, a.astype(np.float32), sr, subtype="FLOAT")
                subprocess.run(["rubberband", "-3", "-q", "-t", f"{k:.8f}", fi, fo], check=True, capture_output=True)
                a = sf.read(fo, always_2d=True)[0].mean(1)
        else:
            import librosa
            a = librosa.effects.time_stretch(a.astype(np.float32), rate=1 / k)
    if sr != SR:
        ratio = Fraction(SR / sr).limit_denominator(2000)
        a = resample_poly(a, ratio.numerator, ratio.denominator)   # sample-rate change only: pitch-neutral
    _STRETCH[key] = a
    return a


def song_end(root):
    """(end in beats, [stray clips]) for the whole song: where the main-lane clips on playing tracks end. A clip
    or two running far past everything else (a stray loop, a forgotten take) is not the song: those are listed,
    and the song ends where the rest does."""
    ends = []
    for t in root.find(".//Tracks"):
        if t.tag not in ("AudioTrack", "MidiTrack") or v(t, "./DeviceChain/Mixer/Speaker/Manual") == "false":
            continue
        lane = t.find("./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events") if t.tag == "AudioTrack" else \
            t.find("./DeviceChain/MainSequencer/ClipTimeable/ArrangerAutomation/Events")
        for c in (list(lane) if lane is not None else []):
            if v(c, "./Disabled") != "true" and c.find("./CurrentEnd") is not None:
                ends.append((float(v(c, "./CurrentEnd")), v(t, "./Name/EffectiveName"), float(v(c, "./CurrentStart"))))
    if not ends:
        return 0.0, []
    e = np.array([x[0] for x in ends])
    p90 = float(np.percentile(e, 90))
    keep = e <= max(p90 * 1.25, p90 + 64)              # 16 bars of grace past where 9 in 10 clips end
    end = float(e[keep].max()) if keep.any() else float(e.max())
    strays = [f"{nm}: a clip from bar {cs / 4 + 1:.0f} to bar {ce / 4 + 1:.0f}" for (ce, nm, cs), k in zip(ends, keep) if not k]
    return end, strays


def _timemap_read(srcm, SR, sec, ms, mb, cb, spb, clip_len):
    """The clip's source stretched along its warp markers with Rubber Band's time map, pitch kept, or None when it
    cannot be done (a start before the file, a stretch too short to map): the caller then reads at varying speed.
    sec = source seconds at every output sample, ms / mb = the markers (source seconds, clip beats), cb = clip beats
    at every output sample."""
    if len(sec) < 4096 or sec[0] < 0 or sec[-1] * SR > len(srcm) + 2:
        return None
    a, b = int(np.floor(sec[0] * SR)), min(int(np.ceil(sec[-1] * SR)) + 1, len(srcm))
    keys = [(0, 0)]
    for s_, b_ in zip(ms, mb):
        if cb[0] < b_ < cb[-1]:
            keys.append((int(round(s_ * SR)) - a, int(round((b_ - cb[0]) * spb * SR))))
    keys.append((b - 1 - a, clip_len))
    ok = [keys[0]]
    for k in keys[1:]:                                   # both columns must rise, or Rubber Band refuses the map
        if k[0] > ok[-1][0] and k[1] > ok[-1][1]:
            ok.append(k)
    if len(ok) < 2 or b - a < 2048:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="hypnomix-work-") as td:
            fi, fo, fm = (os.path.join(td, n) for n in ("i.wav", "o.wav", "m.txt"))
            sf.write(fi, srcm[a:b].astype(np.float32), SR, subtype="FLOAT")
            Path(fm).write_text("".join(f"{x} {y}\n" for x, y in ok), encoding="utf-8")
            subprocess.run(["rubberband", "-3", "-q", "-M", fm, "-D", f"{clip_len / SR:.6f}", fi, fo],
                           check=True, capture_output=True)
            y = sf.read(fo, always_2d=True)[0].mean(1)
    except Exception:
        return None
    return np.pad(y, (0, max(0, clip_len - len(y))))[:clip_len]


def clip_audio(c, src, spb, SR, tighten, warn, s, e, ls, le, start_rel, loop_on):
    """One clip as Live plays it (start marker, loops, warp, clip gain, fades), length (e - s) beats, or None."""
    multi = None
    if v(c, "./IsWarped") == "true":
        m = sorted((float(w.get("SecTime")), float(w.get("BeatTime"))) for w in c.find("./WarpMarkers"))
        if len(m) > 2 or (WARP_TIMEMAP[0] and len(m) == 2 and not loop_on and _HAVE_RB[0]):
            multi = m                        # follow every marker (below), not one straight stretch
        (s0, b0), (s1, b1) = m[0], m[-1]
        slope = (s1 - s0) / (b1 - b0) if b1 != b0 else spb
        to_sec = lambda b, s0=s0, b0=b0, slope=slope: s0 + (b - b0) * slope   # clip beats -> source seconds
        per_beat = 1.0                                     # loop/start values are in beats
    else:
        slope = spb
        to_sec = lambda x: x
        per_beat = 1 / spb                                 # unwarped: loop/start values are in seconds
    k = spb / slope                          # how much longer the clip plays than it was recorded
    clip_len = int((e - s) * spb * SR)
    if multi is not None:
        # many warp markers (transient-warped drums, edited takes): every stretch between two markers keeps
        # its own timing. Read straight from the source along the marker map (varispeed per segment: timing
        # exact, pitch may waver a little where a segment is stretched a lot)
        try:
            from hypnomix.core import dsp
            srcy, _ = dsp.load(src, SR)
        except Exception as e_:
            if warn is not None:
                warn.append(f"could not read {Path(src).name} ({type(e_).__name__}): clip left out of the render")
            return None
        srcm = srcy.mean(1)
        ms, mb = np.array([x for x, _ in multi]), np.array([b for _, b in multi])
        eb = np.arange(clip_len) / (spb * SR)                     # beats since the clip started playing
        if loop_on and le > ls:
            cb = ls + ((start_rel + eb) % (le - ls))
        else:
            cb = ls + start_rel + eb
        lo_slope = (ms[1] - ms[0]) / max(1e-9, mb[1] - mb[0])
        hi_slope = (ms[-1] - ms[-2]) / max(1e-9, mb[-1] - mb[-2])
        sec = np.interp(cb, mb, ms)
        sec = np.where(cb < mb[0], ms[0] + (cb - mb[0]) * lo_slope, sec)       # Live extends the end segments
        sec = np.where(cb > mb[-1], ms[-1] + (cb - mb[-1]) * hi_slope, sec)
        seg = _timemap_read(srcm, SR, sec, ms, mb, cb, spb, clip_len) if (WARP_TIMEMAP[0] and not loop_on
                                                                        and _HAVE_RB[0]) else None
        if seg is None:
            seg = np.interp(sec * SR, np.arange(len(srcm)), srcm, left=0.0, right=0.0)
    else:
        try:
            a = stretched(src, k, SR)        # pitch-preserving stretch of the whole source
        except Exception as e_:              # a file nothing can decode: leave this clip out, say so
            if warn is not None:
                warn.append(f"could not read {Path(src).name} ({type(e_).__name__}): clip left out of the render")
            return None
    # play it like Live: start at the start marker; a looped clip wraps from loop end back to loop start
    need = (e - s) * per_beat if multi is None else 0.0
    pos = ls + start_rel
    parts = []
    while multi is None and need > 1e-9 and len(parts) < 10000:
        stop = le if (loop_on and le > pos) else pos + need
        take = min(need, stop - pos)
        i0, i1 = int(round(to_sec(pos) * k * SR)), int(round(to_sec(pos + take) * k * SR))
        piece = a[max(0, i0):max(0, i1)]
        if i0 < 0:
            piece = np.concatenate([np.zeros(min(-i0, i1 - i0)), piece])
        parts.append(piece)
        need -= take
        pos = ls if loop_on else pos + take
    if multi is None:
        seg = np.concatenate(parts) if parts else np.zeros(0)
    seg = np.pad(seg, (0, max(0, clip_len - len(seg))))[:clip_len]
    seg = seg * float(v(c, "./SampleVolume") or 1)
    fi = float(v(c, "./Fades/FadeInLength") or 0) * spb * SR       # Live stores clip fades in beats
    fo = float(v(c, "./Fades/FadeOutLength") or 0) * spb * SR
    seg = seg[: int((e - s) * spb * SR)].copy()
    if tighten and len(seg) > SR // 10:
        env = np.sqrt(np.maximum(np.convolve(seg ** 2, np.ones(441) / 441, "same"), 0))
        edb = 20 * np.log10(env + 1e-12)
        on = np.flatnonzero(edb > edb.max() - tighten)
        if len(on):
            a0, f0 = max(0, on[0] - int(0.06 * SR)), int(0.04 * SR)
            b0, f1 = min(len(seg), on[-1] + int(0.12 * SR)), int(0.15 * SR)
            m = np.zeros(len(seg))
            m[a0:b0] = 1
            r0 = slice(max(0, a0 - f0), a0); m[r0] = np.linspace(0, 1, r0.stop - r0.start)
            r1 = slice(b0, min(len(seg), b0 + f1)); m[r1] = np.linspace(1, 0, r1.stop - r1.start)
            seg = seg * m
    # Live's default ~3 ms edge fades, unless the clip's fade was set explicitly (an unrolled loop's seams: 0)
    if v(c, "./Fades/IsDefaultFadeIn") != "false" or fi > 0:
        fi = max(fi, 0.003 * SR)
    if v(c, "./Fades/IsDefaultFadeOut") != "false" or fo > 0:
        fo = max(fo, 0.003 * SR)
    kk = min(int(fi), len(seg)); seg[:kk] *= np.linspace(0, 1, kk)
    kk = min(int(fo), len(seg)); seg[len(seg) - kk:] *= np.linspace(1, 0, kk)
    return seg


def render_track(t, als, spb, N, SR, sources, tighten, warn, cache=None):
    y = np.zeros(N)
    name = v(t, "./Name/EffectiveName")
    for c in t.findall(".//ArrangerAutomation/Events/AudioClip"):
        if v(c, "./Disabled") == "true":
            continue
        s, e = float(v(c, "./CurrentStart")), float(v(c, "./CurrentEnd"))
        ls, le = float(v(c, "./Loop/LoopStart")), float(v(c, "./Loop/LoopEnd"))
        start_rel = float(v(c, "./Loop/StartRelative") or 0)       # start marker, relative to the loop start
        loop_on = v(c, "./Loop/LoopOn") == "true"
        src = clip_source(c, als, sources)
        if not src.exists():
            warn.append(f"{name}: missing file {src.name}")
            continue
        ck = cache_key(c, src, spb, SR, tighten, e - s, ls, le, start_rel, loop_on) if cache_enabled(cache) else None
        seg = cache_get(ck)
        if seg is None:
            seg = clip_audio(c, src, spb, SR, tighten, warn, s, e, ls, le, start_rel, loop_on)
            if seg is None:
                continue
            if ck:      # kept as 32-bit float, like the files render writes: a first and a cached run are identical
                seg = seg.astype(np.float32)
                cache_put(ck, seg)
        i = int(round(s * spb * SR))
        L = min(len(seg), N - i)
        if L > 0:
            y[i:i + L] += seg[:L]
    return y


def main():
    ap = argparse.ArgumentParser(prog="hypnomix render", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als"); ap.add_argument("--group"); ap.add_argument("--tracks", nargs="*")
    ap.add_argument("--out"); ap.add_argument("--sources"); ap.add_argument("--tighten", type=float, default=0)
    ap.add_argument("--sr", type=int, default=44100)
    ap.add_argument("--no-cache", action="store_true", help="render every clip again (no render cache)")
    a = ap.parse_args()
    r = ET.fromstring(read_gz(a.als))
    tempo = float(v(r, ".//Tempo/Manual"))
    spb = 60 / tempo
    tr = list(r.find(".//Tracks"))
    pick = [t for t in tr if t.tag == "AudioTrack"]
    if a.group:
        gids = [t.get("Id") for t in tr if t.tag == "GroupTrack" and v(t, "./Name/EffectiveName") == a.group]
        if not gids:
            sys.exit(f"no group {a.group!r}; groups: {[v(t, './Name/EffectiveName') for t in tr if t.tag == 'GroupTrack']}")
        pick = [t for t in pick if v(t, "./TrackGroupId") == gids[0]]
    if a.tracks:
        want = {x.lower() for x in a.tracks}
        pick = [t for t in pick if v(t, "./Name/EffectiveName").lower() in want]
    ends = [float(v(c, "./CurrentEnd")) for t in pick for c in t.iter("AudioClip")]
    if not ends:
        sys.exit("no audio clips on the chosen tracks")
    end, strays = song_end(r)
    if strays:
        print("WARNING: clips far past the end of the song are left out of the render (the song ends at bar "
              f"{end / 4 + 1:.0f}): " + "; ".join(strays[:6]), file=sys.stderr)
    N = int((min(max(ends), end if end > 0 else max(ends)) + 8) * spb * a.sr)
    od = out_at(a.out, "render", Path(a.als).stem)
    warn = []
    for t in pick:
        n = v(t, "./Name/EffectiveName")
        y = render_track(t, a.als, spb, N, a.sr, a.sources, a.tighten, warn, cache=False if a.no_cache else None)
        if not np.any(y):
            continue
        safe = re.sub(r'[\\/:*?"<>|]', "-", n)
        sf.write(str(od / f"{safe}.wav"), y.astype(np.float32), a.sr, subtype="FLOAT")
        print(f"{n:<30} peak {20 * np.log10(np.abs(y).max() + 1e-9):6.1f} dBFS")
    for w_ in sorted(set(warn)):
        print("  !", w_, file=sys.stderr)
    if cache_enabled(False if a.no_cache else None):
        cache_trim()
        print(f"render cache: {CACHE_STATS['hits']} clip(s) reused, {CACHE_STATS['writes']} rendered and kept "
              f"({cache_dir()})")
    print(f"→ {od}")


if __name__ == "__main__":
    main()
