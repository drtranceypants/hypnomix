"""Group tracks and sidechains in HypnoMix Studio sessions: the reader sees sidechain feeds and route
groups, `tidy` / `order` plan group tracks and write the approved ones over MCP (here a fake engine), and the
sidechain and duck checks run on an ACE Compressor keyed from another track."""
import io
import json
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from hypnomix import project
from hypnomix.engineer import duck_ardour as DA
from hypnomix.project import ardour_groups as AG
from hypnomix.workflow import sidechain_project as SCP

SR = 48000
SC = 282240000


def a(sec):
    return f"a{int(round(sec * SC))}"


def region(rid, src, secs):
    return (f'<Region name="r{rid}" id="{rid}" type="audio" muted="0" opaque="1" length="{a(secs)}@{a(0)}" '
            f'start="{a(0)}" layering-index="0" scale-amplitude="1" source-0="{src}" master-source-0="{src}"/>')


def route(rid, name, order, flags, outs="Master", procs="", extra="", playlist=None, active="1"):
    pl = f' audio-playlist="{playlist}"' if playlist else ""
    io = ""
    if outs:
        io = (f'<IO name="{name}" id="{rid}1" direction="Output" default-type="audio">'
              f'<Port type="audio" name="{name}/audio_out 1"><Connection other="{outs}/audio_in 1"/></Port>'
              f'<Port type="audio" name="{name}/audio_out 2"><Connection other="{outs}/audio_in 2"/></Port></IO>')
    return (f'<Route version="7004" id="{rid}" name="{name}" default-type="audio" active="{active}"{pl}>'
            f'<PresentationInfo order="{order}" flags="{flags},OrderSet"/>{io}{extra}{procs}'
            f'<Processor id="{rid}9" name="Amp" active="1" type="amp"><Controllable name="gaincontrol" value="1"/></Processor>'
            f'</Route>')


ACE = ('<Processor id="1501" name="ACE Compressor (stereo)" active="1" type="lv2" unique-id="urn:ardour:a-comp#stereo">'
       '<lv2/><Controllable name="Attack" value="2" parameter="0"/><Controllable name="Release" value="80" parameter="1"/>'
       '<Controllable name="Knee" value="0" parameter="2"/><Controllable name="Ratio" value="10" parameter="3"/>'
       '<Controllable name="Threshold" value="-40" parameter="4"/><Controllable name="Makeup" value="0" parameter="5"/>'
       '<Controllable name="Sidechain" value="1" parameter="9"/><Controllable name="Enable" value="1" parameter="10"/>'
       '<Processor id="1502" name="ACE Compressor (stereo)" active="1" type="sidechain">'
       '<IO name="Bass/ACE Compressor (stereo)" id="1503" direction="Input" default-type="audio">'
       '<Port type="audio" name="Bass/ACE Compressor (stereo)/audio_in 1"><Connection other="Drums/send 1/audio_out 1"/>'
       '<Connection other="Drums/send 1/audio_out 2"/></Port></IO></Processor></Processor>')
SEND = ('<Processor id="2501" name="send 1" active="1" type="send" selfdestruct="1">'
        '<IO name="Drums/send 1" id="2502" direction="Output" default-type="audio">'
        '<Port type="audio" name="Drums/send 1/audio_out 1"><Connection other="Bass/ACE Compressor (stereo)/audio_in 1"/></Port>'
        '<Port type="audio" name="Drums/send 1/audio_out 2"><Connection other="Bass/ACE Compressor (stereo)/audio_in 1"/></Port></IO>'
        '<Processor id="2503" name="Amp" active="1" type="amp"><Controllable name="gaincontrol" value="0.5"/></Processor>'
        '</Processor>')
INTSEND = ('<Processor id="4501" name="Reverb" active="1" type="intsend" target="700">'
           '<Processor id="4502" name="Amp" active="1" type="amp"><Controllable name="gaincontrol" value="0.5"/></Processor>'
           '</Processor>')


def session(groups=""):
    routes = "".join([
        route(10, "Master", 0, "MasterOut", outs=None),
        route(100, "Kick", 1, "AudioTrack", playlist=901),
        route(110, "Snare", 2, "AudioTrack", playlist=902),
        route(150, "Bass", 3, "AudioTrack", procs=ACE, playlist=903),
        route(250, "Drums", 4, "AudioTrack", procs=SEND, playlist=904),
        route(350, "Lead Vocal", 5, "AudioTrack", procs=INTSEND, playlist=905),
        route(450, "Old Vox", 6, "AudioTrack", playlist=906, active="0"),
        route(550, "Keys", 7, "AudioTrack", outs="Synths", playlist=907),
        route(560, "Synths", 8, "AudioBus"),
        route(700, "Reverb", 9, "AudioBus", procs='<Processor id="7001" name="ACE Reverb" active="1" type="lv2" '
                                                  'unique-id="urn:ardour:a-reverb"/>'),
    ])
    pls = "".join(f'<Playlist id="{900 + i}" name="p{i}" type="audio">{region(800 + i, 600 + i, 8.0)}</Playlist>'
                  for i in range(1, 8))
    srcs = "".join(f'<Source name="s{i}.wav" type="audio" id="{600 + i}"/>' for i in range(1, 8))
    return (f'<?xml version="1.0" encoding="UTF-8"?><Session version="7004" name="Song" sample-rate="{SR}">'
            f'<Sources>{srcs}</Sources><Routes>{routes}</Routes><Playlists>{pls}</Playlists>'
            f'<RouteGroups>{groups}</RouteGroups>'
            f'<TempoMap superclocks-per-second="{SC}"><Tempos><Tempo npm="120" enpm="120" note-type="4" type="Constant" '
            f'quarters="0:0" sclock="0"/></Tempos><Meters><Meter divisions-per-bar="4" note-value="4"/></Meters></TempoMap>'
            f'</Session>')


def write_audio(d):
    """Kick/Snare/Drums: a hit every half second; Bass: a 55 Hz tone; the vocal: phrases with gaps."""
    t = np.arange(int(8 * SR)) / SR
    hits = np.zeros_like(t)
    for k in range(16):
        i = int(k * 0.5 * SR)
        n = int(0.08 * SR)
        hits[i:i + n] += np.exp(-np.arange(n) / (0.015 * SR)) * np.sin(2 * np.pi * 60 * np.arange(n) / SR)
    bass = 0.3 * np.sin(2 * np.pi * 55 * t)
    voc = 0.3 * np.sin(2 * np.pi * 220 * t) * ((t % 2.0) < 1.4)
    audio = d / "interchange" / "Song" / "audiofiles"
    audio.mkdir(parents=True)
    for i, y in enumerate([hits, hits, bass, hits, voc, voc, bass], 1):
        sf.write(audio / f"s{i}.wav", 0.8 * y, SR)


class Fixture(unittest.TestCase):
    groups = ""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.dir = Path(self.td.name) / "Song"
        self.dir.mkdir()
        write_audio(self.dir)
        (self.dir / "Song.ardour").write_text(session(self.groups), encoding="utf-8")
        self.p = project.load(self.dir)

    def tearDown(self):
        self.td.cleanup()


class ReaderTest(Fixture):
    groups = ('<RouteGroup id="5000" rgba="0" name="Synths" subgroup-bus="560" routes="550 " active="1" relative="1" '
              'hidden="1" gain="0" mute="1" solo="0" recenable="0" select="1" route-active="0" color="0" monitoring="0"/>')

    def test_sidechain_feed_is_read_through_the_ports(self):
        bass = self.p.track("Bass")
        d = bass.devices[0]
        self.assertEqual(d.uid, "urn:ardour:a-comp#stereo")
        self.assertEqual(d.sidechain, ["Drums"])
        self.assertEqual(d.sidechain_tap, "pre_fader")                 # the send sits before Drums' fader
        self.assertEqual(d.sidechain_feeds, [("Drums", "pre_fader", 0.5)])
        self.assertEqual(self.p.track("Kick").devices, [])

    def test_route_groups_with_their_bus(self):
        g = self.p.groups[0]
        self.assertEqual((g.name, g.id, g.bus.name), ("Synths", "5000", "Synths"))
        self.assertEqual([t.name for t in g.members], ["Keys"])
        self.assertTrue(g.folded)
        self.assertTrue(g.shares["mute"] and not g.shares["gain"])
        self.assertEqual(self.p.track("Keys").group, "Synths")
        self.assertIs(self.p.track("Keys").parent, g.bus)               # routed into the bus
        self.assertEqual(self.p.track("Bass").route_id, "150")
        self.assertFalse(self.p.track("Old Vox").active)


class PlanTest(Fixture):
    def test_tidy_groups_the_switched_off_tracks(self):
        plans = AG.plan_old_takes(self.p)
        self.assertEqual(plans, [dict(op="create", group="Old takes", tracks=["Old Vox"], fold=True, why="switched off",
                                      mixed=False)])
        fs = AG.findings(plans, "tidy")
        self.assertEqual((fs[0]["id"], fs[0]["kind"], fs[0]["applies"]), ("group-1", "group-old", "engine"))
        self.assertIn("folded", fs[0]["fix"])

    def test_order_groups_one_family_and_leaves_bused_tracks_alone(self):
        plans = AG.plan_families(self.p)
        made = {pl["group"]: pl["tracks"] for pl in plans}
        self.assertEqual(made, {"Drums": ["Kick", "Snare", "Drums"]})   # Keys sits in a bus: left alone
        self.assertNotIn("Old Vox", sum(made.values(), []))           # switched off: tidy's business
        labels = {"Bass": dict(label="Bass", confidence=0.9), "Lead Vocal": dict(label="Lead Vocal", confidence=0.9),
                  "Kick": dict(label="Kick", confidence=0.9), "Snare": dict(label="Snare", confidence=0.2)}
        made = {pl["group"]: pl["tracks"] for pl in AG.plan_families(self.p, labels)}
        self.assertEqual(made, {"Drums": ["Kick", "Drums"]})            # an unsure label is not grouped

    def test_one_more_of_a_grouped_family_joins_it(self):
        self.p.groups.append(project.model.Group(name="Drums", id="77"))
        plans = AG.plan_families(self.p)
        self.assertEqual(plans[0]["op"], "add")
        self.assertEqual(plans[0]["group_id"], "77")

    def test_the_planned_group_is_the_one_with_that_name(self):
        self.p.groups[:0] = [project.model.Group(name="Keys", id="70")]      # another name first: not taken
        self.p.groups.append(project.model.Group(name="Drums", id="77"))
        self.assertEqual(AG.plan_families(self.p)[0]["group_id"], "77")
        self.p.groups.append(project.model.Group(name="Old takes", id="88"))
        self.assertEqual(AG.plan_old_takes(self.p)[0], dict(op="add", group="Old takes", group_id="88", tracks=["Old Vox"],
                                                            why="switched off"))

    def test_family_from_the_track_name(self):
        T = lambda n: project.model.Track(n, 0)
        table = {"Kick": 0, "Kick In": 0, "Bass Drum": 0, "Snare Top": 0, "Tom 1": 0, "Hi-Hat": 0, "Hats": 0,
                 "Overhead L": 0, "Drum Kit": 0, "Drum Bus": 0, "Drums": 0, "Toms": 0, "Bass": 1, "Bass Guitar": 1,
                 "Synth Bass": 1, "Bass DI": 1, "Keys": 2, "Lead Guitar": 2, "Piano 2": 2, "Lead Vocal": 3, "Vox Double": 3,
                 "Backing Vocals": 3, "Harmonies": 3, "Kick Sub": 0, "Bass Synth": 1, "Strings": 4, "Cello": 4, "Click": None, "Lead": None, "FX Riser": None}
        got = {n: AG.family_of(T(n)) for n in table}
        self.assertEqual(got, table)
        plans = AG.plan_families(SimpleNamespace(tracks=[T("Bass Drum"), T("Bass"), T("Snare")], groups=[]))
        self.assertEqual({pl["group"]: pl["tracks"] for pl in plans}, {"Drums": ["Bass Drum", "Snare"]})


REAL_TOOLS = {t["name"] for t in json.loads((Path(__file__).parent / "data" / "engine_tools_shape.json").read_text(encoding="utf-8"))["tools"]}
LABELS = ["Attack", "Release", "Knee", "Ratio", "Threshold"]


class FakeEngine:
    """A tiny MCP surface: records every tools/call and answers like the HypnoMix engine. A tool the real engine
    does not have is refused, as the engine refuses it. Plug-ins hold their parameters ({track id: [plug-in]})."""

    def __init__(self, tracks, labels=LABELS, session=None):
        self.calls, self.groups, self.plugins = [], [], {}
        self.tracks = tracks
        self.labels = list(labels)
        self.session, self.dirty = session, False        # the file session_list_snapshots names as current
        eng = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if body["method"] == "tools/list":
                    names = ["tracks_list", "group_create", "group_add", "group_set", "group_list", "session_get_info",
                             "plugin_set_sidechain", "plugin_get_sidechain"]
                    res = {"tools": [{"name": n} for n in names]}
                else:
                    n, args = body["params"]["name"], body["params"]["arguments"]
                    eng.calls.append((n, args))
                    res = {"structuredContent": eng.answer(n, args)} if n in REAL_TOOLS else None
                out = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": res} if res is not None else
                                 {"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32602, "message": f"Unknown tool: {n}"}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}/mcp"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def answer(self, n, args):
        if n == "tracks_list":
            return {"tracks": [{"id": i, "name": nm} for nm, i in self.tracks.items()]}
        if n == "session_get_info":
            return {"sessionName": "Song"}
        if n == "session_list_snapshots":
            snaps = [dict(name=Path(self.session).stem, file=str(self.session), current=True)] if self.session else []
            return {"dirty": self.dirty, "snapshots": snaps}
        if n == "group_create":
            g = dict(groupId=str(9000 + len(self.groups)), name=args["name"], busId="9999", busName=args["name"],
                     folded=False, members=[dict(trackId=t, routedToBus=True) for t in args["track_ids"]])
            self.groups.append(g)
            return {"group": g}
        if n == "group_add":
            g = next(x for x in self.groups if x["groupId"] == args["group_id"])
            g["members"] += [dict(trackId=t, routedToBus=True) for t in args["track_ids"]]
            return {"group": g}
        if n == "group_set":
            g = next(x for x in self.groups if x["groupId"] == args["group_id"])
            g["folded"] = args.get("folded", g["folded"])
            return {"group": g}
        if n == "group_list":
            return {"groups": self.groups}
        if n == "track_get_info":
            return {"plugins": [{"index": i, "enabled": pl["enabled"]} for i, pl in enumerate(self.plug(args["id"]))]}
        if n == "plugin_add_by_plugin_id":
            self.plug(args["id"]).append(self.new_plugin())
            return {}
        if n == "plugin_list_available":
            return {"plugins": [{"uri": "urn:ardour:a-comp#stereo"}]}
        if n == "plugin_get_description":
            vals = self.plug(args["id"])[args["pluginIndex"]]["values"]
            return {"parameters": [{"index": k, "label": lab, "isInput": True, "isControl": True, "currentValue": vals.get(k, 0.0)}
                                   for k, lab in enumerate(self.labels)]}
        if n == "plugin_set_parameter_by_index_value":
            self.plug(args["id"])[args["pluginIndex"]]["values"][args["parameterIndex"]] = args["value"]
            return {}
        if n == "plugin_set_enabled":
            self.plug(args["id"])[args["pluginIndex"]]["enabled"] = args["enabled"]
            return {}
        if n == "plugin_get_sidechain":
            on = any(c[0] == "plugin_set_sidechain" for c in self.calls) or self.keyed
            return {"sidechains": [{"sources": [{"name": "Lead Vocal"}] if on else [], "switch": {"on": on}}]}
        return {}

    keyed = False

    def new_plugin(self, enabled=True):
        return dict(enabled=enabled, values={})

    def plug(self, tid):
        return self.plugins.setdefault(tid, [self.new_plugin()])

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class ApplyTest(Fixture):
    def setUp(self):
        super().setUp()
        self.eng = FakeEngine({t.name: t.route_id for t in self.p.tracks}, session=self.dir / "Song.ardour")

    def tearDown(self):
        self.eng.close()
        super().tearDown()

    def test_only_approved_groups_are_written_and_read_back(self):
        fs = AG.findings(AG.plan_old_takes(self.p), "tidy")
        log, failed = AG.apply(AG.Engine(self.eng.url), fs, [])
        self.assertEqual((log, failed), ([], []))
        self.assertFalse([c for c in self.eng.calls if c[0].startswith("group_")])
        log, failed = AG.apply(AG.Engine(self.eng.url), fs, ["group-1"])
        self.assertEqual(failed, [])
        made = [c for c in self.eng.calls if c[0] == "group_create"]
        self.assertEqual(made, [("group_create", {"name": "Old takes", "track_ids": ["450"]})])
        self.assertIn(("group_set", {"group_id": "9000", "folded": True}), self.eng.calls)
        self.assertIn("folded", log[0])

    def test_a_by_hand_group_is_never_written(self):
        t = (self.dir / "Song.ardour").read_text(encoding="utf-8")
        port = '<Port type="audio" name="Kick/audio_out 2"><Connection other="Master/audio_in 2"/></Port>'
        self.assertIn(port, t)
        (self.dir / "Song.ardour").write_text(t.replace(port, ""), encoding="utf-8")           # Kick now has one output
        fs = AG.findings(AG.plan_families(project.load(self.dir)), "order")
        self.assertEqual((fs[0]["id"], fs[0]["applies"]), ("group-1", "manual"))
        self.assertTrue(fs[0]["fix"].startswith("by hand"))
        log, failed = AG.apply(AG.Engine(self.eng.url), fs, ["group-1"])
        self.assertEqual(failed, [])
        self.assertIn("left for you", log[0])
        self.assertFalse([c for c in self.eng.calls if c[0].startswith("group_")])

    def test_an_add_goes_to_the_planned_group_among_same_names(self):
        self.eng.groups += [dict(groupId="78", name="Drums", busId="1", busName="Drums", folded=False, members=[]),
                            dict(groupId="77", name="Drums", busId="2", busName="Drums 2", folded=False, members=[])]
        fs = AG.findings([dict(op="add", group="Drums", group_id="77", tracks=["Kick"], why="drums")], "order")
        log, failed = AG.apply(AG.Engine(self.eng.url), fs, ["group-1"])
        self.assertEqual(failed, [])
        self.assertIn(("group_add", {"group_id": "77", "track_ids": ["100"]}), self.eng.calls)
        self.assertIn("bus 'Drums 2'", log[0])                               # read back by id, not by name
        self.assertEqual(self.eng.groups[0]["members"], [])

    def test_the_cli_asks_for_ids_and_checks_the_open_session(self):
        a = SimpleNamespace(json=None, engine=self.eng.url, ids=None)
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as e:
            AG.run_cli("order", self.dir, a, AG.plan_families)
        self.assertIn("--ids", str(e.exception))
        a.ids = "group-1"
        with redirect_stdout(io.StringIO()) as out:
            rc = AG.run_cli("order", self.dir, a, AG.plan_families)
        self.assertEqual(rc, 0, out.getvalue())
        self.assertIn("group 'Drums' (3 track(s)", out.getvalue())

    def test_only_a_local_engine(self):
        with self.assertRaises(AG.EngineError):
            AG.Engine("http://example.com:4820/mcp")


class SidechainTest(Fixture):
    def test_ace_compressor_keyed_from_drums_is_measured(self):
        found = SCP.find(self.p)
        self.assertEqual(len(found), 1)
        s = found[0]
        self.assertEqual((s["track"].name, [t.name for t, _, _ in s["sources"]]), ("Bass", ["Drums"]))
        self.assertEqual(s["sources"][0][1:], (0.5, False))             # send level, not post-fader
        c = s["c"]
        self.assertEqual((c["threshold_db"], c["ratio"], c["attack"], c["knee"], c["switch"]), (-40.0, 10.0, 2.0, 0.0, True))
        res = SCP.analyse(self.p)
        fs = SCP.findings(self.p, res, None)
        self.assertEqual(len(fs), 1, fs)
        self.assertIn("ACE Compressor on 'Bass' ducked by Drums", fs[0]["problem"])
        self.assertEqual(fs[0]["applies"], "manual")
        v = fs[0]["ace"]["values"]
        self.assertTrue(-60 <= v["Threshold"] <= 0 and 1 <= v["Ratio"] <= 20 and 0 <= v["Knee"] <= 8, v)
        self.assertEqual(fs[0]["ace"]["route_id"], "150")

    def edit(self, old, new):
        t = (self.dir / "Song.ardour").read_text(encoding="utf-8")
        self.assertIn(old, t)
        (self.dir / "Song.ardour").write_text(t.replace(old, new), encoding="utf-8")
        return project.load(self.dir)

    def test_a_switched_off_send_keys_nothing(self):
        p = self.edit('<Processor id="2501" name="send 1" active="1"', '<Processor id="2501" name="send 1" active="0"')
        d = p.track("Bass").devices[0]
        self.assertEqual((d.sidechain_feeds, d.sidechain_off), ([], ["Drums"]))
        res = SCP.analyse(p)
        self.assertEqual(len(res), 1)                                       # still listed, not dropped
        self.assertIsNone(res[0][1])
        self.assertIn("key send from Drums is switched off", res[0][2])

    def test_a_switched_off_compressor_is_said_not_measured(self):
        for old, new, word in (('<Controllable name="Enable" value="1"', '<Controllable name="Enable" value="0"', "Enable"),
                               ('id="1501" name="ACE Compressor (stereo)" active="1"', 'id="1501" name="ACE Compressor (stereo)" active="0"', "itself")):
            (self.dir / "Song.ardour").write_text(session(self.groups), encoding="utf-8")
            res = SCP.analyse(self.edit(old, new))
            self.assertIsNone(res[0][1])
            self.assertIn("switched off", res[0][2])
            self.assertIn(word, res[0][2])

    def test_a_bus_key_is_its_tracks(self):
        groups = ('<RouteGroup id="5000" rgba="0" name="Synths" subgroup-bus="560" routes="550 " active="1" relative="1" '
                  'hidden="0" gain="0" mute="0" solo="0" recenable="0" select="0" route-active="0" color="0" monitoring="0"/>')
        t = (self.dir / "Song.ardour").read_text(encoding="utf-8").replace("<RouteGroups></RouteGroups>", f"<RouteGroups>{groups}</RouteGroups>")
        t = t.replace('<Connection other="Drums/send 1/audio_out 1"/><Connection other="Drums/send 1/audio_out 2"/>',
                      '<Connection other="Synths/audio_out 1"/><Connection other="Synths/audio_out 2"/>')
        (self.dir / "Song.ardour").write_text(t, encoding="utf-8")
        p = project.load(self.dir)
        self.assertEqual(p.track("Bass").devices[0].sidechain, ["Synths"])
        res = SCP.analyse(p)
        self.assertIsNotNone(res[0][1], res[0][2])                           # Keys plays through it: measured
        trig = SCP.trigger_audio(p, [(p.track("Synths"), 1.0, False)], p.end())
        keys = SCP.SC.to_sr(p.render(p.track("Keys"), 44100, p.end()) * p.track("Keys").volume, 44100)
        self.assertTrue(np.allclose(trig, keys))
        p.track("Keys").muted = True
        res = SCP.analyse(p)
        self.assertIn("bus 'Synths' that keys it carries no audio", res[0][2])
        self.assertNotIn("MIDI or empty track", res[0][2])

    def test_a_switched_off_key_is_said(self):
        self.p.track("Bass").devices[0].params["Sidechain"] = 0.0
        res = SCP.analyse(self.p)
        self.assertIsNone(res[0][1])
        self.assertIn("Sidechain switch is off", res[0][2])


class DuckTest(Fixture):
    def test_the_vocal_reverb_gets_a_keyed_compressor_over_mcp(self):
        props, meta = DA.propose(self.p)
        self.assertEqual(meta["source"], "Lead Vocal")
        self.assertEqual([(x["kind"], x["ret"]) for x in props], [("add", "Reverb")])
        fs = DA.findings(props)
        self.assertEqual((fs[0]["id"], fs[0]["applies"]), ("duck-1", "engine"))
        self.assertEqual(fs[0]["ardour"]["source_id"], "350")
        eng = FakeEngine({t.name: t.route_id for t in self.p.tracks})
        try:
            log, failed = DA.apply(AG.Engine(eng.url), fs, ["duck-1"])
        finally:
            eng.close()
        self.assertEqual(failed, [])
        names = [c[0] for c in eng.calls]
        self.assertEqual(names[names.index("plugin_add_by_plugin_id")]
                         if "plugin_add_by_plugin_id" in names else None, "plugin_add_by_plugin_id")
        sc = next(c[1] for c in eng.calls if c[0] == "plugin_set_sidechain")
        self.assertEqual((sc["track_id"], sc["plugin_index"], sc["source_track_id"]), ("700", 1, "350"))
        self.assertEqual(sc["tap"], "pre_fader")
        sets = [c[1] for c in eng.calls if c[0] == "plugin_set_parameter_by_index_value"]
        self.assertEqual(len(sets), 5)                                       # Sidechain is not listed: a warning, not a stop
        self.assertIn("keyed from Lead Vocal", log[0])
        self.assertIn("(read back)", log[0])
        self.assertIn("does not list Sidechain", log[0])

    def test_the_key_is_what_a_pre_fader_send_carries(self):
        th = lambda: DA.findings(DA.propose(project.load(self.dir))[0])[0]["ardour"]["values"]["Threshold"]
        base = th()
        t = (self.dir / "Song.ardour").read_text(encoding="utf-8")
        amp = '<Processor id="3509" name="Amp" active="1" type="amp"><Controllable name="gaincontrol" value="1"/>'
        self.assertIn(amp, t)
        (self.dir / "Song.ardour").write_text(t.replace(amp, amp.replace('value="1"', 'value="0.5"')), encoding="utf-8")
        self.assertAlmostEqual(th(), base, delta=0.05)                       # the vocal's fader is not in the key
        trim = '<Processor id="3508" name="Trim" active="1" type="trim"><Controllable name="trimcontrol" value="2"/></Processor>'
        (self.dir / "Song.ardour").write_text(t.replace(amp, trim + amp), encoding="utf-8")
        self.assertAlmostEqual(th(), base + 6.02, delta=0.1)                 # its trim is

    def test_a_bus_key_leaves_the_bus_fader_out(self):
        groups = ('<RouteGroup id="5000" rgba="0" name="Synths" subgroup-bus="560" routes="550 " active="1" relative="1" '
                  'hidden="0" gain="0" mute="0" solo="0" recenable="0" select="0" route-active="0" color="0" monitoring="0"/>')
        (self.dir / "Song.ardour").write_text(session(groups), encoding="utf-8")
        p = project.load(self.dir)
        bus = p.track("Synths")
        k1 = DA.key_audio(p, [], bus)
        bus.volume = 0.25
        self.assertTrue(np.allclose(DA.key_audio(p, [], bus), k1))           # a pre-fader tap: not the bus fader
        p.track("Keys").volume = 0.5
        self.assertTrue(np.allclose(DA.key_audio(p, [], bus), 0.5 * k1))     # its tracks' faders: yes

    def tune_session(self, active="0", enable="0"):
        comp = ACE.replace('id="1501"', 'id="7501"').replace('id="1502"', 'id="7502"').replace('id="1503"', 'id="7503"') \
            .replace('active="1" type="lv2"', f'active="{active}" type="lv2"').replace("Bass/", "Reverb/") \
            .replace("Drums/send 1", "Lead Vocal/send 9").replace('name="Enable" value="1"', f'name="Enable" value="{enable}"')
        send = SEND.replace('id="2501"', 'id="3601"').replace('id="2502"', 'id="3602"').replace('id="2503"', 'id="3603"') \
            .replace("Drums/send 1", "Lead Vocal/send 9").replace("Bass/", "Reverb/").replace('name="send 1"', 'name="send 9"')
        t = (self.dir / "Song.ardour").read_text(encoding="utf-8")
        t = t.replace('unique-id="urn:ardour:a-reverb"/>', 'unique-id="urn:ardour:a-reverb"/>' + comp, 1)
        t = t.replace(INTSEND, INTSEND + send, 1)
        (self.dir / "Song.ardour").write_text(t, encoding="utf-8")
        return project.load(self.dir)

    def test_tune_switches_a_compressor_on_and_reads_its_values_back(self):
        p = self.tune_session()
        props, _ = DA.propose(p)
        self.assertEqual(props[0]["kind"], "tune", props)
        self.assertIn("it is switched off", props[0]["problems"])
        fs = DA.findings(props)
        self.assertEqual(fs[0]["ardour"]["values"]["Enable"], 1)
        self.assertTrue(fs[0]["ardour"]["enable"])
        eng = FakeEngine({t.name: t.route_id for t in p.tracks}, LABELS + ["Enable"])
        eng.keyed = True
        eng.plugins["700"] = [eng.new_plugin(), eng.new_plugin(enabled=False)]
        try:
            log, failed = DA.apply(AG.Engine(eng.url), fs, ["duck-1"])
        finally:
            eng.close()
        self.assertEqual(failed, [], log)
        self.assertIn(("plugin_set_enabled", {"id": "700", "pluginIndex": 1, "enabled": True}), eng.calls)
        self.assertTrue(eng.plugins["700"][1]["enabled"])
        self.assertEqual(eng.plugins["700"][1]["values"][5], 1.0)            # Enable
        self.assertIn("(read back)", log[0])

    def test_tune_keys_again_when_the_key_send_is_off(self):
        self.tune_session(active="1", enable="1")
        t = (self.dir / "Song.ardour").read_text(encoding="utf-8").replace('<Processor id="3601" name="send 9" active="1"', '<Processor id="3601" name="send 9" active="0"')
        (self.dir / "Song.ardour").write_text(t, encoding="utf-8")
        p = project.load(self.dir)
        props, _ = DA.propose(p)
        self.assertEqual(props[0]["kind"], "tune", props)                   # not a second compressor
        self.assertIn("key send from Lead Vocal is switched off", props[0]["problems"][0])
        fs = DA.findings(props)
        eng = FakeEngine({t.name: t.route_id for t in p.tracks})
        eng.plugins["700"] = [eng.new_plugin(), eng.new_plugin()]
        try:
            log, failed = DA.apply(AG.Engine(eng.url), fs, ["duck-1"])
        finally:
            eng.close()
        self.assertEqual(failed, [], log)
        self.assertIn(("plugin_set_sidechain", {"track_id": "700", "plugin_index": 1, "source_track_id": "350", "tap": "pre_fader"}),
                      eng.calls)

    def test_tune_says_what_the_engine_did_not_take(self):
        p = self.tune_session(active="1", enable="1")
        fs = DA.findings(DA.propose(p)[0])
        self.assertEqual(fs[0]["kind"], "duck-tune")
        for labels, want in ((["Attack", "Release", "Knee", "Ratio"], "does not list Threshold"), (LABELS, None)):
            eng = FakeEngine({t.name: t.route_id for t in p.tracks}, labels)
            eng.keyed = True
            eng.plugins["700"] = [eng.new_plugin(), eng.new_plugin()]
            if want is None:                                                 # the engine keeps its own value
                real = eng.answer
                eng.answer = lambda n, a: {} if n == "plugin_set_parameter_by_index_value" and a["parameterIndex"] == 3 else real(n, a)
                want = "Ratio reads back"
            try:
                log, failed = DA.apply(AG.Engine(eng.url), fs, ["duck-1"])
            finally:
                eng.close()
            self.assertEqual(log, [])
            self.assertIn(want, failed[0])


if __name__ == "__main__":
    unittest.main()
