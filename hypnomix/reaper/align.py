"""Align a vocal stack from inside REAPER: the Hypnomix Align panel. The REAPER side of the Live Align device.

  hypnomix reaper align           open the Hypnomix Align panel in REAPER (and keep it in step with the app)

Needs the hypnomix app running (`hypnomix app`; for an app on another port give --port N, or set HYPNOMIX_PORT):
it runs `hypnomix alignset` on the SAVED project, the same way the Live device does (through /api/align/*). Save
the project first (alignset reads the saved .rpp). In the panel:

  Guide ←           the selected track becomes the guide (the one the others follow)
  + Part / Clear    the selected tracks become parts (repeat); Clear empties the list
  Range: selection  only the time selection; Song: everywhere
  Protect           the time selection is never moved (repeat for more)
  Sync here         the edit cursor becomes a sync point (lined up exactly); Clear marks empties both lists
  sliders           drag: Tight (how far timing moves), Pitch (0 = off; the chord under every note is checked first,
                    from the project's own instrument tracks), Vibrato, Formant (semitones, pitch unchanged)
  Preset            steps through the presets (or none: the sliders alone)
  Align             measures and makes previews (nothing changes); the lanes show each part before (grey) and after
                    (amber)
  Write project     when on, Align also writes "<project> (aligned).rpp" next to yours: the timing as stretch
                    markers on the parts' own items, pitch / formant as a new active take on each item (the original
                    take stays: switch takes to compare). Your project is never written.
  Timing: markers   the timing as stretch markers (editable; with pitch preserved REAPER's stretch engine plays
                    moved words about 4 ms late). Click for "Timing: takes": a new take that plays the checked
                    preview exactly (not editable as markers)
  Open project      opens the aligned project in a new REAPER tab

Stop with Ctrl-C or by closing the panel.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

from hypnomix.reaper.client import Reaper, ReaperError
from hypnomix.reaper.review import DEFAULT_PORT, app_port      # the same port rule as the review panel

APP = None                              # "http://127.0.0.1:<port>", set when the panel starts (see app_url)
PRESETS = ["", "gentle-stack", "natural-double", "tight-pop", "loose-folk", "rap-doubles"]
LANE_POINTS = 120                       # each lane's shape, thinned for the bridge


def app_url():
    """The app's address: --port, else HYPNOMIX_PORT, else 8791 (read when the panel starts, not when this loads)."""
    return APP or f"http://127.0.0.1:{app_port()}"


def app(path, body=None, timeout=5):
    req = urllib.request.Request(app_url() + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def mmss(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def thin(vals, n=LANE_POINTS):
    if not vals:
        return ""
    k = max(1, len(vals) // n)
    return ",".join(f"{max(vals[i:i + k]):.0f}" for i in range(0, len(vals), k))


class Panel:
    def __init__(self, r):
        self.r = r
        self.st = dict(guide="", parts=[], range=None, protect=[], sync=[], preset=0, tight=0.5, pitch=0.0,
                       vibrato=0.0, formant=0.0, write=False, takes=False)
        self.status, self.busy, self.result, self.job = "", False, None, 0
        self.project = ""

    def flash(self, text):
        self.r.call("panel_set", flash=str(text).replace("\n", " ")[:300])

    def where(self):
        w = self.r.call("align_where") or {}
        w["tracks"] = list(w.get("tracks") or [])
        return w

    def selection(self, w):
        s, e = float(w.get("sel_start") or 0), float(w.get("sel_end") or 0)
        return (s, e) if e > s + 0.05 else None

    # ------------------------------------------------------------ the clicks
    def on(self, ev):
        st = self.st
        if ev.startswith("set:"):
            k, _, v = ev[4:].partition("=")
            if k in ("tight", "pitch", "vibrato", "formant"):
                lo, hi = (-3.0, 3.0) if k == "formant" else (0.0, 1.0)
                st[k] = max(lo, min(hi, float(v)))
            return
        if ev in ("guide", "part", "range", "protect", "sync"):
            w = self.where()
            if ev == "guide":
                if not w["tracks"]:
                    return self.flash("Select the guide track first")
                st["guide"] = w["tracks"][0]
                st["parts"] = [p for p in st["parts"] if p != st["guide"]]
            elif ev == "part":
                new = [t for t in w["tracks"] if t != st["guide"] and t not in st["parts"]]
                if not new:
                    return self.flash("Select a part track (not the guide) first")
                st["parts"] += new
            elif ev == "sync":
                st["sync"].append(round(float(w.get("cursor") or 0), 3))
            else:
                sel = self.selection(w)
                if sel is None:
                    return self.flash("Make a time selection first")
                if ev == "range":
                    st["range"] = [round(sel[0], 3), round(sel[1], 3)]
                else:
                    st["protect"].append([round(sel[0], 3), round(sel[1], 3)])
        elif ev == "song":
            st["range"] = None
        elif ev == "clear":
            st["parts"] = []
        elif ev == "clear_marks":
            st["protect"], st["sync"] = [], []
        elif ev == "preset":
            st["preset"] = (st["preset"] + 1) % len(PRESETS)
        elif ev == "write":
            st["write"] = not st["write"]
        elif ev == "takes":
            st["takes"] = not st["takes"]
        elif ev == "align":
            self.align()
        elif ev == "open":
            out = (self.result or {}).get("out_set")
            if not out:
                return self.flash("No aligned project yet: switch Write project on and Align")
            self.r.call("open_project", path=out)
            self.flash(f"Opened {Path(out).name} in a new tab (yours is still open in its own tab)")

    def body(self):
        st = self.st
        b = dict(set=self.project, guide=st["guide"], parts=list(st["parts"]), protect=[list(x) for x in st["protect"]],
                 sync=list(st["sync"]), tightness=st["tight"], pitch=st["pitch"], vibrato=st["vibrato"],
                 formant=st["formant"], apply=st["write"], takes=st["takes"])
        if st["range"]:
            b["start_s"], b["end_s"] = st["range"]
        if PRESETS[st["preset"]]:
            b["preset"] = PRESETS[st["preset"]]
        return b

    def align(self):
        if self.busy:
            return self.flash("Already aligning: wait for it to finish")
        st = self.st
        if not st["guide"] or not st["parts"]:
            return self.flash("Choose a guide (Guide ←) and at least one part (+ Part)")
        w = self.where()
        path = w.get("project") or ""
        if not path or not path.lower().endswith(".rpp"):
            return self.flash("Save the project first: Align reads the saved .rpp")
        if int(w.get("dirty") or 0):
            return self.flash("The project has unsaved changes: save it (Cmd/Ctrl-S), then Align")
        self.project = path
        try:
            app("/api/align/choose", {"path": path})
            d = app("/api/align/run", self.body())
        except OSError as e:
            return self.flash(f"The hypnomix app is not answering ({e}): start `hypnomix app`")
        if d.get("error"):
            return self.flash(d["error"])
        self.job, self.busy, self.result = d.get("job", 0), True, None
        self.status = "aligning (your project is not changed)"

    def poll(self):
        if not self.busy:
            return
        try:
            s = app("/api/align/state")
        except OSError:
            return
        if s.get("running"):
            self.status = "aligning: " + (s.get("step") or (s.get("log_tail") or [""])[-1])[:80]
            return
        if s.get("status") in ("done", "failed"):
            self.busy = False
            self.result = s.get("result")
            if s.get("status") == "failed" or not self.result:
                tail = (s.get("log_tail") or ["alignset failed"])[-1]
                self.status = "failed"
                self.flash(f"Align failed: {tail}"[:300])
            else:
                self.status = "done"
                self.flash("Written: " + Path(self.result["out_set"]).name if self.result.get("out_set")
                           else "Measured: switch Write project on and Align again to write the new project")

    # ------------------------------------------------------------ what the panel shows
    def summary(self):
        r = self.result or {}
        bits = []
        for row in r.get("parts") or []:
            if row.get("takes"):
                bits.append(f"{row['track']}: new take on {row['takes']} item(s)")
            elif row.get("markers"):
                bits.append(f"{row['track']}: {row['markers']} stretch markers on {row['items']} item(s)")
            elif row.get("skipped"):
                bits.append(f"{row['track']}: left as it was")
        if r.get("rendered") and not r.get("out_set"):
            bits.append("pitch/formant rendered (Write project puts them on new takes)")
        return "; ".join(bits)

    def show(self):
        st = self.st
        wh = ("range " + "–".join(mmss(x) for x in st["range"]) if st["range"] else "the whole song")
        if st["protect"]:
            wh += "  ·  protect " + ", ".join("–".join(mmss(x) for x in p) for p in st["protect"])
        if st["sync"]:
            wh += "  ·  sync " + ", ".join(mmss(t) for t in st["sync"])
        lanes = []
        for t in ((self.result or {}).get("energy") or {}).get("tracks") or []:
            lanes.append(f"{t['name'].replace('|', '/').replace(';', ',')};{thin(t.get('before'))};{thin(t.get('after'))}")
        vals = dict(mode="align", status=(Path(self.project).name + "  ·  " if self.project else "") + self.status,
                    guide=st["guide"], parts=", ".join(st["parts"]), range_on="1" if st["range"] else "0", where=wh,
                    tight=f"{st['tight']:g}", pitch=f"{st['pitch']:g}", vibrato=f"{st['vibrato']:g}",
                    formant=f"{st['formant']:g}", preset=PRESETS[st["preset"]], write="1" if st["write"] else "0",
                    takes="1" if st["takes"] else "0",
                    busy="1" if self.busy else "0", can_open="1" if (self.result or {}).get("out_set") else "0",
                    result=self.summary(), lanes="|".join(lanes[:8]))
        self.r.call("panel_set", **{k: str(v).replace("\n", " ") for k, v in vals.items()})


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="hypnomix reaper align", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=None, help="the hypnomix app's port (default: HYPNOMIX_PORT, else "
                    f"{DEFAULT_PORT})")
    a = ap.parse_args(argv)
    global APP
    APP = f"http://127.0.0.1:{app_port(a.port)}"
    try:
        app("/api/align/state", timeout=2)
    except OSError:
        sys.exit("the hypnomix app is not running: start it (`hypnomix app`)")
    r = Reaper()
    r.start()
    p = Panel(r)
    r.call("panel_open", mode="align")
    print("The Hypnomix Align panel is open in REAPER. Ctrl-C (or close the panel) to stop.")
    try:
        while True:
            for e in (r.call("panel_events") or {}).get("events") or []:
                if e == "closed":
                    raise KeyboardInterrupt
                try:
                    p.on(e)
                except (ReaperError, OSError, ValueError) as err:
                    p.flash(str(err))
            p.poll()
            p.show()
            time.sleep(0.15)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            r.call("panel_close")
        except ReaperError:
            pass
        print("panel closed")


if __name__ == "__main__":
    main()
