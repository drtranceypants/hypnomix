"""Hypnomix Probe / Main for REAPER: the JSFX, putting them into a project, and reading the menus back."""
import collections
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
            src = re.sub(r"//[^\n]*", "", f.read_text())
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


if __name__ == "__main__":
    unittest.main()
