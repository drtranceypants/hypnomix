"""Item edges and fades that cut into a sung word, in a REAPER (or any model-read) project: Live's `edges`
check, run on the shared project model.

Every item on the vocal tracks is rendered twice: as the project plays it, and opened 150 ms past both edges with
no fades. The detectors are Live's own (`session/edges.py`): a consonant ("s", "sh", "t") the take sings at an edge
that the comp turns down while the word goes on; a fade that ducks a sound starting inside it; sound running across
an edge that no other item covers. They work in "beats x seconds per beat"; here positions are seconds with one
second per "beat", so they run unchanged.

REAPER fixes (only approved items, into the new .rpp):
  consonant  the item edge moved out to 10 ms before the consonant (a neighbouring item ending or starting there
             is trimmed to match, so nothing overlaps that did not before), and a 10 ms fade
  fades      the fade set to 10 ms (shortened: this is the one fix that shortens a fade)
  cuts       listen only: never moved automatically
"""
from dataclasses import replace

import numpy as np
from scipy.signal import sosfiltfilt

from hypnomix.project.model import render_clip
from hypnomix.session import edges as ED

LOOK_MS = 150
SR = ED.SR


def opened(c, look_s):
    """The clip with both edges opened by look_s and no fades (positions shift; the audio stays where it is)."""
    tk = c.take
    t2 = replace(tk, offset=tk.offset - look_s * tk.rate)
    return replace(c, start=c.start - look_s, length=c.length + 2 * look_s, takes=[t2], active=0,
                   fade_in=0.0, fade_out=0.0)


def scan(p, vocal_tracks, look=LOOK_MS, rng=25, max_fade_ms=40, loss=6, cut_range=15, swell_s=2.0,
         fix_within_ms=150, fix_min_db=10, cons_range=25, cons_loss=6):
    from hypnomix.project.rpp_edit import locator
    look_s = look / 1000
    X = int(look_s * SR)
    w = int(0.02 * SR)
    found, where = [], {}
    for t in p.tracks:
        if t.name not in vocal_tracks:
            continue
        clips = sorted((c for c in t.clips if not c.muted and c.kind == "audio" and c.path is not None),
                       key=lambda c: c.start)
        if not clips:
            continue
        spans = [(c.start, c.end) for c in clips]
        comp = p.render(t, SR, max(e for _, e in spans))
        comp_hf = ED.env_db(sosfiltfilt(ED.HF, comp), int(0.01 * SR))[::ED.HOP]
        comp_bb = ED.env_db(comp, int(0.01 * SR))[::ED.HOP]
        for ci, c in enumerate(clips):
            s, e = c.start, c.end
            L = int(c.length * SR)
            op = render_clip(opened(c, look_s), SR, [], t.name)
            if op is None:
                continue
            body = op[X:X + L]
            if not len(body) or np.max(np.abs(body)) < 1e-6:
                continue
            key = f"{t.index}:{ci}"
            where[key] = locator(t, c)
            peak = float(np.max(ED.env_db(body, int(0.05 * SR))))
            floor = peak - rng
            fi, fo = c.fade_in, c.fade_out
            base = dict(track=t.name, clip=key, off=not t.on)

            def covered(t0, t1):
                return any(j != ci and a0 <= t0 + 1e-9 and a1 >= t1 - 1e-9 for j, (a0, a1) in enumerate(spans))

            def quiet(lo, hi):
                seg = op[max(0, lo):max(0, hi)]
                if len(seg) < w:
                    return None
                ed = ED.env_db(seg, int(0.005 * SR))
                i = int(np.argmin(ed))
                return (max(0, lo) + i - X) / SR, float(ed[i]) - peak

            found += ED.consonant_hits(op, X, L, s, e, 1.0, fi, fo, peak, comp_hf, comp_bb, base, look,
                                       cons_range, cons_loss)
            pre, post = op[X - w:X], op[X:X + w]
            if ED.rms_db(pre) > peak - cut_range and ED.rms_db(post) > floor and not covered(s - look_s, s):
                q = quiet(0, X)
                found.append(dict(base, kind="start-cut", beat=s, edge="in", level=ED.rms_db(pre) - peak,
                                  quiet_ms=q[0] * 1000 if q else None, quiet_db=q[1] if q else None))
            if max_fade_ms < fi * 1000 < swell_s * 1000:
                n = min(L, int(fi * SR))
                lead = int(0.03 * SR)
                reg = op[X - lead:X + n]
                ramp = np.concatenate([np.zeros(lead), np.linspace(0, 1, n)])
                hits = ED.ducked_onsets(reg, ramp, floor, loss)
                if hits:
                    d, tt, lo = max(hits)
                    at_ms = tt * 1000 - 30
                    thump = lo > 0.6
                    found.append(dict(base, kind="fade-in", beat=s, edge="in", fade_ms=fi * 1000, at_ms=at_ms, duck=d,
                                      thump=thump, sure=(not thump) and at_ms <= fix_within_ms and d >= fix_min_db))
            pre, post = op[X + L - w:X + L], op[X + L:X + L + w]
            if ED.rms_db(pre) > floor and ED.rms_db(post) > peak - cut_range and not covered(e, e + look_s):
                q = quiet(X + L, X + L + X)
                found.append(dict(base, kind="end-cut", beat=e, edge="out", level=ED.rms_db(post) - peak,
                                  quiet_ms=(q[0] - c.length) * 1000 if q else None, quiet_db=q[1] if q else None))
            if max_fade_ms < fo * 1000 < swell_s * 1000:
                n = min(L, int(fo * SR))
                hits = ED.ducked_onsets(body[L - n:], np.linspace(1, 0, n), floor, loss)
                if hits:
                    d, tt, lo = max(hits)
                    found.append(dict(base, kind="fade-out", beat=e, edge="out", fade_ms=fo * 1000,
                                      at_ms=(tt - n / SR) * 1000, duck=d, thump=lo > 0.6, sure=False))
    best = {}
    for f in [f for f in found if f["kind"] == "consonant"]:
        k = (f["track"], f["clip"], f["edge"])
        if k not in best or abs(f["move_s"]) > abs(best[k]["move_s"]):
            best[k] = f
    found = [f for f in found if f["kind"] != "consonant"] + list(best.values())
    found.sort(key=lambda f: (f["beat"], f["track"]))
    return found, where


def findings(p, found, where, daw_words):
    """Live's edge findings, with REAPER words, the bar from seconds, and each target as an item locator."""
    for f in found:
        f["beat"] = f["beat"] * p.tempo / 60.0                 # seconds -> beats, for Live's bar numbering
    out = ED.findings(found)
    for f in out:
        f["targets"] = [[where[t[0]], *t[1:]] for t in f.get("targets", [])]
        for k in ("problem", "fix"):
            f[k] = (f[k].replace("move the edge in Live", f"move the edge in {daw_words['daw']}")
                    .replace("move that edge in Live", f"move that edge in {daw_words['daw']}")
                    .replace("clip", daw_words["item"]).replace("`hypnomix edges SET --tracks", "`hypnomix edges --tracks"))
        if p.daw != "reaper" and f.get("applies") == "set":
            f["applies"] = "manual"
        elif f.get("applies") == "set":
            f["edit"] = dict(op="edges", targets=f["targets"])
    return out


# ---------------------------------------------------------------- REAPER fixes
def set_fade_exact(clip, which, seconds):
    item = clip.native
    key = "FADEIN" if which == "in" else "FADEOUT"
    ln = item.line(key)
    t = list(ln.tokens) if ln is not None else [key, 1, 0, 0, 1, 0, 0, 0]
    while len(t) < 8:
        t.append("0")
    t[2], t[3] = float(seconds), 0                      # the length; no auto-crossfade length overriding it
    item.set(key, *t[1:], after="LOOP")
    if which == "in":
        clip.fade_in = seconds
    else:
        clip.fade_out = seconds


def move_start(track, clip, by_s):
    """Start the item by_s seconds earlier (by_s > 0), same audio in place; a neighbour ending after the new start
    is trimmed to end there."""
    by_s = min(by_s, clip.take.offset / max(clip.take.rate, 1e-9), clip.start)   # not before the file or the project
    if by_s <= 0:
        return 0.0
    new = clip.start - by_s
    for o in track.clips:
        if o is not clip and o.start < new < o.end <= clip.start + 1e-6:
            o.native.set("LENGTH", float(new - o.start))
            o.length = new - o.start
    clip.native.set("POSITION", float(new))
    clip.native.set("LENGTH", float(clip.length + by_s))
    _shift_offsets(clip, -by_s)
    clip.start, clip.length = new, clip.length + by_s
    return by_s


def move_end(track, clip, by_s):
    """End the item by_s seconds later; a neighbour starting before the new end is trimmed to start there."""
    if by_s <= 0:
        return 0.0
    new = clip.end + by_s
    for o in track.clips:
        if o is not clip and clip.end - 1e-6 <= o.start < new < o.end:
            d = new - o.start
            o.native.set("POSITION", float(new))
            o.native.set("LENGTH", float(o.length - d))
            _shift_offsets(o, d)
            o.start, o.length = new, o.length - d
    clip.native.set("LENGTH", float(clip.length + by_s))
    clip.length += by_s
    return by_s


def _shift_offsets(clip, d):
    """Move every take's source offset by d seconds of timeline (keeps the audio where it was)."""
    from hypnomix.project import rpp
    for tk in clip.takes:
        for ln in (tk.native or []):
            if isinstance(ln, rpp.Line) and ln.key == "SOFFS":
                ln.set(float(float(ln.tokens[1]) + d * tk.rate))
        tk.offset += d * tk.rate


def apply_edges(p, f, fix_fade_ms=10):
    """One approved edges finding into the loaded project. Returns lines for the log."""
    from hypnomix.project.rpp_edit import locate
    lines = []
    for tg in f["edit"]["targets"]:
        hit = locate(p, tg[0])
        if hit is None:
            lines.append(f"  skipped an edge at {tg[0]['start']:.3f} s: the item is no longer there")
            continue
        tr, c = hit
        edge = tg[1]
        if len(tg) > 2 and tg[2] == "consonant":
            mv = abs(float(tg[3]))
            got = move_start(tr, c, mv) if edge == "in" else move_end(tr, c, mv)
            lines.append(f"  {tr.name} @ {c.start:.3f} s: edge moved {got * 1000:.0f} ms out for the consonant")
        set_fade_exact(c, edge, fix_fade_ms / 1000)
        lines.append(f"  {tr.name} @ {c.start:.3f} s: fade {edge} {fix_fade_ms} ms")
    return lines
