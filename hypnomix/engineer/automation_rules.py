"""The smooth-automation rules, checked by HypnoMix before any level or plug-in automation is written
(the HypnoMix Studio engine's automation_write from the Assistant, the DAW view or a command; the .ardour file writer
too).

  - every level move is a gentle S-curve (a raised cosine; about 1.2 s is the usual length)
  - no point of a write is more than 3 dB from the ORIGINAL line of its lane (the fader and sends; a trim 4 dB): the
    line as it was heard before HypnoMix's first write to that lane, kept per session, route and control
    (engineer/automation_original.py), so writes and drags one after another never add up past it
  - the steepest point of any move stays under 7 dB/s (an S-curve peaks at pi/2 times its average slope)
  - a write starts and ends on the line as it is heard now (replace-all too), so the way into and out of it is smooth
    as well, and its range is its points (a start or end beyond them would join the old line to them in a straight
    line); one point alone on the line as it is may be added (nothing heard moves: it is a point to drag later). What
    is heard is the lane's points when it plays them, else (a lane that is Off, manual) the control's own value: a
    write switches the lane to play, so the points it keeps must then start and end on that value as well
  - a line that is not known (the control reads as silence, -inf, or cannot be read) refuses every level write: 0 dB
    is never assumed
  - never the level of a bus, a group's bus or the master when what it carries includes a track that is not a vocal
    (riding it would ride those tracks too); the roles are hypnomix's own (engineer/roles.py, by name)
  - never `force` (the engine's way to write a move it finds too steep), and never a recording state (write, touch,
    latch: any later move of the control would be written as a jump)
  - switching a level lane from Off to play is held to the same rules (judge_state): its points start and end on the
    control's value, stay under 7 dB/s and within 3 dB (a trim 4) of the original line
  - start and end are numbers (the engine would read "5" as 5 s), and the mode and curve are read as the engine reads
    them (replace_all is replace-all, s-curve is s_curve)

Plug-in parameters (a filter's cut-off, say) are not level moves and are in the plug-in's own units, so only the
mixed-bus rule (and the no-recording-state rule) holds for them: never the plug-in automation of a bus, a group's bus
or the master that carries a track that is not a vocal (moving it would move those tracks too), judged the same way.
Clearing a plug-in lane is always allowed (it removes movement). Pan, width and mute are not held to these rules (the
engine has no limit on them either). Values are the engine's natural units: dB for the fader, trim and sends (None is
silence).

  judge(args, facts, lane, read, original) -> [problem, ...]   an automation_write, against the lane as it is now
                                                            (automation_get) and the control's value (facts)
  judge_state(args, facts, lane, read, original) -> [...]   an automation_set_state the same way (starts_playing:
                                                            does it make a lane's points heard)
  check(args, facts=None, line=None, read=None, original=None) -> [problem, ...]   the write against a line already
                                                            known; [] when the write may go ahead
  heard(lane, current) -> t -> dB                           what is heard now (None when it is not known)
  checked(control) -> bool                                  is the control held to check() (level or plug-in)
  mixed_bus(facts, others, k) -> sentence                   why a bus carrying `others` is never automated (kind k)
  non_vocal(facts, read=None) -> [name, ...]                what a bus carries that is not a vocal (read: the engine's
                                                            automation_list for a bus that feeds it, read in turn)
  s_points(points, step=0.05) -> [(t, v), ...]              the points with a cosine S between each pair
"""
import math

LINE_DB = 3.0          # a line (fader, send) stays at most this far from its original line, either way
TRIM_DB = 4.0          # a trim at most this
MAX_SLOPE = 7.0        # dB/s: the steepest point of a move stays under this
RAMP_S = 1.2           # the usual length of one S-curve
ON_LINE_DB = 0.1       # a write's first and last points are on the line as it is, within this
EDGE_S = 0.01          # a replace-range write's start and end are its first and last points' times, within this
LEVEL_KINDS = ("gain", "trim", "send")
CHECKED_KINDS = LEVEL_KINDS + ("plugin",)   # held to check(): a plug-in parameter only to the mixed-bus rule
S_PEAK = math.pi / 2   # a cosine S's steepest point, as a multiple of its average slope
VOCAL_ROLES = ("lead_vocal", "backing_vocal")
PLAYING = ("play", "touch", "latch")        # a lane in these plays its points back (touch and latch while untouched)
RECORDING = ("write", "touch", "latch")     # never set by HypnoMix on a level or plug-in lane
_FACTS = object()                           # judge(): the control's value is read from the facts


def kind(control):
    """The kind of a control as automation_list names it: gain, trim, send, pan, mute, plugin or other."""
    c = str(control or "").strip().lower()
    if c in ("gain", "fader", "volume"):
        return "gain"
    if c == "trim":
        return "trim"
    if c.startswith("send:"):
        return "send"
    if c in ("pan_azimuth", "pan", "pan_width", "width"):
        return "pan"
    if c == "mute":
        return "mute"
    if c.startswith("plugin:"):
        return "plugin"
    return "other"


def checked(control):
    """Is this control held to check(): a level control (all the rules) or a plug-in parameter (the mixed-bus rule)."""
    return kind(control) in CHECKED_KINDS


def cap(k):
    """How far a level control may go from its original line."""
    return TRIM_DB if k == "trim" else LINE_DB


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def normal(args):
    """The arguments as the engine reads them: in mode an underscore is a hyphen (replace_all is replace-all), in curve
    a hyphen is an underscore (s-curve is s_curve). A copy; the caller's arguments are never changed."""
    a = dict(args or {})
    if isinstance(a.get("mode"), str):
        a["mode"] = a["mode"].replace("_", "-")
    if isinstance(a.get("curve"), str):
        a["curve"] = a["curve"].replace("-", "_")
    return a


def replace_all(args):
    return normal(args).get("mode") == "replace-all"


def _what(k):
    return {"gain": "fader", "trim": "trim", "send": "send level"}.get(k, "level")


def arg_problems(args, tool="automation_write"):
    """start and end as the engine reads them: a number (or left out). The engine would read the text "5" as 5 s, where
    a check that skips what is not a number would not: so anything else is refused."""
    a = args or {}
    out = []
    for key in ("start", "end"):
        v = a.get(key)
        if v is not None and not _num(v):
            out.append(f"{key} must be a number of seconds (not text, true or anything else: the engine reads those "
                       f"differently)")
    return out


def recording(state, k):
    """The sentence for a recording state on a level or plug-in lane, or ''."""
    if not isinstance(state, str) or state not in RECORDING:
        return ""
    what = "plug-in parameter" if k == "plugin" else _what(k)
    return (f"state {state} is never used on a {what} lane: a recording mode turns any later move of the control into "
            f"a jump written as automation; use play (or manual)")


def points_of(raw):
    """[{time, value}] or [[time, value]] -> [(time, value)], value None for silence; anything else is left out."""
    out = []
    for p in raw or []:
        if isinstance(p, dict):
            t, v = p.get("time"), p.get("value")
        elif isinstance(p, (list, tuple)) and len(p) == 2:
            t, v = p
        else:
            continue
        if _num(t) and (v is None or _num(v)):
            out.append((float(t), None if v is None else float(v)))
    return out


def moves(pts):
    """[(t0, t1, change)] between each pair of points that both have a value."""
    return [(a[0], b[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]) if a[1] is not None and b[1] is not None]


def rate(t0, t1, d, curve="s_curve"):
    """The steepest point of one move, dB/s (inf for a jump)."""
    if abs(d) < 1e-9:
        return 0.0
    if t1 - t0 <= 1e-9:
        return math.inf
    return (S_PEAK if curve == "s_curve" else 1.0) * abs(d) / (t1 - t0)


def steepest(pts, curve="s_curve"):
    return max((rate(a, b, d, curve or "linear") for a, b, d in moves(pts)), default=0.0)


def shortest(d):
    """The shortest S-curve a move of d dB may take, in seconds."""
    return S_PEAK * abs(d) / MAX_SLOPE


def s_points(pts, step=0.05):
    """The points with a raised-cosine S between each pair (one every `step` s), as the engine's s_curve writes them."""
    pts = [p for p in pts if p[1] is not None]
    out = list(pts[:1])
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        n = max(1, int(math.ceil((t1 - t0) / step))) if abs(v1 - v0) > 1e-9 else 1
        for i in range(1, n + 1):
            f = i / n
            out.append((t0 + (t1 - t0) * f, v0 + (v1 - v0) * (1 - math.cos(math.pi * f)) / 2))
    return out


def _vocal(name, route_type=""):
    from hypnomix.engineer import roles as RO
    if str(route_type) == "midi_track":
        return False
    return RO.by_name(str(name or "")) in VOCAL_ROLES


def non_vocal(facts, read=None, _seen=None, _depth=0):
    """The tracks a bus, a group's bus or the master carries that are not vocals (automation_list's busOfGroup members
    and feeders), by hypnomix's roles; [] for a track, or for a bus that carries only vocals. A bus that feeds it is
    judged by what it carries, not by its name (a bus called Vocals may hold the strings too): read(tool, args) reads
    that bus's own automation_list from the engine, in turn; without read, or when it cannot be read, such a bus
    counts as not only vocals."""
    f = facts or {}
    if not (f.get("isBus") or f.get("isMaster") or f.get("busOfGroup")):
        return []
    seen = _seen if _seen is not None else {str(f.get("trackId") or "")}
    out = []
    members = ((f.get("busOfGroup") or {}).get("members") or []) + (f.get("feeders") or [])
    for m in members:
        if not isinstance(m, dict):
            continue
        key = str(m.get("trackId") or m.get("name"))
        if key in seen:
            continue
        seen.add(key)
        if str(m.get("routeType") or "") == "bus":
            sub = None
            if read is not None and _depth < 8 and m.get("trackId"):
                try:
                    sub = read("automation_list", {"track_id": str(m["trackId"])})
                except Exception:
                    sub = None
            if not isinstance(sub, dict):
                out.append(str(m.get("name") or key))
                continue
            sub = dict(sub, isBus=True)
            out += [n for n in non_vocal(sub, read, seen, _depth + 1) if n not in out]
            continue
        if not _vocal(m.get("name"), m.get("routeType")):
            out.append(str(m.get("name") or key))
    return out


def forced(v):
    """The engine's force flag as the engine reads it (true, "true", 1 or "1")."""
    return v is True or (not isinstance(v, bool) and str(v).strip().lower() in ("true", "1"))


def _line(pts):
    """t -> value along valued points (straight between them, flat outside them); .points holds them."""
    def at(t):
        if t <= pts[0][0]:
            return pts[0][1]
        for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
            if t0 <= t <= t1:
                return v0 if t1 - t0 <= 1e-9 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
        return pts[-1][1]
    at.points = list(pts)
    return at


def flat(value):
    """t -> value everywhere (a lane with no points: the control's own value), or None when it is not a number."""
    if not _num(value):
        return None
    f = lambda t: float(value)
    f.points = []
    return f


def line_from(reply, current=None):
    """A function t -> the line's value in dB, from automation_get's reply (its points, straight between them, flat
    before the first and after the last), or the control's current value when it has none. None when neither is known
    (a lane whose points are all silence is not known either). It does not look at the lane's state: heard() does."""
    raw = points_of((reply or {}).get("pointList"))
    pts = [p for p in raw if p[1] is not None]
    if raw and not pts:
        return None
    if not pts:
        return flat(current)
    return _line(pts)


def state_of(lane, facts=None, control=None):
    """The lane's playback state: automation_get's, else automation_list's for the control, else manual."""
    s = (lane or {}).get("state")
    if not s:
        c = control_of(facts, control)
        s = c.get("state") if c else None
    return str(s or "manual")


def control_of(facts, control):
    return next((c for c in (facts or {}).get("controls") or [] if isinstance(c, dict) and c.get("control") == control), None)


def current_of(facts, control):
    """The control's value as automation_list reports it (None for silence or when it is not listed)."""
    c = control_of(facts, control)
    v = c.get("current") if c else None
    return float(v) if _num(v) else None


def heard(lane, current=None):
    """t -> what is heard now, in dB: the lane's points when it plays them (play, touch, latch), else (Off, manual,
    write, or no points) the control's current value. None when that is not known."""
    if str((lane or {}).get("state") or "manual") in PLAYING and points_of((lane or {}).get("pointList")):
        return line_from(lane, current)
    return flat(current)


def _fmt(t):
    return f"{t:.2f} s"


def mixed_bus(facts, others, k):
    """The sentence for a bus, a group's bus or the master that carries `others` (non_vocal), for a control of kind k."""
    name = (facts or {}).get("trackName") or "this bus"
    names = f"{', '.join(others[:6])}{' and more' if len(others) > 6 else ''}"
    if k == "plugin":
        return (f"{name} carries {names}, not only vocals: its plug-in automation is never written (it would move them "
                f"too); automate a vocal track's plug-in instead")
    what = {"gain": "fader", "trim": "trim", "send": "send level"}.get(k, "level")
    return (f"{name} carries {names}, not only vocals: its {what} is never automated (it would ride them too); "
            f"automate the vocal tracks instead")


def unknown(k):
    what = _what(k)
    return (f"the {what}'s line as it is now is not known (the engine reads it as silence, -inf, or could not read it): "
            f"HypnoMix never assumes 0 dB, so nothing is written; set the {what} to a level first, or make this move "
            f"by hand")


def _value_at(pts, t):
    """The value at t along points (straight between them, flat outside)."""
    return _line(pts)(t)


def _farthest(pts, original, dense=True):
    """(t, value, original there, distance) where the points (with their S-curves when dense) go farthest from the
    original line; None for no points. The S between two points and the original's own points are both looked at."""
    pts = [p for p in pts if p[1] is not None]
    if not pts:
        return None
    path = s_points(pts, 0.05) if dense else list(pts)
    times = [t for t, _ in path] + [t for t, _ in getattr(original, "points", []) if pts[0][0] < t < pts[-1][0]]
    best = None
    for t in times:
        v, o = _value_at(path, t), original(t)
        if o is None:
            continue
        d = abs(v - o)
        if best is None or d > best[3]:
            best = (t, v, o, d)
    return best


def _far_problem(pts, original, k, dense=True, kept=False):
    f = _farthest(pts, original, dense)
    lim = cap(k)
    if f is None or f[3] <= lim + 1e-6:
        return ""
    t, v, o, d = f
    who = "a trim" if k == "trim" else "a line"
    return (f"at {_fmt(t)} {'the lane would be' if kept else 'the write is'} at {v:.1f} dB, {d:.1f} dB from the original "
            f"line there ({o:.1f} dB): {who} stays at most {lim:g} dB from its original line (the line as it was before "
            f"HypnoMix first wrote to it), however many writes come one after another")


def check(args, facts=None, line=None, read=None, original=None):
    """Why this automation_write must not be sent, as plain sentences ([] when it may). facts: automation_list's reply
    for the route (for what a bus carries); line: t -> what is heard now (heard(): the edges of the write, either
    mode, are judged against it; None, not known, refuses a level write); original: t -> the lane's original line
    (automation_original.pick; the line itself when not given); read(tool, args): the engine, for the buses that feed
    a bus (non_vocal). Level controls (fader, trim, sends) are held to every rule; a plug-in parameter only to the
    mixed-bus one and the no-recording-state one (its values are in the plug-in's units, so the dB rules mean nothing
    there); anything else is not checked."""
    a = normal(args)
    k = kind(a.get("control"))
    if k not in CHECKED_KINDS:
        return []
    out = arg_problems(a)
    rec = recording(a.get("state"), k)
    if rec:
        out.append(rec)
    others = non_vocal(facts, read)
    if k == "plugin":
        return out + ([mixed_bus(facts, others, k)] if others else [])
    what = _what(k)
    if forced(a.get("force")):
        out.append("force is never used: a level move steeper than 7 dB/s is made longer, not forced")
    if others:
        out.append(mixed_bus(facts, others, k))
    raw = a.get("points") or []
    pts = points_of(raw) if isinstance(raw, list) else []
    if not isinstance(raw, list) or len(pts) != len(raw):
        out.append("every point needs a time in seconds and a value")
    if line is None:
        out.append(unknown(k))
        return out
    every = a.get("mode") == "replace-all"
    if pts and not every:
        for key, t, edge in (("start", pts[0][0], "first"), ("end", pts[-1][0], "last")):
            v = a.get(key)
            if v is not None and (not _num(v) or abs(float(v) - t) > EDGE_S):
                out.append(f"{key} must be the {edge} point's time ({_fmt(t)}): a range wider than the points would be "
                           f"joined to the line outside them without an S-curve")
    if (len(pts) == 1 and not out and not every and pts[0][1] is not None
            and line(pts[0][0]) is not None and abs(pts[0][1] - line(pts[0][0])) <= ON_LINE_DB):
        return out                  # one point on the line as it is (a point added to drag later): nothing is heard to move
    if len(pts) < 2:
        out.append("a level move needs at least two points: one on the line as it is, and where it goes")
        return out
    if any(v is None for _, v in pts):
        out.append(f"a {what} move never goes to silence: use mute, or a region fade")
    if any(b[0] <= a_[0] for a_, b in zip(pts, pts[1:])):
        out.append("the points must be in time order, each later than the one before (two values at one time is a jump)")
        return out
    if str(a.get("curve") or "linear") != "s_curve":
        out.append("level moves are written as gentle S-curves: curve must be s_curve")
    for t0, t1, d in moves(pts):
        r = rate(t0, t1, d, "s_curve")
        if r >= MAX_SLOPE:
            out.append(f"the move from {_fmt(t0)} to {_fmt(t1)} ({d:+.1f} dB) peaks at {r:.1f} dB/s: under {MAX_SLOPE:g} dB/s "
                       f"it needs at least {shortest(d) + 0.01:.2f} s")
    far = _far_problem(pts, original if original is not None else line, k)
    if far:
        out.append(far)
    for (t, v), edge in ((pts[0], "starts"), (pts[-1], "ends")):
        want = line(t)
        if want is not None and v is not None and abs(v - want) > ON_LINE_DB:
            out.append(f"the write {edge} at {v:.1f} dB ({_fmt(t)}) but the line there is {want:.1f} dB: start and end "
                       f"on the line, so the way in and out is an S-curve too"
                       + (" (replace-all puts every other point of the lane away: the line is then what is heard now)"
                          if every else ""))
    return out


def play_problems(lane, current, original=None, k="gain"):
    """Why a level lane that is not playing must not start playing its points ([] when it may): what is heard becomes
    its points instead of the control's current value, so they must start and end on that value, no move between two
    of them may be steeper than 7 dB/s, and none may be more than 3 dB (a trim 4) from the original line."""
    pts = points_of((lane or {}).get("pointList"))
    if not pts:
        return []
    what = _what(k)
    if not _num(current):
        return [unknown(k)]
    if any(v is None for _, v in pts):
        return [f"the lane holds silence (-inf) among its points: switching it to play could jump; make this change by "
                f"hand"]
    out = []
    for (t, v), edge in ((pts[0], "starts"), (pts[-1], "ends")):
        if abs(v - current) > ON_LINE_DB:
            out.append(f"the lane's points {edge} at {v:.1f} dB ({_fmt(t)}) but the {what} is at {current:.1f} dB now: "
                       f"playing them would jump to them; start and end them on the {what}'s value")
            break
    for t0, t1, d in moves(pts):
        r = rate(t0, t1, d, "linear")
        if r >= MAX_SLOPE:
            out.append(f"the lane moves {d:+.1f} dB from {_fmt(t0)} to {_fmt(t1)}, {r:.1f} dB/s: steeper than "
                       f"{MAX_SLOPE:g} dB/s")
            break
    far = _far_problem(pts, original if original is not None else flat(current), k, dense=False, kept=True)
    if far:
        out.append(far)
    return out


def _after(lane, args):
    """The lane's points after a replace-range write: what it keeps outside the range, and the new points (their
    S-curves drawn as the engine writes them)."""
    a = normal(args)
    new = [p for p in points_of(a.get("points")) if p[1] is not None]
    if not new:
        return points_of((lane or {}).get("pointList"))
    lo = a.get("start") if _num(a.get("start")) else new[0][0]
    hi = a.get("end") if _num(a.get("end")) else new[-1][0]
    kept = [p for p in points_of((lane or {}).get("pointList")) if p[0] < lo - 1e-9 or p[0] > hi + 1e-9]
    dense = s_points(new) if str(a.get("curve") or "linear") == "s_curve" else new
    return sorted(kept + dense, key=lambda p: p[0])


def judge(args, facts=None, lane=None, read=None, original=None, current=_FACTS):
    """Why an automation_write must not be sent ([] when it may), judged against the lane as it is now: lane is
    automation_get's reply (its points and state), facts automation_list's (what the route carries, the control's
    current value unless `current` is given), original t -> the lane's original line (automation_original.pick).
    What is heard (heard()) is the line the write's edges must meet. A lane that is not playing and that the write
    switches to play (its state, play unless given) is judged as a whole afterwards: its old points become heard."""
    a = normal(args)
    ctl = a.get("control")
    k = kind(ctl)
    if k not in CHECKED_KINDS:
        return []
    now = state_of(lane, facts, ctl)
    out = []
    if a.get("state") == "keep" and now in RECORDING:
        out.append(recording(now, k) + " (the lane is in it now, and keep would leave it there)")
    if k == "plugin":
        return out + check(a, facts, None, read)
    cur = current_of(facts, ctl) if current is _FACTS else (float(current) if _num(current) else None)
    lane = dict(lane or {}, state=now)
    out += check(a, facts, heard(lane, cur), read, original)
    after = now if a.get("state") == "keep" else str(a.get("state") or "play")
    if not out and now not in PLAYING and after in PLAYING and a.get("mode") != "replace-all":
        out += play_problems({"pointList": [list(p) for p in _after(lane, a)]}, cur, original, k)
    return out


def starts_playing(args, facts=None, lane=None):
    """Does this automation_set_state make a lane's points heard (to play, from a state that does not play them, on a
    lane that has points)?"""
    a = args or {}
    return (a.get("state") == "play" and state_of(lane, facts, a.get("control")) not in PLAYING
            and bool(points_of((lane or {}).get("pointList"))))


def judge_state(args, facts=None, lane=None, read=None, original=None, current=_FACTS):
    """Why an automation_set_state must not be sent ([] when it may). A recording state (write, touch, latch) is never
    set on a level or plug-in lane. Switching a lane that is not playing to play makes its points heard: on a bus
    that carries a track that is not a vocal that is refused (the mixed-bus rule), and a level lane is judged by
    play_problems. Switching a lane off (manual) removes movement: allowed."""
    a = args or {}
    ctl = a.get("control")
    k = kind(ctl)
    if k not in CHECKED_KINDS:
        return []
    s = a.get("state")
    rec = recording(s, k)
    if rec:
        return [rec]
    if not starts_playing(a, facts, lane):
        return []
    others = non_vocal(facts, read)
    if others:
        return [mixed_bus(facts, others, k)]
    if k == "plugin":
        return []
    cur = current_of(facts, ctl) if current is _FACTS else (float(current) if _num(current) else None)
    return play_problems(lane, cur, original, k)


def check_clear(args, reply):
    """Why an automation_clear must not be sent ([] when it may): clearing a stretch inside a level lane joins the points
    either side with a straight line, a move no S-curve shapes, so a ranged clear is refused unless they are level
    with each other (within 0.1 dB). Clearing a whole lane (no start or end) puts the control back to its own value:
    not a move. A range is both a start and an end, numbers (the engine takes nothing else). A plug-in lane may always
    be cleared, on any route (clearing removes movement; nothing is written). reply: automation_get's reply for the
    control as it is now."""
    a = args or {}
    if kind(a.get("control")) not in LEVEL_KINDS or (a.get("start") is None and a.get("end") is None):
        return []
    bad = arg_problems(a, "automation_clear")
    if bad:
        return bad
    if a.get("start") is None or a.get("end") is None:
        return ["give both start and end to clear a stretch, or neither to clear the whole lane (a clear from one edge "
                "to the end of the song would leave the ridden value there, with no S-curve back)"]
    pts = [p for p in points_of((reply or {}).get("pointList")) if p[1] is not None]
    lo, hi = float(a["start"]), float(a["end"])
    before = [p for p in pts if p[0] < lo]
    after = [p for p in pts if p[0] > hi]
    if before and after and abs(after[0][1] - before[-1][1]) > ON_LINE_DB:
        return [f"clearing {_fmt(max(lo, before[-1][0]))} to {_fmt(min(hi, after[0][0]))} would join {before[-1][1]:.1f} dB "
                f"and {after[0][1]:.1f} dB with a straight move, not an S-curve: write the move instead (automation_write, "
                f"curve s_curve) or clear the whole lane"]
    return []


def sentence(problems):
    """The problems as one reply: 'not written: ...'."""
    return "not written (HypnoMix's smooth-automation rules): " + "; ".join(problems) + "."
