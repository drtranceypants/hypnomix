"""Regressions: whole-curve automation offset, check on Live-refused automation times, tune splicing."""
import gzip, tempfile, unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from hypnomix.session import automation as aa
from hypnomix.session import check as K
from hypnomix.studio import tune


def env(points):
    ev = "".join(f'<FloatEvent Id="{i}" Time="{t}" Value="{v}"/>' for i, (t, v) in enumerate(points))
    return ET.fromstring(f'<AutomationEnvelope><EnvelopeTarget><PointeeId Value="5"/></EnvelopeTarget>'
                         f'<Automation><Events>{ev}</Events></Automation></AutomationEnvelope>')


class Offset(unittest.TestCase):
    def test_whole_curve_adds_no_edge_points(self):
        root = ET.fromstring('<Ableton><LiveSet><NextPointeeId Value="100"/></LiveSet></Ableton>')
        e = env([(-63072000, 1.0), (8, 0.5)]); root.append(e)
        aa.scale_range(root, e, -6.0, None, None, 0, True)
        _, pts = aa.events(e)
        self.assertEqual([t for t, *_ in pts], [-63072000.0, 8.0])
        self.assertAlmostEqual(pts[1][1], 0.5 * 10 ** (-6 / 20), places=5)

    def test_range_still_gets_its_edges(self):
        root = ET.fromstring('<Ableton><LiveSet><NextPointeeId Value="100"/></LiveSet></Ableton>')
        e = env([(-63072000, 1.0)]); root.append(e)
        aa.scale_range(root, e, -3.0, 4.0, 8.0, 0, True)
        self.assertEqual([t for t, *_ in aa.events(e)[1]], [-63072000.0, 4.0, 8.0])


class CheckTimes(unittest.TestCase):
    def test_point_before_the_default_is_an_error(self):
        x = ('<Ableton Creator="L" MinorVersion="1"><LiveSet><NextPointeeId Value="100"/><Tracks/>'
             '<AudioTrack Id="1"><Volume><AutomationTarget Id="5"/></Volume>'
             '<AutomationEnvelopes><Envelopes><AutomationEnvelope><EnvelopeTarget><PointeeId Value="5"/></EnvelopeTarget>'
             '<Automation><Events><FloatEvent Id="1" Time="-1000000000.0" Value="1"/>'
             '<FloatEvent Id="2" Time="-63072000" Value="1"/></Events></Automation></AutomationEnvelope>'
             '</Envelopes></AutomationEnvelopes></AudioTrack></LiveSet></Ableton>')
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.als"
            with gzip.open(p, "wb") as fh:
                fh.write(x.encode())
            err, _, _ = K.check(p)
            self.assertTrue(any("time Live refuses" in e for e in err), err)


class TuneSplice(unittest.TestCase):
    def test_only_moved_spans_change(self):
        sr = 1000
        out = np.zeros((1000, 1), np.float32)
        new = np.ones((1000, 1), np.float32)
        for a, b in tune.merge_spans([(0.2, 0.3), (0.28, 0.4)]):
            tune.crossfade_in(out, new, int(a * sr), int(b * sr), sr)
        self.assertTrue(np.all(out[:200] == 0) and np.all(out[400:] == 0))
        self.assertTrue(np.all(out[215:385] == 1))


if __name__ == "__main__":
    unittest.main()
