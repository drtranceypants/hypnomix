#!/usr/bin/env python3
"""Check that every audio file a Live set uses can be found (how Live resolves it: the absolute
Path first, then RelativePath against the set's folder). Reports missing files per track.

Usage: hypnomix refs SET.als [...]   (exit code 1 if anything is missing)
"""
import gzip, sys, os, xml.etree.ElementTree as ET
from pathlib import Path


def check(als):
    als = Path(als)
    r = ET.fromstring(gzip.open(als).read())
    seen, missing, outside = 0, {}, set()
    for t in list(r.find(".//Tracks")) + [x for x in (r.find(".//MainTrack"), r.find(".//MasterTrack")) if x is not None]:
        name = t.find("./Name/EffectiveName").get("Value") if t.find("./Name/EffectiveName") is not None else "Main"
        for sr in t.iter("SampleRef"):
            fr = sr.find("./FileRef")
            if fr is None:
                continue
            p = fr.find("./Path"); rp = fr.find("./RelativePath")
            path = p.get("Value") if p is not None else ""
            rel = rp.get("Value") if rp is not None else ""
            if not path and not rel:
                continue
            seen += 1
            ok = (path and Path(path).exists()) or (rel and (als.parent / rel).exists())
            if not ok:
                missing.setdefault(name, set()).add(path or rel)
            elif path and not str(Path(path).resolve()).startswith(str(als.parent.resolve())):
                outside.add(str(Path(path).parent))
    return seen, missing, outside


if __name__ == "__main__":
    bad = 0
    for a in sys.argv[1:]:
        seen, missing, outside = check(a)
        n = sum(len(v) for v in missing.values())
        bad += n
        print(f"{'OK ' if not n else 'MISSING'} {a}: {seen} sample refs, {n} missing" + (f", uses files outside its folder: {sorted(outside)[:3]}" if outside else ""))
        for t, s in missing.items():
            print(f"   {t}: {sorted(s)[:3]}")
    sys.exit(1 if bad else 0)
