"""Teacher mode (hypnomix/app/teacher.py): the two courses per DAW, the hands-on actions, and their routes."""
import json, re, tempfile, threading, unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from hypnomix.app import setup as SU
from hypnomix.app import teacher as T
from tests.teacher_ids import PINNED


class FakeLive:
    def __init__(self):
        self.calls, self.tracks_ = [], ["Vocal"]

    def ping(self): return True
    def close(self): self.calls.append(("close",))
    def set_tempo(self, bpm): self.calls.append(("tempo", bpm))
    def metronome(self, on=None): self.calls.append(("click", on)); return True
    def new_track(self, kind, name):
        self.tracks_.append(name); self.calls.append(("new", kind, name)); return len(self.tracks_) - 1
    def load_browser_item(self, t, cat, name): self.calls.append(("kit", t, cat)); return 1
    def new_clip(self, t, slot, beats, name): self.calls.append(("clip", t, slot, beats))
    def add_notes(self, t, slot, notes): self.calls.append(("notes", t, len(notes)))
    def inputs(self, t): return (["Ext. In", "Resampling"], ["1", "2", "1/2"], "Ext. In", "1")
    def set_input(self, t, kind=None, channel=None): self.calls.append(("input", kind, channel))
    def monitor(self, t, mode): self.calls.append(("monitor", mode))
    def arm(self, t, on=True): self.calls.append(("arm", t, on)); self.armed_ = on
    def armed(self, t): return getattr(self, "armed_", False) and not getattr(self, "no_input", False)
    def devices(self, t): return ["Reverb"] if t == -2 and getattr(self, "has_reverb", False) else []
    def tid(self, t): return -1 if t == "Master" else -2 if t == "A" else self.tracks_.index(t) if t in self.tracks_ else 0
    def load_stock_device(self, t, name): self.calls.append(("device", t, name)); return 0
    def find_param(self, t, d, names):
        return None if names[0] == "Nope" else {"name": names[0]}
    def set_param_display(self, t, d, p, v): self.calls.append(("disp", p, v))
    def set_param(self, t, d, p, v): self.calls.append(("raw", p, v))


class FakeReaper:
    def __init__(self, chain_ok=True):
        self.calls, self.chain_ok = [], chain_ok

    def alive(self): return True
    def call(self, cmd, **a):
        self.calls.append((cmd, a))
        if cmd == "chain_build" and not self.chain_ok:
            from hypnomix.reaper.client import ReaperError
            raise ReaperError("chain_build: no HypnoMix Main on the master")
        return {"teach_tempo": {"bpm": a.get("bpm")}, "teach_click": {"on": True}, "teach_drums": {"fx": 0, "notes": 3}}.get(cmd, {})
    def transport(self, go=None, at=None): self.calls.append(("transport", go))
    def add_fx(self, track, name): self.calls.append(("add_fx", track, name)); return {"fx": 0}
    def named(self, track, fx, key, value=None): self.calls.append(("named", key, value))
    def set_shown(self, track, fx, p, v):
        if p == "Amount (%)":                              # a plug-in that names its control differently: the next name is tried
            from hypnomix.reaper.client import ReaperError
            raise ReaperError("set_param: no parameter " + p)
        self.calls.append(("shown", track, fx, p, v))
    def set_norm(self, track, fx, p, v): self.calls.append(("norm", track, fx, p, v))
    def tracks(self): return getattr(self, "tracks_", [])
    def add_track(self, name=None, file=None, pos=0.0): self.calls.append(("add_track", name)); return {"index": 0}


class Courses(unittest.TestCase):
    def test_two_courses_for_every_daw(self):
        for d in T.DAWS:
            tour = [c["id"] for c in T.steps(d, "tour")]
            full = [c["id"] for c in T.steps(d, "101")]
            self.assertEqual(tour, ["hypnomix"])                       # engineers: hypnomix and their DAW only
            self.assertEqual(full, ["words", "record", "mix", "master", "hypnomix"])
            for c in T.steps(d, "101"):
                self.assertTrue(c["steps"], (d, c["id"]))
                for s in c["steps"]:
                    self.assertTrue(s["say"], s["id"])
        self.assertIn("Ableton Live", T.steps("live", "tour")[0]["title"])

    def test_published_step_ids_never_change(self):
        """Progress files and the Assistant key on step ids: today's 101 and tour courses stay exactly as published."""
        for key, want in PINNED.items():
            level, daw = key.split("/")
            got = [(c["id"], tuple(s["id"] for s in c["steps"])) for c in T.steps(daw, level)]
            self.assertEqual(got, want, key)

    def test_az_holds_every_step_of_the_smaller_courses(self):
        for d in T.DAWS:
            az = [s["id"] for c in T.steps(d, "az") for s in c["steps"]]
            for lv in ("101", "tour"):
                ids = [s["id"] for c in T.steps(d, lv) for s in c["steps"]]
                self.assertEqual([i for i in az if i in set(ids)], ids, (d, lv))     # a subset, in the same order

    def test_an_unknown_level_falls_back_to_101(self):
        self.assertEqual(T.steps("live", "nonsense"), T.steps("live", "101"))
        with mock.patch("hypnomix.app.setup.load", return_value={"daw": "live", "teach_level": "from-the-future"}):
            self.assertEqual(T.choice()[1], "101")

    def test_live_and_reaper_deepest_ardour_shortest(self):
        for lv in T.LEVELS:
            self.assertGreater(T.count("live", lv), T.count("ardour", lv))
            self.assertGreater(T.count("reaper", lv), T.count("ardour", lv))
            # REAPER has Live's depth: every step but the ones only Live has (its Session View)
            self.assertGreaterEqual(T.count("reaper", lv), T.count("live", lv) - 1, lv)
        live = {s["id"] for c in T.steps("live", "az") for s in c["steps"]}
        reaper = {s["id"] for c in T.steps("reaper", "az") for s in c["steps"]}
        twins = {"screen-live", "hm-connect-live", "hm-devices-live"}          # REAPER has its own step for each
        self.assertEqual(live - reaper - twins, {"session-sketch"})

    def test_reaper_has_lives_hands_on_actions(self):
        def acts(d):
            return {s["id"] for c in T.steps(d, "az") for s in c["steps"] if s.get("action")}
        self.assertEqual(acts("live") - acts("reaper"), {"hm-connect-live"})   # REAPER's twin is hm-connect-reaper
        self.assertIn("hm-connect-reaper", acts("reaper"))
        for sid in ("reverb", "saturation"):
            self.assertIn(sid, acts("reaper"))

    def test_101_covers_what_was_asked(self):
        ids = {s["id"] for c in T.steps("live", "101") for s in c["steps"]}
        for want in ("click", "drums", "track", "gain", "take", "eq", "comp", "reverb", "what", "chain"):
            self.assertIn(want, ids)

    def test_actions_only_where_the_daw_can_be_driven(self):
        for d in T.DAWS:
            for c in T.steps(d, "101"):
                for s in c["steps"]:
                    a = s.get("action")
                    if not a:
                        continue
                    self.assertTrue(a["will"] and a["label"])
                    if d == "ardour":
                        self.assertEqual(a["kind"], "level")           # Ardour can't be driven: only the level check
        live = {s["id"]: s for c in T.steps("live", "101") for s in c["steps"]}
        self.assertEqual(live["drums"]["action"]["kind"], "drums")
        self.assertTrue(live["drums"]["action"]["changes"])
        self.assertFalse(live["gain"]["action"]["changes"])

    def test_beat_is_on_the_beat_with_varied_velocity(self):
        n = T.beat(4)
        self.assertEqual(n, T.beat(4))                                 # the same beat every time
        kicks = [s for p, s, d, v in n if p == 36]
        snares = [s for p, s, d, v in n if p == 38]
        self.assertTrue(all(b * 4 in kicks for b in range(4)))
        self.assertEqual(snares, [1, 3, 5, 7, 9, 11, 13, 15])
        vels = {v for p, s, d, v in n if p == 42}
        self.assertGreater(len(vels), 4)
        self.assertTrue(all(1 <= v <= 127 and 0 <= s < 16 for p, s, d, v in n))
        self.assertEqual([s for p, s, d, v in T.beat(1, "half-time") if p == 38], [2])

    def test_wiki_articles(self):
        a = T.wiki_article("reaper", "tour")
        self.assertEqual((a["id"], a["group"]), ("tour-reaper", "DAW: REAPER"))
        self.assertIn("HypnoMix Main", a["text"])
        b = T.wiki_article("live", "az")                               # the contents page; the chapters are articles of their own
        self.assertEqual(b["id"], "learn-live")
        self.assertIn("Mixing", b["text"])
        self.assertTrue(b["generated"])
        c = next(x for x in T.wiki_articles("live") if x["id"] == "learn-live-mix")
        self.assertIn("EQ Eight", c["text"])

    def test_assistant_note_follows_the_level(self):
        with mock.patch.object(T, "choice", return_value=("live", "", "key")):
            self.assertEqual(T.assistant_note(), "")
        with mock.patch.object(T, "choice", return_value=("live", "tour", "key")):
            self.assertIn("already knows", T.assistant_note())
        with mock.patch.object(T, "choice", return_value=("reaper", "101", "key")):
            self.assertIn("beginner", T.assistant_note())
        with mock.patch.object(T, "choice", return_value=("reaper", "az", "key")):
            self.assertIn("complete course", T.assistant_note())


class Actions(unittest.TestCase):
    def live(self, sid, kind, args=None):
        lv = FakeLive()
        with mock.patch.object(T, "_live", return_value=lv):
            return T.run("live", sid, kind, args or {}), lv.calls

    def test_live_tempo_click_track(self):
        r, c = self.live("tempo", "tempo", {"bpm": "96"})
        self.assertIn(("tempo", 96.0), c)
        r, c = self.live("click", "click")
        self.assertIn(("click", True), c)
        r, c = self.live("track", "track", {"name": "Guitar", "input": 2})
        self.assertIn(("new", "audio", "Guitar"), c)
        self.assertIn(("input", "Ext. In", None), c)
        self.assertIn(("input", None, "2"), c)
        self.assertIn(("monitor", "auto"), c)
        self.assertIn(("arm", 1, True), c)
        with self.assertRaises(ValueError):
            self.live("tempo", "tempo", {"bpm": 900})

    def test_live_track_without_an_audio_input(self):
        lv = FakeLive(); lv.no_input = True
        with mock.patch.object(T, "_live", return_value=lv):
            r = T.run("live", "track", "track", {"name": "Vox", "input": 1})
        self.assertIn("wouldn't arm", r["done"])
        self.assertIn("Audio Input Device", r["by_hand"][0])

    def test_live_reverb_reuses_the_return_s_reverb(self):
        lv = FakeLive(); lv.has_reverb = True
        with mock.patch.object(T, "_live", return_value=lv):
            T.run("live", "reverb", "fx", {})
        self.assertFalse([c for c in lv.calls if c[0] == "device"])
        self.assertIn(("disp", "Dry/Wet", 100), lv.calls)

    def test_live_drums(self):
        r, c = self.live("drums", "drums", {"bars": 2})
        self.assertIn(("new", "midi", "Drums"), c)
        self.assertIn(("kit", 1, "drums"), c)
        self.assertIn(("clip", 1, 0, 8), c)
        self.assertIn(("notes", 1, len(T.beat(2))), c)

    def test_live_fx_and_chain(self):
        r, c = self.live("eq", "fx", {"track": "Vocal"})
        self.assertIn(("device", 0, "EQ Eight"), c)
        self.assertIn(("disp", "1 Frequency A", 100), c)
        r, c = self.live("reverb", "fx")
        self.assertIn(("device", -2, "Reverb"), c)                     # the reverb goes on return A
        r, c = self.live("chain", "chain")
        self.assertEqual([x[2] for x in c if x[0] == "device"], ["EQ Eight", "Glue Compressor", "Utility", "Limiter"])
        self.assertTrue(all(x[1] == -1 for x in c if x[0] == "device"))

    def test_wrong_action_or_daw(self):
        with self.assertRaises(ValueError):
            T.run("live", "eq", "drums", {})
        with self.assertRaises(ValueError):
            T.run("ardour", "tempo", "tempo", {})
        with self.assertRaises(ValueError):
            T.run("", "tempo", "tempo", {})

    def test_reaper(self):
        r = FakeReaper()
        with mock.patch.object(T, "_reaper", return_value=r):
            T.run("reaper", "tempo", "tempo", {"bpm": 120})
            T.run("reaper", "drums", "drums", {"bars": 1})
            T.run("reaper", "track", "track", {"name": "Vox", "input": 3})
            T.run("reaper", "take", "record", {})
            T.run("reaper", "take", "stop", {})
            T.run("reaper", "comp", "fx", {"track": "Vox"})
        cmds = [x[0] for x in r.calls]
        self.assertIn("teach_tempo", cmds)
        drums = next(a for c, a in r.calls if c == "teach_drums")
        self.assertEqual(drums["beats"], 4)
        self.assertEqual(drums["notes"].count(";") + 1, len(T.beat(1)))
        self.assertEqual({n.split(",")[0] for n in drums["notes"].split(";")}, {"32", "33", "34"})   # ReaSynDr's notes
        self.assertIn(("teach_track", {"name": "Vox", "input": 3, "arm": 1, "monitor": 1}), r.calls)
        self.assertIn(("transport", "record"), r.calls)
        self.assertIn(("transport", "stop"), r.calls)
        self.assertIn(("add_fx", "Vox", "ReaComp (Cockos)"), r.calls)

    def test_reaper_reverb_on_a_track_of_its_own(self):
        r = FakeReaper()
        with mock.patch.object(T, "_reaper", return_value=r):
            out = T.run("reaper", "reverb", "fx", {})
        self.assertIn(("add_track", "Reverb"), r.calls)
        self.assertIn(("add_fx", "Reverb", "ReaVerbate (Cockos)"), r.calls)
        self.assertIn(("shown", "Reverb", 0, "Wet", 0), r.calls)
        self.assertIn(("norm", "Reverb", 0, "Dry", 0), r.calls)
        self.assertIn("Wet 0 dB", out["done"])
        self.assertTrue(any("Add new send" in x for x in out["by_hand"]))      # the bridge can't make sends
        a = next(s for c in T.steps("reaper", "101") for s in c["steps"] if s["id"] == "reverb")["action"]
        self.assertEqual(a["fields"], [])
        self.assertIn("Reverb", a["will"])

    def test_reaper_reverb_reuses_the_track_and_the_effect(self):
        r = FakeReaper()
        r.tracks_ = [{"name": "Reverb", "fx": [{"name": "ReaEQ (Cockos)"}, {"name": "VST: ReaVerbate (Cockos)"}]}]
        with mock.patch.object(T, "_reaper", return_value=r):
            out = T.run("reaper", "reverb", "fx", {})
        self.assertFalse([x for x in r.calls if x[0] in ("add_track", "add_fx")])
        self.assertIn(("shown", "Reverb", 1, "Wet", 0), r.calls)
        self.assertTrue(out["done"].startswith("Set ReaVerbate"))

    def test_reaper_saturation(self):
        r = FakeReaper()
        with mock.patch.object(T, "_reaper", return_value=r):
            out = T.run("reaper", "saturation", "fx", {"track": "Bass"})
            with self.assertRaises(ValueError):
                T.run("reaper", "saturation", "fx", {})                           # which track?
        self.assertIn(("add_fx", "Bass", "JS: Saturation"), r.calls)
        self.assertIn(("shown", "Bass", 0, "Amount", 20), r.calls)               # "Amount (%)" refused, "Amount" taken
        self.assertEqual((out["done"], out["by_hand"]), ("Added JS: Saturation to Bass.", []))

    def test_reaper_chain_without_main(self):
        r = FakeReaper(chain_ok=False)
        with mock.patch.object(T, "_reaper", return_value=r):
            out = T.run("reaper", "chain", "chain", {})
        self.assertEqual([x[2] for x in r.calls if x[0] == "add_fx"], ["ReaEQ (Cockos)", "ReaComp (Cockos)", "ReaLimit (Cockos)"])
        self.assertIn("master", out["done"])

    def test_devices(self):
        with mock.patch.object(T, "_cli") as cli:
            T.run("live", "hm-connect-live", "devices", {})
            T.run("reaper", "hm-connect-reaper", "devices", {})
        self.assertEqual([c.args for c in cli.call_args_list], [("probe", "device"), ("device",), ("reaper", "probes", "install")])


def call(base, path, body=None, token=None):
    import urllib.request, urllib.error
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Hypnomix": token} if token else {}, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


class Routes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        cls.td = tempfile.TemporaryDirectory()
        os.environ["HYPNOMIX_APP_HOME"] = cls.td.name
        cls.p = [mock.patch.object(SU, "STATE", Path(cls.td.name) / "setup.json"),
                 mock.patch.object(T, "progress_file", return_value=Path(cls.td.name) / "teacher.json")]
        for x in cls.p:
            x.start()
        from hypnomix.app import server as S
        cls.S = S
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(0))
        port = cls.srv.server_address[1]
        cls.srv.RequestHandlerClass = S.make_handler(port)
        cls.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        import os
        cls.srv.shutdown()
        for x in cls.p:
            x.stop()
        cls.td.cleanup()
        os.environ.pop("HYPNOMIX_APP_HOME", None)

    def test_setup_saves_daw_and_level_and_progress(self):
        tok = self.S.TOKEN
        code, r = call(self.base, "/api/setup/daw", {"daw": "reaper", "teach_level": "tour"}, tok)
        self.assertEqual((code, r), (200, {"daw": "reaper", "teach_level": "tour"}))
        code, st = call(self.base, "/api/teach/state")
        self.assertEqual((st["daw"], st["level"], st["teach"]), ("reaper", "tour", True))
        self.assertEqual([c["id"] for c in st["chapters"]], ["hypnomix"])
        code, st = call(self.base, "/api/teach/state?daw=live&level=101")
        self.assertEqual(st["chapters"][0]["id"], "words")
        code, st = call(self.base, "/api/teach/mark", {"daw": "live", "step": "daw", "at": "tempo", "level": "101"}, tok)
        self.assertEqual((st["done"], st["at"]), (["daw"], "tempo"))
        code, s = call(self.base, "/api/setup/state")
        self.assertEqual((s["daw"], s["teach_level"]), ("reaper", "tour"))
        call(self.base, "/api/setup/daw", {"teach_level": "nonsense"}, tok)
        self.assertEqual(SU.load()["teach_level"], "")
        self.assertFalse(SU.load()["teach"])

    def test_setup_offers_the_complete_course(self):
        tok = self.S.TOKEN
        code, r = call(self.base, "/api/setup/daw", {"daw": "ardour", "teach_level": "az"}, tok)
        self.assertEqual((code, r), (200, {"daw": "ardour", "teach_level": "az"}))
        code, st = call(self.base, "/api/teach/state")
        self.assertEqual((st["level"], st["teach"], st["chapters"][0]["id"]), ("az", True, "sound"))
        self.assertEqual(list(st["levels"]), ["tour", "101", "az"])
        code, s = call(self.base, "/api/setup/state")
        self.assertEqual(s["teach_level"], "az")
        js = __import__("urllib.request").request.urlopen(self.base + "/setup.js").read().decode()
        self.assertIn("data-teach", js)
        self.assertIn("The complete course, A to Z", js)
        call(self.base, "/api/setup/daw", {"daw": "reaper", "teach_level": "tour"}, tok)

    def test_hear_route_serves_a_wav_and_the_glossary(self):
        import urllib.error, urllib.request
        r = urllib.request.urlopen(self.base + "/api/teach/hear?demo=sine-pitch&v=f1k")
        body = r.read()
        self.assertEqual(r.headers["Content-Type"], "audio/wav")
        self.assertEqual(body[:4], b"RIFF")
        self.assertLess(len(body), 44100 * 2 * 2 * 8 + 100)                 # at most about 8 seconds of 16-bit stereo
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(self.base + "/api/teach/hear?demo=nope&v=a")
        self.assertEqual(e.exception.code, 404)
        code, g = call(self.base, "/api/teach/glossary?daw=live")
        self.assertEqual(code, 200)
        self.assertTrue(any(x["term"] == "Compressor" for x in g["terms"]))
        js = urllib.request.urlopen(self.base + "/teacher.js").read().decode()
        for word in ("data-thear", "data-tquiz", "glossaryView", "Common mistakes"):
            self.assertIn(word, js)

    def test_setup_has_one_app_and_hypnomix_daw_is_a_choice_of_daw_not_a_download(self):
        """No "which download" step: the DAW question lists HypnoMix Studio; choosing it saves it and downloads nothing; a stale
        "edition" in a request is ignored and never stored."""
        tok = self.S.TOKEN
        code, s = call(self.base, "/api/setup/state")
        self.assertNotIn("downloads", s)
        self.assertNotIn("installed", s)
        self.assertEqual([d["id"] for d in s["daws"]], ["live", "reaper", "hypnomix", "other"])
        self.assertEqual(next(d for d in s["daws"] if d["id"] == "hypnomix")["title"], "HypnoMix Studio (beta)")
        code, r = call(self.base, "/api/setup/daw", {"daw": "hypnomix", "edition": "full"}, tok)
        self.assertEqual((code, r), (200, {"daw": "hypnomix", "teach_level": ""}))
        self.assertNotIn("edition", SU.load())
        self.assertEqual(call(self.base, "/api/setup/state")[1]["daw"], "hypnomix")
        call(self.base, "/api/setup/daw", {"daw": "nonsense"}, tok)
        self.assertEqual(SU.load()["daw"], "")
        js = __import__("urllib.request").request.urlopen(self.base + "/setup.js").read().decode()
        self.assertNotIn("U.installed", js)

    def test_setup_shows_a_saved_ardour_as_the_hypnomix_tile_and_enables_the_course_buttons_for_both(self):
        """0.3.0's Setup saved 'ardour'; the tile is 'hypnomix' now, and the teacher maps both to the same course."""
        js = __import__("urllib.request").request.urlopen(self.base + "/setup.js").read().decode()
        self.assertIn("daw = U.daw === 'ardour' ? 'hypnomix' : (U.daw || '')", js)
        self.assertIn("${daw === 'other' && id ? 'disabled' : ''}", js)
        self.assertNotIn("daw === 'hypnomix') && id", js)
        self.assertNotIn("if (daw === 'other' || daw === 'hypnomix') teach = ''", js)
        self.assertNotIn("can't drive", js)
        self.assertNotIn("can\\'t drive", js)
        root = Path(__file__).resolve().parent.parent       # sentences true of the other program are not said of this one
        for rel in ("hypnomix/app/lessons/ch13_hypnomix.py", "hypnomix/app/lessons/ch13_hypnomix_steps.py",
                    "hypnomix/app/wiki/articles/18-teacher.html"):
            self.assertNotRegex((root / rel).read_text(encoding="utf-8"), r"(?i)can.t drive", rel)
        for saved in ("ardour", "hypnomix"):
            SU.save(dict(SU.load(), daw=saved, teach_level="tour"))
            self.assertEqual(T.choice()[0], "ardour", saved)

    def test_no_line_of_the_apps_javascript_hides_statements_inside_a_comment(self):
        """setup.js open() once had `// note ... teach = ...; step = ...;` on one line: the note swallowed five state resets and the
        file still parsed. A // comment must not end in what looks like assignment statements, in any of the app's scripts."""
        def tail(line):
            q, i = None, 0
            while i < len(line):
                c = line[i]
                if q:
                    if c == "\\":
                        i += 2
                        continue
                    if c == q:
                        q = None
                elif c in "'\"`":
                    q = c
                elif c == "/" and line[i + 1:i + 2] == "/" and (i == 0 or line[i - 1] != ":"):
                    return line[i + 2:]
                i += 1
            return ""
        root = Path(__file__).resolve().parent.parent / "hypnomix" / "app"
        bad = [f"{f.relative_to(root)}:{n}" for f in root.rglob("*.js")
               for n, l in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
               if re.search(r"\b[A-Za-z_]\w*\s=\s[^=].*;\s*$", tail(l))]
        self.assertEqual(bad, [])
        js = (root / "setup.js").read_text(encoding="utf-8")
        body = js[js.index("async function open(force)"):js.index("function close()")]
        for stmt in ("teach = U.teach_level || ''", "step = force && U.done ? 1 : 0", "msg = null", "liveLog = ''", "cliDone = null"):
            line = next(l for l in body.splitlines() if stmt in l)
            self.assertNotIn("//", line.split(stmt)[0], stmt)          # the statement runs: no comment opens before it

    def test_a_daw_of_the_wrong_kind_is_a_plain_400_not_a_crash(self):
        """A list or a dict where the id belongs (unhashable in a set) was a TypeError out of setup.py: a crash record and a 500."""
        tok = self.S.TOKEN
        for path in ("/api/setup/daw", "/api/setup/finish"):
            for bad in (["a"], {"a": 1}, 7):
                code, r = call(self.base, path, {"daw": bad}, tok)
                self.assertEqual(code, 400, (path, bad, r))
                self.assertIn("wrong kind", r["error"])
        self.assertEqual(call(self.base, "/api/setup/finish", {"daw": None}, tok)[0], 200)
        self.assertEqual(call(self.base, "/api/setup/daw", {"daw": "reaper"}, tok)[1]["daw"], "reaper")

    def test_actions_need_an_ok(self):
        code, r = call(self.base, "/api/teach/do", {"daw": "live", "step": "tempo", "kind": "tempo", "args": {"bpm": 90}}, self.S.TOKEN)
        self.assertEqual(code, 400)
        self.assertIn("OK", r["error"])
        code, r = call(self.base, "/api/teach/do", {"ok": True, "daw": "ardour", "step": "tempo", "kind": "tempo"}, self.S.TOKEN)
        self.assertEqual(code, 400)
        code, r = call(self.base, "/api/teach/do", {"ok": True, "daw": "live", "step": "tempo", "kind": "tempo"})  # no token
        self.assertEqual(code, 403)

    def test_page_has_the_tab(self):
        import urllib.request
        page = urllib.request.urlopen(self.base + "/").read().decode()
        self.assertIn('data-view="teach"', page)
        tabs = re.findall(r'<button class="tab" data-view="(\w+)"', page)
        self.assertEqual(tabs.index("teach"), tabs.index("wiki") + 1)             # the owner asked for this: Teacher sits right after Wiki, not first
        self.assertEqual(tabs[0], "home")                                            # Songs comes first
        self.assertIn("/teacher.js", page)
        js = urllib.request.urlopen(self.base + "/teacher.js").read().decode()
        self.assertIn("teachView", js)


class Wiki(unittest.TestCase):
    def test_courses_are_wiki_articles_under_their_daw(self):
        from hypnomix.app import wiki
        arts = {a["id"]: a for a in wiki.local()}
        for d, g in (("live", "DAW: Ableton Live"), ("reaper", "DAW: REAPER"), ("ardour", "DAW: HypnoMix Studio")):
            self.assertEqual(arts[f"learn-{d}"]["group"], g)
            self.assertEqual(arts[f"tour-{d}"]["group"], g)
        self.assertIn("teacher", arts)


if __name__ == "__main__":
    unittest.main()
