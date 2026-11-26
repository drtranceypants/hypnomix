#!/usr/bin/env python3
"""Learn my style: study every Ableton set you have, describe how you mix, and say where you could improve.

A first-run scan of your whole library. It reads the sets themselves (gzipped XML) and the finished bounces
next to them. Nothing is rendered, nothing is changed, nothing leaves the computer, and Live is never opened.

Which sets
  The folders you give, or by default your Ableton folders (~/Music/Ableton, ~/Documents) plus every set
  Spotlight knows about. Skipped, with the reason reported: Live's own content (Factory Packs, Core Library,
  lessons and demo sets), templates, `Backup` folders, hypnomix output, and older copies: per project folder
  only the newest set counts (older version-named copies, and an older "Song v1 Project" next to a newer
  "Song v2 Project", are listed as skipped). Each set is read once and cached by path, size and time in
  ~/.hypnomix/cache/library/, so a re-run reads only the sets that changed. Reading runs in parallel.

What it learns per set (on top of what `hypnomix taste` reads: levels against the lead, pans, sends, chains)
  devices     Live's own devices by kind of track: Compressor / Glue (ratio, attack, release, threshold, makeup,
              knee, sidechain), EQ Eight (low cut, boosts and cuts by region), Limiter and the Main chain
              (ceiling, gain), Saturator, Utility (width, bass mono), Reverb and Delay on returns (decay,
              predelay, delay time against the tempo)
  plug-ins    third-party plug-ins per kind of track, by name and count only (their settings are an opaque
              blob in the set: hypnomix cannot read them and never tries)
  sounds      instruments, Drum Racks, the samples Simpler / Sampler play, the Live packs the set uses
  genre       a rough GUESS from tempo and instruments, saved only as a question for you to confirm
  bounces     the newest exported mix in or next to the project folder (named like the set, or with mix /
              master / final / bounce in its name): loudness, true peak, crest, tonal balance in 8 bands

Then two parts per topic: YOUR STYLE (median and range across sets; a narrow range is a standard tools keep, a
wide one a taste call they ask about, the same rule as `taste`) and WHERE YOU COULD IMPROVE (measured, gentle,
advice only, each with its evidence: which sets and the numbers). Writes LIBRARY.md and
~/.hypnomix/library.json (HYPNOMIX_HOME to change), which other tools read later.

Usage:
  hypnomix taste --library [DIR …] [--no-bounces] [--jobs N] [--refresh] [--no-spotlight]
                                [--max-bounce-seconds N] [--out DIR]
  hypnomix taste --library --genre "PROJECT=genre" [...]     confirm a genre guess (saved in your preferences)
  python -m hypnomix.workflow.library [DIR …] [same options]
"""
import argparse, collections, concurrent.futures as cf, functools, gzip, hashlib, json, math, os, re, subprocess, sys, time
from hypnomix.core.gz import read_gz
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from hypnomix.core.paths import HOME, out_at
from hypnomix.workflow import taste as T

VERSION = 4                                   # bump when what is read per set changes: old cache entries are re-read
CACHE = HOME / "cache" / "library"
LIBRARY = HOME / "library.json"
DEFAULT_DIRS = ["~/Music/Ableton", "~/Documents"]
AUDIO = (".wav", ".aif", ".aiff", ".flac", ".mp3", ".m4a")
v = T.v

# ---------------------------------------------------------------------------------------------- discovery
_VERSIONY = re.compile(r"(\[[^\]]*\]|\([^)]*\)|\b(v|ver|version|take|rev)\s*\d+[\w.]*|\b(final|mix|master|copy|edit|new|old|"
                       r"fixed|review|recovered|autosave|bounce|demo|draft|alt|wip)\b|\d{4}-\d\d-\d\d|\d{6,}|\s\d+$)", re.I)


def base_name(name):
    """A set or project name without its version words: 'Song v3 (final review 2)' -> 'song'."""
    n = Path(name).stem if name.lower().endswith((".als",) + AUDIO) else name
    n = re.sub(r"\s+project$", "", n.strip(), flags=re.I)
    prev = None
    while prev != n:
        prev, n = n, _VERSIONY.sub(" ", n)
        n = re.sub(r"[\s_\-.]+", " ", n).strip()
    return n.lower() or Path(name).stem.lower()


PACKY = re.compile(r"\b(presets?|drum ?kits?|sample ?pack|construction ?kit|demo ?als|demo ?set|free ?project)\b", re.I)


TESTY = re.compile(r"(\btests?\b|mastering ?chain|\bchain ?test|weirdcomp|\bsandbox\b)", re.I)


def skip_reason(p):
    """Why a set is not one of yours to learn from, or None."""
    parts = Path(p).parts
    low = [x.lower() for x in parts]
    name = Path(p).name
    if name.startswith("._"):
        return "a macOS resource file, not a set"
    if any(x.endswith(".app") for x in low) or "factory packs" in low or "core library" in low:
        return "Live's own content (Factory Packs / Core Library)"
    if any("lesson" in x for x in low) or any(x in ("demo sets", "demo songs") for x in low):
        return "Live's lessons / demo sets"
    if "backup" in low:
        return "a Backup folder (Live's automatic copies)"
    if any(x in ("templates", "defaults") for x in low) or "template" in name.lower() or \
            any("template" in x for x in low[-3:-1]):
        return "a template, not a song"
    if any(x in (".trash", "hypnomix-out") for x in low) or "(BROKEN" in name:
        return "hypnomix output or the Trash"
    if TESTY.search(Path(p).stem) or TESTY.search(project_dir(p).name) or any(x in ("_tests", "tests", "test") for x in low):
        return "a test or device-chain set (by its name), not a song"
    if Path(p).stem.lower() == "default":
        return "a template, not a song"
    if PACKY.search(Path(p).stem) or PACKY.search(project_dir(p).name):
        return "a downloaded pack, preset or demo set (by its name), not your song"
    try:
        if any(x.is_dir() and (x.name.endswith(" Lessons") or x.name == "Presets") for x in project_dir(p).iterdir()):
            return "a downloaded pack / preset project (it has Lessons or Presets folders), not your song"
    except OSError:
        pass
    return None


def project_dir(p):
    """The Live project folder a set belongs to (the folder with 'Ableton Project Info'), else its own folder."""
    d = Path(p).parent
    for x in [d, *list(d.parents)[:2]]:
        if (x / "Ableton Project Info").is_dir():
            return x
    return d


def find_sets(dirs=None, spotlight=True):
    """Every .als under the folders (and from Spotlight when no folders are given)."""
    found = set()
    roots = [Path(d).expanduser() for d in (dirs or DEFAULT_DIRS)]
    for r in roots:
        if r.is_file() and r.suffix == ".als":
            found.add(str(r.resolve())); continue
        if not r.is_dir():
            continue
        for dp, dn, fn in os.walk(r):
            dn[:] = [x for x in dn if not x.startswith(".") and x != "Backup" and not x.endswith(".app")]
            found.update(str(Path(dp, f).resolve()) for f in fn if f.endswith(".als") and not f.startswith("._"))
    if spotlight and not dirs:
        try:
            out = subprocess.run(["mdfind", "kMDItemFSName == '*.als'"], capture_output=True, text=True, timeout=60).stdout
            found.update(str(Path(x).resolve()) for x in out.splitlines() if x.endswith(".als") and Path(x).exists())
        except (OSError, subprocess.SubprocessError):
            pass
    return sorted(found)


def song_key(p):
    """Which song a set is: its name without version words. 'Untitled' and 'Default' sets stay per project."""
    b = base_name(Path(p).name)
    if b in ("untitled", "default", "new", "") or len(b) < 2:          # an untitled set is a version of its project's song
        pb = base_name(project_dir(p).name)
        return ("song", pb) if pb not in ("untitled", "default", "new", "") and len(pb) > 1 else ("project", str(project_dir(p)), b)
    return ("song", b)


def dedupe(paths, mtime=lambda p: os.stat(p).st_mtime):
    """(kept, skipped[(path, reason)]): the newest set of each song. Older sets in the same project folder and older
    copies of the same song in other folders ('Song Project', 'Song v2 Project', a copy elsewhere) are skipped."""
    kept, skipped = [], []
    for p in paths:
        r = skip_reason(p)
        (skipped.append((p, r)) if r else kept.append(p))
    groups = collections.defaultdict(list)
    for p in kept:
        groups[song_key(p)].append(p)
    out = []
    for ps in groups.values():
        ps.sort(key=mtime, reverse=True)
        out.append(ps[0])
        for p in ps[1:]:
            same = project_dir(p) == project_dir(ps[0])
            skipped.append((p, f"older set in the same project (newest: {Path(ps[0]).name})" if same else
                            f"older copy of the same song in another folder (newest: {project_dir(ps[0]).name}/{Path(ps[0]).name})"))
    return sorted(out), skipped


def key_of(p):
    st = os.stat(p)
    return hashlib.sha1(f"{VERSION}|{Path(p).resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:20]


# ---------------------------------------------------------------------------------------------- roles
COARSE = {"lead_vocal": "Lead Vocal", "backing_vocal": "Harmony", "kick": "Drums", "snare": "Drums", "hats": "Drums",
          "toms": "Drums", "overheads": "Drums", "drums": "Drums", "bass": "Bass", "guitar": "Keys", "keys": "Keys",
          "synth": "Synth", "pad": "Pad", "strings": "Strings", "brass": "Strings", "fx": "FX"}
INSTR = {"OriginalSimpler": "Simpler", "MultiSampler": "Sampler", "InstrumentVector": "Wavetable", "Operator": "Operator",
         "UltraAnalog": "Analog", "Collision": "Collision", "StringStudio": "Tension", "LoungeLizard": "Electric",
         "Drift": "Drift", "InstrumentMeld": "Meld", "InstrumentImpulse": "Impulse", "DrumGroupDevice": "Drum Rack",
         "InstrumentGroupDevice": "Instrument Rack", "MxDeviceInstrument": "Max instrument"}
PLUGINS = ("AuPluginDevice", "PluginDevice", "VstPluginDevice", "Vst3PluginDevice")
RACKS = ("AudioEffectGroupDevice", "InstrumentGroupDevice", "MidiEffectGroupDevice", "DrumGroupDevice")


def plugin_name(d):
    for p in ("./PluginDesc/AuPluginInfo/Name", "./PluginDesc/Vst3PluginInfo/Name", "./PluginDesc/VstPluginInfo/PlugName"):
        if d.find(p) is not None and v(d, p):
            return v(d, p)
    return "unknown plug-in"


def walk(devs):
    """Every device in a chain, inside racks too (each rack's branches in order)."""
    for d in (list(devs) if devs is not None else []):
        yield d
        if d.tag in RACKS:
            for br in d.findall("./Branches/*"):
                for p in ("./DeviceChain/MidiToAudioDeviceChain/Devices", "./DeviceChain/AudioToAudioDeviceChain/Devices",
                          "./DeviceChain/MidiToMidiDeviceChain/Devices"):
                    yield from walk(br.find(p))


def names_index():
    """What `hypnomix voices --learn` / `name` already labelled, by song: {song_key: {track name: (label, conf)}}.
    Track names a later version of the song still uses get the same label (read-only)."""
    idx = collections.defaultdict(dict)
    for f in (T.CACHE / "names").glob("*/names.json"):
        try:
            j = json.loads(f.read_text())
            k = song_key(j["set"])
        except (ValueError, KeyError, OSError, TypeError):
            continue
        for r in j.get("tracks", []):
            lab = (str(r.get("final") or r.get("label") or ""), float(r.get("confidence") or 0))
            for n in {r.get("old"), r.get("new")} - {None, ""}:
                idx[str(k)].setdefault(n, lab)
    return dict(idx)


def role_of(t, known=None, group_name=""):
    """A coarse role: the label `hypnomix name` gave this track in this song, else the track's name, its group's
    name (a track in a "Vocals" group is a vocal), then its instrument or samples. None = not known."""
    from hypnomix.engineer.roles import by_name
    nm = v(t, "./Name/EffectiveName") or ""
    if known and nm in known and T.role(*known[nm]):
        return T.role(*known[nm])
    r = by_name(nm)
    devs = list(walk(t.find("./DeviceChain/DeviceChain/Devices")))
    if r is None and re.search(r"\b(audio|track)\b", nm, re.I) and group_name:
        g = by_name(group_name)
        r = "backing_vocal" if g in ("lead_vocal", "backing_vocal") else g
    if r is None:
        hints = " ".join([plugin_name(d) for d in devs if d.tag in PLUGINS] + [v(d, "./UserName") or "" for d in devs]
                         + [Path(v(fr, "./Path") or v(fr, "./RelativePath") or "").stem
                            for d in devs if d.tag in ("OriginalSimpler", "MultiSampler") for fr in d.findall(".//SampleRef/FileRef")])
        r = by_name(hints) if hints.strip() else None
    if r is None and any(d.tag == "DrumGroupDevice" for d in devs):
        r = "drums"
    if r is None and t.tag == "MidiTrack":
        r = "synth"
    return T.role(COARSE.get(r, ""), 1.0) if r else None


# ---------------------------------------------------------------------------------------------- devices
def man(d, name, default=None):
    e = d.find(f"./{name}/Manual")
    if e is None or e.get("Value") is None:
        return default
    s = e.get("Value")
    if s in ("true", "false"):
        return s == "true"
    try:
        return float(s)
    except ValueError:
        return default


EQ_MODE = {0: "low cut 48", 1: "low cut 12", 2: "low shelf", 3: "bell", 4: "notch", 5: "high shelf", 6: "high cut 12",
           7: "high cut 48"}
REGIONS = [("sub", 0, 60), ("bass", 60, 250), ("low-mid", 250, 800), ("mid", 800, 2500), ("presence", 2500, 6000),
           ("air", 6000, 30000)]


def region(f):
    return next(n for n, lo, hi in REGIONS if lo <= f < hi)


def device_params(d, tempo):
    """{kind, …} for the stock devices the library learns from, else None."""
    from hypnomix.engineer import sidechain as SC
    on = man(d, "On", True)
    if d.tag in ("Compressor2", "GlueCompressor"):
        c = SC.read_glue(d) if d.tag == "GlueCompressor" else SC.read_compressor(d)
        c["ratio"] = min(float(c["ratio"]), 100.0)               # Live stores "inf" (limiting) as 3.4e38
        mk = man(d, "Makeup", 0.0) if d.tag == "GlueCompressor" else man(d, "Gain", 0.0)
        return dict(kind="glue" if d.tag == "GlueCompressor" else "compressor", on=on, ratio=round(c["ratio"], 2),
                    attack=round(c["attack"], 2), release=round(c["release"], 1), threshold=round(c["threshold_db"], 1),
                    makeup=round(mk, 1), knee=round(c.get("knee", 0), 1), sidechain=bool(c["sc_on"]),
                    auto_makeup=v(d, "./GainCompensation/Manual") == "true", dry_wet=round(c.get("dry_wet", 1.0), 2))
    if d.tag == "Eq8":
        bands = []
        for i in range(8):
            b = d.find(f"./Bands.{i}/ParameterA")
            if b is None or not man(b, "IsOn", False):
                continue
            mode = int(man(b, "Mode", 3))
            gain = man(b, "Gain", 0.0)
            if mode in (2, 3, 5) and abs(gain) < 0.25:
                continue                                          # a bell or shelf at 0 dB does nothing
            bands.append(dict(mode=EQ_MODE.get(mode, str(mode)), freq=round(man(b, "Freq", 1000.0), 1),
                              gain=round(gain, 1), q=round(man(b, "Q", 0.71), 2)))
        low = [b["freq"] for b in bands if b["mode"].startswith("low cut")]
        return dict(kind="eq", on=on, bands=bands, low_cut=min(low) if low else None)
    if d.tag == "Limiter":
        return dict(kind="limiter", on=on, ceiling=round(man(d, "Ceiling", 0.0), 2), gain=round(man(d, "Gain", 0.0), 2),
                    release=round(man(d, "Release", 300.0), 1), auto_release=bool(man(d, "AutoRelease", False)))
    if d.tag == "Saturator":
        return dict(kind="saturator", on=on, type=int(man(d, "Type", 0)), drive=round(man(d, "PreDrive", 0.0), 1),
                    output=round(man(d, "PostDrive", 0.0), 1), dry_wet=round(man(d, "DryWet", 1.0), 2))
    if d.tag == "StereoGain":
        g = man(d, "Gain", 1.0)
        return dict(kind="utility", on=on, width=round(man(d, "StereoWidth", 1.0), 2), mono=bool(man(d, "Mono", False)),
                    bass_mono=bool(man(d, "BassMono", False)), bass_mono_hz=round(man(d, "BassMonoFrequency", 120.0), 0),
                    gain_db=round(T.db(g), 1) if g and g > 0 else None)
    if d.tag == "Reverb":
        return dict(kind="reverb", on=on, decay_ms=round(man(d, "DecayTime", 1200.0), 0),
                    predelay_ms=round(man(d, "PreDelay", 2.5), 1), size=round(man(d, "RoomSize", 50.0), 1))
    if d.tag in ("Hybrid", "HybridReverb"):
        return dict(kind="reverb", on=on, decay_ms=None, predelay_ms=None, size=None)
    if d.tag in ("Delay", "Echo"):
        p = "DelayLine_" if d.tag == "Delay" else "Delay_"
        synced = bool(man(d, f"{p}SyncL", True))
        free_ms = None
        if not synced:
            t = man(d, f"{p}TimeL", None)
            free_ms = round(t * 1000, 1) if t is not None and t < 10 else t
        beat = 60000.0 / tempo if tempo else None
        return dict(kind="delay", on=on, device=d.tag, synced=synced, free_ms=free_ms,
                    beats=round(free_ms / beat, 3) if free_ms and beat else None,
                    feedback=round(man(d, "Feedback", 0.5), 2), dry_wet=round(man(d, "DryWet", 0.5), 2))
    return None


def lowest_midi_note(t):
    keys = [int(v(kt, "./MidiKey") or 0) for kt in t.iter("KeyTrack")
            if any(float(n.get("Velocity", 0)) > 1 for n in kt.iter("MidiNoteEvent"))]
    return min(keys) if keys else None


# ---------------------------------------------------------------------------------------------- one set
def read_set(path, known=None):
    """Everything the library learns from one set (no audio is read here). `known`: labels from names_index()."""
    path = Path(path)
    root = ET.fromstring(read_gz(path))
    ls = root.find("LiveSet")
    main = next((m for m in (ls.find("MainTrack"), ls.find("MasterTrack")) if m is not None), None)
    tempo = float(v(root, ".//Tempo/Manual") or 120)
    tracks = list(ls.find("Tracks"))
    out = dict(song=path.stem, path=str(path), project=str(project_dir(path)), live=root.get("Creator"),
               mtime=os.stat(path).st_mtime, tempo=round(tempo, 2), devices=[], plugins=[], instruments=[],
               samples=collections.Counter(), packs=collections.Counter(), roles=collections.Counter(),
               no_low_cut=[], bass_f0=None, tracks=0)
    labels, bass_keys = {}, []
    gname = {t.get("Id"): v(t, "./Name/EffectiveName") or "" for t in tracks if t.tag == "GroupTrack"}
    parent = {t.get("Id"): v(t, "./TrackGroupId") for t in tracks}
    role_id, members = {}, collections.defaultdict(set)
    for t in tracks:                                            # first pass: each track's role, and what each group carries
        if t.tag in ("AudioTrack", "MidiTrack"):
            role_id[t.get("Id")] = r = role_of(t, known, gname.get(v(t, "./TrackGroupId"), ""))
            g, seen = v(t, "./TrackGroupId"), set()
            while g in gname and g not in seen:
                members[g].add(r or "unknown"); seen.add(g); g = parent.get(g)
    for t in tracks:
        nm = v(t, "./Name/EffectiveName") or "?"
        playing = v(t, "./DeviceChain/Mixer/Speaker/Manual") != "false"
        if t.tag == "ReturnTrack":
            kinds = [d.tag for d in walk(t.find("./DeviceChain/DeviceChain/Devices"))]
            r = "return:delay" if any(k in ("Delay", "Echo", "FilterDelay", "PingPongDelay", "GrainDelay") for k in kinds) else \
                "return:reverb" if any(k in ("Reverb", "Hybrid", "HybridReverb") for k in kinds) or \
                re.search(r"verb|hall|room|plate|space", nm, re.I) else "return:other"
        elif t.tag == "GroupTrack":
            r = "group"
        else:
            r = role_id.get(t.get("Id"))
            if r:
                labels[nm] = ({"lead": "Lead Vocal", "harmony": "Harmony", "drums": "Drums", "bass": "Bass",
                               "keys/guitar/synth": "Keys", "strings/other": "Strings"}[r], 1.0)
            r = r or "unknown"
            if not playing:
                continue
            out["tracks"] += 1
            out["roles"][r] += 1
            if r == "bass" and t.tag == "MidiTrack":
                k = lowest_midi_note(t)
                if k is not None:
                    bass_keys.append(k)
        devs = list(walk(t.find("./DeviceChain/DeviceChain/Devices")))
        has_cut = False
        for d in devs:
            p = device_params(d, tempo)
            if p:
                p.update(role=r, track=nm)
                if t.tag == "GroupTrack":
                    p["carries"] = sorted(members.get(t.get("Id"), ()))
                out["devices"].append(p)
                has_cut |= p["kind"] == "eq" and p["on"] and p["low_cut"] is not None
            if d.tag in PLUGINS:
                out["plugins"].append(dict(role=r, name=plugin_name(d),
                                           instrument=v(d, "./PluginDesc/AuPluginInfo/ComponentType") == "1635085685"))
            if d.tag in INSTR:
                out["instruments"].append(dict(role=r, name=INSTR[d.tag]))
            if d.tag in ("OriginalSimpler", "MultiSampler", "InstrumentImpulse"):
                for fr in d.findall(".//SampleRef/FileRef"):
                    s = Path(v(fr, "./Path") or v(fr, "./RelativePath") or "").name
                    if s:
                        out["samples"][s] += 1
        if t.tag == "MidiTrack":                                  # a plug-in instrument: the first plug-in on a MIDI track
            first = next((d for d in devs if d.tag in PLUGINS or d.tag in INSTR), None)
            if first is not None and first.tag in PLUGINS:
                for pl in out["plugins"]:
                    if pl["role"] == r and pl["name"] == plugin_name(first):
                        pl["instrument"] = True
        if t.tag in ("AudioTrack", "MidiTrack") and r not in ("bass", "drums", "unknown") and not has_cut:
            out["no_low_cut"].append(dict(track=nm, role=r, eq=any(d.tag == "Eq8" for d in devs),
                                          plugins=sum(d.tag in PLUGINS for d in devs)))
    for d in walk(main.find("./DeviceChain/DeviceChain/Devices")) if main is not None else []:
        p = device_params(d, tempo)
        if p:
            p.update(role="main", track="Main")
            out["devices"].append(p)
        if d.tag in PLUGINS:
            out["plugins"].append(dict(role="main", name=plugin_name(d), instrument=False))
    for fr in root.iter("FileRef"):
        pk = v(fr, "./LivePackName")
        if pk:
            out["packs"][pk] += 1
    if bass_keys:
        out["bass_f0"] = round(440 * 2 ** ((min(bass_keys) - 69) / 12), 1)
    ends = [float(v(c, "./CurrentEnd") or 0) for t in tracks for c in t.findall("./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events/*")
            + t.findall("./DeviceChain/MainSequencer/ClipTimeable/ArrangerAutomation/Events/*")]
    out["arranged_s"] = round(max(ends, default=0) * 60 / tempo, 1)
    out["drum_racks"] = sum(1 for i in out["instruments"] if i["name"] == "Drum Rack")
    try:
        out["taste"] = T.song(path, labels=labels, require_lead=False, root=root)
    except Exception as e:                                         # an old or unusual set: keep the rest
        out["taste"] = dict(song=path.stem, skipped=f"levels and sends not read ({type(e).__name__})")
    out["genre_guess"] = guess_genre(out)
    out["samples"] = dict(out["samples"].most_common(40))
    out["packs"] = dict(out["packs"])
    out["roles"] = dict(out["roles"])
    return out


def guess_genre(s):
    """A rough guess with its reasons. Only ever shown as a question."""
    t, roles = s["tempo"], s["roles"]
    inst = {i["name"] for i in s["instruments"]}
    synthy = len(inst & {"Wavetable", "Operator", "Analog", "Drift", "Meld"}) + sum(p["instrument"] for p in s["plugins"])
    vocals = roles.get("lead", 0) + roles.get("harmony", 0)
    names = " ".join(p["name"] for p in s["plugins"]).lower() + " " + " ".join(s["samples"]).lower()
    drums = roles.get("drums", 0) > 0 or s.get("drum_racks", 0) > 0
    why = [f"{t:g} BPM", f"{vocals} vocal track(s)", f"{'drums' if drums else 'no drums'}",
           f"{synthy} synth instrument(s)"]
    if vocals >= 3 and synthy <= 2 and t < 100:
        g = "pop ballad / singer-songwriter (vocal-led)"
    elif drums and synthy and 118 <= t < 130:
        g = "house / dance"
    elif drums and synthy and 130 <= t < 150:
        g = "trance / techno" if "808" not in names else "trap / hip-hop"
    elif drums and 160 <= t <= 180 and synthy:
        g = "drum & bass"
    elif drums and ("808" in names or re.search(r"trap|hip ?hop", names)) and 60 <= t <= 160:
        g = "hip-hop / trap"
    elif drums and synthy and t < 118:
        g = "downtempo / electronic"
    elif vocals and not synthy and t < 95:
        g = "ballad / acoustic"
    elif vocals and roles.get("keys/guitar/synth", 0) and not synthy:
        g = "pop / rock / country (band)"
    elif not vocals and not drums:
        g = "ambient / cinematic"
    else:
        g = "pop"
    return dict(guess=g, why=", ".join(why), confirmed=False)


# ---------------------------------------------------------------------------------------------- bounces
WORDS = re.compile(r"\b(mix|master|mastered|final|bounce|export|print)\b", re.I)
NOT_A_MIX = re.compile(r"\b(before|discard|test|bad|preview|stem|stems|vocals?|a then b|solo|instrumental|acapella|section)\b", re.I)
ROUGH = re.compile(r"\b(review|unmastered|rough|draft|wip|scratch)\b", re.I)
BOUNCE_DIRS = ["~/Desktop", "~/Music", "~/Documents"]          # where Live's export dialog usually points


def find_bounce(set_path, extra_dirs=None):
    """The exported mix for this set, or None. Looked for in the project folder (named like the set or the project,
    or with mix / master / final / bounce in the name), next to the project folder, and in your usual export
    folders (Desktop, Music, Documents: top level only, the name must be the song's). Ranked: named exactly like
    the set, then final / master / mix in the name, then newest. Test renders ('before', 'test', 'stem', …) are not
    mixes."""
    pd = project_dir(set_path)
    song = base_name(Path(set_path).name)
    names = {song, base_name(pd.name)} - {"", "untitled", "default"}
    cands = []

    def ok(f):
        return f.lower().endswith(AUDIO) and not f.startswith("._") and not NOT_A_MIX.search(Path(f).stem)
    for dp, dn, fn in os.walk(pd):
        rel = Path(dp).relative_to(pd)
        dn[:] = [x for x in dn if x not in ("Samples", "Backup", "Ableton Project Info", "hypnomix-out") and not x.startswith(".")]
        if len(rel.parts) >= 2:
            dn[:] = []
        for f in fn:
            if ok(f) and (WORDS.search(Path(f).stem) or base_name(f) in names):
                cands.append(Path(dp, f))
    for d in [pd.parent] + [Path(x).expanduser() for x in (extra_dirs if extra_dirs is not None else BOUNCE_DIRS)]:
        try:
            for f in d.iterdir():
                if f.is_file() and ok(f.name) and base_name(f.name) in names:
                    cands.append(f)
        except OSError:
            pass
    cands = list({c.resolve(): c for c in cands if c.stat().st_size > 200_000}.values())
    if not cands:
        return None
    rank = lambda c: (c.stem.strip().lower() == Path(set_path).stem.strip().lower(), not ROUGH.search(c.stem),
                      bool(WORDS.search(c.stem)),
                      c.suffix.lower() != ".mp3", c.stat().st_mtime)
    return str(max(cands, key=rank))


BANDS8 = [("sub", 20, 60), ("bass", 60, 150), ("low-mid", 150, 400), ("mid", 400, 1000), ("upper-mid", 1000, 2500),
          ("presence", 2500, 5000), ("brilliance", 5000, 10000), ("air", 10000, 20000)]


def load_audio(path, max_s):
    import soundfile as sf
    try:
        info = sf.info(str(path))
        y, sr = sf.read(str(path), frames=int(min(info.frames, max_s * info.samplerate)), always_2d=True, dtype="float32")
        return y, sr
    except Exception:
        r = subprocess.run(["ffmpeg", "-v", "error", "-t", str(max_s), "-i", str(path), "-f", "f32le", "-ac", "2",
                            "-ar", "44100", "-"], capture_output=True, timeout=120)
        if r.returncode or not r.stdout:
            raise RuntimeError("could not decode")
        return np.frombuffer(r.stdout, dtype=np.float32).reshape(-1, 2), 44100


def measure_bounce(path, max_s=600, budget_s=90):
    """Loudness, true peak, crest, PLR and 8-band tonal balance; reads at most max_s seconds of audio and stops
    with 'timed out' when the work runs over budget_s seconds."""
    import pyloudnorm as pyln
    from hypnomix.core import dsp
    t0 = time.time()
    y, sr = load_audio(path, max_s)
    if len(y) < 20 * sr:
        return dict(file=str(path), skipped="shorter than 20 s: not a song bounce")
    y = y[:, :2] if y.shape[1] >= 2 else np.repeat(y, 2, axis=1)
    lufs = float(pyln.Meter(sr).integrated_loudness(y))
    if time.time() - t0 > budget_s:
        return dict(file=str(path), skipped="timed out")
    blk = 30 * sr
    tp = max(dsp.true_peak(y[i:i + blk + 64], sr) for i in range(0, len(y), blk))
    peak = dsp.sample_peak(y)
    rms = dsp.rms_db(y.mean(axis=1))
    m = y.mean(axis=1)
    n = 8192
    frames = np.lib.stride_tricks.sliding_window_view(m, n)[:: n * 2]
    P = (np.abs(np.fft.rfft(frames * np.hanning(n), axis=1)) ** 2).mean(axis=0)
    f = np.fft.rfftfreq(n, 1 / sr)
    tot = P[(f >= 20) & (f < 20000)].sum() + 1e-20
    bands = {k: round(float(10 * np.log10(P[(f >= lo) & (f < hi)].sum() / tot + 1e-12)), 1) for k, lo, hi in BANDS8}
    if time.time() - t0 > budget_s:
        return dict(file=str(path), skipped="timed out")
    return dict(file=str(path), seconds=round(len(y) / sr, 1), lufs=round(lufs, 1) if np.isfinite(lufs) else None,
                true_peak=round(tp, 2), sample_peak=round(peak, 2), crest=round(peak - rms, 1),
                plr=round(tp - lufs, 1) if np.isfinite(lufs) else None, bands=bands, mtime=os.stat(path).st_mtime)


# ---------------------------------------------------------------------------------------------- cache + pool
def cached(kind, path, fn, *args, refresh=False, extra=""):
    """fn(path, *args), cached on disk by path + size + mtime (+ `extra`, e.g. a digest of the labels used)."""
    k = key_of(path) + (("-" + hashlib.sha1(extra.encode()).hexdigest()[:8]) if extra else "")
    f = CACHE / kind / f"{k}.json"
    if f.exists() and not refresh:
        try:
            return json.loads(f.read_text()), True
        except ValueError:
            pass
    res = fn(path, *args)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(res, default=str))
    return res, False


def _read_job(p, refresh, index=None):
    known = (index or {}).get(str(song_key(p))) or None
    try:
        return cached("sets", p, read_set, known, refresh=refresh,
                      extra=json.dumps(sorted(known.items())) if known else "")
    except Exception as e:
        return dict(song=Path(p).stem, path=p, failed=f"{type(e).__name__}: {e}"[:200]), False


def _bounce_job(p, refresh, max_s=600):
    try:
        return cached("bounces", p, measure_bounce, max_s, refresh=refresh)
    except Exception as e:
        return dict(file=p, skipped=f"failed: {type(e).__name__}"), False


def run_pool(fn, items, jobs, refresh, label):
    res, hits = {}, 0
    if not items:
        return res, 0
    if jobs <= 1:                                          # in this process (tests, debugging)
        for p in items:
            res[p], hit = fn(p, refresh)
            hits += hit
        return res, hits
    with cf.ProcessPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(fn, p, refresh): p for p in items}
        for i, fu in enumerate(cf.as_completed(futs), 1):
            r, hit = fu.result()
            res[futs[fu]] = r
            hits += hit
            if i % 10 == 0 or i == len(items):
                print(f"  {label}: {i}/{len(items)}", file=sys.stderr, flush=True)
    return res, hits


# ---------------------------------------------------------------------------------------------- across sets
def summ(vals, nd=2):
    vals = [float(x) for x in vals if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if not vals:
        return None
    return dict(median=round(float(np.median(vals)), nd), low=round(min(vals), nd), high=round(max(vals), nd),
                p25=round(float(np.percentile(vals, 25)), nd), p75=round(float(np.percentile(vals, 75)), nd), sets=len(vals))


def steady(x, width=None, factor=None):
    """A standard: the middle half of your sets within `width` (or within `factor` times, for times and ratios)."""
    if not x or x["sets"] < 3:
        return False
    if factor:
        return x["p25"] > 0 and x["p75"] / x["p25"] <= factor
    return (x["p75"] - x["p25"]) <= width


def per_set(sets, role, kind, field, agg=np.median):
    """One number per set (the set's median for that role and device), so each set counts once."""
    out = []
    for s in sets:
        xs = [d[field] for d in s["devices"] if d["role"] == role and d["kind"] == kind and d["on"] and d.get(field) is not None]
        if xs:
            out.append(float(agg(xs)))
    return out


COMP_W = dict(ratio=dict(factor=1.6), attack=dict(factor=2.5), release=dict(factor=2.0), threshold=dict(width=6.0),
              makeup=dict(width=3.0), knee=dict(width=3.0))
ROLE_ORDER = ["lead", "harmony", "drums", "bass", "keys/guitar/synth", "strings/other", "unknown", "group",
              "return:reverb", "return:delay", "return:other", "main"]


def style(sets, bounces, genres):
    roles = sorted({d["role"] for s in sets for d in s["devices"]} | {p["role"] for s in sets for p in s["plugins"]},
                   key=lambda r: ROLE_ORDER.index(r) if r in ROLE_ORDER else 99)
    st = dict(sets=len(sets), tempo=summ([s["tempo"] for s in sets], 1))
    comp = {}
    for r in roles:
        for k in ("compressor", "glue"):
            n = sum(any(d["role"] == r and d["kind"] == k and d["on"] for d in s["devices"]) for s in sets)
            if n:
                comp[f"{r}|{k}"] = dict(role=r, kind=k, in_sets=n,
                                        sidechain=round(float(np.mean([d["sidechain"] for s in sets for d in s["devices"]
                                                                       if d["role"] == r and d["kind"] == k])), 2),
                                        **{f: summ(per_set(sets, r, k, f)) for f in COMP_W})
    st["compression"] = comp
    eq = {}
    for r in roles:
        have = [s for s in sets if any(d["role"] == r for d in s["devices"]) or s["roles"].get(r)]
        if not have:
            continue
        cut = [s for s in have if any(d["role"] == r and d["kind"] == "eq" and d["on"] and d["low_cut"] for d in s["devices"])]
        moves = collections.defaultdict(list)
        for s in have:
            for d in s["devices"]:
                if d["role"] == r and d["kind"] == "eq" and d["on"]:
                    for b in d["bands"]:
                        if b["mode"] in ("bell", "low shelf", "high shelf"):
                            moves[(region(b["freq"]), "boost" if b["gain"] > 0 else "cut")].append((s["song"], b["gain"], b["freq"]))
        eq[r] = dict(sets=len(have), low_cut_sets=len(cut), low_cut_share=round(len(cut) / len(have), 2),
                     low_cut_hz=summ(per_set(sets, r, "eq", "low_cut", agg=np.min), 0),
                     moves={f"{a} {b}": dict(sets=len({x[0] for x in xs}), gain=summ([x[1] for x in xs], 1),
                                             freq=summ([x[2] for x in xs], 0)) for (a, b), xs in moves.items()})
    st["eq"] = eq
    main = dict(limiter_sets=sum(any(d["role"] == "main" and d["kind"] == "limiter" and d["on"] for d in s["devices"]) for s in sets),
                ceiling=summ(per_set(sets, "main", "limiter", "ceiling", agg=np.max)),
                limiter_gain=summ(per_set(sets, "main", "limiter", "gain", agg=np.sum)),
                glue_sets=sum(any(d["role"] == "main" and d["kind"] in ("glue", "compressor") and d["on"] for d in s["devices"]) for s in sets),
                utility_sets=sum(any(d["role"] == "main" and d["kind"] == "utility" and d["on"] for d in s["devices"]) for s in sets),
                bass_mono_sets=sum(any(d["kind"] == "utility" and d["on"] and d["bass_mono"] for d in s["devices"]) for s in sets),
                bass_mono_hz=summ([d["bass_mono_hz"] for s in sets for d in s["devices"] if d["kind"] == "utility" and d["bass_mono"]], 0))
    st["main"] = main
    sat = {}
    for r in roles:
        n = sum(any(d["role"] == r and d["kind"] == "saturator" and d["on"] for d in s["devices"]) for s in sets)
        if n:
            sat[r] = dict(in_sets=n, drive=summ(per_set(sets, r, "saturator", "drive"), 1),
                          dry_wet=summ(per_set(sets, r, "saturator", "dry_wet")))
    st["saturation"] = sat
    util = {}
    for r in roles:
        ws = per_set(sets, r, "utility", "width")
        if ws:
            util[r] = dict(width=summ(ws))
    st["utility"] = util
    rev = [d for s in sets for d in s["devices"] if d["role"].startswith("return") and d["kind"] == "reverb" and d["on"]]
    dly = [d for s in sets for d in s["devices"] if d["role"].startswith("return") and d["kind"] == "delay" and d["on"]]
    st["returns"] = dict(reverb_decay_ms=summ(per_set(sets, "return:reverb", "reverb", "decay_ms"), 0),
                         reverb_predelay_ms=summ(per_set(sets, "return:reverb", "reverb", "predelay_ms"), 1),
                         reverbs=len(rev), delays=len(dly),
                         delay_synced=round(float(np.mean([d["synced"] for d in dly])), 2) if dly else None,
                         delay_free_beats=summ([d["beats"] for d in dly if d.get("beats")], 3),
                         delay_feedback=summ([d["feedback"] for d in dly], 2))
    pl = collections.defaultdict(collections.Counter)
    for s in sets:
        for r, n in {(p["role"], p["name"]) for p in s["plugins"]}:
            pl[r][n] += 1
    st["plugins"] = {r: c.most_common(8) for r, c in sorted(pl.items(), key=lambda kv: ROLE_ORDER.index(kv[0]) if kv[0] in ROLE_ORDER else 99)}
    st["plugin_share"] = dict(sets_with_plugins=sum(bool(s["plugins"]) for s in sets),
                              stock_only=sum(not s["plugins"] for s in sets))
    ins = collections.Counter(n for s in sets for n in {i["name"] for i in s["instruments"]})
    pins = collections.Counter(n for s in sets for n in {p["name"] for p in s["plugins"] if p["instrument"]})
    smp = collections.Counter(n for s in sets for n in s["samples"])
    pk = collections.Counter(n for s in sets for n in s["packs"])
    st["sounds"] = dict(instruments=ins.most_common(12), plugin_instruments=pins.most_common(10),
                        samples=[x for x in smp.most_common(12) if x[1] >= 2], packs=pk.most_common(12),
                        drum_rack_sets=sum(s["drum_racks"] > 0 for s in sets))
    ok = [b for b in bounces.values() if b and not b.get("skipped") and b.get("lufs") is not None]
    st["bounces"] = dict(measured=len(ok), lufs=summ([b["lufs"] for b in ok], 1), true_peak=summ([b["true_peak"] for b in ok], 1),
                         crest=summ([b["crest"] for b in ok], 1), plr=summ([b["plr"] for b in ok], 1),
                         bands={k: summ([b["bands"][k] for b in ok], 1) for k, _, _ in BANDS8} if ok else {})
    tast = [s["taste"] for s in sets if s.get("taste") and not s["taste"].get("skipped")]
    st["taste"] = T.across(tast) if tast else None
    st["genres"] = per_genre(sets, bounces, genres)
    return st


def per_genre(sets, bounces, genres):
    by = collections.defaultdict(list)
    for s in sets:
        g = genres.get(Path(s["project"]).name) or genres.get(s["song"])
        if g:
            by[g].append(s)
    out = {}
    for g, ss in by.items():
        bs = [bounces.get(s.get("bounce")) for s in ss]
        bs = [b for b in bs if b and b.get("lufs") is not None]
        out[g] = dict(sets=len(ss), tempo=summ([s["tempo"] for s in ss], 1), bounce_lufs=summ([b["lufs"] for b in bs], 1),
                      bounce_plr=summ([b["plr"] for b in bs], 1),
                      bass_comp_release=summ(per_set(ss, "bass", "compressor", "release"), 0),
                      lead_comp_ratio=summ(per_set(ss, "lead", "compressor", "ratio")),
                      main_ceiling=summ(per_set(ss, "main", "limiter", "ceiling", agg=np.max)))
    return out


# ---------------------------------------------------------------------------------------------- where you could improve
def improve(sets, bounces, prefs=None):
    """Gentle, measured suggestions against common practice and your own habits. Advice only."""
    prefs = prefs or {}
    tp_target = float(((prefs.get("targets") or {}).get("true_peak")) or -1.0)
    out = []
    bo = {s["path"]: bounces.get(s.get("bounce")) for s in sets}
    bo = {k: b for k, b in bo.items() if b and not b.get("skipped") and b.get("lufs") is not None}
    name = {s["path"]: s["song"] for s in sets}

    # 1. bounces peaking above the true-peak target (lossy encodes overshoot further)
    ev = []
    for s in sets:
        b = bo.get(s["path"])
        if not b or b["true_peak"] <= tp_target + 0.05:
            continue
        lim = [d for d in s["devices"] if d["role"] == "main" and d["kind"] == "limiter" and d["on"]]
        last = [p["name"] for p in s["plugins"] if p["role"] == "main"]
        e = dict(set=s["song"], bounce_true_peak=b["true_peak"], file=Path(b["file"]).name)
        if lim:
            e["live_limiter_ceiling"] = max(d["ceiling"] for d in lim)
        elif last:
            e["main_ends_with"] = f"plug-in {last[-1]} (its ceiling is not readable from the set)"
        else:
            e["main_limiter"] = "none"
        ev.append(e)
    if ev:
        out.append(dict(topic="main", rule="ceiling", title=f"Bounces peak above {tp_target:g} dBTP",
                        advice=f"These bounces peak above {tp_target:g} dBTP (measured with 4x oversampling). Streaming "
                               f"encodes (AAC, MP3, Ogg) usually add 0.5-1 dB of overshoot, so they may clip after upload. "
                               f"Consider a true-peak ceiling of {tp_target:g} dB on the last limiter of Main (your "
                               f"preference `targets.true_peak`), then check the encode with `hypnomix translate`.",
                        evidence=ev))

    # 2. compressor releases faster than two cycles of the lowest bass note (bends the bass waveform: distortion)
    ev = []
    for s in sets:
        f0 = s.get("bass_f0") or 41.2
        floor_ms = 2000.0 / f0
        for d in s["devices"]:
            carries_bass = d["role"] in ("bass", "main") or (d["role"] == "group" and "bass" in d.get("carries", []))
            if d["kind"] in ("compressor", "glue") and d["on"] and not d["sidechain"] and carries_bass \
                    and d["release"] < 0.9 * floor_ms and d["ratio"] > 1.2:
                ev.append(dict(set=s["song"], track=d["track"], role=d["role"], release_ms=d["release"],
                               two_cycles_ms=round(floor_ms, 1),
                               lowest_note_hz=s.get("bass_f0") or "unknown (41 Hz, low E, assumed)"))
    if ev:
        out.append(dict(topic="compression", rule="fast-release", title="Compressor release faster than two bass cycles",
                        advice="On the bass, groups with bass in them and Main, a release shorter than two cycles of the lowest note lets the "
                               "compressor follow the waveform itself, which adds distortion to the low end. Try a release of at "
                               "least the 'two cycles' figure (`hypnomix devices` measures it on the real signal).",
                        evidence=ev[:20], count=len(ev)))

    # 3. low cut missing on parts you usually cut
    for r in ("lead", "harmony", "keys/guitar/synth", "strings/other"):
        have = [s for s in sets if s["roles"].get(r)]
        cut = [s for s in have if any(d["role"] == r and d["kind"] == "eq" and d["on"] and d["low_cut"] for d in s["devices"])]
        if len(have) >= 3 and len(cut) / len(have) >= 0.6:
            ev = [dict(set=s["song"], tracks=[x["track"] for x in s["no_low_cut"] if x["role"] == r][:6],
                       note="has a plug-in that may cut" if any(x["plugins"] for x in s["no_low_cut"] if x["role"] == r) else "")
                  for s in have if any(x["role"] == r for x in s["no_low_cut"])]
            if ev:
                hz = summ(per_set(cut, r, "eq", "low_cut", agg=np.min), 0)
                out.append(dict(topic="eq", rule="low-cut", title=f"No low cut on some {r} tracks",
                                advice=f"You cut the low end of {r} parts in {len(cut)} of {len(have)} sets"
                                       + (f" (usually around {hz['median']:g} Hz)" if hz else "")
                                       + ". These tracks have no EQ Eight low cut; a gentle one would match your own habit and "
                                         "clear rumble from the bass. Check by ear: some parts are meant to be full.",
                                evidence=ev[:15], count=len(ev)))

    # 4. loudness spread between finished songs
    if len(bo) >= 3:
        l = sorted((b["lufs"], name[k]) for k, b in bo.items())
        med = float(np.median([x[0] for x in l]))
        if l[-1][0] - l[0][0] > 3.0:
            far = [dict(set=n, lufs=x, vs_median=round(x - med, 1)) for x, n in l if abs(x - med) > 2.0]
            out.append(dict(topic="bounces", rule="loudness-spread", title="Loudness differs a lot between your songs",
                            advice=f"Your bounces range from {l[0][0]:g} to {l[-1][0]:g} LUFS (median {med:.1f}). On an album or "
                                   f"a playlist the quiet ones sound weaker and streaming normalisation turns the loud ones "
                                   f"down. Pick one target (your preferences: `hypnomix prefs set targets.lufs=…`) and master to it.",
                            evidence=far or [dict(set=n, lufs=x) for x, n in (l[0], l[-1])]))

    # 5. heavy limiting on Main, estimated from the bounce's peak-to-loudness ratio
    ev = []
    for k, b in bo.items():
        if b["plr"] is not None and b["plr"] < 8.0:
            ev.append(dict(set=name[k], lufs=b["lufs"], true_peak=b["true_peak"], plr=b["plr"], crest=b["crest"],
                           est_reduction_db=f"about {max(1, round(11 - b['plr']))}-{max(2, round(14 - b['plr']))} dB"))
    if ev:
        out.append(dict(topic="main", rule="heavy-limiting", title="Main chain squeezing hard",
                        advice="A peak-to-loudness ratio under 8 dB means the loudest moments are held down a lot (unlimited "
                               "mixes usually sit at 11-14 dB, so the estimate is the difference). That costs punch. If it isn't "
                               "the sound you want, ease the limiter or Glue gain by a few dB and compare at matched loudness.",
                        evidence=ev))

    # 6. a bounce whose tonal balance is far from your own other songs
    if len(bo) >= 4:
        med = {k: float(np.median([b["bands"][k] for b in bo.values()])) for k, _, _ in BANDS8}
        ev = []
        for k, b in bo.items():
            off = {bn: round(b["bands"][bn] - med[bn], 1) for bn in med if abs(b["bands"][bn] - med[bn]) >= 4.0 and bn != "air"}
            if off:
                ev.append(dict(set=name[k], bands_vs_your_median_db=off))
        if ev:
            out.append(dict(topic="bounces", rule="tonal-outlier", title="A song's tone far from your others",
                            advice="These bounces differ by 4 dB or more in a band from the median of your own songs. It may be "
                                   "deliberate (the arrangement), or a sign the mix leans one way: compare them with "
                                   "`hypnomix match MIX REF` against one of your songs you like.", evidence=ev))
    return out


# ---------------------------------------------------------------------------------------------- report
def fmt(x, unit="", nd=None):
    if not x:
        return "n/a"
    f = (lambda y: f"{y:.{nd}f}") if nd is not None else (lambda y: f"{y:g}")
    if x["sets"] == 1 or x["low"] == x["high"]:
        return f"{f(x['median'])}{unit} ({x['sets']} set{'s' if x['sets'] > 1 else ''})"
    return f"{f(x['median'])}{unit} (middle half {f(x['p25'])} to {f(x['p75'])}, all {f(x['low'])} to {f(x['high'])}, {x['sets']} sets)"


def tag(ok, x=None):
    if x is not None and (not x or x.get("sets", 0) < 3):
        return "too few sets to tell"
    return "**standard**" if ok else "taste call"


def report(lib):
    st, imp, meta = lib["style"], lib["improve"], lib["scan"]
    L = ["# Your style, learned from your library", "",
         f"Learned from {meta['sets']} sets ({meta['read'] + meta['cache_hits']} opened: {meta['read']} read now, "
         f"{meta['cache_hits']} from the cache) in {meta['seconds']:g} s; "
         f"{meta['found']} .als files found, {meta['skipped']} skipped (see the end). Bounces measured: "
         f"{st['bounces']['measured']}. Everything was read from the files on this computer; nothing was changed or uploaded.",
         "", "Two parts per topic. **YOUR STYLE**: the median set and the range. A narrow middle half is a **standard** "
         "(you do it the same way: tools keep to it); a wide one is a **taste call** (tools ask each time). "
         "**WHERE YOU COULD IMPROVE**: measured suggestions with the evidence. Advice only: your ears decide.", ""]
    L += ["## YOUR STYLE", "", "### Tempo and layout", ""]
    L.append(f"- tempo: {fmt(st['tempo'], ' BPM')}")
    tp = st.get("taste")
    if tp:
        body = T.report(tp, [])
        body = body[body.find("## Levels"):body.find("## Per song")] if "## Levels" in body else ""
        L += ["", "### Levels, space, ambience, chains (as `hypnomix taste` reads them; roles from `hypnomix name` labels where a version of the song has them, else from track names)", ""]
        L += [ln.replace("## ", "#### ") for ln in body.splitlines()]
    L += ["", "### Compression (Live's Compressor and Glue, per kind of track; each set counts once)", ""]
    for k, c in st["compression"].items():
        bits = []
        for f, unit in (("ratio", ":1"), ("attack", " ms"), ("release", " ms"), ("threshold", " dB"), ("makeup", " dB")):
            x = c[f]
            if x:
                bits.append(f"{f} {x['median']:g}{unit} ({x['low']:g} to {x['high']:g}, {tag(steady(x, **COMP_W[f]), x)})")
        L.append(f"- {c['role']} · {c['kind']} in {c['in_sets']} sets: " + "; ".join(bits)
                 + (f"; sidechained {c['sidechain']:.0%} of the time" if c["sidechain"] else ""))
    L += ["", "### EQ (EQ Eight)", ""]
    for r, e in st["eq"].items():
        if r.startswith("return") or e["sets"] < 1:
            continue
        mv = sorted(e["moves"].items(), key=lambda kv: -kv[1]["sets"])[:4]
        L.append(f"- {r}: low cut in {e['low_cut_sets']} of {e['sets']} sets"
                 + (f", at {fmt(e['low_cut_hz'], ' Hz', 0)}" if e["low_cut_hz"] else "")
                 + ("; usual moves: " + ", ".join(f"{m} {x['gain']['median']:+g} dB near {x['freq']['median']:g} Hz ({x['sets']} sets)"
                                                  for m, x in mv) if mv else ""))
    m = st["main"]
    L += ["", "### Main chain", "",
          f"- Live Limiter on Main in {m['limiter_sets']} of {st['sets']} sets; ceiling {fmt(m['ceiling'], ' dB')}"
          + (f" · {tag(steady(m['ceiling'], width=0.5), m['ceiling'])}" if m["ceiling"] else ""),
          f"- limiter gain {fmt(m['limiter_gain'], ' dB')}",
          f"- Glue / Compressor on Main in {m['glue_sets']} sets; Utility on Main in {m['utility_sets']} sets; "
          f"bass mono (Utility) used in {m['bass_mono_sets']} sets" + (f" at {m['bass_mono_hz']['median']:g} Hz" if m["bass_mono_hz"] else "")]
    tc = (st.get("taste") or {}).get("main_chain")
    if tc:
        L.append("- Main chain devices in 2+ sets: " + ", ".join(f"{d} ({n})" for d, n in tc))
    if st["saturation"]:
        L += ["", "### Saturation (Saturator)", ""]
        for r, x in st["saturation"].items():
            L.append(f"- {r}: in {x['in_sets']} sets, drive {fmt(x['drive'], ' dB')}, dry/wet {fmt(x['dry_wet'])}")
    if st["utility"]:
        L += ["", "### Width (Utility)", ""]
        for r, x in st["utility"].items():
            L.append(f"- {r}: width {fmt(x['width'])}")
    rt = st["returns"]
    L += ["", "### Returns", "",
          f"- reverb decay {fmt(rt['reverb_decay_ms'], ' ms', 0)}; predelay {fmt(rt['reverb_predelay_ms'], ' ms')}",
          f"- delays: {rt['delays']} on returns" + (f", {rt['delay_synced']:.0%} synced to the tempo" if rt["delay_synced"] is not None else "")
          + (f"; free-time ones at {fmt(rt['delay_free_beats'], ' beats', 2)}" if rt["delay_free_beats"] else "")
          + (f"; feedback {fmt(rt['delay_feedback'])}" if rt["delay_feedback"] else "")]
    L += ["", "### Third-party plug-ins (by name only; their settings are opaque to hypnomix)", "",
          f"- sets using any: {st['plugin_share']['sets_with_plugins']}; stock devices only: {st['plugin_share']['stock_only']}"]
    for r, lst in st["plugins"].items():
        L.append(f"- {r}: " + ", ".join(f"{n} ({c} sets)" for n, c in lst))
    s = st["sounds"]
    L += ["", "### Instruments and samples", "",
          "- Live instruments: " + (", ".join(f"{n} ({c} sets)" for n, c in s["instruments"]) or "none"),
          "- plug-in instruments: " + (", ".join(f"{n} ({c} sets)" for n, c in s["plugin_instruments"]) or "none"),
          f"- Drum Racks in {s['drum_rack_sets']} sets",
          "- samples you reuse (2+ sets): " + (", ".join(f"{n} ({c})" for n, c in s["samples"]) or "none"),
          "- Live packs referenced: " + (", ".join(f"{n} ({c} sets)" for n, c in s["packs"]) or "none")]
    b = st["bounces"]
    L += ["", "### Finished bounces", ""]
    if b["measured"]:
        L += [f"- loudness {fmt(b['lufs'], ' LUFS')} · {tag(steady(b['lufs'], width=2.0), b['lufs'])}",
              f"- true peak {fmt(b['true_peak'], ' dBTP')}", f"- peak-to-loudness (PLR) {fmt(b['plr'], ' dB')}",
              f"- crest {fmt(b['crest'], ' dB')}",
              "- tonal balance (share of energy per band, dB): " + ", ".join(f"{k} {x['median']:g}" for k, x in b["bands"].items() if x)]
    else:
        L.append("- none measured (no bounces found next to the sets, or --no-bounces)")
    L += ["", "## WHERE YOU COULD IMPROVE", ""]
    if not imp:
        L.append("Nothing stood out against common practice or your own habits.")
        L.append("")
    for i, x in enumerate(imp, 1):
        L += [f"### {i}. {x['title']}", "", x["advice"], "", "Evidence" + (f" ({x['count']} in all, first ones shown)" if x.get("count", 0) > len(x["evidence"]) else "") + ":"]
        for e in x["evidence"]:
            L.append("- " + "; ".join(f"{k.replace('_', ' ')} {val}" for k, val in e.items() if val not in ("", None, [])))
        L.append("")
    gq = lib["questions"]
    L += ["## Genres (questions, not facts)", ""]
    if st["genres"]:
        L.append("Confirmed genres, per genre:")
        for g, x in st["genres"].items():
            L.append(f"- {g}: {x['sets']} sets; tempo {fmt(x['tempo'], ' BPM')}; bounce loudness {fmt(x['bounce_lufs'], ' LUFS')}; "
                     f"PLR {fmt(x['bounce_plr'], ' dB')}; bass comp release {fmt(x['bass_comp_release'], ' ms')}; "
                     f"Main ceiling {fmt(x['main_ceiling'], ' dB')}")
        L.append("")
    if gq:
        L.append("Guessed from tempo and instruments; please confirm or correct each with "
                 "`hypnomix taste --library --genre \"PROJECT=genre\"` (saved in your preferences):")
        for q in gq:
            L.append(f"- {q['project']}: {q['guess']}? ({q['why']})")
    L += ["", "## What was read", ""]
    for p_, why in lib["skipped_summary"].items():
        L.append(f"- skipped {why[0]}: {why[1]}")
    for f in lib["failed"]:
        L.append(f"- FAILED to read {f['song']}: {f['failed']}")
    L += ["", "Sets learned from: " + ", ".join(x["song"] for x in lib["sets"])]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------------------------- main
def run(dirs=None, bounces=True, jobs=None, refresh=False, spotlight=True, max_bounce_s=600):
    from hypnomix.workflow import prefs as P
    t0 = time.time()
    found = find_sets(dirs, spotlight=spotlight)
    kept, skipped = dedupe(found)
    jobs = jobs or max(1, min(8, (os.cpu_count() or 2) - 1))
    print(f"found {len(found)} sets, studying {len(kept)} ({len(skipped)} skipped) with {jobs} workers…", file=sys.stderr)
    res, hits = run_pool(functools.partial(_read_job, index=names_index()), kept, jobs, refresh, "sets")
    sets = [res[p] for p in kept if not res[p].get("failed")]
    failed = [res[p] for p in kept if res[p].get("failed")]
    short = [s for s in sets if s.get("arranged_s", 0) < 30]
    skipped += [(s["path"], "less than 30 s in the arrangement: a sketch, preset or device set, not a finished song") for s in short]
    sets = [s for s in sets if s.get("arranged_s", 0) >= 30]
    bres, bhits = {}, 0
    for s in sets:                                         # looked up every run: new exports appear without the set changing
        s["bounce"] = find_bounce(s["path"]) if bounces else None
    if bounces:
        bl = sorted({s["bounce"] for s in sets if s.get("bounce")})
        bres, bhits = run_pool(functools.partial(_bounce_job, max_s=max_bounce_s), bl, jobs, refresh, "bounces")
    for s in sets:                                         # a bounce much shorter than the arrangement is a section
        b = bres.get(s.get("bounce"))
        if b and b.get("seconds") and s["arranged_s"] and b["seconds"] < 90 and b["seconds"] < 0.5 * s["arranged_s"]:
            bres[s["bounce"]] = dict(b, skipped=f"only {b['seconds']:g} s against {s['arranged_s']:g} s arranged: a section, not the mix")
    prefs = P.load()
    genres = ((prefs.get("library") or {}).get("genres")) or {}
    for s in sets:
        g = genres.get(Path(s["project"]).name) or genres.get(s["song"])
        if g:
            s["genre_guess"] = dict(s["genre_guess"], confirmed=True, genre=g)
    st = style(sets, bres, genres)
    imp = improve(sets, bres, prefs)
    reasons = collections.Counter(re.sub(r" \(newest: .*\)$", "", r) for _, r in skipped)
    questions = [dict(project=Path(s["project"]).name, set=s["song"], guess=s["genre_guess"]["guess"], why=s["genre_guess"]["why"],
                      key=f"library.genres.{Path(s['project']).name}") for s in sets if not s["genre_guess"].get("confirmed")]
    lib = dict(version=VERSION, generated=time.strftime("%Y-%m-%d %H:%M"),
               scan=dict(found=len(found), sets=len(sets), skipped=len(skipped), read=len(kept) - hits, cache_hits=hits,
                         bounces=len(bres), bounce_cache_hits=bhits, seconds=round(time.time() - t0, 1), jobs=jobs),
               style=st, improve=imp, questions=questions,
               sets=[dict(song=s["song"], path=s["path"], project=s["project"], tempo=s["tempo"], roles=s["roles"],
                          genre=s["genre_guess"], bounce=s.get("bounce"), bounce_measure=bres.get(s.get("bounce")))
                     for s in sets],
               skipped=[dict(path=p, reason=r) for p, r in skipped],
               skipped_summary={r: (n, r) for r, n in reasons.most_common()}, failed=failed)
    return lib


def save_genres(pairs):
    from hypnomix.workflow import prefs as P
    pr = P.load()
    g = pr.setdefault("library", {}).setdefault("genres", {})
    for x in pairs:
        if "=" not in x:
            sys.exit(f"--genre wants PROJECT=genre, got {x!r}")
        k, val = x.split("=", 1)
        g[k.strip()] = val.strip()
    return P.save(pr)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix taste --library", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="*", help="folders (or sets) to study; default: your Ableton folders + Spotlight")
    ap.add_argument("--no-bounces", action="store_true", help="do not look for or measure exported mixes")
    ap.add_argument("--jobs", type=int, help="parallel readers (default: CPUs - 1, at most 8)")
    ap.add_argument("--refresh", action="store_true", help="ignore the cache and read every set again")
    ap.add_argument("--no-spotlight", action="store_true", help="only walk the folders, do not ask Spotlight")
    ap.add_argument("--max-bounce-seconds", type=float, default=600, help="read at most this much of each bounce (600)")
    ap.add_argument("--genre", action="append", default=[], metavar="PROJECT=GENRE", help="confirm a project's genre")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.genre:
        print(f"saved {len(a.genre)} genre(s) in {save_genres(a.genre)}")
        if not a.dirs:
            return
    lib = run(a.dirs or None, bounces=not a.no_bounces, jobs=a.jobs, refresh=a.refresh, spotlight=not a.no_spotlight,
              max_bounce_s=a.max_bounce_seconds)
    LIBRARY.parent.mkdir(parents=True, exist_ok=True)
    LIBRARY.write_text(json.dumps(lib, indent=1, default=str))
    od = out_at(a.out, "library")
    md = report(lib)
    (od / "LIBRARY.md").write_text(md)
    print(md)
    print(f"→ {od / 'LIBRARY.md'} and {LIBRARY}  ({lib['scan']['seconds']:g} s)")


if __name__ == "__main__":
    main()
