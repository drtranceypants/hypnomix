"""Teacher mode (hypnomix/app/teacher.py): the two courses per DAW, the hands-on actions, and their routes."""
import json, tempfile, threading, unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from hypnomix.app import setup as SU
from hypnomix.app import teacher as T


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
            raise ReaperError("chain_build: no Hypnomix Main on the master")
        return {"teach_tempo": {"bpm": a.get("bpm")}, "teach_click": {"on": True}, "teach_drums": {"fx": 0, "notes": 3}}.get(cmd, {})
    def transport(self, go=None, at=None): self.calls.append(("transport", go))
    def add_fx(self, track, name): self.calls.append(("add_fx", track, name)); return {"fx": 0}
    def named(self, track, fx, key, value=None): self.calls.append(("named", key, value))
    def set_shown(self, track, fx, p, v): self.calls.append(("shown", p, v))


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

    def test_live_deepest_ardour_shortest(self):
        for lv in T.LEVELS:
            self.assertGreater(T.count("live", lv), T.count("ardour", lv))
            self.assertGreaterEqual(T.count("reaper", lv), T.count("ardour", lv))
        self.assertGreater(T.count("live", "101"), T.count("reaper", "101"))

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
        self.assertIn("Hypnomix Main", a["text"])
        b = T.wiki_article("live", "101")
        self.assertEqual(b["id"], "learn-live")
        self.assertIn("EQ Eight", b["text"])
        self.assertTrue(b["generated"])

    def test_assistant_note_follows_the_level(self):
        with mock.patch.object(T, "choice", return_value=("live", "", "key")):
            self.assertEqual(T.assistant_note(), "")
        with mock.patch.object(T, "choice", return_value=("live", "tour", "key")):
            self.assertIn("already knows", T.assistant_note())
        with mock.patch.object(T, "choice", return_value=("reaper", "101", "key")):
            self.assertIn("beginner", T.assistant_note())


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
        self.assertIn("/teacher.js", page)
        js = urllib.request.urlopen(self.base + "/teacher.js").read().decode()
        self.assertIn("teachView", js)


class Wiki(unittest.TestCase):
    def test_courses_are_wiki_articles_under_their_daw(self):
        from hypnomix.app import wiki
        arts = {a["id"]: a for a in wiki.local()}
        for d, g in (("live", "DAW: Ableton Live"), ("reaper", "DAW: REAPER"), ("ardour", "DAW: Ardour")):
            self.assertEqual(arts[f"learn-{d}"]["group"], g)
            self.assertEqual(arts[f"tour-{d}"]["group"], g)
        self.assertIn("teacher", arts)


if __name__ == "__main__":
    unittest.main()
