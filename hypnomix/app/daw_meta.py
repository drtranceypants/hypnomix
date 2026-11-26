"""DAW mode: what the engine's MCP tools do not report yet, read from the session file the engine has open.

The engine's tools give the tempo (session_get_info) but not the time signature or the track colours. The saved
`.ardour` file has them: the time signature (the TempoMap's first Meter) and each route's colour (PresentationInfo
`color`, RGBA; 0 = none chosen).
It is the *saved* state: a colour set since the last save is known to the page that set it, not to this file.
Read only; cached by the file's modification time.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

_CACHE = {}


def _colour(v):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    if n == 0:
        return None
    return "#%06x" % ((n >> 8) & 0xFFFFFF)          # Ardour stores 0xRRGGBBAA


def read(path):
    """{tempo, meter: [beats, note], colors: {route id: '#rrggbb'}, saved: mtime}"""
    p = Path(str(path)).expanduser()
    if p.is_dir():
        snaps = sorted(p.glob("*.ardour"))
        p = next((s for s in snaps if s.stem == p.name), snaps[0] if snaps else p)
    if not p.is_file():
        raise ValueError(f"no session file at {p}")
    mt = p.stat().st_mtime
    hit = _CACHE.get(str(p))
    if hit and hit[0] == mt:
        return hit[1]
    root = ET.parse(p).getroot()
    out = {"session": str(p), "saved": mt, "tempo": None, "meter": None, "colors": {}}
    t = root.find(".//TempoMap//Tempo")
    if t is not None:
        try:
            out["tempo"] = float(t.get("npm") or t.get("note-types-per-minute") or 0) or None
        except ValueError:
            pass
    m = root.find(".//TempoMap//Meter")
    if m is not None:
        try:
            out["meter"] = [int(float(m.get("divisions-per-bar"))), int(float(m.get("note-value")))]
        except (TypeError, ValueError):
            pass
    for r in root.iter("Route"):
        pi = r.find("PresentationInfo")
        c = _colour(pi.get("color")) if pi is not None else None
        if c and r.get("id"):
            out["colors"][r.get("id")] = c
    _CACHE[str(p)] = (mt, out)
    return out
