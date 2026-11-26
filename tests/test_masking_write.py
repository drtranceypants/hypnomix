"""An approved masking finding lands as an EQ band in a NEW file: an EQ Eight in a Live set, a ReaEQ in a REAPER project.

Everything is synthetic (sets and projects built in a temp folder). The Live template for a new EQ Eight is a
small stand-in passed in directly (or through HYPNOMIX_EQ8_TEMPLATE for the command line), so the tests don't
need Live installed."""
import base64, gzip, json, math, os, struct, subprocess, sys, tempfile, unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from hypnomix import project as PJ
from hypnomix.engineer import eqband, masking
from hypnomix.project import rpp, rpp_edit as E
from hypnomix.session import check as C


def band_xml(i, on="true", mode=3, freq=1000, gain=0.0, q=0.7071):
    p = lambda name, val: f'<{name}><Manual Value="{val}"/><AutomationTarget Id="0"/><ModulationTarget Id="0"/></{name}>'
    side = ''.join(f'<{n}><Manual Value="0"/></{n}>' for n in ("Freq", "Gain", "Q"))
    return (f'<Bands.{i}><ParameterA>{p("IsOn", on)}{p("Mode", mode)}{p("Freq", freq)}{p("Gain", gain)}{p("Q", q)}</ParameterA>'
            f'<ParameterB>{side}</ParameterB></Bands.{i}>')


def eq8_xml(did=0, bands=None, mode=0, on="true"):
    """A small EQ Eight like the one Live saves: on, plain stereo, eight flat bell bands unless `bands` says."""
    bands = bands or {}
    body = "".join(band_xml(i, **bands.get(i, dict(on="true" if i < 4 else "false", freq=100 * (i + 1)))) for i in range(8))
    return (f'<Eq8 Id="{did}"><On><Manual Value="{on}"/><AutomationTarget Id="0"/></On><Pointee Id="0"/>'
            f'<UserName Value=""/><Mode Value="{mode}"/><SelectedBand Value="2"/>'
            f'<GlobalGain><Manual Value="0"/><AutomationTarget Id="0"/></GlobalGain>'
            f'<Scale><Manual Value="1"/><AutomationTarget Id="0"/></Scale>{body}</Eq8>')


TEMPLATE = ET.fromstring(eq8_xml())


def track_xml(tid, name, devices="", base=100, envelopes=""):
    mixer = (f'<Mixer><Volume><Manual Value="1"/><AutomationTarget Id="{base}"/></Volume>'
             f'<Pan><Manual Value="0"/><AutomationTarget Id="{base + 1}"/></Pan>'
             f'<Speaker><Manual Value="true"/><AutomationTarget Id="{base + 2}"/></Speaker><Sends/></Mixer>')
    return (f'<AudioTrack Id="{tid}"><Name><EffectiveName Value="{name}"/></Name>'
            f'<AutomationEnvelopes><Envelopes>{envelopes}</Envelopes></AutomationEnvelopes>'
            f'<DeviceChain>{mixer}<MainSequencer><Sample><ArrangerAutomation><Events/></ArrangerAutomation></Sample></MainSequencer>'
            f'<DeviceChain><Devices>{devices}</Devices></DeviceChain></DeviceChain></AudioTrack>')


def write_set(path, tracks):
    xml = ('<?xml version="1.0" encoding="UTF-8"?><Ableton MajorVersion="5" MinorVersion="12.0_12049" Creator="Ableton Live 12.0">'
           f'<LiveSet><NextPointeeId Value="1000"/><Tracks>{"".join(tracks)}</Tracks>'
           '<MainTrack><Name><EffectiveName Value="Main"/></Name><AutomationEnvelopes><Envelopes/></AutomationEnvelopes>'
           '<DeviceChain><Mixer><Volume><Manual Value="1"/><AutomationTarget Id="30"/></Volume>'
           '<Pan><Manual Value="0"/><AutomationTarget Id="31"/></Pan><Speaker><Manual Value="true"/>'
           '<AutomationTarget Id="32"/></Speaker><Sends/></Mixer><Mixer2/><DeviceChain><Devices/></DeviceChain></DeviceChain>'
           '<Tempo><Manual Value="120"/></Tempo></MainTrack></LiveSet></Ableton>')
    with gzip.open(path, "wb") as f:
        f.write(xml.encode())
    return path


def devices_of(root, name):
    t = next(t for t in root.find(".//Tracks") if t.find("./Name/EffectiveName").get("Value") == name)
    return t, list(t.find("./DeviceChain/DeviceChain/Devices"))


def load(path):
    return ET.fromstring(gzip.open(path).read())


class LiveCut(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())

    def test_a_new_eq_eight_goes_at_the_end_with_one_band(self):
        src = write_set(self.td / "Song.als", [track_xml(1, "Keys", '<Saturator Id="0"/>', 100), track_xml(2, "Pad", "", 200)])
        out = self.td / "Song (cut).als"
        items = [dict(id="mask-1", track="Keys", eq=dict(freq=250.0, gain_db=-3.0, q=1.4, keep="Pad"))]
        lines, skipped, done = masking.write_set(src, out, items, 1.0, TEMPLATE)
        self.assertEqual(done, ["mask-1"], skipped)
        root = load(out)
        t, devs = devices_of(root, "Keys")
        self.assertEqual([d.tag for d in devs], ["Saturator", "Eq8"])           # at the END of the chain
        eq = devs[-1]
        self.assertEqual(eq.find("./UserName").get("Value"), eqband.DEVICE_NAME)
        b = eqband.band_info(eqband.band_a(eq, 1))
        self.assertEqual((b["on"], b["mode"], b["freq"], b["gain"], b["q"]), (True, 3, 250.0, -3.0, 1.4))
        for i in (0, 2, 3):                                                      # every other band still flat
            self.assertEqual(eqband.band_info(eqband.band_a(eq, i))["gain"], 0.0)
        self.assertEqual(devices_of(root, "Pad")[1], [])                         # the other part is untouched
        errs, _, _ = C.check(out, src)
        self.assertEqual(errs, [], errs)                                         # ids unique, below NextPointeeId
        self.assertEqual(load(src).find(".//NextPointeeId").get("Value"), "1000")  # the original is as it was

    def test_the_amount_scales_the_cut(self):
        src = write_set(self.td / "Song.als", [track_xml(1, "Keys", "", 100)])
        out = self.td / "Song (half).als"
        items = [dict(id="mask-1", track="Keys", eq=dict(freq=250.0, gain_db=-3.0, q=1.4, keep="Pad"))]
        masking.write_set(src, out, items, 0.5, TEMPLATE)
        eq = devices_of(load(out), "Keys")[1][0]
        self.assertAlmostEqual(eqband.band_info(eqband.band_a(eq, 1))["gain"], -1.5)

    def test_an_eq_eight_already_there_is_reused_through_a_free_band(self):
        mine = eq8_xml(3, {0: dict(on="true", mode=1, freq=80, gain=0.0), 1: dict(on="true", mode=3, freq=300, gain=-4.0),
                           2: dict(on="true", mode=3, freq=1000, gain=2.0), 3: dict(on="false", mode=3, freq=2000)})
        src = write_set(self.td / "Song.als", [track_xml(1, "Keys", mine, 100)])
        out = self.td / "Song (cut).als"
        items = [dict(id="mask-1", track="Keys", eq=dict(freq=2500.0, gain_db=-2.0, q=1.4, keep="Pad"))]
        masking.write_set(src, out, items, 1.0, TEMPLATE)
        t, devs = devices_of(load(out), "Keys")
        self.assertEqual(len(devs), 1)                                           # no second EQ Eight
        got = [eqband.band_info(eqband.band_a(devs[0], i)) for i in range(4)]
        self.assertEqual((got[0]["mode"], got[1]["gain"], got[2]["gain"]), (1, -4.0, 2.0))   # the person's bands are as they were
        self.assertEqual((got[3]["on"], got[3]["freq"], got[3]["gain"]), (True, 2500.0, -2.0))

    def test_no_free_band_means_a_new_eq_eight(self):
        full = eq8_xml(3, {i: dict(on="true", mode=3, freq=100 * (i + 1), gain=-1.0) for i in range(8)})
        src = write_set(self.td / "Song.als", [track_xml(1, "Keys", full, 100)])
        out = self.td / "Song (cut).als"
        masking.write_set(src, out, [dict(id="m", track="Keys", eq=dict(freq=250.0, gain_db=-2.0, q=1.0, keep="Pad"))], 1.0, TEMPLATE)
        self.assertEqual([d.tag for d in devices_of(load(out), "Keys")[1]], ["Eq8", "Eq8"])

    def test_an_automated_band_is_never_taken(self):
        mine = eq8_xml(3, {0: dict(on="false", mode=3, freq=100)})
        root = ET.fromstring(mine)
        tid = eqband.band_a(root, 0).find("./Freq/AutomationTarget")
        env = '<AutomationEnvelope Id="0"><EnvelopeTarget><PointeeId Value="777"/></EnvelopeTarget><Automation><Events/></Automation></AutomationEnvelope>'
        mine = mine.replace('<Bands.0><ParameterA><IsOn><Manual Value="false"/><AutomationTarget Id="0"/><ModulationTarget Id="0"/></IsOn>',
                            '<Bands.0><ParameterA><IsOn><Manual Value="false"/><AutomationTarget Id="777"/><ModulationTarget Id="0"/></IsOn>')
        self.assertIn('Id="777"', mine)
        src = write_set(self.td / "Song.als", [track_xml(1, "Keys", mine, 100, env)])
        out = self.td / "Song (cut).als"
        masking.write_set(src, out, [dict(id="m", track="Keys", eq=dict(freq=250.0, gain_db=-2.0, q=1.0, keep="Pad"))], 1.0, TEMPLATE)
        eq = devices_of(load(out), "Keys")[1][0]
        self.assertEqual(eqband.band_info(eqband.band_a(eq, 0))["freq"], 100.0)      # not repurposed
        self.assertNotEqual(eqband.band_info(eqband.band_a(eq, 0))["gain"], -2.0)

    def test_a_cut_that_is_already_there_is_left_alone(self):
        mine = eq8_xml(3, {1: dict(on="true", mode=3, freq=260, gain=-3.0)})
        src = write_set(self.td / "Song.als", [track_xml(1, "Keys", mine, 100)])
        out = self.td / "Song (cut).als"
        lines, skipped, done = masking.write_set(src, out, [dict(id="m", track="Keys", eq=dict(freq=250.0, gain_db=-2.0, q=1.4, keep="Pad"))],
                                                 1.0, TEMPLATE)
        self.assertEqual(done, [])
        self.assertIn("already there", skipped[0][1])
        self.assertFalse(out.exists())

    def test_an_eq_eight_in_ms_mode_or_off_is_not_reused(self):
        for kw in (dict(mode=2), dict(on="false")):
            src = write_set(self.td / f"S{len(kw)}{list(kw.values())[0]}.als", [track_xml(1, "Keys", eq8_xml(3, **kw), 100)])
            out = src.with_name(src.stem + " (cut).als")
            masking.write_set(src, out, [dict(id="m", track="Keys", eq=dict(freq=250.0, gain_db=-2.0, q=1.0, keep="Pad"))], 1.0, TEMPLATE)
            self.assertEqual([d.tag for d in devices_of(load(out), "Keys")[1]], ["Eq8", "Eq8"])

    def test_names_with_slashes_and_missing_tracks(self):
        src = write_set(self.td / "Song.als", [track_xml(1, "Gtr A/B", "", 100)])
        out = self.td / "Song (cut).als"
        eq = dict(freq=250.0, gain_db=-2.0, q=1.0, keep="x")
        lines, skipped, done = masking.write_set(src, out, [dict(id="a", track="Gtr A-B", eq=eq), dict(id="b", track="Nope", eq=eq)], 1.0, TEMPLATE)
        self.assertEqual(done, ["a"])
        self.assertIn("no audio track called 'Nope'", skipped[0][1])

    def test_the_command_line_refuses_to_overwrite(self):
        src = write_set(self.td / "Song.als", [track_xml(1, "Keys", "", 100)])
        fj = self.td / "findings.json"
        fj.write_text(json.dumps(dict(findings=[dict(id="mask-1", tool="masking", track="Keys",
                                                     eq=dict(freq=250.0, gain_db=-2.0, q=1.0, keep="Pad"))])))
        r = subprocess.run([sys.executable, "-m", "hypnomix.cli", "masking", str(src), "--apply", str(src), "--findings", str(fj),
                            "--ids", "mask-1"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("overwrite", r.stdout + r.stderr)


# ---------------------------------------------------------------- REAPER
# The ReaEQ chunk below is what REAPER 7.86 saved (three base64 parts): bands high pass 25 Hz, low shelf 90 Hz,
# bell 300 Hz, bell 3000 Hz, high shelf 10 kHz, the bells and shelves at about 0 dB.
REAEQ_LINES = [
    "cWVlcu5e7f4CAAAAAQAAAAAAAAACAAAAAAAAAAIAAAABAAAAAAAAAAIAAAAAAAAAzQAAAAEAAAAAABAA",
    "IQAAAAUAAAAEAAAAAQAAAJhGtjUz8zhAAAAAAAAA8D8AAACA61H+PwEAAAAAAQAAAOg7L/fMfFZAAAAAoPrQ7z8AAACA61H+PwEIAAAAAQAAAFGOv2Mzv3JAAAAAoPrQ7z8AAAAgXI/4PwEIAAAAAQAAAFHs/LTmb6dAAAAAoPrQ7z8AAAAgXI/4PwEBAAAAAQAAAApzRer5h8NAAAAAoPrQ7z8AAACA61H+PwEBAAAAAQAAAAAAAAAAAPA/AAAAAAAAAAAAAAAAAgABAA==",
    "AAAQAAAA",
]


def rpp_text(tracks):
    return ('<REAPER_PROJECT 0.1 "7.86/macOS-arm64" 1\n  TEMPO 120 4 4\n' + "".join(tracks) + '>\n')


def rtrack(guid, name, fx="", fxline="    FX 1\n", item=False):
    items = ('    <ITEM\n      POSITION 0\n      LENGTH 4\n      IGUID {AAAAAAAA-0000-0000-0000-000000000001}\n'
             '      <SOURCE WAVE\n        FILE "x.wav"\n      >\n    >\n') if item else ""
    return f'  <TRACK {guid}\n    NAME {name}\n    ISBUS 0 0\n{fxline}{fx}{items}  >\n'


def reaeq_chain(lines=REAEQ_LINES, bypass="0 0 0"):
    body = "".join(f"          {l}\n" for l in lines)
    return ('    <FXCHAIN\n      SHOW 0\n      BYPASS ' + bypass + '\n'
            '      <VST "VST: ReaEQ (Cockos)" reaeq.vst.dylib 0 "" 1919247729<56535472656571726561657100000000> ""\n'
            + body + '      >\n      FLOATPOS 0 0 0 0\n      FXID {11111111-1111-1111-1111-111111111111}\n      WAK 0 0\n    >\n')


class ReaperCut(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())

    def project(self, tracks, name="Song.rpp"):
        p = self.td / name
        p.write_text(rpp_text(tracks))
        return PJ.load(p), p

    def reaeqs(self, project_path, track):
        p = PJ.load(project_path)
        t = next(t for t in p.tracks if t.name == track)
        chain = t.native.chunk("FXCHAIN")
        return t, ([E.ReaEQ(c) for c in chain.chunks("VST") if E._is_reaeq(c)] if chain is not None else [])

    def test_state_decoding_matches_what_reaper_saved(self):
        p, path = self.project([rtrack("{A1}", "Keys", reaeq_chain())])
        t, eqs = self.reaeqs(path, "Keys")
        self.assertEqual([b["type"] for b in eqs[0].bands], [4, 0, 8, 8, 1])
        self.assertAlmostEqual(eqs[0].bands[0]["freq"], 24.95, places=1)
        head, state, tail = eqs[0].blob()                                     # writing it back is byte for byte
        self.assertEqual(base64.b64encode(head).decode(), REAEQ_LINES[0])
        self.assertEqual(base64.b64encode(state).decode(), REAEQ_LINES[1])
        self.assertEqual(base64.b64encode(tail).decode(), REAEQ_LINES[2])

    def test_a_new_reaeq_with_one_band_on_a_track_without_fx(self):
        p, path = self.project([rtrack("{A1}", "Keys", item=True), rtrack("{A2}", "Pad")])
        tr = next(t for t in p.tracks if t.name == "Keys")
        msg, why = E.add_reaeq_cut(tr, 250.0, -3.0, 1.4)
        self.assertIsNone(why)
        out = self.td / "Song (cut).rpp"
        E.save(p, out)
        self.assertEqual(E.check(path, out), [])
        t, eqs = self.reaeqs(out, "Keys")
        self.assertEqual(len(eqs), 1)
        b = eqs[0].bands
        self.assertEqual((len(b), b[0]["type"], b[0]["on"]), (1, 8, True))
        self.assertAlmostEqual(b[0]["freq"], 250.0)
        self.assertAlmostEqual(eqs[0].gain_db(b[0]), -3.0, places=6)
        self.assertAlmostEqual(b[0]["bw"], 2 / math.log(2) * math.asinh(1 / 2.8), places=2)    # Q 1.4 as octaves
        self.assertEqual(self.reaeqs(out, "Pad")[1], [])
        text = out.read_text()
        self.assertLess(text.index("<FXCHAIN"), text.index("<ITEM"))          # before the items, like REAPER writes it
        self.assertEqual(sum(1 for l in text.splitlines() if l.strip().startswith("<")),
                         sum(1 for l in text.splitlines() if l.strip() == ">"))

    def test_the_new_reaeq_goes_at_the_end_of_an_existing_chain(self):
        other = ('    <FXCHAIN\n      SHOW 0\n      BYPASS 0 0 0\n      <JS "loser/3BandEQ" ""\n        0 200 2000\n      >\n'
                 '      FXID {22222222-2222-2222-2222-222222222222}\n    >\n')
        p, path = self.project([rtrack("{A1}", "Keys", other, item=True)])
        msg, why = E.add_reaeq_cut(p.tracks[0], 250.0, -3.0, 1.4)
        self.assertIsNone(why)
        out = self.td / "Song (cut).rpp"
        E.save(p, out)
        devs = PJ.load(out).tracks[0].devices
        self.assertEqual([d.name for d in devs], ["3BandEQ", "ReaEQ (Cockos)"])

    def test_an_existing_reaeq_gives_up_a_flat_band_and_nothing_else_changes(self):
        p, path = self.project([rtrack("{A1}", "Keys", reaeq_chain(), item=True)])
        msg, why = E.add_reaeq_cut(p.tracks[0], 2500.0, -2.0, 1.0)
        self.assertIsNone(why, why)
        out = self.td / "Song (cut).rpp"
        E.save(p, out)
        t, eqs = self.reaeqs(out, "Keys")
        self.assertEqual(len(eqs), 1)
        old = self.reaeqs(path, "Keys")[1][0].bands
        new = eqs[0].bands
        self.assertEqual(len(new), 5)
        same = [i for i in range(5) if new[i] == old[i]]
        self.assertEqual(len(same), 4)                                         # one band became the cut
        cut = next(b for i, b in enumerate(new) if b != old[i])
        self.assertAlmostEqual(cut["freq"], 2500.0)
        self.assertAlmostEqual(eqs[0].gain_db(cut), -2.0, places=6)

    def test_a_full_or_bypassed_reaeq_is_not_reused(self):
        p, path = self.project([rtrack("{A1}", "Keys", reaeq_chain(bypass="1 0 0"), item=True)])
        E.add_reaeq_cut(p.tracks[0], 2500.0, -2.0, 1.0)
        out = self.td / "Song (cut).rpp"
        E.save(p, out)
        self.assertEqual(len(self.reaeqs(out, "Keys")[1]), 2)                  # a second ReaEQ, the bypassed one untouched
        self.assertEqual(len(self.reaeqs(out, "Keys")[1][0].bands), 5)

    def test_a_cut_that_is_already_there_and_a_chain_switched_off(self):
        p, path = self.project([rtrack("{A1}", "Keys", item=True)])
        E.add_reaeq_cut(p.tracks[0], 250.0, -3.0, 1.4)
        msg, why = E.add_reaeq_cut(p.tracks[0], 255.0, -2.0, 1.4)
        self.assertIsNone(msg)
        self.assertIn("already there", why)
        p2, _ = self.project([rtrack("{A1}", "Keys", fxline="    FX 0\n")], "Off.rpp")
        msg, why = E.add_reaeq_cut(p2.tracks[0], 250.0, -3.0, 1.4)
        self.assertIsNone(msg)
        self.assertIn("switched off", why)

    def test_the_command_writes_a_new_project_and_refuses_the_original(self):
        p, path = self.project([rtrack("{A1}", "Keys", item=True), rtrack("{A2}", "Pad")])
        fj = self.td / "findings.json"
        fj.write_text(json.dumps(dict(findings=[dict(id="mask-1", tool="masking", track="Keys",
                                                     eq=dict(freq=250.0, gain_db=-3.0, q=1.4, keep="Pad"))])))
        out = self.td / "Song (cut).rpp"
        args = [sys.executable, "-m", "hypnomix.cli", "masking", str(path), "--findings", str(fj), "--ids", "mask-1"]
        r = subprocess.run(args + ["--apply", str(out), "--scale", "0.5"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        t, eqs = self.reaeqs(out, "Keys")
        self.assertAlmostEqual(eqs[0].gain_db(eqs[0].bands[0]), -1.5, places=6)
        r = subprocess.run(args + ["--apply", str(path)], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)


# ---------------------------------------------------------------- through scan findings and `fix`
def scan_dir(td, src, findings, protected=False):
    sd = Path(td) / "scan"
    sd.mkdir()
    for k, f in enumerate(findings, 1):
        f.setdefault("n", k)
    (sd / "findings.json").write_text(json.dumps(dict(set=str(src), findings=findings)))
    (sd / "scan.json").write_text(json.dumps(dict(mode="set", set_mtime=Path(src).stat().st_mtime)))
    return sd


def fix(*args, env=None):
    e = dict(os.environ)
    e.update(env or {})
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", "fix", *map(str, args)], capture_output=True, text=True, env=e)
    return r.returncode, r.stdout + r.stderr


class ThroughFix(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.tpl = self.td / "eq8.xml"
        self.tpl.write_text(eq8_xml())
        self.env = {"HYPNOMIX_EQ8_TEMPLATE": str(self.tpl), "HYPNOMIX_HOME": str(self.td / "home")}

    def finding(self, **kw):
        f = dict(id="mask-1", tool="masking", kind="masking", severity="medium", track="Keys", where="250 Hz", applies="set",
                 problem="fights with 'Pad' in 160-315 Hz", fix="cut it",
                 eq=dict(freq=250.0, gain_db=-3.0, q=1.4, keep="Pad", band=2, band_name="160-315 Hz"))
        f.update(kw)
        return f

    def test_live_an_approved_finding_lands_as_an_eq_band_in_a_new_set(self):
        src = write_set(self.td / "Song.als", [track_xml(1, "Keys", "", 100), track_xml(2, "Pad", "", 200)])
        sd = scan_dir(self.td, src, [self.finding()])
        out = self.td / "Song (fixed).als"
        code, txt = fix(sd, "--approve", "mask-1", "--out", out, env=self.env)
        self.assertEqual(code, 0, txt)
        t, devs = devices_of(load(out), "Keys")
        self.assertEqual([d.tag for d in devs], ["Eq8"])
        self.assertAlmostEqual(eqband.band_info(eqband.band_a(devs[0], 1))["gain"], -3.0)
        self.assertEqual(C.check(out, src)[0], [])
        self.assertIn("masking", txt)

    def test_live_the_decision_amount_scales_the_cut(self):
        src = write_set(self.td / "Song.als", [track_xml(1, "Keys", "", 100)])
        sd = scan_dir(self.td, src, [self.finding()])
        self.assertEqual(fix(sd, "--decide", "mask-1=approve@50", env=self.env)[0], 0)
        out = self.td / "Song (fixed).als"
        code, txt = fix(sd, "--approved", "--out", out, env=self.env)
        self.assertEqual(code, 0, txt)
        eq = devices_of(load(out), "Keys")[1][0]
        self.assertAlmostEqual(eqband.band_info(eqband.band_a(eq, 1))["gain"], -1.5)

    def test_live_a_protected_track_is_not_touched_without_the_flag(self):
        src = write_set(self.td / "Song.als", [track_xml(1, "Keys", "", 100)])
        sd = scan_dir(self.td, src, [self.finding(protected=True)])
        out = self.td / "Song (fixed).als"
        code, txt = fix(sd, "--approve", "mask-1", "--out", out, env=self.env)
        self.assertNotEqual(code, 0)
        self.assertIn("protected", txt)
        self.assertFalse(out.exists())
        code, txt = fix(sd, "--approve", "mask-1", "--out", out, "--allow-protected", env=self.env)
        self.assertEqual(code, 0, txt)
        self.assertTrue(out.exists())

    def test_live_a_cut_that_is_already_there_is_skipped_not_failed(self):
        mine = eq8_xml(3, {1: dict(on="true", mode=3, freq=250, gain=-3.0)})
        src = write_set(self.td / "Song.als", [track_xml(1, "Keys", mine, 100)])
        sd = scan_dir(self.td, src, [self.finding()])
        out = self.td / "Song (fixed).als"
        code, txt = fix(sd, "--approve", "mask-1", "--out", out, env=self.env)
        self.assertFalse(out.exists())
        self.assertNotIn("FAILED", txt.replace("FAILED (", "x"), txt)

    def test_reaper_an_approved_finding_lands_as_a_reaeq_band_in_a_new_project(self):
        path = self.td / "Song.rpp"
        path.write_text(rpp_text([rtrack("{A1}", "Keys", item=True), rtrack("{A2}", "Pad")]))
        f = self.finding(edit=dict(op="masking"))
        sd = scan_dir(self.td, path, [f])
        (sd / "scan.json").write_text(json.dumps(dict(mode="set", set_mtime=path.stat().st_mtime)))
        out = self.td / "Song (fixed).rpp"
        code, txt = fix(sd, "--decide", "mask-1=approve@50", env=self.env)
        code, txt = fix(sd, "--approved", "--out", out, env=self.env)
        self.assertEqual(code, 0, txt)
        eqs = ReaperCut.reaeqs(self, out, "Keys")[1]
        self.assertAlmostEqual(eqs[0].gain_db(eqs[0].bands[0]), -1.5, places=6)
        self.assertEqual(PJ.load(path).tracks[0].devices, [])                  # the original project is as it was


if __name__ == "__main__":
    unittest.main()
