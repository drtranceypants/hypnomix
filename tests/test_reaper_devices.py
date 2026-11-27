"""The `devices` and `structure` groups of a REAPER project scan, and the `names` group through `fix`.

devices: a ReaComp is read from the .rpp (the chunk REAPER 7.86 saved, its floats changed through the same writer
`fix` uses), judged on its track's own audio and its suggestion written by `fix` into a new .rpp; a ReaEQ with no
high-pass band on a part that rumbles gets a low-cut suggestion; ReaGate is listed, not judged. structure: the
file's own structure and the faders. Everything is synthetic, in temporary folders; nothing here opens REAPER.

Run from the repo root:  python -m unittest tests.test_reaper_devices
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from hypnomix import project as PJ
from hypnomix.project import rpp_edit as E
from hypnomix.workflow import devices_project as DP
from hypnomix.workflow import scan_project as SP
from hypnomix.workflow import sidechain_project as SCP
from tests.test_masking_write import REAEQ_LINES
from tests.test_scan_parity import scan as run_scan

SR = 44100
# the ReaComp REAPER 7.86 saved (tests/test_rpp.py): header, state, tail
COMP_HDR = "bWNlcu9e7f4EAAAAAQAAAAAAAAACAAAAAAAAAAQAAAAAAAAACAAAAAAAAAACAAAAAQAAAAAAAAACAAAAAAAAAFwAAAAAAAAAAAAQAA=="
COMP_STATE = ("776t3g3wrd7NzEw9zczMPW8SAzvNzEw+AAAAAAAAAAAAAIA/AAAAAIzU8ToAAAAAnNEHMwAAgD8AAAAAzcxMPQAAAAAAAAAAAAAAAAAAgD4"
              "AAAAAAAAAAAAAAAA=")


def reacomp(name=""):
    return ('      BYPASS 0 0 0\n'
            f'      <VST "VST: ReaComp (Cockos)" reacomp.vst.dylib 0 "{name}" 1919247213<5653547265636D726561636F6D700000> ""\n'
            f'        {COMP_HDR}\n        {COMP_STATE}\n        AAAQAAAA\n      >\n'
            '      FXID {22222222-2222-2222-2222-222222222222}\n')


def reaeq():
    return ('      BYPASS 0 0 0\n'
            '      <VST "VST: ReaEQ (Cockos)" reaeq.vst.dylib 0 "" 1919247729<56535472656571726561657100000000> ""\n'
            + "".join(f"        {l}\n" for l in REAEQ_LINES) + '      >\n      FXID {11111111-1111-1111-1111-111111111111}\n')


def reagate():
    """A stand-in ReaGate chunk: only its name is read (its state's layout is not)."""
    return ('      BYPASS 0 0 0\n'
            '      <VST "VST: ReaGate (Cockos)" reagate.vst.dylib 0 "" 1919248244<56535472656774726561676174650000> ""\n'
            '        Z2VyduVe7f4CAAAAAQAAAAAAAAACAAAAAAAAAAIAAAABAAAAAAAAAAIAAAAAAAAACAAAAAAAAAAAABAA\n'
            '        776t3g3wrd4=\n        AAAQAAAA\n      >\n      FXID {33333333-3333-3333-3333-333333333333}\n')


def jsfx():
    return '      BYPASS 0 0 0\n      <JS "loser/Saturation" ""\n        0 1\n      >\n      FXID {44444444-4444-4444-4444-444444444444}\n'


def chain(*fx):
    return "    <FXCHAIN\n      SHOW 0\n      LASTSEL 0\n      DOCKED 0\n" + "".join(fx) + "    >\n"


def item(f, length=8.0):
    return (f'    <ITEM\n      POSITION 0\n      LENGTH {length}\n      LOOP 0\n      FADEIN 1 0.01 0 1 0 0 0\n'
            f'      FADEOUT 1 0.01 0 1 0 0 0\n      MUTE 0 0\n      IGUID {{BBBBBBBB-0000-0000-0000-{abs(hash(f)) % 10**12:012d}}}\n'
            f'      NAME "take"\n      VOLPAN 1 0 1 -1\n      SOFFS 0\n      PLAYRATE 1 1 0 -1 0 0.0025\n'
            f'      <SOURCE WAVE\n        FILE "{f}"\n      >\n    >\n')


def track(guid, name, body="", vol=1.0, bus="0 0", extra=""):
    return (f'  <TRACK {{{guid}}}\n    NAME "{name}"\n    VOLPAN {vol} 0 -1 -1 1\n    MUTESOLO 0 0 0\n    IPHASE 0\n'
            f'    ISBUS {bus}\n    FX 1\n{extra}{body}  >\n')


def vocal(rumble=0.12):
    """8 s: four sung phrases (a 220 Hz voice with harmonics, a little vibrato) over a 40 Hz rumble."""
    t = np.arange(8 * SR) / SR
    f = 220 * (1 + 0.01 * np.sin(2 * np.pi * 5 * t))
    ph = 2 * np.pi * np.cumsum(f) / SR
    v = sum(np.sin(k * ph) / k for k in range(1, 6))
    env = np.zeros_like(t)
    for s in (0.3, 2.3, 4.3, 6.3):
        env += np.clip((t - s) / 0.05, 0, 1) * np.clip((s + 1.5 - t) / 0.05, 0, 1)
    env *= 0.25 * (1 + 0.5 * np.sin(2 * np.pi * 0.7 * t))
    return (v * env + rumble * np.sin(2 * np.pi * 40 * t)).astype(np.float32)


def write_project(folder, tracks, name="Song"):
    folder = Path(folder)
    (folder / "Audio").mkdir(parents=True, exist_ok=True)
    sf.write(folder / "Audio" / "vox.wav", vocal(), SR, subtype="FLOAT")
    txt = ('<REAPER_PROJECT 0.1 "7.86/macOS-arm64" 1764000000\n  TEMPO 120 4 4\n  SAMPLERATE 44100 0 0\n'
           + "".join(tracks) + ">\n")
    p = folder / f"{name}.rpp"
    p.write_text(txt, encoding="utf-8")
    return p


def set_comp(path, track_name, fx, **raw_by_name):
    """Change a ReaComp's raw floats in the file the way `fix` does (sidechain_project.State)."""
    p = PJ.load(path)
    t = p.track(track_name)
    st = SCP.State(t.devices[fx].native)
    for k, v in raw_by_name.items():
        st.vals[SCP.P[k]] = v
    st.write()
    tmp = path.with_name(path.stem + " tmp.rpp")
    E.save(p, tmp)
    os.replace(tmp, path)


def no_highpass(path, track_name, fx):
    p = PJ.load(path)
    st = E.ReaEQ(p.track(track_name).devices[fx].native)
    for b in st.bands:
        if b["type"] == 4:
            b["on"] = False
    st.write()
    tmp = path.with_name(path.stem + " tmp.rpp")
    E.save(p, tmp)
    os.replace(tmp, path)


def lead_project(folder, *fx):
    path = write_project(folder, [track("AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA", "Lead Vocal", item("Audio/vox.wav"),
                                        extra=chain(*fx))])
    return path


def g_devices(path, od, roles=None):
    p = PJ.load(path)
    R = SP.Renders(p, od).build(2)
    return SP.g_devices(p, R, Path(od), SimpleNamespace(), roles or {"Lead Vocal": "lead_vocal"})


class Isolated(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()


# ---------------------------------------------------------------- devices
class Devices(Isolated):
    def test_a_reacomp_that_barely_works_gets_a_suggestion_fix_can_write(self):
        path = lead_project(self.dir / "p", reacomp("Vox comp"))
        set_comp(path, "Lead Vocal", 0, thresh=1.0, detector=0.0, attack=0.002)      # 0 dBFS, own track, 1 ms
        out, notes = g_devices(path, self.dir / "scan")
        comp = [f for f in out if f["kind"] == "compressor"]
        self.assertEqual(len(comp), 1, out)
        f = comp[0]
        self.assertEqual(f["applies"], "set")
        self.assertEqual(f["device"], "Vox comp")
        self.assertIn("barely works", f["problem"])
        self.assertIn("attack", f["problem"])
        self.assertEqual(f["edit"]["op"], "reacomp")
        self.assertLess(f["settings"]["threshold_db"], -6)                # down into the signal
        self.assertTrue(3 <= f["settings"]["attack"] <= 30)
        self.assertTrue(any("ReaComp" in n for n in notes))

    def test_a_reacomp_in_its_usual_range_is_info_only(self):
        path = lead_project(self.dir / "p", reacomp())
        set_comp(path, "Lead Vocal", 0, thresh=1.0, detector=0.0)
        f = [x for x in g_devices(path, self.dir / "s1")[0] if x["kind"] == "compressor"][0]
        path2 = lead_project(self.dir / "q", reacomp())                    # the suggested settings, written in
        names = {i: k for k, i in SCP.P.items()}
        set_comp(path2, "Lead Vocal", 0, detector=0.0, **{names[i]: v for i, v in DP.raw(f["settings"]).items()})
        g = [x for x in g_devices(path2, self.dir / "s2")[0] if x["kind"] == "compressor"][0]
        self.assertEqual(g["applies"], "info", g["problem"])
        self.assertNotIn("edit", g)

    def test_a_sidechained_reacomp_is_left_to_the_sidechain_check(self):
        path = lead_project(self.dir / "p", reacomp())                    # as saved: detector on channels 3/4
        out, notes = g_devices(path, self.dir / "scan")
        self.assertEqual([f for f in out if f["kind"] == "compressor"], [])
        self.assertTrue(any("sidechain" in n for n in notes), notes)

    def test_after_a_plugin_it_does_not_model_a_reacomp_is_not_judged(self):
        path = lead_project(self.dir / "p", jsfx(), reacomp())
        set_comp(path, "Lead Vocal", 1, thresh=1.0, detector=0.0)
        out, _ = g_devices(path, self.dir / "scan")
        self.assertEqual([f["kind"] for f in out], ["unknown-level"])
        self.assertEqual(out[0]["applies"], "info")

    def test_reagate_is_listed_not_judged(self):
        path = lead_project(self.dir / "p", reagate())
        out, _ = g_devices(path, self.dir / "scan")
        self.assertEqual([(f["kind"], f["applies"]) for f in out], [("gate-unread", "info")])
        self.assertIn("not read", out[0]["problem"])

    def test_a_reaeq_with_no_high_pass_on_a_rumbling_part_gets_a_low_cut_suggestion(self):
        path = lead_project(self.dir / "p", reaeq())
        out, _ = g_devices(path, self.dir / "s1")
        self.assertEqual([f for f in out if f["kind"] == "eq-lowcut"], [])     # REAPER's ReaEQ has a high pass on
        no_highpass(path, "Lead Vocal", 0)
        out, _ = g_devices(path, self.dir / "s2")
        cut = [f for f in out if f["kind"] == "eq-lowcut"]
        self.assertEqual(len(cut), 1, out)
        self.assertEqual(cut[0]["applies"], "manual")
        self.assertIn("High Pass", cut[0]["fix"])
        bass = g_devices(path, self.dir / "s3", {"Lead Vocal": "bass"})[0]   # the bass keeps its low end
        self.assertEqual([f for f in bass if f["kind"] == "eq-lowcut"], [])

    def test_an_ardour_session_runs_the_group(self):
        # HypnoMix Studio sessions are judged too now (ACE Compressor, ACE EQ, Hypnomix Saturator:
        # tests/test_ardour_devices3.py); a session with nothing renderable gives no findings and the note
        from tests.test_scan_parity import make_ardour
        p = PJ.load(make_ardour(self.dir))
        out, notes = SP.g_devices(p, SimpleNamespace(files={}), self.dir, SimpleNamespace(), {})
        self.assertEqual(out, [])
        self.assertIn("ACE Compressor(s) judged", notes[0])

    def test_apply_refuses_a_reacomp_changed_since_the_scan(self):
        path = lead_project(self.dir / "p", reacomp())
        set_comp(path, "Lead Vocal", 0, thresh=1.0, detector=0.0)
        f = [x for x in g_devices(path, self.dir / "s")[0] if x["kind"] == "compressor"][0]
        set_comp(path, "Lead Vocal", 0, thresh=0.5)
        with self.assertRaises(ValueError):
            DP.apply(PJ.load(path), f, f["edit"])


# ---------------------------------------------------------------- through `scan` and `fix`
def fix(*args):
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", "fix", *map(str, args)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ))
    return r.returncode, r.stdout + r.stderr


class ThroughFix(Isolated):
    def scan(self, path, *groups):
        od = self.dir / "scan"
        args = [path, "--out", od]
        for g in groups:
            args += ["--only", g]
        txt, bail = run_scan(*args)
        self.assertIsNone(bail, txt)
        sd = next(p.parent for p in od.rglob("findings.json"))
        return sd, json.loads((sd / "findings.json").read_text(encoding="utf-8"))["findings"]

    def comp_after(self, out):
        return SCP.settings(SCP.State(PJ.load(out).track("Lead Vocal").devices[0].native).vals)

    def test_scan_writes_devices_and_structure_into_review_and_fix_writes_the_reacomp(self):
        path = lead_project(self.dir / "p", reacomp())
        set_comp(path, "Lead Vocal", 0, thresh=1.0, detector=0.0, attack=0.002)
        before = SCP.State(PJ.load(path).track("Lead Vocal").devices[0].native).vals
        sd, fs = self.scan(path, "devices", "structure")
        review = (sd / "REVIEW.md").read_text(encoding="utf-8")
        self.assertIn("ReaComp", review)
        f = next(x for x in fs if x["tool"] == "devices" and x["kind"] == "compressor")
        self.assertEqual(f["applies"], "set")
        self.assertFalse([x for x in fs if x["tool"] == "structure"], fs)          # a clean project
        out = path.with_name("Song (fixed).rpp")
        code, txt = fix(sd, "--decide", f"{f['id']}=approve")
        self.assertEqual(code, 0, txt)
        code, txt = fix(sd, "--approved", "--out", out)
        self.assertEqual(code, 0, txt)
        self.assertIn("structure OK", txt)
        back = self.comp_after(out)
        self.assertAlmostEqual(back["threshold_db"], f["settings"]["threshold_db"], places=3)
        self.assertAlmostEqual(back["attack"], f["settings"]["attack"], places=3)
        self.assertAlmostEqual(back["release"], f["settings"]["release"], places=2)
        after = SCP.State(PJ.load(out).track("Lead Vocal").devices[0].native).vals
        changed = {i for i, (a, b) in enumerate(zip(before, after)) if abs(a - b) > 1e-9}
        self.assertTrue(changed <= {SCP.P[k] for k in ("thresh", "ratio", "attack", "release")}, changed)
        self.assertEqual(E.check(path, out), [])
        self.assertAlmostEqual(SCP.settings(before)["threshold_db"], 0.0, places=3)   # the original is untouched
        self.assertEqual(SCP.State(PJ.load(path).track("Lead Vocal").devices[0].native).vals, before)

    def test_an_amount_moves_each_setting_that_share_of_the_way(self):
        path = lead_project(self.dir / "p", reacomp())
        set_comp(path, "Lead Vocal", 0, thresh=1.0, detector=0.0, attack=0.002)
        sd, fs = self.scan(path, "devices")
        f = next(x for x in fs if x["kind"] == "compressor")
        out = path.with_name("Song (fixed).rpp")
        self.assertEqual(fix(sd, "--decide", f"{f['id']}=approve@50")[0], 0)
        code, txt = fix(sd, "--approved", "--out", out)
        self.assertEqual(code, 0, txt)
        back = self.comp_after(out)
        self.assertAlmostEqual(back["threshold_db"], f["settings"]["threshold_db"] / 2, places=2)
        self.assertAlmostEqual(back["attack"], (1.0 + f["settings"]["attack"]) / 2, places=2)

    def test_a_default_named_track_is_named_and_fix_renames_it(self):
        path = write_project(self.dir / "p", [track("AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA", "Track 1",
                                                    item("Audio/vox.wav"))])
        sd, fs = self.scan(path, "names")
        f = next(x for x in fs if x["tool"] == "name")
        self.assertEqual(f["applies"], "set")
        self.assertEqual(f["edit"]["op"], "rename")
        out = path.with_name("Song (fixed).rpp")
        self.assertEqual(fix(sd, "--decide", f"{f['id']}=approve", "--note", "Lead Vocal")[0], 0)
        code, txt = fix(sd, "--approved", "--out", out)
        self.assertEqual(code, 0, txt)
        self.assertEqual([t.name for t in PJ.load(out).tracks], ["Lead Vocal"])


# ---------------------------------------------------------------- structure
class Structure(Isolated):
    def run_on(self, tracks):
        path = write_project(self.dir / "p", tracks)
        return SP.g_structure(PJ.load(path), None, self.dir, SimpleNamespace())

    def test_a_clean_project_has_no_findings(self):
        out, notes = self.run_on([track("A-1", "Gtr", item("Audio/vox.wav"))])
        self.assertEqual(out, [])
        self.assertIn("0 error(s)", notes[-1])

    def test_a_stray_send_a_folder_left_open_and_the_faders(self):
        out, _ = self.run_on([
            track("A-1", "Drums", bus="1 1"),
            track("A-2", "Kick", item("Audio/vox.wav"), vol=3.98, extra="    AUXRECV 7 0 1 0 0 0 0 0 0 -1:U 0 -1 ''\n"),
            track("A-3", "Pad", item("Audio/vox.wav"), vol=0.001),
        ])
        kinds = sorted(f["kind"] for f in out)
        self.assertEqual(kinds, ["fader-low", "fader-max", "send-missing", "set-warning"], out)
        self.assertEqual(next(f for f in out if f["kind"] == "send-missing")["track"], "Kick")

    def test_a_project_that_does_not_read_back_byte_for_byte_is_an_error(self):
        from unittest import mock
        from hypnomix.project import rpp
        path = write_project(self.dir / "p", [track("A-1", "Gtr", item("Audio/vox.wav"))])
        p = PJ.load(path)
        with mock.patch.object(rpp, "dumps", lambda root: "something else"):
            out, _ = SP.g_structure(p, None, self.dir, SimpleNamespace())
        self.assertEqual([f["kind"] for f in out], ["set-error"])
        self.assertEqual(out[0]["severity"], "high")

    def test_structure_and_devices_are_reaper_groups(self):
        self.assertIn("devices", SP.GROUPS)
        self.assertIn("structure", SP.GROUPS)


if __name__ == "__main__":
    unittest.main()
