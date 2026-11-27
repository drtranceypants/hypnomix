"""The original line of a level lane (a fader, trim or send), kept so that every HypnoMix writer holds a write to "at
most 3 dB from the original line" (4 dB for a trim) against the same line, however many writes or drags come one after
another (engineer/automation_rules.py: check's and judge's `original`). The Assistant, the DAW view, the engine
connection that checks every write, `hypnomix vocallevel` (--engine and --apply) all read it here.

What the original is: the line as it was heard before HypnoMix's first write to that lane: the lane's points when it
played them, else the control's own value. Once kept it stays, a lane that holds no points any more too: clearing a
lane leaves the control at the value it held (a ride's top, say), so starting again from that would let writes one
after another add up past the original.

Where it is kept: hypnomix-original-lines.json in the session's own folder (beside its .ardour snapshots; the engine's
session_list_snapshots names the folder), one entry per route id and control. In the folder because it then goes
where the session goes, and every snapshot of the session shares it (route ids are the same in each snapshot, so a
snapshot made from one that holds a ride cannot start again from that ride). Not in the session file: the engine's only
place for an app's data there is the song card, whose fields are its own, and the engine is not changed for this.

A lane edited by hand outside HypnoMix keeps its original: HypnoMix's later writes to it are still measured from that
line (a hand edit far from it makes them refused, with the reason), and so is a lane cleared since. To start again
from the line as it is now: remove the lane's entry from the file (or the file itself, for every lane): the next write
takes the line as it is then. The route id and control are kept as the engine reads them (route 02 is route 2, fader
and volume are gain), so one lane has one entry whatever name a call gives it.

  FILE
  folder_of(snaps) -> str or None                      session_list_snapshots' reply -> the session's folder
  pick(folder, route_id, control, lane, current) -> (line, entry, why)
                        line: t -> dB, the original (None when it cannot be known, and why says so); entry: what to
                        keep() once the write is allowed (None when the kept one is used)
  keep(folder, route_id, control, entry)               write it (OSError when the folder cannot be written)
"""
import json
import os
import tempfile
from pathlib import Path

from hypnomix.engineer import automation_rules as R

FILE = "hypnomix-original-lines.json"
ABOUT = ("HypnoMix: the original line of each automation lane it has written to, per route id and control. A level "
         "write never goes more than 3 dB (a trim 4 dB) from it. Remove an entry (or this file) to start again from the "
         "line as it is then.")


def folder_of(snaps):
    f = (snaps or {}).get("folder") if isinstance(snaps, dict) else None
    return str(f) if isinstance(f, str) and f.strip() else None


def key(route_id, control):
    """One lane, one key: the route id and control as the engine reads them (02 is route 2, fader is gain)."""
    return f"{R.canon_route(str(route_id))}|{R.canon_control(str(control))}"


def load(folder):
    """The kept lines {key: entry}; {} when there is no file. ValueError when it is there but cannot be read."""
    p = Path(folder) / FILE
    if not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"{FILE} in the session's folder could not be read ({type(e).__name__})")
    lines = d.get("lines") if isinstance(d, dict) else None
    if not isinstance(lines, dict):
        raise ValueError(f"{FILE} in the session's folder is not a file of original lines")
    return lines


def line_of(entry):
    """An entry -> t -> dB (None when it is not one)."""
    if not isinstance(entry, dict):
        return None
    if isinstance(entry.get("points"), list) and entry["points"]:
        ln = R.line_from({"pointList": entry["points"]})
        return ln if ln is not None and ln.points else None
    return R.flat(entry.get("value"))


def _entry(line):
    return {"points": [[t, v] for t, v in line.points]} if line.points else {"value": line(0.0)}


def pick(folder, route_id, control, lane, current):
    """The lane's original line -> (line, entry to keep or None, why it is not known or '')."""
    k = R.kind(control)
    if not folder:
        return None, None, ("the session's folder could not be read (session_list_snapshots), so the lane's original "
                            "line cannot be kept: nothing is written")
    try:
        kept = load(folder).get(key(route_id, control))
    except ValueError as e:
        return None, None, f"{e}: fix it, or remove it to start every lane again from its line as it is then"
    if kept is not None:                        # kept wins, a lane with no points too (a clear never starts it again)
        ln = line_of(kept)
        if ln is None:
            return None, None, (f"the original line kept for this lane in {FILE} is not readable: remove its entry to "
                                f"start again from the line as it is then")
        return ln, None, ""
    if not R.points_of((lane or {}).get("pointList")):
        ln = R.flat(current)
        if ln is None:
            return None, None, R.unknown(k)
        return ln, _entry(ln), ""
    ln = R.heard(lane, current)
    if ln is None:
        return None, None, R.unknown(k)
    return ln, _entry(ln), ""


def keep(folder, route_id, control, entry):
    """Keep an entry (a new file, or a new or replaced entry; written in full beside the old and moved over it)."""
    lines = load(folder)
    lines[key(route_id, control)] = entry
    body = json.dumps({"about": ABOUT, "lines": lines}, indent=1, sort_keys=True)
    fd, tmp = tempfile.mkstemp(prefix=".hypnomix-lines-", suffix=".tmp", dir=str(folder))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, Path(folder) / FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
