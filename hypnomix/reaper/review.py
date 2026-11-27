"""Review from inside REAPER: the HypnoMix Review panel, A / B / Blind on an A/B project. The REAPER side of the Live device.

  hypnomix reaper review          open the HypnoMix Review panel in REAPER and keep it in step with the app's review

Needs the HypnoMix app running with a review open (`hypnomix app`; for an app on another port give --port N, or
set HYPNOMIX_PORT). The panel shows the finding you are on, and:

  Prev / Next / Next open   step through the findings; REAPER selects the track and puts the time selection on the spot
  Approve / Skip            record your decision in the review (nothing is applied from here)

In an A/B project (`hypnomix abset SCAN_DIR` on a REAPER scan, opened in REAPER instead of the original):

  A · now / B · fix   switch the finding's plug-ins or tracks, instantly, with every plug-in playing
  Blind               X and Y in random order; "I like X / Y" records your choice (blind.json), then tells you
  Match on / off      with HypnoMix Main on the master and the probes relaying (`hypnomix reaper start`), B is
                      turned up or down to A's loudness while it plays

Moving to another finding puts the last one back to A. Stop with Ctrl-C or by closing the panel.
"""
import json
import random
import sys
import time
import urllib.request

from hypnomix.core import loopback
from hypnomix.reaper.client import Reaper, ReaperError

DEFAULT_PORT = 8791
APP = None                              # "http://127.0.0.1:<port>", set when the panel starts (see app_url)


def app_port(given=None):
    """The app's port: --port, else HYPNOMIX_PORT, else 8791 (read when the panel starts)."""
    import os
    if given:
        return int(given)
    try:
        n = int(os.environ.get("HYPNOMIX_PORT", "").strip() or DEFAULT_PORT)
        return n if 1 <= n <= 65535 else DEFAULT_PORT
    except ValueError:
        return DEFAULT_PORT


def app_url():
    return APP or f"http://127.0.0.1:{app_port()}"


def app(path, body=None, timeout=5):
    req = urllib.request.Request(app_url() + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with loopback.urlopen(req, timeout=timeout) as r:      # this computer only: never through a proxy variable
        return json.loads(r.read())


class Panel:
    def __init__(self, r):
        self.r = r
        self.cur = None
        self.ab = dict(id="", spec=None, state="A", blind=None, heard="")
        self.tempo = 120.0
        self.main_fx = None

    # ------------------------------------------------------------ switching
    def apply(self, spec, state):
        for part in spec["parts"]:
            if part["mode"] == "devices":
                for i, on in zip(part["a"], part["a_on"]):
                    self.r.enable(part["track"], i, on if state == "A" else False)
                for i, on in zip(part["b"], part["b_on"]):
                    self.r.enable(part["track"], i, on if state == "B" else False)
            else:
                for name, on in zip(part["a"], part["a_on"]):
                    self.r.set_track(name, mute=0 if (state == "A" and on) else 1)
                for name, on in zip(part["b"], part["b_on"]):
                    self.r.set_track(name, mute=0 if (state == "B" and on) else 1)

    def set_ab(self, state, label=None):
        c = self.cur
        if not c or not c.get("ab"):
            return
        try:
            self.apply(c["ab"], state)
        except ReaperError as e:
            self.flash(f"this is not the A/B project ({e})")
            return
        self.ab.update(id=c["id"], spec=c["ab"], state=state, heard=label or "")
        d = app("/api/ab/state", {"id": c["id"], "state": state})
        if d.get("diff") is not None:
            self.flash(("" if self.ab["blind"] else state + " · ") + f"levels matched ({d['diff']:+.1f} dB)")

    def follow(self):
        """Moving to another finding puts the last one back to A."""
        c = self.cur
        if self.ab["spec"] and (not c or c.get("id") != self.ab["id"]):
            if self.ab["state"] != "A":
                try:
                    self.apply(self.ab["spec"], "A")
                except ReaperError:
                    pass
            self.ab = dict(id="", spec=None, state="A", blind=None, heard="")

    # ------------------------------------------------------------ the panel
    def flash(self, text):
        self.r.call("panel_set", flash=text.replace("\n", " "))

    def show(self):
        c = self.cur or {}
        if not c.get("id"):
            st = dict(status="", head=c.get("text", "Open a review in the HypnoMix app."), problem="", fix="", ab="0",
                      decision="", sev="", track="", where="")
        else:
            st = dict(status=f"{c['n']} of {c['of']}  ·  {c.get('left', 0)} open  ·  {c.get('song', '')}",
                      head=f"[{c.get('severity')}] {c.get('track')}  {c.get('where') or ''}",
                      sev=c.get("severity") or "", track=c.get("track") or "", where=c.get("where") or "",
                      problem=c.get("problem", ""), fix="fix: " + (c.get("fix") or ""), decision=c.get("decision", ""),
                      ab="1" if c.get("ab") else "0", state=self.ab["state"] if self.ab["id"] == c["id"] else "A",
                      blind="1" if self.ab["blind"] else "0", heard=self.ab["heard"], match="1" if c.get("match") else "0")
        self.r.call("panel_set", **{k: str(v).replace("\n", " ")[:600] for k, v in st.items()})

    def on(self, ev):
        c = self.cur or {}
        if ev in ("prev", "next", "next_open"):
            self.cur = app("/api/live/step", {"delta": -1 if ev == "prev" else 1, "undecided": ev == "next_open"})
        elif ev in ("approve", "skip") and c.get("id"):
            self.cur = app("/api/live/decide", {"decision": ev})
        elif ev in ("A", "B"):
            self.set_ab(ev)
        elif ev == "blind" and c.get("ab"):
            self.ab["blind"] = {"X": "A", "Y": "B"} if random.random() < 0.5 else {"X": "B", "Y": "A"}
            self.set_ab(self.ab["blind"]["X"], "X")
            self.flash("Blind: listen to X and Y, then choose the one you like")
        elif ev in ("X", "Y") and self.ab["blind"]:
            self.set_ab(self.ab["blind"][ev], ev)
        elif ev in ("like_X", "like_Y") and self.ab["blind"]:
            which = ev[-1]
            chose = self.ab["blind"][which]
            d = app("/api/ab/blind", {"id": c["id"], "chose": chose, "x": self.ab["blind"]["X"]})
            self.ab["blind"] = None
            self.flash(f"You chose {which} = " + ("B, the fix" if chose == "B" else "A, what you have")
                       + (f"  (B {d['b']} of {d['n']} times)" if d.get("n", 0) > 1 else ""))
        elif ev == "match" and c.get("id"):
            app("/api/ab/state", {"id": c["id"], "state": self.ab["state"], "match": not c.get("match")})
            self.flash("Loudness match " + ("off" if c.get("match") else "on (needs HypnoMix Main and the probes relaying)"))

    def match_gain(self):
        """The gain the app asks of Main while matching A and B, onto HypnoMix Main's hidden setting."""
        if self.main_fx is None:
            self.main_fx = next((k for k, f in enumerate(self.r.fx_list("master")) if "hypnomix main" in f["name"].lower()), -1)
        if self.main_fx < 0:
            return
        try:
            g = app("/api/probe/cmd?id=0&name=Main&main=1").get("gain_db", 0.0)
        except OSError:
            return
        self.r.set_norm("master", self.main_fx, "match gain dB (set by hypnomix during A/B)", (float(g) + 12) / 24)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="hypnomix reaper review", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=None, help="the HypnoMix app's port (default: HYPNOMIX_PORT, else 8791)")
    a = ap.parse_args(argv)
    global APP
    APP = f"http://127.0.0.1:{app_port(a.port)}"
    try:
        app("/api/live/poll?since=-1", timeout=2)
    except OSError:
        sys.exit("the HypnoMix app is not running: start it (`hypnomix app`) and open a review")
    r = Reaper()
    r.start()
    p = Panel(r)
    p.tempo = float(r.ping().get("tempo") or 120.0)
    r.call("panel_open")
    seq, last_gain = -1, 0.0
    print("The HypnoMix Review panel is open in REAPER. Ctrl-C (or close the panel) to stop.")
    try:
        while True:
            d = app(f"/api/live/poll?since={seq}")
            seq = d.get("seq", seq)
            p.cur = d.get("current")
            cmd = d.get("cmd")
            if cmd and cmd.get("type") == "jump":
                spb = 60.0 / p.tempo
                r.call("jump", track=cmd.get("track"), start=cmd["start"] * spb if cmd.get("start") is not None else None,
                       end=cmd["end"] * spb if cmd.get("end") is not None else None)
            p.follow()
            ev = r.call("panel_events")
            for e in ev.get("events") or []:
                if e == "closed":
                    raise KeyboardInterrupt
                p.on(e)
                if e in ("prev", "next", "next_open") and p.cur and p.cur.get("jump"):
                    j = p.cur["jump"]
                    spb = 60.0 / p.tempo
                    r.call("jump", track=j.get("track"), start=j["start"] * spb if j.get("start") is not None else None,
                           end=j["end"] * spb if j.get("end") is not None else None)
                p.follow()
            p.show()
            if time.time() - last_gain > 0.5:
                last_gain = time.time()
                p.match_gain()
            time.sleep(0.15)
    except KeyboardInterrupt:
        pass
    finally:
        p.cur = None
        p.follow()                                       # leave the project on A
        try:
            r.call("panel_close")
        except ReaperError:
            pass
        print("panel closed; the project is back on A")
