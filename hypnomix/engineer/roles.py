"""What is this stem? Name first (people label their stems), then the sound itself.

Each role carries the starting moves a mix engineer would reach for. They are starting points
that the automix then adapts to the actual audio (resonances, mud, harshness, level).
"""
import re

import numpy as np

from hypnomix.core import dsp

# priority: higher wins a frequency fight (see masking.py) and sits louder in the balance
ROLES = {
    #  role        keywords                                                    prio  level  pan    hpf   reverb  comp (ratio, GR dB, attack, release)
    "lead_vocal": (r"lead|lv\b|main ?vox|vocal(?!s? ?(bv|back|harm))|vox|voice|sing", 10, 0.0, 0.0, 90, -14, (3.0, 5, 8, 90)),
    "backing_vocal": (r"\bbv|backing|back ?vox|harm|choir|adlib|double|ooh|aah", 5, -8.0, 0.45, 140, -12, (4.0, 6, 5, 80)),
    "kick": (r"kick|kik|bd\b|bass ?drum", 9, -3.0, 0.0, 30, None, (4.0, 3, 25, 70)),
    "snare": (r"snare|snr|sd\b|clap|rim", 8, -4.0, 0.0, 80, -18, (4.0, 3, 15, 90)),
    "hats": (r"hat|hh\b|hihat|ride|cymbal|shaker|tamb", 3, -14.0, 0.3, 300, -22, None),
    "toms": (r"tom", 4, -9.0, 0.35, 60, -20, (3.0, 3, 10, 120)),
    "overheads": (r"\boh\b|overhead|ohl|ohr|room|amb", 4, -10.0, 0.0, 200, None, (2.0, 2, 20, 150)),
    "drums": (r"drum|kit|beat|perc|loop|break|stem.*drum", 7, -3.0, 0.0, 30, None, (2.0, 2, 20, 120)),
    "bass": (r"bass|sub\b|808|low ?end", 8, -4.0, 0.0, 35, None, (4.0, 5, 15, 120)),
    "guitar": (r"gtr|guitar|acoustic|strum|riff|electric", 6, -7.0, 0.6, 90, -20, (2.5, 3, 15, 120)),
    "keys": (r"key|piano|pno|rhodes|organ|wurli|ep\b", 6, -7.0, 0.3, 70, -18, (2.0, 2, 20, 150)),
    "synth": (r"synth|lead ?syn|arp|pluck|bell", 5, -8.0, 0.4, 80, -18, (2.0, 2, 15, 120)),
    "pad": (r"pad|string|strings|atmo|drone|texture|ambience", 3, -12.0, 0.0, 120, -14, None),
    "brass": (r"brass|horn|trumpet|sax|trombone|wind|flute", 5, -8.0, 0.3, 100, -18, (2.5, 3, 10, 120)),
    "fx": (r"\bfx|sfx|riser|sweep|impact|noise|vinyl|foley", 2, -14.0, 0.0, 100, -16, None),
    "other": (r"$^", 4, -9.0, 0.0, 60, -18, (2.0, 2, 15, 120)),
}


def by_name(name):
    n = name.lower().replace("_", " ").replace("-", " ")
    n = re.sub(r"^\d+\s*", "", n)
    order = ["backing_vocal", "synth", "lead_vocal", "kick", "snare", "toms", "hats", "overheads", "bass", "drums",
             "guitar", "keys", "synth", "pad", "brass", "fx"]
    for r in order:
        if re.search(ROLES[r][0], n):
            return r
    return None


def side_from_name(name):
    n = name.lower()
    if re.search(r"(^|[ _\-(])(l|left)([ _\-).]|$)", n):
        return -1
    if re.search(r"(^|[ _\-(])(r|right)([ _\-).]|$)", n):
        return 1
    return 0


def by_sound(y, sr):
    """Fallback when the name says nothing: spectral shape, transients and pitchedness."""
    edges = [(20, 60), (60, 250), (250, 2000), (2000, 6000), (6000, 20000)]
    e, _ = dsp.band_energy(y, sr, edges)
    share = e / (e.sum() + 1e-20)
    m = y.mean(axis=1)
    b = dsp.block_rms_db(y, sr, 0.02)
    active = b[b > b.max() - 40]
    transient = float(np.percentile(active, 95) - np.percentile(active, 50)) if len(active) > 10 else 0
    low = share[0] + share[1]
    if low > 0.75:
        return "kick" if transient > 14 else "bass"
    if share[4] > 0.45 and transient > 10:
        return "hats"
    if transient > 16 and share[2] > 0.3:
        return "snare"
    # voice-like: most energy 250 Hz–6 kHz and a lot of pitched frames in the vocal range
    if share[2] + share[3] > 0.7:
        try:
            import librosa
            seg = m[: sr * 30]
            f0, vf, _ = librosa.pyin(librosa.resample(seg, orig_sr=sr, target_sr=16000), fmin=80, fmax=1000, sr=16000,
                                     frame_length=1024)
            voiced = float(np.mean(vf)) if len(vf) else 0
            if voiced > 0.35:
                return "lead_vocal"
        except Exception:
            pass
        return "guitar"
    return "other"


def classify(name, y, sr):
    r = by_name(name)
    return (r, "name") if r else (by_sound(y, sr), "sound")


def preset(role):
    _, prio, level, pan, hpf, rev, comp = ROLES[role]
    return dict(prio=prio, level=level, pan=pan, hpf=hpf, reverb=rev, comp=comp)


def classify_all(stems, sr):
    """{name: (role, how)} for a set of stems. Only one stem can be the lead vocal by guesswork: if a stem
    is *named* as the lead, pitched stems guessed by sound become 'other'; if several are guessed, the
    most voice-like (loudest in 1–4 kHz) keeps the role."""
    out = {n: classify(n, y, sr) for n, y in stems}
    named = any(r == "lead_vocal" and h == "name" for r, h in out.values())
    guessed = [n for n, (r, h) in out.items() if r == "lead_vocal" and h == "sound"]
    if named:
        keep = None
    elif len(guessed) > 1:
        ys = dict(stems)
        keep = max(guessed, key=lambda n: dsp.band_energy(ys[n], sr, [(1000, 4000)])[0][0] /
                   (dsp.band_energy(ys[n], sr, [(20, 20000)])[0][0] + 1e-20))
    else:
        keep = guessed[0] if guessed else None
    for n in guessed:
        if n != keep:
            out[n] = ("other", "sound")
    return out
