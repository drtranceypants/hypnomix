"""Read a .ptx / .ptf / .pts session into the import model (hypnomix.project.importer).

The session is read by the engine's reader for these sessions (hypnomix-ptdump, which comes with the HypnoMix DAW
add-on, for Apple-silicon Macs only so far; without it this cannot run). What it
gives: tracks (by name, in order), audio regions (position, start in the file, length) with their files from the
session's Audio Files folder, and MIDI regions with their notes. What the session file does not give this reader, and
the report says so: fader, pan, mute, solo, sends, plug-ins, clip gain, fades, tempo and meter (the session is made
at 120 BPM, 4/4; audio sits at its exact time either way), markers and playlists other than the active one.

A stereo track is kept there as two mono files (Name.L, Name.R): both are carried, as one stereo region.
"""
import re
from pathlib import Path

from hypnomix.project import engine_tools

PT_TICKS_PER_BEAT = 960000          # MIDI note ticks
PT_TICKS_PER_SEC = 1920000          # MIDI region ticks (the engine's own .ptx import reads them so)
SEARCH_LIMIT = 20000                # files looked at when an audio file is not in Audio Files


def _index(folder):
    found = {}
    n = 0
    for p in folder.rglob("*"):
        n += 1
        if n > SEARCH_LIMIT:
            break
        if p.is_file():
            found.setdefault(p.name.lower(), p)
    return found


def read(path):
    path = Path(path).expanduser().resolve()
    data = engine_tools.run("hypnomix-ptdump", path)
    rate = int(data.get("rate") or 48000)
    folder = path.parent
    audio_dir = folder / "Audio Files"
    files = {}
    index = None

    def locate(name):
        nonlocal index
        if not name:
            return None
        if name in files:
            return files[name]
        p = audio_dir / name
        if not p.is_file():
            if index is None:
                index = _index(folder)
            p = index.get(name.lower()) or audio_dir / Path(name).name    # not found: named in the report
        files[name] = p
        return p

    from hypnomix.project.importer import Budget
    budget = Budget(path.name)
    tracks, order, empty = {}, [], 0
    for t in data.get("tracks", []):
        name = t.get("name") or f"Audio {t.get('index', 0) + 1}"
        key = re.sub(r"\.(L|R)$", "", name)              # a stereo track's two mono halves are one track
        tr = tracks.get(key)
        if tr is None:
            budget.add(tracks=1)
            tr = tracks[key] = dict(name=key, kind="audio", regions=[], midi=[], notes=[])
            order.append(key)
        r = t.get("region") or {}
        if not r.get("length"):
            empty += 1
            continue
        budget.add(regions=1)
        f = locate(r.get("file"))
        reg = dict(name=r.get("name") or "", file=f, position=r["start"] / rate, start=r.get("offset", 0) / rate,
                   length=r["length"] / rate)
        # the other half of a stereo pair at the same place: one stereo region, both files' channels
        twin = next((x for x in tr["regions"] if abs(x["position"] - reg["position"]) < 1 / rate and
                     abs(x["length"] - reg["length"]) < 1 / rate and x.get("pair") is None and x["file"] != f), None)
        if twin is not None and re.search(r"\.(L|R)$", name):
            twin["pair"] = reg
            continue
        tr["regions"].append(reg)
    for t in data.get("miditracks", []):
        name = t.get("name") or f"MIDI {t.get('index', 0) + 1}"
        key = f"midi:{name}"
        tr = tracks.get(key)
        if tr is None:
            budget.add(tracks=1)
            tr = tracks[key] = dict(name=name, kind="midi", regions=[], midi=[], notes=[])
            order.append(key)
        r = t.get("region") or {}
        budget.add(regions=1, notes=len(r.get("notes", [])))
        notes = [(pos / PT_TICKS_PER_BEAT, ln / PT_TICKS_PER_BEAT, key_, vel) for pos, ln, key_, vel in r.get("notes", [])]
        length = max([r.get("length", 0) / PT_TICKS_PER_BEAT] + [n[0] + n[1] for n in notes])
        tr["midi"].append(dict(name=r.get("name") or name, position=r.get("start", 0) / PT_TICKS_PER_SEC * 2,
                               length=length, notes=notes))

    out = []
    for key in order:
        tr = tracks[key]
        for r in tr["regions"]:
            pair = r.pop("pair", None)
            if pair is not None:                  # the two mono halves of a stereo region: one region, L then R
                left_first = not re.search(r"[._ -]R(\.\w+)?$", r["file"].name if r["file"] else "")
                r["files"] = [r["file"], pair["file"]] if left_first else [pair["file"], r["file"]]
        out.append(tr)
    not_carried = ["fader, pan, mute and solo, sends and buses, plug-ins and instruments: a .ptx session file keeps "
                   "these where this reader cannot read them; set them in the new session",
                   "clip gain, fades, markers, tempo and meter (the session is at 120 BPM 4/4; audio is placed at its "
                   "exact time either way, MIDI in the session's own ticks at 120 BPM)",
                   "inactive playlists and hidden tracks"] + \
        ([f"{empty} region(s) of zero length: not carried"] if empty else [])
    return dict(name=path.stem, source=path, daw=f".ptx session (version {data.get('version', '?')})", rate=rate,
                bpm=120.0, tempo=[], num=4, den=4, markers=[], tracks=out, not_carried=not_carried, warnings=[],
                tempo_assumed=True)
