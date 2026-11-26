#!/usr/bin/env python3
"""Mine Ableton .als files (gzipped XML): tempo, key, tracks, device/plugin chains, routing, mix and arrangement.

Usage: hypnomix mine project.als [...] [--out DIR]
"""
from hypnomix.core.paths import out_at
import argparse, gzip, json, math, re, sys
from hypnomix.core.gz import read_gz
from collections import Counter, defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET

KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJ = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MIN = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
RACKS = {"AudioEffectGroupDevice", "InstrumentGroupDevice", "MidiEffectGroupDevice", "DrumGroupDevice"}
TRACK_TAGS = ("MidiTrack", "AudioTrack", "GroupTrack", "ReturnTrack")


def val(node, path, default=None):
    n = node.find(path) if node is not None else None
    return n.get("Value") if n is not None and n.get("Value") is not None else default


def lin_to_db(v):
    v = float(v)
    return round(20 * math.log10(v), 1) if v > 0 else -120.0


def device_name(d):
    t = d.tag
    if t == "AuPluginDevice":
        return f"AU:{val(d, 'PluginDesc/AuPluginInfo/Name', '?')} ({val(d, 'PluginDesc/AuPluginInfo/Manufacturer', '')})"
    if t == "PluginDevice":
        for p in ("PluginDesc/Vst3PluginInfo/Name", "PluginDesc/VstPluginInfo/PlugName"):
            n = val(d, p)
            if n:
                return ("VST3:" if "Vst3" in p else "VST:") + n
        return "VST:?"
    if t.startswith("MxDevice"):
        user = val(d, "UserName")
        if user:
            return f"M4L:{user}"
        for fr in d.iter("FileRef"):
            p = val(fr, "RelativePath") or val(fr, "Path") or ""
            if p.endswith(".amxd"):
                return "M4L:" + Path(p).stem
        return "M4L:?"
    return t


def chain(devs_node, depth=0):
    """Flatten a device chain; rack contents are listed with a '>' prefix per level."""
    out = []
    if devs_node is None:
        return out
    for d in devs_node:
        on = val(d, "On/Manual", "true") == "true"
        name = device_name(d)
        user = val(d, "UserName")
        label = (">" * depth) + name + (f" [{user}]" if user and not name.startswith("M4L") else "") + ("" if on else " (off)")
        out.append(label)
        if d.tag in RACKS:
            for br in d.iter("Branches"):
                for b in br:
                    out += chain(b.find("DeviceChain/MidiToAudioDeviceChain/Devices") or
                                 b.find("DeviceChain/AudioToAudioDeviceChain/Devices") or
                                 b.find("DeviceChain/MidiToMidiDeviceChain/Devices"), depth + 1)
                break
    return out


def arrangement_clips(track):
    clips = []
    for ev in track.iter("ArrangerAutomation"):
        for c in ev.find("Events") if ev.find("Events") is not None else []:
            if c.tag in ("AudioClip", "MidiClip"):
                clips.append((float(val(c, "CurrentStart", 0)), float(val(c, "CurrentEnd", 0)), c))
    return clips


def midi_pitch_hist(clips):
    h = [0.0] * 12
    for _, _, c in clips:
        if c.tag != "MidiClip":
            continue
        for kt in c.iter("KeyTrack"):
            key = int(val(kt, "MidiKey", 0))
            for n in kt.iter("MidiNoteEvent"):
                if float(n.get("Velocity", 0)) > 1:
                    h[key % 12] += float(n.get("Duration", 0))
    return h


def corr(a, b):
    ma, mb = sum(a) / 12, sum(b) / 12
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) or 1
    return num / den


def key_from_hist(h):
    if sum(h) == 0:
        return None, 0
    best = max((corr(h, prof[-i:] + prof[:-i]), f"{KEYS[i]} {m}")
               for prof, m in ((MAJ, "major"), (MIN, "minor")) for i in range(12))
    return best[1], round(best[0], 3)


def mine(path):
    root = ET.fromstring(read_gz(path))
    ls = root.find("LiveSet")
    main = ls.find("MainTrack") or ls.find("MasterTrack")
    tsig = val(main, "DeviceChain/Mixer/TimeSignature/TimeSignatures/RemoteableTimeSignature/Numerator", "4")
    out = {"file": str(path), "name": Path(path).stem, "live_version": root.get("Creator"),
           "tempo": float(val(main, "DeviceChain/Mixer/Tempo/Manual", 0)),
           "time_signature": f"{tsig}/{val(main, 'DeviceChain/Mixer/TimeSignature/TimeSignatures/RemoteableTimeSignature/Denominator', '4')}",
           "scale_setting": {"root": KEYS[int(val(ls, 'ScaleInformation/Root', 0)) % 12],
                             "name_index": val(ls, "ScaleInformation/Name")},
           "locators": [(val(l, "Name"), float(val(l, "Time", 0))) for l in ls.findall("Locators/Locators/Locator")],
           "master_chain": chain(main.find("DeviceChain/DeviceChain/Devices")),
           "tracks": []}

    group_names = {t.get("Id"): val(t, "Name/EffectiveName") for t in ls.find("Tracks") if t.tag == "GroupTrack"}
    all_clips, hist = [], [0.0] * 12
    for t in ls.find("Tracks"):
        if t.tag not in TRACK_TAGS:
            continue
        dc = t.find("DeviceChain")
        clips = arrangement_clips(t) if t.tag in ("MidiTrack", "AudioTrack") else []
        h = midi_pitch_hist(clips)
        if "drum" not in (val(t, "Name/EffectiveName", "").lower()) and not any(x.tag == "DrumGroupDevice" for x in (dc.find("DeviceChain/Devices") or [])):
            hist = [a + b for a, b in zip(hist, h)]
        all_clips += [(s, e, t) for s, e, _ in clips]
        out["tracks"].append({
            "type": t.tag.replace("Track", ""), "name": val(t, "Name/EffectiveName"),
            "group": group_names.get(val(t, "TrackGroupId", "-1")),
            "output": val(dc, "AudioOutputRouting/UpperDisplayString"),
            "volume_db": lin_to_db(val(dc, "Mixer/Volume/Manual", 1)),
            "pan": round(float(val(dc, "Mixer/Pan/Manual", 0)), 2),
            "sends_db": [lin_to_db(val(s, "Manual", 0)) for s in dc.findall("Mixer/Sends/TrackSendHolder/Send")],
            "muted": val(dc, "Mixer/Speaker/Manual", "true") == "false",
            "frozen": val(t, "Freeze", "false") == "true",
            "devices": chain(dc.find("DeviceChain/Devices")),
            "arrangement_clips": len(clips),
        })

    # arrangement: length and an 8-bar density map (how many tracks play in each block)
    beats_per_bar = int(tsig)
    end = max((e for _, e, _ in all_clips), default=0)
    out["length_bars"] = round(end / beats_per_bar, 1)
    out["length_seconds"] = round(end * 60 / out["tempo"], 1) if out["tempo"] else None
    block = 8 * beats_per_bar
    density = []
    for b in range(int(math.ceil(end / block)) if end else 0):
        lo, hi = b * block, (b + 1) * block
        density.append(len({id(t) for s, e, t in all_clips if s < hi and e > lo}))
    out["density_per_8_bars"] = density
    # loop brace = usually the export region; density inside it is the song's real energy arc
    ls_, ll_ = float(val(ls, "Transport/LoopStart", 0)), float(val(ls, "Transport/LoopLength", 0))
    out["loop_bars"] = [round(ls_ / beats_per_bar + 1, 1), round((ls_ + ll_) / beats_per_bar + 1, 1)]
    out["loop_seconds"] = round(ll_ * 60 / out["tempo"], 1) if out["tempo"] else None
    out["density_in_loop_per_8_bars"] = [
        len({id(t) for s, e, t in all_clips if s < lo + block and e > lo})
        for lo in [ls_ + i * block for i in range(int(math.ceil(ll_ / block)))]] if ll_ else []
    out["midi_key_est"], out["midi_key_conf"] = key_from_hist(hist)

    # summaries
    plug = Counter(d.lstrip(">").split(" [")[0].replace(" (off)", "")
                   for tr in out["tracks"] for d in tr["devices"])
    plug.update(d.lstrip(">").split(" [")[0] for d in out["master_chain"])
    out["device_counts"] = dict(plug.most_common())
    out["track_type_counts"] = dict(Counter(t["type"] for t in out["tracks"]))
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("files", nargs="+")
    ap.add_argument("--out"); a = ap.parse_args()
    from hypnomix.core.paths import out
    outdir = out_at(a.out, "sessions"); outdir.mkdir(parents=True, exist_ok=True)
    for f in a.files:
        try:
            m = mine(Path(f))
        except Exception as e:
            print(f"FAIL {f}: {e}", file=sys.stderr); continue
        (outdir / (Path(f).stem + ".json")).write_text(json.dumps(m, indent=2), encoding="utf-8")
        print(f"{m['name']}: {m['tempo']} BPM {m['time_signature']}, key~{m['midi_key_est']}, "
              f"{len(m['tracks'])} tracks {m['track_type_counts']}, {m['length_bars']} bars, master={m['master_chain']}")


if __name__ == "__main__":
    main()
