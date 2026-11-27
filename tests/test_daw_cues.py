"""The Session view on the engine and A/B of HypnoMix DAW fixes: `hypnomix abset` for a HypnoMix DAW session (one new snapshot
with every clip fix as a B playlist, mixer moves as A/B values, a level match), the Review routes that build, read
and record it, loops / variations filling cue slots over MCP (a fake engine), and the page wiring."""
import json, re, tempfile, unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

from hypnomix import project
from hypnomix.app import daw as DW, dawreview as DR, server as SV
from hypnomix.project import ardour_cues as AC
from hypnomix.session import variations as V
from hypnomix.workflow import abset as AB, abset_ardour as AA
from tests.test_ardour import SESSION, SR

APP = Path(__file__).resolve().parents[1] / "hypnomix" / "app" / "daw"


def make_session(folder):
    af = folder / "interchange" / "Song" / "audiofiles"
    af.mkdir(parents=True)
    t = np.arange(3 * SR) / SR
    for fn in ("lead.wav", "comp.wav", "gtr-L.wav", "gtr-R.wav"):
        sf.write(af / fn, 0.3 * np.sin(2 * np.pi * 220 * t), SR, subtype="FLOAT")
    s = folder / "Song.ardour"
    s.write_text(SESSION.replace('<Session version="7003" name="Song"', '<Session version="7003" name="Song" id-counter="900"'), encoding="utf-8")
    return s


FINDINGS = [
    dict(id="clips-1", tool="clips", kind="spike", severity="low", track="Lead", where="2.1.01 (1.50 s)", applies="set",
         edit=dict(op="dip", t0=1.5, t1=1.6, db=9.0, ramp=0.02), problem="a burst", fix="a dip"),
    dict(id="mix-1", tool="balance", severity="low", track="Guitar", where="whole song", applies="set",
         edit=dict(op="mixer", fader_db=-3.0), problem="loud", fix="3 dB down"),
    dict(id="tune-Lead", tool="tune", severity="medium", track="Lead", where="whole take", applies="audio",
         problem="off", fix="tune"),
]


class AbsetArdour(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        base = Path(self.td.name).resolve()
        self.sess = make_session(base / "Song")
        self.sd = base / "scan"
        self.sd.mkdir()
        (self.sd / "findings.json").write_text(json.dumps(dict(set=str(self.sess), notes=[], findings=FINDINGS)), encoding="utf-8")

    def tearDown(self):
        self.td.cleanup()

    def test_one_snapshot_b_playlists_mixer_values_and_level_match(self):
        out, spec = AB.build(self.sd, "clips-1,mix-1,tune-Lead")
        self.assertEqual(out, self.sess.with_name("Song (A-B).ardour"))
        self.assertEqual(spec["daw"], "ardour")
        it = spec["items"]
        self.assertEqual(it["clips-1"]["kind"], "playlist")
        self.assertEqual(it["clips-1"]["trackId"], "200")
        self.assertEqual(it["clips-1"]["a_playlist_id"], "500")
        self.assertEqual(it["clips-1"]["b_playlist"], "Lead.B clips-1")
        self.assertLess(it["clips-1"]["match_db"], 0)            # a dip: B is quieter around the spot
        self.assertEqual(it["mix-1"]["kind"], "mixer")
        self.assertAlmostEqual(it["mix-1"]["b"]["fader_db"] - it["mix-1"]["a"]["fader_db"], -3.0, places=2)
        self.assertIsNone(it["tune-Lead"]["kind"])
        self.assertIn("not previewable", it["tune-Lead"]["note"])
        root = ET.parse(out).getroot()
        ids = [x.get("id") for x in root.iter() if (x.get("id") or "").isdigit()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreater(int(root.get("id-counter")), max(map(int, ids)))
        b = next(p for p in root.find("Playlists") if p.get("name") == "Lead.B clips-1")
        self.assertEqual(b.get("orig-track-id"), "200")
        self.assertEqual(next(r for r in root.iter("Route") if r.get("id") == "200").get("audio-playlist"), "500")
        # the snapshot plays like the original: same model (the active playlists), nothing changed
        from hypnomix.project import ardour_edit as E
        errs, changes = E._model_diff(project.load(self.sess), project.load(out))
        self.assertEqual((errs, changes), ([], []))
        # B holds the fix: the envelope dips at 1.5 s (0.5 s into the region)
        self.assertIn("Envelope", ET.tostring(b, encoding="unicode"))
        self.assertTrue((self.sd / "ab_ardour.json").exists())
        with self.assertRaises(RuntimeError):                      # nothing is overwritten
            AB.build(self.sd, "clips-1", out.name)
        self.assertIn("2 of 3 findings", AA.summary(out, spec))

    def test_routes_build_state_and_blind(self):
        env = mock.patch.dict("os.environ", {"HYPNOMIX_APP_HOME": str(Path(self.td.name) / "app")})
        env.start()
        self.addCleanup(env.stop)
        d = SV.work() / "scan" / "Song (DAW)"
        d.mkdir(parents=True)
        (d / "findings.json").write_text((self.sd / "findings.json").read_text(encoding="utf-8"), encoding="utf-8")
        runs = []
        with mock.patch.object(SV, "run_job", lambda kind, title, steps, sd="", watch=(): runs.append((kind, steps, watch))):
            r = DR.handle_post(SV, "/api/dawreview/abset", dict(dir=str(d)))[1]
        self.assertEqual(runs[-1][1][0][1], ["abset", str(d.resolve()), "--out", str(self.sess.with_name("Song (A-B).ardour"))])
        self.assertEqual(list(runs[-1][2]), [self.sess.parent])
        self.assertTrue(r["out"].endswith("Song (A-B).ardour"))
        self.assertFalse(DR.handle_get(SV, "/api/dawreview/abstate", dict(dir=str(d)))[1]["built"])
        out, _ = AB.build(d, "clips-1")
        eng = types_engine(out)
        with mock.patch.object(DR, "_engine", lambda: eng):
            st = DR.handle_get(SV, "/api/dawreview/abstate", dict(dir=str(d)))[1]
            self.assertTrue(st["built"] and st["open"] and st["exists"])
            # the engine on the A/B snapshot still reviews the original's scan
            s2 = DR.handle_get(SV, "/api/dawreview/state", {})[1]
            self.assertEqual((Path(s2["dir"]).resolve(), s2["ab_session"]), (d.resolve(), str(out)))
        self.assertEqual(DR.ab_out_for(self.sess).name, "Song (A-B) 2.ardour")   # the first is taken now
        post = lambda body: DR.handle_post(SV, "/api/dawreview/blind", dict(body, dir=str(d)))[1]
        self.assertEqual(post(dict(id="clips-1", picked="X", was="B"))["choices"][-1]["was"], "B")
        for bad in (dict(id="clips-1", picked="Z", was="B"), dict(id="clips-1", picked="X", was="C"), dict(id="mix-9", picked="X", was="A")):
            with self.assertRaises(ValueError):
                post(bad)
        self.assertEqual(len(json.loads((d / "blind.json").read_text(encoding="utf-8"))["clips-1"]), 1)


class AbsetArdourChecks(unittest.TestCase):
    """The level match's size and span, mutes, the fader without the trim, and how the snapshot is put in place."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.base = Path(self.td.name).resolve()
        self.sess = make_session(self.base / "Song")
        self.sd = self.base / "scan"
        self.sd.mkdir()

    def tearDown(self):
        self.td.cleanup()

    def edit(self, old, new):
        t = self.sess.read_text(encoding="utf-8")
        self.assertIn(old, t)
        self.sess.write_text(t.replace(old, new, 1), encoding="utf-8")

    def findings(self, *fs):
        (self.sd / "findings.json").write_text(json.dumps(dict(set=str(self.sess), notes=[], findings=list(fs))), encoding="utf-8")

    def mixer(self, fid, track, **e):
        return dict(id=fid, tool="balance", severity="low", track=track, where="whole song", applies="set",
                    edit=dict(op="mixer", **e), problem="p", fix="f")

    GUITAR_ON = ('<Controllable name="mute" value="1"/>\n      <Controllable name="phase" value="0" phase-invert="01"/>',
                 '<Controllable name="mute" value="0"/>\n      <Controllable name="phase" value="0" phase-invert="01"/>')
    LEAD_OFF = ('<MuteMaster muted="0"/>\n      <Controllable name="mute" value="0"/>', '<MuteMaster muted="1"/>\n      <Controllable name="mute" value="1"/>')

    def test_fader_values_leave_the_trim_out(self):
        self.edit('<Processor id="601" name="Amp"', '<Processor id="609" name="Trim" active="1" type="trim"><Controllable name="trimcontrol" value="2"/></Processor>'
                  '<Processor id="601" name="Amp"')
        self.findings(self.mixer("mix-1", "Guitar", fader_db=-6.0))
        _, spec = AB.build(self.sd, "mix-1")
        it = spec["items"]["mix-1"]
        self.assertAlmostEqual(it["a"]["fader_db"], 0.0, places=2)          # the fader the engine holds, not fader x trim
        self.assertAlmostEqual(it["b"]["fader_db"], -6.0, places=1)

    def test_level_match_size_follows_the_change(self):
        self.edit(*self.GUITAR_ON)
        self.edit(*self.LEAD_OFF)                                           # Guitar alone is heard
        self.findings(self.mixer("mix-1", "Guitar", fader_db=6.0))
        _, spec = AB.build(self.sd, "mix-1")
        self.assertAlmostEqual(spec["items"]["mix-1"]["match_db"], 6.0, delta=0.1)   # 6 dB more fader: 6 dB louder

    def test_level_match_is_over_the_span_only(self):
        from hypnomix.workflow import fix_ardour as FA
        from tests.test_ardour import a as at
        self.edit(*self.GUITAR_ON)                                          # a loud Guitar far from the spot (8-11 s)
        self.edit(f'length="{at(1)}@{at(0)}"', f'length="{at(3)}@{at(8)}"')
        f = FINDINGS[0]                                                     # a 9 dB dip at 1.5-1.6 s on Lead
        self.findings(f)
        _, spec = AB.build(self.sd, "clips-1")
        it = spec["items"]["clips-1"]
        a = project.load(self.sess)
        b = project.load(self.sess)
        FA.apply_edits(b, [f], {}, [], [], [])
        ya = project.model.mixdown(a, sr=AA.SR, length=a.end())
        yb = project.model.mixdown(b, sr=AA.SR, length=a.end())
        i0, i1 = int(it["span"][0] * AA.SR), int(it["span"][1] * AA.SR)
        want = AA._level(yb[i0:i1], AA.SR) - AA._level(ya[i0:i1], AA.SR)
        self.assertAlmostEqual(it["match_db"], want, delta=0.05)
        whole = AA._level(yb, AA.SR) - AA._level(ya, AA.SR)
        self.assertGreater(abs(it["match_db"] - whole), 0.1)               # not the whole song's difference
        self.assertLess(it["match_db"], -0.05)

    def test_mute_and_unmute_fixes_are_level_matched(self):
        from tests.test_ardour import a as at
        self.edit(*self.GUITAR_ON)
        self.edit('phase-invert="01"', 'phase-invert="00"')
        self.edit(f'length="{at(1)}@{at(0)}"', f'length="{at(2)}@{at(1)}"')   # under the Lead (1-3 s)
        af = self.sess.parent / "interchange" / "Song" / "audiofiles"
        t = np.arange(3 * SR) / SR
        for fn in ("gtr-L.wav", "gtr-R.wav"):                               # not the Lead's tone, so nothing cancels
            sf.write(af / fn, 0.3 * np.sin(2 * np.pi * 330 * t), SR, subtype="FLOAT")
        self.findings(self.mixer("mute-1", "Lead", mute=True))
        _, spec = AB.build(self.sd, "mute-1")
        it = spec["items"]["mute-1"]
        self.assertEqual((it["a"]["mute"], it["b"]["mute"]), (False, True))
        self.assertLess(it["match_db"], -1.0)                               # Lead gone: B is quieter
        self.tearDown()
        self.setUp()                                                        # Guitar starts muted and the fix unmutes it
        self.findings(self.mixer("mute-2", "Guitar", mute=False))
        _, spec = AB.build(self.sd, "mute-2")
        self.assertGreater(spec["items"]["mute-2"]["match_db"], 1.0)

    def test_a_fix_that_leaves_near_silence_is_matched_by_at_most_12_db(self):
        self.findings(self.mixer("mute-1", "Lead", mute=True))              # Guitar starts muted: Lead is all that plays
        out, spec = AB.build(self.sd, "mute-1")
        it = spec["items"]["mute-1"]
        self.assertEqual(it["match_db"], -AA.MAX_MATCH_DB)                  # A is not turned down to silence
        self.assertTrue(it["match_capped"])
        self.assertLess(it["level_db"], -30.0)                              # the measured difference is kept
        self.assertIn("by 12 dB, the most it is", AA.summary(out, spec))

    def test_snapshot_stays_in_the_folder_and_never_writes_through_a_link(self):
        self.findings(FINDINGS[0])
        with self.assertRaisesRegex(RuntimeError, "own folder"):
            AB.build(self.sd, "clips-1", str(self.base / "Song (A-B).ardour"))
        target = self.base / "elsewhere.ardour"
        link = self.sess.with_name("Song (A-B).ardour")
        link.symlink_to(target)                                             # dangling: exists() is False
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            AB.build(self.sd, "clips-1")
        self.assertFalse(target.exists())
        link.unlink()
        # a name taken between the check and the put-in-place: refused, and the file there is untouched
        real = AA._claim
        def race(src, dst):
            if Path(dst).name == "Song (A-B).ardour" and not Path(dst).exists():
                Path(dst).write_text("someone else's", encoding="utf-8")
            return real(src, dst)
        with mock.patch.object(AA, "_claim", race), self.assertRaisesRegex(RuntimeError, "already exists"):
            AB.build(self.sd, "clips-1")
        self.assertEqual(link.read_text(encoding="utf-8"), "someone else's")
        self.assertEqual([p.name for p in self.sess.parent.iterdir() if p.name.endswith(".tmp.ardour")], [])

    def test_a_broken_snapshot_never_replaces_a_file(self):
        self.findings(FINDINGS[0])
        bad = self.sess.with_name("Song (A-B) (BROKEN, do not open).ardour")
        bad.write_text("an older one", encoding="utf-8")
        from hypnomix.project import ardour_edit as E
        with mock.patch.object(E, "_model_diff", lambda a, b: (["made up"], [])), self.assertRaisesRegex(RuntimeError, r"BROKEN, do not open\) 2"):
            AB.build(self.sd, "clips-1")
        self.assertEqual(bad.read_text(encoding="utf-8"), "an older one")
        self.assertTrue(self.sess.with_name("Song (A-B) (BROKEN, do not open) 2.ardour").exists())
        self.assertFalse(self.sess.with_name("Song (A-B).ardour").exists())

    def test_a_numbered_rebuild_keeps_the_first_reviewable(self):
        self.findings(FINDINGS[0], FINDINGS[1])
        first, _ = AB.build(self.sd, "clips-1")
        second, _ = AB.build(self.sd, "mix-1", DR.ab_out_for(self.sess).name)
        self.assertEqual(second.name, "Song (A-B) 2.ardour")
        self.assertEqual(AA.load(self.sd)["session"], str(second))
        self.assertEqual(list(AA.load(self.sd, first)["items"]), ["clips-1"])
        self.assertEqual(list(AA.load(self.sd, second)["items"]), ["mix-1"])
        with mock.patch.object(DR, "scan_folder", lambda srv, s: self.sd):
            self.assertEqual(DR.ab_original(None, first), self.sd)
            self.assertEqual(DR.ab_original(None, second), self.sd)


def types_engine(session):
    class E:
        def connected(self):
            return True
        session_ = None

        def call(self, method, params=None, timeout=8.0):
            assert params["name"] == "session_list_snapshots"
            return {"structuredContent": dict(dirty=False, snapshots=[dict(name=session.stem, file=str(session), current=True)])}
    e = E()
    e.session = str(session)
    return e


class FakeMCP:
    """cue_list / cue_set_clip / tracks_* on one session, as the engine answers them."""

    def __init__(self, tracks=("Drums",)):
        self.url = "http://127.0.0.1:1/mcp"
        self.tracks = [dict(id=str(10 + i), name=n) for i, n in enumerate(tracks)]
        self.slots = {}
        self.calls = []

    def call(self, _tool, **a):
        name = _tool
        self.calls.append((name, a))
        if name == "tracks_list":
            return dict(tracks=self.tracks)
        if name == "tracks_add":
            self.tracks.append(dict(id=str(10 + len(self.tracks)), name=a["name"]))
            return {}
        if name == "cue_list":
            s = self.slots.get(a["track_id"], {})
            return dict(tracks=[dict(trackId=a["track_id"], slots=[dict(slot=n, empty=n not in s) for n in range(16)])])
        if name == "cue_set_clip":
            self.slots.setdefault(a["track_id"], {})[a["slot"]] = a
            return dict(slot=a["slot"], empty=False)
        raise AssertionError(name)


class Cues(unittest.TestCase):
    def test_fill_uses_empty_slots_on_a_new_track_next_to_the_part(self):
        m = FakeMCP()
        after, name = AC.track_id(m, "drum")
        self.assertEqual((after, name), ("10", "Drums"))
        tid, made = AC.clip_track(m, "Drums loops", after)
        self.assertTrue(made)
        self.assertEqual(m.calls[-2][1]["relativeToId"], "10")
        m.slots[tid] = {0: {}}
        placed = AC.fill(m, tid, [dict(file="/tmp/a.wav", name="A", beats=8), dict(file="/tmp/b.wav", name="B", beats=16)])
        self.assertEqual([s for _, s, _ in placed], [1, 2])
        a = m.slots[tid][1]
        self.assertEqual((a["beats"], a["stretchable"], a["follow_action"], a["quantize"]), (8.0, True, "again", "bar"))
        self.assertEqual(AC.clip_track(m, "Drums loops")[0], tid)          # the same track again, not a second one
        m.slots[tid] = {n: {} for n in range(16)}
        self.assertIn("no empty slot", AC.fill(m, tid, [dict(file="/tmp/c.wav", name="C")])[0][2])
        self.assertIn("slot 2: A", AC.report(placed, "Drums loops"))

    def test_connect_checks_the_open_session(self):
        class M:
            def __init__(self, url, timeout=0):
                self.url = url

            def call(self, _tool, **a):
                return dict(snapshots=[dict(file="/x/Other.ardour", current=True)])
        with mock.patch.object(AC, "MCP", M), mock.patch.object(AC, "tool_names", lambda m: {"cue_set_clip"}):
            with self.assertRaisesRegex(RuntimeError, "Other.ardour open"):
                AC.connect(None, "/x/Song.ardour")
            self.assertEqual(AC.connect("http://h/mcp", "/x/Other.ardour").url, "http://h/mcp")
        with mock.patch.object(AC, "MCP", M), mock.patch.object(AC, "tool_names", lambda m: set()):
            with self.assertRaisesRegex(RuntimeError, "no cue tools"):
                AC.connect(None)

    def test_variations_reads_pasted_ardour_regions_as_repeats(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "gtr%L.wav"
            sf.write(f, np.zeros(SR * 40), SR)
            take = project.model.Take("gtr", path=f, offset=4.0, extra_paths=[str(Path(td) / "gtr%R.wav")])
            clips = [project.model.Clip("g", start=2.0 * i, length=2.0, takes=[take]) for i in range(6)]
            clips.append(project.model.Clip("g", start=20, length=2.0, takes=[take], muted=True))
            t = project.model.Track("Guitar", 0, clips=clips)
            pl = V.ardour_plays(t, 120.0)
            self.assertEqual(len(pl), 6)                                    # the muted one is left out
            self.assertEqual((pl[1]["start"], pl[1]["len"], pl[1]["f0"], pl[1]["f1"]), (4.0, 4.0, 4.0, 6.0))
            self.assertEqual(len(pl[0]["paths"]), 2)                       # both channels for the auditions
            self.assertEqual(len(V.repeats(pl, 4, 4)), 1)


class CuesCli(unittest.TestCase):
    """loops --cues and variations --cues send each clip's length in quarter beats: bars x the session's bar."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.dir = Path(self.td.name)
        self.wav = self.dir / "gtr.wav"
        sf.write(self.wav, np.zeros(SR // 10), SR)                          # a tenth of a second: only its path is used
        self.sess = self.dir / "Song.ardour"
        self.sess.write_text("<Session/>", encoding="utf-8")

    def tearDown(self):
        self.td.cleanup()

    def project(self, bpb, clips=1, length=2.0):
        take = project.model.Take("gtr", path=self.wav, offset=4.0)
        cl = [project.model.Clip("g", start=length * i, length=length, takes=[take]) for i in range(clips)]
        return project.model.Project(path=self.sess, daw="ardour", tempo=120.0, beats_per_bar=bpb,
                                     tracks=[project.model.Track("Guitar", 0, clips=cl)])

    def run_main(self, mod, argv, proj, extra=()):
        import sys as _s
        from hypnomix import project as PJ
        m = FakeMCP(tracks=("Guitar",))
        pats = [mock.patch.object(_s, "argv", [mod.__name__] + argv), mock.patch.object(PJ, "load", lambda src: proj),
                mock.patch.object(AC, "connect", lambda url, session=None: m)] + list(extra)
        for pt in pats:
            pt.start()
            self.addCleanup(pt.stop)
        with mock.patch("sys.stdout", new=__import__("io").StringIO()):
            mod.main()
        return [a for n, a in m.calls if n == "cue_set_clip"]

    def loops(self, bpb, argv=()):
        from hypnomix.session import loops as LP
        pick = [dict(n=1, name="L1", groove="straight", fill=False, bars=2, bar=1, bpm=120.0, steady=1.0, seam=1.0,
                     score=1.0, start=0.0)]
        extra = [mock.patch.object(LP.B, "track", lambda *a, **k: dict(snapped=1.0, bpm=120.0, wander_pct=0.0, bpb=k.get("bpb"))),
                 mock.patch.object(LP.B, "load", lambda f: (np.zeros((64, 1)), SR)),
                 mock.patch.object(LP, "candidates", lambda *a: (pick, [0.0, 1.0, 2.0])),
                 mock.patch.object(LP, "cut", lambda y, sr, c: np.zeros(64))]
        return self.run_main(LP, [str(self.sess), "--track", "Guitar", "--cues", "--out", str(self.dir / "o")] + list(argv),
                             self.project(bpb), extra)

    def test_loops_take_the_bar_from_the_session(self):
        self.assertEqual([c["beats"] for c in self.loops(4)], [8.0])
        self.assertEqual([c["beats"] for c in self.loops(3)], [6.0])          # 3/4: two bars are six beats
        self.assertEqual([c["beats"] for c in self.loops(3, ["--bpb", "4"])], [8.0])   # unless told otherwise

    def test_variations_take_the_bar_from_the_session(self):
        cand = dict(f0=20.0, f1=22.0, fit="good", different="some", level_db=0.0, score=1.0)
        for bpb, length in ((4, 2.0), (3, 1.5)):                            # one bar a region: 4 or 3 quarters
            extra = [mock.patch.object(V, "candidates", lambda *a: ([dict(cand)], 1)),
                     mock.patch.object(V, "features", lambda f: dict(dur=40.0)),
                     mock.patch.object(V, "ardour_unused", lambda p, src: []),
                     mock.patch.object(V, "load_play", lambda sp: (np.zeros((SR * 3, 1)), SR)),
                     mock.patch.object(V.B, "load", lambda f: (np.zeros((SR * 30, 1)), SR))]
            sent = self.run_main(V, [str(self.sess), "--cues", "--out", str(self.dir / f"v{bpb}")], self.project(bpb, 8, length), extra)
            self.assertTrue(sent)
            self.assertEqual({c["beats"] for c in sent}, {float(bpb)})


class Wiring(unittest.TestCase):
    def test_page_and_proxy(self):
        html = (APP / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index("js/transport.js"), html.index("js/cues.js"))
        self.assertLess(html.index("js/cues.js"), html.index("js/clips.js"))
        self.assertGreaterEqual(DW.rpc_timeout(b'{"params":{"name":"cue_set_clip"}}'), 90.0)
        self.assertEqual(DW.rpc_timeout(b'{"params":{"name":"cue_list"}}'), DW.RPC_TIMEOUT)
        js = (APP / "js" / "cues.js").read_text(encoding="utf-8") + (APP / "js" / "clips.js").read_text(encoding="utf-8") + (APP / "js" / "review.js").read_text(encoding="utf-8")
        for tool in ("cue_list", "cue_launch", "scene_launch", "cue_stop", "cue_set_clip", "ab_use_playlist"):
            self.assertIn("'" + tool + "'", js)
        self.assertNotRegex(js, r"\son[a-z]+=\"")                          # no inline handlers
        from hypnomix.app import daw_assist as DA
        self.assertTrue({"cue_list", "ab_list"} <= DA.READ_ONLY)
        self.assertNotIn("cue_launch", DA.READ_ONLY)
        from hypnomix.app import daw_meters as DM
        self.assertEqual(DM.MAX_RELAYS, 4)                                 # the docs say at most four streams


if __name__ == "__main__":
    unittest.main()
