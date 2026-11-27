"""`hypnomix vocallevel` on a REAPER project: measured from the project's own renders with faders, folder faders and
volume envelopes (fader-scaled ones as REAPER plays them), the same checks as a Live set; --apply writes smooth
S-curve points on volume envelopes into a NEW .rpp (existing points kept and scaled), never on a folder that holds
non-vocals, passes the structure check and measures better afterwards. Synthetic audio and projects only."""
import contextlib
import io
import json
import tempfile
import unittest
import uuid
from argparse import Namespace
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix import project
from hypnomix.project import rpp_edit as E
from hypnomix.session import vocallevel as VL
from hypnomix.workflow import vocallevel_project as VP

SR = 44100
GAPS = [(3.0, 3.5), (6.5, 7.0), (10.0, 10.5), (13.5, 14.0), (17.0, 17.5)]
LEN = 20.5


def tone(f, db, quiet_line=None):
    t = np.arange(int(LEN * SR)) / SR
    y = 10 ** (db / 20) * np.sqrt(2) * np.sin(2 * np.pi * f * t)
    if quiet_line:
        a, b, d = quiet_line
        y[int(a * SR):int(b * SR)] *= 10 ** (d / 20)
    for a, b in GAPS:
        y[int(a * SR):int(b * SR)] = 0
    return y.astype(np.float32)


def g():
    return "{" + str(uuid.uuid4()).upper() + "}"


def item(f):
    return (f"    <ITEM\n      POSITION 0\n      LENGTH {LEN}\n      LOOP 0\n      IGUID {g()}\n      VOLPAN 1 0 1 -1\n"
            f"      SOFFS 0\n      PLAYRATE 1 1 0 -1 0 0.0025\n      <SOURCE WAVE\n        FILE \"Audio/{f}\"\n      >\n    >")


def track(name, bus, vol=1.0, f=None, env=None):
    body = f"  <TRACK {g()}\n    NAME \"{name}\"\n    VOLPAN {vol} 0 -1 -1 1\n    ISBUS {bus}\n"
    if env:
        body += ("    <VOLENV2\n      EGUID " + g() + "\n      ACT 1 -1\n      VIS 1 1 1\n      ARM 0\n"
                 "      DEFSHAPE 0 -1 -1\n      VOLTYPE 1\n" + "".join(f"      PT {t} {v} 0\n" for t, v in env) + "    >\n")
    return body + (item(f) + "\n" if f else "") + "  >"


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)
        (self.dir / "Audio").mkdir()

    def tearDown(self):
        self._td.cleanup()

    def wav(self, name, y):
        sf.write(self.dir / "Audio" / name, y, SR, subtype="FLOAT")
        return name

    def song(self, harmony_db=-19.0, harmony_fader=1.0, strings=False, lead_env=None, quiet=(7.0, 10.0, -3.5)):
        """A folder "Vocals": Lead Vocal (220 Hz, one line 3.5 dB down) and Harmony (440 Hz, above the melody);
        optionally a Strings track inside the same folder."""
        lead = self.wav("lead.wav", tone(220, -20, quiet))
        harm = self.wav("harm.wav", tone(440, harmony_db))
        parts = ['<REAPER_PROJECT 0.1 "7.86/macOS-arm64" 1', "  TEMPO 120 4 4", "  SAMPLERATE 44100 0 0",
                 track("Vocals", "1 1"), track("Lead Vocal", "0 0", 1.0, lead, lead_env)]
        if strings:
            parts.append(track("Harmony", "0 0", harmony_fader, harm))
            parts.append(track("Strings", "2 -1", 1.0, self.wav("str.wav", tone(110, -30))))
        else:
            parts.append(track("Harmony", "2 -1", harmony_fader, harm))
        path = self.dir / "Song.rpp"
        path.write_text("\n".join(parts + [">", ""]), encoding="utf-8")
        return path

    def run_cli(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = VL.main([str(a) for a in args])
        return code, buf.getvalue()


def env_db(path, name):
    p = project.load(path)
    t = p.track(name)
    env = t.native.chunk("VOLENV2")
    if env is None:
        return None
    return [(tm, 20 * np.log10(max(v, 1e-9))) for tm, v, _ in E.points(env)]


class Measure(Base):
    def test_measured_from_the_project_with_its_fader(self):
        path = self.song()
        code, out = self.run_cli(path, "--json", self.dir / "v.json")
        self.assertEqual(code, 0)
        d = json.loads((self.dir / "v.json").read_text(encoding="utf-8"))
        self.assertEqual(d["daw"], "reaper")
        self.assertEqual(d["melody"], "Lead Vocal")
        self.assertEqual(d["order"], ["Lead Vocal", "Harmony"])
        kinds = [f["kind"] for f in d["findings"]]
        self.assertIn("upper-over-melody", kinds)
        self.assertIn("vocal-line-jump", kinds)
        j = next(f for f in d["findings"] if f["kind"] == "vocal-line-jump" and f["change_db"] > 0)
        self.assertAlmostEqual(j["t0"], 7.0, delta=0.1)
        # the same harmony with its fader 8 dB down sits under the melody: as heard, no upper finding
        path = self.song(harmony_fader=0.4)
        self.run_cli(path, "--json", self.dir / "v2.json")
        d2 = json.loads((self.dir / "v2.json").read_text(encoding="utf-8"))
        self.assertNotIn("upper-over-melody", [f["kind"] for f in d2["findings"]])

    def test_gain_curve_follows_folders_and_fader_scaled_envelopes(self):
        path = self.song(lead_env=[(0, 1.0), (10, 0.5)])
        p = project.load(path)
        p.track("Vocals").volume = 0.8
        lead = p.track("Lead Vocal")
        c = VP.gain_curve(lead, 12 * SR, SR)
        from hypnomix.project.model import envelope_at
        self.assertAlmostEqual(float(c[5 * SR]), 0.8 * float(envelope_at([(0, 1.0), (10, 0.5)], 5.0, fader=True)), 4)
        self.assertNotAlmostEqual(float(c[5 * SR]), 0.8 * 0.75, 2)      # not a straight line in amplitude
        self.assertAlmostEqual(float(c[11 * SR]), 0.4, 4)                # held after the last point

    def test_renders_folder_matches_the_project(self):
        path = self.song()
        p = project.load(path)
        rd = self.dir / "renders"
        rd.mkdir()
        for t in p.audio_tracks():
            sf.write(rd / f"{t.safe_name}.wav", p.render(t, SR).astype(np.float32), SR, subtype="FLOAT")
        self.run_cli(path, "--renders", rd, "--tracks", "Lead Vocal", "Harmony", "--json", self.dir / "r.json")
        self.run_cli(path, "--json", self.dir / "m.json")
        r = json.loads((self.dir / "r.json").read_text(encoding="utf-8"))
        m = json.loads((self.dir / "m.json").read_text(encoding="utf-8"))
        self.assertEqual([(f["kind"], f["where"]) for f in r["findings"]],
                         [(f["kind"], f["where"]) for f in m["findings"]])

    def test_a_live_set_still_needs_a_source(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            VL.main([str(self.dir / "Song.als")])


class Apply(Base):
    def test_apply_writes_smooth_envelopes_into_a_new_project(self):
        path = self.song()
        before = path.read_bytes()
        out = self.dir / "Song (vocal levels).rpp"
        code, text = self.run_cli(path, "--apply", out)
        self.assertEqual(code, 0, text)
        self.assertEqual(path.read_bytes(), before)                      # the original is never written
        self.assertIn("structure check OK", text)
        self.assertEqual(E.check(path, out), [])
        h = env_db(out, "Harmony")                                       # the upper part trimmed, at most 4 dB
        self.assertIsNotNone(h)
        self.assertLess(min(v for _, v in h), -2.5)
        self.assertGreaterEqual(min(v for _, v in h), -4.0 - 1e-6)
        self.assertLessEqual(max(v for _, v in h), 1e-6)
        grp = env_db(out, "Vocals")                                      # the line evening on the vocal-only folder
        self.assertIsNotNone(grp)
        self.assertGreater(max(v for _, v in grp), 1.5)
        self.assertLessEqual(max(abs(v) for _, v in grp), 3.0 + 1e-6)
        self.assertIsNone(env_db(out, "Lead Vocal"))                     # the melody itself is not touched
        for pts in (h, grp):                                             # S-curves: no step between points
            steps = [abs(b[1] - a[1]) / max(b[0] - a[0], 1e-9) for a, b in zip(pts, pts[1:])]
            self.assertLess(max(steps), 6.0)                             # dB/s; a 3 dB S-curve peaks near 3.9
        # measured again from the new project: the upper part sits under the melody, the line is even
        self.assertIn("measured again", text)
        sig, sr, _ = VP.signals(project.load(out), Namespace(renders=None, heard=None, tracks=None))
        _, f2, _ = VL.plan(sig, sr, "Lead Vocal", ["Lead Vocal", "Harmony"], keep_ending=2)
        for f in f2:                     # left over: rounding at the line edges, and the 4 dB cap on the quiet line
            if f["kind"] == "upper-over-melody":
                self.assertLessEqual(abs(f["change_db"]), 0.1 if abs(f["t0"] - 7.0) > 0.2 else 2.5)
        self.assertFalse([f for f in f2 if f["kind"] == "vocal-line-jump" and abs(f["t0"] - 7.0) < 0.2])

    def test_refuses_the_original(self):
        path = self.song()
        with self.assertRaises(SystemExit):
            self.run_cli(path, "--apply", path)

    def test_a_folder_holding_strings_is_never_automated(self):
        path = self.song(strings=True)
        out = self.dir / "new.rpp"
        code, text = self.run_cli(path, "--tracks", "Lead Vocal", "Harmony", "--apply", out)
        self.assertEqual(code, 0, text)
        self.assertIn("also holds Strings", text)
        self.assertIsNone(env_db(out, "Vocals"))
        self.assertIsNone(env_db(out, "Strings"))
        lead = env_db(out, "Lead Vocal")                                 # the evening went on each vocal track
        self.assertIsNotNone(lead)
        self.assertGreater(max(v for _, v in lead), 1.5)

    def test_existing_envelope_is_kept_and_offset(self):
        ride = [(0, 1.0), (1.5, 0.9), (5.0, 0.7), (18.5, 0.6)]
        path = self.song(lead_env=ride, harmony_db=-40)                 # only the line evening, on the folder
        p = project.load(path)
        lead = p.track("Lead Vocal")
        before = VP.gain_curve(lead, int(LEN * SR), SR)
        segs = [(7.0, 10.0, 2.0)]
        self.assertEqual(VP.write_gains(lead, segs), 1)
        out = self.dir / "new.rpp"
        E.save(p, out)
        q = project.load(out)
        after = VP.gain_curve(q.track("Lead Vocal"), int(LEN * SR), SR)
        pts = {round(t, 4): v for t, v in q.track("Lead Vocal").envelopes["Volume"]}
        for t, v in ride:                                                # every point still there, far ones as they were
            self.assertIn(float(t), pts)
        self.assertAlmostEqual(pts[0.0], 1.0, 6)
        self.assertAlmostEqual(pts[18.5], 0.6, 6)
        db = lambda t: 20 * np.log10(after[int(t * SR)] / before[int(t * SR)])
        self.assertAlmostEqual(db(8.5), 2.0, delta=0.05)                 # the line raised over the existing ride
        self.assertAlmostEqual(db(2.0), 0.0, delta=0.05)
        self.assertAlmostEqual(db(14.0), 0.0, delta=0.05)

    def test_switched_off_envelope_is_refused(self):
        path = self.song(lead_env=[(0, 1.0)])
        txt = path.read_text(encoding="utf-8").replace("ACT 1 -1", "ACT 0 -1")
        path.write_text(txt, encoding="utf-8")
        p = project.load(path)
        with self.assertRaises(ValueError):
            VP.write_gains(p.track("Lead Vocal"), [(7.0, 10.0, 2.0)])


if __name__ == "__main__":
    unittest.main()
