"""DAW mode: the time signature and track colours read from the saved session file (/api/daw/meta)."""
import tempfile, unittest
from pathlib import Path
from unittest import mock

from hypnomix.app import daw as DW, daw_meta

SESSION = """<?xml version="1.0" encoding="UTF-8"?>
<Session version="7003" name="Song" sample-rate="48000">
  <Routes>
    <Route version="7003" id="23" name="Master">
      <PresentationInfo order="0" flags="MasterOut,OrderSet" color="0"/>
    </Route>
    <Route version="7003" id="149" name="Bass">
      <PresentationInfo order="1" flags="AudioTrack,OrderSet" color="3651572479"/>
    </Route>
  </Routes>
  <TempoMap superclocks-per-second="282240000">
    <Tempos><Tempo npm="92.5" enpm="92.5" note-type="4" type="Constant" sclock="0" quarters="0:0" bbt="1|1|0"/></Tempos>
    <Meters><Meter note-value="8" divisions-per-bar="6" sclock="0" quarters="0:0" bbt="1|1|0"/></Meters>
  </TempoMap>
</Session>
"""


class Meta(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "Song"
        self.dir.mkdir()
        (self.dir / "Song.ardour").write_text(SESSION)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_meter_tempo_and_colours(self):
        m = daw_meta.read(self.dir)                     # a folder works, like --session
        self.assertEqual(m["meter"], [6, 8])
        self.assertEqual(m["tempo"], 92.5)
        self.assertEqual(m["colors"], {"149": "#d9a692"})   # 0xD9A692FF; colour 0 (none chosen) is left out

    def test_route(self):
        with mock.patch.object(DW.ENGINE, "session", str(self.dir / "Song.ardour")), mock.patch.object(DW.ENGINE, "new", None):
            code, body = DW.handle_post("/api/daw/meta", {})
        self.assertEqual(code, 200)
        self.assertEqual(body["meter"], [6, 8])
        with mock.patch.object(DW.ENGINE, "session", None), mock.patch.object(DW.ENGINE, "new", None):
            code, body = DW.handle_post("/api/daw/meta", {})
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
