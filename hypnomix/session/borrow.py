#!/usr/bin/env python3
"""Borrow loops from the song's ORIGINAL project: clips the new version no longer uses, offered as layers.

Before a song was reworked, its first project often held parts that never made it across: a MIDI riff, a
second keys pattern, a percussion loop. This finds them and offers each as an option for a repetitive
section of the new set, on its own new track, switched OFF (turn it on to hear it; delete it to undo).

  where     the original project: a set with the same song name elsewhere under the same projects folder
            (e.g. "Ableton Projects/Song Project/Song.als" for "…/Claude Producer/Song Project/Song (remix).als"),
            or the sets you name with --from
  what      MIDI clips whose notes the new set doesn't play, and audio recordings it doesn't use at all
            (unused stretches of recordings it does use: `hypnomix variations`)
  loops     MIDI: the 1, 2 or 4-bar window of each clip whose notes already sit closest to the song's own
            groove (measured from the mix: how far each 16th, and above all each downbeat, plays ahead of or
            behind the grid). Audio: warped clips up to 16 bars, whole.
  key       a MIDI loop is offered only for sections whose scale holds (nearly) all its notes
  nudge     the whole MIDI clip is moved by one small offset so its first note lands where the song's
            downbeats land. The notes inside are never moved against each other: the feel stays as played.
            Windows that would need more than 30 ms of nudge, or whose notes sit more than 30 ms from the
            song's groove on average, are not offered (they don't line up).

The new track is a copy of the original track (its instrument and effects, fresh ids), ungrouped, routed to
Main, sends matched to this set's returns and turned down, and switched off.

Usage:
  hypnomix borrow SET.als --mix MIX.wav [--from ORIGINAL.als …] [--names names.json] [--plan [DIR]] [--json OUT]
  hypnomix borrow SET.als --mix MIX.wav --apply NEW.als --ids borrow-1,borrow-3
"""
import argparse, copy, gzip, hashlib, json, math, re, sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

BPB = 4
MAX_NUDGE_MS = 30.0     # a loop whose first note needs a bigger nudge than this doesn't line up: not offered
MAX_FIT_MS = 30.0       # nor one whose notes sit, on average, further than this from the song's groove
v = lambda n, p: (n.find(p).get("Value") if n.find(p) is not None else None)
MAIN_AUDIO = "./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events"
MAIN_MIDI = "./DeviceChain/MainSequencer/ClipTimeable/ArrangerAutomation/Events"
NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def load(p):
    return ET.ElementTree(ET.fromstring(gzip.open(p).read()))


def song_name(path):
    return re.sub(r"\s*\(.*?\)\s*", "", Path(path).stem).strip().lower()


def find_originals(set_path):
    """Sets with the same song name in other folders under the projects folder (not backups)."""
    p = Path(set_path).resolve()
    name = song_name(p)
    roots = [x for x in p.parents if x.name.lower() == "ableton projects"] or [p.parent.parent]
    out = []
    for f in roots[0].rglob("*.als"):
        if "Backup" in f.parts or f.parent == p.parent or song_name(f) != name:
            continue
        if any(part.lower() == "claude producer" for part in f.parts):
            continue
        out.append(f)
    return sorted(out, key=lambda f: (len(f.stem), str(f)))


# ---------------------------------------------------------------- clip contents
def notes_of(c):
    """[(time, key, dur, vel)] of a MIDI clip's enabled notes (clip-content beats)."""
    out = []
    for kt in c.findall(".//KeyTracks/KeyTrack"):
        key = int(v(kt, "./MidiKey"))
        for ev in kt.findall("./Notes/MidiNoteEvent"):
            if ev.get("IsEnabled") == "false":
                continue
            out.append((float(ev.get("Time")), key, float(ev.get("Duration")), float(ev.get("Velocity", 100))))
    return sorted(out)


def note_hash(notes):
    return hashlib.md5(json.dumps([(round(t, 3), k, round(d, 3)) for t, k, d, _ in notes]).encode()).hexdigest()


def used_in(root):
    """What the new set actually PLAYS: Arrangement clips on switched-on tracks (MIDI note contents, audio files).
    Clips on switched-off tracks, disabled clips and Session-view clips are still material to offer."""
    midi, audio = set(), set()
    for t in root.find(".//Tracks"):
        if v(t, "./DeviceChain/Mixer/Speaker/Manual") == "false":
            continue
        for c in t.findall(MAIN_MIDI + "/MidiClip"):
            if v(c, "./Disabled") != "true":
                midi.add(note_hash(notes_of(c)))
        for c in t.findall(MAIN_AUDIO + "/AudioClip"):
            if v(c, "./Disabled") != "true":
                audio.add(Path(v(c, "./SampleRef/FileRef/Path") or "").name)
    return midi, audio


SESSION = "./DeviceChain/MainSequencer/ClipSlotList/ClipSlot/ClipSlot/Value/"


def all_clips(t, tag):
    """(clip, where) for Arrangement and Session-view clips of a track."""
    path = MAIN_MIDI if tag == "MidiClip" else MAIN_AUDIO
    return [(c, "arrangement") for c in t.findall(f"{path}/{tag}")] + [(c, "session") for c in t.findall(SESSION + tag)]


def is_drums(t):
    return any(d.tag == "DrumGroupDevice" for d in t.iter())


# ---------------------------------------------------------------- the song's groove (from the mix)
def groove(mix, tempo, bars=None):
    """Per 16th of the bar: the median offset (beats) at which the song's hits land, and the downbeat offset."""
    import librosa
    y, sr = librosa.load(mix, sr=22050, mono=True)
    on = librosa.onset.onset_detect(y=y, sr=sr, hop_length=256, backtrack=True, units="time")
    beat_s = 60.0 / tempo
    pos = on / beat_s                                    # beats from the start of the bounce (= bar 1)
    slot = np.round(pos * 4) / 4
    off = pos - slot
    keep = np.abs(off) <= 0.12                           # within ~half a 16th
    tmpl = np.zeros(16)
    for k in range(16):
        sel = keep & (np.mod(np.round(slot * 4), 16) == k)
        tmpl[k] = float(np.median(off[sel])) if sel.sum() >= 4 else 0.0
    down = keep & (np.mod(np.round(slot * 4), 16) == 0)
    d_off = float(np.median(off[down])) if down.sum() >= 4 else 0.0
    return tmpl, d_off


def best_window(notes, content_len, tmpl, d_off, tempo):
    """The 1/2/4-bar window whose notes sit closest to the song's groove; its nudge (beats) and fit (ms)."""
    ms = 60000.0 / tempo
    best = None
    for bars in (4, 2, 1):
        L = bars * BPB
        if L > content_len + 1e-6:
            continue
        for w0 in np.arange(0.0, content_len - L + 1e-6, BPB):
            inside = [(t - w0, k) for t, k, _, _ in notes if w0 - 1e-6 <= t < w0 + L - 1e-6]
            if len(inside) < 3:
                continue
            p = np.array([x for x, _ in inside])
            slot = np.round(p * 4) / 4
            off = p - slot
            dev = np.abs(off - tmpl[(np.round(slot * 4) % 16).astype(int)])
            fit = float(np.median(dev) * ms)
            first = int(p.argmin())
            k = int(np.round(slot[first] * 4)) % 16
            target = d_off if k == 0 else tmpl[k]       # where the song lands at that 16th (downbeat: its average)
            nudge = float(target - off[first])          # move the whole clip so the first note lands there
            if abs(nudge) * ms > MAX_NUDGE_MS or fit > MAX_FIT_MS:   # it doesn't line up: not offered
                continue
            score = fit + abs(nudge) * ms * 0.5 - bars * 2  # longer loops a little better
            if best is None or score < best["score"]:
                best = dict(w0=float(w0), bars=bars, fit_ms=round(fit, 1), nudge=nudge,
                            nudge_ms=round(nudge * ms, 1), score=score, n=len(inside),
                            pcs=sorted({kk % 12 for _, kk in inside}))
    return best


# ---------------------------------------------------------------- key fit per section
def section_scales(set_path, mix, tempo):
    """[(bar_a, bar_b, pitch-class set)] from `hypnomix key`'s section map (major-scale sets)."""
    try:
        from hypnomix.ears import key as K
        secs, _ = K.section_map(str(set_path), mix, bars=8, hop_bars=4)
    except Exception:
        return []
    out = []
    for s in secs:
        a, b = (int(x) for x in s["bars"].split("-"))
        pcs = {(s["root"] + st) % 12 for st in K.MAJOR_STEPS}
        if s.get("unsure") and s.get("runner_up"):
            rn = s["runner_up"].split()[0]
            if rn in K.NAMES:
                pcs |= {(K.NAMES.index(rn) + st) % 12 for st in K.MAJOR_STEPS}
        out.append((a, b, pcs))
    return out


def fits(pcs_weighted, scale):
    return all(pc in scale for pc in pcs_weighted)


# ---------------------------------------------------------------- proposals
def propose(set_path, mix, originals):
    tree = load(set_path); root = tree.getroot()
    tempo = float(root.find(".//Tempo/Manual").get("Value"))
    used_midi, used_audio = used_in(root)
    from hypnomix.session.motion import sections_from
    ends = [float(v(c, "./CurrentEnd")) for c in list(root.iter("AudioClip")) + list(root.iter("MidiClip"))
            if c.find("./CurrentEnd") is not None]
    nbars = int(math.ceil(max(ends + [BPB]) / BPB))
    secs, how = sections_from(mix, tempo, nbars)
    secs = [s for s in secs if s["b"] - s["a"] >= 4]
    tmpl, d_off = groove(mix, tempo) if mix else (np.zeros(16), 0.0)
    scales = section_scales(set_path, mix, tempo)

    def scale_for(a, b):
        sc = [pcs for x0, x1, pcs in scales if x0 <= b and x1 >= a]
        return set.intersection(*sc) if sc else None

    cands, seen = [], set()
    for orig in originals:
        oroot = load(orig).getroot()
        for t in oroot.find(".//Tracks"):
            if t.tag not in ("MidiTrack", "AudioTrack"):
                continue
            tname = v(t, "./Name/EffectiveName")
            if t.tag == "MidiTrack":
                for c, where in all_clips(t, "MidiClip"):
                    ns = notes_of(c)
                    h = note_hash(ns)
                    if len(ns) < 3 or h in used_midi or h in seen:
                        continue
                    seen.add(h)
                    ls, le = float(v(c, "./Loop/LoopStart")), float(v(c, "./Loop/LoopEnd"))
                    ns_rel = [(tt - ls, k, d, vel) for tt, k, d, vel in ns if ls - 1e-6 <= tt < le]
                    w = best_window(ns_rel, le - ls, tmpl, d_off, tempo)
                    if w is None:
                        continue
                    cands.append(dict(kind="midi", orig=str(orig), track=tname, clip=c.get("Id"), drums=is_drums(t),
                                      ls=ls, win=w, name=v(c, "./Name") or tname, src=where))
            else:
                for c, where in all_clips(t, "AudioClip"):
                    f = Path(v(c, "./SampleRef/FileRef/Path") or "").name
                    if not f or f in used_audio or f in seen or v(c, "./IsWarped") != "true":
                        continue
                    L = float(v(c, "./CurrentEnd")) - float(v(c, "./CurrentStart"))
                    if not (BPB <= L <= 16 * BPB):
                        continue
                    seen.add(f)
                    bars = int(round(L / BPB))
                    cands.append(dict(kind="audio", orig=str(orig), track=tname, clip=c.get("Id"), drums=False, src=where,
                                      ls=float(v(c, "./Loop/LoopStart")), name=v(c, "./Name") or f,
                                      win=dict(w0=0.0, bars=bars, fit_ms=None, nudge=0.0, nudge_ms=0.0, n=0, pcs=[])))
    # place each where it fits: a repetitive section (longest first) whose scale holds its notes
    order = sorted(secs, key=lambda s: (-(s["repeat"] >= 2), -(s["b"] - s["a"])))
    out, load_ = [], {}
    for cnd in cands:
        for s in sorted(order, key=lambda s: load_.get(s["a"], 0)):     # spread the loops over the sections
            load_.setdefault(s["a"], 0)
            sc = scale_for(s["a"], s["b"])
            if cnd["kind"] == "midi" and not cnd["drums"] and sc is not None and not fits(cnd["win"]["pcs"], sc):
                continue
            out.append(dict(cnd, a=s["a"], b=s["b"], section=s["label"]))
            load_[s["a"]] += 1
            break
    return out, dict(tempo=tempo, how=how, downbeat_ms=round(d_off * 60000 / tempo, 1), nbars=nbars,
                     originals=[str(o) for o in originals], candidates=len(cands))


def findings(props, meta):
    out = []
    for n, p in enumerate(props, 1):
        w = p["win"]
        if p["kind"] == "midi":
            what = (f"a {w['bars']}-bar MIDI loop ({w['n']} notes, from beat {w['w0']:g} of '{p['name']}')"
                    f"; it sits {w['fit_ms']} ms from the song's groove on average")
            nud = (f"; the clip is nudged {w['nudge_ms']:+.1f} ms so its first note lands with the song's downbeats "
                   f"(the notes inside are not moved)" if abs(w["nudge_ms"]) >= 0.5 else "; it already lines up")
            notes = ", ".join(NAMES[pc] for pc in w["pcs"])
        else:
            what, nud, notes = f"a {w['bars']}-bar audio loop ('{p['name']}')", "", ""
        out.append(dict(id=f"borrow-{n}", tool="borrow", kind=f"borrow-{p['kind']}", severity="low",
                        track=f"{p['track']} (from original)", where=f"bars {p['a']}–{p['b'] - 1}",
                        problem=f"from the original project ({Path(p['orig']).name}, track '{p['track']}', "
                                f"{p['src']} clip): {what}"
                                + (f"; notes {notes} fit section {p['section']}" if notes else f"; for section {p['section']}"),
                        fix=f"add it as a layer over bars {p['a']}–{p['b'] - 1} on a new track '{p['track']} (from original)', "
                            f"switched OFF (its instrument and effects copied; turn it on to hear it){nud}. "
                            "An option, not a fix: change bars in the note (a=N b=N)",
                        applies="set", borrow={k: p[k] for k in ("kind", "orig", "track", "clip", "ls", "a", "b", "src")} |
                        {"w0": w["w0"], "bars": w["bars"], "nudge": w["nudge"]}))
    return out


# ---------------------------------------------------------------- writing
def import_track(root, src_track, name, returns_n):
    """A copy of a track from ANOTHER set: fresh ids, no clips, no automation, ungrouped, to Main, sends matched
    to this set's returns and turned down, switched off. Inserted before the returns."""
    tracks = root.find(".//Tracks")
    new = copy.deepcopy(src_track)
    new.set("Id", str(max(int(t.get("Id")) for t in tracks) + 1))
    npi = root.find(".//NextPointeeId")
    nxt = int(npi.get("Value"))
    remap = {}
    for e in new.iter():
        if (e.tag.endswith("Target") or e.tag == "Pointee") and (e.get("Id") or "").isdigit():
            remap[e.get("Id")] = str(nxt); e.set("Id", str(nxt)); nxt += 1
    for e in new.iter("PointeeId"):
        if e.get("Value") in remap:
            e.set("Value", remap[e.get("Value")])
    for path in (MAIN_AUDIO, MAIN_MIDI):
        ev = new.find(path)
        if ev is not None:
            for c in list(ev):
                ev.remove(c)
    for tl in new.findall(".//TakeLanes/TakeLanes"):
        for x in list(tl):
            tl.remove(x)
    for vv in new.findall("./DeviceChain/MainSequencer/ClipSlotList/ClipSlot/ClipSlot/Value"):
        for c in list(vv):
            vv.remove(c)
    envs = new.find("./AutomationEnvelopes/Envelopes")
    if envs is not None:
        for e in list(envs):
            envs.remove(e)
    new.find("./TrackGroupId").set("Value", "-1")
    out = new.find("./DeviceChain/AudioOutputRouting")
    if out is not None:
        out.find("./Target").set("Value", "AudioOut/Main")
        for tag, val in (("UpperDisplayString", "Main"), ("LowerDisplayString", "")):
            if out.find(f"./{tag}") is not None:
                out.find(f"./{tag}").set("Value", val)
    sends = new.find("./DeviceChain/Mixer/Sends")
    holders = sends.findall("./TrackSendHolder")
    while len(holders) > returns_n:
        sends.remove(holders.pop())
    while len(holders) < returns_n and holders:
        h = copy.deepcopy(holders[-1])
        for e in h.iter():
            if e.tag.endswith("Target") and (e.get("Id") or "").isdigit():
                e.set("Id", str(nxt)); nxt += 1
        sends.append(h); holders.append(h)
    for h in holders:
        s = h.find("./Send")
        mn = s.find("./MidiControllerRange/Min")
        s.find("./Manual").set("Value", mn.get("Value") if mn is not None else "0.0003162277571")
    npi.set("Value", str(nxt))
    for tag in ("EffectiveName", "UserName"):
        e = new.find(f"./Name/{tag}")
        if e is not None:
            e.set("Value", name)
    new.find("./DeviceChain/Mixer/Speaker/Manual").set("Value", "false")
    first_return = next((i for i, t in enumerate(tracks) if t.tag == "ReturnTrack"), len(tracks))
    tracks.insert(first_return, new)
    return new


def place_clip(new_track, src_clip, kind, ls, w0, bars, a, b, nudge):
    c = copy.deepcopy(src_clip)
    c.set("Id", "0")
    s0 = ls + w0
    L = bars * BPB
    a_b, b_b = (a - 1) * BPB + nudge, (b - 1) * BPB + nudge
    c.find("./CurrentStart").set("Value", repr(a_b)); c.find("./CurrentEnd").set("Value", repr(b_b))
    c.set("Time", repr(float(a_b)))                    # Live keeps a clip's Time equal to its start
    lp = c.find("./Loop")
    for tag, val in (("LoopStart", s0), ("LoopEnd", s0 + L), ("StartRelative", 0.0), ("OutMarker", s0 + L),
                     ("HiddenLoopStart", s0), ("HiddenLoopEnd", s0 + L)):
        if lp.find(f"./{tag}") is not None:
            lp.find(f"./{tag}").set("Value", repr(float(val)))
    lp.find("./LoopOn").set("Value", "true")
    if c.find("./Disabled") is not None:
        c.find("./Disabled").set("Value", "false")
    ev = new_track.find(MAIN_MIDI if kind == "midi" else MAIN_AUDIO)
    ev.append(c)


def main():
    ap = argparse.ArgumentParser(prog="hypnomix borrow", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als"); ap.add_argument("--mix"); ap.add_argument("--from", dest="orig", action="append")
    ap.add_argument("--json"); ap.add_argument("--plan", nargs="?", const=True)
    ap.add_argument("--apply", metavar="NEW.als"); ap.add_argument("--ids")
    ap.add_argument("--tweak", action="append", help='"borrow-2:a=17,b=33" (repeatable)')
    a = ap.parse_args()
    src = Path(a.als)
    originals = [Path(x) for x in a.orig] if a.orig else find_originals(src)
    if not originals:
        sys.exit("no original project found for this song (name it with --from ORIGINAL.als)")
    props, meta = propose(src, a.mix, originals)
    fs = findings(props, meta)
    print(f"{src.name}: originals {', '.join(Path(o).name for o in originals)}; {meta['candidates']} unused loop(s) found, "
          f"{len(fs)} fit a section; the song's downbeats land {meta['downbeat_ms']:+.1f} ms from the grid")
    for f in fs:
        print(f"  {f['id']:<10} {f['where']:<12} {f['track']}: {f['problem'].split(': ', 1)[-1][:110]}")
    if a.json:
        Path(a.json).write_text(json.dumps({"tool": "borrow", "set": str(src), "findings": fs, "meta": meta}, indent=1, default=str))
    if a.plan:
        from hypnomix.workflow import plan as PL
        od = PL.scan_dir(a.plan if isinstance(a.plan, str) else None, src, " (borrow)")
        PL.write(od, "borrow", src, fs, [f"borrow: originals {', '.join(meta['originals'])}",
                                         "borrow: every loop is an OPTION on a new switched-off track"])
        sj = Path(od) / "scan.json"
        info = json.loads(sj.read_text()) if sj.exists() else {}
        info.update(mode="set", mix=a.mix, borrow_from=meta["originals"])
        sj.write_text(json.dumps(info, indent=1))
    if a.apply:
        if Path(a.apply).resolve() == src.resolve():
            sys.exit("refusing to overwrite the set; give a new file name")
        if Path(a.apply).resolve().parent != src.resolve().parent:
            sys.exit(f"write the new set in the same folder as the original ({src.resolve().parent})")
        want = {x.strip() for x in (a.ids or "").split(",") if x.strip()}
        if not want:
            sys.exit("say which loops: --ids borrow-1,borrow-3 (none is added by default)")
        tw = {}
        for it in a.tweak or []:
            fid, _, kv = it.partition(":")
            tw[fid.strip()] = {k.strip(): float(x) for k, _, x in (p.partition("=") for p in kv.replace(" ", ",").split(",") if "=" in p)}
        tree = load(src); root = tree.getroot()
        returns_n = sum(1 for t in root.find(".//Tracks") if t.tag == "ReturnTrack")
        made, done = {}, 0
        for f in fs:
            if f["id"] not in want:
                continue
            b_ = dict(f["borrow"]); b_.update({k: int(x) for k, x in tw.get(f["id"], {}).items() if k in ("a", "b")})
            oroot = load(b_["orig"]).getroot()
            st = next(t for t in oroot.find(".//Tracks") if v(t, "./Name/EffectiveName") == b_["track"])
            sc = next(c for c, wh in all_clips(st, "MidiClip" if b_["kind"] == "midi" else "AudioClip")
                      if c.get("Id") == b_["clip"] and wh == b_["src"])
            key = (b_["orig"], b_["track"])
            if key not in made:
                made[key] = import_track(root, st, f"{b_['track']} (from original)", returns_n)
            place_clip(made[key], sc, b_["kind"], b_["ls"], b_["w0"], b_["bars"], b_["a"], b_["b"], b_["nudge"])
            done += 1
        for t in made.values():   # clip ids unique per track
            for path in (MAIN_AUDIO, MAIN_MIDI):
                ev = t.find(path)
                for i, c in enumerate(ev if ev is not None else []):
                    c.set("Id", str(i))
        data = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")
        with gzip.open(a.apply, "wb") as fh:
            fh.write(data)
        print(f"wrote {a.apply}: {done} loop(s) on {len(made)} new switched-off track(s)")


if __name__ == "__main__":
    main()
