#!/usr/bin/env python3
"""A/B inside Live: one new set where every proposed fix sits next to what you have now, switched off, so you
hear it with every plug-in, in place, instantly, and nothing is rendered or exported.

  hypnomix abset SCAN_DIR [--ids ID,ID,...] [--out "Song (A-B).als"]

For each finding that changes the set, the fix is built on its own (in a temporary copy of the scan) and
compared with the original, then written into ONE new set like this:

  device changes     (compressor, EQ, sidechain, ducking, a new device)  the changed device is copied in right
                     after yours, named "B · <id>" and switched off. A = yours on, the copy off; B = the other way.
  clip and mixer     (fades, cuts, clip gain, timing, tuning, volume rides, fader moves)  the whole track is
                     copied with the fix, named "<track> · B <id>", and muted. A/B swaps which one is muted.
  new or removed     a track the fix adds is muted (B unmutes it); a track it removes is muted in B.

The set opens and plays exactly like the original (every B is off). The hypnomix device in Live then switches
each finding: **A**, **B**, and **Blind** (it picks at random which is X and which is Y, you choose the one
you like, and only then hear which was which; your choices are kept in blind.json). With the probe on Main,
the louder of A and B is turned down to match while you listen, so you judge the change, not the level.

The A/B set is for listening. Approving still happens in the review, and `hypnomix fix --approved` still writes
the real new set from the original. Writes SCAN_DIR/ab_live.json: which switches belong to which finding.

Not previewable this way (said in ab_live.json): changes to Main other than its devices, and changes to a
return track other than its devices (a copy of a return would not get the sends).
"""
import argparse, copy, difflib, gzip, json, os, shutil, subprocess, sys, tempfile, time
import xml.etree.ElementTree as ET
from pathlib import Path

SKIP_TOOLS = {"name", "order", "tidy", "refs", "unroll", "intent", "audit"}       # not something you hear
TRACK_TAGS = ("AudioTrack", "MidiTrack", "GroupTrack", "ReturnTrack")


def load(p):
    return ET.ElementTree(ET.fromstring(gzip.open(p).read()))


def save(tree, out):
    data = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(tree.getroot(), encoding="utf-8")
    with gzip.open(out, "wb") as f:
        f.write(data)


def main_track(root):
    return root.find(".//MainTrack") if root.find(".//MainTrack") is not None else root.find(".//MasterTrack")


def all_tracks(root):
    ts = root.find(".//LiveSet/Tracks")
    out = {t.get("Id"): t for t in (list(ts) if ts is not None else []) if t.tag in TRACK_TAGS}
    m = main_track(root)
    if m is not None:
        out["main"] = m
    return out


def tname(t):
    if t.tag in ("MainTrack", "MasterTrack"):
        return "Main"
    n = t.find("./Name/UserName")
    if n is None or not n.get("Value"):
        n = t.find("./Name/EffectiveName")
    return n.get("Value") if n is not None else t.tag


def set_name(t, name):
    for tag in ("EffectiveName", "UserName"):
        e = t.find(f"./Name/{tag}")
        if e is not None:
            e.set("Value", name)


def devices(t):
    return t.find("./DeviceChain/DeviceChain/Devices")


def sig(e):
    return ET.tostring(e)


def rest(t):
    """The track without its device list and its name: clips, mixer, automation, routing."""
    c = copy.deepcopy(t)
    d = devices(c)
    if d is not None:
        for x in list(d):
            d.remove(x)
    n = c.find("./Name")
    if n is not None:
        c.remove(n)
    return ET.tostring(c)


def is_on(dev):
    m = dev.find("./On/Manual")
    return m is None or m.get("Value") == "true"


def set_on(dev, on):
    m = dev.find("./On/Manual")
    if m is not None:
        m.set("Value", "true" if on else "false")


def dev_label(d):
    u = d.find("./UserName")
    if u is not None and u.get("Value"):
        return u.get("Value")
    for p in ("./PluginDesc/Vst3PluginInfo/Name", "./PluginDesc/VstPluginInfo/PlugName", "./PluginDesc/AuPluginInfo/Name"):
        e = d.find(p)
        if e is not None and e.get("Value"):
            return e.get("Value")
    return d.tag


class Ids:
    """Fresh automation / modulation / pointee ids for copied elements."""

    def __init__(self, root):
        self.npi = root.find(".//NextPointeeId")
        self.next = int(self.npi.get("Value")) if self.npi is not None else 1_000_000
        mx = max([int(e.get("Id")) for e in root.iter() if (e.tag.endswith("Target") or e.tag == "Pointee")
                  and (e.get("Id") or "").isdigit()] or [0])
        self.next = max(self.next, mx + 1)

    def fresh(self, elem):
        remap = {}
        for e in elem.iter():
            if (e.tag.endswith("Target") or e.tag == "Pointee") and (e.get("Id") or "").isdigit():
                remap[e.get("Id")] = str(self.next)
                e.set("Id", str(self.next))
                self.next += 1
        for e in elem.iter("PointeeId"):
            if e.get("Value") in remap:
                e.set("Value", remap[e.get("Value")])
        if self.npi is not None:
            self.npi.set("Value", str(self.next))
        return elem


def device_diff(do, dx):
    """Align two device lists: (op, i_orig, j_fixed) with op in changed / added / removed."""
    a, b = [x.tag for x in do], [x.tag for x in dx]
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                if sig(do[i1 + k]) != sig(dx[j1 + k]):
                    ops.append(("changed", i1 + k, j1 + k))
        elif tag == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                if i1 + k < i2:
                    ops.append(("removed", i1 + k, None))
                if j1 + k < j2:
                    ops.append(("added", i1 + k - 1 if i1 + k >= i2 else i1 + k, j1 + k))
        elif tag == "delete":
            ops += [("removed", i, None) for i in range(i1, i2)]
        elif tag == "insert":
            ops += [("added", i1 - 1, j) for j in range(j1, j2)]
    return ops


def build_one(ab_root, orig_root, fixed_root, fid, ids, a_dev_refs):
    """Write one finding's B into ab_root. Returns (parts, notes)."""
    O, X, AB = all_tracks(orig_root), all_tracks(fixed_root), all_tracks(ab_root)
    parts, notes = [], []
    tracks_el = ab_root.find(".//LiveSet/Tracks")
    for tid, xt in X.items():
        ot = O.get(tid)
        if ot is None:                                    # a track the fix adds
            new = ids.fresh(copy.deepcopy(xt))
            used = [int(t.get("Id")) for t in tracks_el if (t.get("Id") or "").isdigit()]
            new.set("Id", str(max(used) + 1))
            nm = f"{tname(xt)} · B {fid}"
            set_name(new, nm)
            sp = new.find("./DeviceChain/Mixer/Speaker/Manual")
            if sp is not None:
                sp.set("Value", "false")
            tracks_el.append(new)
            parts.append(dict(mode="tracks", a=[], b=[nm], a_on=[], b_on=[True]))
            continue
        if sig(ot) == sig(xt):
            continue
        abt = AB[tid]
        if rest(ot) != rest(xt):
            if tid == "main" or ot.tag == "ReturnTrack":
                notes.append(f"{tname(ot)}: changes other than its devices cannot be switched in Live; apply this one alone to hear it")
                continue
            new = ids.fresh(copy.deepcopy(xt))
            used = [int(t.get("Id")) for t in tracks_el if (t.get("Id") or "").isdigit()]
            new.set("Id", str(max(used) + 1))
            nm = f"{tname(ot)} · B {fid}"
            set_name(new, nm)
            sp = new.find("./DeviceChain/Mixer/Speaker/Manual")
            on = sp is None or sp.get("Value") == "true"
            if sp is not None:
                sp.set("Value", "false")
            tracks_el.insert(list(tracks_el).index(abt) + 1, new)
            parts.append(dict(mode="tracks", a=[tname(abt)], b=[nm], a_on=[on], b_on=[on]))
            continue
        do, dx, dab = list(devices(ot)), list(devices(xt)), devices(abt)
        refs = a_dev_refs.setdefault(tid, list(dab))      # the AB set's elements for the original devices
        a_els, b_els = [], []
        for op, i, j in device_diff(do, dx):
            if op in ("changed", "added"):
                new = ids.fresh(copy.deepcopy(dx[j]))
                used = [int(d.get("Id")) for d in dab if (d.get("Id") or "").isdigit()]
                new.set("Id", str(max(used) + 1 if used else 0))
                u = new.find("./UserName")
                if u is None:
                    u = ET.SubElement(new, "UserName")
                u.set("Value", f"B · {fid}")
                was_on = is_on(new)
                set_on(new, False)
                after = refs[i] if 0 <= i < len(refs) else None
                pos = list(dab).index(after) + 1 if after is not None else 0
                while pos < len(dab) and (dab[pos].find("./UserName") is not None and
                                          (dab[pos].find("./UserName").get("Value") or "").startswith("B · ")):
                    pos += 1                              # after earlier B copies of the same device
                dab.insert(pos, new)
                b_els.append((new, was_on))
                if op == "changed":
                    a_els.append((refs[i], is_on(refs[i])))
            elif op == "removed":
                a_els.append((refs[i], is_on(refs[i])))
        if a_els or b_els:
            parts.append(dict(mode="devices", track=tname(abt), main=tid == "main", _a=a_els, _b=b_els))
    for tid, ot in O.items():
        if tid not in X and tid != "main":               # a track the fix removes: B mutes it
            sp = ot.find("./DeviceChain/Mixer/Speaker/Manual")
            parts.append(dict(mode="tracks", a=[tname(ot)], b=[], a_on=[sp is None or sp.get("Value") == "true"], b_on=[]))
    return parts, notes


def finalize(ab_root, items):
    """Device positions are only final once every B is in: turn element refs into indices."""
    AB = {tname(t): t for t in all_tracks(ab_root).values()}
    for it in items.values():
        for p in it.get("parts", []):
            if p["mode"] != "devices":
                continue
            devs = list(devices(AB[p["track"]]))
            a_, b_ = p.pop("_a"), p.pop("_b")
            p["a"], p["a_on"] = [devs.index(e) for e, _ in a_], [on for _, on in a_]
            p["b"], p["b_on"] = [devs.index(e) for e, _ in b_], [on for _, on in b_]
            p["a_names"] = [dev_label(devs[i]) for i in p["a"]]
            p["b_names"] = [dev_label(devs[i]) for i in p["b"]]
    return items


def candidates(findings, ids=None):
    want = {x.strip() for x in (ids or "").split(",") if x.strip()}
    out = []
    for f in findings:
        if want:
            if f["id"] in want or str(f.get("n")) in want:
                out.append(f)
        elif f.get("applies") == "set" and f.get("tool") not in SKIP_TOOLS:
            out.append(f)
    return out


def fixed_copy(sd, fid, orig, extra=()):
    """Build this one fix into a temporary set next to the original, from a throwaway copy of the scan."""
    tmp = Path(tempfile.mkdtemp(prefix="hm-ab-"))
    for p in Path(sd).iterdir():
        if p.is_file():
            shutil.copy2(p, tmp / p.name)
        else:
            os.symlink(p.resolve(), tmp / p.name)
    (tmp / "decisions.json").write_text("{}")
    out = orig.with_name(f".{orig.stem} (ab-{fid}-{int(time.time() * 1000) % 10 ** 8}).als")
    cmd = [sys.executable, "-m", "hypnomix.cli", "fix", str(tmp), "--approve", fid, "--out", out.name,
           "--stale-ok", "--no-verify", "--allow-protected"] + list(extra)
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[2]))
    shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode != 0 or not out.exists():
        return None, (r.stderr or r.stdout).strip().splitlines()[-1:] or ["fix failed"]
    return out, []


def build(sd, ids=None, out=None, extra=()):
    sd = Path(sd)
    data = json.loads((sd / "findings.json").read_text())
    orig = Path(data.get("set") or "")
    if orig.suffix.lower() == ".rpp":            # a REAPER project: workflow/abset_project.py
        from hypnomix.workflow import abset_project as AP
        return AP.build(sd, ids, out, extra)
    if not str(orig).endswith(".als") or not orig.exists():
        raise RuntimeError("this scan has no Live set to build an A/B set from (folder scans: use `hypnomix ab`)")
    cands = candidates(data["findings"], ids)
    if not cands:
        raise RuntimeError("no findings that change the set (pass --ids to choose)")
    out = Path(out) if out else orig.with_name(f"{orig.stem} (A-B).als")
    if not out.is_absolute():
        out = orig.parent / out
    if out.exists() or out.resolve() == orig.resolve():
        raise RuntimeError(f"{out.name} already exists: choose a new name with --out (nothing is overwritten)")
    orig_tree = load(orig)
    ab_tree = load(orig)
    ids_ = Ids(ab_tree.getroot())
    items, refs = {}, {}
    for f in cands:
        print(f"  {f['id']}: building B …", flush=True)
        fx, err = fixed_copy(sd, f["id"], orig, extra)
        if not fx:
            items[f["id"]] = dict(parts=[], note="could not be built: " + "; ".join(err))
            continue
        try:
            parts, notes = build_one(ab_tree.getroot(), orig_tree.getroot(), load(fx).getroot(), f["id"], ids_, refs)
        finally:
            fx.unlink(missing_ok=True)
        items[f["id"]] = dict(parts=parts, note="; ".join(notes) if notes else ("" if parts else "the fix changed nothing in the set"),
                              track=f.get("track"), problem=f.get("problem"))
    finalize(ab_tree.getroot(), items)
    save(ab_tree, out)
    spec = dict(set=str(out), original=str(orig), built=time.strftime("%Y-%m-%d %H:%M"), items=items)
    (sd / "ab_live.json").write_text(json.dumps(spec, indent=1))
    return out, spec


def main():
    ap = argparse.ArgumentParser(prog="hypnomix abset", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scan_dir")
    ap.add_argument("--ids", default="", help="only these findings (ids or numbers); default: every audible set change")
    ap.add_argument("--out", help='the A/B set to write (default "<Song> (A-B).als", next to the original)')
    ap.add_argument("--key", help="confirmed key, passed to fix for tuning findings")
    a = ap.parse_args()
    try:
        out, spec = build(a.scan_dir, a.ids, a.out, ["--key", a.key] if a.key else [])
    except RuntimeError as e:
        sys.exit(str(e))
    if spec.get("daw") == "reaper":
        ok = sum(1 for it in spec["items"].values() if it["parts"])
        print(f"\nwrote {out}\n  {ok} of {len(spec['items'])} findings can be switched A/B in REAPER; the original is unchanged")
        for fid, it in spec["items"].items():
            if it.get("note"):
                print(f"  {fid}: {it['note']}")
        print("Open the A/B project in REAPER, then `hypnomix reaper review`: the Hypnomix panel switches A / B / Blind.")
        return
    from hypnomix.session import check as C
    err, warn, _ = C.check(str(out), against=spec["original"],
                           added=[b for it in spec["items"].values() for p in it["parts"] if p["mode"] == "tracks" for b in p["b"]])
    ok = sum(1 for it in spec["items"].values() if it["parts"])
    print(f"\nwrote {out}\n  {ok} of {len(spec['items'])} findings can be switched A/B in Live; the original is unchanged")
    for fid, it in spec["items"].items():
        if it.get("note"):
            print(f"  {fid}: {it['note']}")
    for e in err:
        print(f"  CHECK ERROR: {e}")
    for w in warn[:8]:
        print(f"  check: {w}")
    print("Close the original in Live, open the A/B set, put the hypnomix device on any track, and use A / B / Blind.")


if __name__ == "__main__":
    main()
