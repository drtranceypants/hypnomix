#!/usr/bin/env python3
"""Tidy a set's tracks: retire switched-off tracks, and put clips of one instrument on one track.

Part of the first clean-up, with `name` and `order`. ON BY DEFAULT in scan/fix (skip the items to opt out, or
`hypnomix prefs set cleanup.retire=off` / `cleanup.consolidate=off` for every song). It never changes the sound.

1. Retire (retire-1). Switched-off tracks (the track activator off: old takes, replaced originals, copies) are
   removed from the new set, or with --mode bottom kept but moved to the bottom of their group and renamed
   "old: …". Before anything is removed a full copy of the set is written next to it as
   "<song> (archive, all takes).als", so every take stays reachable. A switched-off track is kept when:
     - its activator is automated (it plays somewhere), or it is a group or return
     - another track listens to it (a sidechain or an input routed from it)
   Review note "keep: Name, Name" keeps those tracks.
   (A new "Old takes" GROUP is not built in a Live set: a group needs Live to create it. In Live: select the "old:"
   tracks, Cmd/Ctrl-G. A HypnoMix Studio session open in HypnoMix Studio gets it directly: see 3.)

2. Consolidate (merge-N). Two tracks of the same instrument, side by side in one group, become one track when:
     - the same devices with the same settings, the same sends, pan and output (so they sound the same)
     - neither track is automated, the one emptied has no take lanes and no Session clips
     - a clip goes over only where it doesn't overlap a clip on the other track, or where the overlap is silence:
     then one of the two clips is cut back to the other's edge, and only when the part cut off is silent
     (rendered, under --silence-db, -55 dBFS). No sound is ever overwritten; a clip inside another stays
   A different fader is made up with clip gain, so every clip plays at the same level as before. When every clip
   fits, the emptied track is removed; clips that don't fit stay where they are (the review says which).
   Check it afterwards with `hypnomix render` (both tracks before, the one track after: they should match).
   The silence check renders one track at a time into a scratch folder (hypnomix-tidy-… under ~/.hypnomix/cache/tmp),
   deletes each render as soon as it is read, and removes the folder when the command ends (an error or Ctrl-C too).

3. HypnoMix Studio sessions (group-1). The switched-off (inactive) tracks not in a group yet become one folded group track
   "Old takes" (a route group plus its bus), written straight into the open HypnoMix Studio over MCP when approved
   (`--engine [URL] --ids group-1`; the engine must have this very session file open: a copy of the same name in
   another folder is refused). Nothing is removed or merged in a HypnoMix Studio session here, and nothing is written
   without --ids (--apply is for a Live set). Not in the engine's undo history: Ungroup puts it back. HypnoMix sees
   the change (the session shows as unsaved, and Stop, Open, New and quit ask Save first); save it to keep it.

Usage:
  hypnomix tidy SESSION.ardour [--json OUT.json]                       # HypnoMix Studio: the group option
  hypnomix tidy SESSION.ardour --engine [http://127.0.0.1:PORT/mcp] --ids group-1
  hypnomix tidy SET.als [--names names.json] [--json OUT.json]
  hypnomix tidy SET.als --apply NEW.als [--ids retire-1,merge-2] [--mode remove|bottom] [--tweak "retire-1:keep: A, B"]
"""
import argparse, copy, gzip, json, math, re, shutil, sys
from hypnomix.core.gz import read_gz
import xml.etree.ElementTree as ET
from pathlib import Path

v = lambda n, p: (n.find(p).get("Value") if n is not None and n.find(p) is not None else None)
LANE = "./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events"
MLANE = "./DeviceChain/MainSequencer/ClipTimeable/ArrangerAutomation/Events"
UI_TAGS = {"LomId", "LomIdView", "IsExpanded", "IsFolded", "ViewData", "ViewStateSesstionTrackWidth",
           "ShouldShowPresetName", "UserName", "Annotation", "LastSelectedTimeableIndex",
           "LastSelectedClipEnvelopeIndex", "LastPresetRef", "BranchSelectorRange", "SourceContext",
           "OverwriteProtectionNumber", "IsContentSelectedInDocument", "PreferModulationVisible", "Pointee"}
MAX_CLIP_GAIN = 63.0957     # +36 dB: what Live stores at most


def name(t):
    return v(t, "./Name/EffectiveName") or t.tag


def lane(t):
    return t.find(LANE) if t.tag == "AudioTrack" else t.find(MLANE)


def clips(t):
    ln = lane(t)
    return [] if ln is None else [c for c in ln if c.tag in ("AudioClip", "MidiClip")]


def span(c):
    return float(v(c, "./CurrentStart")), float(v(c, "./CurrentEnd"))


def is_on(t):
    return v(t, "./DeviceChain/Mixer/Speaker/Manual") != "false"


def automated(t, param=None):
    """True when the track has automation (on `param`'s target only, if given)."""
    envs = t.findall("./AutomationEnvelopes/Envelopes/AutomationEnvelope")
    if param is None:
        return any(e.findall(".//Events/*") for e in envs)
    at = t.find(f"./DeviceChain/Mixer/{param}/AutomationTarget")
    tid = at.get("Id") if at is not None else None
    return any(v(e, "./EnvelopeTarget/PointeeId") == tid for e in envs)


def listeners(root, tid):
    """Names of other tracks that take audio or MIDI from track `tid` (sidechain, input routing)."""
    pat = re.compile(rf"Track\.{tid}(/|$)")
    out = set()
    every = list(root.find(".//Tracks")) + [x for x in (root.find(".//MainTrack"), root.find(".//MasterTrack")) if x is not None]
    for t in every:
        if t.get("Id") == tid:
            continue
        if any(pat.search(e.get("Value") or "") for e in t.iter()):
            out.add(name(t))
    return sorted(out)


def _canon(el):
    """The settings that make a sound, without ids and view state: two equal canons sound the same."""
    if el is None:
        return ""
    x = copy.deepcopy(el)

    def strip(n):
        for k in ("Id",):
            n.attrib.pop(k, None)
        for ch in list(n):
            if ch.tag in UI_TAGS:
                n.remove(ch)
            else:
                strip(ch)
    strip(x)
    return ET.tostring(x, encoding="unicode")


def sound_key(t):
    """What has to match for two tracks to sound the same with the same clips (fader aside)."""
    m = t.find("./DeviceChain/Mixer")
    sends = [v(s, "./Send/Manual") for s in m.findall("./Sends/TrackSendHolder")] if m is not None else []
    return (t.tag, v(t, "./TrackGroupId"), _canon(t.find("./DeviceChain/DeviceChain/Devices")), tuple(sends),
            v(m, "./Pan/Manual"), v(m, "./SplitStereoPanL/Manual"), v(m, "./SplitStereoPanR/Manual"),
            v(m, "./PanMode"), v(t, "./DeviceChain/AudioOutputRouting/Target"),
            v(t, "./DeviceChain/MidiOutputRouting/Target"))


def session_clips(t):
    return any(s.find(".//AudioClip") is not None or s.find(".//MidiClip") is not None
               for s in t.findall("./DeviceChain/MainSequencer/ClipSlotList/ClipSlot"))


def take_lanes(t):
    return t.find(".//TakeLanes//AudioClip") is not None or t.find(".//TakeLanes//MidiClip") is not None


def fader_db(t):
    return 20 * math.log10(max(1e-6, float(v(t, "./DeviceChain/Mixer/Volume/Manual") or 1)))


# ---------------------------------------------------------------- 1. retire
def retire_plan(root, keep=()):
    """([(track el, why kept or None)]) for every switched-off track."""
    out = []
    for t in root.find(".//Tracks"):
        if t.tag not in ("AudioTrack", "MidiTrack") or is_on(t):
            continue
        why = None
        if name(t) in set(keep):
            why = "you said keep it"
        elif automated(t, "Speaker"):
            why = "its on/off switch is automated, so it plays somewhere"
        else:
            ls = listeners(root, t.get("Id"))
            if ls:
                why = "listened to by " + ", ".join(ls[:4])
        out.append((t, why))
    return out


def archive_path(src):
    src = Path(src)
    stem = re.sub(r" \([^()]*\)$", "", src.stem)
    p = src.with_name(f"{stem} (archive, all takes).als")
    n = 2
    while p.exists():
        p = src.with_name(f"{stem} (archive {n}, all takes).als")
        n += 1
    return p


def retire(root, plan, mode="remove"):
    T = root.find(".//Tracks")
    done = []
    for t, why in plan:
        if why:
            continue
        if mode == "remove":
            T.remove(t)
        else:                                            # bottom of its own group (or of the track list)
            g = v(t, "./TrackGroupId")
            T.remove(t)
            items = list(T)
            idx = len([x for x in items if x.tag != "ReturnTrack"])
            if g not in (None, "-1"):
                ids = {g}
                last = None
                for k, x in enumerate(items):          # the group's own block: the group, then its tracks
                    if x.get("Id") in ids or v(x, "./TrackGroupId") in ids:
                        last = k
                        if x.tag == "GroupTrack":
                            ids.add(x.get("Id"))
                idx = (last + 1) if last is not None else idx
            T.insert(idx, t)
            nm = t.find("./Name")
            if not name(t).startswith("old: "):
                for k in ("UserName", "EffectiveName"):
                    if nm.find(k) is not None:
                        nm.find(k).set("Value", "old: " + name(t))
        done.append(name(t))
    return done


# ---------------------------------------------------------------- 2. consolidate
def label_stem(s):
    return re.sub(r"[\s\-_]*\d+$", "", re.sub(r"\s*\(.*?\)$", "", (s or "").strip())).strip().lower()


def same_instrument(a, b, labels):
    la, lb = labels.get(name(a)), labels.get(name(b))
    if la and lb:
        return label_stem(la) == label_stem(lb) and bool(label_stem(la))
    sa, sb = label_stem(name(a)), label_stem(name(b))
    return bool(sa) and sa == sb and not re.fullmatch(r"(\d+-)*(audio|midi)", sa)


MIN_LEN = 0.25          # beats: a cut never leaves a clip shorter than this


def per_beat(c, tempo):
    """Content units per arrangement beat (beats for warped audio and MIDI, seconds for unwarped audio)."""
    return 1.0 if (c.tag == "MidiClip" or v(c, "./IsWarped") == "true") else 60.0 / tempo


def overlaps(x, y):
    return x[0] < y[1] - 1e-6 and y[0] < x[1] - 1e-6


def cut_options(c, d, cur, owner):
    """Ways to end the overlap of moving clip c with clip d by cutting one of them back to the other's edge:
    [(clip, edge, new position, track, silent-from, silent-to)]. A clip inside another would need splitting: none."""
    (ca, cb), (da, db) = cur[c], cur[d]
    if da < ca - 1e-6 and ca < db <= cb + 1e-6:          # d runs into c's start
        return [(d, "end", ca, owner[d], ca, db), (c, "start", db, owner[c], ca, db)]
    if ca <= da + 1e-6 and da < cb - 1e-6 and cb < db - 1e-6:   # c runs into d's start
        return [(c, "end", da, owner[c], da, cb), (d, "start", cb, owner[d], da, cb)]
    return []


def resolve(c, placed, cur, owner, silent):
    """Cuts (clip, edge, new) that let c sit beside every placed clip, cutting only where the cut-off part is
    silent; None when some overlap holds sound."""
    trial, cuts = dict(cur), []
    for d in sorted(placed, key=lambda x: trial[x][0]):
        if not overlaps(trial[c], trial[d]):
            continue
        done = False
        for el, edge, new, trk, s, e in cut_options(c, d, trial, owner):
            a, b = trial[el]
            rest = (b - new) if edge == "start" else (new - a)
            if v(el, "./Loop/LoopOn") == "true" or rest < MIN_LEN or silent is None or not silent(trk, s, e):
                continue
            trial[el] = (new, b) if edge == "start" else (a, new)
            cuts.append((el, edge, new, s, e))
            done = True
            break
        if not done:
            return None
    return cuts, trial


def merge_plan(root, labels=None, silent=None):
    """[dict(dst, src, move=[clips], stay=[clips], cuts=[...], why)] for neighbouring tracks of one instrument.
    `silent(track, from_beat, to_beat)` says whether a track plays nothing there; with it, overlapping clips are
    cut back where the overlapped part is silent (no sound is ever overwritten); without it they stay."""
    labels = labels or {}
    tracks = [t for t in root.find(".//Tracks") if t.tag in ("AudioTrack", "MidiTrack") and is_on(t)]
    used, out = set(), []
    for i, a in enumerate(tracks):
        for b in tracks[i + 1:]:
            if a.get("Id") in used or b.get("Id") in used:
                continue
            if not same_instrument(a, b, labels) or sound_key(a) != sound_key(b):
                continue
            # empty the one with fewer clips into the other
            dst, src = (a, b) if len(clips(a)) >= len(clips(b)) else (b, a)
            why = None
            if automated(a) or automated(b):
                why = "a track is automated"
            elif take_lanes(src):
                why = f"{name(src)} has comp take lanes"
            elif session_clips(src):
                why = f"{name(src)} has Session clips"
            elif listeners(root, src.get("Id")):
                why = f"another track listens to {name(src)}"
            elif any(c.find("./Envelopes/Envelopes/ClipEnvelope") is not None for c in clips(src)):
                why = f"{name(src)} has clip envelopes"
            owner = {c: dst for c in clips(dst)} | {c: src for c in clips(src)}
            cur = {c: span(c) for c in owner}
            placed = list(clips(dst))
            move, stay, cuts = [], [], []
            for c in sorted(clips(src), key=lambda c: span(c)[0]):
                r = resolve(c, placed, cur, owner, silent if c.tag == "AudioClip" else None)
                if r is None:
                    stay.append(c)
                    continue
                cuts += r[0]
                cur = r[1]
                move.append(c); placed.append(c)
            if not move:
                continue
            used |= {a.get("Id"), b.get("Id")}
            out.append(dict(dst=dst, src=src, move=move, stay=stay, cuts=cuts, why=why,
                            gain_db=fader_db(src) - fader_db(dst)))
    return out


def cut(c, edge, new, tempo):
    """Shorten clip c to `new` at one edge (a loop-off clip: its start or end marker moves the same amount). The
    cut lands in silence, so that edge gets no fade (a fade there would now dip audible sound)."""
    a, b = span(c)
    per = per_beat(c, tempo)
    if edge == "start":
        c.find("./CurrentStart").set("Value", repr(float(new)))
        c.set("Time", repr(float(new)))                  # Live keeps a clip's Time equal to its start
        ls = c.find("./Loop/LoopStart")
        ls.set("Value", repr(float(ls.get("Value")) + (new - a) * per))
        fl, fd = "./Fades/FadeInLength", "./Fades/IsDefaultFadeIn"
    else:
        c.find("./CurrentEnd").set("Value", repr(float(new)))
        le = c.find("./Loop/LoopEnd")
        le.set("Value", repr(float(le.get("Value")) - (b - new) * per))
        fl, fd = "./Fades/FadeOutLength", "./Fades/IsDefaultFadeOut"
    if c.find(fl) is not None:
        c.find(fl).set("Value", "0")
        if c.find(fd) is not None:
            c.find(fd).set("Value", "false")
    # a fade longer than the clip is left as it is: Live already plays it clamped, rewriting it changes the sound


def silence_probe(set_path, tempo, floor_db=-55.0):
    """silent(track, a, b): renders a track (once) and says whether it stays under floor_db (RMS, 20 ms windows)
    from beat a to beat b."""
    import subprocess
    import numpy as np
    from hypnomix.core import dsp, tmp as TMP
    box, cache, spb = [], {}, 60.0 / tempo           # box: the render folder, made at the first track, removed by close()

    def silent(t, a, b):
        nm = name(t)
        if nm not in cache:
            if not box:
                box.append(TMP.make("tidy", big=True))
            tmp = box[0]
            subprocess.run([sys.executable, "-m", "hypnomix.cli", "render", str(set_path), "--tracks", nm, "--out", str(tmp)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
            f = tmp / (re.sub(r'[\\/:*?"<>|]', "-", nm) + ".wav")
            cache[nm] = dsp.load(f) if f.exists() else None
            try:
                f.unlink()                               # heard once and kept in memory: never more than one render on disk
            except OSError:
                pass
        if cache[nm] is None:
            return False                                 # could not hear it: never cut
        y, sr = cache[nm]
        y = np.asarray(y, float)
        y = y if y.ndim == 1 else np.abs(y).max(axis=0 if y.shape[0] <= 2 else 1)
        seg = y[max(0, int(a * spb * sr)):int(b * spb * sr)]
        if not len(seg):
            return True
        w = max(1, int(0.02 * sr))
        k = len(seg) // w
        frames = seg[:k * w].reshape(k, w) if k else seg[None, :]
        rms = np.sqrt((frames ** 2).mean(axis=1)) if k else np.sqrt((seg ** 2).mean(keepdims=True))
        return bool(20 * np.log10(max(float(rms.max()), 1e-9)) < floor_db)

    def close():
        while box:
            TMP.remove(box.pop())
    silent.close = close                                 # the caller ends with this, in a finally
    return silent


def merge(root, m, tempo=120.0):
    """Move the plan's clips onto the destination track; remove the source when it is empty. Returns clips moved."""
    for c, edge, new, _, _ in m.get("cuts", []):
        cut(c, edge, new, tempo)
    dl, sl = lane(m["dst"]), lane(m["src"])
    used = {int(c.get("Id")) for c in clips(m["dst"]) if (c.get("Id") or "").isdigit()}
    k = 0
    for c in m["move"]:
        sl.remove(c)
        if c.get("Id") is None or int(c.get("Id")) in used:
            c.set("Id", str(max(used | {-1}) + 1))
        used.add(int(c.get("Id")))
        if abs(m["gain_db"]) > 1e-6 and c.tag == "AudioClip":
            sv = c.find("./SampleVolume")
            if sv is not None:
                sv.set("Value", repr(min(MAX_CLIP_GAIN, float(sv.get("Value")) * 10 ** (m["gain_db"] / 20))))
        at = span(c)[0]
        idx = sum(1 for x in clips(m["dst"]) if span(x)[0] < at)
        dl.insert(idx, c)
        k += 1
    if not clips(m["src"]):
        root.find(".//Tracks").remove(m["src"])
    return k


# ---------------------------------------------------------------- findings
def bar(beat):
    return f"{int(beat // 4) + 1}"


def findings(rplan, mplan, mode="remove"):
    out = []
    go = [name(t) for t, why in rplan if not why]
    kept = [f"{name(t)} ({why})" for t, why in rplan if why]
    if go:
        out.append(dict(id="retire-1", tool="tidy", kind="retire-off", severity="low", track=", ".join(go[:12]),
                        where=f"{len(go)} switched-off track(s)", default="approve", retire=go,
                        problem=f"{len(go)} track(s) are switched off (old takes, replaced originals, copies) and "
                                "clutter the set" + (f". Kept: {'; '.join(kept[:6])}" if kept else ""),
                        fix=("write a full copy as \"(archive, all takes)\", then " +
                             ("remove them from the new set" if mode == "remove" else
                              "move them to the bottom of their group, renamed \"old: …\"") +
                             f": {', '.join(go[:20])}{'…' if len(go) > 20 else ''}. ON BY DEFAULT: skip to keep them, "
                             "or note \"keep: Name, Name\" to keep some"),
                        applies="set"))
    for n, m in enumerate(mplan, 1):
        s, d = name(m["src"]), name(m["dst"])
        ok = not m["why"]
        cuts = (f"; {len(m['cuts'])} overlap(s) cut back where the cut-off part is silent (bars "
                f"{', '.join(bar(x[3]) for x in m['cuts'][:6])}): no sound is overwritten") if m.get("cuts") else ""
        stay = f"; {len(m['stay'])} clip(s) overlap where there is sound and stay on {s} (bars {', '.join(bar(span(c)[0]) for c in m['stay'][:6])})" if m["stay"] else ""
        out.append(dict(id=f"merge-{n}", tool="tidy", kind="consolidate", severity="low", track=f"{s} → {d}",
                        where=f"{len(m['move'])} clip(s)", default="approve" if ok else None,
                        src=m["src"].get("Id"), dst=m["dst"].get("Id"), removes=not m["stay"],
                        problem=f"{s} and {d} are the same instrument with the same sound (devices, sends, pan) on "
                                "two tracks, so one fader doesn't set the part",
                        fix=(f"move {len(m['move'])} clip(s) from {s} onto {d}" +
                             (f", clip gain {m['gain_db']:+.1f} dB to make up the fader difference" if abs(m['gain_db']) > 0.05 else "") +
                             (f", then remove the empty {s}" if not m["stay"] else "") + cuts + stay +
                             (". ON BY DEFAULT: skip to keep both tracks" if ok else f". By hand: {m['why']}")),
                        applies="set" if ok else "manual"))
    return out


def tweaks(items):
    keep = []
    for t in items or []:
        k, _, note = t.partition(":")
        if k.strip() == "retire-1" and note.strip().lower().startswith("keep"):
            keep += [x.strip() for x in note.split(":", 1)[-1].split(",") if x.strip()]
    return keep


def labels_from(names_json):
    if not names_json or not Path(names_json).exists():
        return {}
    rows = json.loads(Path(names_json).read_text(encoding="utf-8", errors="replace")).get("tracks", [])
    return {r["old"]: (r.get("final") or r.get("label")) for r in rows
            if float(r.get("confidence") or 0) >= 0.5 and (r.get("final") or r.get("label"))}


def main():
    ap = argparse.ArgumentParser(prog="hypnomix tidy", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    from hypnomix.session import liveversion as LV; LV.add_force_flag(ap)
    ap.add_argument("als"); ap.add_argument("--names", help="names.json from `hypnomix name` (what each track is)")
    ap.add_argument("--json"); ap.add_argument("--apply", metavar="NEW.als"); ap.add_argument("--ids")
    ap.add_argument("--mode", choices=["remove", "bottom"], default="remove", help="retired tracks: removed, or moved to the bottom")
    ap.add_argument("--tweak", action="append", help='review notes, e.g. "retire-1:keep: Guitar 2, Vox old"')
    ap.add_argument("--archive-from", metavar="ORIGINAL.als", help="the set to archive (default: SET.als)")
    ap.add_argument("--silence-db", type=float, default=-55.0,
                    help="an overlap may be cut only where the cut-off part stays under this (dBFS RMS, 20 ms)")
    ap.add_argument("--no-retire", action="store_true"); ap.add_argument("--no-merge", action="store_true")
    ap.add_argument("--engine", nargs="?", const="", metavar="URL",
                    help="HypnoMix Studio: write the approved group into the open HypnoMix engine (default its usual URL; the "
                         "engine's address is in the DAW view's engine panel). It must have this very session file "
                         "open. HypnoMix sees the change: the session shows as unsaved, and Stop, Open, New and quit "
                         "ask Save first; save in HypnoMix Studio to keep it")
    a = ap.parse_args()
    src = Path(a.als)
    from hypnomix import project as PJ
    if PJ.daw_of(src) == "ardour":
        from hypnomix.project import ardour_groups as AG
        sys.exit(AG.run_cli("tidy", src, a, lambda p: [] if a.no_retire else AG.plan_old_takes(p)))
    if a.apply and Path(a.apply).resolve() == src.resolve():
        sys.exit("refusing to overwrite the set; give a new file name")
    if a.apply and Path(a.apply).resolve().parent != src.resolve().parent:
        sys.exit(f"write the new set in the same folder as the original ({src.resolve().parent})")
    root = ET.fromstring(read_gz(src))
    rplan = [] if a.no_retire else retire_plan(root, tweaks(a.tweak))
    tempo = float(v(root, ".//Tempo/Manual") or 120)
    from hypnomix.core import tmp as TMP
    probe = silence_probe(src, tempo, a.silence_db)
    try:
        with TMP.terminate_cleans():
            mplan = [] if a.no_merge else merge_plan(root, labels_from(a.names), probe)
    finally:
        probe.close()                                    # its renders are removed, on an error or Ctrl-C too
    fs = findings(rplan, mplan, a.mode)
    for f in fs:
        print(f"{f['id']}: {f['problem']}\n   → {f['fix']}\n")
    if not fs:
        print("nothing to tidy: no switched-off tracks, no instrument split over matching tracks")
    if a.json:
        Path(a.json).write_text(json.dumps({"tool": "tidy", "set": str(src), "findings": fs}, indent=1), encoding="utf-8")
    if a.apply:
        want = {x.strip() for x in (a.ids or "").split(",") if x.strip()} or {f["id"] for f in fs if f.get("default") == "approve"}
        from hypnomix.session import liveversion as LV
        LV.guard_write(root)                # refuses a set saved by a Live newer than the newest tested
        moved = 0
        merged = []
        for f, m in zip([f for f in fs if f["kind"] == "consolidate"], mplan):
            if f["id"] in want and f["applies"] == "set":
                moved += merge(root, m, tempo)
                merged.append(name(m["src"]))
        gone = []
        if "retire-1" in want and rplan:
            orig = Path(a.archive_from) if a.archive_from else src
            arch = archive_path(orig)
            shutil.copy2(orig, arch)                  # every take stays reachable
            print(f"archived the full set as {arch.name}")
            gone = retire(root, rplan, a.mode)
        data = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")
        with gzip.open(a.apply, "wb") as fh:
            fh.write(data)
        print(f"wrote {a.apply}: {len(gone)} track(s) {'removed' if a.mode == 'remove' else 'moved down'}, "
              f"{moved} clip(s) consolidated from {', '.join(merged) or 'no tracks'}. "
              f"Check: hypnomix check NEW --against OLD --allow-removed")


if __name__ == "__main__":
    main()
