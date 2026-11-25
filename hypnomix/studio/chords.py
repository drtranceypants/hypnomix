"""What the instruments play under a sung note: the chord check used before any pitch correction.

A note sung between two semitones is pulled toward one of them. The key alone can't say which was meant when both
are in the key: the chord under the note can. A correction whose target clashes with that chord, while the other
neighbour is a chord tone, is not applied; it is asked about (the person decides, with --note-answer).

The chord comes from an instrumental (the song without vocals, sample-aligned with the vocal: a Live export of the
instrument groups, or a render of them). The full mix works too but the vocals are in it, so it is less sure.

  chroma(path)                     12 x N chroma frames on a HOP_S grid
  tones(ch, t0, t1)                the pitch classes sounding under [t0, t1) (strongest first, up to 4)
  take_time(ch, spans, n_frames)   the same frames re-laid in a take file's own time, from clip spans
"""
import numpy as np

SR = 22050
HOP = 512
HOP_S = HOP / SR
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def chroma(path):
    """12 x N chroma (CQT) of an audio file, mono, on the HOP_S grid; silent frames are all zero."""
    import librosa
    import soundfile as sf
    y, sr = sf.read(str(path), dtype="float32", always_2d=True)
    y = y.mean(1)
    if sr != SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=SR)
    ch = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=HOP)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP)[0]
    n = min(ch.shape[1], len(rms))
    ch = ch[:, :n] * (rms[:n] > 1e-3)        # nothing playing: no chord
    return ch


def tones(ch, t0, t1, rel=0.45, most=4):
    """Pitch classes sounding under [t0, t1): every class within `rel` of the strongest, strongest first.
    Empty when the instruments are silent there (the check then says nothing)."""
    if ch is None:
        return []
    k0 = max(0, int(t0 / HOP_S))
    k1 = min(ch.shape[1], max(k0 + 1, int(np.ceil(t1 / HOP_S))))
    if k1 <= k0:
        return []
    c = ch[:, k0:k1].mean(1)
    if c.max() <= 1e-6:
        return []
    order = [int(i) for i in np.argsort(c)[::-1] if c[i] >= rel * c.max()]
    return order[:most]


def name(pcs):
    return " ".join(NAMES[p % 12] for p in pcs) if pcs else "?"


def take_time(ch, spans, n_frames):
    """Chroma laid out in a take file's own time. `spans`: [(song_t0, song_t1, src_t0, src_t1)], one per comp clip
    that plays the take (src = seconds in the take file; a warped clip may give several spans). Take frames that no
    clip plays stay zero (no chord: the check is silent there)."""
    out = np.zeros((12, n_frames))
    for s0, s1, r0, r1 in spans:
        if r1 <= r0 or s1 <= s0:
            continue
        k0, k1 = max(0, int(r0 / HOP_S)), min(n_frames, int(np.ceil(r1 / HOP_S)))
        for k in range(k0, k1):
            st = s0 + (k * HOP_S - r0) * (s1 - s0) / (r1 - r0)
            j = int(st / HOP_S)
            if 0 <= j < ch.shape[1]:
                out[:, k] = ch[:, j]
    return out


def load(path):
    """Chroma from an audio file, or a .npz written by save() (already in the right time base)."""
    if str(path).endswith(".npz"):
        return np.load(str(path))["chroma"]
    return chroma(path)


def save(path, ch):
    np.savez_compressed(str(path), chroma=ch)


def verdict(pick, other, ch, t0, t1):
    """Check one correction. pick/other: MIDI numbers of the target and of the neighbour on the other side of the
    sung pitch. Returns (action, chord pcs, suggestion): "ok" (target fits the chord, or no chord there), "ask"
    (target clashes, the other neighbour is a chord tone: suggestion = other), "colour" (neither is in the chord:
    a passing or colour note; the nearest is kept)."""
    pcs = tones(ch, t0, t1)
    if not pcs or pick % 12 in pcs:
        return "ok", pcs, None
    if other is not None and other % 12 in pcs:
        return "ask", pcs, other
    return "colour", pcs, None
