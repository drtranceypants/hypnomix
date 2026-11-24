#!/usr/bin/env python3
"""Auto-name the tracks and group tracks of a Live set by what they sound like.

First scan of a project: proposes a musical name for every track that still has a default-style name
("12-5-Audio 2", "Audio 3", "4-MIDI", "7-Group"...), from
  1. text clues: existing names, clip/sample file names, device names and presets, plugin names;
  2. audio (rendered straight from the .als, no Live needed): percussiveness, low-end share, brightness,
     single-note pitch + its range, consonant bursts (voice vs violin), chordiness and pluck shape;
  3. MIDI tracks: instrument devices + the note range of their clips.
Groups are named after what their tracks mostly are; in a vocal group the part that sings most is
"Lead Vocal" and the others "Harmony 1..n" from low to high. Low confidence -> "Instrument" and listed
under "please name these".

Usage:
  hypnomix name SET.als              # dry run: proposed names + JSON report
  hypnomix name SET.als --apply      # rename in the OPEN Live set (AbletonOSC); the set must be the one scanned
  hypnomix name SET.als --undo       # put the previous names back
Options: --all (also rename tracks you named yourself), --names JSON (fix any guesses, e.g. '{"7-Group":"Synths"}')
"""
import argparse, gzip, json, os, re, sys, xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np, librosa

from hypnomix.core.paths import out_at
from hypnomix.session.render import render_track, v

SR = 44100


def set_info(als):
    r = ET.fromstring(gzip.open(als).read())
    tempo = float(v(r, ".//Tempo/Manual"))
    ends = [float(v(c, "./CurrentEnd")) for c in list(r.iter("AudioClip")) + list(r.iter("MidiClip"))]
    return r, tempo, max(ends or [0])

DEFAULT_NAME = re.compile(r"^(\d+-)*(\d+-)?(audio|midi|group|track)?\s*\d*(\s+\d+)*$|^\d+-\d+-(audio|midi)\s*\d*(\s+\d+)*$|^\d+-(audio|midi|group)\b.*$", re.I)
KEYWORDS = [  # (regex, label) -- first match wins
    (r"lead\s*vo|main\s*vo", "Lead Vocal"), (r"harm|backing|bvs?\b|choir", "Harmony"),
    (r"vox|vocal|voice|sing", "Vocal"),
    (r"kick|bd\b", "Kick"), (r"snare|sd\b|clap", "Snare"), (r"hat|hh\b|cymbal|ride|crash", "Hats"),
    (r"drum|kit|perc|beat|groove|loop", "Drums"),
    (r"\bbass|sub\b|808", "Bass"), (r"guitar|gtr|acoustic|strum", "Guitar"),
    (r"violin|viola|cello|fiddle|string", "Strings"), (r"piano|keys|rhodes|wurli|organ", "Keys"),
    (r"pad|atmos|ambien|drone", "Pad"), (r"synth|lead|arp|pluck|operator|wavetable|analog|equator|serum|vital", "Synth"),
    (r"fx|riser|sweep|impact|noise", "FX"),
]


def text_clue(*texts):
    blob = " ".join(t for t in texts if t).lower()
    for rx, lab in KEYWORDS:
        if re.search(rx, blob): return lab
    return None


def device_names(t):
    out = []
    devs = t.find("./DeviceChain/DeviceChain/Devices")
    for d in (list(devs) if devs is not None else []):
        if v(d, "./On/Manual") == "false": continue          # bypassed devices are not clues
        out.append(d.tag)
        for p in (".//PluginDesc//Name", ".//PlugName", "./UserName"):
            x = v(d, p)
            if x: out.append(x)
    return out


def audio_features(y, sr=44100):
    """Features on up to 60 s of the track's loudest active audio (22.05 kHz)."""
    z = librosa.resample(y.astype(np.float32), orig_sr=sr, target_sr=22050); sr = 22050
    hop = 512
    rms = librosa.feature.rms(y=z, hop_length=hop)[0]
    if rms.max() < 1e-4: return None
    rdb = 20 * np.log10(rms + 1e-9); act = rdb > rdb.max() - 35
    active_s = act.sum() * hop / sr
    # keep the loudest 60 s of active frames, in time order, as one signal
    idx = np.flatnonzero(act)
    if len(idx) > 60 * sr / hop: idx = np.sort(idx[np.argsort(-rms[idx])][: int(60 * sr / hop)])
    keep = np.concatenate([z[i * hop:(i + 1) * hop] for i in idx])
    S = np.abs(librosa.stft(keep, n_fft=2048, hop_length=hop))
    f = librosa.fft_frequencies(sr=sr, n_fft=2048)
    pw = S ** 2; tot = pw.sum() + 1e-12
    low = pw[f < 150].sum() / tot; high = pw[f > 5000].sum() / tot
    cent = float(np.median(librosa.feature.spectral_centroid(S=S, sr=sr)[0]))
    H, P = librosa.decompose.hpss(S); perc = float((P ** 2).sum() / ((H ** 2).sum() + (P ** 2).sum() + 1e-12))
    on = librosa.onset.onset_detect(y=keep, sr=sr, hop_length=hop); onset_rate = len(on) / (len(keep) / sr + 1e-9)
    f0, vflag, vprob = librosa.pyin(keep[: sr * 30], fmin=40, fmax=1500, sr=sr, hop_length=hop)
    voiced = float(np.mean(vflag)) if len(vflag) else 0
    ff = f0[~np.isnan(f0)]
    med = float(np.median(ff)) if len(ff) > 10 else None
    rng = float(1200 * np.log2(np.percentile(ff, 90) / np.percentile(ff, 10)) / 100) if len(ff) > 10 else 0
    # vowel movement: frame-to-frame timbre (MFCC 2-13) change while a pitch sounds. Voices move between
    # vowels constantly; bowed/blown instruments keep a steady tone. (Measured on real sessions: vocals 12.9-14.3,
    # violins 9.5-10.4.) Works on dark vocals where sibilance-based tests fail.
    M = librosa.feature.mfcc(y=keep[: sr * 30], sr=sr, n_mfcc=14, hop_length=hop)[2:]
    n = min(M.shape[1], len(vflag)); d = np.linalg.norm(np.diff(M[:, :n], axis=1), axis=0)
    both = vflag[1:n] & vflag[:n - 1]
    vowel = float(np.median(d[both])) if both.any() else 0.0
    # note decay: level slope (dB/s) in the 350 ms after each attack. Plucked/struck notes die away
    # (guitars -13..-20), voices sag a little (-5..-10), bowed strings hold or swell (+1..+15).
    # measured on the CONTINUOUS audio (splicing loud frames together fakes attacks and cuts decays)
    first, last = idx[0] * hop, min(len(z), idx[0] * hop + 150 * sr)
    zc = z[first:last]
    r2 = librosa.feature.rms(y=zc, hop_length=256)[0]; r2db = 20 * np.log10(r2 + 1e-9)
    sl = []
    for o in librosa.onset.onset_detect(y=zc, sr=sr, hop_length=256):
        b = o + int(0.35 * sr / 256)
        if b < len(r2db) and r2db[o + 2] > r2db.max() - 30:
            seg = r2db[o + 2:b]; sl.append(np.polyfit(np.arange(len(seg)) * 256 / sr, seg, 1)[0])
    decay = float(np.median(sl)) if len(sl) >= 10 else 0.0
    chroma = librosa.feature.chroma_stft(S=S, sr=sr)
    poly = float(np.mean((chroma / (chroma.max(0, keepdims=True) + 1e-9) > 0.6).sum(0)))
    flat = float(np.median(librosa.feature.spectral_flatness(S=S)[0]))
    return dict(active_s=round(active_s, 1), low=round(low, 3), high=round(high, 3), centroid=round(cent),
                perc=round(perc, 3), onsets_per_s=round(onset_rate, 2), voiced=round(voiced, 3),
                f0=round(med, 1) if med else None, f0_range_st=round(rng, 1), vowel_move=round(vowel, 1), decay_db_s=round(decay, 1),
                chord_notes=round(poly, 2), flatness=round(flat, 4))


def classify_audio(F):
    """(label, confidence 0..1, reason) from audio features. Thresholds tuned on real multitrack sessions (dark vocals, violins, clean and swelled guitars)."""
    if F is None: return "Instrument", 0.0, "silent"
    dec, vow = F["decay_db_s"], F["vowel_move"]
    if F["perc"] > 0.55 and F["voiced"] < 0.35:
        if F["low"] > 0.45: return "Kick", 0.8, "percussive, energy below 150 Hz"
        if F["centroid"] > 4500: return "Hats", 0.75, "percussive and bright"
        return "Drums", 0.75, "percussive"
    if F["f0"] and F["f0"] < 140 and F["low"] > 0.35: return "Bass", 0.8, f"pitched, median {F['f0']} Hz"
    if dec <= -12:
        return ("Guitar", 0.75, f"plucked: notes die away ({dec} dB/s)") if F["perc"] > 0.04 or F["chord_notes"] < 2.6 \
            else ("Keys", 0.5, f"struck chords ({dec} dB/s)")
    if F["voiced"] > 0.35 and F["chord_notes"] < 2.6:
        if vow >= 11.5: return "Vocal", min(0.9, 0.55 + (vow - 11.5) / 6), f"moving vowels ({vow}), voice-like decay ({dec} dB/s)"
        if dec > -2 and vow < 11.5 and F["f0"] and F["f0"] > 190:
            return "Strings", 0.5, f"held notes ({dec} dB/s), steady tone ({vow}) -- could be a swelled guitar/synth"
        return "Lead", 0.35, f"single line (vowels {vow}, decay {dec})"
    if F["chord_notes"] >= 2.6:
        if F["onsets_per_s"] < 1.0: return "Pad", 0.5, "sustained chords"
        return "Keys", 0.4, "chords"
    if F["flatness"] > 0.2: return "FX", 0.4, "noise-like"
    return "Instrument", 0.2, "unclear"


def midi_info(t):
    notes = [int(n.get("Value") or 0) for n in t.iter("MidiKey")]
    keys = [int(k.get("Value")) for k in t.findall(".//KeyTrack/MidiKey") if k.get("Value")]
    return (float(np.median(keys)) if keys else None), len(keys)


def rename_set(src, out, mapping, inplace=False):
    """Write a copy of the set with tracks renamed {old name: new name}. Returns (renamed, skipped[(old, why)]).
    Only a name that matches exactly one track is changed. The original is never touched."""
    import shutil
    if Path(out).resolve() == Path(src).resolve() and not inplace:   # inplace: only for a set a tool just wrote
        raise SystemExit("refusing to overwrite the set; give a new file name")
    tree = ET.ElementTree(ET.fromstring(gzip.open(src).read()))
    tracks = list(tree.getroot().find(".//Tracks"))
    by = defaultdict(list)
    for t in tracks:
        by[v(t, "./Name/EffectiveName")].append(t)
    done, skipped = [], []
    taken = {n for n in by if n not in mapping}
    for old, new in mapping.items():
        if len(by.get(old, [])) != 1:
            skipped.append((old, "no track by that name" if not by.get(old) else "several tracks share that name"))
            continue
        if new in taken:
            skipped.append((old, f"another track is already called {new!r}"))
            continue
        nm = by[old][0].find("./Name")
        nm.find("./UserName").set("Value", new)
        nm.find("./EffectiveName").set("Value", new)
        taken.add(new)
        done.append((old, new))
    tmp = Path(str(out) + ".tmp")
    data = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(tree.getroot(), encoding="utf-8")
    with gzip.open(tmp, "wb") as f:   # same serialisation as every other tool that writes sets
        f.write(data)
    shutil.move(tmp, out)
    return done, skipped


def main():
    ap = argparse.ArgumentParser(prog="hypnomix name", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("set"); ap.add_argument("--out")
    ap.add_argument("--apply", action="store_true"); ap.add_argument("--undo", action="store_true")
    ap.add_argument("--all", action="store_true"); ap.add_argument("--names")
    a = ap.parse_args()
    out = str(out_at(a.out, "names", Path(a.set).stem) / "names.json")
    if a.undo:
        from hypnomix.live.osc import Live
        rep = json.load(open(out)); l = Live(); cur = dict((n, t) for t, n in l.tracks())
        for r in rep["tracks"]:
            if r.get("applied") and r["new"] in cur: l.send("/live/track/set/name", cur[r["new"]], r["old"])
        print("restored", sum(1 for r in rep["tracks"] if r.get("applied"))); return
    r, tempo, end = set_info(a.set)
    spb = 60 / tempo; N = int((end + 8) * spb * SR); warn = []
    tracks = list(r.find(".//Tracks"))
    name = {t.get("Id"): v(t, "./Name/EffectiveName") for t in tracks}
    parent = {t.get("Id"): v(t, "./TrackGroupId") for t in tracks}
    rows = {}
    for t in tracks:
        tid, n = t.get("Id"), name[t.get("Id")]
        rec = {"old": n, "kind": t.tag.replace("Track", ""), "group": name.get(parent[tid]),
               "on": v(t, "./DeviceChain/Mixer/Speaker/Manual") != "false"}
        devs = device_names(t)
        files = [os.path.basename(v(c, "./SampleRef/FileRef/Path") or "") for c in t.iter("AudioClip")][:20]
        clipnames = [v(c, "./Name") for c in list(t.iter("AudioClip")) + list(t.iter("MidiClip"))][:20]
        rec["text_clue"] = text_clue(n if not DEFAULT_NAME.match(n) else "", " ".join(devs), " ".join(files), " ".join(c or "" for c in clipnames))
        if t.tag == "AudioTrack":
            F = audio_features(render_track(t, a.set, spb, N, SR, None, 0, warn)); rec["features"] = F
            lab, conf, why = classify_audio(F)
        elif t.tag == "MidiTrack":
            med, cnt = midi_info(t); rec["midi_median_note"] = med
            dl = " ".join(devs).lower()
            if "drum" in dl or "kit" in dl: lab, conf, why = "Drums", 0.8, "drum rack/kit device"
            elif med is not None and med < 48: lab, conf, why = "Bass", 0.6, f"MIDI notes around {librosa.midi_to_note(int(med))}"
            elif devs: lab, conf, why = "Synth", 0.45, "instrument device"
            else: lab, conf, why = "Instrument", 0.2, "no clues"
        else:
            lab, conf, why = None, 0, "group"
        if rec["text_clue"] and lab != "Vocal" and rec["text_clue"] not in ("Synth",):
            if conf < 0.75 or rec["text_clue"] in ("Lead Vocal", "Harmony", "Kick", "Snare", "Hats", "Guitar", "Bass", "Strings"):
                lab, conf, why = rec["text_clue"], max(conf, 0.7), f"text clue ({why})"
        rec.update(label=lab, confidence=round(conf, 2), reason=why)
        rows[tid] = rec
    # groups: majority of children; vocal groups get Lead + Harmony 1..n (low -> high)
    kids = defaultdict(list)
    for tid, rec in rows.items():
        if parent[tid] not in (None, "-1"): kids[parent[tid]].append(tid)
    for gid, ch in kids.items():
        labs = Counter(rows[c]["label"] for c in ch if rows[c]["label"] and rows[c]["label"] != "Instrument")
        if not labs: rows[gid].update(label="Instrument Group", confidence=0.2, reason="children unclear"); continue
        top, cnt = labs.most_common(1)[0]
        plural = {"Vocal": "Vocals", "Lead Vocal": "Vocals", "Harmony": "Vocals", "Kick": "Drums", "Snare": "Drums", "Hats": "Drums",
                  "Guitar": "Guitars", "Strings": "Strings", "Synth": "Synths", "Keys": "Keys", "Pad": "Pads", "Bass": "Bass", "Drums": "Drums"}.get(top, top + "s")
        rows[gid].update(label=plural, confidence=round(cnt / len(ch), 2), reason=f"{cnt}/{len(ch)} children are {top}")
    # vocals (grouped or not): one Lead Vocal by the shared rule (roles.lead_rank, as scan/tune/automix use),
    # the others Harmony 1..n from low to high. A track already named as the lead keeps it.
    # a copy of a track ("12-Audio CLEAN", "12-Audio copy") is what the original is, when its own sound is unclear
    base_of = lambda n_: re.match(r"^(\d+-(?:audio|midi))\b", n_ or "", re.I)
    by_old = {r["old"]: r for r in rows.values()}
    for rec in rows.values():
        m = base_of(rec["old"])
        if m and m.group(1) != rec["old"] and rec["confidence"] < 0.5:
            orig = next((r for o_, r in by_old.items() if o_.lower() == m.group(1).lower()), None)
            if orig and orig["confidence"] >= 0.5 and orig["label"]:
                lab = "Vocal" if orig["label"] in ("Lead Vocal", "Harmony") or orig["label"].startswith("Harmony") else orig["label"]
                rec.update(label=lab, confidence=orig["confidence"],
                           reason=f"a copy of '{orig['old']}' ({orig['label']}); its own sound: {rec['reason']}")
    # vocals (grouped or not): one Lead Vocal among the ones that PLAY (switched on), by the shared rule
    # (roles.choose_lead, as scan/tune/automix use); the other playing vocals Harmony 1..n from low to high.
    from hypnomix.engineer.roles import choose_lead
    voc = [c for c, r in rows.items() if r["label"] in ("Vocal", "Lead Vocal", "Harmony") and r.get("features")
           and r["kind"] == "Audio" and r.get("on", True)]
    if len(voc) > 1 or (voc and rows[voc[0]]["label"] == "Vocal"):
        named = [c for c in voc if rows[c].get("text_clue") == "Lead Vocal"]
        lead = named[0] if named else choose_lead([(c, rows[c]["features"]["vowel_move"], rows[c]["features"]["active_s"])
                                                   for c in voc])
        rows[lead]["label"] = "Lead Vocal"
        rows[lead]["reason"] += "; lead: among the playing vocals, sings longest of those whose vowels move most"
        rest = sorted([c for c in voc if c != lead], key=lambda c: rows[c]["features"]["f0"] or 0)
        for i, c in enumerate(rest): rows[c]["label"] = f"Harmony {i + 1}"
    if a.names:
        fix = json.loads(a.names)
        for rec in rows.values():
            if rec["old"] in fix: rec.update(label=fix[rec["old"]], confidence=1.0, reason="you said so")
    # final names: only default-named tracks (unless --all); unique
    for rec in rows.values():
        rec["final"] = rec["label"] if (rec["label"] and rec["confidence"] >= 0.35) else ("Instrument" if rec["kind"] != "Group" else "Group")
        if rec["kind"] == "Group" and rec["final"] in ("Bass", "Keys", "Strings"): rec["final"] += " Group"
    # children sharing a label inside one group -> numbered 1..n; same label elsewhere -> numbered globally
    seen = Counter((r["group"], r["final"]) for r in rows.values() if r["kind"] != "Group")
    idx, glob = Counter(), Counter()
    for tid, rec in rows.items():
        rename = a.all or DEFAULT_NAME.match(rec["old"].strip()) is not None
        if not rename or rec["kind"] == "Return": rec["new"] = rec["old"]; continue
        lab = rec["final"]
        m = re.match(r"^\d+-(?:audio|midi|group)\b\s*(.+)$", rec["old"].strip(), re.I)
        if m and not re.fullmatch(r"[\d\s]+", m.group(1)):
            lab = f"{lab} {m.group(1).strip()}"          # their own word after the default name ("CLEAN")
        if rec["kind"] != "Group" and seen[(rec["group"], lab)] > 1 and not re.search(r"\d$", lab):
            idx[(rec["group"], lab)] += 1; name_ = f"{lab} {idx[(rec['group'], lab)]}"
        else:
            name_ = lab
        glob[name_] += 1
        rec["new"] = name_ if glob[name_] == 1 else f"{name_} ({glob[name_]})"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    print(f"{'track':<34}{'->':<4}{'new name':<20}{'conf':>5}  reason")
    for rec in rows.values():
        print(f"{rec['old'][:33]:<34}{'->':<4}{rec['new'][:19]:<20}{rec['confidence']:>5}  {rec['reason']}")
    unsure = [r["old"] for r in rows.values() if r["new"] != r["old"] and (r["confidence"] < 0.5)]
    if unsure: print("\nplease name these (low confidence):", ", ".join(unsure))
    if a.apply:
        from hypnomix.live.osc import Live
        l = Live(); cur = [(t, n) for t, n in l.tracks() if t >= 0]
        byname = defaultdict(list)
        for t, n in cur: byname[n].append(t)
        for rec in rows.values():
            if rec["new"] != rec["old"] and len(byname.get(rec["old"], [])) == 1:
                l.send("/live/track/set/name", byname[rec["old"]][0], rec["new"]); rec["applied"] = True
        print("renamed", sum(1 for r in rows.values() if r.get("applied")), "tracks in Live (undo: --undo)")
    json.dump({"set": a.set, "tracks": list(rows.values())}, open(out, "w"), indent=1, default=float)
    print("report:", out)


if __name__ == "__main__":
    main()
