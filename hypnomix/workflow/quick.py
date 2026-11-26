"""Fast scans: `scan --quick` (only the checks that read the set itself, no rendering or audio analysis) and
`scan --since DIR` (re-run only the groups whose tracks changed since that scan, keep the rest).

Quick groups:
  files      missing audio files (refs)
  intent     automated controls, hard pans, switched-off tracks (from the set)
  structure  the set's structure (the same check `fix` runs on what it writes), default track names, faders and
             clip gains at extremes, clips butted together with no fade: all from the XML, in a second or two

Incremental: every scan keeps a copy of the set it scanned (raw/scanned.als, a few hundred KB). `--since DIR`
compares the set now with that copy (`hypnomix diff`), picks the groups the changes can affect, runs only those
and merges with DIR's other groups. Findings carried over are marked `carried: true`; findings that were not in
the previous scan are marked `new: true`; decisions follow their findings by what they are (tool, track, kind,
place), never by their number in the list.
"""
import json, math, re, shutil
from pathlib import Path

QUICK_GROUPS = ["files", "intent", "structure"]
SNAPSHOT = "scanned.als"
DEFAULT_NAME = re.compile(r"^\d+-(Audio|MIDI|Group|Return)( \d+)?$|^(Audio|MIDI)( \d+)?$")


def g_structure(als, od, a):
    """From the XML only: structure errors, default names (when no names group ran), level extremes, butt joins."""
    import gzip, xml.etree.ElementTree as ET
    from hypnomix.core.gz import read_gz
    from hypnomix.session import check as C
    from hypnomix.session import automation as aa
    out, notes = [], []
    errs, warns, facts = C.check(als)
    n = 0

    def add(kind, sev, track, problem, fix, where="", applies="manual"):
        nonlocal n
        n += 1
        out.append(dict(id=f"structure-{n}", tool="structure", kind=kind, severity=sev, track=track, where=where,
                        problem=problem, fix=fix, applies=applies))
    for e in errs:
        add("set-error", "high", "", f"the set's structure: {e}", "do not apply fixes to this set; open it in Live, "
            "save it again, and re-scan")
    for w in warns[:10]:
        add("set-warning", "info", "", f"the set's structure: {w}", "", applies="info")
    root = ET.fromstring(read_gz(als))
    tempo_el = root.find(".//Tempo/Manual")
    tempo = float(tempo_el.get("Value")) if tempo_el is not None else 120.0
    bpb = 4
    num = root.find(".//TimeSignatures/RemoteableTimeSignature/Numerator")
    if num is not None:
        bpb = int(num.get("Value"))
    where = lambda b: f"{int(b // bpb) + 1}.{int(b % bpb) + 1}.{int(round((b % 1) * 100)):02d}"
    names_ran = (Path(od) / "raw" / "names" / "names.json").exists()
    quick = bool(getattr(a, "quick", False))
    tracks = [t for t in aa.tracks(root) if t is not None]
    for t in tracks:
        name = aa.tname(t)
        on = t.find("./DeviceChain/Mixer/Speaker/Manual")
        on = on is None or on.get("Value") == "true"
        if quick and not names_ran and DEFAULT_NAME.match(name or ""):
            add("default-name", "low", name, f"default name '{name}': tools find parts by name",
                "run the full scan (the names group listens to it and proposes a name), or rename it in Live",
                applies="info")
        vol = t.find("./DeviceChain/Mixer/Volume/Manual")
        if vol is not None and on and t.tag != "MainTrack":
            v = float(vol.get("Value"))
            if v >= 1.99:
                add("fader-max", "low", name, "fader at +6 dB, the top of its range: no room to turn it up, and the "
                    "level going into the next stage is hot", "bring the fader (or the clips) down and the master up "
                    "if needed; check by ear", applies="manual")
            elif 0 < v < 10 ** (-40 / 20) and t.find(".//ArrangerAutomation/Events/AudioClip") is not None:
                add("fader-low", "info", name, f"fader at {20 * math.log10(v):.0f} dB with clips on the track: barely "
                    "heard", "", applies="info")
        if t.tag != "AudioTrack" or not on:
            continue
        clips = sorted(((float(c.find("./CurrentStart").get("Value")), float(c.find("./CurrentEnd").get("Value")), c)
                        for c in t.findall("./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events/AudioClip")
                        if c.find("./CurrentStart") is not None and c.find("./CurrentEnd") is not None
                        and (c.find("./Disabled") is None or c.find("./Disabled").get("Value") != "true")),
                       key=lambda x: x[0])
        if quick:
            boosted = [(s, c) for s, _, c in clips if c.find("./SampleVolume") is not None
                       and float(c.find("./SampleVolume").get("Value")) >= 3.98]
            if boosted:
                g = max(20 * math.log10(float(c.find("./SampleVolume").get("Value"))) for _, c in boosted)
                add("clip-boost", "low", name, f"{len(boosted)} clip(s) boosted up to +{g:.0f} dB with clip gain: the "
                    "take's own noise comes up by as much", "the full scan's noise group measures whether that noise "
                    "is audible", where=where(boosted[0][0]), applies="info")
        butt = []
        for (s0, e0, c0), (s1, e1, c1) in zip(clips, clips[1:]):
            if abs(s1 - e0) > 1e-6:
                continue
            fo = c0.find("./Fades/FadeOutLength")
            fi = c1.find("./Fades/FadeInLength")
            dfo = c0.find("./Fades/IsDefaultFadeOut")
            dfi = c1.find("./Fades/IsDefaultFadeIn")
            zero_out = fo is not None and float(fo.get("Value")) == 0 and dfo is not None and dfo.get("Value") == "false"
            zero_in = fi is not None and float(fi.get("Value")) == 0 and dfi is not None and dfi.get("Value") == "false"
            if zero_out and zero_in:
                butt.append(s1)
        if butt and quick:
            add("butt-join", "low", name, f"{len(butt)} edit(s) where two clips meet with their fades switched off: "
                "a join like that can click", "the full scan's clips group measures each join; listen at "
                + ", ".join(where(b) for b in butt[:6]), where=where(butt[0]), applies="info")
    notes.append(f"structure: {len(errs)} error(s), {len(warns)} warning(s) in the set's structure; "
                 f"{facts.get('audio_clips', '?')} audio clips, {len(tracks)} tracks")
    return out, notes


# ---------------------------------------------------------------- incremental
def keep_snapshot(als, od):
    """A copy of the scanned set, so the next scan can see what changed."""
    dest = Path(od) / "raw" / SNAPSHOT
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(als, dest)
    return dest


def changed_groups(rows, groups, role_labels=None):
    """Which groups a list of diff rows can affect. Returns (groups to re-run, why per group)."""
    role_labels = role_labels or {}
    why = {}

    def need(g, reason):
        if g in groups:
            why.setdefault(g, reason)
    vocal = lambda t: any(str(role_labels.get(t, "")).startswith(v) for v in ("Lead Vocal", "Vocal", "Harmony", "Backing"))
    for r in rows:
        tr, what = r["track"], r["what"]
        if tr == "(song)" or what in ("track added", "track removed", "renamed"):
            for g in groups:
                need(g, f"{tr}: {what}")
            continue
        need("structure", f"{tr}: {what}")
        if what.startswith(("clip", "fade in", "fade out", "warp", "notes moved")):
            need("files", f"{tr}: {what}")
            need("clips", f"{tr}: {what}")
            need("noise", f"{tr}: {what}")
            need("stems", f"{tr}: {what}")
            need("names", f"{tr}: {what}")
            if not role_labels:                       # roles unknown: either could be affected
                need("vocals", f"{tr}: {what}")
                need("timing", f"{tr}: {what}")
            else:
                need("vocals" if vocal(tr) else "timing", f"{tr}: {what}")
        elif what.startswith(("device", "automation")) or ":" in what or (" switched " in what and "track" not in what):
            need("effects", f"{tr}: {what}")
            need("devices", f"{tr}: {what}")
            need("intent", f"{tr}: {what}")
            if vocal(tr):
                need("vocals", f"{tr}: {what}")
        if what in ("fader", "pan") or what.startswith(("send", "track switched")):
            need("intent", f"{tr}: {what}")
            need("devices", f"{tr}: {what}")
            if what.startswith("track switched"):
                for g in ("clips", "timing", "vocals", "noise", "names", "effects"):
                    need(g, f"{tr}: {what}")
    return [g for g in groups if g in why], why


def fp(f):
    return (f.get("tool"), f.get("track") or "", f.get("kind") or "", f.get("where") or "", f.get("device") or "")


def remap_decisions(old_findings, new_findings, dec):
    """Decisions keyed by the new ids, matched by what each finding is. Returns (new decisions, dropped)."""
    old_by_id = {f["id"]: f for f in old_findings}
    new_by_fp = {}
    for f in new_findings:
        new_by_fp.setdefault(fp(f), []).append(f["id"])
    out, dropped = {}, {}
    for fid, d in dec.items():
        f = old_by_id.get(fid)
        cand = new_by_fp.get(fp(f)) if f else None
        if cand and len(cand) == 1:
            out[cand[0]] = d
        else:
            dropped[fid] = d
    return out, dropped
