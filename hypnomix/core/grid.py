"""Which rhythmic grid a song (or each of its bars) is built on: straight 16ths, 8th-note triplets, 16th-note
triplets, or a mix. Timing tools snap toward THAT grid, so a triplet hit is never "fixed" onto a 16th.

Positions are counted in twelfths of a beat, which hold both families exactly:
  straight 16ths   0  3  6  9          8th triplets   0  4  8          16th triplets   0 2 4 6 8 10

Evidence: hits on the thirds of a beat (4 and 8 twelfths) only exist in triplet feels; hits on the quarter and
three-quarter points (3 and 9) only in straight ones. Each bar is judged on its own hits (and its neighbours',
so one bar with two hits doesn't flip), weighted by how strong the hits are:

    g = detect(beats, strengths, bpb=4)      # beats: hit positions in beats from bar 1
    g.positions(bar) -> [0, 3, 6, 9] etc.   g.snap(beat) -> (snapped beat, twelfth key)   g.summary()
"""
import numpy as np

STRAIGHT = (0, 3, 6, 9)
TRIPLET8 = (0, 4, 8)
TRIPLET16 = (0, 2, 4, 6, 8, 10)
NAMES = {STRAIGHT: "straight 16ths", TRIPLET8: "8th-note triplets", TRIPLET16: "16th-note triplets",
         tuple(sorted(set(STRAIGHT) | set(TRIPLET8))): "straight 16ths and 8th-note triplets (mixed)"}


def _evidence(frac, w, tol=0.03):
    """(straight-only weight, triplet-only weight, 16th-triplet-only weight) for in-beat fractions 0..1."""
    near = lambda x: np.abs(((frac - x + 0.5) % 1.0) - 0.5) < tol
    s = w[near(0.25) | near(0.75)].sum()
    t = w[near(1 / 3) | near(2 / 3)].sum()
    t16 = w[near(1 / 6) | near(5 / 6)].sum()
    return float(s), float(t), float(t16)


class Grid:
    def __init__(self, per_bar, bpb):
        self.per_bar, self.bpb = per_bar, bpb

    def positions(self, bar):
        return self.per_bar.get(bar, STRAIGHT)

    def snap(self, beat):
        """(snapped beat, key in twelfths of a beat from bar 1) to the nearest line of that bar's grid."""
        bar = int(beat // self.bpb)
        pos = self.positions(bar)
        b0 = np.floor(beat)
        cands = [b0 + p / 12 for p in pos] + [b0 + 1.0]
        s = min(cands, key=lambda x: abs(beat - x))
        return float(s), int(round(s * 12))

    def summary(self):
        """[(first bar, last bar, name)] runs of bars on the same grid (bars counted from 1)."""
        out, cur = [], None
        for bar in sorted(self.per_bar):
            nm = NAMES.get(tuple(self.per_bar[bar]), str(self.per_bar[bar]))
            if cur and cur[2] == nm and bar == cur[1]:
                cur[1] = bar + 1
            else:
                if cur: out.append(tuple(cur))
                cur = [bar + 1, bar + 1, nm]
        if cur: out.append(tuple(cur))
        return [(a, b, n) for a, b, n in out]

    def has_triplets(self):
        return any(4 in p or 2 in p for p in self.per_bar.values())


def detect(beats, strengths=None, bpb=4, span=1, ratio=2.0, min_hits=8, min_run=2, top=0.6):
    """Grid per bar from hit positions (beats from bar 1). Conservative: straight 16ths unless triplets are
    clearly there. Only the stronger hits count (the top `top` share by strength: the ones that carry the
    groove). A bar (with `span` bars either side) is triplet when its triplet-only hits outweigh the straight-only
    ones `ratio` times over with at least `min_hits` decisive hits, mixed when both sides are each at least half
    the other, and triplet sections shorter than `min_run` bars go back to the song's grid."""
    beats = np.asarray(beats, float)
    w = np.ones_like(beats) if strengths is None else np.asarray(strengths, float)
    if not len(beats):
        return Grid({}, bpb)
    keep = w >= np.quantile(w, 1 - top) if len(w) > 10 else np.ones(len(w), bool)
    beats, w = beats[keep], w[keep]
    bars = (beats // bpb).astype(int)
    frac = beats % 1.0
    MIX = tuple(sorted(set(STRAIGHT) | set(TRIPLET8)))

    def choose(sel, need):
        s, t, t16 = _evidence(frac[sel], w[sel])
        n_dec = int(sel.sum())
        if n_dec < need or (s + t + t16) <= 0:
            return None
        if t16 > ratio * max(s, t):
            return TRIPLET16
        if t > ratio * s:
            return TRIPLET8
        if s > 0 and t > 0 and min(s, t) >= 0.5 * max(s, t):
            return MIX
        return STRAIGHT

    song = choose(np.ones(len(beats), bool), min_hits) or STRAIGHT
    per = {}
    for b in range(int(bars.max()) + 1):
        sel = (bars >= b - span) & (bars <= b + span)
        per[b] = choose(sel, min_hits) or song
    # short islands that differ from their surroundings are noise: give them the song's grid
    keys = sorted(per)
    i = 0
    while i < len(keys):
        j = i
        while j + 1 < len(keys) and per[keys[j + 1]] == per[keys[i]]:
            j += 1
        if per[keys[i]] != song and (j - i + 1) < min_run:
            for k in keys[i:j + 1]:
                per[k] = song
        i = j + 1
    return Grid(per, bpb)
