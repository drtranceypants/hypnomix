"""`hypnomix audit` on a HypnoMix Studio session: the chain read from the saved plug-in controls (ACE EQ's cut bands,
ACE Compressor's Range / Auto Release / Mix, Hypnomix Saturator), bypassed plug-ins, limiters and doubled dynamics,
as for a Live set. A small session fixture, no engine."""
import tempfile
import unittest
from pathlib import Path

from hypnomix.session import audit as AU
from tests.test_ardour_devices3 import comp, ctl, saturator
from tests.test_ardour_groups import SR, region, route


def ace_eq(pid, hp_freq=None, hs=None):
    """An ACE EQ: tone bands off except an optional high shelf (freq, gain); `hp_freq` switches its High Pass on."""
    body = "".join(ctl(f"Filter {k}", 0, 17 + i) for i, k in enumerate(("L", "1", "2", "3", "4")))
    body += ctl("Filter H", 1 if hs else 0, 22)
    if hs:
        body += ctl("Frequency H", hs[0], 14) + ctl("Gain H", hs[1], 15)
    if hp_freq is not None:
        body += ctl("High Pass", 1, 26) + ctl("High Pass Frequency", hp_freq, 27) + ctl("High Pass Slope", 24, 28)
    return f'<Processor id="{pid}" name="ACE EQ" active="1" type="lv2" unique-id="urn:ardour:a-eq"><lv2/>{body}</Processor>'


LIMITER_OFF = ('<Processor id="77" name="Hypnomix Limiter" active="1" type="lv2" unique-id="urn:hypnomix:limiter"><lv2/>'
               + ctl("Enable", 0, 5) + '</Processor>')


def session(lead_procs, bus_procs):
    routes = (route(10, "Master", 0, "MasterOut", outs=None)
              + route(200, "Vocal Bus", 2, "AudioBus", procs=bus_procs)
              + route(100, "Lead Vox", 1, "AudioTrack", outs="Vocal Bus", procs=lead_procs, playlist=901))
    return (f'<?xml version="1.0" encoding="UTF-8"?><Session version="7004" name="Demo" sample-rate="{SR}">'
            f'<Sources><Source name="s1.wav" type="audio" id="601"/></Sources><Routes>{routes}</Routes>'
            f'<Playlists><Playlist id="901" name="p1" type="audio">{region(801, 601, 4.0)}</Playlist></Playlists>'
            f'<TempoMap superclocks-per-second="282240000"><Tempos><Tempo npm="120" enpm="120" note-type="4" '
            f'type="Constant" quarters="0:0" sclock="0"/></Tempos><Meters><Meter divisions-per-bar="4" note-value="4"/>'
            f'</Meters></TempoMap></Session>')


class AuditArdour(unittest.TestCase):
    def audit(self, lead_procs, bus_procs=""):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "Demo"
            d.mkdir()
            (d / "Demo.ardour").write_text(session(lead_procs, bus_procs), encoding="utf-8")
            self.assertTrue(AU._is_ardour(d) and AU._is_ardour(d / "Demo.ardour"))
            return AU.audit(d)

    def test_the_chain_shows_the_new_controls(self):
        chains, flags, nlim = self.audit(
            ace_eq(1, hp_freq=90) + comp(2, extras=dict(rng=3, auto=1, mix=50)) + saturator(3, drive=6, curve=1))
        ch = chains["Lead Vox"]["chain"]
        self.assertEqual(ch[0], "ACE EQ [high pass 90 Hz 24 dB/oct]")
        self.assertEqual(ch[1], "ACE Compressor (stereo) [range 3 dB, auto release, mix 50%]")
        self.assertEqual(ch[2], "Hypnomix Saturator [Analog Clip, drive +6 dB, output +0 dB, mix 100%]")
        self.assertEqual(chains["Lead Vox"]["group"], "Vocal Bus")
        self.assertEqual(nlim, 0)
        self.assertFalse(flags, flags)

    def test_a_session_saved_before_the_new_controls_shows_the_plain_names(self):
        chains, _, _ = self.audit(ace_eq(1) + comp(2))
        self.assertEqual(chains["Lead Vox"]["chain"], ["ACE EQ", "ACE Compressor (stereo)"])

    def test_flags(self):
        chains, flags, nlim = self.audit(ace_eq(1, hp_freq=30, hs=(800, 2)) + comp(2) + LIMITER_OFF, comp(5))
        text = "\n".join(flags)
        self.assertIn("high shelf at 800 Hz", text)
        self.assertIn("high pass at 30 Hz does little", text)
        self.assertIn("bypassed `Hypnomix Limiter`", text)                    # its Enable control is off
        self.assertEqual(nlim, 0)                                              # a bypassed one is not stacked limiting
        self.assertIn("Lead Vox and its group Vocal Bus both run `ACE Compressor`", text)
        self.assertTrue(chains["Lead Vox"]["chain"][-1].endswith("(off)"))

    def test_a_limiter_on_a_track_is_stacked_limiting(self):
        on = LIMITER_OFF.replace('name="Enable" value="0"', 'name="Enable" value="1"')
        _, flags, nlim = self.audit(on)
        self.assertEqual(nlim, 1)
        self.assertTrue(any("Limiting before the master limiter" in f for f in flags), flags)


if __name__ == "__main__":
    unittest.main()
