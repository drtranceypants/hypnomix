"""Performance fixes in the app: the "like this" map, the long review, the Songs poll, the Activity log, the Wiki and the
gzip of big answers. Each test pins the WORK done (calls counted with a stub, sizes of the answers, bytes asked for),
never a wall-clock time, and each says what must stay the same: the findings, the counts and the files written."""
import gzip
import http.client as hc
import json
import os
import random
import re
import shutil
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from hypnomix.workflow import oversight as O, review as RV, scan as SC


# ---------------------------------------------------------------- the "like this" map
def mixed(n, seed=1):
    """Findings of several tools, kinds, severities, roles and sizes (some with none), some protected."""
    rnd = random.Random(seed)
    kinds = [("smooth", "click", "set"), ("smooth", "click", "set"), ("smooth", "cut", "set"), ("timing", "late", "set"),
             ("masking", "masking", "manual"), ("tune", "pitch", "audio"), ("measure", "loudness", "info"), ("key", "key", "answer")]
    out = []
    for i in range(n):
        tool, kind, applies = rnd.choice(kinds)
        f = dict(id=f"{tool}-{i + 1}", n=i + 1, tool=tool, kind=kind, applies=applies,
                 severity=rnd.choice(["low", "low", "medium", "high", "info"]), track=rnd.choice(["T0", "T1", "T2", "T3", None, "Unknown"]),
                 problem=rnd.choice([f"click of {rnd.uniform(1, 12):.1f} dB", f"{rnd.randint(5, 60)} ms late", "no number here"]))
        if applies == "answer":
            f["notes"] = ["F#", "G"]
        if rnd.random() < 0.15:
            f["protected"] = True
        if rnd.random() < 0.1:
            f["size"] = rnd.choice([0.0, 3.0, 3.1])
        out.append(f)
    return out


ROLES = {"T0": "bass", "T1": "keys", "T2": "", "T3": "bass"}          # one track has an empty role, two have none at all


def alike(n):
    return [dict(id=f"smooth-{i + 1}", tool="smooth", kind="click", applies="set", severity="low", track=f"T{i % 4}",
                 problem=f"click of {4 + (i % 50) / 25:.2f} dB") for i in range(n)]


class LikeRanges(unittest.TestCase):
    def test_the_fast_map_is_the_plain_definition(self):
        for seed in range(1, 7):
            fs = mixed(220, seed)
            for band in (0.5, 0.1):
                self.assertEqual(RV.like_map(fs, ROLES, band), RV.like_pairs(fs, ROLES, band), (seed, band))
        self.assertTrue(any(RV.like_pairs(mixed(220, 1), ROLES).values()), "the fixture must have findings that are like each other")

    def test_ids_that_repeat_and_sizes_that_are_not_numbers_take_the_plain_way(self):
        fs = mixed(60, 3)
        dup = fs + [dict(fs[0])]
        self.assertEqual(RV.like_map(dup, ROLES), RV.like_pairs(dup, ROLES))
        nan = mixed(60, 4)
        nan[5].update(tool="smooth", kind="click", applies="set", size=float("nan"))
        self.assertEqual(RV.like_map(nan, ROLES), RV.like_pairs(nan, ROLES))

    def test_no_pair_is_looked_at(self):
        """oversight.like() (every finding against its whole group) is never called, and each size is read once."""
        fs = alike(400)
        with mock.patch.object(O, "like", side_effect=AssertionError("pairs")), mock.patch.object(O, "size", wraps=O.size) as sz:
            runs, order = RV.like_ranges(fs, ROLES)
        self.assertLessEqual(sz.call_count, len(fs))
        self.assertEqual(sorted(order), sorted(f["id"] for f in fs))

    def test_the_answer_grows_with_the_findings_not_their_square(self):
        small, big = RV.like_ranges(alike(250), ROLES)[0], RV.like_ranges(alike(1000), ROLES)[0]
        self.assertTrue(all(len(r) <= 4 for r in big.values()))               # a range or two each (the finding itself splits one)
        self.assertLess(len(json.dumps(big)), 6 * len(json.dumps(small)))      # 4x the findings: about 4x the size (every list was 16x)
        self.assertGreater(sum(RV.like_counts(big).values()), 100000)            # ... for the same 100,000+ "like this" pairs

    def test_the_counts_are_the_lengths_of_the_lists(self):
        fs = mixed(250, 5)
        runs, _ = RV.like_ranges(fs, ROLES)
        self.assertEqual(RV.like_counts(runs), {k: len(v) for k, v in RV.like_pairs(fs, ROLES).items()})

    def test_review_md_says_the_same_numbers(self):
        """REVIEW.md's "N like it" comes from the counts now: every item's lines are the same as from the full lists."""
        td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        fs = mixed(120, 2)
        names = td / "raw" / "names"
        names.mkdir(parents=True)
        (names / "names.json").write_text(json.dumps({"tracks": [{"old": k, "final": f"{v or 'x'} {k}"} for k, v in ROLES.items()]}), encoding="utf-8")
        from hypnomix.workflow import prefs as P
        prefs = P.load()
        ov_map = RV.oversight_payload(td, fs, prefs, like="map")
        ov_cnt = RV.oversight_payload(td, fs, prefs, like="count")
        self.assertNotIn("like", ov_cnt)
        kc = SC.kind_context(fs, ov_map)
        saw = 0
        for f in fs:
            a, b = SC.item_lines(f, ov_map, lambda t: t or "-", kc), SC.item_lines(f, ov_cnt, lambda t: t or "-", kc)
            self.assertEqual(a, b, f["id"])
            saw += sum(" like it" in x for x in a)
        self.assertGreater(saw, 10)

    def test_the_question_budget_is_not_squared(self):
        fs = mixed(300, 6)
        got = O.budget(fs, 25)
        order = sorted(fs, key=lambda f: (O.SEV.get(f.get("severity"), 9), -O.confidence(f)[0], f.get("n", 0)))
        acts = [f for f in order if f.get("applies") != "info"]
        must = [f for f in acts if f.get("severity") == "high" or f.get("protected") or f.get("applies") == "answer"]
        rest = [f for f in acts if f not in must]                          # the old way, whole findings compared with each other
        ask = {f["id"] for f in must} | {f["id"] for f in rest[:max(0, 25 - len(must))]}
        self.assertEqual(([f["id"] for f in got[0]], [f["id"] for f in got[1]]),
                         ([f["id"] for f in acts if f["id"] in ask], [f["id"] for f in acts if f["id"] not in ask]))


# ---------------------------------------------------------------- the app's server
def req(port, path, body=None, headers=None, token=None):
    """One request (POST when there is a body): (status, body bytes, headers with lower-case names)."""
    c = hc.HTTPConnection("127.0.0.1", port, timeout=10)
    h = dict(headers or {})
    if token:
        h["X-Hypnomix"] = token
    c.request("POST" if body is not None else "GET", path, json.dumps(body) if body is not None else None, h)
    r = c.getresponse()
    data = r.read()
    out = (r.status, data, {k.lower(): v for k, v in r.getheaders()})
    c.close()
    return out


def get_(port, path, headers=None):
    return req(port, path, None, headers)


class AppServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.env = mock.patch.dict(os.environ, {"HYPNOMIX_APP_HOME": cls.td.name})
        cls.env.start()
        from hypnomix.app import server as S
        cls.S = S
        d = Path(cls.td.name) / "scan" / "Song"
        d.mkdir(parents=True)
        fs = alike(300)
        (d / "findings.json").write_text(json.dumps(dict(set="/nowhere/Song.als", notes=[], findings=fs)), encoding="utf-8")
        (d / "scan.json").write_text(json.dumps(dict(set="/nowhere/Song.als", mode="set")), encoding="utf-8")
        cls.dir = str(d)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(0))
        cls.port = cls.srv.server_address[1]
        cls.srv.RequestHandlerClass = S.make_handler(cls.port)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.env.stop()
        cls.td.cleanup()

    def test_a_big_answer_is_gzipped_for_a_browser_that_takes_it_and_only_then(self):
        path = "/api/review?dir=" + self.dir.replace("/", "%2F")
        code, plain, h0 = get_(self.port, path)
        self.assertEqual(code, 200)
        self.assertNotIn("content-encoding", h0)
        self.assertEqual(h0["vary"], "Accept-Encoding")
        code, packed, h1 = get_(self.port, path, headers={"Accept-Encoding": "gzip, deflate, br"})
        self.assertEqual((code, h1["content-encoding"], int(h1["content-length"])), (200, "gzip", len(packed)))
        self.assertEqual(json.loads(gzip.decompress(packed)), json.loads(plain))           # the page reads exactly what it did
        self.assertLess(len(packed), len(plain) / 5)
        _, refused, h2 = get_(self.port, path, headers={"Accept-Encoding": "gzip;q=0"})
        self.assertNotIn("content-encoding", h2)
        self.assertEqual(refused, plain)

    def test_gzip_body_rules(self):
        G = self.S.gzip_body
        big = b'{"a": "' + b"x" * 5000 + b'"}'
        self.assertEqual(gzip.decompress(G(big, "application/json", "gzip")), big)
        self.assertEqual(gzip.decompress(G(big, "text/javascript; charset=utf-8", "br, gzip;q=0.5")), big)
        self.assertIsNone(G(b"{}", "application/json", "gzip"))                            # small: not worth it
        self.assertIsNone(G(big, "application/json", None))
        self.assertIsNone(G(big, "application/json", "identity"))
        self.assertIsNone(G(big, "audio/wav", "gzip"))                                      # audio and pictures are never touched
        self.assertIsNone(G(big, "text/html; charset=utf-8", "gzip"))
        self.assertIsNone(G(big, "application/json", "gzip;q=0"))

    def test_an_unchanged_state_costs_a_few_bytes(self):
        code, first, _ = get_(self.port, "/api/state")
        st = json.loads(first)
        self.assertTrue(st["rev"])
        code, again, _ = get_(self.port, "/api/state?rev=" + st["rev"])
        self.assertEqual(json.loads(again), {"rev": st["rev"], "same": True})
        self.assertLess(len(again), 80)
        self.assertLess(len(again), len(first) / 5)
        # a decision changes what the Songs list says: the next ask gets the whole state again, with a new rev
        c, _, _ = req(self.port, "/api/decide", dict(dir=self.dir, id="smooth-1", decision="approve"), token=self.S.TOKEN)
        self.assertEqual(c, 200)
        _, third, _ = get_(self.port, "/api/state?rev=" + st["rev"])
        t = json.loads(third)
        self.assertNotIn("same", t)
        self.assertNotEqual(t["rev"], st["rev"])
        self.assertEqual({k: v for k, v in t.items() if k not in ("rev", "scans")}, {k: v for k, v in st.items() if k not in ("rev", "scans")})
        self.assertEqual(t["scans"][0]["approved"], 1)

    def test_the_state_with_a_rev_says_exactly_what_it_said_before(self):
        st = {"scans": [{"name": "Song", "when": "2026-11-26", "findings": 3}], "job": {"id": 0, "status": "idle"}, "live": False,
              "home": "/x", "n": None, "path": Path("/p")}
        got = json.loads(self.S.state_reply(st))
        rev = got.pop("rev")
        self.assertEqual(got, json.loads(json.dumps(st, default=str)))
        self.assertEqual(self.S.state_reply(st, rev), {"rev": rev, "same": True})
        self.assertNotEqual(json.loads(self.S.state_reply(dict(st, live=True)))["rev"], rev)

    def test_a_note_comes_back_as_its_findings_notes(self):
        for n, text in enumerate(("first", "second"), 1):
            code, body, _ = req(self.port, "/api/note", dict(dir=self.dir, id="smooth-2", text=text), token=self.S.TOKEN)
            self.assertEqual(code, 200)
            notes = json.loads(body)["notes"]
            self.assertEqual([x["text"] for x in notes], ["first", "second"][:n])
        # the page does not fetch the whole review to show it
        js = (Path(self.S.__file__).with_name("review.js")).read_text(encoding="utf-8")
        body = re.search(r"async function addNote\(.*?\n}\n", js, re.S).group(0)
        self.assertNotIn("/api/review", body)

    def test_the_review_asks_for_ranges_not_for_every_list(self):
        code, body, _ = get_(self.port, "/api/review?dir=" + self.dir.replace("/", "%2F"))
        ov = json.loads(body)["oversight"]
        self.assertNotIn("like", ov)
        self.assertIn("like_runs", ov)
        self.assertEqual(sorted(ov["like_order"]), sorted(f["id"] for f in alike(300)))
        self.assertLess(len(body), 1200 * 300)                                              # 300 alike findings: well under 400 KB (the lists were 4 MB)



# ---------------------------------------------------------------- the Activity log
class FakeJob:
    """What popen_job returns: output that arrives line by line, and a hook run between lines (in the job's own thread)."""
    def __init__(self, lines, between=None):
        self.stdout = self._lines(lines, between)

    @staticmethod
    def _lines(lines, between):
        for i, x in enumerate(lines):
            if between:
                between(i)
            yield x + "\n"

    def wait(self, timeout=None):
        return 0


class JobLog(unittest.TestCase):
    def setUp(self):
        from hypnomix.app import server as S
        self.S = S
        self.td = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"HYPNOMIX_APP_HOME": self.td.name})
        self.env.start()
        self.old = {k: S.JOB[k] for k in ("status", "log", "dropped")}

    def tearDown(self):
        self.S.JOB.update(self.old)
        self.env.stop()
        self.td.cleanup()

    def run_job(self, lines, between=None):
        S = self.S
        with mock.patch.object(S, "popen_job", lambda argv: FakeJob(lines, between)):
            S.run_job("tool", "fake", [("fake", ["fake"], True)])
            for _ in range(400):
                if S.JOB["status"] != "running":
                    break
                time.sleep(0.05)
        self.assertEqual(S.JOB["status"], "done")

    def test_a_page_that_keeps_up_sees_every_line_including_the_last(self):
        lines = [f"line {i}" for i in range(6000)]
        seen = {"lines": [], "skipped": 0, "at": 0}

        def poll(_=None):                                    # what the page does: ask for everything after the last total
            total, got, skipped = self.S.log_since(seen["at"])
            seen["lines"] += got
            seen["skipped"] += skipped
            seen["at"] = total
        self.run_job(lines, lambda i: poll() if i % 500 == 0 else None)
        poll()
        self.assertEqual(seen["lines"], ["$ hypnomix fake"] + lines)
        self.assertEqual(seen["skipped"], 0)

    def test_a_page_that_looks_late_gets_the_newest_lines_and_is_told_how_many_it_missed(self):
        lines = [f"line {i}" for i in range(6000)]
        self.run_job(lines)
        total, got, skipped = self.S.log_since(0)
        self.assertEqual(total, 6001)                                                       # the "$ hypnomix" line and the 6,000
        self.assertEqual(got[-1], "line 5999")                                              # the end of the output is never lost
        self.assertEqual(skipped + len(got), total)
        self.assertGreater(skipped, 0)
        self.assertLessEqual(len(got), self.S.LOG_KEEP)
        # asked again from where it was: nothing more, nothing missed
        self.assertEqual(self.S.log_since(total), (total, [], 0))
        # a page that is partway (it has the first 3,500) is told it missed the lines that were let go before its next ask
        _, got2, skipped2 = self.S.log_since(3500)
        self.assertEqual(got2[-1], "line 5999")
        self.assertEqual(skipped2 + len(got2), total - 3500)

    def test_the_page_script_says_so_when_lines_were_left_out(self):
        from hypnomix.app import ui
        self.assertIn("older line", ui.PAGE)
        self.assertIn("j.skipped", ui.PAGE)


# ---------------------------------------------------------------- the long review (the page script)
class ReviewScript(unittest.TestCase):
    """The page script cannot be run here (no JavaScript engine is assumed): these keep the pieces that make a long review cheap
    from being taken out. The behaviour itself (nodes built, the keys, the counts) was checked in a browser on 2,000 findings."""
    @classmethod
    def setUpClass(cls):
        from hypnomix.app import server
        cls.js = Path(server.__file__).with_name("review.js").read_text(encoding="utf-8")

    def test_a_long_list_is_built_a_page_at_a_time_and_a_short_one_whole(self):
        js = self.js
        self.assertRegex(js, r"const LAZY_ABOVE = 150, PAGE = 100, SMALL = 40;")
        group = re.search(r"function sevGroups\(.*?\n}\n", js, re.S).group(0)
        self.assertIn("if (!S.rv.lazy) return", group)                              # below the limit: every card, as before
        self.assertIn("g.slice(0, lg.built).map(cardHTML)", group)                  # above it: the built ones only
        self.assertIn("S.rv.lazy = shown.length + handShown.length + inBatch.size > LAZY_ABOVE", js)

    def test_the_keys_and_the_counts_read_the_findings_not_the_page(self):
        js = self.js
        self.assertIn("function revealId(", js)
        self.assertIn("revealId(id)", re.search(r"function setCur\(.*?\n}\n", js, re.S).group(0))     # a key that reaches a card builds it
        self.assertIn("seqOpen(", re.search(r"function jumpOpen\(.*?\n}\n", js, re.S).group(0))
        # one find() per card was squared work: the index is a Map
        self.assertIn("new Map(fl.map(f => [f.id, f]))", js)
        # the "N like this" counts are looked up from ranges on the cards that exist, not from lists on every card
        self.assertIn("ov.like_runs", re.search(r"function likeAffected\(.*?\n}\n", js, re.S).group(0))


# ---------------------------------------------------------------- the Wiki
class WikiWork(unittest.TestCase):
    def setUp(self):
        from hypnomix.app import wiki
        self.wiki = wiki
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        self.p = [mock.patch.object(wiki, "HOME", self.td), mock.patch.dict(os.environ, {"no_proxy": "127.0.0.1", "NO_PROXY": "127.0.0.1"})]
        for x in self.p:
            x.start()
            self.addCleanup(x.stop)
        wiki._PARSED.clear()
        wiki._GIT.clear()
        self.addCleanup(wiki._PARSED.clear)
        self.addCleanup(wiki._GIT.clear)
        wiki._LIVE.update(checked=0, busy=False, error=None)
        self.live = self.td / "wiki-live" / "articles.json"
        self.live.parent.mkdir(parents=True)

    def write_live(self, n, tag="a", age=100):
        doc = {"commit_time": 5, "assets": [], "articles": [{"id": f"{tag}{i}", "title": f"Article {i}", "html": "<p>x</p>", "text": "x " * 50}
                                                          for i in range(n)]}
        self.live.write_text(json.dumps(doc), encoding="utf-8")
        t = time.time_ns() - age * 10**9
        os.utime(self.live, ns=(t, t))

    def test_the_site_copy_is_read_once_not_on_every_request(self):
        wiki = self.wiki
        self.write_live(40)
        with mock.patch.object(wiki, "tidy", wraps=wiki.tidy) as tidy:
            first = wiki.live()
            for _ in range(6):
                self.assertIs(wiki.live(), first)
            self.assertEqual(tidy.call_count, 40)
            self.write_live(40, tag="b", age=50)                                        # a changed file (same size) is read again
            self.assertEqual([a["id"] for a in wiki.live()["articles"]][:2], ["b0", "b1"])
            self.assertEqual(tidy.call_count, 80)
            self.write_live(40, tag="c", age=0)                                         # one written this second is never trusted to the key alone
            wiki.live()
            wiki.live()
            self.assertEqual(tidy.call_count, 160)

    def test_an_article_request_neither_asks_the_website_nor_builds_the_list(self):
        wiki = self.wiki
        self.write_live(5)
        with mock.patch.object(wiki, "refresh_live") as rl, mock.patch.object(wiki, "index", side_effect=AssertionError("the list")), \
                mock.patch.object(wiki, "checkout", lambda: (None, 0, [])):
            code, body, _ = wiki.handle_get("/api/wiki/article", {"id": "nothing-here"})[:3]
        self.assertEqual(code, 404)
        rl.assert_not_called()

    def test_git_is_asked_once_a_minute_not_three_times_a_request(self):
        wiki = self.wiki
        top = str(Path(wiki.HERE).resolve().parents[2])
        calls = []

        def fake(*args, cwd=None):
            calls.append(args[0])
            return (0, {"rev-parse": top, "log": "123", "status": ""}[args[0]])
        with mock.patch.object(wiki, "git", fake):
            wiki._CACHE["key"] = ("files", 1)
            want = wiki.checkout()
            self.assertEqual(calls, ["rev-parse", "log", "status"])
            for _ in range(5):
                self.assertEqual(wiki.checkout(), want)
            self.assertEqual(len(calls), 3)
            wiki._CACHE["key"] = ("files", 2)                                           # one of the wiki's files changed: asked at once (the repository is known)
            wiki.checkout()
            self.assertEqual(calls[3:], ["log", "status"])
            wiki._GIT["hit"] = (wiki._CACHE["key"], time.time() - wiki.GIT_FOR - 1, want)   # a minute has gone by
            wiki.checkout()
            self.assertEqual(calls[5:], ["log", "status"])

    def serve(self, handler):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv

    def ask(self, **kw):
        wiki = self.wiki
        wiki._LIVE.update(checked=kw.get("checked", 0), busy=False)
        wiki.refresh_live(force=kw.get("force", True))
        for _ in range(200):
            if not wiki._LIVE["busy"]:
                break
            time.sleep(0.02)

    def test_the_website_is_asked_with_what_we_have_and_an_unchanged_list_costs_nothing(self):
        wiki = self.wiki
        state = {"etag": '"v1"', "body": json.dumps({"commit_time": 7, "assets": [], "articles": [{"id": "z", "title": "Z", "html": "<p>z</p>"}] * 200}).encode(),
                 "seen": [], "sent": 0, "status": 200}

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                state["seen"].append(dict(inm=self.headers.get("If-None-Match"), enc=self.headers.get("Accept-Encoding")))
                if state["status"] != 200:
                    self.send_response(state["status"])
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.headers.get("If-None-Match") == state["etag"]:
                    self.send_response(304)
                    self.send_header("ETag", state["etag"])
                    self.end_headers()
                    return
                body = gzip.compress(state["body"]) if "gzip" in (self.headers.get("Accept-Encoding") or "") else state["body"]
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("ETag", state["etag"])
                if body is not state["body"]:
                    self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                state["sent"] += len(body)

        srv = self.serve(H)
        with mock.patch.object(wiki, "LIVE_URL", f"http://127.0.0.1:{srv.server_address[1]}/wiki/articles.json"):
            self.ask()                                                                   # the first time: everything, and gzipped
            self.assertEqual(state["seen"][0]["inm"], None)
            self.assertIn("gzip", state["seen"][0]["enc"])
            self.assertEqual(self.live.read_bytes(), state["body"])
            self.assertLess(state["sent"], len(state["body"]) / 5)
            self.assertEqual(wiki._LIVE["error"], None)
            kept = self.live.stat()
            sent = state["sent"]
            self.ask()                                                                   # again: the website says "same", the file is not touched
            self.assertEqual(state["seen"][1]["inm"], '"v1"')
            self.assertEqual(state["sent"], sent)
            self.assertEqual(wiki._LIVE["error"], None)
            after = self.live.stat()
            self.assertEqual((after.st_ino, after.st_mtime_ns, after.st_size), (kept.st_ino, kept.st_mtime_ns, kept.st_size))
            state["etag"], state["body"] = '"v2"', state["body"].replace(b'"Z"', b'"Y"')     # the website changed
            self.ask()
            self.assertEqual(state["seen"][2]["inm"], '"v1"')
            self.assertEqual(self.live.read_bytes(), state["body"])
            self.ask()
            self.assertEqual(state["seen"][3]["inm"], '"v2"')
            self.live.write_text(self.live.read_text(encoding="utf-8") + " ", encoding="utf-8")        # the copy on this computer was changed: what we remembered is not about it
            self.ask()
            self.assertEqual(state["seen"][4]["inm"], None)
            self.assertEqual(self.live.read_bytes(), state["body"])
            # not forced, and within the hour: no request at all; and with the person's offline choice: none either
            n = len(state["seen"])
            wiki._LIVE.update(checked=time.time(), busy=False)
            wiki.refresh_live()
            wiki.save_settings(live=False)
            self.ask()
            self.assertEqual(len(state["seen"]), n)
            wiki.save_settings(live=True)
            # a failed ask is tried again in ten minutes, not an hour
            state["status"] = 500
            self.ask()
            self.assertIn("500", wiki._LIVE["error"])
            wait = wiki.CHECK_EVERY - (time.time() - wiki._LIVE["checked"])
            self.assertLessEqual(wait, wiki.RETRY_AFTER + 5)
        self.assertGreaterEqual(wiki.CHECK_EVERY, 3600)

    def test_a_small_download_cannot_unpack_to_a_flood(self):
        wiki = self.wiki
        flood = gzip.compress(b"{" + b" " * 50000)

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(flood)))
                self.end_headers()
                self.wfile.write(flood)
        srv = self.serve(H)
        with mock.patch.object(wiki, "LIVE_URL", f"http://127.0.0.1:{srv.server_address[1]}/x"), mock.patch.object(wiki, "LIVE_MAX", 1000):
            self.ask()
        self.assertIn("larger", wiki._LIVE["error"] or "")
        self.assertFalse(self.live.exists())

    def test_the_wiki_tab_reads_the_list_once_per_visit(self):
        js = (Path(self.wiki.__file__).with_name("wiki.js")).read_text(encoding="utf-8")
        view = re.search(r"async function wikiView\(\) \{\n(.*?)\n", js).group(1)
        self.assertIn("W.keep", view)                                                       # an article opened from the list does not fetch it again
        self.assertRegex(js, r"W\.keep = true;\n\s+render\(\)")

    def test_a_request_thread_that_clears_the_parsed_copy_cannot_break_another(self):
        """live() reads the shared copy once, as one tuple: another thread clearing it between a check and a read is a miss, not a KeyError."""
        wiki = self.wiki
        self.write_live(5, age=50)
        first = wiki.live()

        class Racy(dict):                       # clears itself right after a lookup: what a second request thread could do
            def get(self, k, d=None):
                v = dict.get(self, k, d)
                self.clear()
                return v
        with mock.patch.object(wiki, "_PARSED", Racy(wiki._PARSED)):
            again = wiki.live()                 # a hit comes from the one read; a cleared copy is read again, and never raises
        self.assertEqual([a["id"] for a in again["articles"]], [a["id"] for a in first["articles"]])


class SavedReviewPage(unittest.TestCase):
    """The saved REVIEW.html builds a page of cards at a time when the review is long (it built every card: ~60,000 elements for 2,000)."""
    def test_a_long_saved_review_builds_a_page_and_a_short_one_whole(self):
        page = RV.PAGE
        self.assertIn("const LAZY_ABOVE = 300;", page)
        self.assertIn("big = ask.length + info.length + nBatch > LAZY_ABOVE", page)
        self.assertIn("const lim = big ? cap : Infinity", page)              # a short review: no limit, every card, as before
        self.assertIn("ask.slice(0, lim).map(itemHTML)", page)
        self.assertIn("info.slice(0, lim).map(itemHTML)", page)
        self.assertIn("++built <= lim ? itemHTML(f) : ''", page)             # the batch builds no more than the limit either
        self.assertIn("#showmore", page)                                     # and the person can ask for the next page


if __name__ == "__main__":
    unittest.main()
