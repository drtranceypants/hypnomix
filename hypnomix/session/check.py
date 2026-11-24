#!/usr/bin/env python3
"""Check that a Live set written by a tool is structurally sound BEFORE anyone opens it in Live.

  hypnomix check NEW.als [--against ORIGINAL.als] [--json OUT.json]

What it checks (errors make the exit code 1; warnings don't):
  file        it is gzipped XML with an <Ableton> root and a version
  ids         every automation / modulation target id is unique and below NextPointeeId (Live refuses or
              mis-wires a set with duplicate ids); children that carry an Id are unique among their siblings
  envelopes   every automation envelope points at a target that exists; its points are in time order
  clips       end after start; warp markers in increasing order (seconds and beats), at least two on a
              warped clip; fades not negative and not longer than the clip; no two clips overlapping on a track
  audio       every referenced audio file is found (warning: a missing file is the person's to locate)
  --against   the same Live version wrote both; the same tracks in the same order; NextPointeeId did not
              go down; which tracks changed their clip count (warning)

It cannot prove Live will open the set: only Live can. It catches the ways a script usually breaks one.
`hypnomix fix` runs it on every set it writes.
"""
import argparse, gzip, json, math, sys
import xml.etree.ElementTree as ET
from pathlib import Path


def is_pointee(tag):
    return tag.endswith("Target") or tag == "Pointee"


def load_root(path):
    try:
        raw = gzip.open(path).read()
    except OSError as e:
        return None, f"not a gzip file ({e})"
    try:
        return ET.fromstring(raw), None
    except ET.ParseError as e:
        return None, f"the XML does not parse ({e})"


def track_name(t):
    n = t.find("./Name/EffectiveName")
    return n.get("Value") if n is not None else t.tag


def all_tracks(root):
    ts = root.find(".//Tracks")
    return list(ts) if ts is not None else []


def check(path, against=None, renamed=None):
    """Returns (errors, warnings, facts). Empty errors = structurally sound."""
    err, warn, facts = [], [], {}
    root, problem = load_root(path)
    if root is None:
        return [problem], [], {}
    if root.tag != "Ableton":
        err.append(f"root element is <{root.tag}>, not <Ableton>")
    facts["creator"], facts["minor"] = root.get("Creator"), root.get("MinorVersion")
    if not facts["minor"]:
        err.append("no MinorVersion on the root element")

    # ---- pointee ids
    npi = root.find(".//NextPointeeId")
    next_id = int(npi.get("Value")) if npi is not None and (npi.get("Value") or "").isdigit() else None
    facts["next_pointee_id"] = next_id
    seen, dup = {}, set()
    for e in root.iter():
        if is_pointee(e.tag) and (e.get("Id") or "").isdigit():
            i = int(e.get("Id"))
            if i in seen:
                dup.add(i)
            seen[i] = e.tag
    if dup:
        err.append(f"{len(dup)} duplicate automation/modulation target ids (e.g. {sorted(dup)[:5]})")
    if next_id is None:
        err.append("NextPointeeId is missing")
    elif seen and max(seen) >= next_id:
        err.append(f"a target id ({max(seen)}) is not below NextPointeeId ({next_id}): new ids would collide")
    facts["targets"] = len(seen)

    # ---- sibling ids
    bad_sib = 0
    example = ""
    for parent in root.iter():
        ids = {}
        for c in parent:
            if c.get("Id") is not None:
                k = (c.tag, c.get("Id"))
                if k in ids:
                    bad_sib += 1
                    example = example or f"<{c.tag} Id={c.get('Id')}> twice inside <{parent.tag}>"
                ids[k] = 1
    if bad_sib:
        err.append(f"{bad_sib} elements share an Id with a sibling ({example})")

    # ---- envelopes
    n_env = 0
    for env in root.iter("AutomationEnvelope"):
        n_env += 1
        pid = env.find("./EnvelopeTarget/PointeeId")
        if pid is None or not (pid.get("Value") or "").lstrip("-").isdigit():
            err.append("an automation envelope has no target id")
            continue
        if int(pid.get("Value")) not in seen:
            err.append(f"an automation envelope points at id {pid.get('Value')}, which no control has")
        ev = env.find("./Automation/Events")
        times = [float(x.get("Time")) for x in ev if x.get("Time") is not None] if ev is not None else []
        vals = [x.get("Value") for x in ev if x.get("Value") is not None] if ev is not None else []
        if any(b < a - 1e-9 for a, b in zip(times, times[1:])):
            err.append(f"automation points out of time order (target id {pid.get('Value')})")
        for v in vals:
            try:
                if not math.isfinite(float(v)):
                    err.append(f"an automation point is not a number (target id {pid.get('Value')})")
                    break
            except ValueError:
                pass  # booleans and enums are stored as text
    facts["envelopes"] = n_env

    # ---- clips
    n_clips = 0
    per_track = {}
    for t in all_tracks(root):
        name = track_name(t)
        spans = []
        for c in t.findall(".//ArrangerAutomation/Events/AudioClip"):
            n_clips += 1
            g = lambda p: (c.find(p).get("Value") if c.find(p) is not None else None)
            try:
                s, e = float(g("./CurrentStart")), float(g("./CurrentEnd"))
            except (TypeError, ValueError):
                err.append(f"{name}: a clip has no start or end")
                continue
            at = f"{name} @ beat {s:g}"
            if e <= s:
                err.append(f"{at}: clip ends before it starts")
            spans.append((s, e))
            wm = [(float(w.get("SecTime")), float(w.get("BeatTime"))) for w in c.iter("WarpMarker")]
            if g("./IsWarped") == "true":
                if len(wm) < 2:
                    err.append(f"{at}: warped clip with fewer than two warp markers")
                if any(b[0] <= a[0] or b[1] <= a[1] for a, b in zip(wm, wm[1:])):
                    err.append(f"{at}: warp markers are not in increasing order (audio would play backwards or stall)")
            for lab, p in (("fade in", "./Fades/FadeInLength"), ("fade out", "./Fades/FadeOutLength")):
                fv = g(p)
                if fv is not None:
                    fv = float(fv)
                    if fv < 0:
                        err.append(f"{at}: negative {lab}")
                    elif fv > (e - s) + 1e-6:
                        warn.append(f"{at}: {lab} is longer than the clip")
            sv = g("./SampleVolume")
            if sv is not None and not (0 <= float(sv) < 1000):
                err.append(f"{at}: clip gain {sv} is out of range")
        spans.sort()
        for (s0, e0), (s1, e1) in zip(spans, spans[1:]):
            if s1 < e0 - 1e-6:
                warn.append(f"{name}: clips overlap around beat {s1:g}")
                break
        per_track[name] = len(spans)
    facts["audio_clips"], facts["tracks"] = n_clips, len(per_track)

    # ---- audio files
    try:
        from hypnomix.session import refs
        _, missing, _ = refs.check(str(path))
        n = sum(len(v) for v in missing.values())
        if n:
            warn.append(f"{n} audio files are not found from this location (Live will ask you to locate them)")
    except Exception as e:  # the reference check is a courtesy here
        warn.append(f"audio references not checked ({e})")

    # ---- against the original
    if against:
        r0, p0 = load_root(against)
        if r0 is None:
            warn.append(f"could not read the original to compare ({p0})")
        else:
            if r0.get("MinorVersion") != root.get("MinorVersion") or r0.get("Creator") != root.get("Creator"):
                err.append(f"version changed: {r0.get('Creator')} → {root.get('Creator')}")
            ren = renamed or {}                      # renames the person approved are expected changes
            a = [(t.tag, ren.get(track_name(t), track_name(t))) for t in all_tracks(r0)]
            b = [(t.tag, track_name(t)) for t in all_tracks(root)]
            if a != b:
                err.append(f"the track list changed ({len(a)} → {len(b)} tracks, or their order or names)")
            n0 = r0.find(".//NextPointeeId")
            if n0 is not None and next_id is not None and next_id < int(n0.get("Value")):
                err.append("NextPointeeId went down")
            old = {}
            for t in all_tracks(r0):
                old[track_name(t)] = len(t.findall(".//ArrangerAutomation/Events/AudioClip"))
            moved = [f"{k} ({old[k]} → {v})" for k, v in per_track.items() if k in old and old[k] != v]
            if moved:
                warn.append("clip count changed on: " + ", ".join(moved[:6]))
    return err, warn, facts


def main():
    ap = argparse.ArgumentParser(prog="hypnomix check", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als")
    ap.add_argument("--against", metavar="ORIGINAL.als", help="the set this one was written from")
    ap.add_argument("--json", metavar="OUT.json")
    a = ap.parse_args()
    err, warn, facts = check(a.als, a.against)
    if a.json:
        Path(a.json).write_text(json.dumps(dict(set=str(a.als), ok=not err, errors=err, warnings=warn, facts=facts), indent=1))
    name = Path(a.als).name
    print(f"{name}: {facts.get('creator') or '?'}; {facts.get('tracks', 0)} tracks, {facts.get('audio_clips', 0)} "
          f"audio clips, {facts.get('envelopes', 0)} automation envelopes, {facts.get('targets', 0)} targets")
    for e in err:
        print(f"  ERROR   {e}")
    for w in warn:
        print(f"  warning {w}")
    if err:
        print(f"\n{len(err)} error(s): do NOT open this set in Live. Keep the original and report the errors.")
        sys.exit(1)
    print("\nstructure OK" + (f" ({len(warn)} warning(s))" if warn else "")
          + ". Only Live can confirm it opens: keep the original until it has.")


if __name__ == "__main__":
    main()
