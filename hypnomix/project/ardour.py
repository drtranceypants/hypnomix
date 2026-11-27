"""Read an Ardour session (.ardour, Ardour 3 to 9) into the shared model (`model.Project`).

An Ardour session is a folder; the .ardour file in it is XML. What is read, and from where:

  session   Session sample-rate and version; TempoMap (first tempo and meter, number of tempo points,
            superclocks-per-second); VCAManager (VCA faders are reported, not applied)
  sources   Sources/Source: id -> file name (audio in interchange/<session>/audiofiles, MIDI in .../midifiles)
  tracks    Routes/Route in PresentationInfo order: name, kind (AudioTrack, MidiTrack, AudioBus, MasterOut),
            Amp gaincontrol (fader) x trim, Pannable pan-azimuth (0 left .. 1 right), mute (Controllable or
            MuteMaster), solo (self-solo), polarity (phase-invert bits), plug-in Processors (lv2, ladspa, VST,
            VST3, AU, Lua: name, active, readable parameters, preset label), automation lists that play
  routing   a track whose outputs all go to one bus sits in that bus (`parent`); a bus fed only by aux sends
            is a "return"; a plug-in's sidechain input (its Processor type="sidechain" IO) is traced through the
            port connections to the tracks that key it (a send's output, or a route's own output) -> the
            Device's `sidechain` (track names) and `sidechain_tap` (pre_fader: after the source's plug-ins)
  groups    RouteGroups/RouteGroup: name, members (`routes` ids), the subgroup bus, what the members share
            (gain, mute, solo, ...), folded (hidden) -> `Project.groups` and each member's `group`
  regions   the track's playlist (audio-playlist / midi-playlist, or Diskstream playlist before Ardour 6):
            each Region's position, length and source offset, scale-amplitude, gain Envelope (when active),
            FadeIn / FadeOut curves (when active), muted, opaque and layering-index (upper opaque regions
            cover the ones below, as Ardour plays them), every channel's source
  takes     the track's other playlists named "<track>.take N" (orig-track-id = the route; HypnoMix Studio records
            each pass into one and comps from them with comp_range): `Track.take_lanes`, in take order, with
            their regions read like the playlist's. They are not heard; the active playlist is the comp

Times: Ardour 7+ writes "a<superclock>" (audio time) or "b<ticks>" (music time, 1920 per beat) and
"<length>@<position>" for lengths; older sessions write samples. Both become seconds here; music time
goes through the tempo map (constant tempos and ramps exactly, as Ardour plays them: `Clock`).
"""
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from hypnomix.project.model import Clip, Device, Group, Project, Take, TakeLane, Track
from hypnomix.project.model import quarters_per_bar as QB

TICKS = 1920
PLUGIN_TYPES = {"lv2": "LV2", "ladspa": "LADSPA", "windows-vst": "VST", "lxvst": "VST", "mac-vst": "VST",
                "vst3": "VST3", "audiounit": "AU", "luaproc": "Lua"}
AUTOMATION = {"gain": "Volume", "trim": "Trim Volume", "pan-azimuth": "Pan", "pan-width": "Width", "mute": "Mute"}


def yes(v):
    return str(v).strip().lower() in ("1", "yes", "true")


def num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def session_version(root):
    """'7003' -> 7003; '3.0.0' -> 3000; '2.0.0' -> 2000."""
    v = root.get("version", "0")
    if v.isdigit():
        return int(v)
    m = re.match(r"(\d+)\.(\d+)", v)
    return int(m.group(1)) * 1000 + int(m.group(2)) if m else 0


class Clock:
    """Ardour time strings -> seconds, through the session's tempo map: constant tempos, and ramps exactly as Ardour
    plays them (the tempo changes linearly per quarter note from a point's tempo to its end tempo at the next point,
    so the time into a ramp is a logarithm: t(b) = 60 / (T0 k) * ln(1 + k b), k = (T1 - T0) / (Q T0) per quarter,
    which is Ardour's own omega times the superclocks per quarter note at the ramp's start)."""

    def __init__(self, sr, scps=282240000, tempos=None):
        self.sr, self.scps = sr, scps
        # (quarters, seconds, quarters per minute, k: the ramp per quarter, 0 for a constant tempo)
        self.tempos = [tuple(t) + (0.0,) * (4 - len(t)) for t in (tempos or [(0.0, 0.0, 120.0)])]

    def _seg(self, i, key):
        seg = self.tempos[0]
        for t in self.tempos:
            if t[i] <= key:
                seg = t
        return seg

    def beats_to_s(self, q):
        q0, s0, qpm, k = self._seg(0, q)
        dq = q - q0
        if k and 1 + k * dq > 0:
            return s0 + 60.0 / (qpm * k) * math.log1p(k * dq)
        return s0 + dq * 60.0 / qpm

    def s_to_beats(self, s):
        q0, s0, qpm, k = self._seg(1, s)
        ds = s - s0
        if k:
            return q0 + math.expm1(ds * qpm * k / 60.0) / k
        return q0 + ds * qpm / 60.0

    def qpm_at(self, q):
        """The tempo (quarters per minute) at a position in quarters."""
        q0, _, qpm, k = self._seg(0, q)
        return qpm * (1 + k * (q - q0))

    def pos(self, v):
        """A position string -> seconds."""
        v = (v or "").strip()
        if not v:
            return 0.0
        if v[0] == "a":
            return int(v[1:]) / self.scps
        if v[0] == "b":
            return self.beats_to_s(int(v[1:]) / TICKS)
        return num(v) / self.sr                         # samples (before Ardour 7)

    def cnt(self, v, at=None):
        """A length string -> (length seconds, position seconds). '<dist>@<pos>' carries its position."""
        v = (v or "").strip()
        if "@" in v:
            d, p = v.split("@", 1)
            start = self.pos(p)
        else:
            d, start = v, (at or 0.0)
        if d and d[0] == "b":
            q = self.s_to_beats(start)
            return self.beats_to_s(q + int(d[1:]) / TICKS) - start, start
        return self.pos(d), start

    def event_time(self, v, origin=0.0):
        """An automation event time -> seconds. Music-time events are beats from the session start."""
        v = v.strip()
        if v and v[0] == "b":
            return self.beats_to_s(int(v[1:]) / TICKS) - origin
        return self.pos(v)


def tempo_map(root, sr, version, warn):
    """-> (Clock, bpm, beats_per_bar, tempo points)."""
    tm = root.find("TempoMap")
    if tm is None:
        return Clock(sr), 120.0, 4, 0
    scps = int(num(tm.get("superclocks-per-second"), 282240000)) or 282240000
    if version >= 7000:
        raw = []
        for t in tm.iter("Tempo"):
            nt = num(t.get("note-type"), 4.0) or 4.0
            qpm = num(t.get("npm"), 120.0) * 4.0 / nt
            end = num(t.get("enpm"), 0.0) * 4.0 / nt
            q = t.get("quarters", "0:0")
            b, _, k = q.partition(":")
            quarters = num(b) + num(k) / TICKS
            secs = int(num(t.get("sclock"), 0)) / scps
            ramped = t.get("type") == "Ramped" or (end > 0 and abs(end - qpm) > 1e-6)
            cont = str(t.get("continuing") or "").strip().lower() in ("1", "yes", "true", "y")
            raw.append((quarters, secs, qpm if qpm > 0 else 120.0, end if end > 0 else qpm, ramped, num(t.get("omega"), 0.0), cont))
        raw.sort()
        tempos = []
        for i, (quarters, secs, qpm, end, ramped, omega, cont) in enumerate(raw):
            k = 0.0
            if ramped and cont and i + 1 < len(raw):
                end = raw[i + 1][2]                          # a continuing ramp ends at the next point's tempo
            if ramped and i + 1 < len(raw):
                span = raw[i + 1][0] - quarters
                if span > 0:
                    k = (end - qpm) / (span * qpm)
                elif omega:
                    k = omega * scps * 60.0 / qpm            # Ardour's omega x superclocks per quarter at the start
            tempos.append((quarters, secs, qpm, k))
        meters_ = list(tm.iter("Meter"))
    else:
        tempos = []
        first = tm.find("Tempo")
        nt = num(first.get("note-type"), 4.0) if first is not None else 4.0
        bpm = num(first.get("beats-per-minute"), 120.0) if first is not None else 120.0
        tempos.append((0.0, 0.0, bpm * 4.0 / (nt or 4.0)))
        n = len(tm.findall("Tempo"))
        if n > 1:
            warn.append(f"the session has {n} tempos; music-time positions use the first ({bpm:g} BPM)")
        meters_ = tm.findall("Meter")
    clock = Clock(sr, scps, tempos or None)
    sig = meter_list(meters_)
    if len({m for m in sig}) > 1:
        warn.append(f"the session has meter changes ({', '.join(f'{a:g}/{b:g}' for a, b in dict.fromkeys(sig))}): bar "
                    f"numbers assume the first, {sig[0][0]:g}/{sig[0][1]:g}")
    return clock, clock.tempos[0][2], QB(*sig[0]), len(tempos)


def meter_list(meters_):
    """Meter elements -> [(divisions per bar, note value)] in order (4/4 when there is none)."""
    out = [(num(m.get("divisions-per-bar"), 4) or 4, num(m.get("note-value"), 4) or 4) for m in meters_]
    return out or [(4, 4)]


def meters(root, version):
    tm = root.find("TempoMap")
    if tm is None:
        return [(4, 4)]
    return meter_list(list(tm.iter("Meter")) if version >= 7000 else tm.findall("Meter"))


# ---------------------------------------------------------------- sources
def audio_dirs(session_dir):
    inter = session_dir / "interchange"
    dirs = [d / "audiofiles" for d in inter.iterdir()] if inter.is_dir() else []
    return dirs + [session_dir / "sounds", session_dir]


def resolve(name, origin, session_dir, dirs):
    if not name:
        return None
    for cand in (name, origin):
        if cand and Path(cand).is_absolute() and Path(cand).exists():
            return Path(cand)
    for d in dirs:
        if (d / name).exists():
            return d / name
    hits = list(session_dir.rglob(Path(name).name)) if session_dir.exists() else []
    if hits:
        return hits[0]
    return Path(name) if Path(name).is_absolute() else (dirs[0] / name if dirs else session_dir / name)


def sources(root, session_dir):
    dirs = audio_dirs(session_dir)
    out = {}
    for s in root.iter("Source"):
        sid = s.get("id")
        if sid is None or sid in out:
            continue
        typ = s.get("type", "audio")
        path = resolve(s.get("name", ""), s.get("origin", ""), session_dir, dirs) if typ == "audio" else None
        out[sid] = (typ, path, s.get("name", ""))
    return out


# ---------------------------------------------------------------- regions
def events(al, clock, origin=0.0):
    """<AutomationList> -> [(seconds, value)] (times relative to whatever the list is relative to)."""
    ev = al.find("events") if al is not None else None
    if ev is None or not (ev.text or "").strip():
        return []
    pts = []
    for line in ev.text.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            pts.append((clock.event_time(parts[0], origin), num(parts[1], 0.0)))
    return pts


def _fade(rg, tag, clock, active, sr):
    """-> (length seconds, curve [(fraction, gain)] or None). A default fade is Ardour's 64-sample one."""
    if not active:
        return 0.0, None
    f = rg.find(tag)
    if f is None or yes(f.get("default")) or f.find("AutomationList") is None:
        return 64.0 / sr, None
    pts = events(f.find("AutomationList"), clock)
    if len(pts) < 2 or pts[-1][0] <= 0:
        return 0.0, None
    L = pts[-1][0]
    return L, [(t / L, g) for t, g in pts]


def region(rg, clock, srcs, version, sr, warn, tname):
    if version >= 7000:
        length, start = clock.cnt(rg.get("length"))
    else:
        start = clock.pos(rg.get("position"))
        length = clock.pos(rg.get("length"))
    offset = clock.pos(rg.get("start", "0"))
    chans = []
    i = 0
    while rg.get(f"source-{i}") is not None:
        chans.append(srcs.get(rg.get(f"source-{i}"), ("audio", None, "")))
        i += 1
    kind = rg.get("type") or (chans[0][0] if chans else "audio")
    paths = [c[1] for c in chans if c[0] == "audio" and c[1] is not None]
    if kind == "audio" and not paths:
        kind = "empty"
    take = Take(name=rg.get("name", ""), path=paths[0] if paths else None, offset=offset,
                gain=num(rg.get("scale-amplitude"), 1.0), kind=kind, extra_paths=paths[1:], native=rg)
    audio = kind == "audio"
    fi, fic = _fade(rg, "FadeIn", clock, audio and yes(rg.get("fade-in-active", "1")), sr)
    fo, foc = _fade(rg, "FadeOut", clock, audio and yes(rg.get("fade-out-active", "1")), sr)
    env = None
    if yes(rg.get("envelope-active", "0")):
        e = rg.find("Envelope")
        if e is not None and not yes(e.get("default")):
            env = events(e.find("AutomationList"), clock) or None
    # a stretched region (stretch != 1) already plays a new, stretched file: nothing to follow here
    return Clip(name=rg.get("name", ""), start=start, length=length, takes=[take], gain=1.0, fade_in=fi,
                fade_out=fo, fade_in_curve=fic, fade_out_curve=foc, envelope=env, muted=yes(rg.get("muted", "0")),
                opaque=yes(rg.get("opaque", "1")), layer=int(num(rg.get("layering-index"), 0)), native=rg)


# ---------------------------------------------------------------- routes
def controllable(node, name):
    return next((c for c in node.findall("Controllable") if c.get("name") == name), None)


def port_owners(rts):
    """Every output port in the session -> (route name, "send" | "direct", tap, gain, on). A send's tap is "pre_fader"
    when it sits before the route's fader (after its plug-ins: what Live calls Post FX), else "post_fader"; `on` is
    False for a switched-off send (it carries nothing)."""
    owners = {}
    for rt in rts:
        name = rt.get("name", "")
        for io in rt.findall("IO"):
            if io.get("direction") == "Output":
                for p in io.findall("Port"):
                    owners[p.get("name")] = (name, "direct", "post_fader", 1.0, True)
        after_amp = False
        for pr in rt.findall("Processor"):
            if pr.get("type") == "amp":
                after_amp = True
            if pr.get("type") == "send":
                gc = next((c for c in pr.iter("Controllable") if c.get("name") == "gaincontrol"), None)
                gain = num(gc.get("value"), 1.0) if gc is not None else 1.0
                for io in pr.findall("IO"):
                    if io.get("direction") == "Output":
                        for p in io.findall("Port"):
                            owners[p.get("name")] = (name, "send", "post_fader" if after_amp else "pre_fader", gain,
                                                     yes(pr.get("active", "1")))
    return owners


def sidechain_sources(p, owners, off=None):
    """A plug-in Processor's sidechain feeds -> [(track name, tap, send gain)], one per feeding track. A switched-off
    send feeds nothing: its track's name goes into `off` instead (when a list is given)."""
    feeds = []
    for sc in p.findall("Processor"):
        if sc.get("type") != "sidechain":
            continue
        for c in sc.iter("Connection"):
            o = owners.get(c.get("other", ""))
            if not o:
                continue
            if len(o) > 4 and not o[4]:
                if off is not None and o[0] not in off:
                    off.append(o[0])
                continue
            if o[0] not in [f[0] for f in feeds]:
                feeds.append((o[0], o[2], o[3]))
    if off is not None:
        off[:] = [n for n in off if n not in [f[0] for f in feeds]]
    return feeds


def plugin_devices(rt, owners=None):
    out = []
    for p in rt.findall("Processor"):
        kind = PLUGIN_TYPES.get(p.get("type", ""))
        if kind is None:
            continue
        params = {}
        for c in p.findall("Controllable"):
            if c.get("parameter") is not None and "NotAutomatable" not in c.get("flags", "") and c.get("value"):
                params[c.get("name")] = num(c.get("value"))
        preset = ""
        for sub in p:
            preset = sub.get("last-preset-label") or preset
        off = []
        feeds = sidechain_sources(p, owners or {}, off)
        out.append(Device(name=p.get("name", "?"), kind=kind, on=yes(p.get("active", "1")), preset=preset,
                          params=params, native=p, uid=p.get("unique-id", ""), sidechain=[f[0] for f in feeds],
                          sidechain_tap=feeds[0][1] if feeds else "", sidechain_feeds=feeds, sidechain_off=off))
    return out


def route_groups(root, proj):
    """RouteGroups -> [Group]; each member's `group` is set."""
    by_id = {t.route_id: t for t in proj.tracks if t.route_id}
    out = []
    rgs = root.find("RouteGroups")
    for g in (rgs.findall("RouteGroup") if rgs is not None else []):
        members = [by_id[i] for i in (g.get("routes") or "").split() if i in by_id]
        members.sort(key=lambda t: t.index)
        shares = {k: yes(g.get(k, "0")) for k in ("gain", "relative", "mute", "solo", "recenable", "select", "color")}
        grp = Group(name=g.get("name", ""), id=g.get("id", ""), bus=by_id.get(g.get("subgroup-bus", "")),
                    members=members, shares=shares, folded=yes(g.get("hidden", "0")), active=yes(g.get("active", "1")),
                    native=g)
        for t in members:
            t.group = grp.name
        out.append(grp)
    return out


def route_automation(rt, clock):
    """Automation lists that play (state other than Off) -> {label: [(seconds, value)]}."""
    envs = {}

    def take(al, owner=""):
        if al.get("state", "Off") == "Off":
            return
        pts = events(al, clock)
        if not pts:
            return
        aid = al.get("automation-id", "")
        if aid.startswith("parameter-") and owner is not None:
            pid = aid.split("-", 1)[1]
            pname = next((c.get("name") for c in owner.findall("Controllable") if c.get("parameter") == pid),
                         f"param {pid}")
            envs[f"{owner.get('name', '?')}/{pname}"] = pts
        elif aid in AUTOMATION:
            label = AUTOMATION[aid]
            if aid == "pan-azimuth":
                pts = [(t, 2 * v - 1) for t, v in pts]
            envs[label] = pts

    for auto in rt.findall("Automation"):
        for al in auto.findall("AutomationList"):
            take(al)
    pan = rt.find("Pannable")
    if pan is not None:
        for al in pan.iter("AutomationList"):
            take(al)
    for p in rt.findall("Processor"):
        for auto in p.findall("Automation"):
            for al in auto.findall("AutomationList"):
                take(al, p if p.get("type") in PLUGIN_TYPES else None)
    return envs


def route_kind(rt):
    pi = rt.find("PresentationInfo")
    flags = (pi.get("flags", "") if pi is not None else "") + "," + rt.get("flags", "")
    if "MasterOut" in flags:
        return "master"
    if "MonitorOut" in flags or "SurroundMaster" in flags:
        return None
    if "MidiTrack" in flags:
        return "midi"
    if "AudioTrack" in flags:
        return "audio"
    if "Bus" in flags:
        return "folder"
    # Ardour 3-5: no PresentationInfo; a track has a Diskstream or a playlist
    if rt.find("Diskstream") is not None or rt.get("audio-playlist") or rt.get("midi-playlist"):
        return "midi" if rt.get("default-type") == "midi" else "audio"
    return "folder"


def route_order(rt, i):
    pi = rt.find("PresentationInfo")
    if pi is not None and pi.get("order") is not None:
        return int(num(pi.get("order"), i))
    m = re.search(r"editor=(\d+)", rt.get("order-keys", ""))
    return int(m.group(1)) if m else i


def playlist_of(rt, by_id, by_name):
    for key in ("audio-playlist", "midi-playlist"):
        if rt.get(key) and rt.get(key) in by_id:
            return by_id[rt.get(key)]
    ds = rt.find("Diskstream")
    name = (ds.get("playlist") if ds is not None else None) or rt.get("playlist")
    return by_name.get(name) if name else None


TAKE_NAME = re.compile(r"\.take (\d{1,6})$")


def take_number(name):
    """'Lead Vocal.take 3' -> 3; None for any other playlist name."""
    m = TAKE_NAME.search(name or "")
    return int(m.group(1)) if m and int(m.group(1)) >= 1 and m.start() > 0 else None


def take_playlists(rt, active, pls):
    """The route's take playlists (not the one it plays), sorted by take number: [(number, Playlist)]."""
    rid = rt.get("id")
    out = []
    for p in pls:
        if p is active or rid is None or (p.get("orig-track-id") or p.get("orig-diskstream-id")) != rid:
            continue
        n = take_number(p.get("name"))
        if n is not None:
            out.append((n, p))
    return sorted(out, key=lambda x: x[0])


def outputs(rt):
    """Names of the routes this route's outputs feed (port names are 'Route/audio_in 1')."""
    names = set()
    for io in rt.findall("IO"):
        if io.get("direction") != "Output":
            continue
        for c in io.iter("Connection"):
            other = c.get("other", "")
            if "/" in other:
                names.add(other.rsplit("/", 1)[0])
    return names


def read(path):
    path = Path(path).expanduser().resolve()
    if path.is_dir():
        cand = path / f"{path.name}.ardour"
        found = [cand] if cand.exists() else sorted(path.glob("*.ardour"))
        if not found:
            raise SystemExit(f"{path.name}: no .ardour session file in this folder")
        path = found[0]
    root = ET.parse(path).getroot()
    if root.tag != "Session":
        raise SystemExit(f"{path.name}: not a HypnoMix Studio session")
    version = session_version(root)
    if version < 3000:
        raise SystemExit(f"{path.name}: a session in an old format (version 2) that is not read; save it in a newer session format first")
    sr = int(num(root.get("sample-rate"), 48000)) or 48000
    warn = []
    clock, bpm, bpb, tpoints = tempo_map(root, sr, version, warn)
    session_dir = path.parent
    srcs = sources(root, session_dir)
    pls = list(root.iter("Playlist"))
    by_id = {p.get("id"): p for p in pls}
    by_name = {p.get("name"): p for p in pls}

    sig = meters(root, version)
    proj = Project(path=path, daw="ardour", tempo=bpm, beats_per_bar=bpb, sample_rate=sr,
                   tempo_changes=tpoints, native=root, meter=sig[0], meter_changes=sum(1 for a, b in zip(sig, sig[1:]) if a != b))
    proj.warnings = warn
    routes = root.find("Routes")
    rts = list(routes) if routes is not None else []
    rts = sorted(enumerate(rts), key=lambda x: (route_kind(x[1]) == "master", route_order(x[1], x[0])))

    send_targets = {p.get("target") for p in root.iter("Processor") if p.get("type") == "intsend"}
    owners = port_owners([rt for _, rt in rts])
    made, outs = {}, {}
    for i, rt in rts:
        kind = route_kind(rt)
        if kind is None:
            continue
        name = rt.get("name") or f"Track {i + 1}"
        amp = next((p for p in rt.findall("Processor") if p.get("type") == "amp"), None)
        trim = next((p for p in rt.findall("Processor") if p.get("type") == "trim"), None)
        fader = num(controllable(amp, "gaincontrol").get("value"), 1.0) if amp is not None and \
            controllable(amp, "gaincontrol") is not None else 1.0
        tc = next((c for c in trim.findall("Controllable")), None) if trim is not None else None
        tgain = num(tc.get("value"), 1.0) if tc is not None else 1.0
        pan_c = rt.find("Pannable")
        az = controllable(pan_c, "pan-azimuth") if pan_c is not None else None
        pan = 2 * num(az.get("value"), 0.5) - 1 if az is not None else 0.0
        mc = controllable(rt, "mute")
        mm = rt.find("MuteMaster")
        muted = (mc is not None and num(mc.get("value")) > 0.5) or (mm is not None and yes(mm.get("muted")))
        sc = controllable(rt, "solo")
        solo = yes(rt.get("self-solo", "0")) or (sc is not None and (yes(sc.get("self-solo", "0"))))
        ph = controllable(rt, "phase")
        bits = (ph.get("phase-invert") if ph is not None else None) or rt.get("phase-invert", "") or ""
        bits = bits if set(bits) <= {"0", "1"} else ""
        polarity = bool(bits) and set(bits) == {"1"}
        if bits and "1" in bits and not polarity:
            warn.append(f"{name}: polarity is flipped on some channels only ({bits})")
        if kind == "folder" and rt.get("id") in send_targets:
            kind = "return"
        clips = []
        pl = playlist_of(rt, by_id, by_name) if kind in ("audio", "midi") else None
        if pl is not None:
            clips = [region(rg, clock, srcs, version, sr, warn, name) for rg in pl.findall("Region")]
            clips.sort(key=lambda c: c.start)
        lanes = []
        if kind == "audio":
            for n, tp in take_playlists(rt, pl, pls):
                tclips = sorted((region(rg, clock, srcs, version, sr, warn, name) for rg in tp.findall("Region")),
                                key=lambda c: c.start)
                lanes.append(TakeLane(name=tp.get("name", ""), number=n, clips=tclips, native=tp))
        t = Track(name=name, index=len(proj.tracks), kind=kind, clips=clips, devices=plugin_devices(rt, owners),
                  envelopes=route_automation(rt, clock), volume=fader * tgain, pan=pan, muted=muted, solo=solo,
                  polarity=polarity, take_lanes=lanes, native=rt, route_id=rt.get("id", ""), active=yes(rt.get("active", "1")))
        if abs(tgain - 1.0) > 1e-6:
            t.trim = tgain
        proj.tracks.append(t)
        made[name] = t
        outs[name] = outputs(rt)
    for t in proj.tracks:
        if t.kind == "master":
            continue
        dest = {n for n in outs.get(t.name, ()) if n in made}
        if len(dest) == 1:
            d = made[next(iter(dest))]
            if d.kind in ("folder", "return") and d is not t:
                t.parent = d
    proj.groups = route_groups(root, proj)
    vcas = [v for v in root.iter("VCA")]
    if vcas:
        warn.append(f"{len(vcas)} VCA fader(s): their gain is not included in levels here")
    if tpoints > 1:
        warn.append(f"the session has a tempo map ({tpoints} points): bar numbers assume {bpm:g} BPM")
    return proj
