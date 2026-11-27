"""Teacher mode: a guided walk from an empty song to a mastered one, for people who have never used a DAW.

The lessons live in the package hypnomix/app/lessons (one module per chapter); this module is the engine: which steps a
course and a DAW get, the progress file, the hands-on actions, the routes, the glossary and the wiki articles.
Ableton Live and REAPER get the same depth (Live alone has its Session View; REAPER alone has the HypnoMix plug-ins'
built-in guide), and HypnoMix Studio (beta) the short version (its engine add-on can be added on Apple-silicon Macs,
is not available on Intel Macs or Windows yet, and nothing written for Studio has been judged by ear).

A step can carry a hands-on action ("Set the tempo", "Add a drum beat"). Every action that changes the person's
set or project shows exactly what it will do and waits for their click: the browser asks, and the server refuses
an action without `ok`. Live is driven through AbletonOSC (hypnomix/live/osc.py), REAPER through its bridge
(hypnomix/reaper/client.py); where the DAW can't be driven (HypnoMix Studio, or no connection) the step's own instructions
say how to do it by hand. Nothing here needs an AI: the Assistant can narrate a step when one is set up.

Three courses (LEVELS): "tour" for people who already engineer and only need hypnomix, its devices and their DAW;
"101" for people new to audio, the crash course (the basics, a first recording, one effect at a time, mastering, then the
tour); "az" the complete course, A to Z, of which 101 is a subset. The DAW and the course come from the guided setup (~/.hypnomix/setup.json); progress is kept in
~/.hypnomix/teacher.json. The same lessons are the wiki's "Make a song from scratch" articles (wiki_md), so the app
and the website always teach the same thing: change them here and the wiki follows.
"""
import json
import random
import re
import threading
import time
from pathlib import Path

from hypnomix.app import lessons
from hypnomix.app.lessons._common import ALL, LR

DAWS = {"live": "Ableton Live", "reaper": "REAPER", "ardour": "HypnoMix Studio"}
# three courses: "tour" for people who already engineer (hypnomix, its devices and the DAW they use it with), "101"
# for people new to audio (the words, recording, mixing and mastering, then the same tour), "az" the complete course
LEVELS = {"tour": "HypnoMix in your DAW", "101": "The 101 crash course", "az": "The complete course, A to Z"}
DEFAULT_LEVEL = "101"                      # what an unknown saved level falls back to


def _home():
    from hypnomix.core.paths import HOME
    return Path(HOME)


def progress_file():
    return _home() / "teacher.json"


# ---------------------------------------------------------------- the lessons
# A step: id, title, daws (which DAWs teach it), say (paragraphs), terms ([word, meaning]), how ({daw: [steps]}),
# settings ([control, where to start, why]; per DAW when the controls differ), listen (what to listen for),
# action ({daw: action spec}), app (a button into another tab of the app), levels (which courses; default: the chapter's),
# and for the complete course: mistakes (list), try ({do, success}), quiz ([{q, options, answer, why}]),
# hear ([{demo, a, b, listen}]: audio examples made on the spot by teach_audio.py), more (wiki article ids or commands).
# **bold** and `code` work in the text.

CHAPTERS = lessons.CHAPTERS


def _levels(ch, s=None):
    return tuple((s or {}).get("levels") or ch.get("levels") or (DEFAULT_LEVEL,))


# the optional teaching fields a step may carry, passed on to the page and the wiki
EXTRA = ("terms", "settings", "listen", "app", "mistakes", "try", "quiz", "hear", "more")


# Said once, at the first step of each HypnoMix Studio course (tour, 101, A to Z), because that DAW is new.
HONESTY = ("HypnoMix Studio is new: its first engine (0.1.0) is for Apple-silicon Macs. Steps written here for it were written "
           "against Ardour 8 or 9, the free DAW it is built on, and not every one has been tried in HypnoMix Studio yet.")


def _hm_in(daw, how="in"):
    """"HypnoMix in Ableton Live" / "HypnoMix with REAPER"; for HypnoMix Studio the name alone, so it isn't said twice."""
    name = DAWS.get(daw, "your DAW")
    return name if daw == "ardour" else f"HypnoMix {how} {name}"


# What the wiki says instead of the honesty line: a link to the article about HypnoMix Studio (id "ardour")
ABOUT_DAW = ' <a data-wiki="ardour" href="#">What HypnoMix Studio is, and where to get it</a>.'


def _about(daw):
    return ABOUT_DAW if daw == "ardour" else ""


def steps(daw, level=DEFAULT_LEVEL, honesty=True):
    """The chapters of one course (LEVELS) with only this DAW's steps, each step's 'how', settings and action
    resolved for it. `honesty=False` leaves out the honesty line (the wiki says it in its HypnoMix Studio article only)."""
    if level not in LEVELS:
        level = DEFAULT_LEVEL
    out = []
    for ch in CHAPTERS:
        ss = []
        for s in ch["steps"]:
            if level not in _levels(ch, s) or daw not in s.get("daws", ALL):
                continue
            t = {k: s[k] for k in ("id", "title", "say") if k in s}
            for k in EXTRA:
                if s.get(k):
                    t[k] = _for_daw(s[k], daw) if k == "settings" else s[k]
            if s.get("hear"):
                t["hear"] = _hear(s["hear"])
            t["how"] = (s.get("how") or {}).get(daw, [])
            a = (s.get("action") or {}).get(daw)
            if a:
                t["action"] = describe(daw, s, a["kind"])
            ss.append(t)
        if not ss:
            continue
        title = ch["title"]
        if daw in DAWS:
            title = title.replace("HypnoMix in your DAW", _hm_in(daw)).replace("your DAW", DAWS[daw])
        out.append(dict(id=ch["id"], title=title, sub=ch["sub"], steps=ss))
    if honesty and daw == "ardour" and out:
        out[0]["steps"][0]["how"] = [HONESTY] + list(out[0]["steps"][0]["how"])
    return out


def _hear(items):
    """A step's `hear` (demo ids, or {demo, listen}) -> what the page needs: title, what to listen for, one button per variant."""
    from hypnomix.app import teach_audio
    out = []
    for h in items:
        d, listen = (h, None) if isinstance(h, str) else (h["demo"], h.get("listen"))
        if d in teach_audio.DEMOS:
            out.append(teach_audio.catalog(d, listen))
    return out


def _for_daw(settings, daw):
    """`settings` is a list of [control, start, why], or {daw: that list} when the controls differ per DAW."""
    return settings.get(daw, []) if isinstance(settings, dict) else settings


def count(daw, level=DEFAULT_LEVEL):
    return sum(len(c["steps"]) for c in steps(daw, level))


def glossary(daw=None):
    """Every word the lessons define (each step's `terms`, plus lessons/glossary.py), A to Z, each with a link to the step that
    teaches it: [{term, entries: [{meaning, step, title, chapter}]}]. With `daw`, only the words that DAW's lessons teach."""
    words = {}

    def add(term, meaning, sid, title, chapter):
        e = words.setdefault(term.strip().lower(), dict(term=term.strip(), entries=[]))
        if all(x["meaning"] != meaning for x in e["entries"]):
            e["entries"].append(dict(meaning=meaning, step=sid, title=title, chapter=chapter))

    sid_title = {}
    for ch in CHAPTERS:
        for s in ch["steps"]:
            if daw and daw in DAWS and daw not in s.get("daws", ALL):
                continue
            sid_title[s["id"]] = (s["title"], ch["title"])
            for term, meaning in s.get("terms") or []:
                add(term, meaning, s["id"], s["title"], ch["title"])
    for row in lessons.GLOSSARY:
        sid = row[2] if len(row) > 2 else ""
        if sid and sid not in sid_title:
            continue
        add(row[0], row[1], sid, *(sid_title.get(sid) or ("", "")))
    return sorted(words.values(), key=lambda e: re.sub(r"[^a-z0-9 ]", "", e["term"].lower()))


# ---------------------------------------------------------------- the hands-on actions
# What each action does, said before it's done: `fields` are the person's choices (with defaults), `will` the
# sentence they read before they click "Do it".

def _fx_of(daw, step):
    return (step.get("fx") or {}).get(daw)


def describe(daw, step, kind):
    name = DAWS[daw]
    if kind == "tempo":
        return dict(kind=kind, label="Set the tempo", fields=[dict(id="bpm", label="Tempo (BPM)", value=90, type="number")],
                    will=f"Set the song's tempo in {name} to {{bpm}} BPM.", changes=True)
    if kind == "click":
        return dict(kind=kind, label="Turn the click on", fields=[], will=f"Switch {name}'s metronome on.", changes=True)
    if kind == "drums":
        return dict(kind=kind, label="Add a drum beat", fields=[dict(id="feel", label="Feel", value="straight", options=["straight", "half-time"]),
                                                                dict(id="bars", label="Bars", value=4, type="number")],
                    will=(f"Add a MIDI track called Drums with {'a drum kit from the Browser' if daw == 'live' else 'ReaSynDr, REAPER’s drum synth'} "
                          "and a {bars}-bar {feel} beat (kick, snare on 2 and 4, eighth-note hi-hats, a little variation in how hard each hit lands)"
                          + (", as a clip in the first slot of the Session View: drag it into the Arrangement or loop it there." if daw == "live" else ", looped from the start of the project.")),
                    changes=True)
    if kind == "track":
        return dict(kind=kind, label="Make the track", fields=[dict(id="name", label="Name", value="Vocal"), dict(id="input", label="Interface input", value=1, type="number")],
                    will=f"Add an audio track called {{name}} in {name}, recording from input {{input}} of your audio interface, armed and with monitoring on"
                         + (" Auto." if daw == "live" else "."), changes=True)
    if kind == "level":
        return dict(kind=kind, label="Check my level", fields=[dict(id="input", label="Interface input", value=1, type="number")],
                    will="Listen to input {input} of your audio interface for 8 seconds while you play or sing the loudest part, then say which way to turn the gain. Nothing is recorded or saved.",
                    changes=False)
    if kind == "record":
        return dict(kind=kind, label="Record", fields=[dict(id="bars", label="Bars", value=8, type="number")] if daw == "live" else [],
                    will=("Record {bars} bars from bar 1 on every armed track in the Arrangement, after one bar of count-in, then stop."
                          if daw == "live" else "Start recording in REAPER on every armed track, from the edit cursor. Press Space in REAPER (or Stop here) to stop."),
                    changes=True)
    if kind == "fx":
        fx = _fx_of(daw, step)
        on = fx.get("track")
        if fx.get("bus"):                          # REAPER: a track of its own for a shared effect; the send is made by hand
            dev, bus = fx["device"].replace(" (Cockos)", ""), fx["bus"]
            return dict(kind=kind, label=f"Add a {bus} track with {dev}", fields=[],
                        will=(f"Add a track called {bus} with {dev} on it, set with the starting settings above (only the effect, "
                              f"none of the dry sound); if {bus} already has {dev}, set that one instead. The bridge can't make sends, "
                              f"so you then send each track to {bus} yourself (the steps above say how)."), changes=True)
        return dict(kind=kind, label=f"Add {fx['device'].replace(' (Cockos)', '')}",
                    fields=[] if on else [dict(id="track", label="On the track", value="Vocal")],
                    will=(f"Add {fx['device'].replace(' (Cockos)', '')} to " + (f"return track {on}" if on else "the track {track}") +
                          " with the starting settings above (anything it can't set is listed for you to set by hand)."), changes=True)
    if kind == "devices":
        if daw == "live":
            return dict(kind=kind, label="Make the devices", fields=[],
                        will="Write HypnomixProbe, HypnomixMain and the Hypnomix review device into your Live User Library (Presets → Audio Effects → Max Audio Effect → Hypnomix). Your sets aren't touched; an older copy of a device is replaced.",
                        changes=True)
        return dict(kind=kind, label="Install the JSFX", fields=[],
                    will="Copy HypnoMix Probe and HypnoMix Main into REAPER's Effects/hypnomix folder. Your projects aren't touched; an older copy is replaced.",
                    changes=True)
    if kind == "chain":
        return dict(kind=kind, label="Build the mastering chain", fields=[],
                    will=("Add EQ Eight, Glue Compressor, Utility (bass mono below 120 Hz) and Limiter to the end of the Master track, every gain at 0 dB. Nothing already there is removed."
                          if daw == "live" else "Build the mastering chain on REAPER's master (HypnoMix Main's Build chain when Main is there; otherwise ReaEQ, ReaComp and ReaLimit). Nothing already there is removed."),
                    changes=True)
    raise ValueError(f"no such action {kind!r}")


def beat(bars=4, feel="straight", seed=7):
    """A plain drum beat with a little life: (pitch, start beat, length, velocity). General MIDI drums: 36 kick,
    38 snare, 42 closed hi-hat. Timing stays on the beat; only how hard each hit lands varies (a programmed part,
    so no one's playing is being moved)."""
    rnd = random.Random(seed)
    bars = max(1, min(int(bars), 16))
    out = []
    for b in range(bars):
        o = b * 4
        if feel == "half-time":
            kicks, snares = [0, 2.5], [2]
        else:
            kicks, snares = [0, 2, 2.5] if b % 2 else [0, 2], [1, 3]
        for k in kicks:
            out.append((36, o + k, 0.25, 104 + rnd.randint(-6, 6) if k == 0 else 92 + rnd.randint(-8, 6)))
        for s in snares:
            out.append((38, o + s, 0.25, 100 + rnd.randint(-6, 6)))
        for h in range(8):
            on = h % 2 == 0
            out.append((42, o + h * 0.5, 0.2, (84 if on else 62) + rnd.randint(-7, 7)))
    return sorted(out, key=lambda n: (n[1], n[0]))


# ReaSynDr plays its four voices on notes 32-35 (kick, snare, a short tick, a tom; measured in REAPER 7.86), not
# on General MIDI's 36 / 38 / 42, so REAPER's beat is written on its notes
REASYNDR = {36: 32, 38: 33, 42: 34}


def _live():
    from hypnomix.live.osc import Live
    return Live()


def _reaper():
    from hypnomix.reaper.client import Reaper
    return Reaper()


def connections():
    """Can the DAWs be driven right now? (Live: AbletonOSC answers; REAPER: the bridge is running.)"""
    out = {}
    try:
        lv = _live()
        try:
            out["live"] = lv.ping()
        finally:
            lv.close()
    except Exception:
        out["live"] = False
    try:
        out["reaper"] = _reaper().alive()
    except Exception:
        out["reaper"] = False
    out["ardour"] = False
    return out


REC = {"busy": False, "msg": ""}


def _fx_live(lv, fx, track):
    tid = lv.tid(track)
    have = lv.devices(tid) if fx.get("track") else []
    # a return that already has this effect (Live's default set has a Reverb on A) gets its settings, not a second one
    i = have.index(fx["device"]) if fx["device"] in have else lv.load_stock_device(tid, fx["device"])
    done, by_hand = [], []
    for how, names, value in fx["set"]:
        p = None
        try:
            p = lv.find_param(tid, i, names)
            if p is None:
                raise KeyError(names[0])
            (lv.set_param_display if how == "disp" else lv.set_param)(tid, i, p["name"], value)
            done.append(f"{p['name']} {value}")
        except Exception:
            by_hand.append(f"{names[0]}: {value}")
    return done, by_hand


def _fx_reaper(r, fx, track, idx=None):
    """Add fx["device"] to the track (or set the one at `idx`). Each of fx["set"] is [how, param, value] or
    [how, param, value, as shown]: how is "named" (a named config parameter), "norm" (0 to 1) or "shown" (the value
    the plug-in shows); param may be a list of names to try in turn (plug-ins name their controls differently
    across versions). -> (what was set, what to set by hand)."""
    if idx is None:
        idx = r.add_fx(track, fx["device"])["fx"]
    done, by_hand = [], []
    for how, p, value, *seen in fx["set"]:
        names = p if isinstance(p, list) else [p]
        for name in names:
            try:
                if how == "named":
                    r.named(track, idx, name, value)
                elif how == "norm":
                    r.set_norm(track, idx, name, value)
                else:
                    r.set_shown(track, idx, name, value)
            except Exception:
                continue
            done.append(f"{name} {seen[0] if seen else value}")
            break
        else:
            by_hand.append(f"{names[0]}: {seen[0] if seen else value}")
    return done, by_hand


def _find_step(sid):
    for ch in CHAPTERS:
        for s in ch["steps"]:
            if s["id"] == sid:
                return s
    raise ValueError(f"no such step {sid!r}")


def level(inp=1, secs=8.0):
    from hypnomix.studio import soundcheck as SC
    try:
        y, sr = SC.record(None, int(inp), float(secs))
    except SystemExit as e:
        raise RuntimeError(str(e))
    except ImportError:
        raise RuntimeError("the level check needs the sounddevice package (pip install sounddevice); use the track's meter instead")
    r = SC.analyse(y, sr)
    return dict(done=" ".join(r["advice"]), peak=round(r["peak"], 1))


def run(daw, sid, kind, args):
    """Do one action. -> dict(done=text, by_hand=[...]). Raises on failure (the message says what to do)."""
    if daw not in DAWS:
        raise ValueError("choose your DAW first")
    step = _find_step(sid)
    allowed = ((step.get("action") or {}).get(daw) or {}).get("kind")
    if kind != allowed and not (kind == "stop" and allowed == "record" and daw == "reaper"):
        raise ValueError(f"that step has no {kind} action in {DAWS[daw]}")
    a = dict(args or {})
    if kind == "level":
        return level(a.get("input", 1))
    if kind == "devices":
        return make_devices(daw)
    if daw == "live":
        return _run_live(step, kind, a)
    if daw == "reaper":
        return _run_reaper(step, kind, a)
    raise ValueError(f"The Teacher can't do this step in {DAWS[daw]} yet: follow the steps above")


def _cli(*args):
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    if r.returncode:
        raise RuntimeError(f"hypnomix {' '.join(args)} failed: {(r.stderr or r.stdout).strip()[-400:]}")
    return r.stdout


def make_devices(daw):
    if daw == "live":
        _cli("probe", "device")
        _cli("device")
        return dict(done="Made HypnomixProbe, HypnomixMain and Hypnomix: in Live's Browser under User Library → Presets → Audio Effects → Max Audio Effect → Hypnomix.")
    if daw == "reaper":
        _cli("reaper", "probes", "install")
        return dict(done="Installed HypnoMix Probe and HypnoMix Main: in REAPER, Add FX → JS → hypnomix. (Restart REAPER's FX browser if they don't show yet.)")
    raise ValueError("HypnoMix Studio has no HypnoMix devices yet")


def _num(a, k, default, lo, hi):
    try:
        v = float(a.get(k, default))
    except (TypeError, ValueError):
        raise ValueError(f"{k} should be a number")
    if not lo <= v <= hi:
        raise ValueError(f"{k} should be between {lo:g} and {hi:g}")
    return v


def _run_live(step, kind, a):
    from hypnomix.live.osc import LiveError
    lv = _live()
    try:
        if not lv.ping():
            raise LiveError("Live isn't answering: open Live, and in Settings → Link, Tempo & MIDI choose AbletonOSC as a Control Surface (Setup → Ableton Live installs it)")
        if kind == "tempo":
            bpm = _num(a, "bpm", 90, 40, 250)
            lv.set_tempo(bpm)
            return dict(done=f"Tempo set to {bpm:g} BPM.")
        if kind == "click":
            on = lv.metronome(True)
            return dict(done="The click is on." if on else "Live didn't switch the click on: click the metronome icon by the tempo.")
        if kind == "drums":
            bars = int(_num(a, "bars", 4, 1, 16))
            feel = "half-time" if a.get("feel") == "half-time" else "straight"
            tid = lv.new_track("midi", "Drums")
            by_hand = []
            try:
                lv.load_browser_item(tid, "drums", "")
            except LiveError as e:
                by_hand.append(f"No drum kit loaded ({e}). In the Browser, open Drums and drag a kit onto the Drums track.")
            lv.new_clip(tid, 0, bars * 4, "Beat")
            notes = beat(bars, feel)
            lv.add_notes(tid, 0, notes)
            return dict(done=f"Added a Drums track with a {bars}-bar {feel} beat ({len(notes)} hits) in its first Session slot. Click the clip's play button to hear it.",
                        by_hand=by_hand)
        if kind == "track":
            name = str(a.get("name") or "Vocal")[:40]
            ch = int(_num(a, "input", 1, 1, 64))
            tid = lv.new_track("audio", name)
            by_hand = []
            try:
                kinds = lv.inputs(tid)[0]
                ext = next((k for k in kinds if str(k).lower().startswith("ext")), None)
                if ext:
                    lv.set_input(tid, ext, None)
                chans = lv.inputs(tid)[1]
                want = next((c for c in chans if str(c).strip() == str(ch)), None)
                if want:
                    lv.set_input(tid, None, want)
                else:
                    by_hand.append(f"Input {ch} isn't on the list for this interface: choose it under Audio From on the {name} track.")
            except Exception:
                by_hand.append(f"Choose Audio From → Ext. In → {ch} on the {name} track.")
            lv.monitor(tid, "auto")
            lv.arm(tid, True)
            time.sleep(0.3)
            if not lv.armed(tid):
                return dict(done=f"Made the {name} track with monitoring on Auto, but Live wouldn't arm it.",
                            by_hand=["Live has no audio input to record from: in Live's Settings → Audio, choose your audio "
                                     f"interface as the Audio Input Device, then click the {name} track's Arm button."])
            return dict(done=f"Made the {name} track, recording from input {ch}, armed, monitoring Auto.", by_hand=by_hand)
        if kind == "record":
            bars = int(_num(a, "bars", 8, 1, 64))
            if REC["busy"]:
                raise ValueError("already recording")

            def go():
                l2 = _live()
                try:
                    REC.update(busy=True, msg="")
                    l2.record(1, bars, 1, preroll=1)
                    REC["msg"] = f"Recorded {bars} bars."
                except Exception as e:
                    REC["msg"] = f"Recording stopped: {e}"
                finally:
                    l2.close()                        # before "done": the next action needs Live's reply port
                    REC["busy"] = False
            lv.close()
            lv = None
            threading.Thread(target=go, daemon=True).start()
            return dict(done=f"Recording {bars} bars from bar 1, after a bar of count-in. Live stops on its own.")
        if kind == "fx":
            fx = _fx_of("live", step)
            track = fx.get("track") or str(a.get("track") or "")
            if not track:
                raise ValueError("which track?")
            reuse = bool(fx.get("track")) and fx["device"] in lv.devices(lv.tid(track))
            done, by_hand = _fx_live(lv, fx, track)
            return dict(done=f"{'Set the' if reuse else 'Added'} {fx['device']} {'on' if reuse else 'to'} {track}" + (f": {', '.join(done)}." if done else "."),
                        by_hand=[f"Set by hand: {x}" for x in by_hand])
        if kind == "chain":
            from hypnomix.app.masterchain import STOCK
            added, by_hand = [], []
            for st in STOCK["stages"]:
                if not st["on"]:
                    continue
                fx = dict(device=st["device"], set=[[("raw" if how == "raw" else "disp"), names, v]
                                                    for names, v, how in st["set"] if how in ("raw", "disp")])
                d, h = _fx_live(lv, fx, "Master")
                added.append(st["device"])
                by_hand += [f"{st['device']}: {x}" for x in h]
            return dict(done=f"Added {', '.join(added)} to the Master track. Raise the Limiter's gain until the song reaches its target (next step).",
                        by_hand=[f"Set by hand: {x}" for x in by_hand])
        raise ValueError(f"no such action {kind!r}")
    finally:
        if lv is not None:
            lv.close()


def _run_reaper(step, kind, a):
    from hypnomix.reaper.client import ReaperError
    r = _reaper()
    if not r.alive():
        raise ReaperError("REAPER's bridge isn't running: open REAPER, then run `hypnomix reaper start` (Wiki → HypnoMix in REAPER)")
    if kind == "tempo":
        bpm = _num(a, "bpm", 90, 40, 250)
        out = r.call("teach_tempo", bpm=bpm)
        return dict(done=f"Tempo set to {float(out.get('bpm', bpm)):g} BPM.")
    if kind == "click":
        out = r.call("teach_click", on=1)
        return dict(done="The metronome is on." if out.get("on") else "REAPER didn't switch the metronome on: click its button in the transport.")
    if kind == "drums":
        bars = int(_num(a, "bars", 4, 1, 16))
        feel = "half-time" if a.get("feel") == "half-time" else "straight"
        notes = [(REASYNDR.get(p, p), st, d, v) for p, st, d, v in beat(bars, feel)]
        out = r.call("teach_drums", name="Drums", beats=bars * 4, notes=";".join(f"{p},{s:g},{d:g},{v}" for p, s, d, v in notes))
        by_hand = [] if (out.get("fx", -1) >= 0) else ["ReaSynDr didn't load: add a drum instrument to the Drums track (FX → Instruments)."]
        return dict(done=f"Added a Drums track with ReaSynDr and a looped {bars}-bar {feel} beat ({out.get('notes', len(notes))} hits). "
                         "ReaSynDr is a simple drum synth; for a real kit, load any drum plug-in on the track instead.", by_hand=by_hand)
    if kind == "track":
        name = str(a.get("name") or "Vocal")[:40]
        ch = int(_num(a, "input", 1, 1, 64))
        r.call("teach_track", name=name, input=ch, arm=1, monitor=1)
        return dict(done=f"Made the {name} track, recording from input {ch}, armed, monitoring on.")
    if kind == "record":
        r.transport(go="record")
        return dict(done="Recording. Press Space in REAPER (or Stop here) to stop.")
    if kind == "stop":
        r.transport(go="stop")
        return dict(done="Stopped.")
    if kind == "fx":
        fx = _fx_of("reaper", step)
        if fx.get("bus"):
            return _bus_reaper(r, fx)
        track = str(a.get("track") or "")
        if not track:
            raise ValueError("which track?")
        done, by_hand = _fx_reaper(r, fx, track)
        return dict(done=f"Added {fx['device']} to {track}.", by_hand=[f"Set by hand: {x}" for x in by_hand])
    if kind == "chain":
        try:
            r.call("chain_build", name="hypnomix stock", yes=1)
            return dict(done="Built the mastering chain before HypnoMix Main on the master.")
        except ReaperError:
            added, by_hand = [], []
            for dev, sets in (("ReaEQ (Cockos)", [["named", "BANDTYPE0", "4"], ["shown", 0, 25]]),
                              ("ReaComp (Cockos)", [["shown", "Ratio", 2], ["shown", "Attack", 30], ["shown", "Threshold", -12]]),
                              ("ReaLimit (Cockos)", [["shown", "Ceiling", -1]])):
                d, h = _fx_reaper(r, dict(device=dev, set=sets), "master")
                added.append(dev.replace(" (Cockos)", ""))
                by_hand += h
            return dict(done=f"Added {', '.join(added)} to the master (for bass mono and Match target, put HypnoMix Main on the master and press Build chain).",
                        by_hand=[f"Set by hand: {x}" for x in by_hand])
    raise ValueError(f"no such action {kind!r}")


def _bus_reaper(r, fx):
    """A shared effect on a track of its own (the reverb): make the track unless one of that name is there, add the
    effect unless that track already has it, set it. The bridge has no command for sends, so the send stays by hand."""
    bus, dev = fx["bus"], fx["device"]
    short = dev.replace(" (Cockos)", "")
    have = next((t for t in (r.tracks() or []) if t.get("name") == bus), None)
    if have is None:
        r.add_track(name=bus)
    at = next((i for i, f in enumerate((have or {}).get("fx") or []) if short.lower() in str(f.get("name", "")).lower()), None)
    done, by_hand = _fx_reaper(r, fx, bus, at)
    made = "Made a track called " + bus + " with " + short if have is None else (
        ("Set " + short + " on the " + bus + " track") if at is not None else ("Added " + short + " to the " + bus + " track"))
    return dict(done=made + (f": {', '.join(done)}." if done else "."),
                by_hand=[f"Set by hand: {x}" for x in by_hand] + [
                    f"Send a track to it: drag from the track's route button onto the {bus} track (or click the route button, "
                    f"then Add new send → {bus}), and set the send to about -15 dB. Raise it until you just hear the room, then back off a little."])


# ---------------------------------------------------------------- state
def load_progress():
    try:
        return json.loads(progress_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_progress(p):
    progress_file().parent.mkdir(parents=True, exist_ok=True)
    progress_file().write_text(json.dumps(p, indent=1), encoding="utf-8")


def choice():
    """-> (daw, course level or "" when teacher mode is off, how they work)"""
    from hypnomix.app import setup as SU
    s = SU.load()
    lv = s.get("teach_level") or ("101" if s.get("teach") else "")
    daw = s.get("daw", "")
    daw = "ardour" if daw == "hypnomix" else daw      # Setup calls the third DAW "hypnomix"; its lessons keep the key "ardour"
    return daw, (lv if lv in LEVELS else DEFAULT_LEVEL) if lv else "", s.get("mode", "")


def state(daw=None, level=None):
    d, lv, mode = choice()
    daw = daw if daw in DAWS else d if d in DAWS else ""
    level = level if level in LEVELS else lv or "101"
    p = load_progress()
    return dict(daw=daw, daws=DAWS, level=level, levels=LEVELS, teach=bool(lv), mode=mode,
                chapters=steps(daw, level) if daw else [],
                done=sorted(p.get(daw, {}).get("done", [])) if daw else [], at=p.get(daw, {}).get("at", "") if daw else "",
                recording=REC)


def mark(daw, sid, done=True, at=None, level=None):
    p = load_progress()
    q = p.setdefault(daw, {"done": []})
    s = set(q.get("done", []))
    if sid:
        (s.add if done else s.discard)(sid)
    q["done"] = sorted(s)
    if at is not None:
        q["at"] = at
    save_progress(p)
    return state(daw, level)


# ---------------------------------------------------------------- the tours inside the HypnoMix Studio
# The DAW page (hypnomix/app/daw/js/tour.js) keeps its progress here as well as in the browser: the answer to the first offer
# ("accepted" / "declined"), which tours are done, and the step each unfinished one was left at. Kept under the key "dawtour" of
# the same progress file, apart from the courses' own entries. The page sends its whole state; this keeps only what is sane.
TOUR_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def tour_clean(t):
    t = t if isinstance(t, dict) else {}
    done = [x for x in (t.get("done") if isinstance(t.get("done"), list) else []) if isinstance(x, str) and TOUR_ID.match(x)]
    at = t.get("at") if isinstance(t.get("at"), dict) else {}
    return dict(offered=t.get("offered") if t.get("offered") in ("accepted", "declined") else "",
                done=sorted(set(done))[:40],
                at=dict([(k, v) for k, v in at.items() if isinstance(k, str) and TOUR_ID.match(k) and type(v) is int and 0 <= v < 99][:40]))


def tour_state():
    return tour_clean(load_progress().get("dawtour"))


def tour_save(body):
    t = tour_clean(body)
    p = load_progress()
    p["dawtour"] = t
    save_progress(p)
    return t


def assistant_note():
    """For the Assistant's instructions when teacher mode is on: who it's talking to."""
    d, lv, _ = choice()
    if not lv:
        return ""
    if lv == "tour":
        return (f"\n\nTeacher mode is on (the HypnoMix tour): the person already knows recording and mixing, and is learning "
                f"HypnoMix with {DAWS.get(d, 'their DAW')}: its loop, its devices for that DAW, the song card, A/B inside the DAW, "
                "the mastering chain. Skip audio basics unless asked; be precise about HypnoMix's commands, buttons and limits, "
                "and follow the Teacher tab's order when they ask what's next.")
    name = "the complete course, A to Z" if lv == "az" else "the 101 crash course"
    return (f"\n\nTeacher mode is on ({name}): the person is a beginner who may never have used a DAW before, working in "
            f"{DAWS.get(d, 'their DAW')}. Explain in plain words, one idea at a time, define each term the first time you "
            "use it, say exactly where to click in their DAW, and check they're ready before moving on. The Teacher tab "
            "holds the lessons (record to a click, arm a track, set input gain, each effect as it's added, mastering); "
            "follow its order when they ask what's next. Encourage them: mistakes are fine and nothing changes without their OK.")


# ---------------------------------------------------------------- the wiki: the courses and the glossary, from the lessons
def _esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _md_text(t):
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _esc(t)))


WIKI_GROUP = {"live": "DAW: Ableton Live", "reaper": "DAW: REAPER", "ardour": "DAW: HypnoMix Studio"}
URL = "https://hypnomix.bradfieldenterprises.org/wiki/#"


def _more_html(items, daw):
    """`more`: a lesson (step:ID), a wiki article (its id) or a command (hypnomix NAME) -> a short line of links."""
    where = {s["id"]: ch["id"] for ch in CHAPTERS for s in ch["steps"]}
    titles = {s["id"]: s["title"] for ch in CHAPTERS for s in ch["steps"]}
    out = []
    for m in items:
        if m.startswith("step:") and m[5:] in where:
            out.append(f'<a data-wiki="learn-{daw}-{where[m[5:]]}" href="#">{_esc(titles[m[5:]])}</a>')
        elif m.startswith("hypnomix "):
            out.append(f"<code>{_esc(m)}</code>")
        elif not m.startswith("step:"):
            out.append(f'<a data-wiki="{_esc(m)}" href="#">{_esc(m)}</a>')
    return '<p><b>Read next:</b> ' + " · ".join(out) + "</p>" if out else ""


def _step_html(s, daw, name):
    """One lesson step as lean HTML for the wiki."""
    parts = [f'<h3 id="s-{_esc(s["id"])}">{_esc(s["title"])}</h3>' + "".join(f"<p>{_md_text(x)}</p>" for x in s.get("say", []))]
    if s.get("terms"):
        parts.append("<dl>" + "".join(f"<dt>{_esc(w)}</dt><dd>{_esc(m)}</dd>" for w, m in s["terms"]) + "</dl>")
    if s.get("settings"):
        parts.append('<div class="tablewrap"><table><tr><th>Control</th><th>Where to start</th><th>Why</th></tr>' +
                     "".join(f"<tr><td>{_esc(a)}</td><td>{_esc(b)}</td><td>{_esc(c)}</td></tr>" for a, b, c in s["settings"]) + "</table></div>")
    if s.get("how"):
        parts.append(f"<p><b>In {name}</b></p><ol>" + "".join(f"<li>{_md_text(x)}</li>" for x in s["how"]) + "</ol>")
    if s.get("listen"):
        parts.append(f'<div class="note-box"><b>Listen:</b> {_esc(s["listen"])}</div>')
    for h in s.get("hear") or []:
        parts.append(f'<p><b>Hear it</b> in the app\'s Teacher tab: {_esc(h["title"])}. {_esc(h["listen"])}</p>')
    if s.get("mistakes"):
        parts.append("<p><b>Common mistakes</b></p><ul>" + "".join(f"<li>{_md_text(x)}</li>" for x in s["mistakes"]) + "</ul>")
    if s.get("try"):
        parts.append(f"<p><b>Try it:</b> {_md_text(s['try']['do'])} <i>You'll know it worked when: {_md_text(s['try']['success'])}</i></p>")
    for q in s.get("quiz") or []:
        opts = "".join(f"<li>{chr(97 + i)}) {_esc(o)}</li>" for i, o in enumerate(q["options"]))   # lettered in the text: the wiki's cleaner drops <ol type>
        parts.append(f"<details><summary><b>Check yourself:</b> {_esc(q['q'])}</summary><ul>{opts}</ul>"
                     f"<p>Answer: {_esc(q['options'][q['answer']])}. {_esc(q['why'])}</p></details>")
    if s.get("more"):
        parts.append(_more_html(s["more"], daw))
    return "".join(parts)


def _article(aid, daw, title, sub, html, group=None):
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
    return dict(id=aid, group=group or WIKI_GROUP.get(daw, "Reference"), title=title, sub=sub, no="", teaser="",
                html=html, text=text, url=URL + aid, file=str(Path(__file__).resolve()), generated=True)


def wiki_articles(daw):
    """The wiki's articles for one DAW: the tour (one article), the complete course's contents page (`learn-DAW`, so old
    links keep working) and one article per chapter of that course (`learn-DAW-CHAPTER`)."""
    name = DAWS[daw]
    out = [wiki_article(daw, "az"), wiki_article(daw, "tour")]
    for i, ch in enumerate(steps(daw, "az", honesty=False)):
        first = i == 0
        n = sum(1 for s in ch["steps"])
        body = "".join(_step_html(s, daw, name) for s in ch["steps"])
        lead = f'<p class="lead">{_esc(ch["sub"][:1].upper() + ch["sub"][1:])}. {n} lessons, in {name}. In the app, the <b>Teacher</b> tab teaches the same lessons, with audio examples and quizzes.{_about(daw) if first else ""}</p>'
        if daw == "ardour" and ch["id"] in ("record", "hypnomix"):
            body += ('<div class="note-box">HypnoMix Studio gets the short version for now: HypnoMix can read and sca HypnoMix Studio sessions (<code>.ardour</code>), '
                     'but the Teacher can\'t do the hands-on steps there yet, so every step here is done by hand.</div>')
        out.append(_article(f"learn-{daw}-{ch['id']}", daw, ch["title"], f"teacher mode · {name} · {n} lessons",
                            '<div class="prose paper">' + lead + body + "</div>"))
    return out


def wiki_article(daw, level="az"):
    """The tour as one article (`tour-DAW`), or, for the complete course (any other level), its contents page (`learn-DAW`)."""
    name = DAWS[daw]
    if level == "tour":
        parts = [f'<p class="lead">For people who already record and mix: {_hm_in(daw, "with")}, its devices, and the loop from scan to master. '
                 f'In the app, the <b>Teacher</b> tab walks you through the same steps, and can do the hands-on ones for you (it asks first).{_about(daw)}</p>']
        for ch in steps(daw, "tour", honesty=False):
            parts.append(f"<h2>{_esc(ch['title'])}</h2><p><i>{_esc(ch['sub'])}</i></p>")
            parts += [_step_html(s, daw, name) for s in ch["steps"]]
        if daw == "ardour":
            parts.append('<div class="note-box">HypnoMix Studio gets the short version for now: HypnoMix can read and sca HypnoMix Studio sessions (<code>.ardour</code>), '
                         'but the Teacher can\'t do the hands-on steps there yet, so every step here is done by hand.</div>')
        return _article(f"tour-{daw}", daw, f"Guided tour: {_hm_in(daw)}",
                        "teacher mode · the devices, the song card, A/B, the mastering chain", '<div class="prose paper">' + "".join(parts) + "</div>")
    chs = steps(daw, "az", honesty=False)
    n101 = count(daw, "101")
    rows = "".join(f'<li><a data-wiki="learn-{daw}-{c["id"]}" href="#"><b>{_esc(c["title"])}</b></a>: {_esc(c["sub"])} '
                   f'<span class="note">({len(c["steps"])} lessons)</span></li>' for c in chs)
    html = ('<div class="prose paper"><p class="lead">The complete course, A to Z: from what sound is to releasing your song, with '
            f'{name} as your DAW. {sum(len(c["steps"]) for c in chs)} short lessons in {len(chs)} chapters, with audio examples, '
            f'exercises and quizzes. In the app, the <b>Teacher</b> tab teaches the same course and keeps your place; the <a data-wiki="glossary" href="#">Glossary</a> '
            f'lists every word. New and short of time? The <b>101 crash course</b> ({n101} steps for {name}) is inside it: the words and the screen, '
            f'your first recording, mixing one effect at a time, mastering, then the HypnoMix tour.</p><ol>{rows}</ol>'
            f'<p>Already a working engineer? <a data-wiki="tour-{daw}" href="#">The guided tour</a> covers only {_hm_in(daw)}.{_about(daw)}</p></div>')
    return _article(f"learn-{daw}", daw, f"The complete course: make a song from scratch in {name}",
                    "teacher mode · sound, gear, recording, editing, mixing, mastering, releasing", html)


def wiki_glossary():
    """One article: every word the lessons teach, A to Z, each with the chapter article that teaches it."""
    daw_of = {}
    for ch in CHAPTERS:
        for s in ch["steps"]:
            daw_of[s["id"]] = next((d for d in DAWS if d in s.get("daws", ALL)), "live"), ch["id"]
    rows, letter = [], ""
    for g in glossary():
        first = (re.sub(r"[^A-Za-z0-9]", "", g["term"])[:1] or "#").upper()
        if first != letter:
            letter = first
            rows.append(f"<h2>{_esc(letter)}</h2>")
        for e in g["entries"]:
            d, c = daw_of.get(e["step"], (None, None))
            link = f' <a data-wiki="learn-{d}-{c}" href="#">{_esc(e["title"])}</a>' if d else ""
            rows.append(f"<p><b>{_esc(g['term'])}</b>: {_esc(e['meaning'])}{(' <span class=note>→' + link + '</span>') if link else ''}</p>")
    html = ('<div class="prose paper"><p class="lead">Every word the lessons teach, A to Z, with the lesson that explains it. '
            'In the app, the Teacher tab has the same list with a filter.</p>' + "".join(rows) + "</div>")
    return _article("glossary", None, "Glossary", "teacher mode · every word, A to Z", html, group="Reference")


def wiki_all():
    """Every generated article: per DAW the tour, the course contents and its chapters, then the glossary."""
    out = []
    for d in DAWS:
        out += wiki_articles(d)
    return out + [wiki_glossary()]


# ---------------------------------------------------------------- the server's routes
def handle_get(path, q):
    if path == "/teacher.js":
        return 200, Path(__file__).with_name("teacher.js").read_bytes(), "text/javascript; charset=utf-8"
    if path == "/api/teach/state":
        return 200, state(q.get("daw"), q.get("level"))
    if path == "/api/teach/tour":                        # the tours inside the HypnoMix Studio (daw/js/tour.js)
        return 200, tour_state()
    if path == "/api/teach/connections":
        return 200, connections()
    if path == "/api/teach/glossary":
        return 200, dict(terms=glossary(q.get("daw")))
    if path == "/api/teach/hear":
        from hypnomix.app import teach_audio
        try:
            return 200, teach_audio.wav(str(q.get("demo", "")), str(q.get("v", "a"))), "audio/wav"
        except KeyError:
            return 404, dict(error="no such demo")
    return None


def handle_post(path, body):
    if path == "/api/teach/tour":
        return 200, tour_save(body)
    if path == "/api/teach/mark":
        daw = str(body.get("daw", ""))
        if daw not in DAWS:
            return 400, dict(error="choose your DAW first")
        return 200, mark(daw, str(body.get("step", "")), bool(body.get("done", True)), body.get("at"), body.get("level"))
    if path == "/api/teach/do":
        if body.get("ok") is not True:
            return 400, dict(error="this changes your song: it needs your OK first")
        try:
            return 200, run(str(body.get("daw", "")), str(body.get("step", "")), str(body.get("kind", "")), body.get("args") or {})
        except ValueError as e:
            return 400, dict(error=str(e))
        except Exception as e:
            return 500, dict(error=str(e))
    return None
