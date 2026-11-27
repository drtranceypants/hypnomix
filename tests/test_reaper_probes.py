"""HypnoMix Probe / Main for REAPER: the JSFX, putting them into a project, and reading the menus back."""
import collections
import contextlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path

from hypnomix.reaper import probes as P

RPP = """<REAPER_PROJECT 0.1 "7.86/macOS-arm64" 1\r
  TEMPO 120 4 4\r
  <TRACK {A}\r
    NAME Kick\r
    ISBUS 0 0\r
  >\r
  <TRACK {B}\r
    NAME Bass\r
    ISBUS 0 0\r
    <FXCHAIN\r
      SHOW 0\r
      LASTSEL 0\r
      DOCKED 0\r
      BYPASS 0 0 0\r
      <JS loser/3BandEQ ""\r
        0 200 2000 - - -\r
      >\r
      FLOATPOS 0 0 0 0\r
      FXID {C}\r
      WAK 0 0\r
    >\r
  >\r
>\r
"""


class ReaperProbes(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_jsfx_names_never_collide_by_case(self):
        """JSFX variable names are case-insensitive: N and n are one variable (that bug made every sample a block)."""
        for f in P.JSFX.iterdir():
            src = re.sub(r"//[^\n]*", "", f.read_text(encoding="utf-8"))
            src = re.sub(r'"[^"\n]*"', '""', src)                  # text in quotes is not a variable
            src = "\n".join(l for l in src.splitlines() if not l.startswith(("slider", "desc:", "in_pin", "out_pin")))
            names = collections.defaultdict(set)
            for w in re.findall(r"(?<![.\w$])([A-Za-z_]\w*)", src):
                names[w.lower()].add(w)
            clash = {k: v for k, v in names.items() if len(v) > 1}
            self.assertEqual(clash, {}, f.name)

    def test_menus_match_the_live_probe(self):
        from hypnomix.app import probe as LP
        m = P.menus()
        self.assertEqual([k for k, _ in m["hypnomix_probe.jsfx"]], P.TRACK_KEYS)
        self.assertEqual([k for k, _ in m["hypnomix_main.jsfx"]], P.MAIN_KEYS)
        labels = dict(m["hypnomix_probe.jsfx"])
        self.assertEqual(labels["role"], LP.ROLES)
        main = dict(m["hypnomix_main.jsfx"])
        self.assertEqual((main["genre"], main["key"], main["scale"]), (LP.GENRES, LP.KEYS, LP.SCALES))

    def test_insert_and_read_cards(self):
        src = self.dir / "Song.rpp"
        src.write_bytes(RPP.encode())
        out, n = P.insert(src)
        self.assertEqual(n, 3)                                   # two tracks and the master
        text = out.read_bytes().decode()
        self.assertEqual(text.count("\r\n"), text.count("\n"))   # REAPER's CRLF kept on every line
        self.assertIn('<JS hypnomix/hypnomix_probe.jsfx ""', text)
        self.assertIn("<MASTERFXLIST", text)
        body = text.split('<JS hypnomix/hypnomix_main.jsfx ""')[1].splitlines()[1].split()
        self.assertEqual(body[:8], ["0", "0", "0", "0", "-14", "-1", "100", "-1"])
        self.assertEqual(len(body), 64)                          # REAPER writes 64 slider values
        bass = text.split("NAME Bass")[1]
        self.assertLess(bass.index("loser/3BandEQ"), bass.index("hypnomix_probe.jsfx"))   # the probe goes LAST
        again, n2 = P.insert(out, self.dir / "Again.rpp")
        self.assertEqual(n2, 0)                                  # already there: nothing added twice
        # a guitar with focus, and an A minor card at -12 LUFS, the way REAPER saves them
        t = text.replace("0 0 0 -1 -", "10 1 0 -1 -", 1).replace("0 0 0 0 -14 -1 100 -1", "0 10 1 0 -12 -1 100 -1")
        (self.dir / "Told.rpp").write_bytes(t.encode())
        c = P.read_cards(self.dir / "Told.rpp")
        self.assertEqual(c["tracks"]["Kick"], {"role": "guitar", "priority": "focus: others give way", "protect": "off"})
        self.assertEqual((c["song"]["key"], c["song"]["scale"], c["song"]["target"]), ("A", "minor", -12.0))

    def test_probe_read_cards_dispatches_rpp(self):
        from hypnomix.app.probe import read_cards
        src = self.dir / "Song.rpp"
        src.write_bytes(RPP.encode())
        out, _ = P.insert(src)
        c = read_cards(out, self.dir / "cards.json")
        self.assertEqual(c["tracks"]["Bass"]["role"], "auto")

    def test_inserted_rpp_uses_jsfx_desc_and_reads_old_spelling_projects(self):
        """Inserted <JS> lines leave the custom-name slot empty so REAPER shows the JSFX's own desc: title
        (HypnoMix Probe / HypnoMix Main), and older projects carrying an old-spelling display name or mixed-case
        path still read back and are not duplicated on re-insert."""
        self.assertTrue((P.JSFX / "hypnomix_probe.jsfx").read_text(encoding="utf-8").startswith("desc:HypnoMix Probe\n"))
        self.assertTrue((P.JSFX / "hypnomix_main.jsfx").read_text(encoding="utf-8").startswith("desc:HypnoMix Main\n"))
        src = self.dir / "Song.rpp"
        src.write_bytes(RPP.encode())
        out, _ = P.insert(src)
        text = out.read_bytes().decode()
        self.assertNotIn("Hypnomix Probe", text)
        self.assertNotIn("Hypnomix Main", text)
        old = (text.replace('<JS hypnomix/hypnomix_probe.jsfx ""', '<JS HYPNOMIX/HYPNOMIX_PROBE.JSFX "Hypnomix Probe"')
                   .replace('<JS hypnomix/hypnomix_main.jsfx ""', '<JS HYPNOMIX/HYPNOMIX_MAIN.JSFX "Hypnomix Main"')
                   .replace("0 0 0 -1 -", "10 1 0 -1 -", 1)
                   .replace("0 0 0 0 -14 -1 100 -1", "0 10 1 0 -12 -1 100 -1"))
        old_rpp = self.dir / "Old.rpp"
        old_rpp.write_bytes(old.encode())
        c = P.read_cards(old_rpp)
        self.assertEqual(c["tracks"]["Kick"], {"role": "guitar", "priority": "focus: others give way", "protect": "off"})
        self.assertEqual((c["song"]["key"], c["song"]["scale"], c["song"]["target"]), ("A", "minor", -12.0))
        _, added = P.insert(old_rpp, self.dir / "OldAgain.rpp")
        self.assertEqual(added, 0)


class HypnoMixWindows(unittest.TestCase):
    """The JSFX windows and the bridge's panels share one look and a built-in guide."""

    def setUp(self):
        self.root = Path(P.__file__).resolve().parent

    def test_the_look_ships_and_loads(self):
        self.assertIn("hypnomix_ui.jsfx-inc", P.FILES)                       # `probes install` copies it
        for f in ("hypnomix_probe.jsfx", "hypnomix_main.jsfx"):
            src = (P.JSFX / f).read_text(encoding="utf-8")
            self.assertIn("import hypnomix_ui.jsfx-inc", src)
            self.assertIn("no_meter", src)
            self.assertIn("ui_help(", src)                                    # the "?"
        lua = (self.root / "bridge.lua").read_text(encoding="utf-8")
        self.assertIn('dofile, UI_HERE .. "ui.lua"', lua)
        self.assertTrue((self.root / "ui.lua").exists())

    def test_every_guide_step_exists(self):
        """ui_tour_n matches the steps written out (one `ui_tour_i == k` per step but the last, which is the else)."""
        for f in ("hypnomix_probe.jsfx", "hypnomix_main.jsfx"):
            src = (P.JSFX / f).read_text(encoding="utf-8")
            n = int(re.search(r"ui_tour_n = (\d+);", src).group(1))
            ks = sorted(int(k) for k in re.findall(r"ui_tour_i == (\d+) \?", src))
            self.assertEqual(ks, list(range(n - 1)), f)

    def test_settings_are_hidden_but_still_the_card(self):
        """REAPER's slider rows are hidden (the window sets them), and the card is still read by name."""
        for f in ("hypnomix_probe.jsfx", "hypnomix_main.jsfx"):
            for line in (P.JSFX / f).read_text(encoding="utf-8").splitlines():
                if line.startswith("slider"):
                    self.assertRegex(line, r">-", line)
        m = P.menus()
        self.assertEqual([k for k, _ in m["hypnomix_probe.jsfx"]], ["role", "priority", "protect"])
        self.assertNotIn("guide", [k for k, _ in m["hypnomix_main.jsfx"]])

    def test_names_are_found_in_any_case(self):
        from hypnomix.reaper import mixer as MX
        lua = (self.root / "bridge.lua").read_text(encoding="utf-8") + (self.root / "masterchain.lua").read_text(encoding="utf-8")
        self.assertNotIn('find("HypnoMix Main"', lua)
        self.assertIn('find("hypnomix main", 1, true)', lua)
        for name in ("JS: Hypnomix Probe", "JS: HypnoMix Probe", "JS: Hypnomix Main", "JS: HypnoMix Main"):
            self.assertTrue(MX._own_internal(name, "slot (set by hypnomix)"), name)
            self.assertFalse(MX._own_internal(name, "Target LUFS"), name)


if __name__ == "__main__":
    unittest.main()


class InstallMessage(unittest.TestCase):
    def test_install_tells_upgraders_to_rescan_with_f5(self):
        """REAPER caches effect names, so after an update the Add FX list can show the old ones until a rescan."""
        with tempfile.TemporaryDirectory() as td:
            old = os.environ.get("HYPNOMIX_REAPER_RESOURCES")
            os.environ["HYPNOMIX_REAPER_RESOURCES"] = td
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    P.main(["install"])
            finally:
                if old is None:
                    os.environ.pop("HYPNOMIX_REAPER_RESOURCES", None)
                else:
                    os.environ["HYPNOMIX_REAPER_RESOURCES"] = old
            out = buf.getvalue()
            self.assertIn("press F5 to rescan", out)
            self.assertTrue((Path(td) / "Effects" / "hypnomix" / "hypnomix_main.jsfx").is_file())
