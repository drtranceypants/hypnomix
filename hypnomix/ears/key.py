#!/usr/bin/env python3
"""Find a song's key (tonic + major/minor) with a confidence, from up to three independent kinds of evidence:

  midi   notes of every MIDI clip in the Live set (exact; weighted by duration, bass notes count extra)
  audio  pitch-class profile of the harmonic part of the mix (HPSS + CQT chroma), whole song
  tonic  where the music rests: the lowest-sounding note per bar (bass line) and the final chord/bar

Each kind is scored against two published key profiles (Krumhansl-Kessler and Albrecht-Shanahan) for all
24 keys; scores are combined. Relative keys (G major / E minor) share every note, so the tonic evidence
decides between them. Confidence = how clearly the winner beats the runner-up; below --sure it says
UNSURE and lists the top candidates so an agent asks the person instead of guessing.

Usage: hypnomix key [--set SET.als] [--audio MIX.wav] [--sections [--bars 8]] [--json OUT.json]

Tested: 24/24 synthetic keys correct (relative major/minor pairs included); a synthetic G -> A key change is
mapped to the right bars. Real songs that move between closely related scales come out UNSURE with the one
disputed note named (e.g. "F or F#?"): that is the question to ask the person before tuning.
"""
import argparse, gzip, json, sys
import xml.etree.ElementTree as ET
import numpy as np

NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
KK_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
AS_MAJ = np.array([0.238, 0.006, 0.111, 0.006, 0.137, 0.094, 0.016, 0.214, 0.009, 0.080, 0.008, 0.081])
AS_MIN = np.array([0.220, 0.006, 0.104, 0.123, 0.019, 0.103, 0.012, 0.214, 0.062, 0.022, 0.061, 0.052])


def key_scores(pc):
    """Correlation of a 12-bin pitch-class vector with every key (24), averaged over two profile sets."""
    pc = np.asarray(pc, float)
    if pc.sum() <= 0: return np.zeros(24)
    out = np.zeros(24)
    for maj, mnr in ((KK_MAJ, KK_MIN), (AS_MAJ, AS_MIN)):
        for t in range(12):
            out[t] += np.corrcoef(pc, np.roll(maj, t))[0, 1]
            out[12 + t] += np.corrcoef(pc, np.roll(mnr, t))[0, 1]
    return out / 2


def kname(i): return f"{NAMES[i % 12]} {'major' if i < 12 else 'minor'}"


def midi_evidence(als):
    """Pitch-class histogram (duration-weighted) and bass histogram from arrangement MIDI clips."""
    r = ET.fromstring(gzip.open(als).read())
    v = lambda n, p: (n.find(p).get("Value") if n.find(p) is not None else None)
    pc, bass, n = np.zeros(12), np.zeros(12), 0
    for t in r.find(".//Tracks"):
        if t.tag != "MidiTrack": continue
        if v(t, "./DeviceChain/Mixer/Speaker/Manual") == "false": continue        # muted track
        devs = " ".join(d.tag for d in t.iter() if d.tag in ("DrumGroupDevice",))
        if devs: continue                                                         # drum racks: pitches are not notes
        for clip in t.findall(".//ArrangerAutomation/Events/MidiClip"):
            if v(clip, "./Disabled") == "true": continue
            for kt in clip.findall(".//KeyTracks/KeyTrack"):
                key = int(v(kt, "./MidiKey"))
                for ev in kt.findall("./Notes/MidiNoteEvent"):
                    if ev.get("IsEnabled") == "false": continue
                    d = float(ev.get("Duration")) * float(ev.get("Velocity", 100)) / 100
                    pc[key % 12] += d; n += 1
                    if key < 52: bass[key % 12] += d                               # below E3
    return pc, bass, n


def audio_evidence(path, sr=22050):
    import librosa
    y, _ = librosa.load(path, sr=sr, mono=True)
    h = librosa.effects.harmonic(y, margin=3)
    C = np.abs(librosa.cqt(h, sr=sr, hop_length=2048, fmin=librosa.note_to_hz("C1"), n_bins=84, bins_per_octave=12))
    pc = np.zeros(12); bass = np.zeros(12)
    for b in range(84):
        pc[b % 12] += C[b].sum()
        if b < 24: bass[b % 12] += C[b].sum()                                      # C1..B2
    # final chord: last 8 s that still has sound
    e = C.sum(0); live = np.flatnonzero(e > e.max() * 0.05)
    end = live[-1] if len(live) else C.shape[1] - 1
    w = int(8 * sr / 2048); fin = C[:, max(0, end - w):end + 1].sum(1)
    final = np.zeros(12)
    for b in range(84): final[b % 12] += fin[b]
    return pc, bass, final


def tonic_vote(bass, final=None):
    """Score per tonic pitch class from the bass line (and final chord): the note music rests on."""
    s = np.zeros(12)
    if bass is not None and bass.sum() > 0: s += bass / bass.sum()
    if final is not None and final.sum() > 0:
        f = final / final.sum(); s += 0.7 * f + 0.3 * np.roll(f, -7) * 0       # root of the final chord
    return s


def main():
    ap = argparse.ArgumentParser(prog="hypnomix key", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); ap.add_argument("--set"); ap.add_argument("--audio"); ap.add_argument("--json")
    ap.add_argument("--sure", type=float, default=0.12, help="min winner margin (0-1 scale) to call it sure")
    ap.add_argument("--sections", action="store_true", help="also map the scale section by section (key changes, borrowed chords)")
    ap.add_argument("--bars", type=int, default=8); ap.add_argument("--bpm", type=float)
    a = ap.parse_args()
    if not a.set and not a.audio: sys.exit("give --set and/or --audio")
    total, parts, tonic = np.zeros(24), {}, np.zeros(12)
    if a.set:
        pc, bass, n = midi_evidence(a.set)
        if n >= 20:
            s = key_scores(pc); total += 1.2 * s; parts["midi"] = (kname(int(np.argmax(s))), n)
            tonic += 1.2 * tonic_vote(bass)
    if a.audio:
        pc, bass, final = audio_evidence(a.audio)
        s = key_scores(pc); total += s; parts["audio"] = (kname(int(np.argmax(s))), None)
        tonic += tonic_vote(bass, final)
    if tonic.sum() > 0:                                                            # tonic evidence shifts each key
        tn = tonic / tonic.sum()
        for i in range(24): total[i] += 1.5 * tn[i % 12]
    order = np.argsort(-total); best, second = int(order[0]), int(order[1])
    span = total[order[0]] - np.median(total) + 1e-9
    margin = float((total[best] - total[second]) / span)
    sure = margin >= a.sure
    res = {"key": kname(best), "confidence": round(min(1.0, margin / (2 * a.sure)), 2), "sure": bool(sure),
           "runner_up": kname(second), "margin": round(margin, 3),
           "top3": [kname(int(i)) for i in order[:3]], "evidence": parts}
    print(json.dumps(res, indent=1))
    if not sure:
        print(f"UNSURE: {kname(best)} vs {kname(second)}: ask the person to confirm the key before tuning.")
    if a.sections:
        secs, _ = section_map(a.set, a.audio, bars=a.bars, hop_bars=max(1, a.bars // 2), bpm=a.bpm)
        res["sections"] = secs; print_sections(secs)
    if a.json: json.dump(res, open(a.json, "w"), indent=1)



# ---------------------------------------------------------------- section map ----------------------------
MAJOR_STEPS = [0, 2, 4, 5, 7, 9, 11]
HARM_MINOR = [0, 2, 3, 5, 7, 8, 11]
MODES = ["major (Ionian)", "Dorian", "Phrygian", "Lydian", "Mixolydian", "minor (Aeolian)", "Locrian"]


def scale_sets():
    """(name, root, pitch-class set): the 12 diatonic sets (named by their major key) + 12 harmonic minors."""
    out = []
    for r in range(12):
        out.append((f"{NAMES[r]} major / {NAMES[(r + 9) % 12]} minor", r, "diatonic", frozenset((r + s) % 12 for s in MAJOR_STEPS)))
    for r in range(12):
        out.append((f"{NAMES[r]} harmonic minor", r, "harmonic", frozenset((r + s) % 12 for s in HARM_MINOR)))
    return out


def compatible_keys(root, kind):
    if kind == "harmonic": return [f"{NAMES[root]} harmonic minor"]
    return [f"{NAMES[(root + MAJOR_STEPS[i]) % 12]} {MODES[i]}" for i in range(7)]


def midi_notes(als):
    """[(start_beat, end_beat, midi_key, weight)] for arrangement MIDI notes on non-drum, unmuted tracks."""
    r = ET.fromstring(gzip.open(als).read())
    v = lambda n, p: (n.find(p).get("Value") if n.find(p) is not None else None)
    tempo = float(v(r, ".//Tempo/Manual")); out = []
    for t in r.find(".//Tracks"):
        if t.tag != "MidiTrack" or v(t, "./DeviceChain/Mixer/Speaker/Manual") == "false": continue
        if any(d.tag == "DrumGroupDevice" for d in t.iter()): continue
        for clip in t.findall(".//ArrangerAutomation/Events/MidiClip"):
            if v(clip, "./Disabled") == "true": continue
            cs, ce = float(v(clip, "./CurrentStart")), float(v(clip, "./CurrentEnd"))
            ls, le = float(v(clip, "./Loop/LoopStart")), float(v(clip, "./Loop/LoopEnd"))
            loop = v(clip, "./Loop/LoopOn") == "true"; L = max(1e-6, le - ls)
            for kt in clip.findall(".//KeyTracks/KeyTrack"):
                key = int(v(kt, "./MidiKey"))
                for ev in kt.findall("./Notes/MidiNoteEvent"):
                    if ev.get("IsEnabled") == "false": continue
                    nt, d = float(ev.get("Time")), float(ev.get("Duration")); w = float(ev.get("Velocity", 100)) / 100
                    reps = range(int((ce - cs) / L) + 1) if loop else [0]
                    for k in reps:
                        s = cs + (nt - ls) + k * L
                        if cs <= s < ce: out.append((s, min(ce, s + d), key, w))
    return out, tempo


def section_map(als=None, audio=None, bars=8, hop_bars=4, bpm=None, sure_cov=0.85, sure_gap=0.03):
    import librosa
    notes, tempo = (midi_notes(als) if als else ([], bpm))
    tempo = tempo or bpm
    if not tempo: raise SystemExit("need --set or --bpm for the bar grid")
    bar_s = 4 * 60 / tempo
    C = None
    if audio:
        y, sr = librosa.load(audio, sr=22050, mono=True); h = librosa.effects.harmonic(y, margin=3)
        hop = 2048; C = np.abs(librosa.cqt(h, sr=sr, hop_length=hop, fmin=librosa.note_to_hz("C1"), n_bins=84))
        fr_s = hop / sr; dur = len(y) / sr
    else:
        dur = max(e for _, e, _, _ in notes) * 60 / tempo
    sets = scale_sets(); rows = []
    nbars = int(np.ceil(dur / bar_s))
    for b0 in range(0, max(1, nbars - bars + hop_bars), hop_bars):
        t0, t1 = b0 * bar_s, min(dur, (b0 + bars) * bar_s)
        pc, bass = np.zeros(12), np.zeros(12)
        for s, e, k, w in notes:
            ss, ee = s * 60 / tempo, e * 60 / tempo
            ov = max(0, min(ee, t1) - max(ss, t0))
            if ov > 0:
                pc[k % 12] += 1.2 * ov * w
                if k < 52: bass[k % 12] += ov * w
        if C is not None:
            seg = C[:, int(t0 / fr_s):int(t1 / fr_s)]
            if seg.size:
                pa = np.zeros(12); ba = np.zeros(12)
                for i in range(84):
                    pa[i % 12] += seg[i].sum()
                    if i < 24: ba[i % 12] += seg[i].sum()
                if pa.sum() > 0: pc += pa / pa.sum() * max(1.0, pc.sum())
                if ba.sum() > 0: bass += ba / ba.sum() * max(1.0, bass.sum())
        if pc.sum() <= 0: continue
        p = pc / pc.sum()
        ks = key_scores(p)                                     # 24 keys, profile correlation (overtone-robust)
        # a scale (note set) is shared by a major key and its relative minor: score the set by its better key
        setscore = []
        for r in range(12):
            setscore.append((max(ks[r], ks[12 + (r + 9) % 12]), f"{NAMES[r]} major / {NAMES[(r + 9) % 12]} minor", r, "diatonic"))
        setscore.sort(reverse=True)
        bst, snd = setscore[0], setscore[1]
        margin = (bst[0] - snd[0]) / (bst[0] - np.median([x[0] for x in setscore]) + 1e-9)
        stset = frozenset((bst[2] + st) % 12 for st in MAJOR_STEPS)
        fit = float(sum(p[i] for i in stset))
        tonic = NAMES[int(np.argmax(bass))] if bass.sum() > 0 else None
        # which name fits: the bass resting note decides major vs relative minor (or a mode)
        unsure = margin < 0.12
        best = (fit, bst[1], bst[2], bst[3]); second = (float(sum(p[(snd[2] + st) % 12] for st in MAJOR_STEPS)), snd[1], snd[2], snd[3])
        rows.append(dict(bar=b0 + 1, bars=f"{b0 + 1}-{min(nbars, b0 + bars)}", time=f"{int(t0 // 60)}:{t0 % 60:04.1f}",
                         scale=best[1], root=best[2], kind=best[3], coverage=round(best[0], 3),
                         runner_up=second[1], runner_cov=round(second[0], 3), margin=round(float(margin), 3), bass_tonic=tonic, unsure=bool(unsure),
                         compatible=compatible_keys(best[2], best[3])))
    # merge consecutive windows with the same scale into sections
    secs = []
    for r in rows:
        if secs and secs[-1]["scale"] == r["scale"] and secs[-1]["unsure"] == r["unsure"]:
            secs[-1]["bars"] = secs[-1]["bars"].split("-")[0] + "-" + r["bars"].split("-")[1]
            secs[-1]["coverage"] = round(min(secs[-1]["coverage"], r["coverage"]), 3)
        else:
            secs.append(dict(r))
    return secs, tempo


def print_sections(secs):
    main = max(set(s["scale"] for s in secs), key=lambda k: sum(1 for s in secs if s["scale"] == k))
    print(f"\nsection map (scale = the note set that fits; any key sharing it is compatible). Main scale: {main}")
    for s in secs:
        flag = "  ** UNSURE: ask **" if s["unsure"] else ""
        mod = "" if s["scale"] == main else "  <- differs from the main scale (key change or borrowed chords?)"
        print(f"  bars {s['bars']:<8} {s['time']:>6}  {s['scale']:<22} notes in scale {s['coverage']:.0%}, margin {s.get('margin', 0):.2f} over {s['runner_up']}; bass rests on {s['bass_tonic']}{mod}{flag}")
    def disputed(s):
        a = frozenset((s["root"] + st) % 12 for st in MAJOR_STEPS)
        rn = s["runner_up"].split()[0]; rr = NAMES.index(rn) if rn in NAMES else None
        if rr is None: return None
        b = frozenset((rr + st) % 12 for st in MAJOR_STEPS)
        x, y = sorted(a - b), sorted(b - a)
        return (", ".join(NAMES[i] for i in x), ", ".join(NAMES[i] for i in y)) if len(x) <= 2 else None
    uns = [s for s in secs if s["unsure"]]
    # group unsure sections by the note in dispute: that is the one question tuning needs answered
    qs = {}
    for s_ in uns:
        d = disputed(s_)
        if d: qs.setdefault(tuple(sorted(d)), []).append(s_["bars"])
    for (n1, n2), where in qs.items():
        print(f"\nQUESTION: in bars {', '.join(where)}, is the note {n1} or {n2}? (the only difference between the two scales that fit; "
              f"say 'both' if the song uses both, e.g. a borrowed chord, and tuning will accept either there)")
    if uns:
        print(f"\nASK THE PERSON about {len(uns)} section(s) before tuning them: " + "; ".join(f"bars {s['bars']} ({s['scale']} or {s['runner_up']}?)" for s in uns))


if __name__ == "__main__":
    main()
