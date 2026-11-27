"""The ReaComp sidechain check reads Dry / Wet like the devices check: a compressor with Wet at 0 or a parallel
(dry and wet) mix is listed and not judged, since the ducking model assumes a fully wet compressor."""
import tempfile
import unittest
from pathlib import Path

from hypnomix import project
from hypnomix.project import rpp_edit as E
from hypnomix.workflow import sidechain_project as SCP

HDR = "bWNlcu9e7f4EAAAAAQAAAAAAAAACAAAAAAAAAAQAAAAAAAAACAAAAAAAAAACAAAAAQAAAAAAAAACAAAAAAAAAFwAAAAAAAAAAAAQAA=="
STATE = ("776t3g3wrd7NzEw9zczMPW8SAzvNzEw+AAAAAAAAAAAAAIA/AAAAAIzU8ToAAAAAnNEHMwAAgD8AAAAAzcxMPQAAAAAAAAAAAAAAAAAAgD4"
         "AAAAAAAAAAAAAAAA=")
TXT = ('<REAPER_PROJECT 0.1 "7.86/macOS-arm64" 1\n  TEMPO 120 4 4\n'
       '  <TRACK {A}\n    NAME Kick\n    ISBUS 0 0\n  >\n'
       '  <TRACK {B}\n    NAME Bass\n    NCHAN 4\n    ISBUS 0 0\n    AUXRECV 0 0 1 0 0 0 0 0 2 -1:U 0 -1 \'\'\n'
       '    <FXCHAIN\n      BYPASS 0 0 0\n      <VST "VST: ReaComp (Cockos)" reacomp.vst.dylib 0 "" 1919247213<5653547265636D726561636F6D700000> ""\n'
       f'        {HDR}\n        {STATE}\n        AAAQAAAA\n      >\n    >\n  >\n>\n')


class SidechainDryWet(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)
        self.addCleanup(self._td.cleanup)

    def project_with(self, dry, wet, name):
        src = self.dir / "Sc.rpp"
        src.write_text(TXT, encoding="utf-8")
        p = project.load(src)
        st = SCP.find(p)[0]["state"]
        vals = list(st.vals)
        vals[SCP.P["dry"]], vals[SCP.P["wet"]] = dry, wet
        st.vals = vals
        st.write()
        out = self.dir / name
        E.save(p, out)
        return project.load(out)

    def why(self, p):
        (_, r, why), = SCP.analyse(p)
        return r, why

    def test_wet_at_zero_is_not_judged(self):
        r, why = self.why(self.project_with(1.0, 0.0, "dry.rpp"))
        self.assertIsNone(r)
        self.assertIn("no ducking is heard: not judged", why)

    def test_parallel_is_not_judged(self):
        r, why = self.why(self.project_with(1.0, 1.0, "par.rpp"))
        self.assertIsNone(r)
        self.assertIn("parallel compression: not judged", why)

    def test_fully_wet_goes_on_to_be_judged(self):
        r, why = self.why(self.project_with(0.0, 1.0, "wet.rpp"))
        self.assertNotIn("not judged", why or "")


if __name__ == "__main__":
    unittest.main()
