"""plugins: finding installed plug-ins in the standard folders, marking the free list, checking each safely, and keeping
the list in the preferences."""
import json, plistlib, subprocess, sys, tempfile, unittest
from pathlib import Path

from hypnomix.session import plugins as P


def hx(*args):
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def build(td):
    td = Path(td)
    (td / "VST3/Some Vendor").mkdir(parents=True)
    for n in ("DragonflyHallReverb", "My Own Synth", "TDR Nova"):
        (td / "VST3" / f"{n}.vst3/Contents").mkdir(parents=True)
    (td / "VST3/Some Vendor/LoudMax.vst3").mkdir()
    (td / "VST3/.hidden.vst3").mkdir()
    (td / "AU/Things.component/Contents").mkdir(parents=True)
    (td / "AU/Things.component/Contents/Info.plist").write_bytes(plistlib.dumps(dict(AudioComponents=[
        dict(name="Vendor: Chorus Thing", type="aufx", subtype="chor", manufacturer="vndr"),
        dict(name="Vendor: Big Synth", type="aumu", subtype="bsyn", manufacturer="vndr")])))
    (td / "CLAP").mkdir()
    (td / "CLAP/Surge XT.clap").write_text("x")
    (td / "LV2/thing.lv2").mkdir(parents=True)
    return td


class Finding(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = build(self.td.name)
        self.folders = {"vst3": [self.d / "VST3"], "au": [self.d / "AU"], "clap": [self.d / "CLAP"], "lv2": [self.d / "LV2"]}

    def tearDown(self):
        self.td.cleanup()

    def test_every_format_is_found_and_vendor_folders_are_entered(self):
        found = P.scan(self.folders)
        by = {(r["format"], r["name"]) for r in found}
        self.assertIn(("vst3", "DragonflyHallReverb"), by)
        self.assertIn(("vst3", "LoudMax"), by)          # inside a vendor folder
        self.assertIn(("au", "Chorus Thing"), by)                    # names come from the Info.plist, one bundle can hold several
        self.assertIn(("au", "Big Synth"), by)
        self.assertIn(("clap", "Surge XT"), by)
        self.assertIn(("lv2", "thing"), by)
        self.assertNotIn(("vst3", ".hidden"), by)

    def test_au_kind_comes_from_the_component_type(self):
        kinds = {r["name"]: r["kind"] for r in P.scan(self.folders)}
        self.assertEqual((kinds["Chorus Thing"], kinds["Big Synth"]), ("effect", "instrument"))

    def test_free_list_marks_only_the_readme_names(self):
        found = {r["name"]: r["free"] for r in P.scan(self.folders)}
        self.assertEqual(found["DragonflyHallReverb"], "Dragonfly Reverb")
        self.assertEqual(found["TDR Nova"], "TDR Nova")
        self.assertEqual(found["LoudMax"], "LoudMax")
        self.assertEqual(found["Surge XT"], "Surge XT")
        self.assertIsNone(found["My Own Synth"])
        self.assertIsNone(P.free_match("Spanner"))                    # SPAN must match exactly, not as a piece of a word
        self.assertEqual(P.free_match("SPAN")["name"], "SPAN")

    def test_extra_folder_and_missing_folder(self):
        extra = self.d / "elsewhere"
        (extra / "Odd.vst3").mkdir(parents=True)
        found = P.scan({"vst3": [self.d / "nope"]}, [("vst3", extra)])
        self.assertEqual([r["name"] for r in found], ["Odd"])

    def test_every_free_name_is_in_the_readme(self):
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
        table = readme[readme.index("### Free plug-ins that work with hypnomix"):]
        for f in P.FREE:
            self.assertIn(f["name"], table, f["name"])

    def test_standard_folders_per_system(self):
        self.assertTrue(any("Components" in str(x) for x in P.system_folders("darwin", "/h")["au"]))
        self.assertEqual(P.system_folders("win32", "/h")["au"], [])
        self.assertTrue(any(str(x).endswith(".vst3") for x in P.system_folders("linux", "/h")["vst3"]))


class Checking(unittest.TestCase):
    def test_a_crash_or_a_hang_is_one_row_and_the_run_goes_on(self):
        rows = [dict(name=n, format="vst3", path=f"/x/{n}.vst3", kind="", free=None) for n in ("Fine", "Crashes", "Hangs", "Gone")]
        rows.append(dict(name="Clappy", format="clap", path="/x/c.clap", kind="", free=None))

        def probe(path, name, state, timeout=60):
            if "Crashes" in path:
                return dict(ok=False, error="the plug-in crashed while loading (signal 11)")
            if "Hangs" in path:
                return dict(ok=False, error=f"did not load within {timeout} s")
            if "Gone" in path:
                raise RuntimeError("boom")
            return dict(ok=True, instrument=False, params={"a": 0.1, "b": 0.2})

        with self.assertRaises(RuntimeError):                         # an unexpected error in the probe itself is not hidden
            P.check(rows, 5, probe=probe)
        rows = [r for r in rows if r["name"] != "Gone"]
        P.check(rows, 5, probe=probe)
        by = {r["name"]: r for r in rows}
        self.assertTrue(by["Fine"]["loads"])
        self.assertEqual(by["Fine"]["parameters"], 2)
        self.assertEqual(by["Fine"]["kind"], "effect")
        self.assertFalse(by["Crashes"]["loads"])
        self.assertIn("crashed", by["Crashes"]["error"])
        self.assertIn("did not load within 5", by["Hangs"]["error"])
        self.assertIsNone(by["Clappy"]["loads"])
        self.assertIn("not checked", by["Clappy"]["error"])

    def test_the_real_probe_survives_a_plugin_that_does_not_exist(self):
        from hypnomix.session import plugrender as PR
        res = PR.probe("/nonexistent/Nothing.vst3", None, None, timeout=60)
        self.assertFalse(res["ok"])
        self.assertTrue(res["error"])


class Saving(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = build(self.td.name)
        self.prefs = self.d / "prefs.json"
        self.found = P.scan({"vst3": [self.d / "VST3"], "au": [self.d / "AU"]})

    def tearDown(self):
        self.td.cleanup()

    def test_saved_names_are_the_free_ones_and_hand_entries_are_kept(self):
        self.prefs.write_text(json.dumps({"tools": {"daw": "ableton", "plugins": ["Hand Added"]}}))
        P.save_prefs(self.found, False, False, self.prefs)
        d = json.loads(self.prefs.read_text())
        self.assertEqual(d["tools"]["daw"], "ableton")
        self.assertEqual(sorted(d["tools"]["plugins"]), sorted(["Hand Added", "DragonflyHallReverb", "TDR Nova", "LoudMax"]))
        self.assertEqual(len(d["tools"]["plugins_found"]), len(self.found))
        P.save_prefs(self.found, False, True, self.prefs)
        self.assertNotIn("Hand Added", json.loads(self.prefs.read_text())["tools"]["plugins"])

    def test_a_plugin_that_failed_to_load_is_not_offered(self):
        for r in self.found:
            r["loads"] = r["name"] != "TDR Nova"
        names, rows = P.to_prefs(self.found, True)
        self.assertNotIn("TDR Nova", names)
        self.assertIn("DragonflyHallReverb", names)
        self.assertFalse(next(r for r in rows if r["name"] == "TDR Nova")["loads"])

    def test_installed_helpers_read_the_preferences(self):
        prefs = {"tools": {"plugins": ["DragonflyHallReverb", "TDR Nova", "Unknown One"]}}
        self.assertEqual(P.installed_free(prefs), ["DragonflyHallReverb", "TDR Nova", "Unknown One"])
        self.assertEqual(P.installed_with_use(prefs, "space"), [("DragonflyHallReverb", "space")])
        self.assertEqual(P.installed_with_use(prefs, "grit"), [])


class Command(unittest.TestCase):
    def test_list_json_and_save_from_the_command_line(self):
        with tempfile.TemporaryDirectory() as td:
            d = build(td)
            args = ["plugins", "--no-system", "--folder", f"vst3={d / 'VST3'}", "--folder", f"au={d / 'AU'}",
                    "--folder", f"clap={d / 'CLAP'}"]
            code, out = hx(*args)
            self.assertEqual(code, 0, out)
            self.assertIn("on the free list", out)
            self.assertIn("nothing was written", out)
            code, out = hx(*args, "--json", d / "out.json")
            doc = json.loads((d / "out.json").read_text())
            self.assertEqual(doc["free_installed"], ["DragonflyHallReverb", "LoudMax", "Surge XT", "TDR Nova"])
            self.assertFalse(doc["checked"])
            self.assertIsNone(doc["saved"])
            code, out = hx(*args, "--free", "--json")                   # data on stdout, the report on stderr
            self.assertEqual(code, 0, out)
            r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args), "--free", "--json"], capture_output=True, text=True)
            self.assertEqual({p["name"] for p in json.loads(r.stdout)["plugins"]}, {"DragonflyHallReverb", "LoudMax", "Surge XT", "TDR Nova"})
            code, out = hx(*args, "--save", "--prefs-file", d / "p.json")
            self.assertEqual(code, 0, out)
            self.assertIn("saved 4 free plug-in(s)", out)
            self.assertEqual(json.loads((d / "p.json").read_text())["tools"]["plugins"][0], "DragonflyHallReverb")

    def test_a_bad_folder_option_is_explained(self):
        code, out = hx("plugins", "--folder", "vst2=/x")
        self.assertNotEqual(code, 0)
        self.assertIn("FORMAT=DIR", out)

    def test_nothing_found_says_where_to_look(self):
        with tempfile.TemporaryDirectory() as td:
            code, out = hx("plugins", "--no-system", "--folder", f"vst3={td}")
            self.assertEqual(code, 0, out)
            self.assertIn("--folder", out)


if __name__ == "__main__":
    unittest.main()
