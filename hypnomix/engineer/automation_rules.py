"""The smooth-automation rules, checked by HypnoMix before any level or plug-in automation is written
(the HypnoMix Studio engine's automation_write from the Assistant, the DAW view or a command; the .ardour file writer
too).

  - every level move is a gentle S-curve (a raised cosine; about 1.2 s is the usual length)
  - a line move is at most 3 dB (the fader and sends), a trim at most 4 dB
  - the steepest point of any move stays under 7 dB/s (an S-curve peaks at pi/2 times its average slope)
  - a write starts and ends on the line as it is, so the way into and out of it is smooth as well, and its range is
    its points (a start or end beyond them would join the old line to them in a straight line); one point alone on
    the line as it is may be added (nothing heard moves: it is a point to drag later)
  - never the level of a bus, a group's bus or the master when what it carries includes a track that is not a vocal
    (riding it would ride those tracks too); the roles are hypnomix's own (engineer/roles.py, by name)
  - never `force` (the engine's way to write a move it finds too steep)

Plug-in parameters (a filter's cut-off, say) are not level moves and are in the plug-in's own units, so only one rule
holds for them: never the plug-in automation of a bus, a group's bus or the master that carries a track that is not a
vocal (moving it would move those tracks too), judged the same way. Clearing a plug-in lane is always allowed (it
removes movement). Pan, width and mute are not held to these rules (the engine has no limit on them either). Values
are the engine's natural units: dB for the fader, trim and sends (None is silence).

  check(args, facts=None, line=None, read=None) -> [problem, ...]   plain sentences; [] when the write may go ahead
  checked(control) -> bool                                  is the control held to check() (level or plug-in)
  mixed_bus(facts, others, k) -> sentence                   why a bus carrying `others` is never automated (kind k)
  non_vocal(facts, read=None) -> [name, ...]                what a bus carries that is not a vocal (read: the engine's
                                                            automation_list for a bus that feeds it, read in turn)
  s_points(points, step=0.05) -> [(t, v), ...]              the points with a cosine S between each pair
"""
import math

LINE_DB = 3.0          # a line move (fader, send) at most this either way
TRIM_DB = 4.0          # a trim move at most this
MAX_SLOPE = 7.0        # dB/s: the steepest point of a move stays under this
RAMP_S = 1.2           # the usual length of one S-curve
ON_LINE_DB = 0.1       # a write's first and last points are on the line as it is, within this
EDGE_S = 0.01          # a replace-range write's start and end are its first and last points' times, within this
LEVEL_KINDS = ("gain", "trim", "send")
CHECKED_KINDS = LEVEL_KINDS + ("plugin",)   # held to check(): a plug-in parameter only to the mixed-bus rule
S_PEAK = math.pi / 2   # a cosine S's steepest point, as a multiple of its average slope
VOCAL_ROLES = ("lead_vocal", "backing_vocal")


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
    """The largest move a level control may make in one step."""
    return TRIM_DB if k == "trim" else LINE_DB


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


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


def line_from(reply, current=None):
    """A function t -> the line's value in dB, from automation_get's reply (its points, straight between them, flat
    before the first and after the last), or the control's current value when it has none. None when neither is known."""
    pts = [p for p in points_of((reply or {}).get("pointList")) if p[1] is not None]
    if not pts:
        if not _num(current):
            return None
        return lambda t: float(current)

    def at(t):
        if t <= pts[0][0]:
            return pts[0][1]
        for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
            if t0 <= t <= t1:
                return v0 if t1 - t0 <= 1e-9 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
        return pts[-1][1]
    return at


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


def check(args, facts=None, line=None, read=None):
    """Why this automation_write must not be sent, as plain sentences ([] when it may). facts: automation_list's reply
    for the route (for what a bus carries); line: line_from(...) for the control as it is now (for the edges of a
    replace-range write); read(tool, args): the engine, for the buses that feed a bus (non_vocal). Level controls
    (fader, trim, sends) are held to every rule; a plug-in parameter only to the mixed-bus one (its values are in the
    plug-in's units, so the dB rules mean nothing there); anything else is not checked."""
    a = args or {}
    k = kind(a.get("control"))
    if k not in CHECKED_KINDS:
        return []
    others = non_vocal(facts, read)
    if k == "plugin":
        return [mixed_bus(facts, others, k)] if others else []
    out = []
    what = {"gain": "fader", "trim": "trim", "send": "send level"}[k]
    if forced(a.get("force")):
        out.append("force is never used: a level move steeper than 7 dB/s is made longer, not forced")
    if others:
        out.append(mixed_bus(facts, others, k))
    raw = a.get("points") or []
    pts = points_of(raw)
    if len(pts) != len(raw):
        out.append("every point needs a time in seconds and a value")
    replace_all = str(a.get("mode") or "replace-range") == "replace-all"
    if pts and not replace_all:
        for key, t, edge in (("start", pts[0][0], "first"), ("end", pts[-1][0], "last")):
            v = a.get(key)
            if v is not None and (not _num(v) or abs(float(v) - t) > EDGE_S):
                out.append(f"{key} must be the {edge} point's time ({_fmt(t)}): a range wider than the points would be "
                           f"joined to the line outside them without an S-curve")
    if (len(pts) == 1 and not out and not replace_all and line is not None and pts[0][1] is not None
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
    c = cap(k)
    for t0, t1, d in moves(pts):
        if abs(d) > c + 1e-6:
            out.append(f"the move from {_fmt(t0)} to {_fmt(t1)} is {abs(d):.1f} dB: a {'trim' if k == 'trim' else 'line'} "
                       f"move is at most {c:g} dB")
        r = rate(t0, t1, d, "s_curve")
        if r >= MAX_SLOPE:
            out.append(f"the move from {_fmt(t0)} to {_fmt(t1)} ({d:+.1f} dB) peaks at {r:.1f} dB/s: under {MAX_SLOPE:g} dB/s "
                       f"it needs at least {shortest(d) + 0.01:.2f} s")
    if not replace_all and line is not None:
        for (t, v), edge in ((pts[0], "starts"), (pts[-1], "ends")):
            want = line(t)
            if want is not None and v is not None and abs(v - want) > ON_LINE_DB:
                out.append(f"the write {edge} at {v:.1f} dB ({_fmt(t)}) but the line there is {want:.1f} dB: start and end "
                           f"on the line, so the way in and out is an S-curve too")
    return out


def check_clear(args, reply):
    """Why an automation_clear must not be sent ([] when it may): clearing a stretch inside a level lane joins the points
    either side with a straight line, a move no S-curve shapes, so a ranged clear is refused unless they are level
    with each other (within 0.1 dB). Clearing a whole lane (no start or end) puts the control back to its own value:
    not a move. A plug-in lane may always be cleared, on any route (clearing removes movement; nothing is written).
    reply: automation_get's reply for the control as it is now."""
    a = args or {}
    if kind(a.get("control")) not in LEVEL_KINDS or (a.get("start") is None and a.get("end") is None):
        return []
    pts = [p for p in points_of((reply or {}).get("pointList")) if p[1] is not None]
    lo = a.get("start") if _num(a.get("start")) else -math.inf
    hi = a.get("end") if _num(a.get("end")) else math.inf
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
