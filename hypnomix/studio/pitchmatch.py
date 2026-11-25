"""Pitch matching for `hypnomix vocalign --pitch`: a part's notes follow the guide, harmonies keep their interval.

For every note the part sings, the guide's pitch at the same moment is read and the interval between them measured.

  double    the interval is a unison or an octave: the part's note centre is pulled toward the guide's
  harmony   any other interval (a third, a fifth...): the interval is kept, only the drift off it is corrected,
            so the harmony stays the harmony, it just sits where the guide sits
  vibrato   optional (--vibrato 0-1, doubles only): the shape inside the note (vibrato, scoops, falls) moves that
            share of the way toward the guide's; 0 keeps the part's own

The same gentle rules as `hypnomix tune`: only notes more than --pitch-tolerance cents off (20) move, by --pitch
of the way (0.35), never more than --pitch-max cents (25). A note further off than 45 cents is halfway to another
note: it is flagged, not moved. Before a note moves, the chord under it is checked (--chords INSTRUMENTAL.wav or
--ref MIX.wav): a target that clashes with the chord while the other neighbour fits is ASKED, not moved.

The part must already be in time with the guide (this runs after the timing step). Only the moved notes are replaced
(Rubber Band R3, formants kept, 10 ms crossfades); every other sample is the part as it was.
"""
import numpy as np

from hypnomix.studio import tune as T
from hypnomix.studio import chords as CH

FLAG_CENTS = 45.0


def _mono(y):
    return (y.mean(1) if y.ndim > 1 else y).astype(np.float32)


def plan(guide_y, part_y, sr, amount=0.35, vibrato=0.0, tolerance=20.0, max_cents=25.0, chords=None,
         protect=(), only="all"):
    """Returns (curve in semitones per analysis frame, notes). Each note: t0, t1, kind, cents (off the guide's
    interval), action (ok / fix / flag / ask / protected / alone), shift (semitones applied to the centre)."""
    mg, mp = T.track_pitch(_mono(guide_y), sr), T.track_pitch(_mono(part_y), sr)
    n = min(len(mg), len(mp))
    mg, mp = mg[:n], mp[:n]
    notes = T.segment_notes(mp)
    curve = np.full(n, np.nan)
    out = []
    for nt in notes:
        k0, k1 = nt["k0"], min(nt["k1"], n)
        both = np.isfinite(mp[k0:k1]) & np.isfinite(mg[k0:k1])
        row = dict(t0=nt["t0"], t1=nt["t1"], centre=nt["centre"], kind="", cents=None, action="alone", shift=0.0)
        out.append(row)
        if both.mean() < 0.4 or both.sum() < 5:
            continue                                     # the guide isn't singing then: nothing to match
        d = float(np.median(mp[k0:k1][both] - mg[k0:k1][both]))
        r = int(round(d))
        row["kind"] = "double" if r % 12 == 0 else "harmony"
        row["interval"] = r
        row["cents"] = (d - r) * 100
        if only == "doubles" and row["kind"] != "double":
            row["action"] = "alone"; continue
        if only == "harmonies" and row["kind"] != "harmony":
            row["action"] = "alone"; continue
        if any(a < nt["t1"] and b > nt["t0"] for a, b in protect):
            row["action"] = "protected"; continue
        c = abs(row["cents"])
        if c > FLAG_CENTS:
            row["action"] = "flag"
        elif c < tolerance:
            row["action"] = "ok"
        else:
            row["action"] = "fix"
            target = nt["centre"] - (d - r)
            pick = int(round(target))
            other = pick + (1 if nt["centre"] > target else -1)
            if chords is not None:
                v, pcs, sug = CH.verdict(pick, other, chords, nt["t0"], nt["t1"])
                row["chord"] = CH.name(pcs) if pcs else ""
                if v == "ask":
                    row["action"], row["suggest"] = "ask", CH.NAMES[sug % 12]
        if row["action"] == "fix":
            row["shift"] = float(np.clip(-row["cents"] / 100 * amount, -max_cents / 100, max_cents / 100))
        if row["action"] in ("fix", "ok"):
            seg = np.full(k1 - k0, row["shift"])
            if vibrato > 0 and row["kind"] == "double":
                from scipy.ndimage import median_filter
                w = max(3, int(0.3 / (T.HOP / T.SR_A)) | 1)
                gp = np.where(both, mg[k0:k1], np.nan)
                pp = np.where(both, mp[k0:k1], np.nan)
                fill = lambda x: np.interp(np.arange(len(x)), np.flatnonzero(np.isfinite(x)), x[np.isfinite(x)])
                gp, pp = fill(gp), fill(pp)
                shape_g, shape_p = gp - median_filter(gp, w, mode="nearest"), pp - median_filter(pp, w, mode="nearest")
                extra = np.clip(vibrato * (shape_g - shape_p), -0.35, 0.35)
                seg = seg + np.where(both, extra, 0.0)
                if np.abs(extra).max() > 0.05:
                    row["vibrato"] = True
            if np.abs(seg).max() > 1e-4:
                curve[k0:k1] = seg
    idx = np.arange(n)
    have = np.isfinite(curve)
    if not have.any():
        return np.zeros(n), out
    full = np.interp(idx, idx[have], curve[have])
    full[~have] = 0.0                                   # nothing moves outside the moved notes...
    w = max(1, int(0.03 / (T.HOP / T.SR_A)))            # ...and the edges ramp over 30 ms
    full = np.convolve(np.pad(full, (w // 2, w - 1 - w // 2), mode="edge"), np.ones(w) / w, mode="valid")
    return full, out


def apply(in_path, out_path, curve, notes, sr, n_samples, channels):
    """Render: only the notes that move are replaced. Returns the output array."""
    moved = [(r["t0"], r["t1"]) for r in notes if r["action"] == "fix" or r.get("vibrato")]
    if not moved:
        return None
    _, out = T.render(in_path, out_path, curve, sr, n_samples, channels, moved=moved)
    return out


def summary(notes):
    by = {}
    for r in notes:
        by[r["action"]] = by.get(r["action"], 0) + 1
    fixed = [abs(r["cents"]) for r in notes if r["action"] == "fix"]
    return by, (float(np.median(fixed)) if fixed else 0.0)
