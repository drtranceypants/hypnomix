"""`hypnomix abset` for a HypnoMix DAW session: one new snapshot where every proposed fix can be switched A / B in the
HypnoMix DAW, level-matched, without rendering anything.

  hypnomix abset SCAN_DIR [--ids ID,ID,...] [--out "Song (A-B).ardour"]      (the scan of an .ardour session)

For each finding that Apply writes into a HypnoMix DAW session (fades, cuts, spike dips, mixer moves), the fix is built on
its own with the same code as `hypnomix fix` (workflow/fix_ardour.py, on a fresh read of the original), and then:

  clip fixes   (fades, cuts, dips)  the fixed track's playlist is copied into the new snapshot as another playlist
               of that track, named "<playlist>.B <id>" (new ids). The track keeps playing its own playlist, so the
               snapshot plays exactly like the original. B = the track plays the copy (`ab_use_playlist`), A = its
               own again: instant, seamless while playing, nothing else changes.
  mixer moves  (fader, pan, mute)  nothing is written: the A and B values are in ab_ardour.json and the Review view
               sets them over MCP (`track_set_fader_db`, `track_set_pan`, `track_set_mute`).

Level matching: for each finding the rough mix (every heard track's regions with gain, fades and envelopes, faders
and pans; muted tracks and tracks in a muted folder left out; no plug-ins) is rendered around the spot as it is and
with the fix, and the difference in loudness (LUFS where the span is long enough, else RMS) is `match_db`; a mute or
unmute fix is matched like any other. The mixer A / B fader values are the fader alone (a track's trim is not in
them, since the Review view sets the fader only). While you listen, the louder side is turned down by that much on the
master fader, so you judge the change, not the level, by at most MAX_MATCH_DB (12 dB): a fix that silences or brings
in most of what plays at the spot (muting the only track there, a cut) would otherwise turn the other side down to
silence, so the item keeps the measured difference as `level_db` and says `match_capped`. `match_db` is measured, not
heard: plug-ins after the change (compressors) can move it.

The Review view in the DAW (connected to the engine) shows **Build A/B**, then **Open A/B session** (the engine
restarts on the new snapshot: nothing in the open one is saved), then A, B and Blind on each finding (Blind picks at
random which is X and which is Y; you choose, then see which was which; the choices go into the scan's blind.json).
Approving still happens in the review, and Apply still writes the real snapshot from the original.

Writes the snapshot beside the original (never over a file, never through a link: it is written to a hidden name in
the folder, checked, then put in place only if the name is still free) and SCAN_DIR/ab_ardour.json: which switch
belongs to which finding, for every snapshot built from this scan (a numbered rebuild keeps the earlier ones). Read
back before it is kept: the new snapshot must read as the same session (same tracks, regions, gains, fades and faders
as the original); else it is kept as "(BROKEN, do not open)" (numbered when that name is taken).
"""
import copy, json, math, os, re, time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

CLIP_OPS = ("fade", "cut", "dip")
MIXER_OPS = ("mixer",)
SPAN_PAD = 1.0                  # seconds either side of a spot for the level match
SR = 22050                      # the level match's render rate (a rough mix, not for listening)
MAX_MATCH_DB = 12.0             # the most the louder side is turned down: beyond it one side is (nearly) silence


def _ids(root):
    v = [int(x.get("id")) for x in root.iter() if (x.get("id") or "").isdigit()]
    return max(v + [int(root.get("id-counter") or 0)])


def _playlist_of(root, route):
    pid = route.get("audio-playlist") or route.get("playlist")
    if not pid:
        ds = route.find("Diskstream")
        pid = ds.get("playlist") if ds is not None else None
    pls = root.find("Playlists")
    if pid is None or pls is None:
        return None
    return next((p for p in pls if p.get("id") == pid or p.get("name") == pid), None)


def _route(root, rid):
    return next((r for r in root.iter("Route") if r.get("id") == rid), None)


def _span(f, tempo, bpb, end, bars_ok=True):
    """Seconds around a finding for the level match. bars_ok=False (the tempo or the meter changes): a position given
    only as a bar is not trusted, so the span is the start of the song, as for a finding with no position."""
    from hypnomix.app.dawreview import seconds_of
    e = f.get("edit") if isinstance(f.get("edit"), dict) else {}
    if isinstance(e.get("t0"), (int, float)) and isinstance(e.get("t1"), (int, float)):
        a, b = float(e["t0"]), float(e["t1"])
    else:
        w = str(f.get("where") or "")
        if not bars_ok and not re.search(r"\(-?\d+(?:\.\d+)? s\)", w) and not re.match(r"\s*\d+(?::\d{1,2}){1,2}", w):
            f = dict(f, where="whole")                     # no bar position: the edit's own time, or the start
        t = seconds_of(f, tempo, bpb)
        if t is None:
            return 0.0, min(end, 30.0)
        a = b = t
    return max(0.0, a - SPAN_PAD), min(end, b + SPAN_PAD + 0.5)


def _level(y, sr):
    from hypnomix.core import dsp
    if len(y) >= int(0.45 * sr):
        try:
            v = float(dsp.lufs(y, sr))
            if math.isfinite(v):
                return v
        except Exception:
            pass
    r = float(np.sqrt(np.mean(y ** 2)) + 1e-12)
    return 20 * math.log10(r)


def heard(p, t):
    """The track is in the rough mix: the tracks `mixdown` takes by default (audio, with clips, not muted, no muted folder)."""
    return any(x is t for x in p.audio_tracks())


def _fader(t):
    v = t.fader_db
    return round(v, 2) if math.isfinite(v) else -120.0


def _claim(src, dst):
    """Put the finished file src at dst only if dst does not exist (a dangling link counts as existing); never follows a
    link at dst. False when the name is taken."""
    try:
        os.link(src, dst)
        return True
    except FileExistsError:
        return False
    except (OSError, NotImplementedError, AttributeError):
        pass                                   # a file system without hard links: create it exclusively and copy
    try:
        fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0), 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "wb") as w:
        w.write(Path(src).read_bytes())
        w.flush()
        os.fsync(w.fileno())
    return True


def _taken(p):
    return os.path.lexists(p)


class Mix:
    """The original's rough mix, rendered once; a fixed track swapped in for each finding."""

    def __init__(self, project):
        from hypnomix.project import model as M
        self.p, self.M = project, M
        self.end = project.end()
        self.warn = []
        self.full = M.mixdown(project, sr=SR, warn=self.warn)
        self.contrib = {}

    def track(self, p, t):
        """One track's share of the rough mix: silence when it is not heard (the same rule that built `full`)."""
        if not heard(p, t):
            return np.zeros_like(self.full)
        return self.M.mixdown(p, sr=SR, tracks=[t], length=self.end, warn=self.warn)[: len(self.full)]

    def match(self, name, fixed, span):
        """dB the fixed mix is louder than the original over span (seconds), measured (not capped)."""
        ta, tb = self.p.track(name), fixed.track(name)
        if ta is None or tb is None:
            return 0.0
        if name not in self.contrib:
            self.contrib[name] = self.track(self.p, ta)
        a = self.full
        b = a - self.contrib[name] + self._pad(self.track(fixed, tb))
        i0, i1 = int(span[0] * SR), max(int(span[0] * SR) + 1, int(span[1] * SR))
        return round(_level(b[i0:i1], SR) - _level(a[i0:i1], SR), 2)

    def _pad(self, y):
        out = np.zeros_like(self.full)
        n = min(len(y), len(out))
        out[:n] = y[:n]
        return out


def build(sd, ids=None, out=None, session=None):
    from hypnomix import project as PJ
    from hypnomix.core import atomic
    from hypnomix.project import ardour_edit as E
    from hypnomix.workflow import abset as AB, fix_ardour as FA, oversight as O
    sd = Path(sd)
    data = O.load_findings_doc(sd)
    orig = Path(session or data.get("set") or "")
    if orig.is_dir() and PJ.ardour_session(orig) is not None:     # the scan of a session folder: its .ardour
        orig = PJ.ardour_session(orig)
    if orig.suffix.lower() != ".ardour" or not orig.exists():
        raise RuntimeError("this scan has no HypnoMix DAW session to build an A/B snapshot from")
    cands = AB.candidates(data["findings"], ids)
    if not cands:
        raise RuntimeError("no findings that change the session (pass --ids to choose)")
    out = Path(out) if out else orig.with_name(f"{orig.stem} (A-B).ardour")
    if not out.is_absolute():
        out = orig.parent / out
    if out.suffix.lower() != ".ardour":
        out = out.with_name(out.name + ".ardour")
    if out.parent.resolve() != orig.parent.resolve():
        raise RuntimeError("the A/B snapshot goes in the session's own folder (it shares its sound files)")
    if _taken(out) or out.resolve() == orig.resolve():
        raise RuntimeError(f"{out.name} already exists: choose a new name with --out (nothing is overwritten)")
    dec = O.load_decisions(sd)

    base = PJ.load(orig)            # first: a damaged file stops here with the reader's one sentence
    tree = ET.parse(orig)
    ab = tree.getroot()
    next_id = _ids(ab) + 1
    mix = None
    items = {}
    for f in cands:
        fid = f["id"]
        ed = f.get("edit") if isinstance(f.get("edit"), dict) else {}
        op = ed.get("op")
        if op not in CLIP_OPS + MIXER_OPS:
            items[fid] = dict(kind=None, track=f.get("track"), problem=f.get("problem"),
                              note="not previewable here: a HypnoMix DAW A/B session holds fades, cuts, spike dips and mixer moves")
            continue
        p = PJ.load(orig)
        log, failed, skipped = [], [], []
        done = FA.apply_edits(p, [f], dec, log, failed, skipped)
        if not done:
            why = "; ".join([str(x) for x in failed] + [w for _, w in skipped]) or "the fix changed nothing"
            items[fid] = dict(kind=None, track=f.get("track"), problem=f.get("problem"), note="could not be built: " + why)
            continue
        if mix is None:
            print("  rendering the rough mix for level matching …", flush=True)
            mix = Mix(base)
        span = _span(f, base.tempo or 120.0, base.beats_per_bar or 4, max(mix.end, 1.0),
                     bars_ok=base.tempo_changes <= 1 and not getattr(base, "meter_changes", 0))
        tr = p.track(f["track"])
        rid = tr.native.get("id")
        item = dict(track=tr.name, trackId=rid, problem=f.get("problem"), fix=f.get("fix"), span=[round(span[0], 3), round(span[1], 3)],
                    did=log[0][2:] if log else "")
        if op in MIXER_OPS:
            a_t = base.track(tr.name)
            item.update(kind="mixer",
                        a=dict(fader_db=_fader(a_t), pan=round(a_t.pan, 3), mute=bool(a_t.muted)),
                        b=dict(fader_db=_fader(tr), pan=round(tr.pan, 3), mute=bool(tr.muted)))
        else:
            fixed_pl = _playlist_of(p.native, tr.native)
            a_pl = _playlist_of(ab, _route(ab, rid))
            if fixed_pl is None or a_pl is None:
                items[fid] = dict(kind=None, track=tr.name, problem=f.get("problem"), note="could not be built: the track's playlist was not found")
                continue
            if ET.tostring(fixed_pl) == ET.tostring(a_pl):
                items[fid] = dict(kind=None, track=tr.name, problem=f.get("problem"), note="the fix changed nothing in the session")
                continue
            b_pl = copy.deepcopy(fixed_pl)
            for el in b_pl.iter():
                if (el.get("id") or "").isdigit():
                    el.set("id", str(next_id))
                    next_id += 1
            name = f"{a_pl.get('name')}.B {fid}"
            b_pl.set("name", name)
            b_pl.set("orig-track-id", rid)
            b_pl.set("shared-with-ids", "")
            ab.find("Playlists").append(b_pl)
            item.update(kind="playlist", a_playlist=a_pl.get("name"), a_playlist_id=a_pl.get("id"),
                        b_playlist=name, b_playlist_id=b_pl.get("id"))
        measured = mix.match(tr.name, p, span)
        item["match_db"] = round(max(-MAX_MATCH_DB, min(MAX_MATCH_DB, measured)), 2)
        if item["match_db"] != measured:
            item.update(level_db=measured, match_capped=True)
        items[fid] = item
        print(f"  {fid}: {item['kind']} on {tr.name}, B is {measured:+.1f} dB"
              + (f" (matched by {item['match_db']:+.1f} dB at most)" if item.get("match_capped") else ""), flush=True)

    ab.set("id-counter", str(next_id + 1))
    ab.set("name", out.stem)
    tmp = out.with_name(f".{out.stem}.{os.getpid()}.tmp.ardour")      # hidden, in the same folder, ours alone
    try:
        if _taken(tmp):
            os.unlink(tmp)
        with open(tmp, "xb") as w:
            tree.write(w, encoding="UTF-8", xml_declaration=True)
            w.flush()
            os.fsync(w.fileno())
        errs = []
        try:
            e2, changes = E._model_diff(PJ.load(orig), PJ.load(tmp))
            errs += e2 + [f"plays differently from the original: {c}" for c in changes]
        except (Exception, SystemExit) as e:
            errs.append(f"the A/B snapshot does not read back ({e})")
        seen = [int(x.get("id")) for x in ET.parse(tmp).getroot().iter() if (x.get("id") or "").isdigit()]
        dup = len(seen) - len(set(seen))
        if dup and dup != len(_dups(orig)):
            errs.append("ids are not unique")
        if errs:
            n, bad = 2, out.with_name(out.stem + " (BROKEN, do not open).ardour")
            while not _claim(tmp, bad):
                bad = out.with_name(f"{out.stem} (BROKEN, do not open) {n}.ardour")
                n += 1
            raise RuntimeError("the A/B snapshot is not sound, kept as " + bad.name + ": " + "; ".join(errs[:4]))
        if not _claim(tmp, out):
            raise RuntimeError(f"{out.name} already exists: choose a new name with --out (nothing is overwritten)")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if out.parent.resolve() != orig.parent.resolve():
        raise RuntimeError("the A/B snapshot did not land in the session's own folder")
    spec = dict(daw="ardour", session=str(out), original=str(orig), built=time.strftime("%Y-%m-%d %H:%M"),
                level_match="rough mix (heard tracks' regions, gains, fades, envelopes, faders, pans; mutes respected; "
                            "no plug-ins), LUFS (RMS under 0.45 s) around each spot", items=items)
    old = load(sd) or {}
    builds = {k: v for k, v in (old.get("builds") or {}).items() if isinstance(v, dict)}
    if old.get("session") and old.get("session") not in builds:      # a file from before builds were kept
        builds[old["session"]] = {k: v for k, v in old.items() if k != "builds"}
    builds[str(out)] = spec
    atomic.write_json(sd / "ab_ardour.json", dict(spec, builds=builds))
    return out, spec


def _dups(p):
    seen, d = set(), []
    for x in ET.parse(p).getroot().iter():
        v = x.get("id")
        if (v or "").isdigit():
            if v in seen:
                d.append(v)
            seen.add(v)
    return d


def load(sd, session=None):
    """The scan's A/B spec: the newest build, or with session the build of that snapshot (None when there is none)."""
    from hypnomix.core import atomic
    doc = atomic.load_json(Path(sd) / "ab_ardour.json", None)
    if not doc or session is None:
        return doc
    try:
        want = Path(session).resolve()
        for k, v in (doc.get("builds") or {doc.get("session", ""): doc}).items():
            if isinstance(v, dict) and k and Path(k).resolve() == want:
                return {x: y for x, y in v.items() if x != "builds"}
    except OSError:
        pass
    return None


def save_blind(sd, fid, picked, was):
    """One blind choice (picked: "X" | "Y"; was: "A" | "B" behind it) into SCAN_DIR/blind.json, whole or not at all."""
    from hypnomix.core import atomic
    p = Path(sd) / "blind.json"
    doc = atomic.load_json(p, {}) or {}
    doc.setdefault(fid, []).append(dict(picked=picked, was=was, at=time.strftime("%Y-%m-%d %H:%M:%S"), daw="ardour"))
    atomic.write_json(p, doc)
    return doc[fid]


def summary(out, spec):
    ok = sum(1 for it in spec["items"].values() if it.get("kind"))
    lines = [f"wrote {out}", f"  {ok} of {len(spec['items'])} findings can be switched A/B in HypnoMix DAW; the original is unchanged"]
    for fid, it in spec["items"].items():
        if it.get("note"):
            lines.append(f"  {fid}: {it['note']}")
        elif it.get("kind"):
            lines.append(f"  {fid}: {it['kind']} on {it['track']}, B {it.get('level_db', it['match_db']):+.1f} dB (the louder side is "
                         f"turned down {'by ' + format(abs(it['match_db']), 'g') + ' dB, the most it is, ' if it.get('match_capped') else ''}while you listen)")
    lines.append("In the DAW view: Review → Open A/B session, then A / B / Blind on each finding.")
    return "\n".join(lines)
