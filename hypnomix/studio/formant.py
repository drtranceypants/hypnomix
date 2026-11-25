"""Formant and transpose for `hypnomix vocalign --formant / --transpose`: widen a stack, or move a part.

  transpose  semitones up or down, formants kept (the voice still sounds like the singer)
  formant    semitones of formant shift with the pitch unchanged: + sounds smaller/brighter, - bigger/darker.
             Small amounts (0.2-0.8) on a double make it sound like a different singer, so the stack gets wider
             without more takes. Done in two Rubber Band R3 passes: shift pitch and formants together, then shift
             the pitch back with formants kept.

Both can be limited to time ranges (--formant-at 62-70,90-101): outside them the audio stays sample for sample
(10 ms crossfades). The output is lined up with the input sample for sample.
"""
import subprocess, tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix.studio import tune as T


def _rb(x, sr, semis, keep_formant):
    with tempfile.TemporaryDirectory() as td:
        fi, fo = Path(td) / "i.wav", Path(td) / "o.wav"
        sf.write(str(fi), x, sr, subtype="FLOAT")
        cmd = ["rubberband", "-3", "-q", "-p", f"{semis:.5f}"] + (["-F"] if keep_formant else []) + [str(fi), str(fo)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-300:])
        y, _ = sf.read(str(fo), dtype="float32", always_2d=True)
    return y


def shift(y, sr, formant=0.0, transpose=0.0, ranges=None):
    """y: (n, ch) float. Returns the shifted audio, same length, sample-aligned with y."""
    if abs(formant) < 1e-4 and abs(transpose) < 1e-4:
        return y
    orig = y
    y = np.asarray(y, np.float32)
    peak = float(np.abs(y).max()) or 1.0
    s = 0.9 / peak
    x = y * s
    if abs(formant) >= 1e-4:
        x = _rb(x, sr, formant, keep_formant=False)       # pitch and formants up by `formant`
        x = _rb(x, sr, transpose - formant, keep_formant=True)   # pitch to `transpose`, formants stay shifted
    else:
        x = _rb(x, sr, transpose, keep_formant=True)
    x = x / s
    lag = T.lag_env(y.mean(1), x.mean(1), sr)          # the loudness shape doesn't change with pitch: safe to line up on
    n = len(y)
    idx = np.arange(n) + int(lag)
    ok = (idx >= 0) & (idx < len(x))
    out = np.zeros_like(y)
    out[ok] = x[idx[ok], :y.shape[1]] if x.shape[1] >= y.shape[1] else np.repeat(x[idx[ok]], y.shape[1], 1)
    if not ranges:
        return out.astype(np.asarray(orig).dtype)
    res = np.array(orig, copy=True)                       # outside the ranges: the input, bit for bit
    for a, b in ranges:
        T.crossfade_in(res, out, max(0, int(a * sr)), min(n, int(b * sr)), sr)
    return res
