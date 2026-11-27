"""Hands-on mixer tools for the REAPER that is open, the way `hypnomix live`, `loop` and `diagnose` work in Live.

  hypnomix reaper snapshot [OUT.json]       every track (the master too): fader, pan, width, mute, solo, phase,
                                            sends, and each plug-in's on/off state and parameters, as JSON
                                            (an OUT that already exists is never overwritten)
  hypnomix reaper snapshot restore FILE     put a snapshot back (one undo step, "hypnomix: snapshot restore");
                                            FILE is a snapshot or a loop take's .json
  hypnomix reaper snapshot diff A B         what changed from A to B, in plain words (REAPER not needed)

  hypnomix reaper loop --bars 33-40         render that stretch of the master, measure it, keep it, compare it
  hypnomix reaper loop --secs 60-80           with the previous take of the same stretch (and your profile)
       --label NAME                         name the take
       --set "CHANGE"                       a change before the take (repeatable)
       --ab "CHANGE"                        A/B: render as it is, make the change(s), render again; B is also
                                            written at A's loudness so you can hear it level-matched
       --revert                             with --ab (only): put the mix back as it was before B (one undo step)

  hypnomix reaper diagnose [--bars 8]       find the loudest stretch, solo each top-level folder (or track) and
                                            render it: who owns the sub (20-60 Hz), the bass (60-250 Hz) and the
                                            vocal band (1-4 kHz), and who spreads the low end in stereo;
                                            each run gets its own folder, hypnomix-out/diagnose/reaper-<song>/
                                            run-001, run-002 ... (an earlier run is never replaced)

A CHANGE is one of (TRACK: name, number from `hypnomix reaper tracks`, or master; quote names with spaces):
  db TRACK -2.5          fader to -2.5 dB          nudge TRACK +1     fader up 1 dB
                         (a fader or send runs from -150 to +12 dB)
  pan TRACK -0.3         pan (-1 left .. 1 right)  mute TRACK 0|1
  fx TRACK FX 0|1        a plug-in off or on (FX: name or number)
  send TRACK N -12       send N (0 = the first) to -12 dB
  param TRACK FX P 0.4   a parameter, normalized 0..1   paramd TRACK FX P -3   a parameter by what it shows

Takes are rendered (not played): REAPER's own render of the master, sample-exact, nothing to route. They go to
hypnomix-out/loop/reaper-<stretch>/NN-<label>.wav with a .json holding the measurements and the mixer snapshot.
Bars count from the start of the project (bar 1 at 0 s), whatever number REAPER shows for the first bar.
Run in a private REAPER 7.86 on a two-track test project (2026-11-26), never on a real song, nothing judged by
ear: snapshot, diff and restore were exact; loop --ab "nudge Bass -3" measured B at -1.4 LU and --revert put the mix
back; diagnose put every solo back. Not checked: Windows, a real song, listening, diagnose with folders, send
destination names, and snapshot speed on a project with large plug-ins (see docs/REAPER.md).
"""
import argparse
import json
import math
import re
import shlex
import sys
import time
from pathlib import Path

from hypnomix.reaper.client import Reaper, ReaperError

BANDS = (("sub", 20, 60), ("bass", 60, 250), ("vocal", 1000, 4000))


# ------------------------------------------------------------------ snapshots
def snapshot(r, max_params=4096):
    return r.call("mixer_snapshot", max_params=max_params)


def _own_internal(fx_name, param_name):
    """A value HypnoMix Probe / Main keep for themselves (the bridge's slot and match gain, the 'guide seen' flag):
    left out of snapshots by mixer.lua, and skipped here too so older snapshots never put them back."""
    fn, pn = str(fx_name or "").lower(), str(param_name or "").lower()
    if "hypnomix probe" not in fn and "hypnomix main" not in fn:
        return False
    return any(w in pn for w in ("slot", "abgain", "match gain", "guide seen"))


def _snap_of(d):
    """The mixer snapshot in D: a snapshot itself, or a loop take's .json (its "mix"). None when there is none."""
    for s in (d, d.get("mix") if isinstance(d, dict) else None):
        if isinstance(s, dict) and isinstance(s.get("tracks"), list) and all(isinstance(t, dict) for t in s["tracks"]):
            return s
    return None


def _clean(s):
    return str(s).replace("\t", " ").replace("\n", " ").replace("\r", " ")


def _num(v):
    return repr(float(v))


def flatten(snap):
    """The snapshot as the bridge's restore file (see mixer.lua `restore_file`). Only values, never code."""
    out = []
    for t in snap.get("tracks", []):
        out.append(f"track\t{_clean(t.get('guid', ''))}\t{int(t.get('index', -1))}\t{_clean(t.get('name', ''))}")
        for key, field in (("D_VOL", "volume"), ("D_PAN", "pan"), ("D_WIDTH", "width")):
            if t.get(field) is not None:
                out.append(f"info\t{key}\t{_num(t[field])}")
        for key, field in (("B_MUTE", "mute"), ("B_PHASE", "phase")):
            if t.get(field) is not None:
                out.append(f"info\t{key}\t{1 if t[field] else 0}")
        if not t.get("master") and t.get("solo") is not None:
            out.append(f"info\tI_SOLO\t{int(t['solo'])}")
        for s in t.get("sends") or []:
            dest = _clean(s.get("dest", ""))
            for key, field in (("D_VOL", "volume"), ("D_PAN", "pan"), ("I_SENDMODE", "mode")):
                if s.get(field) is not None:
                    out.append(f"send\t{int(s['index'])}\t{dest}\t{key}\t{_num(s[field])}")
            if s.get("mute") is not None:
                out.append(f"send\t{int(s['index'])}\t{dest}\tB_MUTE\t{1 if s['mute'] else 0}")
        for f in t.get("fx") or []:
            out.append(f"fx\t{_clean(f.get('guid', ''))}\t{int(f.get('index', 0))}\t{_clean(f.get('name', ''))}")
            for p in f.get("params") or []:
                if not _own_internal(f.get("name"), p.get("name")):
                    out.append(f"param\t{int(p['i'])}\t{_num(p['value'])}")
            if f.get("on") is not None:
                out.append(f"on\t{1 if f['on'] else 0}")
    return "\n".join(out) + "\n"


def restore(r, snap):
    """Put a snapshot back in one undo step. Returns {changed, missing}."""
    path = Path(r.dir) / f"restore-{int(time.time() * 1000)}.txt"
    path.write_text(flatten(snap), encoding="utf-8", newline="\n")
    try:
        return r.call("mixer_restore", file=str(path).replace("\\", "/"))
    finally:
        path.unlink(missing_ok=True)


def db(v):
    return -math.inf if not v or v <= 0 else 20 * math.log10(v)


def db_words(v):
    d = db(v)
    return "-inf dB" if d == -math.inf else f"{d:+.1f} dB"


def pan_words(p):
    if abs(p) < 0.005:
        return "centre"
    return f"{abs(p) * 100:.0f}% {'left' if p < 0 else 'right'}"


def _label(t):
    return "Master" if t.get("master") else (t.get("name") or f"track {t.get('index')}")


def _match(items, key_fields):
    """{key: item}, by the first field that is set (GUID, then index + name)."""
    out = {}
    for it in items:
        for f in key_fields:
            k = f(it)
            if k is not None and k not in out:
                out[k] = it
                break
    return out


def _vol_changed(a, b):
    if a is None or b is None:
        return False
    da, dbb = db(a), db(b)
    if math.isinf(da) or math.isinf(dbb):
        return da != dbb
    return abs(da - dbb) > 0.05


def diff(a, b):
    """What changed from snapshot A to snapshot B, one plain sentence per change."""
    lines = []
    ta = {("master" if t.get("master") else t.get("guid") or f"#{t.get('index')}"): t for t in a.get("tracks", [])}
    tb = {("master" if t.get("master") else t.get("guid") or f"#{t.get('index')}"): t for t in b.get("tracks", [])}
    for k, t in tb.items():
        if k not in ta:
            lines.append(f"{_label(t)}: a new track")
    for k, t in ta.items():
        if k not in tb:
            lines.append(f"{_label(t)}: gone")
    for k, x in ta.items():
        y = tb.get(k)
        if y is None:
            continue
        name = _label(y)
        if x.get("name") != y.get("name") and not y.get("master"):
            lines.append(f"{x.get('name')}: renamed {y.get('name')}")
        if _vol_changed(x.get("volume"), y.get("volume")):
            ch = db(y["volume"]) - db(x["volume"])
            lines.append(f"{name}: fader {db_words(x['volume'])} → {db_words(y['volume'])}"
                         + (f" ({ch:+.1f} dB)" if math.isfinite(ch) else ""))
        if abs((x.get("pan") or 0) - (y.get("pan") or 0)) > 0.005:
            lines.append(f"{name}: pan {pan_words(x.get('pan') or 0)} → {pan_words(y.get('pan') or 0)}")
        if abs((x.get("width") if x.get("width") is not None else 1) - (y.get("width") if y.get("width") is not None else 1)) > 0.005:
            lines.append(f"{name}: width {(x.get('width') or 0) * 100:.0f}% → {(y.get('width') or 0) * 100:.0f}%")
        if bool(x.get("mute")) != bool(y.get("mute")):
            lines.append(f"{name}: {'muted' if y.get('mute') else 'unmuted'}")
        if bool(x.get("solo")) != bool(y.get("solo")):
            lines.append(f"{name}: {'soloed' if y.get('solo') else 'solo off'}")
        if bool(x.get("phase")) != bool(y.get("phase")):
            lines.append(f"{name}: polarity {'flipped' if y.get('phase') else 'back to normal'}")
        sa = {(s.get("index"), s.get("dest")): s for s in x.get("sends") or []}
        sb = {(s.get("index"), s.get("dest")): s for s in y.get("sends") or []}
        for k2, s in sb.items():
            if k2 not in sa:
                lines.append(f"{name}: a new send to {s.get('dest')} at {db_words(s.get('volume'))}")
        for k2, s in sa.items():
            s2 = sb.get(k2)
            if s2 is None:
                lines.append(f"{name}: the send to {s.get('dest')} is gone")
                continue
            if _vol_changed(s.get("volume"), s2.get("volume")):
                lines.append(f"{name}: send to {s.get('dest')} {db_words(s.get('volume'))} → {db_words(s2.get('volume'))}")
            if abs((s.get("pan") or 0) - (s2.get("pan") or 0)) > 0.005:
                lines.append(f"{name}: send to {s.get('dest')} pan {pan_words(s.get('pan') or 0)} → {pan_words(s2.get('pan') or 0)}")
            if bool(s.get("mute")) != bool(s2.get("mute")):
                lines.append(f"{name}: send to {s.get('dest')} {'muted' if s2.get('mute') else 'unmuted'}")
            if s.get("mode") != s2.get("mode"):
                modes = {0: "post-fader", 1: "pre-FX", 3: "pre-fader (post-FX)"}
                lines.append(f"{name}: send to {s.get('dest')} {modes.get(int(s.get('mode') or 0), s.get('mode'))} → "
                             f"{modes.get(int(s2.get('mode') or 0), s2.get('mode'))}")
        keyf = (lambda f: f.get("guid") or None, lambda f: (f.get("index"), f.get("name")))
        fa, fb = _match(x.get("fx") or [], keyf), _match(y.get("fx") or [], keyf)
        for k2, f in fb.items():
            if k2 not in fa:
                lines.append(f"{name}: {f.get('name')} added")
        for k2, f in fa.items():
            f2 = fb.get(k2)
            if f2 is None:
                lines.append(f"{name}: {f.get('name')} removed")
                continue
            fname = f"{name} · {f2.get('name')}"
            if bool(f.get("on")) != bool(f2.get("on")):
                lines.append(f"{fname}: switched {'on' if f2.get('on') else 'off'}")
            pa = {p["i"]: p for p in f.get("params") or []}
            for p2 in f2.get("params") or []:
                p = pa.get(p2["i"])
                if p is None or abs(p["value"] - p2["value"]) <= 1e-6 or _own_internal(f2.get("name"), p2.get("name")):
                    continue
                if p.get("shown") and p2.get("shown") and p["shown"] != p2["shown"]:
                    lines.append(f"{fname}: {p2.get('name')} {p['shown'].strip()} → {p2['shown'].strip()}")
                else:
                    lines.append(f"{fname}: {p2.get('name')} {p['value']:.3f} → {p2['value']:.3f}")
    return lines


# ------------------------------------------------------------------ one change (loop --set / --ab)
NUMBER_REF = re.compile(r"\s*(-?[0-9]{1,9})(\.0+)?\s*")          # a track number: plain digits, nothing Lua or Python might read otherwise


def _find(snap, ref):
    """The track REF names: the master for "master" (or nothing), plain digits (like 3 or 3.0) as a track index
    (never a name), anything else by name, so '1_0', '0x10', 'nan' and 'inf' are names. Whatever is found is then
    sent to the bridge by its own index, so the bridge's reading of REF never matters."""
    tracks = snap.get("tracks", [])
    if ref is None or str(ref) in ("", "master"):
        return next((t for t in tracks if t.get("master")), None)
    if NUMBER_REF.fullmatch(str(ref)):
        n = int(NUMBER_REF.fullmatch(str(ref)).group(1))
        return next((t for t in tracks if not t.get("master") and t.get("index") == n), None)
    return next((t for t in tracks if not t.get("master") and t.get("name") == ref), None)


NEED = {"db": 2, "nudge": 2, "pan": 2, "mute": 2, "fx": 3, "send": 3, "param": 4, "paramd": 4}
DB_MIN, DB_MAX = -150.0, 12.0                            # the fader and send levels a change may set


def parse_change(text):
    a = shlex.split(text)
    if not a or a[0] not in NEED:
        raise ValueError(f"unknown change {text!r} (use {'/'.join(NEED)})")
    op, args = a[0], a[1:]
    if len(args) != NEED[op]:
        raise ValueError(f"change {text!r}: {op} takes {NEED[op]} values; refusing to guess")
    if op in ("mute", "fx") and args[-1] not in ("0", "1"):
        raise ValueError(f"change {text!r}: the last value is 0 or 1")
    try:
        v = float(args[-1])
    except ValueError:
        raise ValueError(f"change {text!r}: {args[-1]!r} is not a number")
    if not math.isfinite(v):
        raise ValueError(f"change {text!r}: {args[-1]!r} is not a finite number")
    if op in ("db", "send") and not DB_MIN <= v <= DB_MAX:
        raise ValueError(f"change {text!r}: {args[-1]} dB is outside {DB_MIN:g} to {DB_MAX:+g} dB")
    if op == "send" and not re.fullmatch(r"\d+", args[1]):
        raise ValueError(f"change {text!r}: the send number {args[1]!r} is a whole number (0 = the first)")
    return op, args


def apply_change(r, text):
    op, args = parse_change(text)
    t, v = args[0], args[-1]
    if op == "db":
        return r.set_track(t, volume_db=float(v))
    if op == "nudge":
        tr = _find(snapshot(r, max_params=0), t)
        if tr is None:
            raise ReaperError(f"no track {t}")
        if not tr["volume"] or tr["volume"] <= 0:
            raise ReaperError(f"{t}'s fader is at -inf dB: use db {t} N instead")
        new = db(tr["volume"]) + float(v)
        if new > DB_MAX:
            raise ReaperError(f"nudge {t} {v}: the fader would reach {new:+.1f} dB, above {DB_MAX:+g} dB")
        # the track that was read, by its own index, so the bridge changes that same track
        return r.set_track("master" if tr.get("master") else str(tr["index"]), volume_db=new)
    if op == "pan":
        return r.set_track(t, pan=max(-1.0, min(1.0, float(v))))
    if op == "mute":
        return r.set_track(t, mute=int(v))
    if op == "fx":
        return r.enable(t, args[1], v == "1")
    if op == "send":
        return r.call("mixer_send", track=t, send=int(args[1]), volume_db=float(v))
    if op == "param":
        return r.set_norm(t, args[1], args[2], max(0.0, min(1.0, float(v))))
    return r.set_shown(t, args[1], args[2], float(v))


# ------------------------------------------------------------------ loop
def measure_take(wav):
    from hypnomix.ears.measure import measure
    from hypnomix.session.profile import audio_metrics
    return audio_metrics(measure(wav))


def parse_range(text, whole=False):
    """A-B as two numbers; WHOLE: two whole numbers (bars)."""
    num = r"\d+" if whole else r"\d+(?:\.\d+)?"
    m = re.fullmatch(rf"\s*({num})\s*-\s*({num})\s*", str(text))
    if not m:
        raise ValueError(f"{text!r}: give a range of {'whole numbers' if whole else 'numbers'}, e.g. 33-40")
    return float(m.group(1)), float(m.group(2))


def bar_span(tm, first, last):
    """Seconds of bars FIRST..LAST (1-based, inclusive) from the bridge's time map."""
    bars = tm["bars"]
    if first < 1 or last < first:
        raise ValueError(f"bars {first}-{last}: the first bar is 1 and the range runs forwards")
    if last >= len(bars):
        raise ValueError(f"bars {first}-{last}: the project has {len(bars) - 1} bars")
    return bars[first - 1], bars[last]


def _take_no(f):
    """The take number at the front of NN-label.wav / .json (any number of digits), or None."""
    m = re.match(r"(\d+)-", f.name)
    return int(m.group(1)) if m else None


def file_label(label):
    """LABEL as part of a file name: no folders, nothing Windows refuses (the .json keeps the label as typed)."""
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", str(label)).strip(" .")
    s = re.sub(r"\.{2,}", ".", s).strip(" .-")
    return s or "take"


def take(r, start, end, folder, label, measure=None):
    measure = measure or measure_take
    folder = Path(folder)
    n = max([k for f in folder.glob("*-*.wav") if (k := _take_no(f)) is not None] or [0]) + 1
    wav = folder / f"{n:02d}-{file_label(label)}.wav"
    r.render_master(start, end, wav)
    m = measure(wav)
    meta = {"label": label, "start": round(start, 3), "end": round(end, 3), "secs": round(end - start, 3), "metrics": m}
    try:
        meta["mix"] = snapshot(r)
    except ReaperError as e:                             # the snapshot is a bonus, never fatal
        meta["mix_error"] = str(e)
    wav.with_suffix(".json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return wav, m


def level_match(wav_b, lufs_a, lufs_b):
    """B at A's loudness, next to it (NN-label-B-matched.wav). Returns the path and the gain in dB."""
    import numpy as np
    import soundfile as sf
    gain = (lufs_a - lufs_b) if (lufs_a is not None and lufs_b is not None and math.isfinite(lufs_a) and math.isfinite(lufs_b)) else 0.0
    y, sr = sf.read(str(wav_b), always_2d=True)
    out = Path(wav_b).with_name(Path(wav_b).stem + "-matched.wav")
    sf.write(str(out), (y * 10 ** (gain / 20)).astype(np.float32), sr, subtype="FLOAT")
    return out, gain


def loop(r, start, end, folder, label="take", sets=(), ab=(), revert=False, measure=None, log=print):
    from hypnomix.live.loop import report
    from hypnomix.session.profile import profile_ranges
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    prof = profile_ranges()
    prev_json = sorted((f for f in folder.glob("*-*.json") if _take_no(f) is not None), key=_take_no)
    prev = json.loads(prev_json[-1].read_text(encoding="utf-8", errors="replace"))["metrics"] if prev_json else None
    for c in list(sets) + list(ab):
        parse_change(c)                                  # every change checked before anything renders
    for c in sets:
        apply_change(r, c)
        log(f"  ✓ {c}")
    if not ab:
        w, m = take(r, start, end, folder, label, measure)
        report(m, prev, prof, f"TAKE {w}" + ("   (Δ vs previous take)" if prev else ""))
        return {"take": str(w), "metrics": m}
    before = snapshot(r)
    wa, ma = take(r, start, end, folder, f"{label}-A", measure)
    report(ma, prev, prof, f"A  TAKE {wa}")
    out = None
    try:
        for c in ab:
            apply_change(r, c)
            log(f"  ✓ {c}")
        wb, mb = take(r, start, end, folder, f"{label}-B", measure)
        report(mb, ma, prof, f"B  TAKE {wb}   (Δ = B − A)")
        matched, gain = level_match(wb, ma.get("integrated_lufs"), mb.get("integrated_lufs"))
        louder = -gain
        log(f"\n  B is {abs(louder):.1f} LU {'louder' if louder >= 0 else 'quieter'} than A. The bands above are shares "
            f"of each take's own total, so they compare at matched loudness already.")
        log(f"  B at A's loudness ({gain:+.1f} dB), to listen against A: {matched}")
        out = {"a": str(wa), "b": str(wb), "b_matched": str(matched), "gain_db": gain, "a_metrics": ma, "b_metrics": mb}
    finally:
        if revert:                                       # put back even when B failed part way
            try:
                res = restore(r, before)
            except Exception as e:
                log(f"\n  could not put the mix back ({e}): it may still hold the B changes "
                    f"(Edit > Undo in REAPER takes them out)")
                if out is not None:
                    raise
            else:
                log(f"\n  mix put back as it was before B ({res.get('changed', 0)} values; one undo step)")
                if out is not None:
                    out["reverted"] = res
    return out


# ------------------------------------------------------------------ diagnose
def top_level(tracks):
    """The tracks at the top of the folder tree, in order: folders (I_FOLDERDEPTH 1) and loose tracks."""
    level, out = 0, []
    for t in tracks:
        if level == 0:
            out.append(dict(t, folder=t.get("depth", 0) == 1))
        level = max(0, level + int(t.get("depth", 0)))
    return out


def loudest(y, sr, bars, n):
    """1-based first bar of the loudest N bars (by RMS of the mono sum), from the bar start times in seconds."""
    import numpy as np
    m = y.mean(axis=1) if y.ndim > 1 else y
    e = []
    for i in range(len(bars) - 1):
        a, b = int(round(bars[i] * sr)), int(round(bars[i + 1] * sr))
        seg = m[a:b]
        e.append(float((seg ** 2).sum()) if len(seg) else 0.0)
    n = max(1, min(n, len(e)))
    if not e:
        return 1
    sums = np.convolve(np.array(e), np.ones(n), "valid")
    return int(np.argmax(sums)) + 1


def band_levels(path):
    import numpy as np
    import soundfile as sf
    from hypnomix.session.doctor import band_db, low_corr
    z, sr = sf.read(str(path), always_2d=True)
    zm = z.mean(axis=1)
    if not len(zm) or np.abs(zm).max() < 1e-4:
        return {"silent": True}
    out = {"rms": round(10 * math.log10(float((zm ** 2).mean()) + 1e-15), 1)}
    for name, lo, hi in BANDS:
        out[name] = round(band_db(zm, sr, lo, hi), 1)
    out["low_corr"] = low_corr(z, sr) if z.shape[1] > 1 else None
    return out


def shares(res):
    for band, _, _ in BANDS:
        tot = sum(10 ** (v[band] / 10) for v in res.values() if not v.get("silent"))
        for v in res.values():
            if not v.get("silent"):
                v[band + "_share"] = round(100 * 10 ** (v[band] / 10) / tot) if tot > 0 else 0
    return res


def diagnose(r, folder, bars=8, whole=None, project=None, log=print):
    import soundfile as sf
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    tm = r.call("mixer_timemap")
    if not tm.get("length"):
        raise ReaperError("the project is empty")
    units = top_level(r.tracks())
    if not whole:                                        # every unit soloed: the user's own solos don't count
        whole = folder / "whole.wav"
        whole.unlink(missing_ok=True)                    # so exists() below means this run wrote it
        r.call("mixer_solo_render", tracks=",".join(u["guid"] for u in units), start=0.0, end=float(tm["length"]),
               path=str(whole.resolve()).replace("\\", "/"))
        if not whole.exists():
            raise ReaperError("REAPER did not write the render")
    whole = Path(whole)
    try:
        y, sr = sf.read(str(whole), always_2d=True)
    except (OSError, RuntimeError) as e:                 # soundfile's errors are RuntimeErrors
        raise ValueError(f"{whole}: not a readable audio file ({e})")
    bar0 = loudest(y, sr, tm["bars"], bars)
    last = min(bar0 + bars - 1, len(tm["bars"]) - 1)
    start, end = bar_span(tm, bar0, last)
    log(f"loudest {last - bar0 + 1} bars: {bar0}-{last} ({start:.1f}-{end:.1f} s)")
    kind = "folder" if any(u["folder"] for u in units) else "track"
    res, seen = {}, set()
    for u in units:
        name = u["name"] or f"track {u['index']}"
        if name in seen:
            name = f"{name} ({u['index']})"
        seen.add(name)
        if u.get("mute"):
            continue
        wav = folder / f"solo-{u['index']:03d}.wav"
        wav.unlink(missing_ok=True)                      # a leftover from an earlier run must not count
        r.call("mixer_solo_render", tracks=u["guid"], start=float(start), end=float(end),
               path=str(wav.resolve()).replace("\\", "/"))
        if not wav.exists():
            res[name] = {"silent": True, "error": "REAPER did not write the render"}
            continue
        res[name] = dict(band_levels(wav), wav=str(wav), folder=u["folder"])
    shares(res)
    out = {"project": project, "tempo": tm.get("tempo"), "loud_bars": [bar0, last], "start": start,
           "end": end, "by": kind, "units": res}
    (folder / "diagnose.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def print_diagnosis(out, log=print):
    log(f"{'folder' if out['by'] == 'folder' else 'track':<30}{'level':>7}{'sub%':>6}{'bass%':>7}{'vocal%':>8}{'lowcorr':>9}")
    rows = sorted(out["units"].items(), key=lambda kv: -kv[1].get("rms", -999))
    for n, v in rows:
        if v.get("silent"):
            log(f"{n[:29]:<30}  (silent here)")
            continue
        lc = f"{v['low_corr']:.2f}" if v.get("low_corr") is not None else "  -"
        log(f"{n[:29]:<30}{v['rms']:>7}{v['sub_share']:>6}{v['bass_share']:>7}{v['vocal_share']:>8}{lc:>9}")
    live = [(n, v) for n, v in rows if not v.get("silent")]
    for band, words in (("sub", "the sub (20-60 Hz)"), ("bass", "the bass (60-250 Hz)"), ("vocal", "the vocal band (1-4 kHz)")):
        if live:
            n, v = max(live, key=lambda kv: kv[1][band + "_share"])
            log(f"  {n} owns {words}: {v[band + '_share']}% of it")
    wide = [n for n, v in live if v.get("low_corr") is not None and v["low_corr"] < 0.7]
    if wide:
        log(f"  wide below 150 Hz (correlation under 0.7): {', '.join(wide)}")


# ------------------------------------------------------------------ the command line
def _out(*parts):
    from hypnomix.core.paths import out
    return out(*parts)


SNAPSHOT_USAGE = "hypnomix reaper snapshot [OUT.json] | snapshot restore FILE.json | snapshot diff A.json B.json"


def read_snapshot(path):
    """The mixer snapshot in PATH (a snapshot, or a loop take's .json), or one plain sentence and exit."""
    p = Path(path)
    if not p.is_file():
        sys.exit(f"{p}: no such file")
    try:
        d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        sys.exit(f"{p}: not a readable snapshot (a .json from hypnomix reaper snapshot or loop)")
    s = _snap_of(d)
    if s is None:
        why = f" (the take's snapshot failed: {d['mix_error']})" if isinstance(d, dict) and d.get("mix_error") else ""
        sys.exit(f"{p}: no mixer snapshot in this file{why}")
    return s


def _free(path):
    """PATH, or PATH-2, PATH-3 ... if it is taken (for the default, timestamped name only)."""
    n, out = 1, path
    while out.exists():
        n += 1
        out = path.with_name(f"{path.stem}-{n}{path.suffix}")
    return out


def main_snapshot(argv, r=None):
    argv = list(argv)
    if any(x in ("-h", "--help") for x in argv):
        print(__doc__)
        return None
    for x in argv:
        if x.startswith("-"):
            sys.exit(f"unknown option {x}: {SNAPSHOT_USAGE}")
    if argv and argv[0] == "diff":
        if len(argv) != 3:
            sys.exit("hypnomix reaper snapshot diff A.json B.json")
        a, b = read_snapshot(argv[1]), read_snapshot(argv[2])
        try:
            lines = diff(a, b)
        except (TypeError, ValueError, KeyError, AttributeError):
            sys.exit(f"{argv[1]} or {argv[2]}: not a readable snapshot (a .json from hypnomix reaper snapshot or loop)")
        print("\n".join(lines) if lines else "no differences")
        return lines
    if argv and argv[0] == "restore":
        if len(argv) != 2:
            sys.exit("hypnomix reaper snapshot restore FILE.json")
        s = read_snapshot(argv[1])
        if not s["tracks"]:
            sys.exit(f"{argv[1]}: the snapshot holds no tracks, so there is nothing to restore")
        try:
            flatten(s)                                   # a damaged file stops here, before REAPER is asked
        except (TypeError, ValueError, KeyError, AttributeError):
            sys.exit(f"{argv[1]}: not a readable snapshot (a .json from hypnomix reaper snapshot or loop)")
        res = restore(r or Reaper(), s)
        print(f"restored: {res.get('changed', 0)} values changed (Edit > Undo takes it back)")
        for m in res.get("missing") or []:
            print(f"  not found now: {m}")
        return res
    if len(argv) > 1:
        sys.exit(SNAPSHOT_USAGE)
    if argv:
        out = Path(argv[0])
        if out.exists():
            sys.exit(f"{out.name} already exists: choose a new name (nothing is ever overwritten)")
    else:
        out = _free(_out("snapshots") / f"reaper-mix-{time.strftime('%Y%m%d-%H%M%S')}.json")
    snap = snapshot(r or Reaper())                       # first, so an unreachable REAPER leaves no new folders
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        sys.exit(f"could not make the folder {out.parent}: {e.strerror or e}")
    try:
        with open(out, "x", encoding="utf-8") as f:     # "x": never replaces a file, even one made just now
            f.write(json.dumps(snap, indent=1))
    except FileExistsError:
        sys.exit(f"{out.name} already exists: choose a new name (nothing is ever overwritten)")
    except OSError as e:
        sys.exit(f"could not write {out}: {e.strerror or e}")
    n_fx = sum(len(t.get("fx") or []) for t in snap["tracks"])
    print(f"{len(snap['tracks']) - 1} tracks and the master, {n_fx} plug-ins → {out}")
    return snap


def main_loop(argv, r=None):
    ap = argparse.ArgumentParser(prog="hypnomix reaper loop", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--bars", help="bars A-B (1-based, inclusive)")
    g.add_argument("--secs", help="seconds A-B")
    ap.add_argument("--label", default="take")
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--ab", action="append", default=[])
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args(argv)
    if a.revert and not a.ab:
        ap.error("--revert only works together with --ab")
    try:
        for c in a.set + a.ab:
            parse_change(c)
        if a.bars:
            first, last = (int(x) for x in parse_range(a.bars, whole=True))
        else:
            start, end = parse_range(a.secs)
            if end <= start:
                raise ValueError(f"--secs {a.secs}: the end comes after the start")
    except ValueError as e:
        sys.exit(str(e))
    r = r or Reaper()
    try:
        if a.bars:
            start, end = bar_span(r.call("mixer_timemap"), first, last)
            section = f"reaper-bars{first:03d}-{last:03d}"
        else:
            section = f"reaper-{start:.1f}-{end:.1f}s"
        return loop(r, start, end, _out("loop", section), a.label, a.set, a.ab, a.revert)
    except (ReaperError, ValueError) as e:
        sys.exit(str(e))


def run_folder(base):
    """A new folder BASE/run-001, run-002 ... for one diagnose run; an earlier run's folder is never reused."""
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    n = max((int(m.group(1)) for p in base.iterdir() if (m := re.fullmatch(r"run-(\d+)", p.name))), default=0)
    while True:
        n += 1
        folder = base / f"run-{n:03d}"
        try:
            folder.mkdir()                               # exclusive: a folder made at the same moment is skipped
            return folder
        except FileExistsError:
            continue


def main_diagnose(argv, r=None):
    ap = argparse.ArgumentParser(prog="hypnomix reaper diagnose", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bars", type=int, default=8)
    ap.add_argument("--whole", help="a render of the whole master you already have (skips rendering it)")
    a = ap.parse_args(argv)
    if a.bars < 1:
        sys.exit("--bars: give 1 or more bars")
    if a.whole and not Path(a.whole).is_file():
        sys.exit(f"--whole {a.whole}: no such file")
    r = r or Reaper()
    try:
        project = r.ping().get("project") or ""
        song = Path(project).stem or "unsaved"
        base = _out("diagnose", f"reaper-{song}")
        try:
            folder = run_folder(base)
        except OSError as e:
            sys.exit(f"could not make a folder for this run in {base}: {e.strerror or e}")
        out = diagnose(r, folder, a.bars, a.whole, project or None)
    except (ReaperError, ValueError) as e:
        sys.exit(str(e))
    print_diagnosis(out)
    print(f"the renders and diagnose.json are in {folder}")
    return out
