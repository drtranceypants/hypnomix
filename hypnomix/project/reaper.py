"""Read a REAPER project (.rpp) into the shared model (`model.Project`).

What is read, and from where (REAPER writes everything in seconds, so nothing needs a tempo to place it):

  project   TEMPO bpm num den, SAMPLERATE, the tempo map (TEMPOENVEX), RECORD_PATH
  tracks    NAME, VOLPAN (fader, pan), MUTESOLO, IPHASE (polarity), ISBUS (folders: parent and depth),
            FX (whole chain on/off), FXCHAIN (each plug-in: name, BYPASS, offline, PRESETNAME, JS sliders)
  envelopes VOLENV2/VOLENV (volume), PANENV2/PANENV (pan), MUTEENV, PARMENV (plug-in parameters): PT lines
  items     POSITION, LENGTH, LOOP, FADEIN/FADEOUT (shape, length, auto-crossfade length), MUTE, VOLPAN
            (item volume, first take's pan and volume), each take's NAME, SOFFS, PLAYRATE (rate, keep pitch),
            TAKEVOLPAN, SOURCE (WAVE/FLAC/MP3/... FILE, SECTION, MIDI, EMPTY), stretch markers (SM)

Volume values are linear amplitude (1.0 = 0 dB), envelope points too: REAPER saves amplitudes even when the
envelope shows fader scaling (VOLTYPE 1), checked against REAPER 7.86. FADEIN/FADEOUT: shape (6 is saved as 5.1),
length, auto-crossfade length (used when set). Stretch markers are followed (each segment at its own speed); reversed sections are reported; the renderer plays such takes
straight (a warning says so).
"""
import os
import re
from pathlib import Path

from hypnomix.project import rpp
from hypnomix.project.model import Clip, Device, Project, Take, Track

AUDIO_SOURCES = {"WAVE", "FLAC", "MP3", "VORBIS", "OPUS", "WAVPACK", "AIFF", "OGG", "CAF"}
FX_TAGS = {"VST", "AU", "JS", "CLAP", "DX", "LV2", "VIDEO_EFFECT"}
ENV_NAMES = {"VOLENV2": "Volume", "VOLENV": "Volume (pre-FX)", "VOLENV3": "Trim Volume", "PANENV2": "Pan",
             "PANENV": "Pan (pre-FX)", "MUTEENV": "Mute", "WIDTHENV2": "Width"}


def num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def resolve(path, proj_dir, record_path=""):
    """Where an item's file really is: absolute, next to the project, in the recording folder, or anywhere below.
    A project saved on Windows writes `Audio\\Drums.wav` and `C:\\Users\\...`: read on another system the backslashes are
    folder separators too, and a path that starts with a drive letter is looked for by its file name."""
    if not path:
        return None
    text = str(path)
    if os.sep != "\\":
        text = text.replace("\\", "/")
        record_path = str(record_path or "").replace("\\", "/")
    p = Path(text)
    foreign = os.sep != "\\" and re.match(r"^[A-Za-z]:/", text) is not None       # a Windows path on a Mac or Linux
    cands = [p] if p.is_absolute() else []
    cands += ([] if foreign else [proj_dir / p])
    cands += [proj_dir / record_path / p.name, proj_dir / p.name, proj_dir / "Audio" / p.name, proj_dir / "Media" / p.name]
    for c in cands:
        if c.exists():
            return c
    hits = list(proj_dir.rglob(p.name)) if proj_dir.exists() else []
    return hits[0] if hits else (p if p.is_absolute() or foreign else proj_dir / p)


def _source(ch, proj_dir, rec):
    """A <SOURCE ...> chunk -> (kind, path, section, reversed)."""
    if ch is None:
        return "empty", None, None, False
    typ = ch.tokens[1] if len(ch.tokens) > 1 else ""
    if typ == "SECTION":
        inner = ch.chunk("SOURCE")
        kind, path, _, _ = _source(inner, proj_dir, rec)
        sec = (num(ch.get("STARTPOS")), num(ch.get("LENGTH")))
        return kind, path, sec, ch.get("MODE", cast=int, default=0) in (2, 3)
    if typ in AUDIO_SOURCES:
        return "audio", resolve(ch.get("FILE", default=""), proj_dir, rec), None, False
    if typ == "MIDI":
        return "midi", None, None, False
    if typ == "EMPTY" or not typ:
        return "empty", None, None, False
    f = ch.get("FILE")
    return ("audio", resolve(f, proj_dir, rec), None, False) if f else (typ.lower(), None, None, False)


def _takes(item, proj_dir, rec, warn, where):
    """Split an <ITEM> into its takes. The first take's lines sit at the top of the item; each `TAKE` line
    starts the next one. The take marked `TAKE SEL` plays (else the first)."""
    groups, cur, active = [], [], 0
    for c in item.children:
        if isinstance(c, rpp.Line) and c.key == "TAKE":
            groups.append(cur)
            cur = [c]
            if "SEL" in c.tokens[1:]:
                active = len(groups)
        else:
            cur.append(c)
    groups.append(cur)
    takes, sm_total = [], 0
    for n, g in enumerate(groups):
        lines = {c.key: c for c in g if isinstance(c, rpp.Line)}
        src = next((c for c in g if isinstance(c, rpp.Chunk) and c.name == "SOURCE"), None)
        if n and "TAKE" in lines and "NULL" in lines["TAKE"].tokens[1:]:
            takes.append(Take(name="", kind="empty", native=g))
            continue
        kind, path, section, rev = _source(src, proj_dir, rec)
        if n == 0:
            vp = lines.get("VOLPAN")
            gain = num(vp.tokens[3], 1.0) if vp is not None and len(vp.tokens) > 3 else 1.0
        else:
            tv = lines.get("TAKEVOLPAN")
            gain = num(tv.tokens[2], 1.0) if tv is not None and len(tv.tokens) > 2 else 1.0
        pr = lines.get("PLAYRATE")
        rate = num(pr.tokens[1], 1.0) if pr is not None and len(pr.tokens) > 1 else 1.0
        keep = (pr.tokens[2] != "0") if pr is not None and len(pr.tokens) > 2 else True
        nm = lines.get("NAME")
        # stretch markers: one SM line, markers joined by "+" ("SM 0.5 0.8 + 1.5 1.2"): (take time, source seconds)
        marks = []
        for ln in (c for c in g if isinstance(c, rpp.Line) and c.key == "SM"):
            grp = []
            for tok in ln.tokens[1:] + ["+"]:
                if tok == "+":
                    if len(grp) >= 2:
                        marks.append((num(grp[0]), num(grp[1])))
                    grp = []
                else:
                    grp.append(tok)
        sm = len(marks)
        sm_total += sm if n == active else 0
        if rev and n == active:
            warn.append(f"{where}: a reversed take is rendered forwards")
        takes.append(Take(name=nm.tokens[1] if nm is not None and len(nm.tokens) > 1 else "",
                          path=path, offset=num(lines["SOFFS"].tokens[1]) if "SOFFS" in lines else 0.0,
                          gain=gain, rate=rate if rate > 0 else 1.0, preserve_pitch=keep, section=section,
                          kind=kind, stretch=sorted(marks) or None, native=g))
    return takes, min(active, len(takes) - 1), sm_total


def _fade(item, key):
    ln = item.line(key)
    if ln is None or len(ln.tokens) < 3:
        return 0.0, 0
    raw = num(ln.tokens[1])
    shape = 6 if abs(raw - 5.1) < 1e-6 else int(raw)      # REAPER saves shape 6 as "5.1"
    length = num(ln.tokens[2])
    auto = num(ln.tokens[3]) if len(ln.tokens) > 3 else 0.0
    if len(ln.tokens) > 5 and ln.tokens[5] == "1":        # equal-power crossfade (measured: sin / cos)
        shape = 7
    return (auto if auto > 0 else length), shape


def _clip(item, proj_dir, rec, warn, tname):
    item.project_dir = proj_dir                 # edits write new file paths relative to the project
    pos, length = num(item.get("POSITION")), num(item.get("LENGTH"))
    where = f"{tname} item at {pos:.2f} s"
    takes, active, sm = _takes(item, proj_dir, rec, warn, where)
    vp = item.line("VOLPAN")
    item_vol = num(vp.tokens[1], 1.0) if vp is not None and len(vp.tokens) > 1 else 1.0
    fi, fis = _fade(item, "FADEIN")
    fo, fos = _fade(item, "FADEOUT")
    mute = item.line("MUTE")
    name = item.get("NAME", default="") or (takes[active].name if takes else "")

    return Clip(name=name, start=pos, length=length, takes=takes, active=active, gain=item_vol,
                loop=item.get("LOOP", cast=int, default=1) == 1, fade_in=fi, fade_out=fo, fade_in_shape=fis,
                fade_out_shape=fos, muted=mute is not None and len(mute.tokens) > 1 and mute.tokens[1] == "1",
                stretch_markers=sm, native=item)


def _envelope(ch):
    pts = []
    for ln in ch.lines("PT"):
        if len(ln.tokens) >= 3:
            pts.append((num(ln.tokens[1]), num(ln.tokens[2])))
    act = ch.line("ACT")
    on = act is None or (len(act.tokens) > 1 and act.tokens[1] == "1")
    return pts, on





def _devices(tr):
    chain = tr.chunk("FXCHAIN")
    out, envs = [], {}
    if chain is None:
        return out, envs
    chain_on = tr.get("FX", cast=int, default=1) != 0
    bypass, last = None, None
    for c in chain.children:
        if isinstance(c, rpp.Line):
            if c.key == "BYPASS":
                bypass = c
            elif c.key == "PRESETNAME" and last is not None:
                last.preset = c.tokens[1] if len(c.tokens) > 1 else ""
            continue
        if c.name in FX_TAGS:
            label = c.tokens[1] if len(c.tokens) > 1 else c.name
            kind = label.split(":", 1)[0] if ":" in label else c.name
            name = label.split(":", 1)[1].strip() if ":" in label else Path(label).stem
            off = bypass is not None and len(bypass.tokens) > 1 and bypass.tokens[1] == "1"
            offline = bypass is not None and len(bypass.tokens) > 2 and bypass.tokens[2] == "1"
            params = {}
            if c.name == "JS":     # JSFX keep their slider values as plain numbers on the first line
                first = next((x for x in c.children if isinstance(x, rpp.Line)), None)
                if first is not None:
                    params = {f"slider{i + 1}": float(t) for i, t in enumerate(first.tokens)
                              if t not in ("-", "") and _isnum(t)}
            last = Device(name=name, kind=kind, on=chain_on and not off and not offline, params=params, native=c)
            out.append(last)
            bypass = None
        elif c.name == "PARMENV" and last is not None:
            pts, on = _envelope(c)
            idx = c.tokens[1].split(":")[0] if len(c.tokens) > 1 else "?"
            if on:
                envs[f"{last.name}/param {idx}"] = pts
    return out, envs


def _isnum(t):
    try:
        float(t)
        return True
    except ValueError:
        return False


def read(path):
    path = Path(path).expanduser().resolve()
    root = rpp.load(path)
    proj_dir = path.parent
    rec = root.get("RECORD_PATH", default="") or ""
    tempo_ln = root.line("TEMPO")
    tempo = num(tempo_ln.tokens[1], 120.0) if tempo_ln is not None else 120.0
    bpb = int(num(tempo_ln.tokens[2], 4)) if tempo_ln is not None and len(tempo_ln.tokens) > 2 else 4
    sr = root.get("SAMPLERATE", cast=int, default=44100) or 44100
    tmap = root.chunk("TEMPOENVEX")
    tchanges = len(tmap.lines("PT")) if tmap is not None else 0
    proj = Project(path=path, daw="reaper", tempo=tempo, beats_per_bar=bpb, sample_rate=sr,
                   tempo_changes=tchanges, native=root)
    proj.warnings = []
    stack = []
    for i, tr in enumerate(root.chunks("TRACK")):
        name = tr.get("NAME", default="") or f"Track {i + 1}"
        vp = tr.line("VOLPAN")
        ms = tr.line("MUTESOLO")
        bus = tr.line("ISBUS")
        folder = bus is not None and len(bus.tokens) > 1 and bus.tokens[1] == "1"
        delta = int(num(bus.tokens[2])) if bus is not None and len(bus.tokens) > 2 else 0
        clips = [_clip(it, proj_dir, rec, proj.warnings, name) for it in tr.chunks("ITEM")]
        kinds = {c.kind for c in clips}
        kind = "folder" if folder else ("midi" if kinds and kinds <= {"midi", "empty"} else "audio")
        devices, envs = _devices(tr)
        fader_envs = set()
        for ch in tr.chunks():
            if ch.name in ENV_NAMES or ch.name.startswith("AUXVOLENV"):
                pts, on = _envelope(ch)
                if on and pts:
                    lab = ENV_NAMES.get(ch.name, "Send volume")
                    envs[lab] = pts
                    if ch.get("VOLTYPE", cast=int, default=0) == 1:
                        fader_envs.add(lab)
        t = Track(name=name, index=i, kind=kind, clips=clips, devices=devices, envelopes=envs,
                  volume=num(vp.tokens[1], 1.0) if vp is not None and len(vp.tokens) > 1 else 1.0,
                  pan=num(vp.tokens[2]) if vp is not None and len(vp.tokens) > 2 else 0.0,
                  muted=ms is not None and len(ms.tokens) > 1 and ms.tokens[1] == "1",
                  solo=ms is not None and len(ms.tokens) > 2 and ms.tokens[2] not in ("0", ""),
                  polarity=tr.get("IPHASE", cast=int, default=0) == 1,
                  parent=stack[-1] if stack else None, native=tr)
        t.fader_envelopes = fader_envs           # envelopes REAPER interpolates in fader position (VOLTYPE 1)
        proj.tracks.append(t)
        if folder:
            stack.append(t)
        elif delta < 0:
            for _ in range(-delta):
                if stack:
                    stack.pop()
    if tchanges > 1:
        proj.warnings.append(f"the project has a tempo map ({tchanges} points): bar numbers assume {tempo:g} BPM")
    return proj
