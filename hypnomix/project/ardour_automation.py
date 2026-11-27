"""Automation and the tempo map of a HypnoMix DAW session, written by HypnoMix's commands (vocallevel, motion,
tempomap --follow, breathe): into the open HypnoMix engine over MCP when the command is given --engine, else into a
NEW .ardour snapshot. Either way under HypnoMix's smooth-automation rules (engineer/automation_rules.py).

Level automation (the fader, trim, a send):
  edge_points(segs, base_db, ramp, cap) -> [(t, dB)]   per-line gains [(t0, t1, dB)] (vocallevel's plan) as the points
                         of a gentle S-curve at every change, centred in the gap between lines (session/vocallevel.py
                         _steps): each change is one S-curve about `ramp` s long, shortened only where two changes are
                         closer than that, never below what keeps its steepest point under 7 dB/s (else ValueError)
  write_engine(eng, route_id, control, pts)   automation_write (curve s_curve: the engine puts the cosine between
                         the points), checked against the rules with the route's facts first (automation_list: a bus
                         that carries anything but vocals is refused), ONE engine undo step
  write_file(p, track, control, pts)          the same S-curves, point by point, into the route's AutomationList
                         (gain on the Amp, trim on the Trim; state Play) of the loaded session, checked the same way
                         with the facts read from the session (what feeds a bus)
  A control that already plays automation is refused in both: those moves are made by hand.

Plug-in parameters (motion's filter sweeps) are not level moves: write_engine / write_file take them too
(`plugin:<processorId>:<index>` in the engine, the Processor's parameter-N list in the file), with curve linear.

The tempo map (sessions in the format of version 7 and later):
  from_beats(pts) -> [dict(beat, bpm, bpm_end)]   a tempo line of (beat from the start, BPM) pairs, as HypnoMix's
                         tempo writers build it (two pairs on one beat = a step, a change between beats = a glide), as
                         tempo points: a glide becomes a ramp (HypnoMix DAW ramps change the tempo linearly per beat, the
                         same line), the last point never ramps. Beats are quarter notes; positions are rounded to whole
                         beats (the engine places tempo points on beats)
  engine_points(pts, bpb) / write_tempo_engine(eng, pts, bpb)   tempo_set_points, replace-all, ONE engine undo step
  write_tempo_file(p, pts, bpb)   the session's <Tempos> replaced: each point's sclock, quarters, BBT and omega
                         computed as the session stores them (a ramp's omega = (1/end - 1/start superclocks per quarter) /
                         its length in quarters); a session with meter changes, a meter that is not x/4, or BBT
                         markers is refused
  seconds(pts, beats)    where beats land on that map (constant tempos and ramps exactly)
Audio regions keep their time when the tempo map changes; MIDI and music-time regions follow the bars.
"""
import math

from hypnomix.engineer import automation_rules as RULES
from hypnomix.project import ardour as AR

RAMP_S = 1.2
TICKS = 1920


# ---------------------------------------------------------------- level moves
def edge_points(segs, base_db=0.0, ramp=RAMP_S, cap=RULES.LINE_DB):
    """[(t0, t1, dB)] held per line -> [(t, dB)]: base_db away from every line, base_db + dB on a line, each change a
    gentle S-curve between two points (the engine's s_curve, or s_points, draws the cosine)."""
    from hypnomix.session import vocallevel as VL
    st = VL._steps(sorted(s for s in segs if s[1] > s[0]), ramp)
    if not any(abs(g) > 1e-3 for _, _, g in st):
        return []
    edges, prev = [], 0.0                      # (time, from, to)
    for i, (a, b, g) in enumerate(st):
        if abs(g - prev) > 1e-3:
            edges.append((a, prev, g))
        prev = g
        nxt = st[i + 1] if i + 1 < len(st) else None
        if nxt is None or abs(nxt[0] - b) > 1e-6:          # a gap with no line after: back to the line as it is
            if abs(g) > 1e-3:
                edges.append((b, g, 0.0))
            prev = 0.0
    for _, f, t in edges:
        if abs(t - f) > cap + 1e-6:
            raise ValueError(f"a change of {abs(t - f):.1f} dB: more than the {cap:g} dB a move may make")
    pts = []
    for i, (e, f, t) in enumerate(edges):
        half = ramp / 2
        if i:
            half = min(half, (e - edges[i - 1][0]) / 2)
        if i + 1 < len(edges):
            half = min(half, (edges[i + 1][0] - e) / 2)
        need = RULES.shortest(t - f) + 0.02
        if 2 * half < need:
            raise ValueError(f"two changes {2 * half:.2f} s apart at {e:.1f} s: too close for a smooth move "
                             f"(it needs {need:.2f} s); make that one by hand")
        a, b = max(0.0, e - half), e + half
        for q in ((a, base_db + f), (b, base_db + t)):
            if pts and abs(pts[-1][0] - q[0]) < 1e-6:
                continue
            pts.append((round(q[0], 6), round(q[1], 4)))
    return pts


def _args(route_id, control, pts, level=True):
    return {"track_id": str(route_id), "control": control, "points": [{"time": t, "value": v} for t, v in pts],
            "mode": "replace-range", "curve": "s_curve" if level else "linear",
            "start": pts[0][0], "end": pts[-1][0]}


def write_engine(eng, route_id, control, pts):
    """One automation_write into the open engine, after the rules (refusals raise ValueError with the reason).
    Returns the engine's reply."""
    if not pts:
        return None
    facts = eng.call("automation_list", {"track_id": str(route_id)})
    c = next((x for x in facts.get("controls") or [] if x.get("control") == control), None)
    if c is None:
        raise ValueError(f"{facts.get('trackName') or route_id}: no control {control} in the engine")
    if c.get("points") or c.get("state") not in (None, "manual"):
        raise ValueError(f"{facts.get('trackName') or route_id}: its {c.get('name') or control} already has automation; "
                         "make these moves by hand")
    level = RULES.kind(control) in RULES.LEVEL_KINDS
    args = _args(route_id, control, pts, level)
    line = RULES.line_from(None, c.get("current"))
    bad = RULES.check(args, facts, line, read=lambda tool, a: eng.call(tool, a))
    if bad:
        raise ValueError(RULES.sentence(bad))
    return eng.call("automation_write", args)


def steepest_of(reply):
    """The steepest move an engine reply reports ({perSecond, jump, ...}), dB/s; None when it says nothing."""
    st = (reply or {}).get("steepest")
    if isinstance(st, dict):
        st = math.inf if st.get("jump") else st.get("perSecond")
    return float(st) if isinstance(st, (int, float)) else None


# ---------------------------------------------------------------- the same, into a session file
def facts_of(p, track):
    """automation_list's route facts, read from the loaded session: is it a bus, and what feeds it."""
    kids = []

    def walk(t):
        for x in p.tracks:
            if x.parent is t and x is not t:
                kids.append({"name": x.name, "routeType": "midi_track" if x.kind == "midi" else
                             "audio_track" if x.kind == "audio" else "bus"})
                walk(x)
    if track.kind == "master":
        kids = [{"name": x.name, "routeType": "midi_track" if x.kind == "midi" else "audio_track"}
                for x in p.tracks if x.kind in ("audio", "midi")]
    elif track.kind in ("folder", "return"):
        walk(track)
    return {"trackName": track.name, "isBus": track.kind in ("folder", "return"), "isMaster": track.kind == "master",
            "feeders": [k for k in kids if k["routeType"] != "bus"]}


def _list_of(rt, control):
    """(the AutomationList element, the Controllable, unit) for a control on a route's saved XML."""
    if control in ("gain", "trim"):
        ptype, cname = ("amp", "gaincontrol") if control == "gain" else ("trim", "trimcontrol")
        pr = next((x for x in rt.findall("Processor") if x.get("type") == ptype), None)
        if pr is None:
            return None, None
        al = next((x for x in pr.iter("AutomationList") if x.get("automation-id") == control), None)
        return al, AR.controllable(pr, cname)
    if control.startswith("plugin:"):
        _, pid, idx = control.split(":", 2)
        pr = next((x for x in rt.findall("Processor") if x.get("id") == pid), None)
        if pr is None:
            return None, None
        al = next((x for x in pr.iter("AutomationList") if x.get("automation-id") == f"parameter-{idx}"), None)
        ctl = next((x for x in pr.iter("Controllable") if x.get("parameter") == str(idx)), None)
        return al, ctl
    return None, None


def write_file(p, track, control, pts, step=0.05):
    """The points into the route's AutomationList in the loaded session (save it with ardour_edit.save). Level moves
    are written as S-curves point by point (the file has no curve to ask for), gains as the session stores them (linear)."""
    import xml.etree.ElementTree as ET
    from hypnomix.project import ardour_edit as AE
    if not pts:
        return 0
    rt = track.native
    al, ctl = _list_of(rt, control)
    if al is None:
        raise ValueError(f"{track.name}: no {control} automation list in the session")
    ev = al.find("events")
    if (ev is not None and (ev.text or "").strip()) or al.get("state", "Off") != "Off":
        raise ValueError(f"{track.name}: its {control} already has automation; make these moves by hand")
    level = RULES.kind(control) in RULES.LEVEL_KINDS
    args = _args(getattr(track, "index", 0), control, pts, level)
    base = AR.num(ctl.get("value"), 1.0) if ctl is not None else 1.0
    cur = 20 * math.log10(base) if level and base > 0 else (None if level else base)
    bad = RULES.check(args, facts_of(p, track) if level else None, RULES.line_from(None, cur))
    if bad:
        raise ValueError(RULES.sentence(bad))
    dense = RULES.s_points(pts, step) if level else list(pts)
    ctx = AE.Ctx(p)
    if ev is None:
        ev = ET.SubElement(al, "events")
    ev.text = "\n" + "".join(f"{ctx.fmt(t)} {AE.num(10 ** (v / 20) if level else v)}\n" for t, v in dense)
    al.set("state", "Play")
    return len(dense)


# ---------------------------------------------------------------- the tempo map
def from_beats(line, bpb=4):
    """[(beat, bpm)] (beats from the start, as HypnoMix's tempo writers build them) -> [dict(beat, bpm, bpm_end)]."""
    pts = sorted(((float(b), float(v)) for b, v in line), key=lambda q: q[0])     # stable: a step keeps its order
    if not pts:
        return []
    out = []
    for (b0, v0), (b1, v1) in zip(pts, pts[1:]):
        if b1 - b0 < 1e-6:
            continue                                       # a step: the next pair starts the new tempo
        beat = int(round(b0))
        end = v1 if abs(v1 - v0) > 1e-6 else v0
        if out and out[-1]["beat"] == beat:
            out[-1].update(bpm=v0, bpm_end=end)
        elif out and abs(out[-1]["bpm"] - v0) < 1e-6 and abs(out[-1]["bpm_end"] - v0) < 1e-6 and abs(end - v0) < 1e-6:
            continue                                       # the same steady tempo goes on
        else:
            out.append(dict(beat=beat, bpm=v0, bpm_end=end))
    b, v = pts[-1]
    beat = int(round(b))
    if out and out[-1]["beat"] == beat:
        out[-1].update(bpm=v, bpm_end=v)
    elif not out or abs(out[-1]["bpm_end"] - v) > 1e-6 or abs(out[-1]["bpm"] - v) > 1e-6:
        out.append(dict(beat=beat, bpm=v, bpm_end=v))
    if out[0]["beat"] != 0:
        out.insert(0, dict(beat=0, bpm=out[0]["bpm"], bpm_end=out[0]["bpm"]))
    for x in out:
        if not 20 <= x["bpm"] <= 400 or not 20 <= x["bpm_end"] <= 400:
            raise ValueError(f"a tempo of {x['bpm']:g} BPM at beat {x['beat']}: tempos stay between 20 and 400 BPM")
    out[-1]["bpm_end"] = out[-1]["bpm"]                    # the last point never ramps
    return out


def seconds(pts, beats):
    """Where each beat (from the start, quarter notes) lands on the tempo points: constant tempos and ramps exactly."""
    out = []
    for q in beats:
        t = 0.0
        for i, x in enumerate(pts):
            b0 = x["beat"]
            b1 = pts[i + 1]["beat"] if i + 1 < len(pts) else math.inf
            if q <= b0:
                break
            dq = min(q, b1) - b0
            t += _span(x["bpm"], x["bpm_end"] if i + 1 < len(pts) else x["bpm"], b1 - b0 if b1 < math.inf else 0, dq)
            if q <= b1:
                break
        out.append(t)
    return out


def _span(t0, t1, length, dq):
    """Seconds over the first dq quarters of a point at t0 ramping to t1 over `length` quarters."""
    if abs(t1 - t0) < 1e-9 or length <= 0:
        return dq * 60.0 / t0
    k = (t1 - t0) / (length * t0)
    return 60.0 / (t0 * k) * math.log1p(k * dq)


def engine_points(pts, bpb=4):
    out = []
    for x in pts:
        bar, beat = divmod(int(x["beat"]), bpb)
        p = {"bar": bar + 1, "beat": beat + 1, "bpm": round(x["bpm"], 4)}
        if abs(x["bpm_end"] - x["bpm"]) > 1e-6:
            p["bpm_end"] = round(x["bpm_end"], 4)
        out.append(p)
    return out


def write_tempo_engine(eng, pts, bpb=4):
    """The whole tempo map in the open engine (tempo_set_points, replace-all): ONE engine undo step."""
    meters = (eng.call("tempo_get_map", {}) or {}).get("meters") or []
    _meter_ok([(m.get("divisionsPerBar"), m.get("noteValue")) for m in meters], bpb)
    return eng.call("tempo_set_points", {"points": engine_points(pts, bpb), "mode": "replace-all"})


def _meter_ok(meters, bpb):
    sig = {(int(a or 4), int(b or 4)) for a, b in meters} or {(4, 4)}
    if len(sig) > 1:
        raise ValueError("the session has meter changes: write its tempo map by hand")
    a, b = next(iter(sig))
    if b != 4 or a != bpb:
        raise ValueError(f"the session is in {a}/{b}: these tempo points count {bpb} quarter notes a bar (--bpb)")


def write_tempo_file(p, pts, bpb=4):
    """Replace the loaded session's tempo points (save it with ardour_edit.save)."""
    import xml.etree.ElementTree as ET
    root = p.native
    if AR.session_version(root) < 7000:
        raise ValueError("this session was saved by an older HypnoMix DAW (before 7.0): open and save it in HypnoMix DAW first")
    tm = root.find("TempoMap")
    if tm is None:
        raise ValueError("the session has no tempo map")
    meters = list(tm.iter("Meter"))
    _meter_ok([(AR.num(m.get("divisions-per-bar"), 4), AR.num(m.get("note-value"), 4)) for m in meters], bpb)
    mt = tm.find("MusicTimes")
    if mt is not None and len(mt):
        raise ValueError("the session has BBT markers: write its tempo map by hand")
    scps = int(AR.num(tm.get("superclocks-per-second"), 282240000)) or 282240000
    tempos = tm.find("Tempos")
    if tempos is None:
        tempos = ET.SubElement(tm, "Tempos")
    for old in list(tempos):
        tempos.remove(old)
    at = seconds(pts, [x["beat"] for x in pts])
    for i, (x, sec) in enumerate(zip(pts, at)):
        ramp = i + 1 < len(pts) and abs(x["bpm_end"] - x["bpm"]) > 1e-6
        omega = 0.0
        if ramp:
            q = pts[i + 1]["beat"] - x["beat"]
            s0, s1 = scps * 60.0 / x["bpm"], scps * 60.0 / x["bpm_end"]
            omega = (1.0 / s1 - 1.0 / s0) / q
        bar, beat = divmod(int(x["beat"]), bpb)
        ET.SubElement(tempos, "Tempo", {
            "npm": f"{x['bpm']:.12g}", "enpm": f"{(x['bpm_end'] if ramp else x['bpm']):.12g}", "note-type": "4",
            "type": "Ramped" if ramp else "Constant", "locked-to-meter": "0", "continuing": "0", "active": "1",
            "sclock": str(int(round(sec * scps))), "quarters": f"{int(x['beat'])}:0", "bbt": f"{bar + 1}|{beat + 1}|0",
            "omega": repr(omega) if ramp else "0"})
    p.tempo = pts[0]["bpm"]
    p.tempo_changes = len(pts)
    return len(pts)


def music_time_regions(p):
    """Regions placed in music time (they follow the bars when the tempo map changes): [(track, region name)]."""
    out = []
    for t in p.tracks:
        for c in t.clips:
            el = c.native
            at = el is not None and ((el.get("length") or "").partition("@")[2] or el.get("position") or "")
            if at and at.startswith("b"):
                out.append((t.name, c.name))
    return out
