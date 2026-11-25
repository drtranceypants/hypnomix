#!/usr/bin/env python3
"""First-pass scan: run every hypnomix check on a song, change NOTHING, and write one review list.

  hypnomix scan SET.als [--mix MIX.wav] [--ref INSTRUMENTAL.wav] [--out DIR] [--only GROUP ...]
  hypnomix scan SONG.rpp             (a REAPER project: see `hypnomix.workflow.scan_project` for its groups)
  hypnomix scan SONG.ardour          (an Ardour session, or its session folder: the same groups as REAPER)
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
  noise    takes whose big clip-gain boost lifts their noise floor into the mix
  intent   "is this deliberate?": every automated control, big clip gains, hard pans, switched-off tracks
  structure  the set's structure and level extremes, from the XML alone
  stems    with --deep only (renders every track): frequency fights between tracks, mic phase and polarity

Faster scans:
  --quick        only the groups that read the set itself (files, intent, structure; no rendering, no audio
                 analysis): seconds, for a check while you work
  --since DIR    incremental: compare the set with the copy DIR's scan kept (raw/scanned.als), re-run only the
                 groups the changes can affect, keep DIR's other findings (marked carried; new ones marked new).
                 Decisions follow their findings. Combine with --quick. `hypnomix watch SET.als` does this on
                 every save.

The vocals group also measures how far doubles and harmonies sit from the lead in time (vocalign).

A FOLDER of audio files is scanned in two groups instead:

  recordings  per file: clipping, hot or very quiet levels, noise floor, DC offset, clicks
  stems       how the files sit together: each frequency fight between two parts as its own finding
              (masking), and phase / polarity between files that record the same source (align)

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
import argparse, json, re, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from hypnomix.core.paths import out_at

GROUPS = ["names", "files", "clips", "timing", "vocals", "effects", "devices", "mix", "noise", "intent", "structure", "stems"]
FOLDER_GROUPS = ["recordings", "stems"]
AUDIO_EXT = (".wav", ".aif", ".aiff", ".flac")
PLAN_GROUPS = ["prep", "automix", "master", "motion", "borrow"]         # written by `prep|automix|master --plan`
ALL_GROUPS = list(dict.fromkeys(GROUPS + FOLDER_GROUPS + PLAN_GROUPS + ["recordings"]))
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


MELODIC_LABELS = ("Guitar", "Keys", "Piano", "Strings", "Synth", "Pad", "Organ", "Brass", "Lead", "Pluck")


def is_melodic(label):
    return any(label.startswith(m) for m in MELODIC_LABELS)


def is_vocal(label):
    return any(label.startswith(v) for v in VOCAL_LABELS)


# ---------------------------------------------------------------- groups
def g_names(als, od, a):
    """Rename default-named tracks and groups ("9-Audio", "7-Group") by what they sound like (`hypnomix name`).
    Sure names are proposed as renames; unsure ones are questions ("what is this track?")."""
    path = od / "raw" / "names" / "names.json"
    if not path.exists():
        roles(als, od)
    if not path.exists():
        return [], ["names: did NOT run (hypnomix name failed; see raw/names.txt)"]
    rows = json.loads(path.read_text()).get("tracks", [])
    out, n = [], 0
    for r in rows:
        if r.get("kind") == "Return" or r.get("new") in (None, r.get("old")):
            continue
        n += 1
        sure = float(r.get("confidence") or 0) >= 0.5
        out.append(dict(
            id=f"name-{n}", tool="name", kind="track-name" if sure else "track-name-question",
            severity="low", track=r["old"], where="", old=r["old"], new=r["new"], applies="set",
            problem=(f"default name '{r['old']}'; it sounds like {r['new']!r} ({r.get('reason')})" if sure else
                     f"default name '{r['old']}', and what it is isn't clear from its sound ({r.get('reason')}; "
                     f"best guess {r['new']!r})"),
            fix=(f"rename it {r['new']!r} in the new set" if sure else
                 "ask what it is, then record the name: `fix DIR --decide " + f"name-{n}=approve --note \"<name>\"`")))
    notes = []
    from hypnomix.workflow import prefs as P
    if str(P.get(P.load(), "cleanup.order", "on")).lower() in ("off", "no", "false", "0"):
        notes.append("order: skipped (your preference cleanup.order=off)")
    else:
        j = od / "raw" / "order.json"
        code, txt = hx("order", als, "--names", path, "--json", j)
        save(od / "raw" / "order.txt", strip_warnings(txt))
        if j.exists():
            out += json.loads(j.read_text())["findings"]
            notes.append("order: track order and vocal stacks are ON by default (skip the order items to opt out, or "
                         "`hypnomix prefs set cleanup.order=off` for every song)")
        else:
            notes.append(f"order: did NOT run ({txt.strip()[-200:]})")
    off = lambda k: str(P.get(P.load(), k, "on")).lower() in ("off", "no", "false", "0")
    if off("cleanup.retire") and off("cleanup.consolidate"):
        notes.append("tidy: skipped (your preferences cleanup.retire=off, cleanup.consolidate=off)")
    else:
        j = od / "raw" / "tidy.json"
        extra = (["--no-retire"] if off("cleanup.retire") else []) + (["--no-merge"] if off("cleanup.consolidate") else [])
        code, txt = hx("tidy", als, "--names", path, "--json", j, *extra)
        save(od / "raw" / "tidy.txt", strip_warnings(txt))
        if j.exists():
            out += json.loads(j.read_text())["findings"]
            notes.append("tidy: retiring switched-off tracks (after an archive copy) and merging one instrument's "
                         "matching tracks are ON by default (skip retire-1 / merge-N to opt out, or `hypnomix prefs set "
                         "cleanup.retire=off` / `cleanup.consolidate=off`)")
        else:
            notes.append(f"tidy: did NOT run ({txt.strip()[-200:]})")
    return out, notes + [f"names: {sum(1 for f in out if f['kind'] == 'track-name')} renames proposed, "
                 f"{sum(1 for f in out if f['kind'] == 'track-name-question')} tracks to ask about (findings keep the old names; "
                 "REVIEW.md shows the new ones; `fix` renames last)"]


def g_devices(als, od, a):
    """Every Live device on every track, judged by what it does to that track's own audio (`hypnomix devices`)."""
    j = od / "raw" / "devices.json"
    args = ["devices", als, "--json", j]
    if (od / "raw" / "names" / "names.json").exists():
        args += ["--names", od / "raw" / "names" / "names.json"]
    code, out = hx(*args)
    save(od / "raw" / "devices.txt", strip_warnings(out))
    if not j.exists():
        return [], [f"devices: did NOT run ({out.strip()[-200:]})"]
    d = json.loads(j.read_text())
    return d["findings"], [f"devices: {len(d['findings'])} Live device(s) checked; third-party plug-ins are skipped"] + \
        [f"devices: {n_}" for n_ in d.get("notes", [])[:6]]


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
    # clip edges and fades that cut into a word, on the vocal tracks (switched-off comp originals included)
    je = od / "raw" / "edges.json"
    nj = od / "raw" / "names" / "names.json"
    code, txt = hx("edges", als, "--json", je, *(["--names", nj] if nj.exists() else []))
    save(od / "raw" / "edges.txt", strip_warnings(txt))
    found = list(d["findings"])
    if je.exists():
        ef = json.loads(je.read_text())["findings"]
        found += ef
        rec = sum(1 for f in ef if f.get("recommended"))
        notes.append(f"edges: {len(ef)} item(s) on vocal clip edges, {rec} clear-cut fade fix(es) recommended; "
                     "cuts are listen-only")
    else:
        notes.append(f"edges: did NOT run ({txt.strip()[-200:]})")
    return found, notes


def g_timing(als, od, a, role):
    tracks = [t for t, r in role.items() if r["kind"] in ("Audio", "AudioTrack", "Midi", "MidiTrack", "")
              and not is_vocal(r["label"]) and "Group" not in r["label"]]
    if a.timing_track:
        tracks = a.timing_track
    if not tracks:
        return [], ["timing: no instrument tracks found (name them, or pass --timing-track)"]
    j = od / "raw" / "timing.json"
    args = ["timing", als, "--json", j, "--list", "0"]
    for t in tracks:
        args += ["--track", t]
    melodic = [t for t in tracks if is_melodic(role.get(t, {}).get("label", ""))]
    for t in melodic:
        args += ["--melodic", t]
    bass = [t for t in tracks if role.get(t, {}).get("label", "").startswith("Bass")]
    drums = [t for t in tracks if role.get(t, {}).get("label", "").startswith(("Drums", "Kick", "Snare", "Hats", "Perc"))]
    for t in bass:
        args += ["--bass", t]
    for t in drums:
        args += ["--drums", t]
    code, out = hx(*args)
    save(od / "raw" / "timing.txt", strip_warnings(out))
    if not j.exists():
        return [], [f"timing failed: {out[-300:]}"]
    d = json.loads(j.read_text())
    notes = [f"timing: song looseness {d['looseness_ms']} ms across {len(d['tracks'])} instrument tracks "
             f"(the band's natural feel; only outliers are listed)"]
    if d.get("grid"):
        runs = d["grid"]
        trip = [r for r in runs if "triplet" in r[2]]
        notes.append("timing: grid " + ("; ".join(f"bars {a}-{b}: {nm}" for a, b, nm in runs[:8]) if trip else
                                         f"straight 16ths throughout") + " (nudges go toward this grid)")
    if bass or drums:
        notes.append(f"timing: low end first: bass ({', '.join(bass) or 'none found'}) is checked against the drums "
                     f"({', '.join(drums) or 'none found'}) on every beat, with tighter tolerances")
    if melodic:
        notes.append(f"timing: melodic parts ({', '.join(melodic)}) only get OPTIONAL, partial nudges (at most 30% "
                     "of the way and 15 ms), and only for clear outliers: their looseness is part of the feel")
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
    how = "--lead-track" if a.lead_track else "named 'Lead Vocal'" if lead else None
    if not lead and files:  # `name` didn't single one out: the shared picker (vowel movement, then singing time)
        from hypnomix.core import dsp
        from hypnomix.engineer.roles import pick_lead
        lead = pick_lead([(t, dsp.load(p, 22050)[0]) for t, p in files.items()], 22050)
        how = "picked by sound: the vocal whose vowels move most (sings the words), then singing time"
    if lead:
        info = json.loads((od / "scan.json").read_text()) if (od / "scan.json").exists() else {}
        info["lead"] = lead
        (od / "scan.json").write_text(json.dumps(info, indent=1))
    findings, notes = [], []
    kf, kq = key_map(als, od, a)
    findings += kq["findings"]
    notes += kq["notes"]

    def one(item):
        t, p = item
        j = od / "raw" / f"tune-{p.stem}.json"
        args = ["tune", p, "--report-only", "--json", j]
        if a.ref:
            args += ["--ref", a.ref]
        if a.key:
            args += ["--key", a.key]
        elif kf:
            args += ["--scales", kf]
        if lead and t != lead and lead in files:
            args += ["--guide", files[lead]]
        if getattr(a, "backing", None):
            args += ["--chords", a.backing]
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
                f["asked_notes"] = d.get("asked", [])
                findings.append(f)
            if not a.ref and not any("tuning measured from the singer" in n for n in notes):
                notes.append("vocals: tuning measured from the singers themselves; give --ref MIX.wav for a "
                             "reliable grid")
    if lead in files and len(files) > 1:
        try:
            d_f, d_n = doubles(files, lead)
            notes += d_n
        except Exception as e:
            d_f = []
            notes.append(f"doubles: failed ({e})")
        findings += d_f
    if len(files) > 2:     # a lead and two or more harmonies: clips of lower harmonies sitting far too low
        j = od / "raw" / "cliplevel.json"
        args = ["cliplevel", als, "--json", j, "--renders", rd]
        if (od / "raw" / "names" / "names.json").exists():
            args += ["--names", od / "raw" / "names" / "names.json"]
        code, out = hx(*args)
        save(od / "raw" / "cliplevel.txt", strip_warnings(out))
        if j.exists():
            findings += json.loads(j.read_text())["findings"]
        else:
            notes.append(f"clip levels of lower harmonies: did NOT run ({out.strip()[-160:]})")
    if files:              # the vocal reverb and delay: ducked while the singer sings?
        j = od / "raw" / "duck.json"
        args = ["duck", als, "--json", j, "--renders", rd]
        if (od / "raw" / "names" / "names.json").exists():
            args += ["--names", od / "raw" / "names" / "names.json"]
        code, out = hx(*args)
        save(od / "raw" / "duck.txt", strip_warnings(out))
        if j.exists():
            findings += json.loads(j.read_text())["findings"]
        else:
            notes.append(f"vocal reverb/delay ducking: did NOT run ({out.strip()[-160:]})")
    if len(files) > 1:
        try:
            findings += harmony_question(files, lead, als)
        except Exception as e:
            notes.append(f"harmony balance check: failed ({e})")
    tuned = any(f.get("tool") == "tune" for f in findings)
    if tuned:
        first = next(f for f in findings if f.get("tool") == "tune")
        notes.append(f"vocals: key {first['key']} (confirm it before tuning: --key, or the section map's answers); lead taken as "
                     f"'{lead}' ({how}; harmonies are checked against it; --lead-track to change)")
    return findings, notes


def key_map(als, od, a):
    """Key section by section (`hypnomix key --sections`): songs change key and borrow chords.

    Returns (path of the map or None, {findings, notes}). Each question the map can't settle (two scales that
    differ by one note in some bars) becomes a finding to ask the person before any tuning."""
    j = od / "raw" / "key.json"
    args = ["key", "--set", als, "--sections", "--json", j]
    if a.ref:
        args += ["--audio", a.ref]
    code, out = hx(*args)
    save(od / "raw" / "key.txt", strip_warnings(out))
    if not j.exists():
        return None, {"findings": [], "notes": [f"key map: did NOT run ({out.strip()[-200:]}); tuning uses one key"]}
    d = json.loads(j.read_text())
    secs, qs = d.get("sections", []), d.get("questions", [])
    main = d["key"]
    moves = sorted({s["scale"] for s in secs})
    notes = [f"key map: {main} ({'sure' if d.get('sure') else 'UNSURE'}), {len(secs)} sections, scales used: "
             f"{'; '.join(moves)}" + ("" if a.ref else " (from the set's MIDI only: give --mix/--ref for the audio)")]
    findings = []
    for n, q in enumerate(qs, 1):
        findings.append(dict(
            id=f"key-{n}", tool="key", kind="key-question", severity="medium", track="(whole song)",
            where="bars " + ", ".join(q["bars"]),
            problem=f"two scales fit these bars equally well; they differ only in {q['notes'][0]} vs {q['notes'][1]}. "
                    "Tuning needs to know which one the song uses there.",
            fix=f"ask: {q['question']} Then tune with the answer: `fix --key sections --answer "
                f"{q['notes'][1]}` (or `--answer \"BARS=NOTE\"`, or `--answer both`)",
            applies="answer", notes=q["notes"], bars=q["bars"]))
    if not qs and not d.get("sure"):
        notes.append(f"key map: whole-song key unsure ({main} vs {d.get('runner_up')}): confirm it with the person")
    return j, {"findings": findings, "notes": notes}


def faders_db(als, names):
    """Each track's fader (dB) from the set: renders are raw clips, so levels compare as heard only with these."""
    import gzip, math, xml.etree.ElementTree as ET
    out = {}
    for t in ET.fromstring(gzip.open(als).read()).find(".//Tracks"):
        nm = t.find("./Name/EffectiveName").get("Value")
        vol = t.find("./DeviceChain/Mixer/Volume/Manual")
        if nm in names and vol is not None and float(vol.get("Value")) > 0:
            out[nm] = round(20 * math.log10(float(vol.get("Value"))), 2)
    return out


def harmony_question(files, lead, als=None, block_s=0.5, floor_db=-45.0):
    """When two or more vocal parts sing together, ask how to balance them. Never a default fix: which part to
    prioritise, which side to make quieter and by how much are the person's choices (`hypnomix voices`)."""
    import numpy as np
    from hypnomix.core import dsp
    act = {}
    for t, p in files.items():
        y, sr = dsp.load(p, 22050)
        b = dsp.block_rms_db(y, sr, block_s)
        act[t] = b > max(floor_db, (np.percentile(b, 95) if len(b) else 0) - 30)
    n = min(len(v) for v in act.values())
    together = np.sum([v[:n] for v in act.values()], axis=0) >= 2
    secs = float(together.sum() * block_s)
    if secs < 8:
        return []
    parts = ", ".join(files)
    return [dict(
        id="harmony-1", tool="voices", kind="harmony-balance", severity="low", track="(vocal parts)",
        where=f"{secs:.0f} s where 2+ parts sing together",
        problem=f"{len(files)} vocal parts ({parts}) sing together for about {secs:.0f} s. Where a higher part "
                "overshadows the one below it, the stack loses its shape.",
        fix=("suggested (approve with no note): your confirmed spacing (`hypnomix voices --confirm`; e.g. the lowest "
             "harmony is the basis, the next one up about 4 dB under it, higher ones about 5.5 dB under it), only "
             "where a part is clearly over and drowning out the ones below, subtly (small cuts, smooth ramps); the "
             "lead and the root are never turned down; nothing is ever turned up. "
             "For more, ask, one at a time: 1) which part to prioritise (the lead, '" + str(lead) + "', or the lowest, the "
             "highest, or another track); 2) which side to make quieter: above it, below it or both; 3) how much "
             "quieter per step: 0 / 1 / 1.5 / 3 / 4.5 / 6 dB or a custom value; 4) ladder (each further part quieter "
             "again) or flat (all one step under). Record it: `fix DIR --decide harmony-1=approve --note "
             "\"anchor=lead reduce=above above=1.5 spread=flat\"` (optional below=…, max-cut=…, tolerance=…). Or skip it."),
        applies="audio", stems=[str(p) for p in files.values()], lead=lead,
        faders=faders_db(als, set(files)) if als else {})]


def doubles(files, lead):
    """How far each other vocal sits from the lead in time, where both sing (median and worst 5%)."""
    from hypnomix.core import dsp
    from hypnomix.studio import vocalign as V
    yl, sr = dsp.load(files[lead], 22050)
    out, notes = [], []
    for n, (t, p) in enumerate(((t, p) for t, p in files.items() if t != lead), 1):
        yo, _ = dsp.load(p, 22050)
        m = min(len(yl), len(yo))
        two_d = lambda y: y if y.ndim > 1 else y[:, None]        # vocalign wants (samples, channels)
        med, p95 = V.residual_ms(two_d(yl[:m]), two_d(yo[:m]), sr, 150)
        if med < 20 and p95 < 60:
            continue
        sev = "medium" if med >= 35 or p95 >= 90 else "low"
        out.append(dict(id=f"doubles-{n}", tool="vocalign", kind="vocal-timing", severity=sev, track=t, where="",
                        problem=f"sits {med:.0f} ms from the lead on average where both sing (worst moments {p95:.0f} ms{' or more: the most this check measures' if p95 >= 148 else ''}): "
                                "words start and end apart, which smears consonants",
                        fix=("listen, then nudge this part's own comp clips in Live where its words start apart from the "
                             "lead (clip edits only: no aligned or rendered copy is swapped in). Skip this if it is a "
                             "counter-melody or sings different words: it is only for parts that follow the lead."),
                        applies="manual"))
    notes.append(f"doubles: {len(files) - 1} vocal(s) compared with the lead '{lead}' for timing")
    return out, notes


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


def g_mix(als, od, a, tempo=None):
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
    try:  # sections: needs the tempo, which a set knows
        from hypnomix.session import automation as aa
        from hypnomix.ears import sections as SE
        if tempo is None and Path(als).is_file() and Path(als).suffix.lower() == ".als":
            tempo = float(aa.load(als).getroot().find(".//Tempo/Manual").get("Value"))
        if tempo:
            r = SE.analyse(a.mix, bpm=tempo)
            save(od / "raw" / "sections.json", json.dumps(r, indent=1, default=str))
            findings += [f for f in r["findings"] if f.get("severity") != "info"]
    except Exception as e:
        findings.append(dict(id="sections-0", tool="sections", kind="sections", severity="info", track="mix", where="",
                             problem=f"section check failed ({e})", fix="", applies="info"))
    if a.like:
        try:
            from hypnomix.ears import match as MA
            r = MA.analyse(a.mix, a.like)
            save(od / "raw" / "match.json", json.dumps(r, indent=1, default=str))
            findings += r["findings"]
        except Exception as e:
            findings.append(dict(id="match-0", tool="match", kind="match", severity="info", track="mix", where="",
                                 problem=f"reference comparison failed ({e})", fix="", applies="info"))
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
    try:  # voices: sibilance and breaths, as proposals
        from hypnomix.engineer import roles
        role, _ = roles.classify(path.stem, y, sr)
        if role in ("lead_vocal", "backing_vocal"):
            from hypnomix.studio import deess as DE, breaths as BR
            ev = DE.analyse(y, sr)
            if len(ev) >= 5:
                worst = max(e["over_db"] for e in ev)
                out.append(("sibilance", "medium" if len(ev) >= 40 else "low",
                            f"{len(ev)} harsh 's' / 't' sounds (the strongest {worst:.0f} dB over the voice's own level)",
                            "turn down only the high band during those moments (de-ess) into a new file; listen that "
                            "the words stay crisp, not lispy", ["deess", path, "{out}/" + path.stem + " (deess).wav"]))
            br = BR.analyse(y, sr)
            if len(br) >= 4:
                out.append(("breaths", "low", f"{len(br)} breaths between phrases",
                            "turn them down 8 dB (not off) into a new file. Skip if the breaths are part of the feel.",
                            ["breaths", path, "{out}/" + path.stem + " (breaths).wav"]))
    except Exception as e:
        out.append(("vocal-check", "info", f"sibilance and breath check failed ({e})", "", None))
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


PAIR_WORDS = {"in", "out", "top", "bottom", "btm", "bot", "di", "amp", "mic", "close", "far", "room", "inside",
              "outside", "front", "back", "1", "2", "a", "b"}


def pair_base(name):
    """'Kick In' -> 'kick': the name without the words that tell two mics on one source apart."""
    words = [w for w in re.split(r"[\s_\-.()]+", Path(name).stem.lower()) if w and not w.isdigit() or w in ("1", "2")]
    left = [w for w in words if w not in PAIR_WORDS]
    return " ".join(left) if len(left) < len(words) else None


def phase_findings(stems, sr, paths=None):
    """Files that record the same source (by name): time offset and polarity between them."""
    from hypnomix.engineer import align as A
    groups, out = {}, []
    for n, y in stems:
        b = pair_base(n)
        if b:
            groups.setdefault(b, []).append((n, y))
    k = 0
    for base, members in groups.items():
        ref_n, ref = members[0]
        for n, y in members[1:]:
            m = min(len(ref), len(y))
            lag, pol, peak = A.offset(ref[:m], y[:m], sr, 20)
            if peak < 0.2:          # not the same source after all
                continue
            ms = lag / sr * 1000
            if pol > 0 and abs(ms) < 0.25:
                continue
            k += 1
            what = ("polarity is flipped against it" if pol < 0 else "") + (" and " if pol < 0 and abs(ms) >= 0.25 else "") \
                + (f"it is {abs(ms):.2f} ms {'late' if ms > 0 else 'early'}" if abs(ms) >= 0.25 else "")
            f = dict(id=f"phase-{k}", tool="align", kind="phase", severity="medium" if pol < 0 else "low", track=n,
                     where="", problem=f"same source as '{ref_n}': {what}. Summed, the low end partly cancels.",
                     fix=("flip its polarity" if pol < 0 else "") + (" and " if pol < 0 and abs(ms) >= 0.25 else "")
                         + (f"shift it {abs(ms):.2f} ms {'earlier' if ms > 0 else 'later'}" if abs(ms) >= 0.25 else "")
                         + ". Listen to the two together: the low end should get fuller, not thinner.",
                     applies="manual")
            if paths and ref_n in paths and n in paths:
                f["applies"] = "audio"
                f["run"] = ["align", str(paths[ref_n]), str(paths[n]), "--apply", "--out", "{out}"]
            out.append(f)
    return out


def stem_findings(stems, sr, paths=None, top=8):
    """Masking as one finding per fight, plus phase between same-source files."""
    from hypnomix.engineer import masking as M
    collisions, role_of = M.analyse(stems, sr)
    same = lambda c: pair_base(c["a"]) is not None and pair_base(c["a"]) == pair_base(c["b"])
    collisions = [c for c in collisions if not same(c)]      # two mics on one source share every band by design
    out = []
    for k, c in enumerate(collisions[:top], 1):
        out.append(dict(id=f"mask-{k}", tool="masking", kind="masking", severity="medium" if c["frac"] >= 0.5 else "low",
                        track=c["give"], where="",
                        problem=f"fights with '{c['keep']}' in {c['band_name']}: similar level there "
                                f"{int(c['frac'] * 100)}% of the time both play ({c['seconds']:.0f} s)",
                        fix=M.advice(c).replace("**", "") + ". Listen for the part that should lead getting clearer, "
                            "not for the cut itself.", applies="manual"))
    notes = [f"stems: {len(stems)} parts compared; roles by name then sound: "
             + ", ".join(f"{n}={r}" for n, r in list(role_of.items())[:12])]
    if len(collisions) > top:
        notes.append(f"stems: {len(collisions) - top} smaller frequency fights not listed (hypnomix masking shows all)")
    return out + phase_findings(stems, sr, paths), notes


def g_stems(folder, od, a):
    from hypnomix.engineer import masking as M
    files = audio_files(folder)
    if len(files) < 2:
        return [], ["stems: fewer than two files, nothing to compare"]
    stems, sr = M.load_stems(folder)
    return stem_findings(stems, sr, {p.stem: p for p in files})


# ---------------------------------------------------------------- deeper checks on a set
def g_stems_set(als, od, a):
    """--deep: render every audio track that is on (clip gain, fades, warps; no devices) and compare them."""
    if not a.deep:
        return [], ["stems: skipped (add --deep to render every track and check frequency fights and mic phase)"]
    from hypnomix.engineer import masking as M
    rd = od / "raw" / "renders-all"
    code, out = hx("render", als, "--out", rd)
    save(od / "raw" / "render-all.txt", strip_warnings(out))
    on = {re.sub(r'[\\/:*?"<>|]', "-", t) for t in tracks_on(als)}
    keep = [p for p in audio_files(rd)] if rd.exists() else []
    if len(keep) < 2:
        return [], [f"stems: render failed or fewer than two tracks ({out[-200:]})"]
    stems, sr = M.load_stems(rd)
    stems = [(n, y) for n, y in stems if n in on]
    if len(stems) < 2:
        return [], ["stems: fewer than two switched-on audio tracks with clips"]
    f, notes = stem_findings(stems, sr)
    notes.append("stems: tracks were rendered without their effects, so EQ already on a track is not counted")
    return f, notes


def g_noise(als, od, a):
    """Clips boosted a lot with clip gain: the boost lifts the take's own noise floor by the same amount."""
    import math
    import numpy as np
    import soundfile as sf
    from hypnomix.session import automation as aa
    from hypnomix.session import smooth as S
    root = aa.load(als).getroot()
    bpb = aa.BPB
    tempo = float(root.find(".//Tempo/Manual").get("Value"))
    floors, rows = {}, {}

    def floor_of(path):
        if path not in floors:
            try:
                y, sr = sf.read(str(path), dtype="float32", always_2d=True)
                m = y.mean(1)
                blk = int(sr * 0.05)
                n = max(1, len(m) // blk)
                db = 10 * np.log10((m[: n * blk] ** 2).reshape(n, blk).mean(1) + 1e-14)
                live = db[db > -90]
                steady = len(live) > 20 and float(np.percentile(live, 15) - np.percentile(live, 2)) < 4
                floors[path] = (float(np.percentile(live, 5)), steady) if len(live) else (None, False)
            except Exception:
                floors[path] = (None, False)
        return floors[path]
    for t in root.find(".//Tracks"):
        if t.tag != "AudioTrack" or not S.track_on(t):
            continue
        name = t.find("./Name/EffectiveName").get("Value")
        for c in t.findall(".//ArrangerAutomation/Events/AudioClip"):
            ci = S.clip_info(c, Path(als).parent, tempo)
            if ci["disabled"] or not ci["gain"] or ci["gain"] < 3.98 or not ci["path"].exists():   # +12 dB and up
                continue
            g = 20 * math.log10(ci["gain"])
            fl, steady = floor_of(ci["path"])
            if fl is None or fl + g < -55:
                continue
            r = rows.setdefault((name, str(ci["path"])), dict(gain=g, floor=fl, steady=steady, beats=[]))
            r["gain"] = max(r["gain"], g)
            r["beats"].append(ci["start"])
    out = []
    for n, ((track, path), r) in enumerate(sorted(rows.items(), key=lambda kv: -(kv[1]["floor"] + kv[1]["gain"])), 1):
        eff = r["floor"] + r["gain"]
        b = min(r["beats"])
        where = f"{int(b // bpb) + 1}.{int(b % bpb) + 1}.{int(round((b % 1) * 100)):02d}"
        out.append(dict(id=f"noise-{n}", tool="dehiss", kind="boosted-noise", track=track, where=where,
                        severity="high" if eff > -40 else "medium" if eff > -48 else "low",
                        problem=f"{len(r['beats'])} clip(s) of '{Path(path).name}' are boosted up to +{r['gain']:.0f} dB with "
                                f"clip gain; the quietest moments of that file sit at {r['floor']:.0f} dBFS, so they play "
                                f"at about {eff:.0f} dBFS" + ("" if r["steady"] else " (may be quiet playing, not noise: listen)"),
                        fix=f"listen to the gaps between phrases there. If it is hiss: `hypnomix dehiss \"{path}\"` makes a "
                            "cleaned copy to swap in (or `hypnomix render --sources`); or record that part hotter. "
                            "Turning the clip down hides the part, not the noise.",
                        applies="manual"))
    return out, [f"noise: {len(rows)} boosted take(s) of +12 dB or more with an audible floor"] if rows else []


def g_intent(als, od, a):
    """Things that look unusual but are probably choices. Listed as questions, never as problems."""
    import math
    from hypnomix.session import automation as aa
    from hypnomix.session import smooth as S
    root = aa.load(als).getroot()
    bpb = aa.BPB
    bar = lambda beats: max(1.0, beats / bpb + 1)
    out, n = [], 0

    def add(track, problem, where=""):
        nonlocal n
        n += 1
        out.append(dict(id=f"intent-{n}", tool="intent", kind="deliberate?", severity="info", track=track, where=where,
                        problem=problem, applies="info",
                        fix="If this is on purpose, nothing to do: tools will not change it. To have it shown on every "
                            "review: hypnomix prefs set protect.notes=\"...\""))
    extra = 0
    for t in aa.tracks(root):
        if t is None:
            continue
        name = aa.tname(t)
        parent = t.find("./AutomationEnvelopes/Envelopes")
        tg = aa.targets(t)
        for env in (parent if parent is not None else []):
            pid = env.find("./EnvelopeTarget/PointeeId").get("Value")
            if pid not in tg:
                continue
            lab, _, vol_like = tg[pid]
            pts = []
            for e in env.find("./Automation/Events"):
                try:
                    tm, v = float(e.get("Time")), float(e.get("Value"))
                except (TypeError, ValueError):
                    continue
                if tm > -1e6:
                    pts.append((tm, v))
            if len(pts) < 2:
                continue
            vals = [v for _, v in pts]
            if max(vals) - min(vals) < 1e-6:
                continue
            if len(out) >= 30:
                extra += 1
                continue
            if vol_like:
                d = lambda v: f"{20 * math.log10(v):+.1f} dB" if v > 0 else "silence"
                rng = f"{d(min(vals))} to {d(max(vals))}"
            else:
                rng = f"{min(vals):.3g} to {max(vals):.3g}"
            add(name, f"{lab} is automated from bar {int(bar(pts[0][0]))} to {int(bar(pts[-1][0]))} ({len(pts)} points, {rng})",
                f"{int(bar(pts[0][0]))}.1.00")
        if t.tag == "AudioTrack":
            if not S.track_on(t) and t.find(".//ArrangerAutomation/Events/AudioClip") is not None:
                add(name, "the track is switched off but has clips (it is not checked and not heard)")
            pan = t.find("./DeviceChain/Mixer/Pan/Manual")
            if pan is not None and abs(float(pan.get("Value"))) >= 0.9 and S.track_on(t):
                add(name, f"panned hard {'right' if float(pan.get('Value')) > 0 else 'left'}")
    notes = [f"intent: {n} thing(s) that look deliberate, listed as questions"]
    if extra:
        notes.append(f"intent: {extra} more automated controls not listed (hypnomix automation list shows all)")
    return out, notes


# ---------------------------------------------------------------- what the person told hypnomix in Live
def told_in_live(als, a):
    """The probe menus and HypnomixMain's song card, read from the saved set: they win over guessing.
    A key typed in Live counts as confirmed by the person; a track marked lead vocal is the lead; protected
    tracks are protected for this song; the card's loudness target and ceiling are the targets."""
    try:
        from hypnomix.app.probe import read_cards
        c = read_cards(als)
    except Exception:
        return {}
    song, tracks = c.get("song", {}), c.get("tracks", {})
    out = {}
    if song.get("key_name"):
        out["key"] = song["key_name"]
        if not a.key:
            a.key = song["key_name"]
    lead = [t for t, v in tracks.items() if v.get("role") == "lead vocal"]
    if lead:
        out["lead"] = lead[0]
        if not a.lead_track:
            a.lead_track = lead[0]
    roles = {t: v["role"] for t, v in tracks.items() if v.get("role") not in (None, "auto")}
    if roles:
        out["roles"] = roles
    prot = [t for t, v in tracks.items() if str(v.get("protect", "off")).startswith("on")]
    if prot:
        out["protect"] = prot
    pri = {t: v["priority"].split(":")[0] for t, v in tracks.items() if str(v.get("priority", "normal")) != "normal"}
    if pri:
        out["priority"] = pri
    for k in ("genre", "target", "ceiling", "mode", "amount", "chords"):
        if song.get(k) not in (None, "", "not set"):
            out[k] = song[k]
    return out


# ---------------------------------------------------------------- merge + review
def merge(od):
    from hypnomix.workflow import prefs as P
    od = Path(od)
    prefs = P.load()
    protected = {t.lower() for t in (prefs.get("protect", {}).get("tracks") or [])}
    findings, notes, meta = [], [], {}
    sjp = od / "scan.json"
    told = (json.loads(sjp.read_text()).get("told") or {}) if sjp.exists() else {}
    protected |= {t.lower() for t in told.get("protect", [])}
    if told:
        notes.append("Told in Live (probe menus and the song card): " + "; ".join(
            f"{k} {v if not isinstance(v, (dict, list)) else ', '.join(f'{a}={b}' for a, b in v.items()) if isinstance(v, dict) else ', '.join(v)}"
            for k, v in told.items()))
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
    write_review(od, setp, findings, notes, meta, P.summary(prefs), prefs=prefs)
    return findings, notes


def oversight_lines(f, ov, show):
    """The "you usually / common practice / confidence / why" lines for one finding in REVIEW.md."""
    e = ov["extras"].get(f["id"], {})
    L = [f"- confidence: {e.get('confidence', 0.5):.0%} ({e.get('confidence_from', 'default')})"
         + ("" if f.get("applies") in ("info", "answer") else
            (" · amount: 0-100 (`--decide ID=approve@60`)" if e.get("scalable") else
             f" · all or nothing ({e.get('scale_note')})"))]
    if e.get("usually"):
        L.append(f"- you usually: {e['usually']}")
    if e.get("practice"):
        L.append(f"- common practice: {e['practice']}")
    if ov["teach"] and e.get("why"):
        L.append(f"- why this technique: {e['why']}")
    like = ov["like"].get(f["id"])
    if like and f.get("applies") not in ("info", "answer"):
        L.append(f"- {len(like)} more like this: `hypnomix fix DIR --decide-like {f['id']}=approve` (or skip; "
                 "--dry-run lists them first)")
    return L


def write_review(od, setp, findings, notes, meta, pref_lines=(), prefs=None):
    od = Path(od)
    try:
        from hypnomix.workflow import oversight as O, review as RV, prefs as P
        prefs = P.load() if prefs is None else prefs
        ov = RV.oversight_payload(od, findings, prefs)
    except Exception as e:  # the review must still be written
        ov = None
        notes = list(notes) + [f"WARNING: oversight lines failed ({e})"]
    nj = Path(od) / "raw" / "names" / "names.json"
    newname = {}
    if nj.exists():
        newname = {r["old"]: r["new"] for r in json.loads(nj.read_text()).get("tracks", [])
                   if r.get("new") and r.get("new") != r.get("old")}
    show = lambda t: f"{newname[t]} (now '{t}')" if t in newname else (t or "-")
    counts = {s: sum(1 for f in findings if f.get("severity") == s) for s in SEV}
    from hypnomix import project as PJ
    daw = PJ.daw_of(setp) if setp else None
    rpp_ = daw in ("reaper", "ardour")
    L = [f"# First-pass review: {Path(setp).stem if setp else od.name}", "",
         f"{'Project' if rpp_ else 'Set'}: `{setp}`  ", "Nothing has been changed. Go through the items one at a time: "
         "**approve**, **skip** or **change** each" + (", then `hypnomix fix` writes them into ONE new project." if daw == "reaper" else
                                                       ", then make the approved changes (see Apply)." if rpp_ else
         ", then `hypnomix fix` writes every approved set change into ONE new set."), "",
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
    def item(f):
        where = f" @ {f['where']}" if f.get("where") else ""
        also = f" (same audio again at {', '.join(f['also_at'][:5])})" if f.get("also_at") else ""
        mark = " · NEW since the last scan" if f.get("new") else " · carried over from the last scan" if f.get("carried") else ""
        L.append(f"### {f.get('n', '')}. [{f.get('severity')}] {f['tool']}: {show(f.get('track')) if f['tool'] != 'name' else f.get('track')}{where}{also}")
        L.append(f"- id: `{f['id']}` · applies: **{f.get('applies')}**"
                 + (" · **PROTECTED track: ask again before changing**" if f.get("protected") else "") + mark)
        if f.get("history"):
            L.append(f"- history: {f['history']}")
        L.append(f"- problem: {f.get('problem')}")
        fix = str(f.get("fix", "")).strip()
        L.append(f"- proposed fix: {fix}" if "\n" not in fix else "- proposed fix:\n\n```\n" + fix + "\n```")
        if f.get("flagged_notes"):
            L.append(f"- notes to check by ear: " + ", ".join(f"{x['time']} {x['sung']} ({x['cents']:+d}c)"
                                                           for x in f["flagged_notes"][:12]))
        if ov:
            L.extend(oversight_lines(f, ov, show))
        if f.get("applies") == "answer":
            L.append(f"- answer: [ ] {f['notes'][0]}  [ ] {f['notes'][1]}  [ ] both   (record: `hypnomix fix DIR --answer NOTE`)")
        elif f.get("applies") != "info":
            L.append("- decision: [ ] approve  [ ] skip  [ ] change: ____  amount: ___%")
        L.append("")

    budget = (ov or {}).get("budget")
    if budget:
        by_id = {f["id"]: f for f in findings}
        L += ["", f"## Items (most severe first; your question budget: {budget['max']})", ""]
        for fid in budget["ask"]:
            item(by_id[fid])
        if budget["batch"]:
            L += ["<details>", f"<summary>Low priority: batch ({len(budget['batch'])} items beyond your "
                  f"{budget['max']} questions; high-severity and protected items are never in here)</summary>", "",
                  "Suggested grouped decisions (advice: each still needs your yes; any single item can be decided "
                  "differently afterwards and wins):", ""]
            for sg in budget["suggestions"]:
                L.append(f"- {sg['tool']} {sg['kind']}{' (' + sg['role'] + ')' if sg['role'] else ''}: "
                         f"{len(sg['ids'])} item(s), suggested **{sg['decision']}** ({sg['why']}): "
                         f"`hypnomix fix \"{od}\" --decide {','.join(i + '=' + sg['decision'] for i in sg['ids'][:40])}`")
            L.append("")
            for fid in budget["batch"]:
                item(by_id[fid])
            L += ["</details>", ""]
        if budget["info"]:
            L += ["## Measurements (nothing to decide)", ""]
            for fid in budget["info"]:
                item(by_id[fid])
    else:
        L += ["", "## Items (most severe first)", ""]
        for f in findings:
            item(f)
    if daw == "reaper":
        L += ["## Apply", "", "```", f'hypnomix fix "{od}" --decide ID=approve,ID=skip      # record each decision',
              f'hypnomix fix "{od}" --approved --out "<Song> (fixed).rpp"   # apply only what was approved', "```",
              "`fix` writes approved *set* items (fades, eases, dips) into ONE new .rpp next to the original, and "
              "tuned vocals as NEW TAKES on your own items (the original take stays: switch takes to A/B). Other "
              "*audio* items become new files; *manual* items are listed for you. Every finding is looked up again "
              "before anything changes, and the new project is checked and measured again afterwards. REAPER can stay "
              "open; open the new file when it is written."]
        (od / "REVIEW.md").write_text("\n".join(L) + "\n")
        return
    if rpp_:
        name, ext, swap = {"reaper": ("REAPER", ".rpp", "as new takes"),
                           "ardour": ("Ardour", ".ardour", "as new regions")}[daw]
        L += ["## Apply", "", "```", f'hypnomix fix "{od}" --decide ID=approve,ID=skip      # record each decision', "```",
              f"{name} project: *manual* items say what to change in {name}; *audio* items (tune, dehiss, deess, "
              f"breaths) become new files with `hypnomix fix` as for any project, and you swap them in {swap}. "
              f"Writing approved project changes into a new {ext} comes with a later hypnomix release."]
        (od / "REVIEW.md").write_text("\n".join(L) + "\n")
        return
    L += ["## Apply", "", "```", f'hypnomix fix "{od}" --decide ID=approve,ID=skip      # record each decision',
          f'hypnomix fix "{od}" --approved --out "<Song> (fixed).als"   # apply only what was approved', "```",
          "Close the set in Live first. `fix` writes approved *set* changes in one new set next to the original; "
          "*audio* items become new files (originals untouched); *manual* items are listed for you. It looks every "
          "finding up again before changing anything and measures the result afterwards."]
    (od / "REVIEW.md").write_text("\n".join(L) + "\n")


# ---------------------------------------------------------------- incremental (--since)
def incremental_plan(als, od, prev, groups, a):
    """What to re-run: compare the set with the copy the previous scan kept. Old group results not re-run are
    carried into od (with their findings marked carried)."""
    from hypnomix.session import diff as D
    from hypnomix.workflow import quick as Q
    prev = prev.resolve()
    if not (prev / "findings.json").exists():
        sys.exit(f"--since: no scan in {prev}")
    snap = prev / "raw" / Q.SNAPSHOT
    old_groups = {g: json.loads((prev / f"{g}.json").read_text()) for g in ALL_GROUPS if (prev / f"{g}.json").exists()}
    old_findings = json.loads((prev / "findings.json").read_text())["findings"]
    old_dec = json.loads((prev / "decisions.json").read_text()) if (prev / "decisions.json").exists() else {}
    if not snap.exists():
        print(f"--since: {prev} kept no copy of the set it scanned (an older scan): every group runs again")
        rows, rerun, why = [{"track": "(song)", "what": "no earlier copy to compare"}], list(groups), \
            {g: "no earlier copy to compare" for g in groups}
    else:
        rows = D.diff(snap, als)
        nj = prev / "raw" / "names" / "names.json"
        labels = {}
        if nj.exists():
            labels = {r["old"]: str(r.get("final") or r.get("label") or "") for r in json.loads(nj.read_text()).get("tracks", [])}
        rerun, why = Q.changed_groups(rows, groups, labels)
        for g in groups:                       # a group the previous scan never ran has nothing to carry
            if g not in old_groups and g not in rerun:
                rerun.append(g)
                why[g] = "not in the previous scan"
        if a.mix and "mix" in groups and "mix" not in rerun:
            old_scan = json.loads((prev / "scan.json").read_text()) if (prev / "scan.json").exists() else {}
            if old_scan.get("mix") != a.mix or Path(a.mix).stat().st_mtime > (prev / "findings.json").stat().st_mtime:
                rerun.append("mix")
                why["mix"] = "a new or re-bounced mix"
    if od.resolve() != prev:                   # keep what fix needs from the previous scan's raw files
        for sub in ("names",):
            if (prev / "raw" / sub).is_dir() and not (od / "raw" / sub).exists():
                shutil.copytree(prev / "raw" / sub, od / "raw" / sub)
        for j in (prev / "raw").glob("*.json"):
            if not (od / "raw" / j.name).exists():
                shutil.copyfile(j, od / "raw" / j.name)
    if any(r["what"] in ("track added", "track removed", "renamed") for r in rows) and "names" in rerun:
        nj = od / "raw" / "names" / "names.json"
        if nj.exists():
            nj.unlink()                         # track names and roles are measured again
    affected, _ = Q.changed_groups(rows, list(old_groups))
    for g, d in old_groups.items():
        if g in rerun:
            continue
        for f in d["findings"]:
            f["carried"] = True
            f.pop("new", None)
            if g in affected:
                f["stale"] = True
        d.setdefault("notes", [])
        d["notes"] = [n for n in d["notes"] if not n.startswith(f"{g}: carried")] + [
            f"{g}: carried over from the scan in {prev.name}" + (" (its tracks changed since: run the full scan for this "
                                                                 "group)" if g in affected else "")]
        (od / f"{g}.json").write_text(json.dumps(d, indent=1, default=str))
    return dict(dir=str(prev), rows=rows, rerun=rerun, why=why, old_groups=old_groups, old_findings=old_findings,
                old_dec=old_dec)


def incremental_finish(od, since):
    """Mark the re-run groups' findings that were not in the previous scan as new."""
    from hypnomix.workflow import quick as Q
    old_fp = {Q.fp(f) for f in since["old_findings"]}
    for g in since["rerun"]:
        p = od / f"{g}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        for f in d["findings"]:
            f.pop("carried", None)
            if Q.fp(f) not in old_fp:
                f["new"] = True
        p.write_text(json.dumps(d, indent=1, default=str))


def incremental_decisions(od, since):
    """Decisions from the previous scan, re-keyed by what each finding is. Those whose finding is gone are kept
    apart in decisions-stale.json (nothing is lost; nothing is applied from it)."""
    from hypnomix.workflow import quick as Q
    new = json.loads((od / "findings.json").read_text())["findings"]
    dec, dropped = Q.remap_decisions(since["old_findings"], new, since["old_dec"])
    if dec or (od / "decisions.json").exists():
        (od / "decisions.json").write_text(json.dumps(dec, indent=1))
    if dropped:
        p = od / "decisions-stale.json"
        old = json.loads(p.read_text()) if p.exists() else {}
        old.update(dropped)
        p.write_text(json.dumps(old, indent=1))
    return dec, dropped


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(prog="hypnomix scan", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als", nargs="?", metavar="SET.als|SONG.rpp|SONG.ardour|FOLDER")
    ap.add_argument("--mix", help="a bounce of the full mix (loudness, true peak, release checks)")
    ap.add_argument("--ref", help="mix or instrumental for tuning and key (vocals); defaults to --mix")
    ap.add_argument("--backing", metavar="INSTRUMENTAL.wav", help="the song without vocals (sample-aligned): the chord "
                    "under every sung note is read from it before any pitch correction is suggested (default: --ref)")
    ap.add_argument("--key", help='song key for the vocal check, e.g. "F# major"')
    ap.add_argument("--like", metavar="REFERENCE.wav", help="a finished song you want this mix to sit next to: "
                    "tone, dynamics and width differences become proposals (needs --mix)")
    ap.add_argument("--out", help="output folder (default hypnomix-out/scan/<song>)")
    ap.add_argument("--only", action="append", choices=sorted(set(GROUPS + FOLDER_GROUPS + ["effects", "recordings"])), help="run only these groups (repeatable)")
    ap.add_argument("--vocal-track", action="append", help="vocal tracks to check (default: from `name`)")
    ap.add_argument("--lead-track", help="the lead vocal (default: from `name`, else the vocal that sings most)")
    ap.add_argument("--timing-track", action="append", help="instrument tracks for timing (default: from `name`)")
    ap.add_argument("--jobs", type=int, default=4, help="parallel jobs (default 4)")
    ap.add_argument("--deep", action="store_true", help="a set: also render every track and check frequency fights "
                    "and mic phase between tracks (slower)")
    ap.add_argument("--merge", metavar="DIR", help="only rebuild findings.json + REVIEW.md from DIR")
    ap.add_argument("--quick", action="store_true", help="only the checks that read the set itself (files, intent, "
                    "structure): no rendering or audio analysis, seconds")
    ap.add_argument("--since", metavar="DIR", help="incremental: re-run only the groups whose tracks changed since "
                    "the scan in DIR, and keep its other findings")
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
    from hypnomix import project as PJ
    daw = PJ.daw_of(als)
    reaper = daw in ("reaper", "ardour")      # a project read through the shared model (an Ardour folder too)
    folder = als.is_dir() and not reaper
    if folder and not audio_files(als):
        sys.exit(f"no audio files (wav, aif, flac) in {als}")
    od = out_at(a.out, "scan", als.stem if not als.is_dir() else als.name)
    if reaper:
        from hypnomix.workflow import scan_project as SP
        mine = SP.GROUPS
    else:
        mine = FOLDER_GROUPS if folder else GROUPS
    groups = a.only or mine
    if a.quick:
        if folder:
            sys.exit("--quick is for a Live set (a folder of audio is always measured)")
        from hypnomix.workflow.quick import QUICK_GROUPS
        groups = [g for g in groups if g in QUICK_GROUPS] or list(QUICK_GROUPS)
    wrong = [g for g in groups if g not in mine]
    if wrong:
        sys.exit(f"{', '.join(wrong)}: not a group for a {'folder' if folder else PJ.NAMES[daw] + ' project' if reaper else 'Live set'} (use {', '.join(mine)})")
    told = told_in_live(als, a) if not folder and not reaper else {}
    info = {"set": str(als), "mode": "folder" if folder else daw if reaper else "set", "mix": a.mix, "ref": a.ref, "backing": a.backing, "key": a.key, "lead": None,
            "set_mtime": als.stat().st_mtime}
    if told:
        info["told"] = told
    (od / "raw").mkdir(exist_ok=True)
    sj = od / "scan.json"
    if sj.exists():  # parallel --only runs share this file: keep what another run already recorded
        old = json.loads(sj.read_text())
        if old.get("set") == info["set"]:
            info = {k: (v if v is not None else old.get(k)) for k, v in info.items()}
    since = None
    if a.since and not folder:
        since = incremental_plan(als, od, Path(a.since).expanduser(), groups, a)
        groups = since["rerun"]
        info["since"] = str(Path(a.since).expanduser().resolve())
    info["quick"] = bool(a.quick)
    sj.write_text(json.dumps(info, indent=1))
    if not folder and not reaper:
        from hypnomix.workflow.quick import keep_snapshot
        keep_snapshot(als, od)              # the next `--since` compares against this copy
    print(f"scanning {als.name}: {', '.join(groups) or 'nothing changed'} → {od}")
    if reaper:
        SP.run(a, als, od, groups)
        return finish(od)
    role = roles(als, od) if {"names", "timing", "vocals", "devices"} & set(groups) else {}
    if role:
        vox = [t for t, r in role.items() if is_vocal(r["label"])]
        print(f"  track roles from `name`: {len(vox)} vocal, {len(role) - len(vox)} other")

    def run(g):
        t0 = time.time()
        fn = {"devices": lambda: g_devices(als, od, a), "names": lambda: g_names(als, od, a), "files": lambda: g_files(als, od, a), "clips": lambda: g_clips(als, od, a),
              "timing": lambda: g_timing(als, od, a, role), "vocals": lambda: g_vocals(als, od, a, role),
              "effects": lambda: g_effects(als, od, a), "mix": lambda: g_mix(als, od, a),
              "noise": lambda: g_noise(als, od, a), "intent": lambda: g_intent(als, od, a),
              "structure": lambda: __import__("hypnomix.workflow.quick", fromlist=["g_structure"]).g_structure(als, od, a),
              "recordings": lambda: g_recordings(als, od, a),
              "stems": lambda: (g_stems(als, od, a) if folder else g_stems_set(als, od, a))}[g]
        try:
            f, notes = fn()
        except Exception as e:  # one failing check must not sink the scan
            f, notes = [], [f"{g}: failed ({e})"]
        secs = time.time() - t0
        (od / f"{g}.json").write_text(json.dumps({"group": g, "set": str(als), "seconds": secs,
                                                  "findings": f, "notes": notes}, indent=1, default=str))
        print(f"  {g:<8} {len(f):4d} findings  ({secs:.0f} s)")
        return g

    with ThreadPoolExecutor(max_workers=max(1, min(a.jobs, len(groups) or 1))) as ex:
        list(ex.map(run, groups))
    finish(od, since)


def finish(od, since=None):
    if since:
        incremental_finish(od, since)
    findings, notes = merge(od)
    if since:
        dec, dropped = incremental_decisions(od, since)
        if dropped:
            print(f"  {len(dropped)} decision(s) whose finding is gone kept in decisions-stale.json")
        n_new = sum(1 for f in findings if f.get("new"))
        n_car = sum(1 for f in findings if f.get("carried"))
        print(f"\nincremental: {len(since['rows'])} change(s) since {since['dir']}; re-ran {', '.join(since['rerun']) or 'no groups'}; "
              f"{n_car} finding(s) carried over, {n_new} new")
        for g, why in since["why"].items():
            print(f"  {g:<9} re-run: {why}")
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
