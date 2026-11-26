"""First-pass scan of a REAPER project (.rpp) or an Ardour session (.ardour): the same review list as a Live set,
from the shared project model.

    hypnomix scan SONG.rpp [--mix MIX.wav] [--ref MIX.wav] [--deep] [--only GROUP ...]
    hypnomix scan SONG.ardour (or the session folder) [same options]

The DAW can stay open (nothing is written next to the project; everything goes to the output folder). Every audio
track that is heard is rendered once from the project (item and take volume, fades, loops, sections, playrate; no
FX, no faders) into raw/renders/, and the groups work from those renders and the model:

  files       items whose audio file is missing
  clips       clicks at item edges with no fade; level jumps where one item meets the next (comps)
  vocals      pitch of every vocal track (tune --report-only), doubles vs the lead in time, harmony balance question
  effects     plug-ins switched off or offline, whole FX chains off, several limiters on one track
  recordings  every source file the project plays: clipping, levels, noise floor, DC, sibilance, breaths, clicks
  noise       items boosted a lot: the boost lifts the take's own noise floor
  intent      "is this deliberate?": automation, hard pans, muted tracks with items, big item gains, polarity flips,
              stretch markers
  mix         with --mix: loudness, true peak, release checks, translation, sections
  stems       with --deep: frequency fights and mic phase between tracks

Without --ref, the key and tuning are measured from a rough mix of the project's renders (faders and pans, no FX).
Findings that change the project are listed as *manual* (what to do in the DAW) until `hypnomix fix` can write
project files; findings that make new audio (tune, dehiss, deess) work the same as for a Live set.
"""
import json
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix import project as PJ
from hypnomix.project.model import render_clip
from hypnomix.workflow import scan as SC

# how each DAW names things, for the fix text
WORDS = {
    "reaper": dict(daw="REAPER", item="item", relink="REAPER offers to search for missing media when the project "
                   "opens, or re-link it in the item's properties (Choose new file)"),
    "ardour": dict(daw="Ardour", item="region", relink="Ardour asks for missing files when the session opens "
                   "(Session > Properties > Misc lists the search paths), or import it again"),
}
W = dict(WORDS["reaper"])

GROUPS = ["names", "files", "clips", "vocals", "effects", "recordings", "noise", "intent", "mix", "stems"]
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
class Renders:
    """Each heard audio track rendered once (float WAV), plus a rough stereo mix for key and tuning."""

    def __init__(self, p, od):
        self.p, self.dir = p, Path(od) / "raw" / "renders"
        self.files, self.warn = {}, []

    def build(self, jobs=4):
        self.dir.mkdir(parents=True, exist_ok=True)
        tracks = [t for t in self.p.audio_tracks() if any(c.kind == "audio" for c in t.clips)]
        L = self.p.end()

        def one(t):
            out = self.dir / f"{t.safe_name}.wav"
            if not out.exists():
                y = self.p.render(t, SR, L, self.warn)
                if not np.any(y):
                    return t, None
                sf.write(str(out), y.astype(np.float32), SR, subtype="FLOAT")
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
        sf.write(str(out), acc, SR, subtype="FLOAT")
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


def g_names(p, R, od, a):
    """Default-named tracks ("Track 3", "Audio 2") named by how they sound, and the tracks put in working order
    (drums, bass, keys/guitar/synth, vocals, other melodic; low to high), as for a Live set."""
    from hypnomix.session import order as OR
    from hypnomix.workflow import prefs as P
    rows, parent = name_rows(p, R)
    nd = od / "raw" / "names"
    nd.mkdir(parents=True, exist_ok=True)
    (nd / "names.json").write_text(json.dumps({"set": str(p.path), "tracks": list(rows.values())}, indent=1, default=float))
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
    for f in OR.findings(orow, new_ids, []):
        f["fix"] = f["fix"].replace("sound, routing and sends unchanged", "sound, folders, routing and sends unchanged")
        out.append(_edit(p, f, op="order", order=[int(i) for i in f["track_order"]]))
    notes.append("order: track order is ON by default (skip the order item to keep yours, or `hypnomix prefs set "
                 "cleanup.order=off`); vocal-stack clip moves are Live-only for now")
    return out, notes


# ---------------------------------------------------------------- groups
def g_files(p, R, od, a):
    out = []
    for n, (t, c, path) in enumerate(p.missing(), 1):
        out.append(_f("files", n, tool="files", kind="missing-audio", severity="high", track=t.name,
                      where=_where(p, c.start), problem=f"{W['item']} '{c.name}' plays {path}, which is not there",
                      fix="find the file before anything else: " + W["relink"]))
    return out, [f"files: {sum(len(t.clips) for t in p.tracks)} items checked, {len(out)} missing"]


FADE_S = 0.005          # a click fix: 5 ms fade
AMOUNT = 0.5            # how much of a jump / spike a fix takes away (Live `smooth` --amount)
EASE_S = 0.3            # a cut's ease back to normal (Live `smooth` --ease-ms)
SPIKE_DB = 12.0         # a burst this far over its surroundings is a spike (Live `smooth` --spike-db)


def _edit(p, finding, **edit):
    """Attach the exact project edit to a finding. Only REAPER projects are written for now; elsewhere the
    finding stays manual (what to do by hand)."""
    if p.daw == "reaper":
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
    from hypnomix.project.rpp_edit import locator
    from hypnomix.session.smooth import HIT_DB, PLOSIVE_HZ, PLOSIVE_MAX_DIP, PLOSIVE_SHARE, SPIKES_PER_MIN
    out, n, notes, regular, onsets = [], 0, [], [], 0
    for t in p.audio_tracks():
        clips = sorted((c for c in t.clips if not c.muted and c.kind == "audio"), key=lambda c: c.start)
        for c in clips:
            if c.fade_in >= 0.002 and c.fade_out >= 0.002:
                continue
            seg = render_clip(replace(c, fade_in=0.0, fade_out=0.0), SR, [], t.name)
            if seg is None or not len(seg):
                continue
            for edge, short, lvl, at in (("start", c.fade_in < 0.002, abs(seg[0]), c.start),
                                         ("end", c.fade_out < 0.002, abs(seg[-1]), c.end)):
                if short and lvl > 0.01:
                    n += 1
                    which = "in" if edge == "start" else "out"
                    out.append(_edit(p, _f("clips", n, tool="clips", kind="click",
                                           severity="medium" if lvl > 0.05 else "low", track=t.name, where=_where(p, at),
                                           problem=f"{W['item']} '{c.name}' {edge}s on a loud sample "
                                                   f"({20 * math.log10(lvl):.0f} dBFS) with no fade: an audible tick",
                                           fix=f"a {FADE_S * 1000:.0f} ms fade {which} on the {W['item']} "
                                               f"(in {W['daw']}, or approve it here)"),
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
                                   fix=f"listen first. If it is not the performance: short fades either side of the "
                                       f"cut and a volume ease that takes {AMOUNT:.0%} of the jump away and returns to "
                                       f"normal over {EASE_S * 1000:.0f} ms (note `method=item` to set the "
                                       f"{W['item']} volume {-(f - b) * AMOUNT:+.1f} dB instead; `amount=0.3` for "
                                       "less)"),
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
                                   fix=f"a quick {d:.1f} dB dip in the track volume over the burst, like riding it by "
                                       "hand (listen first: skip it if it is the performance)"),
                             op="dip", t0=b0 * 0.01, t1=b1 * 0.01, db=round(d, 2), ramp=0.02))
    notes.append(f"clips: {W['item']} edges, cuts and spikes checked on {len(p.audio_tracks())} tracks")
    if regular:
        notes.append("spikes not checked on tracks with regular hits (drums): " + ", ".join(regular))
    if onsets:
        notes.append(f"clips: {onsets} loud consonant(s) opening a phrase left alone (part of the singing)")
    # item edges and fades that cut into a word, on the vocal tracks (Live's `edges`, on the model)
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
        except Exception as e:
            notes.append(f"edges: failed ({type(e).__name__}: {e})")
    else:
        notes.append("edges: no vocal tracks found, so no word edges checked")
    if p.daw == "reaper":
        notes.append("clips: approved fixes are written into a NEW .rpp by `hypnomix fix` (the original is never touched)")
    return out, notes


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
        code, out = SC.hx("key", "--audio", ref, "--sections", "--bpm", p.tempo, "--json", j)
        SC.save(od / "raw" / "key.txt", SC.strip_warnings(out))
        if j.exists():
            kf = j
            d = json.loads(j.read_text())
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

    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for t, j, out in ex.map(one, files.items()):
            if not j.exists():
                notes.append(f"tune failed on {t}: {out[-200:]}")
                continue
            d = json.loads(j.read_text())
            for f in d["findings"]:
                f.update(track=t, key=d["key"], tuning_cents=d["tuning_cents"], flagged_notes=d["flagged"],
                         asked_notes=d.get("asked", []))
                findings.append(f)
    if lead in files and len(files) > 1:
        try:
            d_f, d_n = SC.doubles(files, lead)
            for f in d_f:
                f["fix"] = f["fix"].replace("comp clips in Live", f"{W['item']}s in {W['daw']}")
            findings += d_f
            notes += d_n
        except Exception as e:
            notes.append(f"doubles: failed ({e})")
        try:
            hq = SC.harmony_question(files, lead)
            for f in hq:
                f["faders"] = {t: round(p.track(t).volume_db, 2) for t in files if p.track(t).volume > 0}
            findings += hq
        except Exception as e:
            notes.append(f"harmony balance check: failed ({e})")
    notes.append(f"vocals: {len(files)} vocal track(s); lead '{lead}'"
                 + ("" if a.lead_track else " (by name or sound; --lead-track to change)"))
    return findings, notes


def g_effects(p, R, od, a):
    out, n = [], 0
    for t in p.tracks:
        if not t.devices:
            continue
        chain_off = all(not d.on for d in t.devices) and t.native is not None and \
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
                              problem=f"{d.name} is bypassed or offline", fix="remove it if it is not needed: "
                              "a bypassed plug-in still loads with the project"))
        lim = [d.name for d in t.devices if d.on and any(w in d.name.lower() for w in LIMITER_WORDS)]
        if len(lim) > 1:
            n += 1
            out.append(_f("fx", n, tool="effects", kind="stacked-limiters", severity="medium", track=t.name,
                          problem=f"{len(lim)} limiters in a row ({', '.join(lim)}): each one flattens what the "
                                  "last left, and the second rarely adds anything but distortion",
                          fix="keep one limiter at the end of the chain; set its ceiling there"))
    return out, [f"effects: {sum(len(t.devices) for t in p.tracks)} plug-ins on {sum(1 for t in p.tracks if t.devices)} tracks"]


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

    def add(track, problem, where=""):
        nonlocal n
        n += 1
        out.append(_f("intent", n, tool="intent", kind="deliberate?", severity="info", track=track, where=where,
                      problem=problem, applies="info",
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
                        f"({len(pts)} points, {rng})", _where(p, pts[0][0]))
        if t.muted and t.clips:
            add(t.name, "the track is muted but has items (it is not checked and not heard)")
        if t.on and abs(t.pan) >= 0.9:
            add(t.name, f"panned hard {'right' if t.pan > 0 else 'left'}")
        if t.on and t.polarity:
            add(t.name, "polarity (phase) is flipped on the track")
        for c in t.clips:
            if c.muted or not t.on:
                continue
            if c.level < 0:
                add(t.name, f"{W['item']} '{c.name}' plays with its polarity flipped", _where(p, c.start))
            elif c.level > 10 ** (9 / 20):
                add(t.name, f"{W['item']} '{c.name}' is turned up {20 * math.log10(c.level):+.1f} dB", _where(p, c.start))
            if c.stretch_markers:
                add(t.name, f"{W['item']} '{c.name}' has {c.stretch_markers} stretch marker(s) (followed in the checks' renders)",
                    _where(p, c.start))
    return out, [f"intent: {n} thing(s) that look deliberate, listed as questions"]


def g_mix(p, R, od, a):
    return SC.g_mix(p.path, od, a, tempo=p.tempo)


def g_stems(p, R, od, a):
    if not a.deep:
        return [], ["stems: skipped (add --deep to check frequency fights and mic phase between tracks)"]
    from hypnomix.engineer import masking as M
    stems, sr = M.load_stems(R.dir)
    if len(stems) < 2:
        return [], ["stems: fewer than two heard audio tracks"]
    f, notes = SC.stem_findings(stems, sr)
    notes.append("stems: tracks were rendered without their FX, so EQ already on a track is not counted")
    return f, notes


# ---------------------------------------------------------------- run
def run(a, path, od, groups):
    p = PJ.load(path)
    W.clear()
    W.update(WORDS.get(p.daw, WORDS["reaper"]))
    print(f"  {W['daw']} project: {len(p.tracks)} tracks, {p.tempo:g} BPM, {p.end():.0f} s")
    R = Renders(p, od)
    if {"names", "clips", "vocals", "stems"} & set(groups):
        R.build(a.jobs)
        print(f"  rendered {len(R.files)} tracks → {R.dir}")
    role = roles(p, R) if {"vocals", "clips"} & set(groups) else {}
    vocal_names = [t for t, r in role.items() if r in ("lead_vocal", "backing_vocal")]
    fns = {"names": g_names, "files": g_files, "clips": lambda p, R, od, a: g_clips(p, R, od, a, vocal_names), "effects": g_effects, "recordings": g_recordings, "noise": g_noise,
           "intent": g_intent, "mix": g_mix, "stems": g_stems,
           "vocals": lambda p, R, od, a: g_vocals(p, R, od, a, role)}
    warn = list(getattr(p, "warnings", [])) + sorted(set(R.warn))

    def one(g):
        import time
        t0 = time.time()
        try:
            f, notes = fns[g](p, R, od, a)
        except Exception as e:
            f, notes = [], [f"{g}: failed ({type(e).__name__}: {e})"]
        if g == groups[0] and warn:
            notes = [f"project: {w}" for w in warn[:12]] + notes
        secs = time.time() - t0
        (od / f"{g}.json").write_text(json.dumps({"group": g, "set": str(p.path), "seconds": secs,
                                                  "findings": f, "notes": notes}, indent=1, default=str))
        print(f"  {g:<10} {len(f):4d} findings  ({secs:.0f} s)")

    with ThreadPoolExecutor(max_workers=max(1, min(a.jobs, len(groups)))) as ex:
        list(ex.map(one, groups))
