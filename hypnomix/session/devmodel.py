"""hypnomix's own models of two of Live's stock devices, for offline previews (`hypnomix ab`, `plugrender`): EQ Eight
and Gate. They sit beside the models of Compressor, Glue Compressor, Utility and Limiter in `plugrender.run_stock`.

They are MODELS, not Live: the filter shapes are the standard ones (RBJ bell and shelves, Butterworth cuts), so the
curve lands where the settings say, but Live's own filters differ in small ways near the band edges and Gate's
detector is a simple peak follower. Good for hearing what a settings change does, not for judging the final sound.
What is not modelled is said so, and the device is then left out of the render instead of guessed:
  EQ Eight   L/R and M/S modes (only plain stereo is modelled), a band with a changing gain curve (an envelope on it
             plays as the saved value)
  Gate       flipped mode, sidechain on, the look-ahead choice
"""
import numpy as np
from scipy.signal import butter, lfilter, sosfilt


NO_MODEL = "no model:"


def _man(d, name, default=None):
    e = d.find(f"./{name}/Manual")
    if e is None or e.get("Value") is None:
        return default
    v = e.get("Value")
    if v in ("true", "false"):
        return v == "true"
    try:
        return float(v)
    except ValueError:
        return default


# ---------------------------------------------------------------- EQ Eight
def _biquad(mode, sr, f, gain_db, q):
    """(b, a) for a bell (3), shelves (2, 5) or notch (4); RBJ's cookbook."""
    f = float(np.clip(f, 10.0, 0.49 * sr))
    w0 = 2 * np.pi * f / sr
    cw, sw = np.cos(w0), np.sin(w0)
    q = max(float(q), 0.1)
    A = 10 ** (gain_db / 40)
    al = sw / (2 * q)
    if mode == 3:
        b = [1 + al * A, -2 * cw, 1 - al * A]
        a = [1 + al / A, -2 * cw, 1 - al / A]
    elif mode == 4:
        b = [1, -2 * cw, 1]
        a = [1 + al, -2 * cw, 1 - al]
    else:
        t = 2 * np.sqrt(A) * al
        if mode == 2:
            b = [A * ((A + 1) - (A - 1) * cw + t), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - t)]
            a = [(A + 1) + (A - 1) * cw + t, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - t]
        else:
            b = [A * ((A + 1) + (A - 1) * cw + t), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - t)]
            a = [(A + 1) - (A - 1) * cw + t, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - t]
    return np.array(b) / a[0], np.array(a) / a[0]


def eq8_bands(d):
    """[(on, mode, freq, gain dB, q)] of band A of every one of the 8 bands, gains already scaled by the device's
    own Scale and shifted by nothing else (the global gain is applied after)."""
    scale = _man(d, "Scale", 1.0) or 1.0
    out = []
    for i in range(8):
        b = d.find(f"./Bands.{i}/ParameterA")
        if b is None:
            continue
        out.append((bool(_man(b, "IsOn", False)), int(_man(b, "Mode", 3)), float(_man(b, "Freq", 1000.0)),
                    float(_man(b, "Gain", 0.0)) * scale, float(_man(b, "Q", 0.71))))
    return out


def eq8(y, sr, d):
    """EQ Eight on y (n, 2). Returns (y, note or None); a note starting 'no model:' means nothing was done."""
    mode = d.find("./Mode")
    if mode is not None and int(float(mode.get("Value", "0"))) != 0:
        return y, f"{NO_MODEL} EQ Eight is in L/R or M/S mode (only plain stereo is modelled)"
    out = np.array(y, dtype=float, copy=True)
    for on, m, f, g, q in eq8_bands(d):
        if not on:
            continue
        if m in (0, 1, 6, 7):
            order = 8 if m in (0, 7) else 2
            kind = "high" if m in (0, 1) else "low"
            f_ = float(np.clip(f, 10.0, 0.49 * sr))
            sos = butter(order, f_, btype=kind, fs=sr, output="sos")
            out = sosfilt(sos, out, axis=0)
        elif abs(g) > 1e-3 or m == 4:
            b, a = _biquad(m, sr, f, g, q)
            out = lfilter(b, a, out, axis=0)
    gg = _man(d, "GlobalGain", 0.0) or 0.0
    return out * 10 ** (gg / 20), None


# ---------------------------------------------------------------- Gate
def gate(y, sr, d):
    """Gate on y (n, 2): a peak follower with a threshold, a return (hysteresis) and hold, then attack / release
    smoothing down to the floor. Returns (y, note or None)."""
    if _man(d, "FlipMode", False):
        return y, f"{NO_MODEL} Gate is in flip mode"
    sc = d.find("./SideChain/OnOff/Manual")
    if sc is not None and sc.get("Value") == "true":
        return y, f"{NO_MODEL} Gate listens to a sidechain"
    thr = 20 * np.log10(max(_man(d, "Threshold", 0.001), 1e-9))
    ret = max(_man(d, "Return", 0.0), 0.0)
    atk, hold, rel = (max(_man(d, k, v), 0.1) for k, v in (("Attack", 1.0), ("Hold", 10.0), ("Release", 50.0)))
    floor = 10 ** (min(_man(d, "Gain", -40.0), 0.0) / 20)
    hop = max(1, int(sr * 0.001))                               # 1 ms steps
    n = len(y) // hop
    if n < 2:
        return y, None
    e = np.abs(y[: n * hop]).max(axis=1).reshape(n, hop).max(axis=1)
    e_db = 20 * np.log10(e + 1e-9)
    open_, held, state = False, 0, np.empty(n)
    hold_n = int(hold)
    for i in range(n):
        if e_db[i] > thr:
            open_, held = True, hold_n
        elif open_ and e_db[i] < thr - ret:
            if held > 0:
                held -= 1
            else:
                open_ = False
        elif open_:
            held = hold_n
        state[i] = 1.0 if open_ else 0.0
    up, dn = 1 - np.exp(-1.0 / atk), 1 - np.exp(-1.0 / rel)
    g = np.empty(n)
    cur = floor + (1 - floor) * state[0]
    for i in range(n):
        t = floor + (1 - floor) * state[i]
        cur += (up if t > cur else dn) * (t - cur)
        g[i] = cur
    gain = np.interp(np.arange(len(y)), np.arange(n) * hop + hop / 2, g)
    return y * gain[:, None], "its look-ahead is not modelled"
