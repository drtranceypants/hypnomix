"""`hypnomix duck` on a HypnoMix Studio session: duck the vocal reverb and delay returns.

The same check as for a Live set (`duck.py`), on the shared model (`project/ardour.py`):

  returns   buses fed by aux sends (internal sends); a reverb or a delay by their name or plug-ins
  vocals    tracks labelled as vocals in names.json, else named like them (vocal, vox, harmony, backing, lead)
  source    the vocal group's bus when (nearly) every vocal sits in one group, else the first vocal
  key       what the pre-fader sidechain send from the source carries (plug-ins not simulated): from the vocal
            group's bus, every track in that bus at its fader, summed, without the bus fader; from one vocal, that
            track alone with its trim, without its fader
  tune      an ACE Compressor on the return already keyed from the vocals: how far it ducks (measured on what its
            own key sends carry) while the singer sings and whether it lets go in the gaps; a new threshold (and
            release) when it is off. A switched-off compressor is switched on (the plug-in and its Enable control)
            and a switched-off key send is made again from the source
  add       nothing ducks the return yet: an ACE Compressor at the end of its chain, keyed from the source
            (plugin_set_sidechain, pre-fader), ratio 4, 1 ms attack, 205 ms release, the threshold fitted to
            --depth dB (3) while the singer sings; reverbs a little lighter (2 dB)

Every item is an option. Approved ones are written straight into the open HypnoMix engine over MCP
(`--engine [URL] --ids duck-1`): plugin_add_by_plugin_id, plugin_set_parameter_by_index_value, plugin_set_enabled,
plugin_set_sidechain (tap pre_fader), each read back: a control the engine does not list, a value that reads back
different, or a compressor that reads back switched off or unkeyed is reported as not done. Before anything is
written the engine must have THIS session file open (`ardour_groups.require_open`), and every route id (and, for a
tune, the plug-in at its index) must still be the one the scan saw (`check_targets`). None of that is in the engine's undo history: remove the plug-in (or call plugin_set_sidechain with "none")
to put it back. The compressor is simulated: check it by ear.
"""
import json
import re
from pathlib import Path

import numpy as np

from hypnomix.engineer import sidechain as SC
from hypnomix.workflow import sidechain_project as SCP

VOCALISH = re.compile(r"vocal|vox|voice|harmony|backing|\bbv\b|\blead\b|choir|sing", re.I)
DELAY = re.compile(r"delay|echo", re.I)
REVERB = re.compile(r"reverb|verb|hall|plate|room|space|tail", re.I)
ACE = "lv2:urn:ardour:a-comp#stereo"
ACE_MONO = "lv2:urn:ardour:a-comp"
NEW = dict(kind="ace", model=0, ratio=4.0, knee=6.0, attack=1.0, release=205.0, lookahead=0, lookahead_ms=0.0,
           sc_gain_db=0.0, eq_on=False, eq_mode=SC.HIGHPASS, eq_freq=100.0, eq_q=0.707, eq_gain=0.0, dry_wet=1.0,
           range_db=None, threshold_db=-20.0)


def vocal_tracks(p, labels=None):
    out = []
    for t in p.tracks:
        if t.kind != "audio" or not t.active or not t.clips:
            continue
        lab = (labels or {}).get(t.name)
        if lab is not None:
            if float(lab.get("confidence") or 0) >= 0.5 and VOCALISH.search(str(lab.get("label") or "")):
                out.append(t)
        elif VOCALISH.search(t.name):
            out.append(t)
    lead = next((t for t in out if re.search(r"lead", t.name, re.I)), None)
    return ([lead] + [t for t in out if t is not lead]) if lead else out


def vocal_source(p, vocals):
    """The group bus most vocals sit in (3 in 4 or more), else the first vocal."""
    buses = [t.parent for t in vocals if t.parent is not None and t.parent.kind == "folder"]
    if buses:
        b = max(set(buses), key=buses.count)
        if buses.count(b) >= 0.75 * len(vocals):
            return b
    return vocals[0] if vocals else None


def returns_of(p):
    out = []
    for t in p.tracks:
        if t.kind != "return":
            continue
        tags = t.name + " " + " ".join(d.name for d in t.devices)
        kind = "delay" if DELAY.search(tags) else "reverb" if REVERB.search(tags) else None
        out.append(dict(name=t.name, track=t, kind=kind))
    return out


def aux_sends(t):
    """A route's aux sends -> {target route id: gain linear}."""
    out = {}
    rt = t.native
    for pr in (rt.findall("Processor") if rt is not None else []):
        if pr.get("type") != "intsend":
            continue
        gc = next((c for c in pr.iter("Controllable") if c.get("name") == "gaincontrol"), None)
        g = float(gc.get("value", 1.0)) if gc is not None else 1.0
        if pr.get("active", "1") in ("1", "yes", "true"):
            out[pr.get("target")] = max(out.get(pr.get("target"), 0.0), g)
    return out


def key_audio(p, vocals, source):
    """What a pre-fader send from `source` carries, at the simulation rate: a bus's tracks at their faders (not the bus
    fader), or one track with its trim (not its fader). `vocals` is the fallback when there is no source."""
    L = p.end()
    if source is None:
        return None
    if SCP.is_bus(source):
        mix = SCP.bus_audio(p, source, L)
    else:
        mix = p.render(source, 44100, L) * (getattr(source, "trim", None) or 1.0)
    return SC.to_sr(mix, 44100) if mix is not None else None


def propose(p, labels=None, depth=3.0):
    from hypnomix.engineer import duck as D
    vocals = vocal_tracks(p, labels)
    if not vocals:
        return [], dict(note="no vocal tracks found")
    src = vocal_source(p, vocals)
    feeders = vocals + ([src] if src is not None and src not in vocals else [])
    fed = []
    for r in returns_of(p):
        if not r["kind"]:
            continue
        lv = max([20 * np.log10(max(aux_sends(t).get(r["track"].route_id, 0.0), 1e-9)) for t in feeders] + [-70.0])
        if lv > -40:
            fed.append(dict(r, send_db=round(float(lv), 1)))
    if not fed:
        return [], dict(note="the vocals don't send to a reverb or delay return", source=src.name if src else None)
    trig = key_audio(p, vocals, src)
    if trig is None or not np.any(trig):
        return [], dict(note="the vocals have no audio to key from")
    act = D.active_mask(trig)
    names = {t.name for t in feeders}
    out = []
    for r in fed:
        t = r["track"]
        target = depth if r["kind"] == "delay" else max(1.0, depth - 1.0)
        here = [(k, d) for k, d in enumerate(t.devices) if SCP.is_ace_comp(d)
                and (set(d.sidechain) | set(getattr(d, "sidechain_off", None) or [])) & names]
        if here:
            k, d = here[0]
            c = SCP.ace_settings(d)
            by_name = {x.name: x for x in p.tracks}
            feeds = [(by_name[n], g, tap == "post_fader") for n, tap, g in d.sidechain_feeds if n in by_name]
            heard = SCP.trigger_audio(p, feeds, p.end()) if feeds else None     # what its own key sends carry
            key = heard if heard is not None and np.any(heard) and len(heard) == len(trig) else trig
            cur = SC.phrase_measure(SC.gain_reduction(SC.detector(key, c), c), act)
            problems = []
            rekey = None
            if not feeds:
                problems.append(f"its key send from {', '.join(d.sidechain_off)} is switched off, so nothing keys it")
                rekey = src.route_id
                key = trig
            if not c["on"]:
                problems.append("it is switched off")
            if not c["switch"]:
                problems.append("its Sidechain switch is off, so it listens to the return itself")
            if cur["depth"] < 0.6 * target:
                problems.append(f"it barely ducks ({cur['depth']:.1f} dB while the singer sings)")
            elif cur["depth"] > 2.5 * target:
                problems.append(f"it ducks hard ({cur['depth']:.1f} dB while the singer sings)")
            if cur["in_gaps"] > 1.5:
                problems.append(f"it is still {cur['in_gaps']:.1f} dB down half a second into the gaps")
            if not problems:
                continue
            new = dict(c)
            if new["release"] < 100 or new["release"] > 400:
                new["release"] = float(np.clip(new["release"], 150, 300))
            new, m = D.fit(key, act, new, target)
            out.append(dict(kind="tune", ret=r["name"], ret_id=t.route_id, kind_ret=r["kind"], plugin_index=k,
                            source=", ".join(d.sidechain or d.sidechain_off), new=new, m=m, problems=problems,
                            enable_plugin=not d.on, enable_control=float(d.params.get("Enable", 1.0)) <= 0.5,
                            rekey=rekey))
        else:
            new, m = D.fit(trig, act, dict(NEW), target)
            out.append(dict(kind="add", ret=r["name"], ret_id=t.route_id, kind_ret=r["kind"], send_db=r["send_db"],
                            source=src.name, source_id=src.route_id, new=new, m=m))
    return out, dict(source=src.name, vocals=[t.name for t in vocals])


def findings(props):
    fs = []
    for i, pr in enumerate(props, 1):
        n, m = pr["new"], pr["m"]
        vals = SCP.ace_values(n)
        settings = SCP.describe_ace(n)
        result = f"ducks about {m['depth']:.1f} dB while the singer sings, {m['in_gaps']:.1f} dB half a second into the gaps"
        common = dict(id=f"duck-{i}", tool="duck", severity="low", track=pr["ret"], where="", applies="engine")
        if pr["kind"] == "add":
            fs.append(dict(common, kind="duck-add",
                           problem=f"the vocals send to the {pr['kind_ret']} '{pr['ret']}' ({pr['send_db']:+.0f} dB) and "
                                   f"nothing ducks it: the {pr['kind_ret']} sits on top of the words",
                           fix=f"add an ACE Compressor at the end of '{pr['ret']}', its sidechain keyed from "
                               f"'{pr['source']}' (pre-fader): {settings}; {result}. An option "
                               f"({'recommended for delays' if pr['kind_ret'] == 'delay' else 'reverbs: lighter, optional'})",
                           ardour=dict(op="add", ret_id=pr["ret_id"], source_id=pr["source_id"], values=vals,
                                       source_name=pr["source"])))
        else:
            fs.append(dict(common, kind="duck-tune",
                           problem=f"the vocal ducking on '{pr['ret']}' (from '{pr['source']}'): " + "; ".join(pr["problems"]),
                           fix=("switch it on and " if pr.get("enable_plugin") or pr.get("enable_control") else "")
                               + ("key it again from the source (pre-fader) and " if pr.get("rekey") else "")
                               + f"set it to {settings}: {result}. An option",
                           ardour=dict(op="tune", ret_id=pr["ret_id"], plugin_index=pr["plugin_index"],
                                       values=dict(vals, **({"Enable": 1} if pr.get("enable_control") else {})),
                                       enable=bool(pr.get("enable_plugin")), rekey=pr.get("rekey"))))
    return fs


# ---------------------------------------------------------------- writing over MCP
REQUIRED = ("Threshold", "Ratio", "Attack", "Release", "Enable")      # without these the duck is not what was approved


def _params(eng, tid, index):
    d = eng.call("plugin_get_description", {"id": tid, "pluginIndex": index})
    return {p.get("label"): p for p in d.get("parameters", []) if p.get("isInput")}


def _set_values(eng, tid, index, values):
    """Each control by its label -> plugin_set_parameter_by_index_value. Returns the labels the engine does not list."""
    by_label = _params(eng, tid, index)
    missing = []
    for label, val in values.items():
        prm = by_label.get(label)
        if prm is None:
            missing.append(label)
            continue
        eng.call("plugin_set_parameter_by_index_value", {"id": tid, "pluginIndex": index, "parameterIndex": prm["index"],
                                                         "value": float(val)})
    return missing


def _read_back(eng, tid, index, values):
    """(values read back {label: value}, problems): each sent value against the engine's, and the plug-in switched on."""
    problems, got = [], {}
    by_label = _params(eng, tid, index)
    for label, want in values.items():
        prm = by_label.get(label)
        v = prm.get("currentValue", prm.get("value")) if prm else None
        if v is None:
            continue
        got[label] = float(v)
        if abs(float(v) - float(want)) > 0.05 + 0.01 * abs(float(want)):
            problems.append(f"{label} reads back {float(v):g}, not {float(want):g}")
    plugs = eng.call("track_get_info", {"id": tid}).get("plugins", [])
    me = next((x for x in plugs if x.get("index") == index), None)
    if me is not None and me.get("enabled") is False:
        problems.append("the compressor reads back switched off")
    return got, problems


def check_targets(eng, fs, ids):
    """Before any write: each approved option's route ids must carry, in the engine, the names the scan saw (route ids
    are small numbers that every session reuses), and a tune's plug-in index must hold an ACE Compressor. Returns
    the reasons for the ones that do not ({finding id: sentence}); those are not written."""
    from hypnomix.project.ardour_groups import EngineError
    names = {str(t.get("id")): t.get("name") for t in eng.call("tracks_list", {"includeHidden": True}).get("tracks", [])
             if isinstance(t, dict)}
    bad = {}
    for f in fs:
        if f["id"] not in set(ids):
            continue
        a = f["ardour"]
        need = [(a["ret_id"], f["track"])] + ([(a["source_id"], a.get("source_name"))] if a["op"] == "add" else [])
        wrong = [f"route {rid} is '{names.get(str(rid))}' in the engine, not '{nm}'" if str(rid) in names
                 else f"no route {rid} ('{nm}') in the engine" for rid, nm in need if names.get(str(rid)) != nm]
        if wrong:
            bad[f["id"]] = "; ".join(wrong) + " (is this the session it scanned? scan it again)"
            continue
        if a["op"] == "tune":
            try:
                d = eng.call("plugin_get_description", {"id": a["ret_id"], "pluginIndex": a["plugin_index"]})
            except EngineError as e:
                bad[f["id"]] = f"could not read plug-in {a['plugin_index']} on '{f['track']}': {e}"
                continue
            d = d.get("plugin", d) if isinstance(d, dict) else {}       # the engine nests it under "plugin"
            d = d if isinstance(d, dict) else {}
            what = " ".join(str(d.get(k) or "") for k in ("name", "uniqueId", "uri", "label")).lower()
            if "a-comp" not in what and "ace compressor" not in what:
                bad[f["id"]] = (f"plug-in {a['plugin_index']} on '{f['track']}' is not the ACE Compressor the scan saw "
                                f"({d.get('name') or 'unknown'}): scan it again")
    return bad


def apply(eng, fs, ids):
    """Approved duck findings -> MCP. Returns (log, failed)."""
    from hypnomix.project.ardour_groups import EngineError
    log, failed = [], []
    for f in fs:
        if f["id"] not in set(ids):
            continue
        a = f["ardour"]
        warn = []
        try:
            if a["op"] == "add":
                av = json.dumps(eng.call("plugin_list_available", {"search": "ACE Compressor"}))
                uri = ACE if "a-comp#stereo" in av else ACE_MONO
                before = {p["index"] for p in eng.call("track_get_info", {"id": a["ret_id"]}).get("plugins", [])}
                eng.call("plugin_add_by_plugin_id", {"id": a["ret_id"], "pluginId": uri})
                plugs = eng.call("track_get_info", {"id": a["ret_id"]}).get("plugins", [])
                new = [p["index"] for p in plugs if p["index"] not in before] or [max(p["index"] for p in plugs)]
                index = new[0]
                missing = _set_values(eng, a["ret_id"], index, a["values"])
                eng.call("plugin_set_sidechain", {"track_id": a["ret_id"], "plugin_index": index,
                                                  "source_track_id": a["source_id"], "tap": "pre_fader"})
            else:
                index = a["plugin_index"]
                if a.get("enable"):
                    eng.call("plugin_set_enabled", {"id": a["ret_id"], "pluginIndex": index, "enabled": True})
                missing = _set_values(eng, a["ret_id"], index, a["values"])
                if a.get("rekey"):
                    eng.call("plugin_set_sidechain", {"track_id": a["ret_id"], "plugin_index": index,
                                                      "source_track_id": a["rekey"], "tap": "pre_fader"})
            need = [x for x in missing if x in REQUIRED]
            warn = [x for x in missing if x not in REQUIRED]
            got, bad = _read_back(eng, a["ret_id"], index, {k: v for k, v in a["values"].items() if k not in missing})
            sc = eng.call("plugin_get_sidechain", {"track_id": a["ret_id"], "plugin_index": index})["sidechains"][0]
        except (EngineError, KeyError, IndexError, TypeError, ValueError) as e:
            failed.append(f"{f['id']}: {e if isinstance(e, EngineError) else f'the engine answered without {e}'}")
            continue
        if need:
            failed.append(f"{f['id']}: the engine does not list {', '.join(need)} on the compressor, so it was not set")
            continue
        if bad:
            failed.append(f"{f['id']}: " + "; ".join(bad))
            continue
        if not sc["sources"] or not (sc.get("switch") or {}).get("on"):
            failed.append(f"{f['id']}: the compressor reads back unkeyed: {json.dumps(sc)[:300]}")
            continue
        v = dict(a["values"], **got)
        said = SCP.describe_ace(dict(threshold_db=v["Threshold"], ratio=v["Ratio"], attack=v["Attack"], release=v["Release"],
                                     knee=6 * v.get("Knee", 0.0)))
        log.append(f"- {f['id']}: ACE Compressor {index} on {f['track']} keyed from "
                   f"{', '.join(s['name'] for s in sc['sources'])}: {said}"
                   + (" (read back)" if got else " (the engine does not report the values: not read back)")
                   + (f"; the engine does not list {', '.join(warn)}, left as it was" if warn else ""))
    return log, failed


def main(path, a):
    from hypnomix.project import ardour as AR
    from hypnomix.project import ardour_groups as AG
    AG.daw_flags(a, "duck-1")
    p = AR.read(path)
    props, meta = propose(p, AG.labels_from(getattr(a, "names", None)), a.depth)
    fs = findings(props)
    print(f"{Path(p.path).name}: vocals → sidechain source '{meta.get('source')}'; {len(fs)} ducking option(s)"
          + (f" ({meta['note']})" if meta.get("note") else ""))
    for f in fs:
        print(f"  {f['id']:<8} {f['track']:<30} {f['fix'].split('. An option')[0]}")
    if a.json:
        from hypnomix.core import atomic as AT
        AT.write_json(Path(a.json), {"tool": "duck", "set": str(p.path), "findings": fs})
    if getattr(a, "engine", None) is None:
        return 0
    want = AG.wanted(fs, a.ids, "duck-1")
    log, failed = [], []
    try:
        eng = AG.Engine(a.engine or None)
        if not eng.has("plugin_set_sidechain", "plugin_get_sidechain"):
            raise SystemExit(f"the engine at {eng.url} does not answer, or has no sidechain tools (an older HypnoMix "
                             f"engine); {AG.WHERE_URL}")
        if AG.require_open(eng, p.path):
            print("  note: the engine has unsaved changes, so the saved file may be behind it; each track and "
                  "plug-in is checked in the engine first")
        bad = check_targets(eng, fs, want)
        failed += [f"{k}: {v}" for k, v in bad.items()]
        log, more = apply(eng, fs, [x for x in want if x not in bad])
        failed += more
    except AG.EngineError as e:
        failed.append(str(e))
    for line in log:
        print(line)
    for line in failed:
        print("  not done: " + line)
    if log:
        print(AG.APP_NOTICES + ".")
    return 1 if failed else 0
