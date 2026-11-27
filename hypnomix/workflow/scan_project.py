"""First-pass scan of a REAPER project (.rpp) or a HypnoMix Studio session (.ardour): the same review list as a Live set,
from the shared project model.

    hypnomix scan SONG.rpp [--mix MIX.wav] [--ref MIX.wav] [--deep] [--only GROUP ...]
    hypnomix scan SONG.ardour (or the session folder) [same options]

The DAW can stay open (nothing is written next to the project; everything goes to the output folder). Every audio
track that is heard is rendered once from the project (item and take volume, fades, loops, sections, playrate; no
FX, no faders) into raw/renders/, and the groups work from those renders and the model:

  names       default-named tracks ("Track 3") named by how they sound; the tracks put in working order; vocal
              stacks (each part on the track for its pitch)
  files       items whose audio file is missing
  clips       clicks at item edges with no fade; level jumps where one item meets the next (comps)
  timing      instrument hits out of time with the band (REAPER: nudges written as stretch markers)
  vocals      pitch of every vocal track (tune --report-only), doubles vs the lead in time, harmony balance question,
              vocal level line to line and upper parts under the melody (vocallevel)
  effects     plug-ins switched off or offline, whole FX chains off, several limiters on one track; sidechained
              ReaComps simulated hit by hit
  devices     every ReaComp judged on its track's own audio (the Live Compressor check: too little, too much,
              release bending the bass, drum transients clamped) with suggested settings `fix` writes into it; a low
              cut suggested where a ReaEQ has none and the part rumbles under 80 Hz; ReaGate and ReaLimit listed,
              not judged (their saved settings are not read); a ReaComp with Wet at 0 or a parallel dry/wet mix is
              not judged; the master track's plug-ins are not read. HypnoMix DAW: each ACE Compressor judged the
              same way (Range, Auto Release, Mix simulated; the settings listed by hand), ACE EQ's High Pass band
              as the low cut, a hard-driven Hypnomix Saturator. See `devices_project.py`
  recordings  every source file the project plays: clipping, levels, noise floor, DC, sibilance, breaths, clicks
  noise       items boosted a lot: the boost lifts the take's own noise floor
  intent      "is this deliberate?": automation, hard pans, muted tracks with items, big item gains, polarity flips,
              stretch markers
  mix         with --mix: loudness, true peak, release checks, translation, sections
  stems       with --deep: frequency fights and mic phase between tracks
  structure   from the project file alone: does it read back byte for byte (else do not apply fixes), folders that
              do not close, sends from tracks that are not there, faders at the top or almost silent (REAPER; a
              HypnoMix Studio session gets only the nearly-silent fader check)

Without --ref, the key and tuning are measured from a rough mix of the project's renders (faders and pans, no FX).
Findings that `hypnomix fix` can write into a new project say `set` (a new .rpp; for a HypnoMix Studio session only item
fades, cuts and dips, into a new .ardour snapshot that HypnoMix has written and read back but not opened in
a released DAW); the rest are *manual* (what to do in the DAW). Findings that make new audio (tune, dehiss, deess) work the
same as for a Live set.

Behaves like a scan of a Live set (the shared parts are in `scan.py`, which calls this): a re-scan into the same
folder keeps each decision on ITS finding and sets aside those that no longer match; a folder that holds another
project is never reused; a check that did not run is one plain sentence in the notes, with the traceback in
raw/<group>-error.txt; the tuning and timing preferences (off = never propose) are honoured. The renders in raw/ are
kept only while the project and its audio files are unchanged.
"""
import hashlib
import json
import math
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix import project as PJ
from hypnomix.core import atomic as AT
from hypnomix.project.model import render_clip
from hypnomix.workflow import scan as SC

# how each DAW names things, for the fix text
WORDS = {
    "reaper": dict(daw="REAPER", item="item", relink="REAPER offers to search for missing media when the project "
                   "opens, or re-link it in the item's properties (Choose new file)"),
    "ardour": dict(daw="HypnoMix Studio", item="region", relink="HypnoMix Studio asks for missing files when the session opens "
                   "(Session > Properties > Misc lists the search paths), or import it again"),
}
W = dict(WORDS["reaper"])

GROUPS = ["names", "files", "clips", "timing", "vocals", "effects", "devices", "recordings", "noise", "intent", "structure",
          "mix", "stems", "mpe"]
SR = 44100
LIMITER_WORDS = ("limit", "maximi", "loudmax", "clipper")


def _where(p, t):
    return f"{p.where(t)} ({t:.2f} s)"


def _f(prefix, n, **kw):
    kw.setdefault("severity", "low")
    kw.setdefault("where", "")
    kw.setdefault("applies", "manual")
    return dict(id=f"{prefix}-{n}", **kw)


# ---------------------------------------------------------------- renders, shared by every group
def signature(p):
    """What the renders were made from: the project file and the size and time of every audio file it plays. A
    re-scan into the same folder after the project (or a file) changed must not judge from the old renders."""
    h = hashlib.sha1()
    try:
        h.update(Path(p.path).read_bytes())
    except OSError:
        h.update(str(p.path).encode())
    for t in p.tracks:
        for c in t.clips:
            for tk in c.takes:
                for path in ([tk.path] if tk.path else []) + list(tk.extra_paths or []):
                    try:
                        st = Path(path).stat()
                        h.update(f"{path}|{st.st_size}|{st.st_mtime_ns}".encode())
                    except OSError:
                        h.update(f"{path}|missing".encode())
    return h.hexdigest()


class Renders:
    """Each heard audio track rendered once (float WAV), plus a rough stereo mix for key and tuning. The renders are
    kept for the next run only while the project and its audio are the same (a stamp beside them says which)."""
    STAMP = ".stamp"

    def __init__(self, p, od):
        self.p, self.dir = p, Path(od) / "raw" / "renders"
        self.files, self.warn = {}, []

    def _fresh(self, sig):
        """Claim the folder for this project state. The stamp is written FIRST, so a second scan running into the
        same folder (several `--only` scans in parallel) sees the same stamp and reuses the renders instead of
        deleting them. Old renders (and the rough mix) are deleted only when a stamp says ANOTHER project state, or
        when there is no stamp but renders (made by an older version, so nobody can say what they were made from)."""
        stamp = self.dir / self.STAMP
        try:
            old_sig = stamp.read_text(encoding="utf-8").strip()
        except OSError:
            old_sig = None
        if old_sig == sig:
            return
        AT.write_text(stamp, sig, backup=False)
        for old in list(self.dir.glob("*.wav")) + [self.dir.parent / "renders-mix.wav"]:
            try:
                old.unlink()
            except OSError:
                pass

    @staticmethod
    def _put(path, y):
        """Write a render whole or not at all (a second scan reading it never sees half a file)."""
        part = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.part")
        try:
            sf.write(str(part), y, SR, subtype="FLOAT", format="WAV")
            os.replace(part, path)
        finally:
            part.unlink(missing_ok=True)

    def build(self, jobs=4):
        self.dir.mkdir(parents=True, exist_ok=True)
        sig = signature(self.p)
        self._fresh(sig)
        tracks = [t for t in self.p.audio_tracks() if any(c.kind == "audio" for c in t.clips)]
        L = self.p.end()

        def one(t):
            out = self.dir / f"{t.safe_name}.wav"
            if not out.exists():
                y = self.p.render(t, SR, L, self.warn)
                if not np.any(y):
                    return t, None
                self._put(out, y.astype(np.float32))
            return t, out

        with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
            for t, path in ex.map(one, tracks):
                if path is not None:
                    self.files[t.name] = path
        return self

    def mix(self):
        """raw/renders-mix.wav: renders summed with faders (folders included) and pans."""
        out = self.dir.parent / "renders-mix.wav"
        if out.exists() or not self.files:
            return out if out.exists() else None
        acc = None
        for name, path in self.files.items():
            t = self.p.track(name)
            y, _ = sf.read(str(path), dtype="float32")
            g = t.volume * (-1 if t.polarity else 1)
            par = t.parent
            while par is not None:
                g *= par.volume
                par = par.parent
            pan = max(-1.0, min(1.0, t.pan))
            l, r = math.cos((pan + 1) * math.pi / 4) * math.sqrt(2), math.sin((pan + 1) * math.pi / 4) * math.sqrt(2)
            if acc is None or len(acc) < len(y):
                acc = np.pad(acc, ((0, len(y) - len(acc)), (0, 0))) if acc is not None else np.zeros((len(y), 2), np.float32)
            acc[: len(y), 0] += y * g * l
            acc[: len(y), 1] += y * g * r
        peak = float(np.abs(acc).max()) if acc is not None else 0
        if peak > 0.98:                       # a rough mix for analysis only: keep it from clipping
            acc *= 0.98 / peak
        self._put(out, acc)
        return out


# ---------------------------------------------------------------- roles
def roles(p, R):
    """{track: role} from names first, then sound (engineer.roles), one vocal picked as the lead."""
    from hypnomix.core import dsp
    from hypnomix.engineer import roles as RO
    out, guessed = {}, []
    for name, path in R.files.items():
        r = RO.by_name(name)
        if r is None:
            y, _ = dsp.load(path, 22050)
            r = RO.by_sound(y, 22050)
            if r == "lead_vocal":
                guessed.append(name)
        out[name] = r
    if not any(r == "lead_vocal" and n not in guessed for n, r in out.items()) and len(guessed) > 1:
        keep = RO.pick_lead([(n, dsp.load(R.files[n], 22050)[0]) for n in guessed], 22050)
        for n in guessed:
            if n != keep:
                out[n] = "backing_vocal"
    return out


# ---------------------------------------------------------------- names and order (Live's `name` and `order`, fed from the model)
def name_rows(p, R):
    """Per-track guesses in `hypnomix name`'s format (rows by track index), from the project and its renders."""
    from hypnomix.session import names as NM
    rows, parent = {}, {}
    for t in p.tracks:
        tid = str(t.index)
        parent[tid] = str(t.parent.index) if t.parent is not None else None
        kind = "Group" if t.kind == "folder" else ("Midi" if t.kind == "midi" else "Audio")
        files = [Path(c.path).name for c in t.clips if c.path][:20]
        devs = [d.name for d in t.devices if d.on]
        rec = {"old": t.name, "kind": kind, "group": t.parent.name if t.parent is not None else None, "on": t.on,
               "sources": sorted({str(c.path) for c in t.clips if c.path})}
        rec["text_clue"] = NM.text_clue(t.name if not NM.DEFAULT_NAME.match(t.name) else "", " ".join(devs),
                                        " ".join(files), " ".join(c.name for c in t.clips[:20]))
        if kind == "Audio" and t.name in R.files:
            y, sr = sf.read(str(R.files[t.name]), dtype="float32")
            F = NM.audio_features(y, sr)
            rec["features"] = F
            lab, conf, why = NM.classify_audio(F)
        elif kind == "Audio":
            lab, conf, why = "Instrument", 0.0, "nothing heard (muted, or no audio items)"
        elif kind == "Midi":
            dl = " ".join(devs).lower()
            if "drum" in dl or "kit" in dl or "rs5k" in dl or "samplomatic" in dl:
                lab, conf, why = "Drums", 0.7, "drum sampler"
            elif devs:
                lab, conf, why = "Synth", 0.45, "instrument plug-in"
            else:
                lab, conf, why = "Instrument", 0.2, "no clues"
        else:
            lab, conf, why = None, 0, "folder"
        if rec["text_clue"] and lab != "Vocal" and rec["text_clue"] not in ("Synth",):
            if conf < 0.75 or rec["text_clue"] in ("Lead Vocal", "Harmony", "Kick", "Snare", "Hats", "Guitar", "Bass", "Strings"):
                lab, conf, why = rec["text_clue"], max(conf, 0.7), f"text clue ({why})"
        rec.update(label=lab, confidence=round(conf, 2), reason=why)
        rows[tid] = rec
    NM.propose(rows, parent)
    return rows, parent


def stack_moves(p, orow, min_overlap=0.3):
    """Vocal stacks in a REAPER project: where two or more vocal parts of one folder sing at once, the lowest part at
    that moment belongs on the stack's lowest track, the next on the next one up (Live's `order`, on the model).
    An item moves only when that is safe; otherwise it is listed with the reason:
      - a track uses fixed or free item lanes (moving an item off its lanes would scramble the comp)
      - a track's own automation runs over the item (it would play under the other track's rides)
      - the target track would hold two items at once after all the moves
    A moved item takes its takes and take envelopes with it, and its volume is changed by the difference between
    the two faders, so it plays at the same level in the mix."""
    from hypnomix.core import pitch
    from hypnomix.project.rpp_edit import locator
    from hypnomix.session.order import assign_stack
    byidx = {t.index: t for t in p.tracks}
    stacks = {}
    for r in orow:
        t = byidx[int(r["id"])]
        if r["kind"] == "Audio" and r["cat"] == 3 and t.on:
            stacks.setdefault(r["parent"], []).append(t)
    out = []
    for gid, members in stacks.items():
        if len(members) < 2:
            continue
        clips = []
        for t in members:
            for k, c in enumerate(t.clips):
                if c.muted or c.kind != "audio" or c.path is None or not Path(c.path).exists():
                    continue
                s0 = (c.take.section[0] if c.take.section else 0.0) + c.take.offset
                clips.append(dict(key=(t.index, k), track=t.index, start=c.start, end=c.end, c=c, t=t,
                                  s0=s0, s1=s0 + c.length * c.take.rate))
        if not clips:
            continue
        with ThreadPoolExecutor(6) as ex:
            hzs = list(ex.map(lambda d: pitch.median_between(str(d["c"].path), d["s0"], d["s1"], fmin=70, fmax=1000)
                              if d["s1"] > d["s0"] else None, clips))
        for d, hz in zip(clips, hzs):
            d["hz"] = hz
        tp = {}
        for t in members:
            hs = [d["hz"] for d in clips if d["track"] == t.index and d["hz"]]
            tp[t.index] = float(np.median(hs)) if hs else 0.0
        order_ = sorted(tp, key=lambda i: tp[i])
        want = assign_stack(clips, order_, min_overlap)

        def lanes(t):
            return t.native.get("FREEMODE", cast=int, default=0) != 0

        def automated(t, a0, a1):
            return any(a0 <= x <= a1 for pts in t.envelopes.values() for x, _ in pts if len(pts) > 1)
        cand, hand = [], []
        for d in clips:
            if d["key"] not in want:
                continue
            src, dst = d["t"], byidx[want[d["key"]]]
            why = None
            if lanes(src) or lanes(dst):
                why = f"'{src.name if lanes(src) else dst.name}' uses item lanes: moving the item would scramble the comp"
            elif automated(src, d["start"], d["end"]) or automated(dst, d["start"], d["end"]):
                why = "a track is automated there"
            gain = 20 * math.log10(src.volume / dst.volume) if src.volume > 0 and dst.volume > 0 else 0.0
            m = dict(item=locator(src, d["c"]), src=src.index, dst=dst.index, src_name=src.name, dst_name=dst.name,
                     start=d["start"] * p.tempo / 60, end=d["end"] * p.tempo / 60, hz=d["hz"], key=d["key"],
                     gain_db=round(gain, 3), clip=d["key"],
                     chains_differ=[x.name for x in src.devices if x.on] != [x.name for x in dst.devices if x.on])
            if why:
                m["why"] = why
                hand.append(m)
            else:
                cand.append(m)
        span = {d["key"]: (d["start"], d["end"]) for d in clips}
        while True:                                  # the FINAL layout must have no overlaps on any track
            where = {d["key"]: d["track"] for d in clips}
            for m in cand:
                where[m["key"]] = m["dst"]
            bad = next((m for m in cand if any(k != m["key"] and where[k] == m["dst"] and
                                                min(span[m["key"]][1], span[k][1]) - max(span[m["key"]][0], span[k][0]) > 1e-6
                                                for k in where)), None)
            if bad is None:
                break
            cand.remove(bad)
            bad["why"] = f"'{bad['dst_name']}' would have two items at once there"
            hand.append(bad)
        if cand or hand:
            out.append(dict(group=gid, tracks=[byidx[i].name for i in order_], moves=cand, hand=hand))
    return out


def g_names(p, R, od, a):
    """Default-named tracks ("Track 3", "Audio 2") named by how they sound, and the tracks put in working order
    (drums, bass, keys/guitar/synth, vocals, other melodic; low to high), as for a Live set."""
    from hypnomix.session import order as OR
    from hypnomix.workflow import prefs as P
    rows, parent = name_rows(p, R)
    nd = od / "raw" / "names"
    nd.mkdir(parents=True, exist_ok=True)
    AT.write_text(nd / "names.json", json.dumps({"set": str(p.path), "tracks": list(rows.values())}, indent=1,
                                                default=float), backup=False)
    out, n = [], 0
    for tid, r in rows.items():
        if r.get("new") in (None, r["old"]):
            continue
        n += 1
        sure = float(r.get("confidence") or 0) >= 0.5
        f = _f("name", n, tool="name", kind="track-name" if sure else "track-name-question", track=r["old"],
               old=r["old"], new=r["new"],
               problem=(f"default name '{r['old']}'; it sounds like {r['new']!r} ({r.get('reason')})" if sure else
                        f"default name '{r['old']}', and what it is isn't clear from its sound ({r.get('reason')}; "
                        f"best guess {r['new']!r})"),
               fix=(f"rename it {r['new']!r}" if sure else
                    f"ask what it is, then record the name: `fix DIR --decide name-{n}=approve --note \"<name>\"`"))
        out.append(_edit(p, f, op="rename", index=int(tid)))
    notes = [f"names: {n} default-named track(s) to name" if n else "names: every track already has a name"]
    if str(P.get(P.load(), "cleanup.order", "on")).lower() in ("off", "no", "false", "0"):
        notes.append("order: skipped (your preference cleanup.order=off)")
        return out, notes
    orow = []
    for t in p.tracks:
        r = rows[str(t.index)]
        lab = r.get("final") or r.get("label")
        orow.append(dict(id=str(t.index), name=t.name, kind=r["kind"], parent=parent[str(t.index)],
                         label=lab, cat=OR.category(lab, float(r.get("confidence") or 0)), pitch=OR.pitch_key(r)))
    new_ids = OR.propose_order(orow)
    stacks = stack_moves(p, orow) if p.daw == "reaper" else []
    for f in OR.findings(orow, new_ids, stacks):
        if f["kind"] == "vocal-stack":
            st = next(x for x in stacks if ", ".join(x["tracks"]) == f["track"])
            f["fix"] = (f["fix"].replace("level kept the same with clip gain", "level kept the same with item volume")
                        .replace("By hand in Live", "By hand in REAPER").replace("clip(s)", "item(s)"))
            f["problem"] = f["problem"].replace("clip", "item")
            if st["moves"]:
                out.append(_edit(p, f, op="stack", moves=[{k: m[k] for k in ("item", "src", "dst", "gain_db")}
                                                           for m in st["moves"]]))
            else:
                out.append(f)
            continue
        f["fix"] = f["fix"].replace("sound, routing and sends unchanged", "sound, folders, routing and sends unchanged")
        out.append(_edit(p, f, op="order", order=[int(i) for i in f["track_order"]]))
    notes.append("order: track order and vocal stacks are ON by default (skip the order items to keep yours, or "
                 "`hypnomix prefs set cleanup.order=off`)")
    return out, notes


# ---------------------------------------------------------------- groups
def g_files(p, R, od, a):
    out = []
    for n, (t, c, path) in enumerate(p.missing(), 1):
        out.append(_f("files", n, tool="files", kind="missing-audio", severity="high", track=t.name,
                      where=_where(p, c.start), problem=f"{W['item']} '{c.name}' plays {path}, which is not there",
                      fix="find the file and re-link it before anything else"))
    heard = len(out)
    takes = p.missing_takes() if hasattr(p, "missing_takes") else []
    for n, (t, lane, c, path) in enumerate(takes, heard + 1):
        num = f"take {lane.number}" if getattr(lane, "number", 0) else f"the take lane '{lane.name}'"
        out.append(_f("files", n, tool="files", kind="missing-take-audio", severity="medium", track=t.name,
                      where=_where(p, c.start),
                      problem=f"{num} of {t.name} uses {path}, which is not there; the comp does not play it, but you "
                              "cannot comp from it",
                      fix="find the file and re-link it before you comp from that take"))
    n_lane = sum(len(lane.clips) for t in p.tracks for lane in t.take_lanes)
    notes = [f"files: {sum(len(t.clips) for t in p.tracks) + n_lane} items checked"
             + (f" ({n_lane} on take lanes)" if n_lane else "") + f", {heard} missing"
             + (f", {len(takes)} more file{'s' if len(takes) != 1 else ''} only takes use" if takes else "")]
    if out:
        notes.append(f"files: to re-link, {W['relink']}")
    return out, notes


FADE_S = 0.005          # a click fix: 5 ms fade
AMOUNT = 0.5            # how much of a jump / spike a fix takes away (Live `smooth` --amount)
EASE_S = 0.3            # a cut's ease back to normal (Live `smooth` --ease-ms)
SPIKE_DB = 12.0         # a burst this far over its surroundings is a spike (Live `smooth` --spike-db)


def _edit(p, finding, **edit):
    """Attach the exact project edit to a finding. Only REAPER projects are written for now; elsewhere the
    finding stays manual (what to do by hand). A HypnoMix Studio session is written for item fades, cuts and spikes."""
    if p.daw == "reaper" or (p.daw == "ardour" and edit.get("op") in ("fade", "cut", "dip")):
        finding.update(applies="set", edit=edit)
    return finding


def spikes(levels_db, block_s=0.01, spike_db=SPIKE_DB):
    """Short bursts far over the surrounding level, from a 10 ms level curve (Live `smooth.find_spikes`, ported to
    any audio). [(block of the peak, first block, last block, size dB, onset?)]. A burst that opens a sung phrase
    (quiet just before, singing right after) is a consonant, not a problem: onset=True."""
    from hypnomix.session.smooth import SOUNDING_DB
    L = np.convolve(levels_db, np.ones(5) / 5, mode="same")
    k = int(1.5 / block_s)
    Lq = np.where(L > SOUNDING_DB, L, np.nan)
    pad = np.pad(Lq, k, constant_values=np.nan)
    win = np.lib.stride_tricks.sliding_window_view(pad, 2 * k + 1)[:, ::5]
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        M = np.nanmedian(win, axis=1)
    dev = L - M
    hot = (dev >= spike_db) & (M > SOUNDING_DB)
    out, i, n = [], 0, len(hot)
    while i < n:
        if not hot[i]:
            i += 1
            continue
        j = i
        while j < n and hot[j]:
            j += 1
        if (j - i) * block_s <= 0.4:
            pk = i + int(np.argmax(dev[i:j]))
            pre, post = L[max(0, i - 15):max(0, i - 3)], L[j:j + 30]
            onset = (len(pre) == 0 or float(np.median(pre)) < max(SOUNDING_DB, M[pk] - 15)) and \
                len(post) >= 10 and float(np.median(post)) >= M[pk] - 12
            out.append((pk, max(0, i - 2), min(n, j + 2), float(dev[pk]), bool(onset)))
        i = j
    return out


def g_clips(p, R, od, a, vocals=()):
    if p.daw == "ardour":
        from hypnomix.project.ardour_edit import locator
    else:
        from hypnomix.project.rpp_edit import locator
    from hypnomix.session.smooth import HIT_DB, PLOSIVE_HZ, PLOSIVE_MAX_DIP, PLOSIVE_SHARE, SPIKES_PER_MIN
    out, n, notes, regular, onsets = [], 0, [], [], 0
    short_fade = 0.002        # shorter than this counts as no fade; HypnoMix Studio's own default fade (64 samples) is enough of one
    if p.daw == "ardour":
        short_fade = min(short_fade, 64.0 / (p.sample_rate or 44100) - 1e-9)
    for t in p.audio_tracks():
        clips = sorted((c for c in t.clips if not c.muted and c.kind == "audio"), key=lambda c: c.start)
        for c in clips:
            if c.fade_in >= short_fade and c.fade_out >= short_fade:
                continue
            seg = render_clip(replace(c, fade_in=0.0, fade_out=0.0), SR, [], t.name)
            if seg is None or not len(seg):
                continue
            for edge, short, lvl, at in (("start", c.fade_in < short_fade, abs(seg[0]), c.start),
                                         ("end", c.fade_out < short_fade, abs(seg[-1]), c.end)):
                if short and lvl > 0.01:
                    n += 1
                    which = "in" if edge == "start" else "out"
                    out.append(_edit(p, _f("clips", n, tool="clips", kind="click",
                                           severity="medium" if lvl > 0.05 else "low", track=t.name, where=_where(p, at),
                                           problem=f"{W['item']} '{c.name}' {edge}s on a loud sample "
                                                   f"({20 * math.log10(lvl):.0f} dBFS) with no fade: an audible tick",
                                           fix=f"a {FADE_S * 1000:.0f} ms fade {which} on the {W['item']}"),
                                     op="fade", which=which, seconds=FADE_S, item=locator(t, c)))
        if t.name not in R.files:
            continue
        y, _ = sf.read(str(R.files[t.name]), dtype="float32")
        rms = lambda a0, a1: 10 * math.log10(float(np.mean(y[max(0, int(a0 * SR)):max(1, int(a1 * SR))] ** 2)) + 1e-12)
        for c0, c1 in zip(clips, clips[1:]):
            gap = c1.start - c0.end
            if not -0.25 <= gap <= 0.02:       # touching or crossfaded: a comp edit
                continue
            b, f = rms(c1.start - 0.3, c1.start - 0.03), rms(c1.start + 0.03, c1.start + 0.3)
            if b < -50 or f < -50 or abs(f - b) < 4:
                continue
            n += 1
            out.append(_edit(p, _f("clips", n, tool="clips", kind="cut", severity="medium" if abs(f - b) >= 8 else "low",
                                   track=t.name, where=_where(p, c1.start),
                                   problem=f"level jumps {f - b:+.1f} dB where '{c0.name}' meets '{c1.name}' (a comp "
                                           "cut recorded at a different level)",
                                   fix=f"listen first; if it is not the performance: short fades either side and a "
                                       f"volume ease that takes {AMOUNT:.0%} of the jump away over "
                                       f"{EASE_S * 1000:.0f} ms (note `method=item` sets the {W['item']} volume "
                                       f"{-(f - b) * AMOUNT:+.1f} dB instead; `amount=0.3` for less)"),
                             op="cut", t=c1.start, size=f - b, item=locator(t, c1), prev=locator(t, c0),
                             fade=FADE_S, amount=AMOUNT, ease=EASE_S))
        # spikes: 10 ms levels of the track as heard (clip gains and fades), inside its items only
        blk = int(0.01 * SR)
        nb = len(y) // blk
        lv = 10 * np.log10((y[: nb * blk].astype(np.float64) ** 2).reshape(nb, blk).mean(axis=1) + 1e-12)
        inside = np.zeros(nb, bool)
        for c in clips:
            inside[int(c.start / 0.01):int(c.end / 0.01) + 1] = True
        lv = np.where(inside, lv, -120.0)
        found = spikes(lv, 0.01, HIT_DB)
        minutes = sum(c.length for c in clips) / 60
        hits = sum(1 for x in found if not x[4])           # phrase-opening consonants are singing, not a beat
        if hits >= 4 and minutes > 0 and hits / minutes > SPIKES_PER_MIN:      # 4+: one burst is no beat
            regular.append(t.name)          # regular hits: the instrument (drums, plucks), not a problem
            continue
        for pk, b0, b1, size, onset in found:
            if size < SPIKE_DB:
                continue
            if onset:
                onsets += 1
                continue
            seg = y[b0 * blk:b1 * blk].astype(np.float64)
            spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2 if len(seg) >= 64 else np.zeros(1)
            fr = np.fft.rfftfreq(len(seg), 1 / SR) if len(seg) >= 64 else np.zeros(1)
            plosive = spec.sum() > 0 and spec[fr < PLOSIVE_HZ].sum() / spec.sum() >= PLOSIVE_SHARE
            d = min(size * AMOUNT, PLOSIVE_MAX_DIP) if plosive else size * AMOUNT
            n += 1
            out.append(_edit(p, _f("clips", n, tool="clips", kind="spike", severity="medium" if size >= 18 else "low",
                                   track=t.name, where=_where(p, pk * 0.01),
                                   problem=f"a short burst {size:.0f} dB over its surroundings"
                                           + (" (mostly low end: a plosive)" if plosive else " (a pop, bump or one "
                                              "shouted word)"),
                                   fix=f"a quick {d:.1f} dB dip in the track volume over the burst (skip it if it is "
                                       "the performance)"),
                             op="dip", t0=b0 * 0.01, t1=b1 * 0.01, db=round(d, 2), ramp=0.02))
    notes.append(f"clips: {W['item']} edges, cuts and spikes checked on {len(p.audio_tracks())} tracks")
    if regular:
        notes.append("spikes not checked on tracks with regular hits (drums): " + ", ".join(regular))
    if onsets:
        notes.append(f"clips: {onsets} loud consonant(s) opening a phrase left alone (part of the singing)")
    # item edges and fades that cut into a word, on the vocal tracks (Live's `edges`, on the model)
    comped = [t for t in p.audio_tracks(include_off=True) if t.comped]
    if comped:
        notes.append("clips: comped from takes: " + ", ".join(f"{t.name} ({len(t.take_lanes)} take{'s' if len(t.take_lanes) != 1 else ''})"
                                                         for t in comped)
                     + "; the checks and fixes work on the comp's own clips (each still plays its take's file, so the "
                       "edges check opens it past the edge), the takes are never changed")
    if vocals:
        from hypnomix.workflow import edges_project as EP
        try:
            found, where = EP.scan(p, set(vocals))
            ef = EP.findings(p, found, where, W)
            for k, f in enumerate(ef, 1):
                f["id"] = f"edges-{k}"
            out += ef
            rec = sum(1 for f in ef if f.get("recommended"))
            notes.append(f"edges: {len(ef)} item(s) on vocal item edges, {rec} clear-cut fix(es) recommended; "
                         "cuts are listen-only")
        except Exception:
            notes.append(SC.check_failed(od, "edges", traceback.format_exc(), "so item edges that cut into a word "
                                         "were not checked", "edges-error.txt"))
    else:
        notes.append("edges: no vocal tracks found, so no word edges checked")
    if p.daw == "reaper":
        notes.append("clips: approved fixes are written into a NEW .rpp by `hypnomix fix` (the original is never touched)")
    elif p.daw == "ardour":
        notes.append("clips: approved fades, cuts and spikes are written into a NEW .ardour snapshot beside the "
                     "original by `hypnomix fix` (written and re-read by HypnoMix; not yet opened in HypnoMix Studio)")
    return out, notes


def g_timing(p, R, od, a, role):
    """Instrument hits out of time with the band (Live's `timing`, on the model); fixes are stretch markers."""
    from hypnomix.workflow import timing_project as TP
    tracks = getattr(a, "timing_track", None) or [t for t, r in role.items() if r not in ("lead_vocal", "backing_vocal", "fx")]
    if not tracks:
        return [], ["timing: no instrument tracks found (name them, or pass --timing-track)"]
    melodic = [t for t in tracks if role.get(t) in TP.MELODIC_ROLES]
    bass = [t for t in tracks if role.get(t) == "bass"]
    drums = [t for t in tracks if role.get(t) in TP.DRUM_ROLES]
    tr, issues, notes_ = TP.analyse(p, tracks, False, melodic, bass, drums)
    fs = TP.findings(p, tr, issues, notes_)
    if SC.pref_wants("timing") == "off":              # "off = never propose": nothing is proposed, and the person is told why
        n_t = sum(1 for f in fs if f.get("tool") == "timing")
        return [f for f in fs if f.get("tool") != "timing"], [
            f"timing proposals are off in your preferences (taste.timing; {n_t} hit(s) measured off the band's feel); "
            "turn them back on with `hypnomix prefs set taste.timing=loose`"]
    for f in fs:                                       # the re-check after a fix judges with the same roles
        if f.get("edit"):
            f["edit"]["roles"] = dict(tracks=tracks, melodic=melodic, bass=bass, drums=drums)
    if p.daw != "reaper":
        for f in fs:
            f.pop("edit", None)
            if f["applies"] == "set":
                f["applies"] = "manual"
    notes = [f"timing: song looseness {notes_['looseness'] * 1000:.0f} ms across {len(tr)} instrument tracks "
             "(the band's natural feel; only outliers are listed)"]
    if bass or drums:
        notes.append(f"timing: low end first: bass ({', '.join(bass) or 'none found'}) against the drums "
                     f"({', '.join(drums) or 'none found'})")
    if melodic:
        notes.append(f"timing: melodic parts ({', '.join(melodic)}) only get optional, partial nudges")
    if p.daw == "reaper":
        notes.append("timing: approved nudges are written as stretch markers on the items (drag or delete them in REAPER)")
    if notes_.get("skipped_missing"):
        n_ = notes_["skipped_missing"]
        notes.append(f"timing: {n_} item{'s' if n_ != 1 else ''} skipped because the audio file is missing "
                     "(the files group lists them); the other items were checked")
    return fs, notes


def g_vocals(p, R, od, a, role):
    vox = a.vocal_track or [t for t, r in role.items() if r in ("lead_vocal", "backing_vocal")]
    files = {t: R.files[t] for t in vox if t in R.files}
    if not files:
        return [], ["vocals: no vocal tracks found (name them 'Lead Vocal', 'Harmony'..., or pass --vocal-track)"]
    lead = a.lead_track or next((t for t in files if role.get(t) == "lead_vocal"), None)
    ref = a.ref or (str(R.mix()) if R.mix() else None)
    findings, notes = [], []
    if not a.ref and ref:
        notes.append("vocals: key and tuning measured from a rough mix of the project's renders (no FX); "
                     "give --ref MIX.wav for a reliable grid")
    kf = None
    if not a.key and ref:
        j = od / "raw" / "key.json"
        j.unlink(missing_ok=True)              # a failed check must not be read from an earlier scan's file
        code, out = SC.hx("key", "--audio", ref, "--sections", "--bpm", p.tempo, "--json", j)
        SC.save(od / "raw" / "key.txt", SC.strip_warnings(out))
        if not j.exists():
            notes.append(SC.check_failed(od, "key map", out, "so vocal tuning uses one key for the whole song",
                                         "key-error.txt"))
        else:
            kf = j
            d = json.loads(j.read_text(encoding="utf-8"))
            notes.append(f"key map: {d['key']} ({'sure' if d.get('sure') else 'UNSURE'}), "
                         f"{len(d.get('sections', []))} sections")
            for n, q in enumerate(d.get("questions", []), 1):
                findings.append(_f("key", n, tool="key", kind="key-question", severity="medium", track="(whole song)",
                                   where="bars " + ", ".join(q["bars"]), applies="answer", notes=q["notes"],
                                   bars=q["bars"], problem=f"two scales fit these bars; they differ only in "
                                   f"{q['notes'][0]} vs {q['notes'][1]}", fix=f"ask: {q['question']}"))

    def one(item):
        t, path = item
        j = od / "raw" / f"tune-{path.stem}.json"
        j.unlink(missing_ok=True)
        args = ["tune", path, "--report-only", "--json", j]
        if ref:
            args += ["--ref", ref]
        if a.key:
            args += ["--key", a.key]
        elif kf:
            args += ["--scales", kf]
        if lead and t != lead and lead in files:
            args += ["--guide", files[lead]]
        if a.backing:
            args += ["--chords", a.backing]
        code, out = SC.hx(*args)
        SC.save(od / "raw" / f"tune-{path.stem}.txt", SC.strip_warnings(out))
        return t, j, out

    tuning_off, off_notes = SC.pref_wants("tune") == "off", 0
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for t, j, out in ex.map(one, files.items()):
            if not j.exists():
                notes.append(SC.check_failed(od, f"tuning check on {t}", out, "so that vocal has no pitch findings",
                                             f"tune-{files[t].stem}-error.txt"))
                continue
            d = json.loads(j.read_text(encoding="utf-8"))
            for f in d["findings"]:
                f.update(track=t, key=d["key"], tuning_cents=d["tuning_cents"], flagged_notes=d["flagged"],
                         asked_notes=d.get("asked", []))
                if tuning_off:                       # "off = never propose": counted, not listed
                    off_notes += len(d["flagged"])
                    continue
                findings.append(f)
    if tuning_off:
        notes.append(f"tuning proposals are off in your preferences (taste.tuning; {off_notes} note(s) measured off "
                     "pitch); turn them back on with `hypnomix prefs set taste.tuning=natural`")
    if lead in files and len(files) > 1:
        try:
            d_f, d_n = SC.doubles(files, lead)
            for f in d_f:
                f["fix"] = f["fix"].replace("comp clips in Live", f"{W['item']}s in {W['daw']}")
            findings += d_f
            notes += d_n
        except Exception as e:
            notes.append(f"doubles: failed ({SC.plain_reason(str(e) or e.__class__.__name__)}), so doubles and "
                         "harmonies were not compared with the lead in time")
        try:
            hq = SC.harmony_question(files, lead)
            for f in hq:
                f["faders"] = {t: round(p.track(t).volume_db, 2) for t in files if p.track(t).volume > 0}
            findings += hq
        except Exception as e:
            notes.append(f"harmony balance check: failed ({SC.plain_reason(str(e) or e.__class__.__name__)}), so no "
                         "harmony balance question is asked")
    if len(files) > 1:     # vocal level line to line, and upper parts under the melody (as for a Live set)
        j = od / "raw" / "vocallevel.json"
        j.unlink(missing_ok=True)              # a failed check must not be read from an earlier scan's file
        args = ["vocallevel", p.path, "--renders", R.dir, "--json", j, "--tracks", *files.keys()]
        if lead in files:
            args += ["--melody", lead]
        code, out = SC.hx(*args)
        SC.save(od / "raw" / "vocallevel.txt", SC.strip_warnings(out))
        if j.exists():
            vf = json.loads(j.read_text(encoding="utf-8", errors="replace"))["findings"]
            for f in vf:                       # `fix` does not write these: vocallevel --apply does (REAPER)
                f["applies"] = "manual"
                if p.daw == "reaper" and f.get("change_db"):
                    f["fix"] += f" (`hypnomix vocallevel` with --apply NEW.rpp writes every such move at once)"
            findings += vf
            notes.append("vocal levels: measured from renders x faders x volume envelopes (FX not modelled)"
                         + (f"; write the fixes with `hypnomix vocallevel \"{Path(p.path).name}\" --apply NEW.rpp`"
                            if p.daw == "reaper" else "")
                         + "; before the final render re-run `hypnomix vocallevel` with --heard DIR on solo renders")
        else:
            notes.append(SC.check_failed(od, "vocal levels", out, "so the vocal level line to line was not checked",
                                         "vocallevel-error.txt"))
    notes.append(f"vocals: {len(files)} vocal track(s); lead '{lead}'"
                 + ("" if a.lead_track else " (by name or sound; --lead-track to change)"))
    return findings, notes


def g_effects(p, R, od, a):
    out, n = [], 0
    for t in p.tracks:
        if not t.devices:
            continue
        chain_off = p.daw == "reaper" and all(not d.on for d in t.devices) and t.native is not None and \
            t.native.get("FX", cast=int, default=1) == 0
        if chain_off:
            n += 1
            out.append(_f("fx", n, tool="effects", kind="chain-off", severity="info", applies="info", track=t.name,
                          problem=f"the whole FX chain is switched off ({len(t.devices)} plug-ins)",
                          fix="on purpose? Nothing to do. Otherwise switch the chain on (the FX button)"))
            continue
        for d in t.devices:
            if not d.on:
                n += 1
                out.append(_f("fx", n, tool="effects", kind="bypassed", severity="info", applies="info", track=t.name,
                              device=d.name, problem=f"{d.name} is bypassed or offline", fix="remove it if it is not needed: "
                              "a bypassed plug-in still loads with the project"))
        lim = [d.name for d in t.devices if d.on and any(w in d.name.lower() for w in LIMITER_WORDS)]
        if len(lim) > 1:
            n += 1
            out.append(_f("fx", n, tool="effects", kind="stacked-limiters", severity="medium", track=t.name,
                          problem=f"{len(lim)} limiters in a row ({', '.join(lim)}): each one flattens what the "
                                  "last left, and the second rarely adds anything but distortion",
                          fix="keep one limiter at the end of the chain; set its ceiling there"))
    notes = [f"effects: {sum(len(t.devices) for t in p.tracks)} plug-ins on {sum(1 for t in p.tracks if t.devices)} tracks"]
    # sidechain compression (ReaComp listening to a send): Live's `sidechain` simulation on the model
    try:
        from hypnomix.workflow import sidechain_project as SCP
        res = SCP.analyse(p)
        out += SCP.findings(p, res, W)
        if res and p.daw == "ardour":
            notes.append(f"sidechain: {len(res)} sidechained ACE Compressor(s) measured hit by hit; the suggested "
                         "settings are listed to set in the device (other compressors: not checked)")
        elif res:
            notes.append(f"sidechain: {len(res)} sidechained ReaComp(s) measured hit by hit; suggestions are written "
                         "into the ReaComp by `fix` (other compressors: only listed)")
    except Exception:
        notes.append(SC.check_failed(od, "sidechain", traceback.format_exc(), "so compressors listening to a send "
                                     "were not checked", "sidechain-error.txt"))
    return out, notes


def g_recordings(p, R, od, a):
    files = sorted({c.path for t in p.audio_tracks() for c in t.clips
                    if c.kind == "audio" and c.path is not None and Path(c.path).exists()})
    findings, facts, n = [], {}, 0

    def one(path):
        try:
            return path, SC.check_recording(Path(path))
        except Exception as e:
            return path, ([("unreadable", "high", f"could not be read ({e})", "re-export it as WAV", None)], {})

    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for path, (rows, fact) in ex.map(one, files):
            facts[Path(path).name] = fact
            for kind, sev, problem, fix, run in rows:
                n += 1
                f = _f("rec", n, tool=(run[0] if run else "recording"), kind=kind, severity=sev,
                       track=Path(path).name, problem=problem, fix=fix, applies="audio" if run else "manual")
                if run:
                    f["run"] = [str(x) for x in run]
                findings.append(f)
    if files:
        code, out = SC.hx("clicks", *files)
        SC.save(od / "raw" / "clicks.txt", SC.strip_warnings(out))
    SC.save(od / "raw" / "recordings.json", json.dumps(facts, indent=1))
    return findings, [f"recordings: {len(files)} source files the project plays were measured (whole files, "
                      "including parts outside the items)"]


def g_noise(p, R, od, a):
    out, n = [], 0
    for t in p.audio_tracks():
        for c in t.clips:
            g = abs(c.level)
            if c.muted or c.kind != "audio" or g < 10 ** (6 / 20) or c.path is None or not Path(c.path).exists():
                continue
            from hypnomix.core import dsp
            y, sr = dsp.load(c.path)
            floor = dsp.noise_floor_db(y, sr) + 20 * math.log10(g)
            if floor < -60:
                continue
            n += 1
            out.append(_f("noise", n, tool="noise", kind="boosted-noise", severity="medium" if floor > -50 else "low",
                          track=t.name, where=_where(p, c.start),
                          problem=f"{W['item']} '{c.name}' is turned up {20 * math.log10(g):+.1f} dB, which lifts its noise "
                                  f"floor to about {floor:.0f} dBFS in the mix",
                          fix="de-hiss the source first (`hypnomix dehiss FILE OUT.wav`, a new file), or record the "
                              "part hotter next time"))
    return out, []


def g_intent(p, R, od, a):
    out, n = [], 0

    def add(track, problem, where="", what=""):
        """`what` names the thing (part of the finding's identity, so a re-scan keeps each decision on ITS finding)."""
        nonlocal n
        n += 1
        out.append(_f("intent", n, tool="intent", kind="deliberate?", severity="info", track=track, where=where,
                      device=what, problem=problem, applies="info",
                      fix="If this is on purpose, nothing to do: tools will not change it. To have it shown on every "
                          "review: hypnomix prefs set protect.notes=\"...\""))
    for t in p.tracks:
        for lab, pts in t.envelopes.items():
            vals = [v for _, v in pts]
            if len(pts) < 2 or max(vals) - min(vals) < 1e-6:
                continue
            if lab.startswith("Volume"):
                d = lambda v: f"{20 * math.log10(v):+.1f} dB" if v > 0 else "silence"
                rng = f"{d(min(vals))} to {d(max(vals))}"
            else:
                rng = f"{min(vals):.3g} to {max(vals):.3g}"
            add(t.name, f"{lab} is automated from bar {int(p.bar(pts[0][0]))} to {int(p.bar(pts[-1][0]))} "
                        f"({len(pts)} points, {rng})", _where(p, pts[0][0]), what=f"automation: {lab}")
        if t.muted and t.clips:
            add(t.name, "the track is muted but has items (it is not checked and not heard)", what="muted")
        if t.on and abs(t.pan) >= 0.9:
            add(t.name, f"panned hard {'right' if t.pan > 0 else 'left'}", what="hard pan")
        if t.on and t.polarity:
            add(t.name, "polarity (phase) is flipped on the track", what="track polarity")
        for c in t.clips:
            if c.muted or not t.on:
                continue
            if c.level < 0:
                add(t.name, f"{W['item']} '{c.name}' plays with its polarity flipped", _where(p, c.start), what="item polarity")
            elif c.level > 10 ** (9 / 20):
                add(t.name, f"{W['item']} '{c.name}' is turned up {20 * math.log10(c.level):+.1f} dB", _where(p, c.start),
                    what="item gain")
            if c.stretch_markers:
                add(t.name, f"{W['item']} '{c.name}' has {c.stretch_markers} stretch marker(s) (followed in the checks' renders)",
                    _where(p, c.start), what="stretch markers")
    return out, [f"intent: {n} thing(s) that look deliberate, listed as questions"]


def g_mix(p, R, od, a):
    return SC.g_mix(p.path, od, a, tempo=p.tempo)


def g_mpe(p, R, od, a):
    """MPE health checks on a HypnoMix Studio session's MIDI tracks (hypnomix.project.mpe): read only."""
    from hypnomix.project import mpe as MP
    return MP.checks(p, W)


def g_stems(p, R, od, a):
    if not a.deep:
        return [], ["stems: skipped (add --deep to check frequency fights and mic phase between tracks)"]
    from hypnomix.engineer import masking as M
    stems, sr = M.load_stems(R.dir, lazy=True)
    if len(stems) < 2:
        return [], ["stems: fewer than two heard audio tracks"]
    real = {t.safe_name: t.name for t in p.tracks} if p.daw == "reaper" else None   # only REAPER projects can be written
    f, notes = SC.stem_findings(stems, sr, writable=real)
    for x in f:
        if x.get("eq"):
            x["edit"] = dict(op="masking")
    notes.append("stems: tracks were rendered without their FX, so EQ already on a track is not counted")
    return f, notes


def g_devices(p, R, od, a, role):
    """ReaComp / ACE Compressor, ReaEQ / ACE EQ low cut, Hypnomix Saturator drive, ReaGate / ReaLimit listed:
    `devices_project.py` (Live's `devices` on the model)."""
    from hypnomix.workflow import devices_project as DP
    return DP.g_devices(p, R, od, a, role)


FADER_TOP_DB = 11.9      # REAPER's fader goes to +12 dB by default (a preference in REAPER)
FADER_LOW_DB = -40.0


def g_structure(p, R, od, a):
    """From the project file alone (Live's `structure`): the file reads back byte for byte, folders close, sends come
    from tracks that exist, faders are not at the top or nearly silent with items on the track."""
    out, n = [], 0

    def add(kind, sev, track, problem, fix, applies="manual"):
        nonlocal n
        n += 1
        out.append(_f("structure", n, tool="structure", kind=kind, severity=sev, track=track, problem=problem,
                      fix=fix, applies=applies))
    notes = []
    if p.daw == "reaper":
        from hypnomix.project import rpp
        try:
            same = rpp.dumps(rpp.load(p.path)).encode("utf-8", errors="surrogateescape") == Path(p.path).read_bytes()
        except Exception as e:
            same, why = False, SC.plain_reason(str(e) or e.__class__.__name__)
        else:
            why = "a load and save would change it"
        if not same:
            add("set-error", "high", "", f"the project's structure: it does not read back byte for byte ({why})",
                "do not apply fixes to this project; open it in REAPER, save it again, and re-scan")
        depth, ntr = 0, len(p.tracks)
        for t in p.tracks:
            bus = t.native.line("ISBUS") if t.native is not None else None
            tk = bus.tokens if bus is not None else []
            if len(tk) > 2 and tk[1] == "1":
                depth += 1
            elif len(tk) > 2:
                try:
                    k = max(0, -int(float(tk[2])))
                except ValueError:
                    k = 0
                if k > depth:
                    add("set-warning", "info", t.name, f"the project's structure: '{t.name}' closes {k} folder(s) "
                        f"but only {depth} is open", "", applies="info")
                depth = max(0, depth - k)
            for ln in (t.native.lines("AUXRECV") if t.native is not None else []):
                src = ln.tokens[1] if len(ln.tokens) > 1 else ""
                if not src.lstrip("-").isdigit() or not 0 <= int(src) < ntr or int(src) == t.index:
                    add("send-missing", "medium", t.name, f"a send into '{t.name}' comes from track {src}, which is "
                        + ("this track itself" if src.isdigit() and int(src) == t.index else "not in the project"),
                        "check the track's routing in REAPER (the routing button) and remove the stray send")
        if depth > 0:
            add("set-warning", "info", "", f"the project's structure: {depth} folder(s) never close (the last "
                "track is still inside a folder)", "", applies="info")
    else:
        notes.append("structure: HypnoMix Studio session: only the nearly-silent fader check (the file's own structure is checked "
                     "when `fix` writes a new snapshot)")
    for t in p.tracks:
        if not t.on:
            continue
        db = 20 * math.log10(t.volume) if t.volume > 0 else -150.0
        if p.daw == "reaper" and db >= FADER_TOP_DB:
            add("fader-max", "low", t.name, f"fader at {db:+.1f} dB, the top of its range: no room to turn it up, and "
                "the level going into the next stage is hot", "bring the fader (or the items) down and the folder or "
                "master up if needed; check by ear")
        elif db < FADER_LOW_DB and any(c.kind == "audio" and not c.muted for c in t.clips):
            add("fader-low", "info", t.name, f"fader at {db:.0f} dB with {W['item']}s on the track: barely heard", "",
                applies="info")
    notes.append(f"structure: {sum(1 for f in out if f['kind'] == 'set-error')} error(s), "
                 f"{sum(1 for f in out if f['kind'] != 'set-error')} other finding(s) in the project's structure; "
                 f"{sum(len(t.clips) for t in p.tracks)} {W['item']}s, {len(p.tracks)} tracks")
    return out, notes


# ---------------------------------------------------------------- run
STALE_ERRORS = {"clips": ("edges-error.txt",), "vocals": ("key-error.txt", "tune-*-error.txt", "vocallevel-error.txt"),
                "effects": ("sidechain-error.txt",)}


def run(a, path, od, groups):
    p = PJ.load(path)
    W.clear()
    W.update(WORDS.get(p.daw, WORDS["reaper"]))
    print(f"  {W['daw']} project: {len(p.tracks)} tracks, {p.tempo:g} BPM, {p.end():.0f} s")
    R = Renders(p, od)
    for old in ("renders-error.txt", "roles-error.txt"):
        (od / "raw" / old).unlink(missing_ok=True)
    early = []                                 # a step before the groups that failed: told once, in the first group's notes
    if {"names", "clips", "timing", "vocals", "devices", "stems"} & set(groups):
        try:
            R.build(a.jobs)
            print(f"  rendered {len(R.files)} tracks → {R.dir}")
        except Exception:
            early.append(SC.check_failed(od, "rendering the tracks", traceback.format_exc(), "so the checks that need "
                                         "the audio of the tracks have little or nothing to work on",
                                         "renders-error.txt"))
    role = {}
    if {"vocals", "clips", "timing", "devices"} & set(groups):
        try:
            role = roles(p, R)
        except Exception:
            early.append(SC.check_failed(od, "track roles", traceback.format_exc(), "so vocals and instruments were "
                                         "not told apart", "roles-error.txt"))
    vocal_names = [t for t, r in role.items() if r in ("lead_vocal", "backing_vocal")]
    fns = {"timing": lambda p, R, od, a: g_timing(p, R, od, a, role), "names": g_names, "files": g_files, "clips": lambda p, R, od, a: g_clips(p, R, od, a, vocal_names), "effects": g_effects,
           "devices": lambda p, R, od, a: g_devices(p, R, od, a, role), "structure": g_structure, "recordings": g_recordings, "noise": g_noise,
           "intent": g_intent, "mix": g_mix, "stems": g_stems, "mpe": g_mpe,
           "vocals": lambda p, R, od, a: g_vocals(p, R, od, a, role)}
    warn = list(getattr(p, "warnings", [])) + sorted(set(R.warn))

    def one(g):
        t0 = time.time()
        for pat in STALE_ERRORS.get(g, ()) + (f"{g}-error.txt",):   # an old traceback must not sit beside a clean result
            for old in (od / "raw").glob(pat):
                old.unlink(missing_ok=True)
        try:
            f, notes = fns[g](p, R, od, a)
        except Exception:                      # one failing check must not sink the scan
            f, notes = [], [SC.check_failed(od, g, traceback.format_exc(), "so this group has no findings, which does "
                                            "not mean it is clean", f"{g}-error.txt")]
        if g == groups[0]:
            notes = [f"project: {w}" for w in warn[:12]] + early + notes
        secs = time.time() - t0
        AT.write_text(od / f"{g}.json", json.dumps({"group": g, "set": str(p.path), "seconds": secs,
                                                    "findings": f, "notes": notes}, indent=1, default=str),
                      backup=False)
        print(f"  {g:<10} {len(f):4d} findings  ({secs:.0f} s)")

    with ThreadPoolExecutor(max_workers=max(1, min(a.jobs, len(groups)))) as ex:
        list(ex.map(one, groups))
