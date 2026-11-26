#!/usr/bin/env python3
"""Put a Live set's tracks in a working order, and the parts of a vocal stack on the right tracks.

Part of the first clean-up of a song, ON BY DEFAULT (opt out: `hypnomix prefs set cleanup.order=off`, or skip
the order items in the review). It never changes the sound: only the order of tracks and, where it is safe,
which track a clip sits on.

1. Track order. Top to bottom:
     drums and percussion, bass, keys / guitar / synth / pads, vocals, strings, brass and other melodic parts,
     then anything unclear (asked about)
   and inside each of those, from the lowest pitch range to the highest (drums: kick to hats by brightness).
   Groups move as one block (named after the parts clearly in them) and their own tracks are ordered inside
   them the same way. Tracks keep their ids, so sends, sidechains and routing are untouched. Returns stay last.

2. Vocal stacks. Where two or more vocal parts sing at the same time on tracks of one group, the lowest part
   at that moment belongs on the stack's lowest track, the next on the next one up (low harmony, mid, high),
   so one fader sets one voice. A clip is moved only when that is safe, and the review says why not otherwise:
     - its own track has no comp take lanes (moving a comped clip would lose its takes): otherwise by hand
     - nothing else sits on the target track at that time, and neither track is automated there
     - it has no clip envelopes (they point at the old track's devices)
   A moved clip's clip gain is adjusted by the difference between the two faders, so it plays at the same level
   in the mix as before. When the two tracks' effects differ, the review says so: A/B it.

Usage:
  hypnomix order SET.als --names names.json [--json OUT.json]           # proposal (names.json: `hypnomix name`)
  hypnomix order SET.als --names names.json --apply NEW.als [--ids order-1,order-2]
"""
import argparse, gzip, json, sys
from hypnomix.core.gz import read_gz
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

CATEGORIES = ["drums", "bass", "keys/guitar/synth", "vocals", "other melodic", "unclear"]
LABEL_CAT = {
    "Drums": 0, "Kick": 0, "Snare": 0, "Hats": 0, "Toms": 0, "Percussion": 0, "Perc": 0, "Overheads": 0, "Cymbals": 0,
    "Bass": 1,
    "Keys": 2, "Piano": 2, "Guitar": 2, "Synth": 2, "Pad": 2, "Organ": 2, "Pluck": 2,
    "Vocal": 3, "Lead Vocal": 3, "Harmony": 3, "Backing Vocal": 3, "Vocals": 3,
    "Strings": 4, "Violin": 4, "Viola": 4, "Cello": 4, "Brass": 4, "Woodwind": 4, "Flute": 4,
}
CONFIDENT = 0.5
v = lambda n, p: (n.find(p).get("Value") if n.find(p) is not None else None)


def category(label, conf=1.0):
    if not label or conf < CONFIDENT:
        return 5
    base = label.split(" (")[0]
    for k in sorted(LABEL_CAT, key=len, reverse=True):
        if base == k or base.startswith(k + " ") or base.startswith(k):
            return LABEL_CAT[k]
    return 5


def pitch_key(rec):
    """Where a track sits, low to high: its median pitch (Hz), else its brightness (drums), else unknown."""
    f = rec.get("features") or {}
    if f.get("f0"):
        return float(f["f0"])
    if rec.get("midi_median_note") is not None:
        return 440.0 * 2 ** ((float(rec["midi_median_note"]) - 69) / 12)
    if f.get("centroid"):
        return float(f["centroid"]) / 10.0          # brightness: only compared within drums
    return None


# ---------------------------------------------------------------- 1. track order (pure)
def propose_order(tracks):
    """tracks: [dict(id, kind, parent, cat, pitch)] in current order (parent = group id or None).
    Returns the ids in the proposed order. Groups stay blocks; ties keep their current order."""
    pos = {t["id"]: i for i, t in enumerate(tracks)}
    kids = {}
    for t in tracks:
        kids.setdefault(t["parent"], []).append(t)
    byid = {t["id"]: t for t in tracks}

    def unit_cat(t):
        if t["kind"] != "Group":
            return t["cat"]
        cats = [unit_cat(c) for c in kids.get(t["id"], [])]
        cats = [c for c in cats if c != 5]
        return max(set(cats), key=cats.count) if cats else 5

    def unit_pitch(t):
        if t["kind"] != "Group":
            return t["pitch"]
        ps = [unit_pitch(c) for c in kids.get(t["id"], [])]
        ps = [p for p in ps if p is not None]
        return float(np.median(ps)) if ps else None

    def sort_key(t):
        p = unit_pitch(t) if unit_cat(t) != 5 else None      # unclear parts keep the order you gave them
        return (unit_cat(t), 0 if p is not None else 1, p if p is not None else 0, pos[t["id"]])

    out = []

    def emit(parent):
        units = [t for t in kids.get(parent, []) if t["kind"] != "Return"]
        for t in sorted(units, key=sort_key):
            out.append(t["id"])
            if t["kind"] == "Group":
                emit(t["id"])
    emit(None)
    out += [t["id"] for t in tracks if t["kind"] == "Return"]
    missing = [t["id"] for t in tracks if t["id"] not in out]       # anything whose parent isn't in the list
    return out + missing


# ---------------------------------------------------------------- set reading
def load(path):
    return ET.ElementTree(ET.fromstring(read_gz(path)))


def track_rows(root, names):
    """Rows for propose_order + per-track details, from the set and names.json rows (matched by name)."""
    by_name = {r["old"]: r for r in names}
    rows = []
    for t in root.find(".//Tracks"):
        nm = v(t, "./Name/EffectiveName") or ""
        rec = by_name.get(nm, {})
        kind = t.tag.replace("Track", "")
        g = v(t, "./TrackGroupId")
        rows.append(dict(id=t.get("Id"), name=nm, kind=kind, parent=None if g in (None, "-1") else g,
                         label=rec.get("final") or rec.get("label"), cat=category(rec.get("final") or rec.get("label"),
                                                                                  float(rec.get("confidence") or 0)),
                         pitch=pitch_key(rec) if rec else None, el=t, on=v(t, "./DeviceChain/Mixer/Speaker/Manual") != "false"))
    return rows


# ---------------------------------------------------------------- 2. vocal stacks
def clip_pitch(ci, tempo):
    """Median sung pitch (Hz) of one arrangement clip, from its audio file (fast, cached per file)."""
    from hypnomix.core import pitch
    from hypnomix.session import smooth as sm
    s0, s1 = sm.file_seconds(ci, np.array([ci["start"], ci["end"]]), tempo)
    if s1 <= s0 or not Path(ci["path"]).exists():
        return None
    return pitch.median_between(ci["path"], float(s0), float(s1), fmin=70, fmax=1000)

def assign_stack(clips, track_order, min_overlap=0.3):
    """Pure. clips: [dict(key, track, start, end, hz)]; track_order: the stack's tracks low to high.
    Where clips overlap (>= min_overlap of the shorter), the k-th lowest clip of that moment belongs on the
    k-th track. Returns {key: wanted track} for clips that should move (alone-singing clips stay put)."""
    want = {}
    for c in clips:
        if c["hz"] is None:
            continue
        group = [d for d in clips if d["hz"] is not None and
                 min(c["end"], d["end"]) - max(c["start"], d["start"]) >= min_overlap * min(c["end"] - c["start"], d["end"] - d["start"])]
        if len(group) < 2:
            continue
        group.sort(key=lambda d: d["hz"])
        k = group.index(c)
        if k < len(track_order) and track_order[k] != c["track"]:
            want[c["key"]] = track_order[k]
    return want


def has_lane_clips(t):
    return len(t.findall(".//TakeLanes//AudioClip")) > 0


def automated_between(t, s, e):
    for ev in t.findall("./AutomationEnvelopes/Envelopes/AutomationEnvelope//Events/*"):
        tm = float(ev.get("Time", "-1e9"))
        if s <= tm <= e and tm > -1e8:
            return True
    return False


def chain_signature(t):
    devs = t.find("./DeviceChain/DeviceChain/Devices")
    return [d.tag for d in devs] if devs is not None else []


def stack_moves(root, rows, tempo, als_dir):
    """Proposed clip moves per vocal stack: [(group id, [move dict])], plus the clips that need a hand."""
    from hypnomix.session import smooth as sm
    stacks = {}
    for r in rows:
        if r["kind"] == "Audio" and r["cat"] == 3 and r["on"]:
            stacks.setdefault(r["parent"], []).append(r)
    out = []
    for gid, members in stacks.items():
        if len(members) < 2:
            continue
        clips = []
        for r in members:
            for c in r["el"].findall("./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events/AudioClip"):
                if v(c, "./Disabled") == "true":
                    continue
                ci = sm.clip_info(c, als_dir, tempo)
                clips.append(dict(key=(r["id"], c.get("Id")), track=r["id"], start=float(v(c, "./CurrentStart")),
                                  end=float(v(c, "./CurrentEnd")), el=c, ci=ci))
        if not clips:
            continue
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(6) as ex:
            for c, hz in zip(clips, ex.map(lambda c: clip_pitch(c["ci"], tempo), clips)):
                c["hz"] = hz
        tr_pitch = {}
        for r in members:
            hs = [c["hz"] for c in clips if c["track"] == r["id"] and c["hz"]]
            tr_pitch[r["id"]] = float(np.median(hs)) if hs else (r["pitch"] or 0)
        order_ = sorted(tr_pitch, key=lambda k: tr_pitch[k])
        want = assign_stack(clips, order_)
        byid = {r["id"]: r for r in members}
        moves, hand = [], []
        cand = []
        for c in clips:
            if c["key"] not in want:
                continue
            src, dst = byid[c["track"]], byid[want[c["key"]]]
            why = None
            if has_lane_clips(src["el"]):
                why = f"'{src['name']}' is comped from take lanes: moving the clip would lose its takes"
            elif c["el"].find("./Envelopes/Envelopes") is not None and len(c["el"].find("./Envelopes/Envelopes")):
                why = "the clip has clip envelopes tied to its track's devices"
            elif automated_between(src["el"], c["start"], c["end"]) or automated_between(dst["el"], c["start"], c["end"]):
                why = "a track is automated there"
            item = dict(clip=c["el"].get("Id"), src=src["id"], dst=dst["id"], src_name=src["name"], dst_name=dst["name"],
                        start=c["start"], end=c["end"], hz=c["hz"], key=c["key"],
                        chains_differ=chain_signature(src["el"]) != chain_signature(dst["el"]))
            if why:
                item["why"] = why
                hand.append(item)
            else:
                cand.append(item)
        # check the FINAL layout (swaps are fine): every track must be free of overlaps after all moves
        while True:
            where = {c["key"]: c["track"] for c in clips}
            for m in cand:
                where[m["key"]] = m["dst"]
            span = {c["key"]: (c["start"], c["end"]) for c in clips}
            bad = None
            for m in cand:
                s0, e0 = span[m["key"]]
                if any(k != m["key"] and where[k] == m["dst"] and min(e0, span[k][1]) - max(s0, span[k][0]) > 1e-6
                       for k in where):
                    bad = m
                    break
            if bad is None:
                break
            cand.remove(bad)
            bad["why"] = f"'{bad['dst_name']}' would have two clips at once there"
            hand.append(bad)
        moves = cand
        if moves or hand:
            out.append(dict(group=gid, tracks=[byid[k]["name"] for k in order_], moves=moves, hand=hand))
    return out


def move_clip(root, m):
    tracks = {t.get("Id"): t for t in root.find(".//Tracks")}
    path = "./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events"
    se, de = tracks[m["src"]].find(path), tracks[m["dst"]].find(path)
    c = next((x for x in se.findall("AudioClip") if x.get("Id") == m["clip"]), None)
    if c is None:
        return False
    se.remove(c)
    used = {int(x.get("Id")) for x in de.findall("AudioClip")}
    if int(c.get("Id")) in used:
        c.set("Id", str(max(used) + 1))
    fs = float(v(tracks[m["src"]], "./DeviceChain/Mixer/Volume/Manual") or 1)
    fd = float(v(tracks[m["dst"]], "./DeviceChain/Mixer/Volume/Manual") or 1)
    sv = c.find("./SampleVolume")
    if sv is not None and fd > 0:
        sv.set("Value", repr(min(63.0957, float(sv.get("Value")) * fs / fd)))   # same level in the mix
    idx = sum(1 for x in de.findall("AudioClip") if float(v(x, "./CurrentStart")) < m["start"])
    de.insert(idx, c)
    return True


def reorder(root, ids):
    T = root.find(".//Tracks")
    els = {t.get("Id"): t for t in T}
    for t in list(T):
        T.remove(t)
    for i in ids:
        T.append(els[i])


# ---------------------------------------------------------------- findings
def findings(rows, new_ids, stacks):
    names = {r["id"]: r for r in rows}
    out = []
    cur = [r["id"] for r in rows]
    if new_ids != cur:
        def show(ids):
            lines, last = [], None
            for i in ids:
                r = names[i]
                if r["kind"] == "Return":
                    continue
                c = CATEGORIES[r["cat"]] if r["kind"] != "Group" else "group"
                depth = 0; p = r["parent"]
                while p:
                    depth += 1; p = names[p]["parent"] if p in names else None
                lines.append("  " * depth + f"{r['name']} ({c})")
            return "; ".join(lines)
        unclear = [names[i]["name"] for i in new_ids if names[i]["cat"] == 5 and names[i]["kind"] not in ("Group", "Return")]
        out.append(dict(id="order-1", tool="order", kind="track-order", severity="low", track="(all tracks)", where="",
                        default="approve",
                        problem="tracks are not in working order (drums, bass, keys/guitar/synth, vocals, other melodic; "
                                "low to high inside each)" + (f". Unclear, put last: {', '.join(unclear)}" if unclear else ""),
                        fix="reorder the tracks (sound, routing and sends unchanged): " + show(new_ids)
                            + ". ON BY DEFAULT: skip this item to keep the current order "
                              "(or `hypnomix prefs set cleanup.order=off` for every song)",
                        applies="set", track_order=new_ids))
    for n, st in enumerate(stacks, 2):
        mv, hand = st["moves"], st["hand"]
        diff = sorted({f"{m['src_name']} → {m['dst_name']}" for m in mv if m["chains_differ"]})
        txt = "; ".join(f"bar {int(m['start'] // 4) + 1}: {m['src_name']} → {m['dst_name']}" for m in mv[:12])
        out.append(dict(id=f"order-{n}", tool="order", kind="vocal-stack", severity="low",
                        track=", ".join(st["tracks"]), where=f"{len(mv)} clip(s) to move, {len(hand)} by hand",
                        default="approve" if mv else None,
                        problem=("in the vocal stack (" + ", ".join(st["tracks"]) + ", low to high), some parts sit on "
                                 "the wrong track for their pitch, so one fader does not set one voice"),
                        fix=(f"move {len(mv)} clip(s) to the track for their pitch, level kept the same with clip gain"
                             + (f" ({txt}{'…' if len(mv) > 12 else ''})" if mv else "")
                             + (f". Different effects on: {', '.join(diff)}: A/B those" if diff else "")
                             + (f". By hand in Live ({len(hand)}): " + "; ".join(
                                 f"bar {int(h['start'] // 4) + 1} {h['src_name']} → {h['dst_name']} ({h['why']})" for h in hand[:8])
                                if hand else "")),
                        applies="set" if mv else "manual", moves=[{k: m[k] for k in ("clip", "src", "dst", "start")} for m in mv]))
    return out


def read_names(path):
    """The track rows of a names.json file (written by `hypnomix name`); stops with a plain message when
    --names was given something else, such as a track name."""
    what = ("--names expects the path to a names.json file written by `hypnomix name SET.als` "
            "(not a track name)")
    p = Path(path)
    if not p.is_file():
        sys.exit(f"{what}; '{path}' is not a file")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        sys.exit(f"{what}; '{path}' is not a names.json file (it is not valid JSON)")
    rows = data.get("tracks") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        sys.exit(f"{what}; '{path}' has no \"tracks\" list")
    return rows


def main():
    ap = argparse.ArgumentParser(prog="hypnomix order", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    from hypnomix.session import liveversion as LV; LV.add_force_flag(ap)
    ap.add_argument("als"); ap.add_argument("--names", required=True, help="names.json from `hypnomix name`")
    ap.add_argument("--json"); ap.add_argument("--apply", metavar="NEW.als"); ap.add_argument("--ids")
    ap.add_argument("--no-clips", action="store_true", help="only reorder tracks; leave every clip where it is")
    a = ap.parse_args()
    src = Path(a.als)
    if a.apply and Path(a.apply).resolve() == src.resolve():
        sys.exit("refusing to overwrite the set; give a new file name")
    if a.apply and Path(a.apply).resolve().parent != src.resolve().parent:
        sys.exit(f"write the new set in the same folder as the original ({src.resolve().parent})")
    names = read_names(a.names)
    if not src.is_file():
        sys.exit(f"can't open the set '{src}': no such file (give the path to a saved .als)")
    tree = load(src); root = tree.getroot()
    tempo = float(root.find(".//Tempo/Manual").get("Value"))
    rows = track_rows(root, names)
    new_ids = propose_order(rows)
    stacks = [] if a.no_clips else stack_moves(root, rows, tempo, src.parent)
    fs = findings(rows, new_ids, stacks)
    for f in fs:
        print(f"{f['id']}: {f['problem']}\n   → {f['fix']}\n")
    if not fs:
        print("tracks are already in working order; no vocal-stack moves")
    if a.json:
        Path(a.json).write_text(json.dumps({"tool": "order", "set": str(src), "findings": fs}, indent=1, default=str), encoding="utf-8")
    if a.apply:
        want = {x.strip() for x in (a.ids or "").split(",") if x.strip()} or {f["id"] for f in fs}
        done = 0
        for f in fs:
            if f["id"] not in want or f["applies"] != "set":
                continue
            if f["kind"] == "vocal-stack":
                for m in f["moves"]:
                    done += move_clip(root, m)
        if "order-1" in want and any(f["id"] == "order-1" for f in fs):
            reorder(root, new_ids)
        data = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")
        from hypnomix.session import liveversion as LV
        LV.guard_write(root)                # refuses a set saved by a Live newer than the newest tested
        with gzip.open(a.apply, "wb") as fh:
            fh.write(data)
        print(f"wrote {a.apply}: {'tracks reordered; ' if 'order-1' in want else ''}{done} clip(s) moved")


if __name__ == "__main__":
    main()
