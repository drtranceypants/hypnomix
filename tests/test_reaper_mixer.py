"""REAPER's hands-on mixer tools (`hypnomix reaper snapshot / loop / diagnose`) against a fake bridge. The Lua side
(mixer.lua) cannot run here: these tests check that Python and the Lua agree on command names, keys and the restore
file, and that bridge.lua loads mixer.lua the way it loads masterchain.lua."""
import contextlib
import io
import json
import math
import re
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix.reaper import mixer as MX

ROOT = Path(__file__).resolve().parents[1] / "hypnomix" / "reaper"
LUA = (ROOT / "mixer.lua").read_text(encoding="utf-8")
BRIDGE = (ROOT / "bridge.lua").read_text(encoding="utf-8")
SR = 22050


def snap():
    return {"project": "Song.rpp", "tempo": 120, "tracks": [
        {"index": -1, "name": "MASTER", "guid": "{M}", "master": True, "volume": 1.0, "pan": 0.0, "width": 1.0,
         "mute": False, "phase": False, "sends": [], "fx": [
             {"index": 0, "name": "ReaLimit (Cockos)", "guid": "{F0}", "on": True, "params": [
                 {"i": 0, "name": "Threshold", "value": 0.5, "shown": "-3.0"}]}]},
        {"index": 0, "name": "Drums", "guid": "{D}", "volume": 1.0, "pan": 0.0, "width": 1.0, "mute": False,
         "phase": False, "solo": 0, "depth": 1, "sends": [], "fx": []},
        {"index": 1, "name": "Kick", "guid": "{K}", "volume": 0.5, "pan": 0.0, "width": 1.0, "mute": False,
         "phase": False, "solo": 0, "depth": -1, "fx": [],
         "sends": [{"index": 0, "dest": "Verb", "volume": 0.25, "pan": 0.0, "mute": False, "mode": 0}]},
        {"index": 2, "name": "Lead Vocal", "guid": "{V}", "volume": 1.0, "pan": -0.2, "width": 1.0, "mute": False,
         "phase": False, "solo": 0, "depth": 0, "sends": [], "fx": [
             {"index": 0, "name": "ReaComp (Cockos)", "guid": "{C}", "on": True, "params": [
                 {"i": 0, "name": "Thresh", "value": 0.4, "shown": "-12.0"},
                 {"i": 1, "name": "Ratio", "value": 0.1, "shown": "4.0:1"}]}]},
        {"index": 3, "name": "Verb", "guid": "{R}", "volume": 1.0, "pan": 0.0, "width": 1.0, "mute": True,
         "phase": False, "solo": 0, "depth": 0, "sends": [], "fx": []}]}


def tone(f, secs=1.0, amp=0.3, stereo_offset=0.0):
    t = np.arange(int(secs * SR)) / SR
    L = amp * np.sin(2 * np.pi * f * t)
    R = amp * np.sin(2 * np.pi * f * t + stereo_offset)
    return np.stack([L, R], axis=1).astype(np.float32)


class FakeBridge:
    """Answers the bridge commands the mixer tools send; renders are tones chosen per soloed track."""
    def __init__(self, folder):
        self.dir = Path(folder)
        self.calls, self.snap, self.restored = [], snap(), None
        self.solo_tone = {"{D}": 50.0, "{V}": 2000.0}

    def call(self, cmd, **k):
        self.calls.append((cmd, k))
        if cmd == "mixer_snapshot":
            return json.loads(json.dumps(self.snap))
        if cmd == "mixer_restore":
            self.restored = Path(k["file"]).read_text(encoding="utf-8")
            return {"changed": 3, "missing": []}
        if cmd == "mixer_timemap":
            return {"length": 8.0, "tempo": 120, "bars": [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]}
        if cmd == "mixer_solo_render":
            if "," in k["tracks"]:                                  # the whole song, every unit soloed
                y = tone(100.0, secs=k["end"] - k["start"])
                y[: int(SR * 2)] *= 0.1                             # bar 1 quiet: the loudest stretch is later
                sf.write(k["path"], y, SR)
                return {"path": k["path"], "exists": True, "soloed": k["tracks"].count(",") + 1}
            sf.write(k["path"], tone(self.solo_tone.get(k["tracks"], 400.0), secs=k["end"] - k["start"]), SR)
            return {"path": k["path"], "exists": True, "soloed": 1}
        if cmd == "ping":
            return {"project": "/x/Song.rpp"}
        return {}

    def tracks(self):
        return [{k: t[k] for k in ("index", "name", "guid", "volume", "pan", "mute", "depth")}
                for t in self.snap["tracks"] if not t.get("master")]

    def set_track(self, track, volume_db=None, pan=None, mute=None):
        self.calls.append(("set_track", dict(track=track, volume_db=volume_db, pan=pan, mute=mute)))
        return {}

    def enable(self, track, fx, on=True):
        self.calls.append(("fx_enable", dict(track=track, fx=fx, on=on)))
        return {}

    def set_norm(self, track, fx, param, value):
        self.calls.append(("set_param", dict(track=track, fx=fx, param=param, value=value)))
        return {}

    def set_shown(self, track, fx, param, value):
        self.calls.append(("set_param", dict(track=track, fx=fx, param=param, shown=value)))
        return {}

    def render_master(self, start, end, path):
        y = tone(100.0, secs=end - start)
        y[: int(SR * 2)] *= 0.1                                 # bar 1 quiet: the loudest stretch is later
        if self.calls and self.calls[-1][0] == "set_track":
            y *= 0.5                                            # the change made B quieter
        sf.write(str(path), y, SR, subtype="FLOAT")
        self.calls.append(("render_master", dict(start=start, end=end, path=str(path))))
        return Path(path)


def fake_measure(wav):
    y, sr = sf.read(str(wav), always_2d=True)
    lufs = 10 * math.log10(float((y ** 2).mean()) + 1e-15)
    return {"integrated_lufs": lufs, "true_peak_dbtp": 20 * math.log10(float(np.abs(y).max()) + 1e-12),
            "band_sub_20_60": -20.0}


class Snapshot(unittest.TestCase):
    def test_flatten_is_values_only_and_lua_reads_every_key(self):
        text = MX.flatten(snap())
        kinds = {ln.split("\t")[0] for ln in text.splitlines()}
        self.assertEqual(kinds, {"track", "info", "send", "fx", "param", "on"})
        for kind in kinds:
            self.assertIn(f'kind == "{kind}"', LUA)
        info = {ln.split("\t")[1] for ln in text.splitlines() if ln.startswith("info\t")}
        send = {ln.split("\t")[3] for ln in text.splitlines() if ln.startswith("send\t")}
        lua_info = set(re.findall(r"(\w+) = true", LUA.split("local INFO = {")[1].split("}")[0]))
        lua_send = set(re.findall(r"(\w+) = true", LUA.split("local SEND = {")[1].split("}")[0]))
        self.assertLessEqual(info, lua_info)
        self.assertLessEqual(send, lua_send)
        self.assertNotIn("I_SOLO", text.split("track\t{D}")[0])        # the master has no solo
        self.assertIn("track\t{M}\t-1\tMASTER", text)
        self.assertIn("send\t0\tVerb\tD_VOL\t0.25", text)
        self.assertIn("param\t1\t0.1", text)

    def test_names_with_tabs_cannot_break_the_file(self):
        s = snap()
        s["tracks"][3]["name"] = "Lead\tVocal\nTake 2"
        line = next(ln for ln in MX.flatten(s).splitlines() if ln.startswith("track\t{V}"))
        self.assertEqual(line.split("\t"), ["track", "{V}", "2", "Lead Vocal Take 2"])

    def test_restore_writes_into_the_bridge_folder_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as td:
            b = FakeBridge(td)
            res = MX.restore(b, snap())
            self.assertEqual(res["changed"], 3)
            cmd, k = b.calls[-1]
            self.assertEqual(cmd, "mixer_restore")
            self.assertTrue(k["file"].startswith(str(Path(td)).replace("\\", "/")))
            self.assertFalse(Path(k["file"]).exists())
            self.assertIn("fx\t{C}\t0\tReaComp (Cockos)", b.restored)

    def test_diff_in_plain_words(self):
        a, b = snap(), snap()
        b["tracks"][2]["volume"] = 0.5 * 10 ** (1.5 / 20)                # Kick +1.5 dB
        b["tracks"][3]["pan"] = 0.0
        b["tracks"][3]["fx"][0]["on"] = False
        b["tracks"][3]["fx"][0]["params"][0].update(value=0.5, shown="-6.0")
        b["tracks"][2]["sends"][0]["volume"] = 0.5
        b["tracks"][4]["mute"] = False
        b["tracks"].append({"index": 4, "name": "Pad", "guid": "{P}", "volume": 1.0, "fx": []})
        lines = MX.diff(a, b)
        text = "\n".join(lines)
        self.assertIn("Kick: fader -6.0 dB → -4.5 dB (+1.5 dB)", text)
        self.assertIn("Lead Vocal: pan 20% left → centre", text)
        self.assertIn("Lead Vocal · ReaComp (Cockos): switched off", text)
        self.assertIn("Lead Vocal · ReaComp (Cockos): Thresh -12.0 → -6.0", text)
        self.assertIn("Kick: send to Verb -12.0 dB → -6.0 dB", text)
        self.assertIn("Verb: unmuted", text)
        self.assertIn("Pad: a new track", text)
        self.assertEqual(MX.diff(a, snap()), [])

    def test_cli_snapshot_save_and_diff(self):
        with tempfile.TemporaryDirectory() as td:
            b = FakeBridge(td)
            out = Path(td) / "a.json"
            with contextlib.redirect_stdout(io.StringIO()):
                MX.main_snapshot([str(out)], r=b)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["tracks"][0]["name"], "MASTER")
            s2 = snap(); s2["tracks"][1]["mute"] = True
            (Path(td) / "b.json").write_text(json.dumps(s2), encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                MX.main_snapshot(["diff", str(out), str(Path(td) / "b.json")], r=b)
            self.assertEqual(buf.getvalue().strip(), "Drums: muted")


class Changes(unittest.TestCase):
    def test_parse_refuses_to_guess(self):
        for bad in ("db Lead", "louder Lead 2", "mute Lead 2", "fx Lead 0 maybe", "db Lead abc"):
            with self.assertRaises(ValueError, msg=bad):
                MX.parse_change(bad)
        self.assertEqual(MX.parse_change("db 'Lead Vocal' -2"), ("db", ["Lead Vocal", "-2"]))

    def test_each_change_is_the_right_bridge_command(self):
        with tempfile.TemporaryDirectory() as td:
            b = FakeBridge(td)
            MX.apply_change(b, "nudge Kick +1.5")
            self.assertAlmostEqual(b.calls[-1][1]["volume_db"], 20 * math.log10(0.5) + 1.5)
            MX.apply_change(b, "fx 'Lead Vocal' ReaComp 0")
            self.assertEqual(b.calls[-1], ("fx_enable", dict(track="Lead Vocal", fx="ReaComp", on=False)))
            MX.apply_change(b, "send Kick 0 -9")
            self.assertEqual(b.calls[-1], ("mixer_send", dict(track="Kick", send=0, volume_db=-9.0)))
            MX.apply_change(b, "paramd master 0 Threshold -2")
            self.assertEqual(b.calls[-1][1]["shown"], -2.0)
            MX.apply_change(b, "pan Kick 3")
            self.assertEqual(b.calls[-1][1]["pan"], 1.0)


class Loop(unittest.TestCase):
    def test_bar_span(self):
        tm = {"bars": [0.0, 2.0, 4.0, 6.0]}
        self.assertEqual(MX.bar_span(tm, 2, 3), (2.0, 6.0))
        with self.assertRaises(ValueError):
            MX.bar_span(tm, 2, 4)

    def test_take_then_compare_with_the_previous(self):
        with tempfile.TemporaryDirectory() as td:
            b = FakeBridge(td)
            with contextlib.redirect_stdout(io.StringIO()):
                MX.loop(b, 2.0, 6.0, Path(td) / "loop", measure=fake_measure, log=lambda *a: None)
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    MX.loop(b, 2.0, 6.0, Path(td) / "loop", label="again", measure=fake_measure, log=lambda *a: None)
            self.assertIn("Δ vs previous take", buf.getvalue())
            files = sorted(p.name for p in (Path(td) / "loop").iterdir())
            self.assertEqual(files, ["01-take.json", "01-take.wav", "02-again.json", "02-again.wav"])
            meta = json.loads((Path(td) / "loop" / "02-again.json").read_text(encoding="utf-8"))
            self.assertEqual((meta["start"], meta["end"]), (2.0, 6.0))
            self.assertEqual(meta["mix"]["tracks"][1]["name"], "Drums")

    def test_ab_level_matches_b_and_reverts(self):
        with tempfile.TemporaryDirectory() as td:
            b, said = FakeBridge(td), []
            with contextlib.redirect_stdout(io.StringIO()):
                out = MX.loop(b, 2.0, 6.0, Path(td) / "loop", label="kick", ab=["db Kick -3"], revert=True,
                              measure=fake_measure, log=said.append)
            self.assertAlmostEqual(out["gain_db"], 20 * math.log10(2), places=2)    # B rendered at half level
            ya, _ = sf.read(out["a"]); ym, _ = sf.read(out["b_matched"])
            self.assertAlmostEqual(float(np.abs(ya).max()), float(np.abs(ym).max()), places=4)
            self.assertIn("quieter", "\n".join(said))
            self.assertEqual(b.calls[-1][0], "mixer_restore")
            self.assertIn("reverted", out)

    def test_a_bad_change_stops_before_any_render(self):
        with tempfile.TemporaryDirectory() as td:
            b = FakeBridge(td)
            with self.assertRaises(ValueError):
                MX.loop(b, 0, 2, Path(td), ab=["db Kick"], measure=fake_measure)
            self.assertFalse([c for c in b.calls if c[0] == "render_master"])


class Diagnose(unittest.TestCase):
    def test_top_level_folders_and_loose_tracks(self):
        tl = MX.top_level(FakeBridge(".").tracks())
        self.assertEqual([(t["name"], t["folder"]) for t in tl], [("Drums", True), ("Lead Vocal", False), ("Verb", False)])
        flat = [{"name": n, "depth": 0} for n in "abc"]
        self.assertEqual([t["name"] for t in MX.top_level(flat)], ["a", "b", "c"])

    def test_loudest_window(self):
        y = np.zeros((10 * SR, 2)); y[6 * SR:8 * SR] = 0.5
        self.assertEqual(MX.loudest(y, SR, [0, 2, 4, 6, 8, 10], 1), 4)
        self.assertEqual(MX.loudest(y, SR, [0, 2, 4, 6, 8, 10], 2), 3)

    def test_solo_each_folder_and_say_who_owns_what(self):
        with tempfile.TemporaryDirectory() as td:
            b = FakeBridge(td)
            out = MX.diagnose(b, Path(td) / "dx", bars=2, log=lambda *a: None)
            self.assertEqual(out["by"], "folder")
            self.assertEqual(out["loud_bars"], [2, 3])
            solos = [k for c, k in b.calls if c == "mixer_solo_render"]
            self.assertEqual(solos[0]["tracks"].count(","), 2)                    # the whole song: every unit soloed
            self.assertEqual([k["tracks"] for k in solos[1:]], ["{D}", "{V}"])      # Verb is muted: skipped
            self.assertEqual((solos[1]["start"], solos[1]["end"]), (2.0, 6.0))
            u = out["units"]
            self.assertGreater(u["Drums"]["sub_share"], 90)
            self.assertGreater(u["Lead Vocal"]["vocal_share"], 90)
            said = []
            MX.print_diagnosis(out, log=said.append)
            self.assertTrue(any("Drums owns the sub" in s for s in said))
            self.assertTrue(any("Lead Vocal owns the vocal band" in s for s in said))
            self.assertTrue((Path(td) / "dx" / "diagnose.json").exists())


class Lua(unittest.TestCase):
    def test_bridge_loads_mixer_like_masterchain(self):
        self.assertIn('dofile(HERE .. "mixer.lua")', BRIDGE)
        self.assertIn("MX.commands(C, CHANGES)", BRIDGE)
        self.assertLess(BRIDGE.index("local CHANGES"), BRIDGE.index('"mixer.lua"'))
        self.assertLess(BRIDGE.index("function C.render_master"), BRIDGE.index('"mixer.lua"'))

    def test_every_command_python_sends_exists_in_lua(self):
        py = (ROOT / "mixer.py").read_text(encoding="utf-8")
        for cmd in set(re.findall(r'"(mixer_\w+)"', py)):
            self.assertIn(f"function C.{cmd}(", LUA, cmd)

    def test_undo_steps(self):
        self.assertIn('reaper.Undo_EndBlock("hypnomix: snapshot restore", -1)', LUA)
        self.assertIn("CHANGES.mixer_restore = false", LUA)
        self.assertIn("CHANGES.mixer_send = true", LUA)
        self.assertNotRegex(LUA, r"reaper\.(MB|ShowMessageBox|GetUserInputs)\(")     # no dialogs
        self.assertNotIn("40860", LUA)                                             # never closes a tab

    def test_blocks_balance(self):
        """A rough syntax check (no Lua here): every function/if/for/while opens one `end`."""
        code = re.sub(r"--[^\n]*", "", re.sub(r'"(?:\\.|[^"\\])*"', '""', LUA))
        opens = len(re.findall(r"\b(function|if|for|while)\b", code))
        ends = len(re.findall(r"\bend\b", code))
        self.assertEqual(opens, ends)


if __name__ == "__main__":
    unittest.main()
