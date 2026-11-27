"""How far a fix goes, and in which key a song is tuned, are the person's to set.

- Lead mode's strength defaults to halfway on the command line too (the Align device and panel already did).
- Timing and tuning findings start at a saved amount (Preferences: taste.timing_amount, taste.tuning_amount), each has
  its own slider, the previews are made at that amount, and the Live device and the REAPER panel can change it. An
  amount only scales the tool's own gentle proposal down: nothing passes the tool's caps.
- The review shows the key the scan detected and lets the person choose another (a note and major or minor): the
  song's tuning findings are proposed again in it, only the tuning check runs, and the key is saved for the song."""
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import soundfile as sf

from hypnomix.workflow import oversight as O
from tests.test_align import NOTES, voice
from tests.test_app import call

ROOT = Path(__file__).resolve().parents[1]
TIMING = dict(id="timing-1", tool="timing", kind="late", severity="low", track="Bass", where="12.3.50", applies="set",
              problem="lands 32 ms late", fix="nudge it")
TUNE = dict(id="tune-Lead", tool="tune", kind="pitch", severity="medium", track="Lead", where="whole take",
            applies="audio", problem="median 22 cents off", fix="tune 9 notes", key="C major",
            key_source="estimated from the vocal, fit 0.71; confirm with --key")
CLICK = dict(id="smooth-1", tool="smooth", kind="click", severity="low", track="Bass", where="12.3.50", applies="set",
             problem="click at a clip edge", fix="4 ms fade")
RENAME = dict(id="name-1", tool="name", kind="track-name", severity="low", track="Audio 3", applies="set", problem="", fix="")


class Halfway(unittest.TestCase):
    def test_lead_strength_defaults_to_halfway_and_all_the_way_is_a_flag(self):
        from hypnomix.studio import vocalign as V
        ap = V.build_parser()
        self.assertEqual(ap.parse_args(["l.wav", "d.wav"]).strength, 0.5)
        self.assertEqual(ap.parse_args(["l.wav", "d.wav", "--strength", "1"]).strength, 1.0)
        with self.assertRaises(SystemExit):
            ap.parse_args(["l.wav", "d.wav", "--strength", "1.5"])           # never past all the way
        self.assertIn("default 0.5", ap.format_help())
        from hypnomix.app import align as AL                                 # the device's dial at its starting value
        self.assertIn("--strength 0.50", " ".join(AL.argv_for(dict(guide="L", parts=["D"], tightness=0.5), "/x.als", "/tmp/o")))


class Amounts(unittest.TestCase):
    def test_timing_and_tuning_start_at_the_saved_amount_and_the_rest_at_100(self):
        prefs = {"taste": {"timing_amount": 60, "tuning_amount": 40}}
        self.assertEqual(O.default_amount(TIMING, prefs), 60)
        self.assertEqual(O.default_amount(TUNE, prefs), 40)
        self.assertEqual(O.default_amount(CLICK, prefs), 100)                # only the two kinds have a saved start
        self.assertEqual(O.default_amount(TIMING, {}), 100)
        self.assertEqual(O.default_amount(RENAME, prefs), 100)
        self.assertEqual(O.effective_amount(TIMING, {"decision": "approve"}, prefs), 60)     # slider never touched
        self.assertEqual(O.effective_amount(TIMING, {"decision": "approve", "amount": 85}, prefs), 85)   # its own slider wins
        self.assertEqual(O.effective_amount(TIMING, {"decision": "approve", "amount": 0}, prefs), 0)
        self.assertEqual(O.effective_amount(TIMING, None, prefs), 60)
        self.assertEqual(O.effective_amount(RENAME, {"decision": "approve", "amount": 30}, prefs), 100)   # all or nothing
        e = O.extras(TUNE, prefs=prefs, teach_on=False)
        self.assertEqual((e["scalable"], e["default_amount"], e["amount_pref"]), (True, 40, "taste.tuning_amount"))
        self.assertNotIn("default_amount", O.extras(RENAME, prefs=prefs, teach_on=False))

    def test_no_amount_passes_the_tools_own_caps(self):
        for amt in range(0, 101):
            for flags in (O.amount_flags("tune", amt), O.amount_flags("timing", amt)):
                if flags:
                    self.assertEqual(len(flags), 2)
                    self.assertLessEqual(float(flags[1]), 0.35 if flags[0] == "--amount" else 1.0)
        self.assertEqual(O.amount_flags("tune", 100), [])                    # 100 = the tool's own proposal: 35%, 25 cents at most
        self.assertEqual(O.amount_flags("tune", 50), ["--amount", "0.1750"])
        self.assertEqual(O.amount_flags("timing", 50), ["--strength", "0.5000"])
        from hypnomix.studio import tune as T                                # the tuner's own gentle defaults stand
        src = Path(T.__file__).read_text(encoding="utf-8")
        self.assertIn("[--amount 0.35]", src)

    def test_the_two_preferences_take_whole_numbers_from_0_to_100(self):
        from hypnomix.workflow import prefs as P
        keys = {q["key"]: q for q in P.QUESTIONS}
        for k in ("taste.timing_amount", "taste.tuning_amount"):
            self.assertEqual(keys[k]["default"], 100)
            self.assertEqual(P.parse(k, "50"), 50)
            for bad in ("120", "-5", "lots", "12.5"):
                with self.assertRaises(P.PrefError):
                    P.parse(k, bad)

    def test_previews_are_made_at_the_amount(self):
        from hypnomix.workflow import ab as AB
        with tempfile.TemporaryDirectory() as td:
            sd = Path(td)
            self.assertEqual(AB.amount_for(sd, TIMING), 100)
            (sd / "decisions.json").write_text(json.dumps({"timing-1": {"decision": "approve", "amount": 50},
                                                           "tune-Lead": {"decision": "approve", "amount": 0}}), encoding="utf-8")
            self.assertEqual(AB.amount_for(sd, TIMING), 50)
            self.assertEqual(AB.amount_for(sd, TUNE), 1)                     # a preview of nothing is never made
            args = AB.timing_args(sd, "Song.als", "tmp.als", ["timing-1"], False, 50)
            self.assertEqual(args[args.index("--strength") + 1], "0.5000")
            self.assertNotIn("--strength", AB.timing_args(sd, "Song.als", "tmp.als", ["timing-1"], False))
        src = Path(AB.__file__).read_text(encoding="utf-8")
        self.assertIn('O.amount_flags("tune", amt)', src)

    def test_the_card_the_device_and_the_panel_have_the_control(self):
        from hypnomix.workflow import review as RV
        page = Path(RV.__file__).read_text(encoding="utf-8")
        for bit in ("e.default_amount", "data-remake", "starts at your saved", "of the proposed move"):
            self.assertIn(bit, page)
        from hypnomix.app import device as D
        for bit in ('"Amount " + c.amount + "%"', '"/api/live/amount"'):
            self.assertIn(bit, D.JS)
        lua = (ROOT / "hypnomix" / "reaper" / "bridge.lua").read_text(encoding="utf-8")
        self.assertIn('st.scalable == "1"', lua)
        self.assertIn('"amount")', lua)
        app_js = (ROOT / "hypnomix" / "app" / "review.js").read_text(encoding="utf-8")
        for bit in ("'/api/ab/remake'", "'/api/retune'", "keyInfo: R.key_info"):
            self.assertIn(bit, app_js)


class TheApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.old = os.environ.get("HYPNOMIX_APP_HOME")
        os.environ["HYPNOMIX_APP_HOME"] = cls.td.name
        from hypnomix.app import server as S
        cls.S = S
        d = Path(cls.td.name) / "scan" / "Song"
        d.mkdir(parents=True)
        (d / "findings.json").write_text(json.dumps(dict(set="/nowhere/Song.als", findings=[TIMING, TUNE, RENAME], notes=[])),
                                         encoding="utf-8")
        cls.dir = str(d)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(0))
        port = cls.srv.server_address[1]
        cls.srv.RequestHandlerClass = S.make_handler(port)
        cls.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.td.cleanup()
        if cls.old is None:
            os.environ.pop("HYPNOMIX_APP_HOME", None)
        else:
            os.environ["HYPNOMIX_APP_HOME"] = cls.old

    def test_the_device_steps_the_amount_and_a_decision_keeps_it(self):
        call(self.base, "/api/review?dir=" + urllib.request.quote(self.dir))
        cur = None
        for _ in range(4):                                                   # walk to the timing finding
            _, cur, _ = call(self.base, "/api/live/step", dict(delta=1))
            if cur["id"] == "timing-1":
                break
        self.assertEqual((cur["id"], cur["scalable"], cur["amount"]), ("timing-1", True, 100))
        seen = []
        for _ in range(4):
            _, cur, _ = call(self.base, "/api/live/amount", dict(step=1))
            seen.append(cur["amount"])
        self.assertEqual(seen, [25, 50, 75, 100])
        _, cur, _ = call(self.base, "/api/live/amount", dict(amount=40))
        self.assertEqual((cur["amount"], cur["decision"]), (40, "approve"))
        _, cur, _ = call(self.base, "/api/live/decide", dict(decision="approve"))
        self.assertEqual(cur["amount"], 40)                                  # the amount stays with the decision
        code, _, _ = call(self.base, "/api/live/amount", dict(amount=140))
        self.assertEqual(code, 400)
        for _ in range(4):
            _, cur, _ = call(self.base, "/api/live/step", dict(delta=1))
            if cur["id"] == "name-1":
                break
        self.assertEqual((cur["id"], cur["scalable"]), ("name-1", False))
        code, r, _ = call(self.base, "/api/live/amount", dict(step=1))
        self.assertEqual(code, 400)
        self.assertIn("all or nothing", r["error"])

    def test_the_review_says_which_key_and_refuses_a_key_that_is_not_one(self):
        _, r, _ = call(self.base, "/api/review?dir=" + urllib.request.quote(self.dir))
        k = r["key_info"]
        self.assertEqual((k["detected"], k["confirmed"]), ("C major", ""))
        self.assertEqual(k["source"], "estimated from the vocal, fit 0.71")
        self.assertEqual((len(k["notes"]), k["scales"]), (12, ["major", "minor"]))
        code, r, _ = call(self.base, "/api/retune", dict(dir=self.dir, key="H dorian"), self.S.TOKEN)
        self.assertEqual(code, 400)
        self.assertIn("not a key", r["error"])
        code, r, _ = call(self.base, "/api/ab/remake", dict(dir=self.dir, id="nope-9"), self.S.TOKEN)
        self.assertEqual(code, 400)


class Retune(unittest.TestCase):
    """The tuning check alone, again, in the chosen key, on a short synthetic vocal (8 s)."""
    def test_the_tuning_is_proposed_again_in_the_chosen_key_and_saved_for_the_song(self):
        from hypnomix.workflow import scan as SC
        self.assertEqual(SC.key_name("eb Minor"), "D# minor")
        self.assertEqual(SC.key_name("a"), "A major")
        for bad in ("", "H minor", "C dorian", "C major please"):
            with self.assertRaises(ValueError):
                SC.key_name(bad)
        with tempfile.TemporaryDirectory() as td:
            od = Path(td) / "Song"
            (od / "raw" / "renders").mkdir(parents=True)
            wav = od / "raw" / "renders" / "Lead.wav"
            sf.write(wav, voice(NOTES, cents=18), 44100, subtype="PCM_16")
            other = dict(id="doubles-1", tool="vocalign", kind="vocal-timing", severity="low", track="Double",
                         problem="sits 30 ms from the lead", fix="nudge", applies="manual")
            tune = dict(TUNE, input=str(wav))
            (od / "vocals.json").write_text(json.dumps(dict(group="vocals", set=str(od / "Song.als"), seconds=1.0,
                                                            findings=[tune, other], notes=["vocals: key C major (confirm it)"])),
                                            encoding="utf-8")
            (od / "scan.json").write_text(json.dumps(dict(set=str(od / "Song.als"), mode="set", key=None, lead="Lead")),
                                          encoding="utf-8")
            SC.merge(od)
            (od / "decisions.json").write_text(json.dumps({"doubles-1": {"decision": "skip", "note": "", "at": "x", "by": "me"}}),
                                               encoding="utf-8")
            key, n = SC.retune(od, "a minor")
            self.assertEqual((key, n), ("A minor", 1))
            data = json.loads((od / "findings.json").read_text(encoding="utf-8"))
            by = {f["id"]: f for f in data["findings"]}
            self.assertEqual(by["tune-Lead"]["key"], "A minor")
            self.assertEqual(by["tune-Lead"]["key_source"], "given")
            self.assertIn("doubles-1", by)                                   # every other finding stays
            info = json.loads((od / "scan.json").read_text(encoding="utf-8"))
            self.assertEqual((info["key"], info["key_confirmed"]), ("A minor", True))
            self.assertEqual(info["key_detected"]["key"], "C major")         # what the scan heard is kept beside it
            self.assertIn("skip", json.dumps(json.loads((od / "decisions.json").read_text(encoding="utf-8"))["doubles-1"]))
            self.assertTrue(any("key A minor" in x for x in data["notes"]))
            SC.retune(od, "C major")                                         # and back: the detected key is not overwritten
            info = json.loads((od / "scan.json").read_text(encoding="utf-8"))
            self.assertEqual((info["key"], info["key_detected"]["key"]), ("C major", "C major"))
            wav.unlink()
            with self.assertRaises(ValueError):
                SC.retune(od, "G major")

    def test_the_card_shows_the_key_and_in_the_app_lets_it_be_chosen(self):
        from hypnomix.workflow import review as RV
        page = Path(RV.__file__).read_text(encoding="utf-8")
        for bit in ("function ovKeyHTML", "data-keynote", "data-keyscale", "data-retune", "The scan detected",
                    "The chord under every note is still checked"):
            self.assertIn(bit, page)
        from hypnomix.app import server as S
        self.assertIsNone(S.key_info([CLICK], {}))                            # no tuning findings: nothing to show
        k = S.key_info([TUNE], {"key": "A minor", "key_detected": {"key": "C major", "source": "estimated from the vocal, fit 0.71"}})
        self.assertEqual((k["detected"], k["confirmed"]), ("C major", "A minor"))


if __name__ == "__main__":
    unittest.main()
