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
    "strings": (r"string|violin|viola|cello|fiddle|quartet", 5, -9.0, 0.3, 120, -14, (2.0, 2, 20, 150)),
    "pad": (r"pad|atmo|drone|texture|ambience", 3, -12.0, 0.0, 120, -14, None),
    "brass": (r"brass|horn|trumpet|sax|trombone|wind|flute", 5, -8.0, 0.3, 100, -18, (2.5, 3, 10, 120)),
    "fx": (r"\bfx|sfx|riser|sweep|impact|noise|vinyl|foley", 2, -14.0, 0.0, 100, -16, None),
    "other": (r"$^", 4, -9.0, 0.0, 60, -18, (2.0, 2, 15, 120)),
}


def by_name(name):
    n = name.lower().replace("_", " ").replace("-", " ")
    n = re.sub(r"^\d+\s*", "", n)
    order = ["backing_vocal", "synth", "lead_vocal", "kick", "snare", "toms", "hats", "overheads", "bass", "drums",
             "guitar", "strings", "keys", "synth", "pad", "brass", "fx"]
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


# hypnomix name's classifier labels -> automix roles
_FROM_NAME_LABEL = {"Kick": "kick", "Snare": "snare", "Hats": "hats", "Drums": "drums", "Bass": "bass",
                    "Guitar": "guitar", "Keys": "keys", "Pad": "pad", "Strings": "strings", "Vocal": "lead_vocal",
                    "Synth": "synth", "FX": "fx", "Lead": "other", "Instrument": "other"}


def by_sound(y, sr):
    """Fallback when the name says nothing. Uses the same tested cues as `hypnomix name`: percussiveness,
    low end, single-note pitch, vowel movement (voices change tone constantly, bowed strings don't) and note
    decay (plucked notes die away, bowed ones hold). Falls back to a simple spectral guess if that fails."""
    try:
        from hypnomix.session.names import audio_features, classify_audio
        m = y.mean(axis=1) if y.ndim > 1 else y
        lab, conf, _ = classify_audio(audio_features(m, sr))
        if conf >= 0.35:
            return _FROM_NAME_LABEL.get(lab, "other")
    except Exception:
        pass
    return _by_sound_simple(y, sr)


def _by_sound_simple(y, sr):
    """Spectral shape, transients and pitchedness (the original guess)."""
    edges = [(20, 60), (60, 250), (250, 2000), (2000, 6000), (6000, 20000)]
    e, _ = dsp.band_energy(y, sr, edges)
    share = e / (e.sum() + 1e-20)
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
    return "other"


def classify(name, y, sr):
    r = by_name(name)
    return (r, "name") if r else (by_sound(y, sr), "sound")


def preset(role):
    _, prio, level, pan, hpf, rev, comp = ROLES[role]
    return dict(prio=prio, level=level, pan=pan, hpf=hpf, reverb=rev, comp=comp)


def lead_score(y, sr):
    """The lead sings the words: its vowels move the most (harmonies often hold oohs and long vowels);
    singing time breaks ties."""
    b = dsp.block_rms_db(y, sr, 0.05)
    sung = float((b > b.max() - 35).sum()) * 0.05
    try:
        from hypnomix.session.names import audio_features
        m = y.mean(axis=1) if y.ndim > 1 else y
        return (round(audio_features(m, sr)["vowel_move"], 0), sung)
    except Exception:
        return (0, sung)


def pick_lead(vocals, sr):
    """Name of the lead among [(name, audio)] vocal stems. The one lead picker: scan, doubles, tune --guide,
    prep, masking and automix all use it, so they agree."""
    vocals = list(vocals)
    if not vocals:
        return None
    if len(vocals) == 1:
        return vocals[0][0]
    return max(vocals, key=lambda nv: lead_score(nv[1], sr))[0]


def classify_all(stems, sr):
    """{name: (role, how)} for a set of stems. Only one stem can be the lead vocal by guesswork: if a stem
    is *named* as the lead, stems guessed as voices by sound become backing vocals; if several are guessed,
    the one whose vowels move most (it sings the words) is the lead and the rest are backing vocals."""
    out = {n: classify(n, y, sr) for n, y in stems}
    named = any(r == "lead_vocal" and h == "name" for r, h in out.values())
    guessed = [n for n, (r, h) in out.items() if r == "lead_vocal" and h == "sound"]
    if named:
        keep = None
    elif len(guessed) > 1:
        keep = pick_lead([(n, y) for n, y in stems if n in guessed], sr)
    else:
        keep = guessed[0] if guessed else None
    for n in guessed:
        if n != keep:
            out[n] = ("backing_vocal", "sound")
    return out
