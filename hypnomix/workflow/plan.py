"""Shared by `prep --plan`, `automix --plan` and `master --plan`: turn a tool's moves into review findings.

A plan changes nothing. It writes the moves the tool WOULD make into a scan folder as findings, so they go
through the same review as everything else (REVIEW.md, `hypnomix review`, decisions.json), and
`hypnomix fix DIR --approved` then runs the tool with only the approved moves, into DIR/fixed/.
"""
import json
from pathlib import Path

from hypnomix.core.paths import out_at

PLAN_GROUPS = ["prep", "automix", "master"]


def scan_dir(custom, source, suffix=""):
    """--plan with a folder name uses it; bare --plan uses hypnomix-out/scan/<source name>."""
    src = Path(source)
    name = (src.name if src.is_dir() else src.stem) + suffix
    return out_at(custom if isinstance(custom, str) and custom else None, "scan", name)


def write(od, group, source, findings, notes, seconds=0.0):
    od = Path(od)
    (od / "raw").mkdir(parents=True, exist_ok=True)
    src = Path(source).resolve()
    for n, f in enumerate(findings, 1):
        f.setdefault("id", f"{group}-{n}")
        f.setdefault("tool", group)
        f.setdefault("where", "")
        f.setdefault("applies", "audio")
    (od / f"{group}.json").write_text(json.dumps({"group": group, "set": str(src), "seconds": seconds,
                                                  "findings": findings, "notes": notes}, indent=1, default=str))
    sj = od / "scan.json"
    info = json.loads(sj.read_text()) if sj.exists() else {}
    if info.get("set") in (None, str(src)):
        info.update(set=str(src), mode="folder" if src.is_dir() else "file", set_mtime=src.stat().st_mtime)
        sj.write_text(json.dumps(info, indent=1))
    from hypnomix.workflow import scan
    all_f, _ = scan.merge(od)
    print(f"{len(findings)} proposed move(s) from {group}; nothing was changed.\nreview: {od / 'REVIEW.md'}")
    print(f'next: hypnomix ab "{od}"  ·  hypnomix review "{od}"  ·  hypnomix fix "{od}" --approved')
    return od
