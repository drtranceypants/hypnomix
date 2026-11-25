"""First-pass scan of a REAPER project (.rpp): the same review list as a Live set, from the shared project model.

    hypnomix scan SONG.rpp [--mix MIX.wav] [--ref MIX.wav] [--deep] [--only GROUP ...]

REAPER can stay open (nothing is written next to the project; everything goes to the output folder). Every audio
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
Findings that change the project are listed as *manual* (what to do in REAPER) until `hypnomix fix` can write
.rpp files; findings that make new audio (tune, dehiss, deess) work the same as for a Live set.
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

GROUPS = ["files", "clips", "vocals", "effects", "recordings", "noise", "intent", "mix", "stems"]
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


# ---------------------------------------------------------------- groups
def g_files(p, R, od, a):
    out = []
    for n, (t, c, path) in enumerate(p.missing(), 1):
        out.append(_f("files", n, tool="files", kind="missing-audio", severity="high", track=t.name,
                      where=_where(p, c.start), problem=f"item '{c.name}' plays {path}, which is not there",
                      fix="find the file before anything else: REAPER offers to search for missing media when the "
                          "project opens, or re-link it in the item's properties (Choose new file)"))
    return out, [f"files: {sum(len(t.clips) for t in p.tracks)} items checked, {len(out)} missing"]


def g_clips(p, R, od, a):
    out, n = [], 0
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
                    out.append(_f("clips", n, tool="clips", kind="click", severity="medium" if lvl > 0.05 else "low",
                                  track=t.name, where=_where(p, at),
                                  problem=f"item '{c.name}' {edge}s on a loud sample ({20 * math.log10(lvl):.0f} dBFS) "
                                          f"with no fade: an audible tick",
                                  fix=f"give the item a short fade {'in' if edge == 'start' else 'out'} (5 ms) in REAPER"))
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
            out.append(_f("clips", n, tool="clips", kind="cut", severity="medium" if abs(f - b) >= 8 else "low",
                          track=t.name, where=_where(p, c1.start),
                          problem=f"level jumps {f - b:+.1f} dB where '{c0.name}' meets '{c1.name}' (a comp cut "
                                  "recorded at a different level)",
                          fix=f"listen first; if it is not the performance, set item '{c1.name}' volume "
                              f"{-(f - b) / 2:+.1f} dB (half the jump) or lengthen the crossfade"))
    return out, [f"clips: item edges and cuts checked on {len(p.audio_tracks())} tracks"]


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
                f["fix"] = f["fix"].replace("comp clips in Live", "items in REAPER")
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
                          problem=f"item '{c.name}' is turned up {20 * math.log10(g):+.1f} dB, which lifts its noise "
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
            if lab.startswith("Volume") and "fader-scaled" not in lab:
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
                add(t.name, f"item '{c.name}' plays with its polarity flipped", _where(p, c.start))
            elif c.level > 10 ** (9 / 20):
                add(t.name, f"item '{c.name}' is turned up {20 * math.log10(c.level):+.1f} dB", _where(p, c.start))
            if c.stretch_markers:
                add(t.name, f"item '{c.name}' has {c.stretch_markers} stretch marker(s) (checks play it straight)",
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
    print(f"  REAPER project: {len(p.tracks)} tracks, {p.tempo:g} BPM, {p.end():.0f} s")
    R = Renders(p, od)
    if {"clips", "vocals", "stems"} & set(groups):
        R.build(a.jobs)
        print(f"  rendered {len(R.files)} tracks → {R.dir}")
    role = roles(p, R) if "vocals" in groups else {}
    fns = {"files": g_files, "clips": g_clips, "effects": g_effects, "recordings": g_recordings, "noise": g_noise,
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
