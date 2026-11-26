"""The Assistant on the Hypnomix engine: which engine tools may run without asking, the arguments models get
wrong, what a proposed change will do (before -> after), and engine replies trimmed before they go to the model.

Kept apart from chat.py (the conversation loop) so each rule here is small and testable on its own.

  READ_ONLY            the engine tools that only read. An explicit list: any tool not on it (a new one too) asks
                       first, whatever its name or the engine's readOnlyHint says.
  fix_args(...)        types and names a model commonly gets wrong (an id as a number, a track's name where its id
                       goes, regionId vs region_id), fixed before the call; the person sees the fixed call.
  preview(...)         the rows of a proposal card: "Drums · fader  0.0 dB -> -2.0 dB", read from the engine.
  trim(...)            a reply made small enough for the model (peaks summarised, long lists cut, plug-in lists
                       and parameter lists reduced to what matters, file paths cut to their names).
  plain(...)           an engine error in plain words.
  describe(...)        a card's plain-words title and summary, and what undo can do for it (UNDO_NOTES).
  offered(...)         which engine tools one request carries (a core set, plus the groups the view needs): the full
                       list costs thousands of tokens on every step.
  home_short(...)      the home folder (and any /Users/name) in a text shortened to ~, for what goes to the model.
"""
import json, math, os, re, unicodedata

# The engine tools that only read. Everything else (and any tool the engine adds later) is a proposal. A tool is here
# only when NO argument can make it change anything: the one argument that could (meters_get's ensure_rms switches
# every route's meter type) is taken out of the call (STRIP_ARGS) and out of the schema the model sees.
READ_ONLY = frozenset({
    "hello_world", "session_get_info", "session_list_snapshots", "transport_get_state", "markers_list",
    "tracks_list", "track_get_info", "track_get_regions", "track_get_fader", "region_get_info", "region_get_peaks",
    "plugin_get_description", "plugin_list_available", "midi_note_list", "midi_note_get_json", "meters_get",
    "export_status", "region_get_warp",
})


STRIP_ARGS = {"meters_get": ("ensure_rms", "ensureRms")}


def read_args(tool, args):
    """-> (the arguments of a read that runs unasked, the names taken out). An argument that would make the read change
    something is never passed on; the model is told, and a person who wants it asks for it in the DAW."""
    a = args or {}
    drop = [k for k in STRIP_ARGS.get(tool, ()) if k in a]
    return {k: v for k, v in a.items() if k not in drop}, drop


def read_only(t):
    """True only for an allowlisted tool the engine does not mark as writing."""
    name = str(t.get("name") or "")
    ann = t.get("annotations") or {}
    if name not in READ_ONLY:
        return False
    return ann.get("readOnlyHint") is not False and not ann.get("destructiveHint")


# ---------------------------------------------------------------- the schemas, made clearer for the model
HINTS = {
    "id": "route id, a decimal string (\"252\") from daw_session_overview, not the track's name",
    "track_id": "route id, a decimal string (\"252\"), not the track's name",
    "trackId": "route id, a decimal string (\"252\"), not the track's name",
    "targetId": "the receiving bus's route id (decimal string)",
    "regionId": "region id: decimal string from daw_track_get_regions",
    "region_id": "region id: decimal string from daw_track_get_regions",
    "db": "the new absolute level in dB (not a change)",
    "pluginIndex": "the plug-in's index on the track (0 = first)",
    "pluginId": "a pluginId from daw_plugin_list_available",
    "position": "0..1",
}


def schema(t):
    """The engine's input schema with a short hint on fields that have none."""
    s = t.get("inputSchema") if isinstance(t.get("inputSchema"), dict) else {}
    if s.get("type") != "object":
        return {"type": "object", "properties": {}}
    s = json.loads(json.dumps(s))
    for k in STRIP_ARGS.get(str(t.get("name")), ()):        # not offered: it would change what a read must not change
        (s.get("properties") or {}).pop(k, None)
    for k, p in (s.get("properties") or {}).items():
        if isinstance(p, dict) and not p.get("description") and k in HINTS:
            if k == "position" and t.get("name") == "track_set_pan":
                p["description"] = "0.0 = right, 0.5 = centre, 1.0 = left (Ardour's convention)"
            elif k == "position" and str(t.get("name", "")).startswith("plugin_add"):
                p["description"] = "insert at this plug-in index (omit to add at the end)"
            elif k != "position":
                p["description"] = HINTS[k]
    return s


ID_KEYS = ("id", "track_id", "trackId", "targetId", "relativeToId")


def missing_route(args, tracks):
    """The first route id in args that is not in the session (tracks: a function -> [{id, name}]), or None.
    Only checked when the session lists its tracks (an empty list checks nothing)."""
    ids = [str(args[k]) for k in ("id", "track_id", "trackId", "targetId") if isinstance(args.get(k), (str, int))]
    if not ids:
        return None
    known = {str(t.get("id")) for t in tracks() or []}
    return next((i for i in ids if known and i not in known), None)


def _camel(k):
    return re.sub(r"_([a-z])", lambda m: m.group(1).upper(), k)


def _snake(k):
    return re.sub(r"([A-Z])", lambda m: "_" + m.group(1).lower(), k)


def fix_args(sch, args, tracks=None):
    """-> (fixed arguments, [what was fixed]). tracks: [{id, name}] to turn a track's name into its id."""
    props = (sch or {}).get("properties") or {}
    out, notes = {}, []
    for k, v in (args or {}).items():
        if k not in props:                                   # regionId <-> region_id, trackId <-> track_id
            alt = next((a for a in (_camel(k), _snake(k)) if a in props and a not in args), None)
            if alt:
                notes.append(f"{k} -> {alt}")
                k = alt
        want = (props.get(k) or {}).get("type")
        if want == "string" and isinstance(v, (int, float)) and not isinstance(v, bool):
            v = str(int(v)) if float(v).is_integer() else str(v)
        elif want in ("number", "integer") and isinstance(v, str):
            try:
                n = float(v.strip().replace("dB", "").replace("db", ""))
                v = int(n) if want == "integer" and n.is_integer() else n
            except ValueError:
                pass
        elif want == "integer" and isinstance(v, float) and v.is_integer():
            v = int(v)
        elif want == "boolean" and isinstance(v, str) and v.lower() in ("true", "false", "on", "off", "yes", "no"):
            v = v.lower() in ("true", "on", "yes")
        if k in ID_KEYS and isinstance(v, str) and v and not v.isdigit() and tracks:
            hit = [t for t in tracks if str(t.get("name", "")).strip().lower() == v.strip().lower()]
            if len(hit) == 1:
                notes.append(f"{k} {v!r} -> {hit[0]['id']}")
                v = str(hit[0]["id"])
        if k == "route_ids" and isinstance(v, list):
            v = [str(int(x)) if isinstance(x, (int, float)) and not isinstance(x, bool) else x for x in v]
        out[k] = v
    return out, notes


_TYPES = {"string": (str,), "number": (int, float), "integer": (int,), "boolean": (bool,), "array": (list,),
          "object": (dict,)}


def invalid(sch, args):
    """Why these (already fixed) arguments cannot work for a change, or '' : a required field missing, a value of
    the wrong type ("loud" for a number) or one not in the field's list. Checked before a card is shown."""
    props = (sch or {}).get("properties") or {}
    a = args or {}
    miss = [k for k in (sch or {}).get("required") or [] if a.get(k) in (None, "")]
    if miss:
        return f"missing {', '.join(miss)} (required)"
    for k, v in a.items():
        p = props.get(k) or {}
        want = _TYPES.get(p.get("type"))
        if want and v is not None and (not isinstance(v, want) or (isinstance(v, bool) and bool not in want)):
            return f"{k} must be a {p['type']}, not {json.dumps(v)[:40]}"
        if isinstance(v, float) and not math.isfinite(v):
            return f"{k} must be a finite number"
        if p.get("enum") and v not in p["enum"]:
            return f"{k} must be one of {', '.join(map(str, p['enum']))}"
    return ""


# ---------------------------------------------------------------- before -> after
def _db(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "?"
    if v <= -192:
        return "-inf dB"
    return f"{v:+.1f} dB".replace("+0.0", "0.0").replace("-0.0", "0.0")


def _pan(p):
    try:
        p = float(p)
    except (TypeError, ValueError):
        return "?"
    if abs(p - 0.5) < 0.005:
        return "centre"
    return f"{abs(p - 0.5) * 200:.0f}% {'left' if p > 0.5 else 'right'}"


def _onoff(v):
    return "on" if v else "off"


def preview(tool, args, read):
    """The rows of a proposal card, [{what, before, after}], read now from the engine through read(tool, args)
    (which returns the tool's structured reply or None). Unknown tools: []."""
    a = args or {}
    rid = str(a.get("id") or a.get("track_id") or "")
    info = None

    def ti():
        nonlocal info
        if info is None:
            info = read("track_get_info", {"id": rid}) or {}
        return info

    name = lambda: ti().get("name") or f"track {rid}"
    plugins = lambda: ti().get("plugins") or []
    plug = lambda i: next((p for p in plugins() if p.get("index") == i), None)
    rows = []
    try:
        if tool == "track_set_fader_db":
            rows.append(dict(what=f"{name()} · fader", before=_db((ti().get("fader") or {}).get("db")), after=_db(a.get("db"))))
        elif tool == "track_set_fader_position":
            f = ti().get("fader") or {}
            rows.append(dict(what=f"{name()} · fader", before=f"{_db(f.get('db'))} (position {f.get('position', '?')})",
                             after=f"position {a.get('position')}"))
        elif tool in ("track_set_mute", "track_set_solo", "track_set_rec_enable", "track_set_rec_safe"):
            field = {"track_set_mute": "mute", "track_set_solo": "solo", "track_set_rec_enable": "recEnabled",
                     "track_set_rec_safe": "recSafe"}[tool]
            label = {"mute": "mute", "solo": "solo", "recEnabled": "record arm", "recSafe": "record safe"}[field]
            rows.append(dict(what=f"{name()} · {label}", before=_onoff(ti().get(field)), after=_onoff(a.get("value"))))
        elif tool == "track_set_pan":
            rows.append(dict(what=f"{name()} · pan", before=_pan((ti().get("pan") or {}).get("position")),
                             after=_pan(a.get("position"))))
        elif tool == "track_set_send_level_db":
            s = next((x for x in ti().get("sends") or [] if x.get("index") == a.get("sendIndex")), {})
            rows.append(dict(what=f"{name()} · send {a.get('sendIndex')}{' to ' + s['targetName'] if s.get('targetName') else ''}",
                             before=_db(s.get("db")), after=_db(a.get("db"))))
        elif tool == "track_rename":
            rows.append(dict(what="track name", before=name(), after=str(a.get("newName"))))
        elif tool == "track_remove":
            rows.append(dict(what=name(), before="in the session", after="removed (this cannot be undone)"))
        elif tool in ("plugin_add_by_plugin_id", "plugin_add_by_unique_id"):
            want = a.get("pluginId") or a.get("uniqueId") or ""
            avail = (read("plugin_list_available", {}) or {}).get("plugins") or []
            p = next((x for x in avail if want in (x.get("pluginId"), x.get("uniqueId"))), None)
            new = (p or {}).get("name") or str(want)
            now = [x.get("name") for x in plugins()]
            after = list(now)
            pos = a.get("position")
            after.insert(pos if isinstance(pos, int) and 0 <= pos <= len(after) else len(after), new + " (new)")
            rows.append(dict(what=f"{name()} · plug-ins", before=", ".join(now) or "none", after=", ".join(after)))
        elif tool == "plugin_remove":
            p = plug(a.get("pluginIndex"))
            rows.append(dict(what=f"{name()} · plug-in {a.get('pluginIndex')}", before=(p or {}).get("name", "?"), after="removed"))
        elif tool == "plugin_set_enabled":
            p = plug(a.get("pluginIndex")) or {}
            rows.append(dict(what=f"{name()} · {p.get('name', 'plug-in ' + str(a.get('pluginIndex')))}",
                             before=_onoff(p.get("enabled")), after=_onoff(a.get("enabled"))))
        elif tool in ("plugin_set_parameter_by_index_value", "plugin_set_parameter_by_control_value",
                      "plugin_set_parameter_by_index_interface", "plugin_set_parameter_by_control_interface"):
            d = read("plugin_get_description", {"id": rid, "pluginIndex": a.get("pluginIndex")}) or {}
            key = "index" if "by_index" in tool else "controlId"
            want = a.get("parameterIndex") if key == "index" else a.get("controlId")
            par = next((x for x in d.get("parameters") or [] if x.get(key) == want), {})
            iface = tool.endswith("interface")
            cur = par.get("currentInterface" if iface else "currentValue")
            new = a.get("interface" if iface else "value")
            rows.append(dict(what=f"{name()} · {(d.get('plugin') or {}).get('name', 'plug-in')} · "
                                  f"{par.get('label', 'parameter ' + str(want))}{'' if iface else _range(par)}",
                             before=_num(cur), after=_num(new)))
        elif tool == "region_set_gain_db":
            r = (read("region_get_info", {"regionId": a.get("regionId")}) or {}) if a.get("regionId") else {}
            rows.append(dict(what=f"region {r.get('name') or a.get('regionId') or '(selected)'} · gain",
                             before=_db((r.get("audio") or {}).get("gainDb")) if r else "?", after=_db(a.get("db"))))
        elif tool == "region_mute":
            r = read("region_get_info", {"regionId": a.get("region_id")}) or {}
            rows.append(dict(what=f"region {r.get('name') or a.get('region_id')} · mute", before=_onoff(r.get("muted")),
                             after=_onoff(a.get("muted", True))))
        elif tool in ("session_undo", "session_redo"):
            n = a.get("count") or 1
            rows.append(dict(what="session", before="as it is", after=f"{tool[8:]} {n} step{'s' if n != 1 else ''}"))
        elif tool == "session_save":
            rows.append(dict(what="session file", before="last saved state",
                             after=f"saved{(' as snapshot ' + str(a['snapshotName'])) if a.get('snapshotName') else ''}"))
        else:
            rows.extend(_more_rows(tool, a, read, ti, name, plugins))
    except Exception:                               # a preview is a courtesy: never block a proposal on it
        return rows
    return rows


def _region(read, a):
    """The region a call names: its info from the engine, or {}."""
    rid = a.get("regionId") or a.get("region_id")
    return (read("region_get_info", {"regionId": str(rid)}) or {}) if rid else {}


def _rname(r, a):
    return str(r.get("name") or a.get("regionId") or a.get("region_id") or "(selected)")


def _at(a):
    """Where a call puts something, in words: a sample, a bar and beat, or a distance."""
    if a.get("sample") is not None:
        return f"sample {a['sample']}"
    if a.get("bar") is not None:
        return f"bar {a['bar']}" + (f" beat {a['beat']}" if a.get("beat") is not None else "")
    if a.get("deltaSamples") is not None:
        return f"{int(a['deltaSamples']):+d} samples"
    if a.get("deltaBeats") is not None:
        return f"{float(a['deltaBeats']):+g} beats"
    return "the new place"


def _more_rows(tool, a, read, ti, name, plugins):
    """Rows for the tools that remove, move, split or write something: what goes, where to, in words."""
    rows = []
    if tool == "region_remove":
        r = _region(read, a)
        rows.append(dict(what=f"region {_rname(r, a)}", before="on the timeline", after="removed (the audio stays in the session)"))
    elif tool in ("region_split",):
        r = _region(read, a)
        rows.append(dict(what=f"region {_rname(r, a)}", before="one region", after=f"two regions, cut at {_at(a)}"))
    elif tool.startswith(("region_move_", "region_copy_")):
        r = _region(read, a)
        verb = "moved" if "_move_" in tool else "copied"
        where = _at(a) + (f" on track {a['trackId']}" if a.get("trackId") else "")
        rows.append(dict(what=f"region {_rname(r, a)} · position", before=f"starts at sample {r.get('startSample', '?')}",
                         after=f"{verb}: {where}"))
    elif tool.startswith("region_resize_"):
        r = _region(read, a)
        rows.append(dict(what=f"region {_rname(r, a)} · length", before=f"{r.get('lengthSamples', '?')} samples",
                         after=f"{a.get('startSample', a.get('startBar', 'same start'))} to {a.get('endSample', a.get('endBar', 'same end'))}"))
    elif tool in ("region_set_gain_linear", "region_normalize"):
        r = _region(read, a)
        rows.append(dict(what=f"region {_rname(r, a)} · gain", before=_db((r.get("audio") or {}).get("gainDb")),
                         after=("peak at " + _db(a.get("targetDb", 0))) if tool == "region_normalize" else f"x{a.get('linear')}"))
    elif tool == "region_set_fades":
        r = _region(read, a)
        rows.append(dict(what=f"region {_rname(r, a)} · fades", before="as they are",
                         after=f"in {a.get('fade_in_samples', 'same')} / out {a.get('fade_out_samples', 'same')} samples"))
    elif tool == "region_set_envelope":
        r = _region(read, a)
        rows.append(dict(what=f"region {_rname(r, a)} · gain envelope", before="as it is",
                         after=f"{len(a.get('points') or [])} points"))
    elif tool in ("region_set_warp", "region_clear_warp"):
        r = _region(read, a)
        rows.append(dict(what=f"region {_rname(r, a)} · warp", before="its current warp",
                         after="no warp (original timing)" if tool == "region_clear_warp" else f"{len(a.get('anchors') or [])} warp points"))
    elif tool == "markers_delete_by_name":
        rows.append(dict(what=f"marker {a.get('name')}", before="in the session", after="deleted"))
    elif tool == "markers_delete_by_location_id":
        rows.append(dict(what=f"marker {a.get('locationId')}", before="in the session", after="deleted"))
    elif tool in ("markers_rename_by_name", "markers_rename_by_location_id"):
        rows.append(dict(what="marker name", before=str(a.get("name") or a.get("locationId")), after=str(a.get("newName"))))
    elif tool in ("markers_add", "markers_add_range_samples", "markers_add_range_bbt"):
        rows.append(dict(what="markers", before="-", after=f"{a.get('name') or 'a marker'} at {_at(a) if tool == 'markers_add' else 'the range given'}"))
    elif tool == "track_remove_send":
        s = next((x for x in ti().get("sends") or [] if x.get("index") == a.get("sendIndex")), {})
        rows.append(dict(what=f"{name()} · send {a.get('sendIndex')}{' to ' + s['targetName'] if s.get('targetName') else ''}",
                         before=_db(s.get("db")) if s else "in place", after="removed"))
    elif tool == "track_add_send":
        rows.append(dict(what=f"{name()} · sends", before="as they are",
                         after=f"new send to {a.get('targetId')}" + (f" at {_db(a['db'])}" if a.get("db") is not None else "")))
    elif tool == "plugin_reorder":
        now = [str(x.get("name")) for x in plugins()]
        after = list(now)
        try:
            after.insert(int(a["toIndex"]), after.pop(int(a["fromIndex"])))
        except (KeyError, ValueError, IndexError, TypeError):
            after = ["(order changed)"]
        rows.append(dict(what=f"{name()} · plug-in order", before=", ".join(now) or "none", after=", ".join(after)))
    elif tool == "plugin_set_position":
        p = next((x for x in plugins() if x.get("index") == a.get("pluginIndex")), {})
        rows.append(dict(what=f"{name()} · {p.get('name', 'plug-in ' + str(a.get('pluginIndex')))} · place",
                         before="as it is", after="after the fader" if a.get("postFader") else "before the fader"))
    elif tool == "track_set_color":
        rows.append(dict(what=f"{ (read('track_get_info', {'id': str(a.get('track_id'))}) or {}).get('name') or 'track ' + str(a.get('track_id'))} · colour",
                         before="as it is", after=str(a.get("color"))))
    elif tool == "track_reorder":
        rows.append(dict(what="track order", before="as it is", after="a new order (this cannot be undone)"))
    elif tool in ("tracks_add", "buses_add"):
        rows.append(dict(what="new " + ("tracks" if tool == "tracks_add" else "buses"), before="-",
                         after=f"{a.get('count') or 1} x {a.get('type') or 'audio'}{' named ' + str(a['name']) if a.get('name') else ''}"))
    elif tool == "session_import_audio":
        paths = [os.path.basename(str(x)) for x in a.get("paths") or []]
        rows.append(dict(what="audio files", before="-", after=f"{len(paths)} copied into the session: " + ", ".join(paths[:5])
                         + (f" and {len(paths) - 5} more" if len(paths) > 5 else "")))
    elif tool == "session_export_mix":
        rows.append(dict(what="the mix", before="-", after="bounced to a new file: " + os.path.basename(str(a.get("path") or "?"))))
    elif tool == "session_rename":
        rows.append(dict(what="session name", before="as it is", after=str(a.get("newName"))))
    return rows


def _num(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"{v:g}" if abs(v) >= 0.01 or v == 0 else f"{v:.4f}"
    return "?" if v is None else str(v)


def _range(par):
    if "lower" in par and "upper" in par:
        return f" ({_num(par['lower'])}..{_num(par['upper'])})"
    return ""


SETTLES = ("track_set_mute", "track_set_solo", "track_set_rec_enable", "track_set_rec_safe", "plugin_set_enabled",
           "region_mute")   # the engine queues these ("submitted"): a read straight after can still see the old value


def readback(tool, args, read, tries=8, pause=0.1):
    """After an approved change: the same rows' current value, as text ("Drums · fader now -2.0 dB"), or ''.
    For a change the engine applies a moment later, read again (up to tries x pause) until it shows the new value."""
    import time
    rows = preview(tool, args, read)
    for _ in range(tries if tool in SETTLES else 0):
        if all(r.get("before") == r.get("after") for r in rows):
            break
        time.sleep(pause)
        rows = preview(tool, args, read)
    return "; ".join(f"{r['what']} now {r['before']}" for r in rows if r.get("before") not in (None, "?"))

# ---------------------------------------------------------------- a card in plain words
# What the person reads first on a proposal card: one title in plain words per changing tool (the exact call stays under
# a disclosure). Every tool the engine offers that is not read-only has one (a test holds that against the real list).
TITLES = {
    "session_save": "Save the session", "session_undo": "Undo in the session", "session_redo": "Redo in the session",
    "session_rename": "Rename the session", "session_quick_snapshot": "Save a snapshot of the session",
    "session_store_mixer_scene": "Store a mixer scene", "session_recall_mixer_scene": "Recall a mixer scene",
    "session_import_audio": "Import audio files", "session_export_mix": "Bounce the mix to a new audio file",
    "transport_locate_sample": "Move the playhead", "transport_locate_bbt": "Move the playhead",
    "transport_goto_start": "Move the playhead to the start", "transport_goto_end": "Move the playhead to the end",
    "transport_prev_marker": "Jump to the previous marker", "transport_next_marker": "Jump to the next marker",
    "transport_loop_toggle": "Switch looping on or off", "transport_loop_location_samples": "Set the loop range",
    "transport_loop_location_bbt": "Set the loop range", "transport_set_record_enable": "Arm or disarm recording",
    "transport_set_speed": "Change the playback speed", "transport_play": "Start playback", "transport_stop": "Stop playback",
    "markers_add": "Add a marker", "markers_add_range_samples": "Add a range marker", "markers_add_range_bbt": "Add a range marker",
    "markers_set_auto_loop_samples": "Set the loop range", "markers_set_auto_loop_bbt": "Set the loop range",
    "markers_hide_auto_loop": "Show or hide the loop range", "markers_set_auto_punch_samples": "Set the punch range",
    "markers_set_auto_punch_bbt": "Set the punch range", "markers_hide_auto_punch": "Show or hide the punch range",
    "markers_delete_by_location_id": "Delete a marker", "markers_delete_by_name": "Delete a marker",
    "markers_rename_by_location_id": "Rename a marker", "markers_rename_by_name": "Rename a marker",
    "tracks_add": "Add tracks", "buses_add": "Add buses",
    "region_set_gain_linear": "Change a region's gain", "region_set_gain_db": "Change a region's gain",
    "region_normalize": "Normalise a region", "region_split": "Split a region", "region_resize_samples": "Resize a region",
    "region_resize_bbt": "Resize a region", "region_copy_to_sample": "Copy a region", "region_copy_to_bbt": "Copy a region",
    "region_copy_by_samples": "Copy a region", "region_copy_by_beats": "Copy a region", "region_move_to_sample": "Move a region",
    "region_move_to_bbt": "Move a region", "region_move_by_samples": "Move a region", "region_move_by_beats": "Move a region",
    "region_set_fades": "Change a region's fades", "region_set_envelope": "Change a region's gain envelope",
    "region_set_warp": "Change a region's warp", "region_clear_warp": "Clear a region's warp",
    "region_mute": "Mute or unmute a region", "region_remove": "Remove a region from the timeline",
    "plugin_set_parameter_by_index_value": "Change a plug-in setting", "plugin_set_parameter_by_index_interface": "Change a plug-in setting",
    "plugin_set_parameter_by_control_value": "Change a plug-in setting", "plugin_set_parameter_by_control_interface": "Change a plug-in setting",
    "plugin_set_enabled": "Switch a plug-in on or off", "plugin_remove": "Remove a plug-in", "plugin_reorder": "Reorder plug-ins",
    "plugin_set_position": "Move a plug-in before or after the fader", "plugin_add_by_plugin_id": "Add a plug-in",
    "plugin_add_by_unique_id": "Add a plug-in",
    "track_select": "Select a track", "track_rename": "Rename a track", "track_set_mute": "Mute or unmute a track",
    "track_set_solo": "Solo or unsolo a track", "track_set_rec_enable": "Arm or disarm a track for recording",
    "track_set_rec_safe": "Switch record-safe on or off", "track_set_pan": "Change a track's pan",
    "track_set_send_level_position": "Change a send level", "track_set_send_level_db": "Change a send level",
    "track_add_send": "Add a send", "track_set_send_position": "Move a send before or after the fader",
    "track_remove_send": "Remove a send", "track_set_fader_position": "Change a fader", "track_set_fader_db": "Change a fader",
    "track_set_color": "Change a track's colour", "track_reorder": "Reorder tracks", "track_remove": "Remove a track",
    "midi_region_add_samples": "Add a MIDI region", "midi_region_add_bbt": "Add a MIDI region",
    "midi_note_add_region_beat": "Add a MIDI note", "midi_note_add_sample": "Add a MIDI note", "midi_note_add_bbt": "Add a MIDI note",
    "midi_note_edit": "Edit MIDI notes", "midi_note_import_json_into_region": "Import MIDI notes into a region",
    "midi_note_import_json_to_new_region_samples": "Import MIDI notes as a new region",
    "midi_note_import_json_to_new_region_bbt": "Import MIDI notes as a new region",
}


def title_of(tool):
    return TITLES.get(tool) or str(tool).replace("_", " ").capitalize()


# What the engine's own undo (daw_session_undo) can do for a call. Verified against the engine's source: only the edits
# it records as reversible commands are undo steps (region edits, markers and ranges, MIDI notes and regions). A fader,
# pan, mute, solo, send or plug-in change is NOT in that history: it is taken back by setting the old value again.
UNDO_STEP = frozenset("""
    region_set_gain_linear region_set_gain_db region_normalize region_split region_resize_samples region_resize_bbt
    region_copy_to_sample region_copy_to_bbt region_copy_by_samples region_copy_by_beats region_move_to_sample
    region_move_to_bbt region_move_by_samples region_move_by_beats region_set_fades region_set_envelope region_mute
    region_remove region_set_warp region_clear_warp transport_loop_location_samples transport_loop_location_bbt markers_add markers_add_range_samples markers_add_range_bbt markers_set_auto_loop_samples
    markers_set_auto_loop_bbt markers_hide_auto_loop markers_set_auto_punch_samples markers_set_auto_punch_bbt
    markers_hide_auto_punch markers_delete_by_location_id markers_delete_by_name markers_rename_by_location_id
    markers_rename_by_name midi_region_add_samples midi_region_add_bbt midi_note_add_region_beat midi_note_add_sample
    midi_note_add_bbt midi_note_edit midi_note_import_json_into_region midi_note_import_json_to_new_region_samples
    midi_note_import_json_to_new_region_bbt
""".split())
PLAYBACK = frozenset("""transport_play transport_stop transport_goto_start transport_goto_end transport_locate_sample
    transport_locate_bbt transport_prev_marker transport_next_marker transport_set_speed""".split())
# Said in their own words: these are not taken back by an undo step, or not by anything. (Verified against the engine's
# source: a plug-in or a send added or removed is not a reversible command, so Undo does not touch it; a warp is, it
# replaces the region in the playlist as one undo step.)
UNDO_NOTES = {
    "plugin_remove": ("none", "Not an engine undo step, and removing a plug-in loses its settings: adding it again starts "
                              "from its defaults. Save a snapshot first if you may want it back as it is."),
    "track_remove_send": ("none", "Not an engine undo step, and removing a send loses its level: adding it again starts "
                                  "from the defaults. Save a snapshot first if you may want it back as it is."),
    "plugin_add_by_plugin_id": ("none", "Not an engine undo step. To take it back, remove the plug-in with another card."),
    "plugin_add_by_unique_id": ("none", "Not an engine undo step. To take it back, remove the plug-in with another card."),
    "track_add_send": ("none", "Not an engine undo step. To take it back, remove the send with another card."),
    "track_remove": ("none", "This cannot be undone. Save a snapshot first if you may want the track back."),
    "track_reorder": ("none", "The engine cannot undo a change of track order."),
    "track_set_color": ("none", "Not in the engine's undo history; set the old colour again to take it back."),
    "session_save": ("none", "Writes the session file with what is open now; it is not an undo step."),
    "session_quick_snapshot": ("none", "Writes a new snapshot file next to the session; delete it to take it back."),
    "session_export_mix": ("none", "Writes a new audio file; delete the file to take it back. The session itself does not change."),
    "session_import_audio": ("none", "The regions it adds are one undo step, but new tracks stay: the engine does not undo track creation."),
    "tracks_add": ("none", "The engine does not undo track creation; a new track is removed with its own card."),
    "buses_add": ("none", "The engine does not undo track creation; a new bus is removed with its own card."),
    "session_undo": ("none", "Undoes the engine's own last step; Redo puts it back."),
    "session_redo": ("none", "Redoes the engine's own last undone step."),
    "session_store_mixer_scene": ("none", "Overwrites the stored scene; it is not an undo step."),
    "session_recall_mixer_scene": ("back", "Sets every fader and switch to the scene; not an undo step. Store a scene first to be able to come back."),
}
UNDO_TEXT = {
    "step": "One undo step in the engine: Undo takes it back.",
    "back": "Not an engine undo step: it is taken back by setting the old value again (the card shows it).",
    "play": "Playback only: nothing in the session's content changes.",
    "none": "Cannot be undone from here.",
}


def undo_info(tool):
    """-> (kind, words): 'step' (one engine undo step), 'back' (set the old value again), 'play' (playback only) or
    'none' (cannot be undone), and what the card says about it."""
    if tool in UNDO_NOTES:
        return UNDO_NOTES[tool]
    if tool in UNDO_STEP:
        return "step", UNDO_TEXT["step"]
    if tool in PLAYBACK:
        return "play", UNDO_TEXT["play"]
    return "back", UNDO_TEXT["back"]


def _steps(a):
    n = a.get("count") if isinstance(a.get("count"), int) and not isinstance(a.get("count"), bool) else 1
    return "the last step" if n == 1 else f"the last {n} steps"


def _own_summary(tool, a):
    """A summary sentence for the calls whose before -> after rows do not read as one, or ''."""
    if tool == "session_save":
        snap = str(a.get("snapshotName") or "").strip()
        if not snap:
            return "Saves the open session to its file, as it is now."
        return (f"Saves the open session as a new snapshot called {snap!r}" +
                (" and switches to it." if a.get("switchToSnapshot") is True else "; the session stays on its own file."))
    if tool == "session_undo":
        return f"Undoes {_steps(a)} in the session."
    if tool == "session_redo":
        return f"Puts back {_steps(a)} that {'was' if _steps(a) == 'the last step' else 'were'} undone in the session."
    if tool == "markers_add":
        where = (f"bar {a['bar']}" + (f" beat {a['beat']:g}" if isinstance(a.get("beat"), (int, float)) else "")) \
            if a.get("bar") is not None else "the playhead"
        return f"Adds a marker{' called ' + repr(str(a['name'])) if a.get('name') else ''} at {where}."
    return ""


def describe(tool, args, rows, where=None):
    """-> (title, summary): the card in plain words. rows are the before -> after rows read from the engine; where is a
    function (kind, id) -> a name for a track or region (or None). Without rows the summary says what is touched and
    with which values."""
    title = title_of(tool)
    a = args or {}
    own = _own_summary(tool, a)
    if own:
        return title, own[:600]
    if rows:
        return title, " ".join((f"{r['what']}: {r['after']}." if r.get("before") in ("-", "", None)
                                else f"{r['what']}: from {r['before']} to {r['after']}.") for r in rows)[:600]
    bits = []
    for k, v in a.items():
        if v in (None, "", [], {}):
            continue
        if k in ID_KEYS + ("track_id", "trackId"):
            nm = where("track", str(v)) if where else None
            bits.append(f"on {nm}" if nm else f"on route {v}")
        elif k in ("regionId", "region_id"):
            nm = where("region", str(v)) if where else None
            bits.append(f"region {nm}" if nm else f"region {v}")
        elif k == "confirm":
            continue
        else:
            sv = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v)
            bits.append(f"{k} {sv[:80]}")
    return title, (title + (": " + ", ".join(bits) if bits else " (no settings)") + ".")[:600]


def digest(tool, args):
    """A short fingerprint of exactly one call (the tool and its arguments). The card carries it, the answer must bring
    it back, and the call is checked against it again just before it is sent."""
    import hashlib
    body = json.dumps({"tool": tool, "arguments": args}, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


# The mixer settings Hear it may set (and put back): plain setters whose value the page knows.
PREVIEW_UNDO_TOOLS = ("track_set_fader_db", "track_set_fader_position", "track_set_pan", "track_set_mute", "track_set_solo",
                      "track_set_send_level_db", "track_set_send_level_position", "plugin_set_enabled",
                      "plugin_set_parameter_by_index_value", "plugin_set_parameter_by_index_interface")
PREVIEW_TOOLS = frozenset(PREVIEW_UNDO_TOOLS)


def export_problem(args):
    """Why a bounce to args['path'] must not be proposed, or ''. The engine replaces a file that is already there; the
    person's own files (a stem, a mix) are never to be overwritten by a card, so the model picks a new name."""
    p = str((args or {}).get("path") or "")
    if not p or not os.path.isabs(p):
        return "path must be an absolute file path ending in .wav"
    if any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in p):      # a NUL or a line break: the engine's C strings would cut the name there
        return "path has a control or invisible character in it: use a plain file name"
    if not p.lower().endswith(".wav"):
        return "path must end in .wav"
    folder = os.path.dirname(p)
    if not os.path.isdir(folder):
        return f"the folder {os.path.basename(folder) or p!r} does not exist (the engine does not make it)"
    # the engine writes <folder>/<the name without its suffix>.wav, in lower case: that file is the one it would replace
    name = os.path.basename(p)[:-4] + ".wav"
    try:
        same = {x.lower() for x in os.listdir(folder)}
    except OSError:
        same = set()
    if os.path.lexists(p) or os.path.lexists(os.path.join(folder, name)) or name.lower() in same or os.path.basename(p).lower() in same:
        return (f"a file called {os.path.basename(p)} is already there and the export would replace it. Choose a new "
                "file name (for example add -2 or the date) and propose that")
    return ""


# ---------------------------------------------------------------- what the model needs of the tool list, and no more
# Every step of a conversation carries the tool definitions: all 111 of the engine's cost about 16,000 tokens each time.
# A request carries the CORE (the reads and the mixing moves of most requests), plus the groups the DAW view needs;
# daw_more_tools {group} asks for another group (it stays for the conversation), so nothing is out of reach.
CORE = frozenset("""
    session_get_info tracks_list track_get_info track_get_regions markers_list transport_get_state plugin_list_available
    plugin_get_description meters_get region_get_info export_status session_save session_undo session_redo
    track_set_fader_db track_set_pan track_set_mute track_set_solo track_set_send_level_db plugin_add_by_plugin_id
    plugin_set_enabled plugin_set_parameter_by_index_value plugin_remove
""".split())
GROUPS = ("regions", "markers", "transport", "plugins", "tracks", "session", "midi", "other")
GROUP_ABOUT = {
    "regions": "regions on the timeline: gain, move, copy, split, resize, fades, envelope, warp, peaks, remove",
    "markers": "markers and the loop / punch ranges",
    "transport": "play, stop, move the playhead, loop and speed",
    "plugins": "the rest of the plug-in tools: other ways to set a parameter, reorder, place, add by unique id",
    "tracks": "add, rename, select, arm, colour, reorder or remove tracks and buses, sends, fader by position, import audio",
    "session": "rename, snapshots, mixer scenes, bounce the mix to a file",
    "midi": "MIDI regions and notes",
    "other": "any tool the engine has that the groups above do not cover",
}
VIEW_GROUPS = {"mixer": ("plugins",), "arrange": ("regions",), "session": (), "review": ()}
SESSION_EXTRA = ("session_rename", "session_quick_snapshot", "session_store_mixer_scene", "session_recall_mixer_scene",
                 "session_export_mix", "hello_world")


def group_of(tool):
    """The group an engine tool belongs to ('core' for the always-offered ones)."""
    t = str(tool)
    if t in CORE:
        return "core"
    for pre, g in (("region_", "regions"), ("markers_", "markers"), ("transport_", "transport"), ("plugin_", "plugins"),
                   ("midi_", "midi"), ("track_", "tracks"), ("tracks_", "tracks"), ("buses_", "tracks")):
        if t.startswith(pre):
            return g
    if t == "session_import_audio":
        return "tracks"
    if t in SESSION_EXTRA or t.startswith(("session_", "meters_", "export_")):
        return "session"
    return "other"


def offered(names, view=None, enabled=()):
    """The engine tools (by engine name) one request carries: the core, the groups the view needs and the groups the
    conversation asked for. A tool the core or a group does not cover (a new one from the engine) is in 'other'."""
    want = set(VIEW_GROUPS.get(str(view or ""), ())) | set(enabled or ())
    return [n for n in names if group_of(n) == "core" or group_of(n) in want]


def short_text(text, limit=200):
    """text cut at the end of a sentence that fits in limit characters (or at limit, with an ellipsis)."""
    t = " ".join(str(text or "").split())
    if len(t) <= limit:
        return t
    cut = t[:limit]
    i = max(cut.rfind(". "), cut.rfind("! "))
    return cut[:i + 1] if i > limit // 3 else cut.rstrip(" ,;:") + "…"


def known_tool(name):
    """Is this one of the engine's own tools (the ones this app has a plain title or a read-only entry for)?"""
    return name in READ_ONLY or name in TITLES


_SAFE_KEY = re.compile(r"^[A-Za-z0-9_]{1,40}$")
_LIMITS = ("minimum", "maximum")


def attached_schema(s):
    """The input schema of a tool from a window this app did not start, rebuilt from property names, types and numeric
    limits only: no description, enum, default, title or example is copied, so nothing a stranger wrote in it reaches the
    model (the app's own hints are added afterwards). A property whose name is not a plain identifier is left out."""
    s = s if isinstance(s, dict) else {}
    props = {}
    for k, p in (s.get("properties") if isinstance(s.get("properties"), dict) else {}).items():
        if not isinstance(k, str) or not _SAFE_KEY.match(k) or not isinstance(p, dict):
            continue
        q = {"type": p["type"]} if p.get("type") in _TYPES else {}
        for lim in _LIMITS:
            if isinstance(p.get(lim), (int, float)) and not isinstance(p.get(lim), bool) and math.isfinite(p[lim]):
                q[lim] = p[lim]
        it = p.get("items")
        if q.get("type") == "array" and isinstance(it, dict) and it.get("type") in _TYPES:
            q["items"] = {"type": it["type"]}
        props[k] = q
    out = {"type": "object", "properties": props}
    req = [k for k in (s.get("required") if isinstance(s.get("required"), list) else []) if isinstance(k, str) and k in props]
    if req:
        out["required"] = req
    return out


def slim_schema(s, field=110):
    """A tool's input schema without the long prose: every field keeps its name, type, limits and a short description."""
    out = json.loads(json.dumps(s))
    for p in (out.get("properties") or {}).values():
        if isinstance(p, dict):
            if isinstance(p.get("description"), str):
                p["description"] = short_text(p["description"], field)
            p.pop("title", None)
    out.pop("additionalProperties", None)
    return out


# ---------------------------------------------------------------- what goes to the model: names, never the home folder
_HOME_RE = re.compile(r"(?:/Users|/home)/[^/\s\"'<>\\]+|[A-Za-z]:\\\\?Users\\\\?[^\\\s\"'<>]+")


def _homes():
    out = set()
    for h in (os.path.expanduser("~"), os.environ.get("HYPNOMIX_USER_HOME", "")):
        h = str(h or "").rstrip("/\\")
        if len(h) > 3:
            out.add(h)
    return sorted(out, key=len, reverse=True)


def home_short(text):
    """text with the home folder (and any /Users/<name>) shortened to ~: a folder name carries the person's login."""
    if not isinstance(text, str):
        return text
    for h in _homes():
        text = text.replace(h, "~")
    return _HOME_RE.sub("~", text)


PATH_KEYS = frozenset({"path", "folder", "file", "dir", "directory", "sessionPath", "sessionFolder", "filePath", "sourcePath",
                       "originalPath", "snapshotPath"})


def _names_only(o):
    """Every value under a key that holds a path becomes the file's own name (a snapshot list, a warp map's sources)."""
    if isinstance(o, list):
        return [_names_only(x) for x in o]
    if isinstance(o, dict):
        return {k: (os.path.basename(str(v).rstrip("/\\")) or str(v) if k in PATH_KEYS and isinstance(v, str) and ("/" in v or "\\" in v)
                    else _names_only(v)) for k, v in o.items()}
    return o


# ---------------------------------------------------------------- replies made small for the model
MAX_LIST = 60
MAX_CHARS = 8000


def _peaks_summary(sc):
    """region_get_peaks: per channel the loudest peak and a coarse envelope (max |peak| per bucket, dBFS)."""
    out = {k: v for k, v in sc.items() if k != "channels"}
    chans = []
    for ch in sc.get("channels") or []:
        pk = ch.get("peaks") or []
        amp = [max(abs(float(a or 0)), abs(float(b or 0))) for a, b in (p if isinstance(p, (list, tuple)) and len(p) == 2 else (0, 0) for p in pk)]
        top = max(amp) if amp else 0.0
        n = 48
        env = []
        if amp:
            step = max(1, math.ceil(len(amp) / n))
            env = [max(amp[i:i + step]) for i in range(0, len(amp), step)]
        to_db = lambda x: round(20 * math.log10(x), 1) if x > 0 else None
        chans.append(dict(channel=ch.get("channel"), pairs=len(pk), peakDbfs=to_db(top),
                          envelopeDbfs=[to_db(x) for x in env]))
    out["channels"] = chans
    out["note"] = ("summarised for you: each channel's loudest peak and a coarse envelope (max |peak| per "
                   "bucket, dBFS, null = silence); the full pairs are for drawing")
    return out


def _cut(o, depth=0):
    if isinstance(o, list):
        items = [_cut(x, depth + 1) for x in o[:MAX_LIST]]
        if len(o) > MAX_LIST:
            items.append(f"... {len(o) - MAX_LIST} more not shown (narrow the request)")
        return items
    if isinstance(o, dict):
        return {k: _cut(v, depth + 1) for k, v in o.items()}
    if isinstance(o, float):
        return round(o, 4)
    return o


PLUGIN_KEEP = ("pluginId", "name", "typeLabel", "creator", "isInstrument")
REGION_KEEP = ("regionId", "name", "type", "startSample", "lengthSamples", "muted", "locked")
PARAM_KEEP = ("index", "controlId", "label", "lower", "upper", "currentValue", "isOutput")


def trim(tool, sc):
    """A structured reply -> compact JSON text for the model."""
    if not isinstance(sc, (dict, list)):
        return home_short(str(sc))[:MAX_CHARS]
    sc = _names_only(sc)
    if tool == "region_get_peaks" and isinstance(sc, dict):
        sc = _peaks_summary(sc)
    elif tool == "plugin_list_available" and isinstance(sc, dict):
        sc = dict(sc, plugins=[{k: p.get(k) for k in PLUGIN_KEEP if k in p} for p in sc.get("plugins") or []])
    elif tool == "plugin_get_description" and isinstance(sc, dict):
        sc = dict(sc, parameters=[{k: p.get(k) for k in PARAM_KEEP if k in p} for p in sc.get("parameters") or []
                                  if not p.get("isHidden")])
    elif tool == "track_get_regions" and isinstance(sc, dict):
        sc = dict(sc, regions=[{k: r.get(k) for k in REGION_KEEP if k in r} for r in sc.get("regions") or []])
    elif tool == "meters_get" and isinstance(sc, dict):
        sc = dict(sc, routes=[{k: r.get(k) for k in ("id", "name", "peakDb", "maxPeakDb", "rmsDb")} for r in sc.get("routes") or []])
    text = home_short(json.dumps(_cut(sc), default=str, separators=(",", ":")))
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + f' ... (cut: the reply was {len(text)} characters; ask for less, e.g. one track or a sub-range)'
    return text


# ---------------------------------------------------------------- errors in plain words
def plain(msg, tool="", args=None):
    m = str(msg or "the tool failed").strip()
    low = m.lower()
    a = args or {}
    if "route not found" in low:
        rid = a.get("id") or a.get("track_id") or a.get("trackId")
        return (f"no track or bus with id {rid!r} in this session. Use the ids from daw_session_overview "
                "(they are decimal strings like \"252\", not names).")
    if "region" in low and "not found" in low:
        return "no such region in this session: read the track's regions again (daw_track_get_regions) for current ids."
    if "plugin" in low and ("not found" in low or "out of range" in low or "invalid" in low):
        return f"{m}. Read the track's plug-ins again (daw_track_get_info) for their current indexes."
    if "timed out" in low or "unreachable" in low:
        return ("the engine did not answer in time. If this was a change, it may or may not have happened: read it "
                "back before trying again.")
    if "not json" in low:
        return ("the engine's reply came back broken (not valid JSON), so there is nothing to read from it. "
                + ("For peaks, ask for fewer (e.g. width_px 200) or one channel. " if tool == "region_get_peaks" else "")
                + "If this was a change, read it back before trying again.")
    if "export is running" in low or "export is already running" in low or "-32003" in low:
        return ("an export (a bounce of the mix) is running in the engine: until it finishes the engine refuses the "
                "transport (play, stop, locate, loop, record) and a second export, so the bounce cannot be cut short. "
                "Nothing changed. Check daw_export_status, then try again when it is done.")
    if "still being built" in low or "-32002" in low:
        return ("the engine is still building this file's waveform data (just after an import, or a session that had "
                "none): try again in a few seconds.")
    if "not running" in low:
        return "the engine is not running right now (it may be restarting). Try again in a moment."
    return m
