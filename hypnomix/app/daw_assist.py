"""The Assistant on the HypnoMix Studio engine: which engine tools may run without asking, the arguments models get
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
    "export_status", "region_get_warp", "playlist_list", "take_list", "plugin_get_sidechain", "group_list",
    "session_get_card", "cue_list", "ab_list",
    # MIDI inputs and MPE (only an engine that lists them has them): the port list, a track's MPE setting and the
    # per-note input monitor. The monitor's first read attaches a tap to the track's MIDI input port: nothing in the
    # session, and nothing that is heard, changes (its `reset` only clears the monitor's own counts).
    "midi_ports_list", "midi_monitor_get", "track_get_mpe",
    # automation and the tempo map (only an engine that lists them has them): a route's automatable controls and the
    # facts about what it carries, one control's points, and the tempo map. None of them has an argument that writes.
    "automation_list", "automation_get", "tempo_get_map",
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
                p["description"] = "0.0 = right, 0.5 = centre, 1.0 = left (the engine's convention)"
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
        ty = p.get("type")
        if isinstance(ty, list):                         # ["string", "null"]: any of them, and null clears the field
            if v is None or any(isinstance(v, _TYPES[x]) and not (isinstance(v, bool) and bool not in _TYPES[x])
                                for x in ty if isinstance(x, str) and x in _TYPES):
                continue
            return f"{k} must be a {' or '.join(str(x) for x in ty)}, not {json.dumps(v)[:40]}"
        want = _TYPES.get(ty) if isinstance(ty, str) else None
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
        elif tool == "comp_range":
            sr = (read("session_get_info", {}) or {}).get("sampleRate") or 48000
            t0 = a["start_sample"] / sr if isinstance(a.get("start_sample"), (int, float)) else a.get("start")
            t1 = a["end_sample"] / sr if isinstance(a.get("end_sample"), (int, float)) else a.get("end")
            src = f"take {a['take']}" if a.get("take") is not None else f"take playlist {a.get('take_playlist_id')}"
            rows.append(dict(what=f"{name()} · comp {_num(t0)}–{_num(t1)} s", before="what the comp plays there now",
                             after=f"{src}, {_num(a.get('xfade_ms', 10))} ms crossfades (one undo step)"))
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
    elif tool == "track_set_mpe":
        m = read("track_get_mpe", {"track_id": str(a.get("track_id"))}) or {}
        rows.append(dict(what=f"{m.get('name') or name()} · MPE", before=_mpe_words(m.get("zone"), m.get("members")) if m else "?",
                         after=_mpe_words(a.get("zone"), a.get("members"))))
    elif tool == "midi_port_set_flags":
        port = str(a.get("port") or "")
        p = next((x for x in (read("midi_ports_list", {"direction": "all"}) or {}).get("ports") or []
                  if port in (x.get("name"), x.get("prettyName"))), {})
        now = p.get("flags") or {}
        keys = [k for k in ("music", "control", "selection", "mpe") if isinstance(a.get(k), bool)]
        flags = lambda f: ", ".join(f"{k} {'on' if f.get(k) else 'off'}" for k in keys) or "as they are"
        rows.append(dict(what=f"MIDI port {p.get('prettyName') or port}", before=flags(now) if p else "?",
                         after=flags({k: a[k] for k in keys})))
    elif tool == "midi_track_connect_input":
        rows.append(dict(what=f"{name()} · MIDI input", before="as it is" if not a.get("exclusive") else "its connections now",
                         after=("only " if a.get("exclusive") else "also ") + f"from {a.get('port')}"))
    elif tool == "midi_track_disconnect_input":
        rows.append(dict(what=f"{name()} · MIDI input", before="as it is",
                         after=f"no longer from {a['port']}" if a.get("port") else "connected to nothing"))
    elif tool in ("automation_write", "automation_clear", "automation_set_state"):
        rows.extend(_auto_rows(tool, a, read))
    elif tool in ("tempo_set_points", "tempo_set_meter"):
        rows.extend(_tempo_rows(tool, a, read))
    return rows


def _secs(t):
    return "?" if not isinstance(t, (int, float)) or isinstance(t, bool) else f"{t:.1f} s"


def _auto_rows(tool, a, read):
    """A card's rows for an automation call: the control on its route, the points there now and after."""
    from hypnomix.engineer import automation_rules as AR
    rid, ctl = str(a.get("track_id") or ""), str(a.get("control") or "")
    facts = read("automation_list", {"track_id": rid}) or {}
    c = next((x for x in facts.get("controls") or [] if x.get("control") == ctl), {})
    what = f"{facts.get('trackName') or 'route ' + rid} · {c.get('name') or ctl} automation"
    if tool == "automation_set_state":
        return [dict(what=what, before=str(c.get("state") or "?"), after=str(a.get("state")))]
    a = AR.normal(a)                                   # replace_all and s-curve as the engine reads them
    every = tool == "automation_write" and a.get("mode") == "replace-all"
    rng = {} if every else {k: a[k] for k in ("start", "end") if isinstance(a.get(k), (int, float)) and not isinstance(a.get(k), bool)}
    now = read("automation_get", dict(track_id=rid, control=ctl, **rng)) or {}
    have = now.get("pointList") or []
    before = (f"{len(have)} point{'s' if len(have) != 1 else ''}" + (f", {_secs(have[0].get('time'))} to {_secs(have[-1].get('time'))}" if have else "")
              + f", {now.get('state') or c.get('state') or '?'}") if now else "?"
    if tool == "automation_clear":
        return [dict(what=what, before=before, after="no points" + (f" from {_secs(rng.get('start'))} to {_secs(rng.get('end'))}" if rng else ""))]
    pts = AR.points_of(a.get("points"))
    unit = " dB" if AR.kind(ctl) in AR.LEVEL_KINDS else ""
    moves = AR.moves(pts)
    words = (f"{len(pts)} point{'s' if len(pts) != 1 else ''} from {_secs(pts[0][0])} to {_secs(pts[-1][0])}" if pts else "no points")
    if moves and unit:
        big = max(abs(d) for _, _, d in moves)
        words += f", largest move {big:.1f} dB, steepest {AR.steepest(pts, a.get('curve')):.1f} dB/s"
    words += f", {a.get('curve') or 'linear'}" + (f", {a['state']}" if a.get("state") else ", play")
    if every:
        words += "; every other point on the lane is removed (replace-all)"
    return [dict(what=what, before=before, after=words)]


def _tempo_rows(tool, a, read):
    """A card's rows for a tempo map call: the map now (its points, ramps shown as from -> to) and after."""
    m = read("tempo_get_map", {}) or {}
    def bpm(p, end=None):
        b, e = p.get("bpm"), p.get("bpmEnd" if end is None else end)
        if not isinstance(b, (int, float)):
            return "?"
        return f"{b:g}" + (f"->{e:g}" if isinstance(e, (int, float)) and abs(e - b) > 1e-6 else "")
    if tool == "tempo_set_meter":
        now = ", ".join(f"bar {x.get('bbt', {}).get('bar', '?')}: {x.get('divisionsPerBar')}/{x.get('noteValue')}" for x in m.get("meters") or []) or "?"
        after = (f"no meter change at bar {a.get('bar')}" if a.get("remove") else
                 f"{a.get('divisions_per_bar')}/{a.get('note_value') or 4} from bar {a.get('bar')}")
        return [dict(what="time signature", before=now, after=after)]
    now = ", ".join(f"bar {x.get('bbt', {}).get('bar', '?')}: {bpm(x)} BPM" for x in (m.get("tempos") or [])[:8]) or "?"
    pts = [x for x in a.get("points") or [] if isinstance(x, dict)]
    where = lambda x: (f"bar {x['bar']}" + (f" beat {x['beat']}" if x.get("beat") else "")) if x.get("bar") else f"{_secs(x.get('time'))}"
    after = ", ".join(f"{where(x)}: {bpm(x, 'bpm_end')} BPM" for x in pts[:8]) + (f" and {len(pts) - 8} more" if len(pts) > 8 else "")
    mode = " (the whole map)" if a.get("mode") == "replace-all" else ""
    return [dict(what="tempo map" + mode, before=now, after=after or "no points")]


def _mpe_words(zone, members):
    """A track's MPE mode in words: 'off', or the zone and how many member channels."""
    if zone in (None, "", "off"):
        return "off"
    return f"{zone} zone" + (f", {members} member channels" if isinstance(members, int) and not isinstance(members, bool) else "")


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
    "playlist_new": "Make a new take", "playlist_select": "Choose which take a track plays",
    "comp_range": "Comp a stretch from a take",
    "plugin_set_sidechain": "Key a plug-in from another track",
    "group_create": "Make a group track", "group_add": "Add tracks to a group", "group_remove": "Take tracks out of a group",
    "group_delete": "Ungroup", "group_set": "Change a group",
    "track_bounce": "Bounce one track to a new audio file", "session_set_card": "Change the song card",
    "meters_stream_info": "Open the meter stream",
    "cue_set_clip": "Put a clip into a cue slot", "cue_set_props": "Change a cue slot's settings",
    "cue_launch": "Launch a clip", "cue_stop": "Stop clips", "scene_launch": "Launch a scene",
    "ab_use_playlist": "Switch which playlist a track plays",
    "midi_port_set_flags": "Mark a MIDI port", "midi_track_connect_input": "Connect a track's MIDI input",
    "midi_track_disconnect_input": "Disconnect a track's MIDI input", "midi_monitor_stop": "Stop the MIDI input monitor",
    "track_set_mpe": "Set MPE on a track",
    "automation_write": "Write automation", "automation_clear": "Clear automation",
    "automation_set_state": "Switch automation playback on or off",
    "tempo_set_points": "Change the tempo map", "tempo_set_meter": "Change the time signature",
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
    midi_note_import_json_to_new_region_bbt comp_range track_set_mpe
    automation_write automation_clear tempo_set_points tempo_set_meter
""".split())
PLAYBACK = frozenset("""transport_play transport_stop transport_goto_start transport_goto_end transport_locate_sample
    transport_locate_bbt transport_prev_marker transport_next_marker transport_set_speed cue_launch cue_stop
    scene_launch""".split())
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
    "playlist_new": ("none", "Not an engine undo step: the new take stays with the track (it is not heard unless chosen)."),
    "playlist_select": ("back", "Not an engine undo step: choose the comp again to take it back."),
    "plugin_set_sidechain": ("back", "Not an engine undo step: choose the old source again (or none) to take it back."),
    "group_create": ("none", "Not an engine undo step: Ungroup (another card) puts the tracks back on the master."),
    "group_add": ("none", "Not an engine undo step: take the tracks out of the group again with another card."),
    "group_remove": ("none", "Not an engine undo step: add the tracks to the group again with another card; taking the last ones out removes the group bus."),
    "group_delete": ("none", "Cannot be undone from here: the group bus is removed (with any plug-ins on it); make the group again to get it back."),
    "group_set": ("back", "Not an engine undo step: set the old values again to take it back."),
    "track_bounce": ("none", "Writes a new audio file; delete the file to take it back. The session itself does not change."),
    "session_set_card": ("back", "Not an engine undo step: set the old values again (the card is kept in the session file when it is saved)."),
    "meters_stream_info": ("none", "The app's own: never offered."),
    "cue_set_clip": ("none", "Not an engine undo step: clear the slot with another card. While any slot of a track holds a "
                             "clip (launched or not), that track's Arrangement regions do not play; clearing its "
                             "last clip brings them back at once."),
    "cue_set_props": ("back", "Not an engine undo step: set the old values again to take it back."),
    "ab_use_playlist": ("back", "Not an engine undo step: switch back to the playlist it played before."),
    "session_recall_mixer_scene": ("back", "Sets every fader and switch to the scene; not an undo step. Store a scene first to be able to come back."),
    # MIDI inputs (the engine's own words: port flags and connections are not undo steps; its reply lists what was before)
    "midi_port_set_flags": ("back", "Not an engine undo step, and not kept in the session: the flags are saved at once in "
                                    "this computer's MIDI port settings. To put them back, set the old flags again with "
                                    "another card (the card shows them; the engine's reply lists them too)."),
    "midi_track_connect_input": ("back", "Not an engine undo step (connections never are). To put it back, disconnect "
                                         "this port with another card, or connect the ports it had before again (the "
                                         "engine's reply lists them). Kept in the session when it is saved."),
    "midi_track_disconnect_input": ("back", "Not an engine undo step (connections never are). To put it back, connect "
                                            "the port again with another card (the engine's reply lists what was connected)."),
    "midi_monitor_stop": ("back", "Changes nothing in the session or in what is heard: it only stops watching the "
                                  "track's MIDI input. Reading the monitor again starts it again."),
    # automation and the tempo map (the engine's own words: a write or a clear, with its state, is one undo step; a state
    # change alone is not, as in the editor; a tempo or meter change is one undo step and audio keeps its time)
    "automation_write": ("step", "One undo step in the engine: Undo takes back the points and the playback state together."),
    "automation_clear": ("step", "One undo step in the engine: Undo puts the points back. The playback state stays as it is."),
    "automation_set_state": ("back", "Not an engine undo step (as in the editor): set the old state again with another "
                                     "card (the engine's reply says what it was)."),
    "tempo_set_points": ("step", "One undo step in the engine: Undo puts the old tempo map back. Audio regions keep "
                                 "their time; MIDI follows the bars."),
    "tempo_set_meter": ("step", "One undo step in the engine: Undo puts the old time signature back."),
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


def automation_clear_problem(args, read):
    """Why an automation_clear must not be proposed (a ranged clear inside a level lane that would leave a straight
    move, a range of one edge only, or a start or end that is not a number), or ''."""
    from hypnomix.engineer import automation_rules as AR
    a = args or {}
    if AR.kind(a.get("control")) not in AR.LEVEL_KINDS or (a.get("start") is None and a.get("end") is None):
        return ""
    problems = AR.check_clear(a, read("automation_get", {"track_id": str(a.get("track_id") or ""), "control": str(a.get("control") or "")}))
    return AR.sentence(problems) if problems else ""


def _auto_context(a, read):
    """(facts, lane, original line, why) for an automation call on a level or plug-in control, read through
    read(tool, args); why is '' when everything needed could be read (a route or lane that cannot be read: why is the
    whole answer; an original line that cannot be known: the rules are judged first, then why)."""
    from hypnomix.engineer import automation_original as AO
    from hypnomix.engineer import automation_rules as AR
    a = AR.normal(a)                                   # fader is gain, route 02 is route 2, as the engine reads them
    rid, ctl = str(a.get("track_id") or ""), str(a.get("control") or "")
    facts = read("automation_list", {"track_id": rid})
    if facts is None:
        return None, None, None, f"route {rid}: what it carries could not be read (automation_list); read it first"
    lane = read("automation_get", {"track_id": rid, "control": ctl})
    if lane is None:
        return facts, None, None, f"route {rid}'s {ctl} lane could not be read (automation_get); read it first"
    if AR.kind(ctl) not in AR.LEVEL_KINDS:
        return facts, lane, None, ""
    line, _, why = AO.pick(AO.folder_of(read("session_list_snapshots", {})), rid, ctl, lane, AR.current_of(facts, ctl))
    return facts, lane, line, why


def automation_problem(args, read):
    """Why an automation_write must not be proposed (hypnomix's smooth-automation rules, read against the route's facts
    and, for a level control, the lane as it is now and its original line, through read(tool, args)), or ''. A plug-in
    parameter is held to the mixed-bus rule (and the no-recording-state rule) only. The app checks the same again as
    it is sent."""
    from hypnomix.engineer import automation_rules as AR
    a = args or {}
    if not AR.checked(a.get("control")):
        return ""
    facts, lane, line, why = _auto_context(a, read)
    if lane is None:
        return why
    problems = AR.judge(a, facts, lane, read, line) or ([why] if why else [])
    return AR.sentence(problems) if problems else ""


def automation_state_problem(args, read):
    """Why an automation_set_state must not be proposed: a recording state (write, touch, latch) on a level or plug-in
    lane, or a switch to play that would make a lane's points heard against the rules (automation_rules.judge_state),
    or ''. The app checks the same again as it is sent."""
    from hypnomix.engineer import automation_rules as AR
    a = args or {}
    if not AR.checked(a.get("control")):
        return ""
    if AR.recording(a.get("state"), AR.kind(a.get("control"))):
        return AR.sentence(AR.judge_state(a))
    if a.get("state") != "play":
        return ""
    facts, lane, line, why = _auto_context(a, read)
    if lane is None:
        return why
    problems = AR.judge_state(a, facts, lane, read, line) or ([why] if why and AR.starts_playing(a, facts, lane) else [])
    return AR.sentence(problems) if problems else ""


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
# Every step of a conversation carries the tool definitions: all of the engine's (more than 100) cost about 16,000 tokens or more each time.
# A request carries the CORE (the reads and the mixing moves of most requests), plus the groups the DAW view needs;
# daw_more_tools {group} asks for another group (it stays for the conversation), so nothing is out of reach.
CORE = frozenset("""
    session_get_info tracks_list track_get_info track_get_regions markers_list transport_get_state plugin_list_available
    plugin_get_description meters_get region_get_info export_status session_save session_undo session_redo
    track_set_fader_db track_set_pan track_set_mute track_set_solo track_set_send_level_db plugin_add_by_plugin_id
    plugin_set_enabled plugin_set_parameter_by_index_value plugin_remove
""".split())
GROUPS = ("regions", "markers", "transport", "plugins", "tracks", "session", "midi", "cues", "mpe", "automation", "tempo",
          "other")
GROUP_ABOUT = {
    "regions": "regions on the timeline: gain, move, copy, split, resize, fades, envelope, warp, peaks, remove",
    "markers": "markers and the loop / punch ranges",
    "transport": "play, stop, move the playhead, loop and speed",
    "plugins": "the rest of the plug-in tools: other ways to set a parameter, reorder, place, add by unique id",
    "tracks": "add, rename, select, arm, colour, reorder or remove tracks and buses, sends, fader by position, import audio, takes and comping, group tracks",
    "session": "rename, snapshots, mixer scenes, bounce the mix to a file",
    "midi": "MIDI regions and notes",
    "cues": "the Session view's clip slots: list, fill, launch, stop, scenes",
    "mpe": "MIDI inputs and MPE: the controller ports and their flags, a track's MIDI input, the per-note input monitor, a track's MPE mode",
    "automation": "automation lanes: a route's controls and what it carries, read and write points (level moves as gentle S-curves), clear, playback state",
    "tempo": "the tempo map: read it, set tempo points and ramps, time signatures",
    "other": "any tool the engine has that the groups above do not cover",
}
VIEW_GROUPS = {"mixer": ("plugins",), "arrange": ("regions",), "session": ("cues",), "review": ()}
SESSION_EXTRA = ("session_rename", "session_quick_snapshot", "session_store_mixer_scene", "session_recall_mixer_scene",
                 "session_export_mix", "hello_world")


# The MIDI input and MPE tools: their own group, offered only when the engine lists at least one of them (an engine
# built without them shows no such group, so nothing about it reaches the model).
MPE_TOOLS = frozenset("""
    midi_ports_list midi_port_set_flags midi_track_connect_input midi_track_disconnect_input midi_monitor_get
    midi_monitor_stop track_get_mpe track_set_mpe
""".split())
# Automation and the tempo map: the same, each its own group, never in the core (asked for when a request needs them).
AUTOMATION_TOOLS = frozenset("automation_list automation_get automation_write automation_clear automation_set_state".split())
TEMPO_TOOLS = frozenset("tempo_get_map tempo_set_points tempo_set_meter".split())
OPTIONAL_GROUPS = {"mpe": MPE_TOOLS, "automation": AUTOMATION_TOOLS, "tempo": TEMPO_TOOLS}


def groups_for(names):
    """The groups daw_more_tools may offer for an engine that lists these tools: every group, less an optional one
    (mpe, automation, tempo) the engine has none of."""
    have = {str(n) for n in names or ()}
    return tuple(g for g in GROUPS if g not in OPTIONAL_GROUPS or have & OPTIONAL_GROUPS[g])


def group_of(tool):
    """The group an engine tool belongs to ('core' for the always-offered ones)."""
    t = str(tool)
    if t in CORE:
        return "core"
    if t in MPE_TOOLS:
        return "mpe"
    if t in AUTOMATION_TOOLS or t.startswith("automation_"):
        return "automation"
    if t in TEMPO_TOOLS or t.startswith("tempo_"):
        return "tempo"
    for pre, g in (("region_", "regions"), ("markers_", "markers"), ("transport_", "transport"), ("plugin_", "plugins"),
                   ("midi_", "midi"), ("track_", "tracks"), ("tracks_", "tracks"), ("buses_", "tracks"),
                   ("playlist_", "tracks"), ("take_", "tracks"), ("comp_", "tracks"), ("group_", "tracks"),
                   ("ab_", "tracks"), ("cue_", "cues"), ("scene_", "cues")):
        if t.startswith(pre):
            return g
    if t == "session_import_audio":
        return "tracks"
    if t in SESSION_EXTRA or t.startswith(("session_", "meters_", "export_")):
        return "session"
    return "other"


# A provider takes at most 128 tools in one request (the app's own come on top of these). With every group on, the engine
# has more than that. Past the limit, first the other forms of a tool (another unit, another way to address the same
# thing) are left out, in this order; the form kept does the same job. If that is not enough, whole groups are put away
# (offered(): the one asked for longest ago first), never a few tools of a group at random.
MAX_OFFERED = 112
SECOND_FORMS = """
    plugin_set_parameter_by_index_interface plugin_set_parameter_by_control_value plugin_set_parameter_by_control_interface
    region_set_gain_linear track_set_fader_position track_set_send_level_position plugin_add_by_unique_id hello_world
    markers_delete_by_location_id markers_rename_by_location_id
    transport_locate_bbt transport_loop_location_bbt markers_add_range_bbt markers_set_auto_loop_bbt
    markers_set_auto_punch_bbt region_resize_bbt region_copy_to_bbt region_move_to_bbt midi_region_add_bbt
    midi_note_add_bbt midi_note_import_json_to_new_region_bbt ab_list ab_use_playlist
    transport_loop_location_samples region_copy_by_beats region_move_by_beats region_copy_by_samples
    region_move_by_samples midi_note_add_sample track_get_fader midi_note_import_json_to_new_region_samples
""".split()                       # ab_list / ab_use_playlist: playlist_list / playlist_select do the same for a track
# The last eight are needed only by an engine with the MIDI input and MPE tools (144 with every group on): the loop range
# by samples is markers_set_auto_loop_samples (the same handler), a copy or move by beats or by a distance is the copy or
# move to a sample, a note at a sample is a note at a beat of its region, track_get_info reads the fader too, and a new
# region from JSON is midi_region_add_samples then midi_note_import_json_into_region. Kept last, so an engine without
# those tools loses none of them.


# Engine tools never offered to the model: the meter stream's address and token are the app's own (daw_meters.py).
NEVER_OFFERED = frozenset({"meters_stream_info"})


def _order(enabled):
    """The groups asked for, oldest first: a list or tuple as given (its last one is the newest), a set in GROUPS order."""
    if isinstance(enabled, (list, tuple)):
        return list(dict.fromkeys(str(g) for g in enabled))
    en = {str(g) for g in enabled or ()}
    return [g for g in GROUPS if g in en] + sorted(en - set(GROUPS))


def offered(names, view=None, enabled=(), limit=MAX_OFFERED, cut=None, put_away=None):
    """The engine tools (by engine name) one request carries: the core, the groups the view needs and the groups the
    conversation asked for (`enabled`: oldest first when it is a list or tuple, GROUPS order when it is a set). A tool
    the core or a group does not cover (a new one from the engine) is in 'other'. Never more than `limit`; past it:
      1. the SECOND_FORMS go first (another form of a tool that stays does the same job);
      2. then whole groups that were asked for are put away: 'other' first, then the one asked for longest ago. Never
         the core, the view's groups or the last named group asked for (the one the conversation is working on). Each one
         put away is added to `put_away` (a list), so the model can be told that daw_more_tools brings it back;
      3. only if one group alone is still too big, tool by tool by priority (the core and the view's groups are
         kept; the 'other' group goes before the groups asked for).
    Never silently: every tool left out is added to `cut` (a list) so the person and the model can be told."""
    view_groups = set(VIEW_GROUPS.get(str(view or ""), ()))
    order = _order(enabled)
    want = view_groups | set(order)
    out = [n for n in names if n not in NEVER_OFFERED and (group_of(n) == "core" or group_of(n) in want)]
    dropped = []
    for n in SECOND_FORMS:
        if len(out) <= limit:
            break
        if n in out:
            out.remove(n)
            dropped.append(n)
    if len(out) > limit:
        newest = next((g for g in reversed(order) if g not in view_groups and g != "other"), None)
        for g in (["other"] if "other" in order else []) + [g for g in order if g != "other"]:
            if len(out) <= limit:
                break
            if g in view_groups or g == newest:
                continue
            gone = [n for n in out if group_of(n) == g]
            if not gone:
                continue
            out = [n for n in out if group_of(n) != g]
            dropped += gone
            if isinstance(put_away, list):
                put_away.append(g)
    if len(out) > limit:
        def rank(n):
            g = group_of(n)
            return 0 if g == "core" else 1 if g in view_groups else 3 if g == "other" else 2
        keep = set(sorted(out, key=lambda n: (rank(n), out.index(n)))[:limit])
        dropped += [n for n in out if n not in keep]
        out = [n for n in out if n in keep]
    if isinstance(cut, list):
        cut.extend(dropped)
    return out


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
        ty = p.get("type")
        if isinstance(ty, list):                         # ["string", "null"] (a field that null clears)
            ty = [x for x in ty if isinstance(x, str) and (x in _TYPES or x == "null")]
            q = {"type": ty} if ty else {}
        else:
            q = {"type": ty} if isinstance(ty, str) and ty in _TYPES else {}
        for lim in _LIMITS:
            if isinstance(p.get(lim), (int, float)) and not isinstance(p.get(lim), bool) and math.isfinite(p[lim]):
                q[lim] = p[lim]
        it = p.get("items")
        if q.get("type") == "array" and isinstance(it, dict) and isinstance(it.get("type"), str) and it["type"] in _TYPES:
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
        if "\\" in h:
            text = text.replace(h.replace("\\", "\\\\"), "~")        # the same folder inside JSON text, where each backslash is doubled
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
