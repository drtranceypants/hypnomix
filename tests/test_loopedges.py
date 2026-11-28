import numpy as np
import tempfile, unittest
from pathlib import Path

from hypnomix.session import loopedges as L

SR = 44100


def burst(n_total, at, freq=200.0, dur=0.12, amp=0.8, seed=0):
    """A decaying tone+noise hit starting at sample `at`."""
    y = np.zeros(n_total)
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    env = np.exp(-t * 40)
    y[at:at + n] += amp * env * (np.sin(2 * np.pi * freq * t + 0.7) * 0.6 + rng.standard_normal(n) * 0.2)
    return y


def sec(x):
    return int(round(x * SR))


def approx(v):
    class A:
        def __eq__(self, o): return abs(o - v) < 1e-6
    return A()


class LoopEdges(unittest.TestCase):
    def test_start_and_end_follow_attacks(self):
        start_s, end_s = 1.0, 3.0
        y = np.zeros(sec(5))
        y += burst(len(y), sec(start_s) + sec(0.012))      # late downbeat (+12 ms)
        y += burst(len(y), sec(1.9), freq=500)             # interior hit
        y += burst(len(y), sec(end_s) - sec(0.006), freq=300, seed=2)   # next downbeat 6 ms early
        r = L.align_audio(y, SR, start_s, end_s)
        assert r["flags"] == []
        assert abs(r["new_start"] - 1.012) < 0.001
        assert r["new_start"] <= 1.012 + 1e-9
        # end is before the early attack by the guard
        assert r["new_end"] < end_s - 0.006
        assert (end_s - 0.006) - r["new_end"] <= 0.0025
        assert (end_s - 0.006) - r["new_end"] >= 0.001 - 1e-4
        assert r["length_diff_ms"] < 0 and abs(r["length_diff_ms"]) < 25


    def test_zero_crossing_snap(self):
        y = np.zeros(sec(4))
        y += burst(len(y), sec(1.0))
        y += burst(len(y), sec(3.0))
        r = L.align_audio(y, SR, 1.0, 3.0)
        i = r["start_sample"]
        assert y[i] == 0 or (y[i] <= 0) != (y[i + 1] <= 0) or abs(y[i]) < 1e-3
        j = r["end_sample"]
        assert j <= sec(3.0) - sec(0.001) + 1
        assert abs(y[j]) < 1e-3 or (y[j - 1] <= 0) != (y[j] <= 0) or (y[j] <= 0) != (y[j + 1] <= 0)


    def test_no_transient_pad_keeps_bar_lines(self):
        t = np.arange(sec(4)) / SR
        y = 0.2 * np.sin(2 * np.pi * 220 * t)
        r = L.align_audio(y, SR, 1.0, 3.0)
        assert "no_transient" in r["flags"]
        assert abs(r["new_start"] - 1.0) < 0.002
        assert abs(r["new_end"] - 3.0) < 0.002
        assert 3.0 - r["new_end"] >= 0


    def test_length_off_flag(self):
        y = np.zeros(sec(4))
        y += burst(len(y), sec(1.0) + sec(0.040) - 5)
        y += burst(len(y), sec(3.0) - sec(0.035))
        r = L.align_audio(y, SR, 1.0, 3.0)
        assert "length_off" in r["flags"]


    def test_tail_rings_flag(self):
        y = np.zeros(sec(4))
        y += burst(len(y), sec(1.0), dur=0.05, amp=0.05)
        y += burst(len(y), sec(1.5), dur=0.05, amp=0.05, seed=3)
        y += burst(len(y), sec(2.8), dur=0.2, amp=0.9, seed=4) * np.exp(-np.arange(len(y)) * 0)  # loud, rings to the end
        y[sec(2.8):sec(3.0) + sec(0.2)] += 0.5 * np.sin(2 * np.pi * 150 * np.arange(sec(0.4)) / SR)[:sec(0.2) + sec(0.2)]
        y += burst(len(y), sec(3.0), seed=5)
        r = L.align_audio(y, SR, 1.0, 3.0)
        assert r["tail_rings"] and "tail_rings" in r["flags"]


    def test_cut_has_fade_out_and_sharp_start(self):
        y = np.zeros(sec(4))
        y += burst(len(y), sec(1.0))
        y += burst(len(y), sec(2.0), amp=0.8)
        y[sec(2.5):sec(3.0)] += 0.3 * np.sin(2 * np.pi * 100 * np.arange(sec(0.5)) / SR)
        r = L.align_audio(y, SR, 1.0, 3.0, fade_ms=4)
        seg = L.cut_audio(y, SR, r["new_start"], r["new_end"], 4)
        assert abs(seg[-1]) < 1e-3
        assert seg.shape[0] == r["end_sample"] - r["start_sample"]


    def test_group_shared_bounds_and_offsets(self):
        n = sec(4)
        drums = burst(n, sec(1.0)) + burst(n, sec(3.0))
        bass = burst(n, sec(1.0) + sec(0.007), freq=60, amp=0.3) + burst(n, sec(3.0) + sec(0.007), freq=60, amp=0.3)
        pad = 0.1 * np.sin(2 * np.pi * 200 * np.arange(n) / SR)
        r = L.align_group({"bass": (bass, SR), "drums": (drums, SR), "pad": (pad, SR)}, 1.0, 3.0)
        assert r["ref"] == "drums"
        assert r["stems"]["drums"]["offset_ms"] == 0
        assert abs(r["stems"]["bass"]["offset_ms"] - 7.0) < 1.0
        assert r["stems"]["pad"]["offset_ms"] is None and "no_transient" in r["stems"]["pad"]["flags"]
        assert r["stems"]["bass"]["new_start"] == r["stems"]["drums"]["new_start"] == r["new_start"]
        r2 = L.align_group({"bass": (bass, SR), "drums": (drums, SR)}, 1.0, 3.0, each=True)
        assert abs(r2["stems"]["bass"]["new_start"] - 1.007) < 0.001
        assert abs(r2["stems"]["drums"]["new_start"] - 1.0) < 0.001
        r3 = L.align_group({"bass": (bass, SR), "drums": (drums, SR)}, 1.0, 3.0, ref="bass")
        assert r3["ref"] == "bass" and abs(r3["new_start"] - 1.007) < 0.001


    def test_midi_nudge_remove_wrap_shorten(self):
        notes = [
            (36, 4.01, 0.5, 100),     # near start (late by 0.01 < 1/32): nudged to 4.0
            (40, 4.0, 0.5, 90),       # exactly on start
            (50, 5.0, 0.5, 80),       # interior: untouched
            (36, 7.99, 0.25, 100),    # early next downbeat, start has 36 -> removed
            (45, 7.98, 0.5, 70),      # early, no 45 at start -> wrapped to start
            (60, 7.0, 3.0, 64),       # rings past end 8.0 -> shortened
            (70, 8.0, 0.5, 64),       # belongs to next loop: dropped
            (71, 2.0, 0.5, 64),       # before loop: dropped
        ]
        r = L.align_midi(notes, 4.0, 8.0)
        assert (r["nudged"], r["removed"], r["wrapped"], r["shortened"]) == (1, 1, 1, 1)
        got = {(p, round(s, 6)): (round(d, 6), v) for p, s, d, v in r["notes"]}
        assert (36, 0.0) in got and got[(36, 0.0)][0] == approx(0.51)
        assert (40, 0.0) in got and (45, 0.0) in got and (50, 1.0) in got
        assert (60, 3.0) in got and got[(60, 3.0)][0] == approx(1.0 - 1 / 128)
        assert not any(p in (70, 71) for p, _, _, _ in r["notes"])
        assert sum(1 for p, s, _, _ in r["notes"] if p == 36) == 1
        assert r["notes"] == sorted(r["notes"], key=lambda n: (n[1], n[0]))


    def test_midi_interior_notes_never_move(self):
        notes = [(60, 5.003, 0.5, 90), (62, 6.5, 0.2, 90)]
        r = L.align_midi(notes, 4.0, 8.0)
        assert r["nudged"] == 0
        assert [(p, round(s, 6)) for p, s, _, _ in r["notes"]] == [(60, 1.003), (62, 2.5)]


    def test_midi_file_roundtrip_and_cli(self):
        tmp_path = Path(tempfile.mkdtemp())
        src = tmp_path / "a.mid"
        L.write_midi(src, [(36, 0.01, 0.5, 100), (38, 1.0, 0.5, 90), (36, 3.99, 0.25, 100)], 480, 500000)
        notes, ppq, tempo = L.read_midi(src)
        assert ppq == 480 and tempo == 500000 and len(notes) == 3
        out = tmp_path / "cut.mid"
        assert L.main([str(src), "--bar", "1", "--bars", "1", "--out", str(out)]) == 0
        cut, _, _ = L.read_midi(out)
        assert [(p, round(s, 3)) for p, s, _, _ in cut] == [(36, 0.0), (38, 1.0)]


    def test_audio_cli_writes_cut(self):
        import soundfile as sf
        y = np.zeros(sec(6))
        y += burst(len(y), sec(0.5) + sec(0.01))
        y += burst(len(y), sec(2.5) - sec(0.005))
        tmp_path = Path(tempfile.mkdtemp())
        f = tmp_path / "a.wav"
        sf.write(str(f), y, SR)
        out = tmp_path / "cut.wav"
        assert L.main([str(f), "--bpm", "120", "--downbeat", "0.5", "--bar", "1", "--bars", "1", "--out", str(out)]) == 0
        cut, sr = sf.read(str(out))
        assert sr == SR and abs(len(cut) / SR - 1.985) < 0.005


if __name__ == '__main__':
    unittest.main()
