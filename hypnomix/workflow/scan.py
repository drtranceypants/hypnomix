#!/usr/bin/env python3
"""First-pass scan: run every hypnomix check on a song, change NOTHING, and write one review list.

  hypnomix scan SET.als [--mix MIX.wav] [--ref INSTRUMENTAL.wav] [--out DIR] [--only GROUP ...]
  hypnomix scan FOLDER               (raw recordings or exported stems, any DAW: no Live set needed)
  hypnomix scan --merge DIR          (rebuild REVIEW.md from group results, e.g. after parallel agents)

Your saved preferences (`hypnomix prefs`) are read first: the loudness target, tracks you protected,
things you marked as deliberate, and what you usually approve or skip are all shown in REVIEW.md.

Groups (each can run on its own with --only, so several agents can scan in parallel and --merge after):

  files    missing audio files                                  (refs)
  clips    clicks, level jumps at cuts, spikes on clips         (smooth)
  timing   instrument hits out of time with the band            (timing; tracks from `name`)
  vocals   pitch of every vocal track, harmonies vs the lead    (render + tune --report-only)
  effects  distortion in recordings and device chains,
           sidechain compressors, device-chain audit            (distortion, sidechain, audit)
  mix      loudness, true peak, release checks, translation     (measure, qc, translate; needs --mix)

A FOLDER of audio files is scanned in two groups instead:

  recordings  per file: clipping, hot or very quiet levels, noise floor, DC offset, clicks
  stems       how the files sit together: frequency fights between parts          (masking)

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
FOLDER_GROUPS = ["recordings", "stems"]
AUDIO_EXT = (".wav", ".aif", ".aiff", ".flac")
ALL_GROUPS = GROUPS + FOLDER_GROUPS
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
    for n, (tool, args) in enumerate([("measure", [a.mix, "--out", od / "raw" / "measure"]), ("qc", [a.mix]),
                                      ("translate", [a.mix])], 1):
        code, out = hx(tool, *args)
        out = strip_warnings(out)
        save(od / "raw" / f"{tool}.txt", out)
        if tool == "measure":
            findings += target_check(out)
        sev = "high" if (tool == "qc" and code != 0) else "info"
        findings.append(dict(id=f"mix-{n}", tool=tool, kind=tool, severity=sev, track="mix", where="",
                             problem=f"{tool} of the mix" + (" FAILED release checks" if sev == "high" else ""),
                             fix=out.strip()[:1500], applies="manual" if sev == "high" else "info"))
    return findings, []


def target_check(measure_out):
    """Compare the mix with the person's loudness / true-peak target (preferences, else -14 LUFS / -1 dBTP)."""
    from hypnomix.workflow import prefs as P
    t = P.load().get("targets", {})
    lufs_t, tp_t = float(t.get("lufs", -14)), float(t.get("true_peak", -1.0))
    m = re.search(r"(-?\d+(?:\.\d+)?) LUFS.*?TP (-?\d+(?:\.\d+)?) dBTP", measure_out)
    if not m:
        return []
    lufs, tp = float(m.group(1)), float(m.group(2))
    src = "your target" if t else "the default target (set yours with `hypnomix prefs`)"
    f = []
    if tp > tp_t + 0.05:
        f.append(dict(id="mix-peak", tool="measure", kind="true-peak", severity="high" if tp > 0 else "medium",
                      track="mix", where="", applies="manual",
                      problem=f"true peak {tp:+.1f} dBTP is over {src} of {tp_t:+.1f} dBTP "
                              "(lossy encodes such as AAC and MP3 overshoot further)",
                      fix=f"lower the limiter ceiling to {tp_t:.1f} dBTP, or `hypnomix master MIX.wav --target {lufs_t:g}`"))
    if abs(lufs - lufs_t) > 1.5:
        way = "louder" if lufs > lufs_t else "quieter"
        f.append(dict(id="mix-loudness", tool="measure", kind="loudness", severity="low", track="mix", where="",
                      applies="manual",
                      problem=f"the mix is {lufs:.1f} LUFS, {abs(lufs - lufs_t):.1f} LU {way} than {src} ({lufs_t:g} LUFS). "
                              "Normal for an unmastered mix; it matters for a master.",
                      fix=f"`hypnomix master MIX.wav --target {lufs_t:g}` when the mix is approved"))
    return f


# ---------------------------------------------------------------- folder of recordings (no Live set)
def audio_files(folder):
    return sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in AUDIO_EXT and not p.name.startswith("."))


def check_recording(path):
    """Plain measurements of one recording: (list of (kind, severity, problem, fix, run), facts)."""
    import numpy as np
    import soundfile as sf
    y, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if not len(y):
        return [("empty", "high", "the file has no audio", "export it again", None)], {}
    mono = y.mean(1)
    peak = float(np.abs(y).max())
    peak_db = 20 * np.log10(max(peak, 1e-9))
    blk = int(sr * 0.05)
    n = max(1, len(mono) // blk)
    rms = np.sqrt((mono[: n * blk] ** 2).reshape(n, blk).mean(1) + 1e-14)
    db = 20 * np.log10(rms)
    live = db[db > -90]  # digital silence (gaps in a render) says nothing about the noise
    out, name = [], path.name
    if not len(live):
        return [("silent", "medium", "the file is silent", "check the export (wrong track or range?)", None)], {}
    active = live[live > np.percentile(live, 95) - 30]
    level = float(np.median(active))
    floor = float(np.percentile(live, 5))
    snr = level - floor
    # clipping: runs of 3+ samples stuck at the top
    top = np.abs(y).max(1) >= max(0.985, peak * 0.9995) if peak >= 0.985 else np.zeros(len(y), bool)
    runs = int((np.diff(np.concatenate([[0], top.view(np.int8), [0]])) == 1).sum()) if top.any() else 0
    stuck = int((np.convolve(top, np.ones(3), "same") >= 3).sum()) if top.any() else 0
    clipped = runs if stuck else 0
    if clipped >= 5:
        first = float(np.argmax(top)) / sr
        out.append(("clipped", "high" if clipped >= 50 else "medium",
                    f"{clipped} clipped peaks (flattened waveform tops; first at {int(first // 60)}:{first % 60:04.1f})",
                    "re-record with lower input gain if you can; otherwise `prep` rebuilds the flattened tops "
                    "(a repair, not a cure)", None))
    elif peak_db > -0.3:
        out.append(("hot", "low", f"peaks reach {peak_db:+.1f} dBFS: no headroom",
                    "nothing to repair; record with peaks around -12 to -6 dBFS next time", None))
    if level < -45:
        out.append(("quiet", "low", f"very quiet: about {level:.0f} dBFS while playing",
                    "gain-stage it (`prep` does); raising it also raises its noise, so check the next item", None))
    dc = float(abs(mono.mean()))
    if dc > 0.003:
        out.append(("dc", "low", f"DC offset {dc * 100:.1f}% of full scale (eats headroom, clicks at edits)",
                    "remove it with a 25 Hz high-pass (`cleanup` does)",
                    ["cleanup", path, "--no-noise", "--no-hum", "--keep-ends", "--out", "{out}"]))
    steady = float(np.percentile(live, 15) - np.percentile(live, 2)) < 4  # hiss is flat; quiet music is not
    if 6 < snr < 35 and floor > -60 and steady:
        sev = "medium" if snr < 25 else "low"
        out.append(("noise", sev, f"steady noise floor around {floor:.0f} dBFS, only {snr:.0f} dB under the playing "
                    "level (hiss, room or preamp noise between phrases; check by ear that it is noise, not a pad)",
                    "gentle spectral de-hiss plus soft gate into a new file; listen for dulled highs and cut-off tails",
                    ["dehiss", path, "{out}/" + path.stem + " (dehiss).wav"]))
    return out, dict(peak_db=round(peak_db, 1), level_db=round(level, 1), floor_db=round(floor, 1))


def g_recordings(folder, od, a):
    files = audio_files(folder)
    findings, notes, facts = [], [], {}

    def one(p):
        try:
            return p, check_recording(p)
        except Exception as e:
            return p, ([("unreadable", "high", f"could not be read ({e})", "export it again as WAV", None)], {})

    n = 0
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for p, (rows, fact) in ex.map(one, files):
            facts[p.name] = fact
            for kind, sev, problem, fix, run in rows:
                n += 1
                f = dict(id=f"rec-{n}", tool=(run[0] if run else "recording"), kind=kind, severity=sev, track=p.name,
                         where="", problem=problem, fix=fix, applies="audio" if run else "manual")
                if run:
                    f["run"] = [str(x) for x in run]
                findings.append(f)
    code, out = hx("clicks", *files) if files else (0, "")
    save(od / "raw" / "clicks.txt", strip_warnings(out))
    save(od / "raw" / "recordings.json", json.dumps(facts, indent=1))
    notes.append(f"recordings: {len(files)} files measured; click report in raw/clicks.txt")
    notes.append("the whole folder can be prepared in one go (`hypnomix prep FOLDER`: copies, never the originals) "
                 "once the person has seen this list")
    return findings, notes


def g_stems(folder, od, a):
    if len(audio_files(folder)) < 2:
        return [], ["stems: fewer than two files, nothing to compare"]
    rep_md = od / "raw" / "masking.md"
    code, out = hx("masking", folder, "--out", rep_md)
    out = strip_warnings(out)
    save(od / "raw" / "masking.txt", out)
    if code != 0:
        return [], [f"masking failed: {out[-300:]}"]
    return [dict(id="stems-1", tool="masking", kind="masking", severity="info", track="", where="",
                 problem="frequency fights between the parts (who should give way, and the cut that does it)",
                 fix=out.strip()[:1800], applies="info")], []


# ---------------------------------------------------------------- merge + review
def merge(od):
    from hypnomix.workflow import prefs as P
    od = Path(od)
    prefs = P.load()
    protected = {t.lower() for t in (prefs.get("protect", {}).get("tracks") or [])}
    findings, notes, meta = [], [], {}
    for g in ALL_GROUPS:
        p = od / f"{g}.json"
        if p.exists():
            d = json.loads(p.read_text())
            for f in d["findings"]:
                f["group"] = g
            findings += d["findings"]
            notes += d.get("notes", [])
            meta[g] = d.get("seconds")
    findings.sort(key=lambda f: (SEV.get(f.get("severity"), 9), ALL_GROUPS.index(f["group"]), f.get("track", "")))
    for n, f in enumerate(findings, 1):
        f["n"] = n
        if protected and (f.get("track") or "").lower() in protected and f.get("applies") in ("set", "audio"):
            f["protected"] = True
        h = P.habit(prefs, f)
        if h:
            f["history"] = h
    sets = {json.loads((od / f"{g}.json").read_text()).get("set") for g in ALL_GROUPS if (od / f"{g}.json").exists()}
    if len(sets) > 1:
        notes.insert(0, "WARNING: the group results in this folder come from different sets or folders: "
                     + "; ".join(sorted(map(str, sets))) + ". Scan again into an empty folder.")
    setp = sorted(map(str, sets))[0] if sets else ""
    (od / "findings.json").write_text(json.dumps({"set": setp, "notes": notes, "findings": findings},
                                                 indent=1, default=str))
    write_review(od, setp, findings, notes, meta, P.summary(prefs))
    return findings, notes


def write_review(od, setp, findings, notes, meta, pref_lines=()):
    counts = {s: sum(1 for f in findings if f.get("severity") == s) for s in SEV}
    L = [f"# First-pass review: {Path(setp).stem if setp else od.name}", "",
         f"Set: `{setp}`  ", "Nothing has been changed. Go through the items one at a time: **approve**, **skip** "
         "or **change** each, then `hypnomix fix` writes every approved set change into ONE new set.", "",
         f"**{len(findings)} findings:** {counts['high']} high, {counts['medium']} medium, {counts['low']} low, "
         f"{counts['info']} info", ""]
    if pref_lines:
        L += ["## Your preferences", ""] + [f"- {x}" for x in pref_lines] + [""]
    else:
        L += ["_No preferences saved yet: `hypnomix prefs questions` (loudness target, protected tracks, "
              "how you like to review)._", ""]
    L += ["| group | findings | scan time |", "|---|---|---|"]
    for g in ALL_GROUPS:
        n = sum(1 for f in findings if f["group"] == g)
        if g in meta:
            L.append(f"| {g} | {n} | {meta[g] or 0:.0f} s |")
    broken = [n for n in notes if "failed" in n or n.startswith("WARNING")]
    notes = [n for n in notes if n not in broken]
    if broken:
        L += ["", "## Checks that did NOT run (so 'no findings' there means nothing)", ""] + [f"- {n}" for n in broken]
    if notes:
        L += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    L += ["", "## Items (most severe first)", ""]
    for f in findings:
        where = f" @ {f['where']}" if f.get("where") else ""
        also = f" (same audio again at {', '.join(f['also_at'][:5])})" if f.get("also_at") else ""
        L.append(f"### {f['n']}. [{f.get('severity')}] {f['tool']}: {f.get('track') or '-'}{where}{also}")
        L.append(f"- id: `{f['id']}` · applies: **{f.get('applies')}**"
                 + (" · **PROTECTED track: ask again before changing**" if f.get("protected") else ""))
        if f.get("history"):
            L.append(f"- history: {f['history']}")
        L.append(f"- problem: {f.get('problem')}")
        fix = str(f.get("fix", "")).strip()
        L.append(f"- proposed fix: {fix}" if "\n" not in fix else "- proposed fix:\n\n```\n" + fix + "\n```")
        if f.get("flagged_notes"):
            L.append(f"- notes to check by ear: " + ", ".join(f"{x['time']} {x['sung']} ({x['cents']:+d}c)"
                                                           for x in f["flagged_notes"][:12]))
        L.append("- decision: [ ] approve  [ ] skip  [ ] change: ")
        L.append("")
    L += ["## Apply", "", "```", f'hypnomix fix "{od}" --decide ID=approve,ID=skip      # record each decision',
          f'hypnomix fix "{od}" --approved --out "<Song> (fixed).als"   # apply only what was approved', "```",
          "Close the set in Live first. `fix` writes approved *set* changes in one new set next to the original; "
          "*audio* items become new files (originals untouched); *manual* items are listed for you. It looks every "
          "finding up again before changing anything and measures the result afterwards."]
    (od / "REVIEW.md").write_text("\n".join(L) + "\n")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(prog="hypnomix scan", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als", nargs="?", metavar="SET.als|FOLDER")
    ap.add_argument("--mix", help="a bounce of the full mix (loudness, true peak, release checks)")
    ap.add_argument("--ref", help="mix or instrumental for tuning and key (vocals); defaults to --mix")
    ap.add_argument("--key", help='song key for the vocal check, e.g. "F# major"')
    ap.add_argument("--out", help="output folder (default hypnomix-out/scan/<song>)")
    ap.add_argument("--only", action="append", choices=ALL_GROUPS, help="run only these groups (repeatable)")
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
    als = Path(a.als).expanduser().resolve()
    if not als.exists():
        sys.exit(f"not found: {als}")
    folder = als.is_dir()
    if folder and not audio_files(als):
        sys.exit(f"no audio files (wav, aif, flac) in {als}")
    od = out_at(a.out, "scan", als.stem if not folder else als.name)
    mine = FOLDER_GROUPS if folder else GROUPS
    groups = a.only or mine
    wrong = [g for g in groups if g not in mine]
    if wrong:
        sys.exit(f"{', '.join(wrong)}: not a group for a {'folder' if folder else 'Live set'} (use {', '.join(mine)})")
    info = {"set": str(als), "mode": "folder" if folder else "set", "mix": a.mix, "ref": a.ref, "key": a.key,
            "set_mtime": als.stat().st_mtime}
    (od / "raw").mkdir(exist_ok=True)
    sj = od / "scan.json"
    if sj.exists():  # parallel --only runs share this file: keep what another run already recorded
        old = json.loads(sj.read_text())
        if old.get("set") == info["set"]:
            info = {k: (v if v is not None else old.get(k)) for k, v in info.items()}
    sj.write_text(json.dumps(info, indent=1))
    print(f"scanning {als.name}: {', '.join(groups)} → {od}")
    role = roles(als, od) if {"timing", "vocals"} & set(groups) else {}
    if role:
        vox = [t for t, r in role.items() if is_vocal(r["label"])]
        print(f"  track roles from `name`: {len(vox)} vocal, {len(role) - len(vox)} other")

    def run(g):
        t0 = time.time()
        fn = {"files": lambda: g_files(als, od, a), "clips": lambda: g_clips(als, od, a),
              "timing": lambda: g_timing(als, od, a, role), "vocals": lambda: g_vocals(als, od, a, role),
              "effects": lambda: g_effects(als, od, a), "mix": lambda: g_mix(als, od, a),
              "recordings": lambda: g_recordings(als, od, a), "stems": lambda: g_stems(als, od, a)}[g]
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
    broken = [n for n in notes if "failed" in n]
    if broken:
        print(f"\n{len(broken)} check(s) did NOT run: tell the person, and do not call those areas clean:")
        for n in broken:
            print("  - " + n[:200].replace("\n", " "))


if __name__ == "__main__":
    main()
