import unittest

import numpy as np

from hypnomix.session import turnaround_fx as T

SR, BPM = 44100, 120
STEP = SR * 60 / BPM / 4          # 5512.5 samples
BAR = int(round(STEP * 16))


def only(*names, **kw):
    w = {n: 0 for n in T.IDS}
    for n in names:
        w[n] = 1
    return dict(weights=w, chance=1.0, **kw)


def tone(n, ch=2):
    t = np.arange(n) / SR
    s = 0.5 * np.sin(2 * np.pi * 220 * t) + 0.2 * np.sin(2 * np.pi * 3100 * t)
    return np.stack([s] * ch, 1) if ch else s



def run_single(effect, x, p=0.1, L_steps=8, first=40, mix=1.0, keep_lows=False, **kw):
    """Force one segment of `effect` by rendering a hand-made pattern."""
    orig = T.pattern
    T.pattern = lambda *a, **k: [{"start": 0, "length": L_steps, "effect": T.IDS[effect], "name": effect, "p": p}]
    try:
        return T.render_window(x, SR, BPM, 0, first, L_steps, 0, 0.0, keep_lows=keep_lows, humanise_ms=0.0, mix=mix, **kw)
    finally:
        T.pattern = orig



class TurnaroundFx(unittest.TestCase):
    def test_rng_golden(self):
        # Park-Miller from s=1: the minimal-standard sequence
        r = T.ParkMiller(1)
        assert [r.rnd() * T._M for _ in range(4)] == [16807, 282475249, 1622650073, 984943658]
        assert T.seed_state(1, 0, 1) == 7920
        assert T.seed_state(42, 3, 2) == 437328          # epoch = 3 // 2 = 1
        assert T.seed_state(5, 9, 0) == T.seed_state(5, 0, 1)   # evolve 0: never
        r = T.ParkMiller(T.seed_state(1, 0, 1))
        got = [r.rnd() for _ in range(5)]
        want = [0.06198484453465084, 0.7792820938766385, 0.3941517846631593, 0.5090448337183543, 0.516520304380227]
        assert np.allclose(got, want, atol=1e-15, rtol=0)


    def test_pattern_golden_and_deterministic(self):
        a = T.pattern(1, 0, 8, 2, None, 0.75, 1)
        assert a == T.pattern(1, 0, 8, 2, None, 0.75, 1)
        assert [(s["start"], s["length"], s["name"]) for s in a] == [(0, 2, "gate"), (6, 2, "drop")]
        assert [(s["start"], s["length"], s["name"]) for s in T.pattern(1, 2, 8, 2, None, 0.75, 1)] == [(0, 8, "tapestop")]
        assert T.pattern(1, 0, 8, 2, None, 0.0, 1) == []


    def test_pattern_tiles_and_respects_weights(self):
        for seed in range(1, 40):
            for fi in range(6):
                for W in (4, 8, 16, 32):
                    segs = T.pattern(seed, fi, W, 3, {"repeat": 0, "roll": 0, "echo": 0, "crush": 5}, 1.0, 1)
                    end = 0
                    for s in segs:
                        assert s["start"] >= end and s["length"] >= 1 and s["start"] + s["length"] <= W
                        assert s["effect"] not in (1, 2, 10)
                        end = s["start"] + s["length"]
                    assert segs and end == W          # the last segment ends exactly at the window end
                    assert all(a["effect"] != b["effect"] for a, b in zip(segs, segs[1:]))


    def test_fill_windows_grow(self):
        w = T.fill_windows(16, 4, 8, True, 4)
        assert [(f, W, b) for f, _, W, b in w] == [(0, 8, 0), (1, 16, 1), (2, 8, 0), (3, 32, 2)]
        assert [first + W for _, first, W, _ in w] == [4 * 16, 8 * 16, 12 * 16, 16 * 16]
        assert all(W == 8 for _, _, W, _ in T.fill_windows(16, 4, 8, False, 4))
        assert T.fill_windows(16, 4, 32, True, 4)[3][2] == 32      # capped


    def test_length_and_chance_zero_exact(self):
        x = tone(SR * 40)
        y = T.render(x, SR, BPM, 0.0, chance=0.0)
        assert y.shape == x.shape and np.array_equal(y, x)
        y = T.render(x[:, 0], SR, BPM, 0.0, seed=2, level=3)
        assert y.shape == (len(x),)
        odd = tone(SR * 40 + 1234)
        assert len(T.render(odd, SR, BPM, 0.0, seed=2, level=3)) == len(odd)


    def test_untouched_outside_windows_and_downbeats(self):
        x = np.random.RandomState(1).randn(SR * 70, 2) * 0.1
        kw = dict(seed=3, level=3, chance=1.0, weights={"echo": 0})
        y = T.render(x, SR, BPM, 0.0, **kw)
        mask = np.zeros(len(x), bool)
        for fi, first, W, _ in T.fill_windows(len(x) // BAR, 4, 8, True, 4):
            a = int(round(first * STEP)); b = int(round((first + W) * STEP))
            mask[a:b] = True
            assert np.array_equal(y[b:b + 50], x[b:b + 50])        # the next downbeat is untouched
        assert not np.array_equal(y[mask], x[mask])
        assert np.array_equal(y[~mask], x[~mask])


    def test_echo_tail_rings_after_window_only_added(self):
        x = np.zeros((SR * 20, 2)); x[:, :] = tone(SR * 20)
        y = T.render(x, SR, BPM, 0.0, **only("echo", seed=1))
        b = int(round(64 * STEP))
        assert np.abs(y[b + 100:b + int(3 * STEP)] - x[b + 100:b + int(3 * STEP)]).max() > 1e-3


    def test_reverse_relationship(self):
        x = np.random.RandomState(2).randn(SR * 12, 1)
        y = run_single("reverse", x)
        a = int(round(40 * STEP)); L = int(round(48 * STEP)) - a
        mid = np.arange(int(0.01 * SR), L - int(0.01 * SR))
        assert np.allclose(y[a + mid, 0], x[a - BAR + (L - mid), 0])


    def test_rearrange_relationship(self):
        x = np.random.RandomState(3).randn(SR * 12, 1)
        a = int(round(40 * STEP)); L = int(round(48 * STEP)) - a
        mid = np.arange(int(0.01 * SR), L - int(0.01 * SR))
        for p, off in ((0.1, -4), (0.5, -8), (0.9, 4)):
            y = run_single("rearrange", x, p=p)
            assert np.allclose(y[a + mid, 0], x[a - BAR + int(round(off * STEP)) + mid, 0])


    def test_repeat_relationship_on_ramp(self):
        x = (np.arange(SR * 12) / (SR * 12.0))[:, None]
        y = run_single("repeat", x, p=0.1)           # 1/8 note = 2 steps
        a = int(round(40 * STEP)); S = int(round(2 * STEP))
        # inside the second slice (clear of the 2 ms restart fades) the output replays the segment start, x0.92
        k = np.arange(int(0.01 * SR), S - int(0.01 * SR))
        assert np.allclose(y[a + S + k, 0], x[a + k, 0] * 0.92, atol=1e-9)
        assert np.allclose(y[a + 2 * S + k, 0], x[a + k, 0] * 0.92 ** 2, atol=1e-9)
        # the first slice is the input itself (apart from the 3 ms fade-in)
        assert np.allclose(y[a + 300:a + S - 300, 0], x[a + 300:a + S - 300, 0])


    def test_tapestop_halftime_drop(self):
        x = (np.arange(SR * 12) / (SR * 12.0))[:, None]
        a = int(round(40 * STEP))
        y = run_single("halftime", x)
        t = np.arange(2000, 5000)
        assert np.allclose(y[a + t, 0], x[a, 0] + 0.5 * t / (SR * 12.0), atol=1e-9)
        y = run_single("tapestop", x)
        assert y[a + 20000, 0] < x[a + 20000, 0]
        y = run_single("drop", x, p=0.9)
        assert np.abs(y[a + 3000:a + 40000]).max() == 0.0


    def test_mix_zero_is_dry(self):
        x = tone(SR * 12)
        assert np.array_equal(run_single("reverse", x, mix=0.0), x)


    def test_no_clicks_on_sine(self):
        n = SR * 70
        t = np.arange(n) / SR
        x = (0.5 * np.sin(2 * np.pi * 100 * t))[:, None]
        base = np.abs(np.diff(x[:, 0])).max()
        for name in ("repeat", "roll", "reverse", "tapestop", "halftime", "drop", "filter", "gate", "rearrange", "echo"):
            y = T.render(x, SR, BPM, 0.0, keep_lows=False, level=3, seed=4, **only(name))
            jump = np.abs(np.diff(y[:, 0])).max()
            assert jump < 0.3 + base, (name, jump)       # no step discontinuities (a full-scale jump would be ~1)
            assert not np.array_equal(y, x), name


    def test_keep_lows_drop_mutes_only_highs(self):
        x = tone(SR * 12)
        y = run_single("drop", x, p=0.9, keep_lows=True)
        lo = T._lowpass_150(x, SR)
        a = int(round(40 * STEP)); b = int(round(48 * STEP))
        assert np.abs(y[a + 2000:b - 2000] - lo[a + 2000:b - 2000]).max() < 1e-9
        assert np.array_equal(y[:a], x[:a]) and np.array_equal(y[b:], x[b:])
        # lows + highs are an exact split: with the effect at mix 0 nothing changes
        assert np.array_equal(run_single("drop", x, p=0.9, keep_lows=True, mix=0.0), x)


if __name__ == "__main__":
    unittest.main()
