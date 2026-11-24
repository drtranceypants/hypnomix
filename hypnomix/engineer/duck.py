#!/usr/bin/env python3
"""Duck the vocal reverb and delay: the ambience steps back while the singer sings and blooms in the gaps.

For every reverb or delay return the vocals send to, it looks for a sidechained Compressor on that return
triggered by the vocals, and measures what it does (the vocals are rendered from the set, faders included):

  tune   ducking already there: how far it turns the ambience down while the singer sings, and whether it
         lets go in the gaps. Proposed when it barely ducks, ducks too hard, or doesn't recover between
         phrases: the threshold is fitted to the target depth, the release kept or brought into range.
  add    no ducking yet: a Compressor at the end of the return's chain, its sidechain fed by the vocals
         (the vocal group if the vocals sit in one, else the lead; after their effects, "Post FX"),
         ratio 4, ~1 ms attack, ~205 ms release, threshold fitted so it ducks about --depth dB (3) while
         the singer sings. Delays first; reverbs a little lighter (2 dB), as an option.

Every item is an option, never applied unless approved; --apply writes a NEW set. Built from Live's own
"Basic Peak Compressor" preset, so Live must be installed. The compressor is simulated (like `hypnomix
sidechain`): check by ear.

Usage:
  hypnomix duck SET.als [--names names.json] [--renders DIR] [--depth 3] [--json OUT.json]
  hypnomix duck SET.als --apply NEW.als --ids duck-1,duck-2
"""
import argparse, gzip, json, math, re, subprocess, sys, tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from hypnomix.engineer import sidechain as SC

v = lambda n, p: (n.find(p).get("Value") if n.find(p) is not None else None)
safe = lambda n: re.sub(r'[\\/:*?"<>|]', "-", n)
VOCAL = re.compile(r"^(Lead Vocal|Harmony|Backing Vocal|Vocal)\b")
NEW = dict(kind="compressor", model=0, ratio=4.0, knee=6.0, attack=1.0, release=205.0, lookahead=1, sc_gain_db=0.0,
           eq_on=False, eq_mode=SC.HIGHPASS, eq_freq=100.0, eq_q=0.707, eq_gain=0.0, dry_wet=1.0, range_db=None)


def hx(*args):
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def db(x):
    return 20 * math.log10(x) if x and x > 0 else -70.0


def returns_of(root):
    out = []
    for t in root.find(".//Tracks"):
        if t.tag != "ReturnTrack":
            continue
        devs = t.find("./DeviceChain/DeviceChain/Devices")
        tags = " ".join((v(d, "./UserName") or "") + " " + d.tag for d in (list(devs) if devs is not None else []))
        tags += " " + (v(t, "./Name/EffectiveName") or "")
        kind = "delay" if re.search(r"delay|echo", tags, re.I) else "reverb" if re.search(r"reverb|verb|hybrid|tail", tags, re.I) else None
        out.append(dict(name=v(t, "./Name/EffectiveName"), el=t, kind=kind))
    return out


def vocal_source(root, vocals):
    """The vocal group if (nearly) all playing vocals sit in one, else the lead (first vocal)."""
    tracks = {v(t, "./Name/EffectiveName"): t for t in root.find(".//Tracks")}
    groups = [v(tracks[n], "./TrackGroupId") for n in vocals if n in tracks]
    by_id = {t.get("Id"): t for t in root.find(".//Tracks")}
    if groups:
        g = max(set(groups), key=groups.count)
        if g not in (None, "-1") and groups.count(g) >= 0.75 * len(groups) and g in by_id:
            return by_id[g]
    return tracks.get(vocals[0])


def trigger_audio(set_path, root, vocals, renders, source_el):
    """The vocals as the sidechain hears them: each vocal render with its fader (and the group's), summed."""
    from hypnomix.core import dsp
    rd = Path(renders) if renders else Path(tempfile.mkdtemp())
    need = [n for n in vocals if not (rd / f"{safe(n)}.wav").exists()]
    if need:
        hx("render", set_path, "--tracks", *need, "--out", rd)
    tracks = {v(t, "./Name/EffectiveName"): t for t in root.find(".//Tracks")}
    group_gain = 1.0
    if source_el is not None and source_el.tag == "GroupTrack":
        group_gain = float(v(source_el, "./DeviceChain/Mixer/Volume/Manual") or 1.0)
    mix = None
    for n in vocals:
        f = rd / f"{safe(n)}.wav"
        if not f.exists() or n not in tracks:
            continue
        y = SC.load_mono(str(f))
        g = float(v(tracks[n], "./DeviceChain/Mixer/Volume/Manual") or 1.0) * group_gain
        mix = y * g if mix is None else (np.pad(mix, (0, max(0, len(y) - len(mix)))) + np.pad(y * g, (0, max(0, len(mix) - len(y)))))
    return mix


def active_mask(trig):
    blk = int(0.05 * SC.SR)
    n = len(trig) // blk
    r = 20 * np.log10(np.sqrt((trig[: n * blk].reshape(n, blk) ** 2).mean(1)) + 1e-9)
    act = r > r.max() - 30
    m = np.repeat(act, blk)[: len(trig)] if n else np.zeros(len(trig), bool)
    return np.pad(m, (0, len(trig) - len(m)))                     # the last partial block counts as silent


def fit(trig, act, c, target):
    """Threshold so the ducking reaches `target` dB while the singer sings (median)."""
    lvl = SC.detector(trig, c)
    lo, hi = float(np.percentile(lvl[act], 10)) - 30 if act.any() else -60.0, float(lvl.max()) + 1
    for _ in range(16):
        c["threshold_db"] = (lo + hi) / 2
        d = SC.phrase_measure(SC.gain_reduction(lvl, c), act)["depth"]
        if d > target:
            lo = c["threshold_db"]
        else:
            hi = c["threshold_db"]
    c["threshold_db"] = (lo + hi) / 2
    return c, SC.phrase_measure(SC.gain_reduction(lvl, c), act)


def propose(set_path, names_json=None, renders=None, depth=3.0):
    set_path = Path(set_path)
    root = ET.fromstring(gzip.open(set_path).read())
    if names_json is None:
        nd = Path(tempfile.mkdtemp()); hx("name", set_path, "--out", nd); names_json = nd / "names.json"
    rows = json.loads(Path(names_json).read_text())["tracks"]
    vocals = [r["old"] for r in rows if r.get("kind") == "Audio" and r.get("on", True)
              and float(r.get("confidence") or 0) >= 0.5 and VOCAL.match(str(r.get("final") or r.get("label") or ""))]
    lead = next((r["old"] for r in rows if str(r.get("final") or r.get("label") or "").startswith("Lead Vocal")), None)
    if lead in vocals:
        vocals = [lead] + [x for x in vocals if x != lead]
    if not vocals:
        return [], dict(note="no vocal tracks found")
    tracks = {v(t, "./Name/EffectiveName"): t for t in root.find(".//Tracks")}
    src = vocal_source(root, vocals)
    rets = returns_of(root)
    # which returns the vocals feed (their own sends, or their group's)
    feeders = [tracks[n] for n in vocals if n in tracks] + ([src] if src is not None and src.tag == "GroupTrack" else [])
    fed = []
    for i, r in enumerate(rets):
        if not r["kind"]:
            continue
        lv = max([db(float(v(h, "./Send/Manual"))) for t in feeders
                  for k, h in enumerate(t.findall("./DeviceChain/Mixer/Sends/TrackSendHolder")) if k == i] + [-70.0])
        if lv > -40:
            fed.append(dict(r, send_db=round(lv, 1)))
    if not fed:
        return [], dict(note="the vocals don't send to a reverb or delay return", source=v(src, "./Name/EffectiveName") if src is not None else None)
    trig = trigger_audio(set_path, root, vocals, renders, src)
    if trig is None:
        return [], dict(note="could not render the vocals")
    act = active_mask(trig)
    src_devs = src.find("./DeviceChain/DeviceChain/Devices") if src is not None else None
    src_fx = [((v(d, "./UserName") or "") or d.tag) for d in (list(src_devs) if src_devs is not None else [])]
    on, off = SC.find_sidechains(root)
    vocal_ids = {tracks[n].get("Id") for n in vocals if n in tracks} | ({src.get("Id")} if src is not None else set())
    out = []
    for r in fed:
        here = [c for c in on + off if c["host_el"] is r["el"]]
        from_vocals = [c for c in here if c.get("source_el") is not None and c["source_el"].get("Id") in vocal_ids]
        target = depth if r["kind"] == "delay" else max(1.0, depth - 1.0)
        if from_vocals:
            c = from_vocals[0]
            cur = SC.phrase_measure(SC.gain_reduction(SC.detector(trig, c), c), act)
            problems = []
            if not c["on"]:
                problems.append("it is switched off")
            if cur["depth"] < 0.6 * target:
                problems.append(f"it barely ducks ({cur['depth']:.1f} dB while the singer sings)")
            elif cur["depth"] > 2.5 * target:
                problems.append(f"it ducks hard ({cur['depth']:.1f} dB while the singer sings)")
            if cur["in_gaps"] > 1.5:
                problems.append(f"it is still {cur['in_gaps']:.1f} dB down half a second into the gaps")
            if not problems:
                continue
            new = dict(c)
            if new.get("release", 0) and (new["release"] < 100 or new["release"] > 400):
                new["release"] = float(np.clip(new["release"], 150, 300))
            new, m = fit(trig, act, new, target)
            post_fx = "post" in (c.get("source_tap") or "").lower() and bool(src_fx)
            out.append(dict(kind="tune", ret=r["name"], kind_ret=r["kind"], source=c["source_name"], cur=cur, new=new, m=m,
                            problems=problems, dev_id=c["el"].get("Id"), glue=c.get("kind") == "glue",
                            uncertain=src_fx if post_fx else None))
        else:
            new, m = fit(trig, act, dict(NEW), target)
            out.append(dict(kind="add", ret=r["name"], kind_ret=r["kind"], send_db=r["send_db"],
                            source=v(src, "./Name/EffectiveName"), source_id=src.get("Id"), new=new, m=m,
                            uncertain=src_fx or None))
    return out, dict(source=v(src, "./Name/EffectiveName") if src is not None else None, vocals=vocals)


def findings(props):
    fs = []
    for i, p in enumerate(props, 1):
        n, m = p["new"], p["m"]
        settings = (f"threshold {n['threshold_db']:.1f} dB, ratio {n['ratio']:g}, attack {n['attack']:g} ms, "
                    f"release {n['release']:.0f} ms")
        result = f"ducks about {m['depth']:.1f} dB while the singer sings, {m['in_gaps']:.1f} dB half a second into the gaps"
        caveat = (f" Measured from the vocals before {p['source']}'s own effects ({', '.join(p['uncertain'][:3])}); if they "
                  "add level, it ducks more in Live: watch the compressor's gain-reduction meter in a chorus and trim the "
                  f"threshold until it shows about {m['depth']:.0f} dB while the singer sings.") if p.get("uncertain") else ""
        if p["kind"] == "add":
            fs.append(dict(id=f"duck-{i}", tool="duck", kind="duck-add", severity="low", track=p["ret"], where="",
                           problem=f"the vocals send to the {p['kind_ret']} '{p['ret']}' ({p['send_db']:+.0f} dB) and nothing "
                                   f"ducks it: the {p['kind_ret']} sits on top of the words",
                           fix=f"add a Compressor at the end of '{p['ret']}', its sidechain fed by '{p['source']}' (Post FX): "
                               f"{settings}; {result}. An option ({'recommended for delays' if p['kind_ret'] == 'delay' else 'reverbs: lighter, optional'})."
                               + caveat,
                           applies="set", duck=dict(kind="add", ret=p["ret"], source_id=p["source_id"], source=p["source"], c=_c(n))))
        else:
            unsure = bool(p.get("uncertain"))
            fs.append(dict(id=f"duck-{i}", tool="duck", kind="duck-tune", severity="info" if unsure else "low",
                           track=p["ret"], where="",
                           problem=f"the vocal ducking on '{p['ret']}' (from '{p['source']}'): " + "; ".join(p["problems"])
                                   + (" (as measured; see below)" if unsure else ""),
                           fix=(f"check it in Live first: {caveat.strip()} If it really ducks that little, try {settings}."
                                if unsure else f"set it to {settings}: {result}. An option"),
                           applies="manual" if unsure else "set",
                           duck=dict(kind="tune", ret=p["ret"], dev_id=p["dev_id"], c=_c(n))))
    return fs


def _c(c):
    keep = ("kind", "model", "ratio", "knee", "attack", "release", "lookahead", "sc_gain_db", "eq_on", "eq_mode",
            "eq_freq", "eq_q", "eq_gain", "dry_wet", "threshold_db", "range_db", "auto_release")
    return {k: (float(c[k]) if isinstance(c.get(k), (int, float, np.floating)) and not isinstance(c.get(k), bool) else c.get(k))
            for k in keep if k in c}


def add_compressor(root, ret_el, source_id, source_name, c):
    tpl = ET.fromstring(ET.tostring(SC.find_template()))
    nxt = root.find(".//NextPointeeId")
    nid = int(nxt.get("Value"))
    for e in tpl.iter():
        if e.tag in ("AutomationTarget", "ModulationTarget", "Pointee") and e.get("Id") is not None:
            e.set("Id", str(nid)); nid += 1
    nxt.set("Value", str(nid))
    devs = ret_el.find("./DeviceChain/DeviceChain/Devices")
    tpl.set("Id", str(max([int(d.get("Id", "0")) for d in devs] + [-1]) + 1))
    sc = tpl.find("./SideChain")
    sc.find("./OnOff/Manual").set("Value", "true")
    rt = sc.find("./RoutedInput/Routable")
    rt.find("./Target").set("Value", f"AudioIn/Track.{source_id}/PostFxOut")
    rt.find("./UpperDisplayString").set("Value", source_name)
    rt.find("./LowerDisplayString").set("Value", "Post FX")
    un = tpl.find("./UserName")
    if un is not None:
        un.set("Value", "Vocal Duck")
    SC.write_settings(tpl, c)
    devs.append(tpl)
    return tpl


def main():
    ap = argparse.ArgumentParser(prog="hypnomix duck", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als"); ap.add_argument("--names"); ap.add_argument("--renders"); ap.add_argument("--json")
    ap.add_argument("--depth", type=float, default=3.0, help="how far the ambience ducks while the singer sings (dB)")
    ap.add_argument("--apply", metavar="NEW.als"); ap.add_argument("--ids")
    a = ap.parse_args()
    src = Path(a.als)
    props, meta = propose(src, a.names, a.renders, a.depth)
    fs = findings(props)
    print(f"{src.name}: vocals → sidechain source '{meta.get('source')}'; {len(fs)} ducking option(s)"
          + (f" ({meta['note']})" if meta.get("note") else ""))
    for f in fs:
        print(f"  {f['id']:<8} {f['track']:<30} {f['fix'].split('. An option')[0]}")
    if a.json:
        Path(a.json).write_text(json.dumps({"tool": "duck", "set": str(src), "findings": fs}, indent=1, default=float))
    if a.apply:
        if Path(a.apply).resolve() == src.resolve():
            sys.exit("refusing to overwrite the set; give a new file name")
        if Path(a.apply).resolve().parent != src.resolve().parent:
            sys.exit(f"write the new set in the same folder as the original ({src.resolve().parent})")
        want = {x.strip() for x in (a.ids or "").split(",") if x.strip()}
        if not want:
            sys.exit("say which: --ids duck-1,… (nothing is applied by default)")
        root = ET.fromstring(gzip.open(src).read())
        rets = {r["name"]: r["el"] for r in returns_of(root)}
        done = 0
        for f in fs:
            if f["id"] not in want:
                continue
            d = f["duck"]
            if d["kind"] == "add":
                add_compressor(root, rets[d["ret"]], d["source_id"], d["source"], d["c"]); done += 1
            else:
                el = next((x for x in rets[d["ret"]].iter() if x.tag in ("Compressor2", "GlueCompressor") and x.get("Id") == d["dev_id"]), None)
                if el is not None:
                    SC.write_settings(el, dict(d["c"], kind="glue" if el.tag == "GlueCompressor" else "compressor")); done += 1
        data = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")
        with gzip.open(a.apply, "wb") as fh:
            fh.write(data)
        print(f"wrote {a.apply}: {done} ducking change(s)")


if __name__ == "__main__":
    main()
