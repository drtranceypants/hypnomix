#!/usr/bin/env python3
"""First-pass scan: run every hypnomix check on a song, change NOTHING, and write one review list.

  hypnomix scan SET.als [--mix MIX.wav] [--ref INSTRUMENTAL.wav] [--out DIR] [--only GROUP ...]
  hypnomix scan --merge DIR          (rebuild REVIEW.md from group results, e.g. after parallel agents)

Groups (each can run on its own with --only, so several agents can scan in parallel and --merge after):

  files    missing audio files                                  (refs)
  clips    clicks, level jumps at cuts, spikes on clips         (smooth)
  timing   instrument hits out of time with the band            (timing; tracks from `name`)
  vocals   pitch of every vocal track, harmonies vs the lead    (render + tune --report-only)
  effects  distortion in recordings and device chains,
           sidechain compressors, device-chain audit            (distortion, sidechain, audit)
  mix      loudness, true peak, release checks, translation     (measure, qc, translate; needs --mix)

Output folder (default hypnomix-out/scan/<song>/):
  <group>.json      normalised findings from that group (id, severity, track, where, problem, fix, applies)
  raw/              each tool's own output (text and JSON), renders of the vocal tracks
  findings.json     every finding, sorted most severe first
  REVIEW.md         the same as a checklist for a human: one item at a time, nothing applied yet

Each finding says how it is fixed:
  set     a change to the Live set that `hypnomix fix` can write into ONE new set (smooth, timing,
          distortion, sidechain). The original set is never touched.
  audio   a new audio file (tune); you swap it in Live.
  manual  needs your hands or ears in Live; the finding says what to do.
  info    a measurement to know about; nothing to apply.

Tip: --ref should be the song's mix or instrumental (tuning and key for the vocal check). Without it
the vocals are measured against their own average tuning, which under-corrects a flat singer.
"""
import argparse, json, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from hypnomix.core.paths import out_at

GROUPS = ["files", "clips", "timing", "vocals", "effects", "mix"]
SEV = {"high": 0, "medium": 1, "low": 2, "info": 3}
VOCAL_LABELS = ("Lead Vocal", "Vocal", "Harmony", "Backing Vocal")


def hx(*args, timeout=3600):
    """Run a hypnomix command; return (exit code, stdout+stderr text)."""
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)],
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "") + (("\n" + r.stderr) if r.stderr.strip() else "")


def save(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text)


def strip_warnings(text):
    return "\n".join(l for l in text.splitlines() if "Warning" not in l and "warnings.warn" not in l)


# ---------------------------------------------------------------- track roles
def roles(als, od):
    """Track name -> role label from `hypnomix name` (written once, reused by every group)."""
    path = od / "raw" / "names" / "names.json"
    if not path.exists():
        code, out = hx("name", als, "--out", od / "raw" / "names")
        save(od / "raw" / "names.txt", strip_warnings(out))
        if code != 0 or not path.exists():
            return {}
    rows = json.loads(path.read_text()).get("tracks", [])
    return {r["old"]: dict(label=str(r.get("final") or r.get("label") or ""), kind=r.get("kind", ""),
                           active=float((r.get("features") or {}).get("active_s") or 0))
            for r in rows}


def tracks_on(als):
    """Names of tracks whose activator is on (switched-off tracks aren't heard, so aren't checked)."""
    from hypnomix.session import automation as aa
    from hypnomix.session.smooth import track_on
    root = aa.load(als).getroot()
    return {t.find("./Name/EffectiveName").get("Value") for t in root.find(".//Tracks")
            if t.find("./Name/EffectiveName") is not None and track_on(t)}


def is_vocal(label):
    return any(label.startswith(v) for v in VOCAL_LABELS)


# ---------------------------------------------------------------- groups
def g_files(als, od, a):
    code, out = hx("refs", als)
    save(od / "raw" / "refs.txt", out)
    f = []
    for n, line in enumerate(l for l in out.splitlines() if "MISSING" in l and ":" in l):
        f.append(dict(id=f"files-{n + 1}", tool="refs", kind="missing-audio", severity="high", track="",
                      where="", problem=line.strip(), applies="manual",
                      fix="find the missing files (Live: File > Manage Files > Locate) before anything else"))
    return f, []


def g_clips(als, od, a):
    j = od / "raw" / "smooth.json"
    code, out = hx("smooth", als, "--json", j)
    save(od / "raw" / "smooth.txt", strip_warnings(out))
    if not j.exists():
        return [], [f"smooth failed: {out[-300:]}"]
    d = json.loads(j.read_text())
    notes = []
    if d["notes"].get("regular"):
        notes.append("spikes not checked on tracks with regular hits (drums): " + ", ".join(d["notes"]["regular"]))
    return d["findings"], notes


def g_timing(als, od, a, role):
    tracks = [t for t, r in role.items() if r["kind"] in ("Audio", "AudioTrack", "") and not is_vocal(r["label"])
              and "Group" not in r["label"]]
    if a.timing_track:
        tracks = a.timing_track
    if not tracks:
        return [], ["timing: no instrument tracks found (name them, or pass --timing-track)"]
    j = od / "raw" / "timing.json"
    args = ["timing", als, "--json", j, "--list", "0"]
    for t in tracks:
        args += ["--track", t]
    code, out = hx(*args)
    save(od / "raw" / "timing.txt", strip_warnings(out))
    if not j.exists():
        return [], [f"timing failed: {out[-300:]}"]
    d = json.loads(j.read_text())
    notes = [f"timing: song looseness {d['looseness_ms']} ms across {len(d['tracks'])} instrument tracks "
             f"(the band's natural feel; only outliers are listed)"]
    return d["findings"], notes


def g_vocals(als, od, a, role):
    on = tracks_on(als)
    vox = [t for t, r in role.items() if is_vocal(r["label"]) and t in on]
    if a.vocal_track:
        vox = a.vocal_track
    if not vox:
        return [], ["vocals: no vocal tracks found (name them, or pass --vocal-track)"]
    rd = od / "raw" / "renders"
    code, out = hx("render", als, "--tracks", *vox, "--out", rd)
    save(od / "raw" / "render-vocals.txt", strip_warnings(out))
    files = {t: rd / (re.sub(r'[\\/:*?"<>|]', "-", t) + ".wav") for t in vox}
    files = {t: p for t, p in files.items() if p.exists()}
    lead = a.lead_track or next((t for t in vox if role.get(t, {}).get("label") == "Lead Vocal"), None)
    if not lead and files:  # `name` didn't single one out: the vocal that sings the most is the lead
        lead = max(files, key=lambda t: sung_seconds(files[t]))
    findings, notes = [], []

    def one(item):
        t, p = item
        j = od / "raw" / f"tune-{p.stem}.json"
        args = ["tune", p, "--report-only", "--json", j]
        if a.ref:
            args += ["--ref", a.ref]
        if a.key:
            args += ["--key", a.key]
        if lead and t != lead and lead in files:
            args += ["--guide", files[lead]]
        code, out = hx(*args)
        save(od / "raw" / f"tune-{p.stem}.txt", strip_warnings(out))
        return t, j, out

    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for t, j, out in ex.map(one, files.items()):
            if not j.exists():
                notes.append(f"tune failed on {t}: {out[-200:]}")
                continue
            d = json.loads(j.read_text())
            for f in d["findings"]:
                f["track"] = t
                f["key"], f["tuning_cents"] = d["key"], d["tuning_cents"]
                f["flagged_notes"] = d["flagged"]
                findings.append(f)
            if not a.ref and not any("tuning measured from the singer" in n for n in notes):
                notes.append("vocals: tuning measured from the singers themselves; give --ref MIX.wav for a "
                             "reliable grid")
    if findings:
        notes.append(f"vocals: key {findings[0]['key']} (confirm it before tuning: --key); lead taken as "
                     f"'{lead}' (harmonies are checked against it; --lead-track to change)")
    return findings, notes


def sung_seconds(path, floor_db=-45.0):
    import numpy as np
    import soundfile as sf
    y, sr = sf.read(str(path), dtype="float32", always_2d=True)
    blk = int(sr * 0.05)
    n = len(y) // blk
    rms = np.sqrt((y[: n * blk].mean(1) ** 2).reshape(n, blk).mean(1) + 1e-12)
    return float((20 * np.log10(rms) > floor_db).sum() * 0.05)


def g_effects(als, od, a):
    findings, notes = [], []
    j = od / "raw" / "distortion.json"
    args = ["distortion", als, "--json", j]
    if a.mix:
        args += ["--mix", a.mix]
    code, out = hx(*args)
    save(od / "raw" / "distortion.txt", strip_warnings(out))
    if j.exists():
        d = json.loads(j.read_text())
        for f in d.get("findings", []):
            fid = (f.get("evidence") or {}).get("id")
            pure = bool(f.get("changes"))
            findings.append(dict(id=fid, tool="distortion", kind=f["kind"], severity=f["severity"],
                                 track=f["track"], where=f.get("where", ""), device=f.get("device", ""),
                                 problem=f["cause"], fix=f["fix"], applies="set" if pure else "manual",
                                 changes=f.get("changes", [])))
    else:
        notes.append(f"distortion failed: {out[-300:]}")

    code, out = hx("sidechain", als, "--out", od / "raw" / "sidechain")
    out = strip_warnings(out)
    save(od / "raw" / "sidechain.txt", out)
    blocks = re.split(r"\n(?=\[\d+\] )", out)
    for b in blocks[1:]:
        head = b.splitlines()[0]
        m = re.match(r"\[(\d+)\] (.+?)\s+<-\s+(.+)", head)
        host = m.group(2).strip() if m else head
        body = "\n".join(l.strip() for l in b.splitlines()[1:] if l.strip())
        has_sug = "suggest" in body.lower()
        glue = "now: Glue" in body
        fix = body[:900]
        if glue:
            fix = ("switch this Glue Compressor to Live's Compressor (+1 ms lookahead), with these settings:\n"
                   + fix)
        findings.append(dict(id=f"sidechain-{m.group(1) if m else len(findings)}", tool="sidechain",
                             kind="sidechain", severity="medium" if (has_sug or glue) else "info", track=host,
                             where="", problem=head, fix=fix,
                             applies="set" if (has_sug or glue) else "info", host=host, glue=glue))

    code, out = hx("audit", als)
    out = strip_warnings(out)
    save(od / "raw" / "audit.txt", out)
    if out.strip():
        findings.append(dict(id="audit-1", tool="audit", kind="audit", severity="info", track="", where="",
                             problem="device-chain audit (EQ, stacked limiters, bypassed devices)",
                             fix=out.strip()[:1500], applies="info"))
    return findings, notes


def g_mix(als, od, a):
    if not a.mix:
        return [], ["mix: skipped (give --mix MIX.wav for loudness, true peak, qc and translation)"]
    findings = []
    for n, (tool, args) in enumerate([("measure", [a.mix]), ("qc", [a.mix]), ("translate", [a.mix])], 1):
        code, out = hx(tool, *args)
        out = strip_warnings(out)
        save(od / "raw" / f"{tool}.txt", out)
        sev = "high" if (tool == "qc" and code != 0) else "info"
        findings.append(dict(id=f"mix-{n}", tool=tool, kind=tool, severity=sev, track="mix", where="",
                             problem=f"{tool} of the mix" + (" FAILED release checks" if sev == "high" else ""),
                             fix=out.strip()[:1500], applies="manual" if sev == "high" else "info"))
    return findings, []


# ---------------------------------------------------------------- merge + review
def merge(od):
    od = Path(od)
    findings, notes, meta = [], [], {}
    for g in GROUPS:
        p = od / f"{g}.json"
        if p.exists():
            d = json.loads(p.read_text())
            for f in d["findings"]:
                f["group"] = g
            findings += d["findings"]
            notes += d.get("notes", [])
            meta[g] = d.get("seconds")
    findings.sort(key=lambda f: (SEV.get(f.get("severity"), 9), GROUPS.index(f["group"]), f.get("track", "")))
    for n, f in enumerate(findings, 1):
        f["n"] = n
    setp = next((json.loads((od / f"{g}.json").read_text()).get("set") for g in GROUPS
                 if (od / f"{g}.json").exists()), "")
    (od / "findings.json").write_text(json.dumps({"set": setp, "notes": notes, "findings": findings},
                                                 indent=1, default=str))
    write_review(od, setp, findings, notes, meta)
    return findings, notes


def write_review(od, setp, findings, notes, meta):
    counts = {s: sum(1 for f in findings if f.get("severity") == s) for s in SEV}
    L = [f"# First-pass review: {Path(setp).stem if setp else od.name}", "",
         f"Set: `{setp}`  ", "Nothing has been changed. Go through the items one at a time: **approve**, **skip** "
         "or **change** each, then `hypnomix fix` writes every approved set change into ONE new set.", "",
         f"**{len(findings)} findings:** {counts['high']} high, {counts['medium']} medium, {counts['low']} low, "
         f"{counts['info']} info", "", "| group | findings | scan time |", "|---|---|---|"]
    for g in GROUPS:
        n = sum(1 for f in findings if f["group"] == g)
        if g in meta:
            L.append(f"| {g} | {n} | {meta[g] or 0:.0f} s |")
    if notes:
        L += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    L += ["", "## Items (most severe first)", ""]
    for f in findings:
        where = f" @ {f['where']}" if f.get("where") else ""
        also = f" (same audio again at {', '.join(f['also_at'][:5])})" if f.get("also_at") else ""
        L.append(f"### {f['n']}. [{f.get('severity')}] {f['tool']}: {f.get('track') or '-'}{where}{also}")
        L.append(f"- id: `{f['id']}` · applies: **{f.get('applies')}**")
        L.append(f"- problem: {f.get('problem')}")
        fix = str(f.get("fix", "")).strip()
        L.append(f"- proposed fix: {fix}" if "\n" not in fix else "- proposed fix:\n\n```\n" + fix + "\n```")
        if f.get("flagged_notes"):
            L.append(f"- notes to check by ear: " + ", ".join(f"{x['time']} {x['sung']} ({x['cents']:+d}c)"
                                                           for x in f["flagged_notes"][:12]))
        L.append("- decision: [ ] approve  [ ] skip  [ ] change: ")
        L.append("")
    L += ["## Apply", "", "```", f'hypnomix fix "{od}" --approve ID,ID,... --out "<Song> (fixed).als"', "```",
          "Close the set in Live first. `fix` writes approved *set* changes in one new set next to the original; "
          "*audio* items (tune) are rendered to new files with instructions; *manual* items are listed for you."]
    (od / "REVIEW.md").write_text("\n".join(L) + "\n")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(prog="hypnomix scan", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als", nargs="?")
    ap.add_argument("--mix", help="a bounce of the full mix (loudness, true peak, release checks)")
    ap.add_argument("--ref", help="mix or instrumental for tuning and key (vocals); defaults to --mix")
    ap.add_argument("--key", help='song key for the vocal check, e.g. "F# major"')
    ap.add_argument("--out", help="output folder (default hypnomix-out/scan/<song>)")
    ap.add_argument("--only", action="append", choices=GROUPS, help="run only these groups (repeatable)")
    ap.add_argument("--vocal-track", action="append", help="vocal tracks to check (default: from `name`)")
    ap.add_argument("--lead-track", help="the lead vocal (default: from `name`, else the vocal that sings most)")
    ap.add_argument("--timing-track", action="append", help="instrument tracks for timing (default: from `name`)")
    ap.add_argument("--jobs", type=int, default=4, help="parallel jobs (default 4)")
    ap.add_argument("--merge", metavar="DIR", help="only rebuild findings.json + REVIEW.md from DIR")
    a = ap.parse_args()
    if a.merge:
        findings, notes = merge(a.merge)
        print(f"{len(findings)} findings → {Path(a.merge) / 'REVIEW.md'}")
        return
    if not a.als:
        ap.error("give a set (.als), or --merge DIR")
    a.ref = a.ref or a.mix
    als = Path(a.als).resolve()
    od = out_at(a.out, "scan", als.stem)
    groups = a.only or GROUPS
    (od / "scan.json").write_text(json.dumps({"set": str(als), "mix": a.mix, "ref": a.ref, "key": a.key},
                                             indent=1))
    print(f"scanning {als.name}: {', '.join(groups)} → {od}")
    role = roles(als, od) if {"timing", "vocals"} & set(groups) else {}
    if role:
        vox = [t for t, r in role.items() if is_vocal(r["label"])]
        print(f"  track roles from `name`: {len(vox)} vocal, {len(role) - len(vox)} other")

    def run(g):
        t0 = time.time()
        fn = {"files": lambda: g_files(als, od, a), "clips": lambda: g_clips(als, od, a),
              "timing": lambda: g_timing(als, od, a, role), "vocals": lambda: g_vocals(als, od, a, role),
              "effects": lambda: g_effects(als, od, a), "mix": lambda: g_mix(als, od, a)}[g]
        try:
            f, notes = fn()
        except Exception as e:  # one failing check must not sink the scan
            f, notes = [], [f"{g}: failed ({e})"]
        secs = time.time() - t0
        (od / f"{g}.json").write_text(json.dumps({"group": g, "set": str(als), "seconds": secs,
                                                  "findings": f, "notes": notes}, indent=1, default=str))
        print(f"  {g:<8} {len(f):4d} findings  ({secs:.0f} s)")
        return g

    with ThreadPoolExecutor(max_workers=max(1, min(a.jobs, len(groups)))) as ex:
        list(ex.map(run, groups))
    findings, notes = merge(od)
    counts = {s: sum(1 for f in findings if f.get("severity") == s) for s in SEV}
    print(f"\n{len(findings)} findings ({counts['high']} high, {counts['medium']} medium, {counts['low']} low, "
          f"{counts['info']} info). Nothing was changed.\nreview: {od / 'REVIEW.md'}")


if __name__ == "__main__":
    main()
