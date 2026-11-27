"""Fast pitch tracking for whole tracks, cached: librosa.yin (about 50x faster than pYIN) on the stretches
where something is actually sounding, never on silence.

    times, f0, level_db = pitch.track("Vocal.wav")      # f0 in Hz, NaN where nothing pitched is sounding

The result is cached in <HypnoMix home>/cache/pitch/ (~/.hypnomix unless HYPNOMIX_HOME says otherwise) by file
path, size, modification time and settings, so a scan and the fix after it (and any other tool) analyse each
file once. Use pYIN only where note-level accuracy
matters (vocal tuning); for "which part is higher / where is it singing" this is plenty.
"""
import hashlib
import threading
import os
from pathlib import Path

import numpy as np


def cache_dir():
    """The pitch cache folder: under the same HypnoMix home as everything else (HYPNOMIX_HOME)."""
    from hypnomix.core.atomic import cache_root
    return cache_root() / "pitch"


def _key(path, fmin, fmax, sr, hop, floor_db):
    st = os.stat(path)
    raw = f"{Path(path).resolve()}|{st.st_size}|{st.st_mtime_ns}|{fmin}|{fmax}|{sr}|{hop}|{floor_db}|v1"
    return hashlib.sha1(raw.encode()).hexdigest()


def active_segments(level_db, floor_db, hop_s, pad_s=0.05, merge_s=0.3):
    """[(i0, i1)] frame ranges within floor_db of the loudest frame, padded and with short gaps merged."""
    act = level_db > (level_db.max() - floor_db)
    idx = np.flatnonzero(act)
    if not len(idx):
        return []
    segs, s, prev = [], idx[0], idx[0]
    gap = int(merge_s / hop_s)
    for i in idx[1:]:
        if i - prev > gap:
            segs.append((s, prev + 1)); s = i
        prev = i
    segs.append((s, prev + 1))
    pad = int(pad_s / hop_s)
    return [(max(0, a - pad), min(len(level_db), b + pad)) for a, b in segs]


def track(path, fmin=65.0, fmax=1000.0, sr=22050, hop=256, floor_db=35.0, cache=True):
    """(times s, f0 Hz with NaN where unpitched or silent, level dB per frame) for a whole audio file."""
    import librosa
    import soundfile as sf
    k = _key(path, fmin, fmax, sr, hop, floor_db) if cache else None
    cdir = cache_dir()
    f = cdir / f"{k}.npz" if k else None
    if f is not None and f.exists():
        try:
            d = np.load(f)
            return d["t"], d["f0"], d["db"]
        except Exception:                 # unreadable (an old crash mid-write): measure again below
            pass
    y, fs = sf.read(str(path), always_2d=True, dtype="float32")
    m = y.mean(1)
    if fs != sr:
        m = librosa.resample(m, orig_sr=fs, target_sr=sr)
    n = 1 + len(m) // hop
    rms = librosa.feature.rms(y=m, frame_length=2048, hop_length=hop, center=True)[0][:n]
    db = 20 * np.log10(rms + 1e-9)
    f0 = np.full(len(db), np.nan)
    frame = 2048                                                  # long enough for 65 Hz at 22.05 kHz
    for a, b in active_segments(db, floor_db, hop / sr):
        seg = m[a * hop: b * hop + frame]
        if len(seg) < frame:
            continue
        est = librosa.yin(seg, fmin=fmin, fmax=fmax, sr=sr, frame_length=frame, hop_length=hop)
        est = est[: b - a]
        ok = (est > fmin * 1.03) & (est < fmax * 0.97)          # yin pins unpitched frames to the edges
        f0[a:a + len(est)] = np.where(ok, est, np.nan)
    f0[db < db.max() - floor_db] = np.nan
    t = np.arange(len(db)) * hop / sr
    if f is not None:                     # written whole, then renamed: parallel readers never see half a file
        cdir.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f"{k}.{os.getpid()}.{threading.get_ident()}.tmp.npz")
        np.savez_compressed(tmp, t=t, f0=f0, db=db)
        from hypnomix.core.atomic import replace as atomic_replace
        atomic_replace(tmp, f)
    return t, f0, db


def median_between(path, s0, s1, **kw):
    """Median pitch (Hz) of a file between two times in seconds, or None if too little is pitched there."""
    t, f0, _ = track(path, **kw)
    sel = f0[(t >= s0) & (t < s1)]
    sel = sel[np.isfinite(sel)]
    return float(np.median(sel)) if len(sel) >= 10 else None
