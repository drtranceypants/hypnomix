#!/usr/bin/env python3
"""Sanity of the files before any work: is what you are about to mix actually in good shape? Report first;
nothing is changed and nothing is renamed.

Usage:
    hypnomix preflight FOLDER | SET.als | PROJECT.rpp | SESSION.ardour [--plan [SCAN_DIR]] [--out DIR]
                       [--recursive] [--length-tolerance 0.05] [--max-lag 5]

For a FOLDER it reads every audio file in it. For a set or project it reads every source file the project
plays (through the shared project model, so Live, REAPER and Ardour work the same way).

What it looks for, each as a finding with what to do:
  sample rate / bit depth   files that differ from the rest, and which ones are the odd ones out
  length and start          stems of one song that differ in length, or play ahead of or behind the others
                            (folders only: the clips of a project are placed by their positions)
  duplicates                two files with exactly the same audio
  fake stereo               stereo files whose left and right are identical (really mono); one empty channel;
                            plus a list of the mono files
  silent files              nothing in them, or so quiet nothing can be done with them
  DC offset, clipping       a steady offset away from zero; flat-topped peaks that are already in the file
  lossy sources             mp3, aac, ogg and other compressed files in a project
  missing or offline files  the project points at a file that is not there
  names that will not travel  characters other systems refuse (< > : " / \\ | ? *), reserved Windows names,
                            trailing spaces or dots, names that differ only by capitals, very long names or paths

With --plan every finding goes into a scan folder for the normal review (`hypnomix review`, `ab`, then
`hypnomix fix DIR --approved`). The three that `prep` already knows how to repair (DC offset: step rumble,
flat-topped peaks: step declip, fake stereo: step mono) are planned as prep steps and written, only if you approve,
as new files; `prep` also puts its usual 5 ms and 50 ms fades on the ends of those files. Different sample rates,
bit depths and lengths are made uniform by `hypnomix prep FOLDER --plan` (its format step); the rest are listed for
you to do: re-export, find the file again, rename. Without --plan the report is PREFLIGHT.md in --out
(default hypnomix-out/preflight); the exit code is 1 when something high is found, so it can gate a script.

Measured, not heard: a file the check calls silent may be an empty track on purpose. Say so and skip it.
"""
import argparse, collections, hashlib, json, os, re, sys, unicodedata, warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
from hypnomix.core import dsp  # noqa: E402
from hypnomix.core.paths import out_at  # noqa: E402

LOSSY_EXT = {".mp3", ".aac", ".m4a", ".ogg", ".oga", ".opus", ".wma", ".mp2"}
PCM_BITS = {"PCM_U8": 8, "PCM_S8": 8, "PCM_16": 16, "PCM_24": 24, "PCM_32": 32, "FLOAT": "32 float", "DOUBLE": "64 float"}
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
BAD_CHARS = set('<>:"/\\|?*')
HOP = 0.02                                       # seconds per envelope point, for the start check
SEV = {"high": 0, "medium": 1, "low": 2, "info": 3}


# ---------------------------------------------------------------- one file
def inspect(path, envelope=False):
    """Plain facts about one audio file. Never raises: a file that cannot be read says so."""
    import soundfile as sf
    path = Path(path)
    f = dict(name=path.name, path=str(path), ext=path.suffix.lower(), readable=True, error="")
    sub, sr = "", None
    try:
        info = sf.info(str(path))
        sub, sr = info.subtype, int(info.samplerate)
        f.update(sr=sr, channels=int(info.channels), subtype=sub, format=info.format)
    except Exception:
        pass                                      # mp3 on an old libsndfile: dsp.load falls back to ffmpeg
    try:
        y, sr2 = dsp.load(path)
    except Exception as e:
        f.update(readable=False, error=str(e).strip().splitlines()[-1][:120] if str(e).strip() else "unreadable")
        return f
    y = y.astype(np.float32)
    if sr is None:
        sr = int(sr2)
        f.update(sr=sr, channels=int(y.shape[1]), subtype="", format="")
    f["bits"] = PCM_BITS.get(sub)
    f["lossy"] = path.suffix.lower() in LOSSY_EXT or (bool(sub) and sub not in PCM_BITS)
    n = len(y)
    f["frames"] = n
    f["dur"] = n / sr if sr else 0.0
    if not n:
        f.update(peak=0.0, silent=True, empty=True)
        return f
    peak = float(np.max(np.abs(y)))
    f["peak"] = peak
    f["peak_db"] = round(20 * np.log10(max(peak, 1e-9)), 1)
    f["silent"] = peak < 10 ** (-80 / 20)
    f["quiet"] = (not f["silent"]) and peak < 10 ** (-50 / 20)
    f["dc"] = [round(float(abs(y[:, c].mean())), 5) for c in range(y.shape[1])]
    f["clipped"] = clip_runs(y, peak)
    # identical channels: judged against the file's own peak (-60 dB under it), so a very quiet stereo file is not called mono
    f["fake_stereo"] = bool(y.shape[1] == 2 and not f["silent"] and float(np.max(np.abs(y[:, 0] - y[:, 1]))) <= 1e-3 * peak)
    if y.shape[1] == 2 and not f["silent"]:
        pk = np.max(np.abs(y), axis=0)
        f["one_empty"] = bool(min(pk) < 1e-5 and max(pk) > 1e-3)
    else:
        f["one_empty"] = False
    f["hash"] = None if f["silent"] else hashlib.sha1(np.ascontiguousarray(y).tobytes()).hexdigest() + f":{sr}"
    mono = y.mean(axis=1)
    b = max(1, int(HOP * sr))
    k = len(mono) // b
    if k:
        env = np.sqrt((mono[:k * b].reshape(k, b) ** 2).mean(axis=1))
        on = np.flatnonzero(np.abs(mono) > 10 ** (-60 / 20))
        f["first_sound"] = float(on[0] / sr) if len(on) else None
        if envelope:
            f["env"] = np.sqrt(env).astype(np.float32)           # square root: loud hits do not drown the rest
    return f


def clip_runs(y, peak):
    """Runs of 3 or more samples stuck at the top (the same test the folder scan uses)."""
    if peak < 0.985:
        return 0
    top = np.abs(y).max(axis=1) >= max(0.985, peak * 0.9995)
    if not top.any():
        return 0
    stuck = int((np.convolve(top, np.ones(3), "same") >= 3).sum())
    runs = int((np.diff(np.concatenate([[0], top.view(np.int8), [0]])) == 1).sum())
    return runs if stuck else 0


# ---------------------------------------------------------------- the start check
def lags(envs, max_s=5.0):
    """{name: (lag seconds, correlation at the best lag, correlation at 0, repeats)}: where each file's envelope lines
    up best with the average of the others. Positive: its sound arrives that much ahead of the others. `repeats`:
    other lags match about as well (a steady rhythm), so the lag may be a whole number of beats off."""
    names = [n for n, e in envs.items() if e is not None and len(e) > 50 and float(np.std(e)) > 0]
    out = {}
    if len(names) < 2:
        return out
    L = int(round(max_s / HOP))
    for n in names:
        rest = [envs[m] for m in names if m != n]
        N = max(len(e) for e in rest + [envs[n]])
        ref = np.zeros(N)
        for e in rest:
            z = (e - e.mean()) / (e.std() + 1e-12)
            ref[:len(z)] += z
        e = envs[n]
        best = (0, -2.0)
        cs = {}
        for lag in range(-L, L + 1):
            a = e[max(0, -lag):] if lag < 0 else e
            r = ref[lag:] if lag > 0 else ref
            m = min(len(a), len(r))
            if m < 100:
                continue
            a, r = a[:m], r[:m]
            if a.std() < 1e-9 or r.std() < 1e-9:
                continue
            c = float(np.corrcoef(a, r)[0, 1])
            cs[lag] = c
            if c > best[1]:
                best = (lag, c)
        if cs:
            # a steady rhythm matches just as well one or more periods away: among lags that are about as good as
            # the best, report the nearest to zero, and say when others tie
            ties = [l for l, c in cs.items() if c >= best[1] - 0.02]
            pick = min(ties, key=lambda l: (abs(l), -cs[l]))
            far = any(abs(l - pick) * HOP >= 0.2 for l in ties)
            out[n] = (pick * HOP, cs[pick], cs.get(0, 0.0), far)
    return out


# ---------------------------------------------------------------- names
def name_problems(path):
    """The reasons a file or folder name would not survive another system, in plain words."""
    p = Path(path)
    name = p.name
    out = []
    bad = sorted({c for c in name if c in BAD_CHARS})
    if bad:
        out.append(("chars", "has " + " ".join(repr(c) for c in bad) + " in its name (Windows refuses these, and some tools and "
                    "uploads mangle them elsewhere)"))
    if any(ord(c) < 32 for c in name):
        out.append(("chars", "has a control character in its name"))
    stem = name.rsplit(".", 1)[0].strip().lower() if "." in name else name.strip().lower()
    if stem in RESERVED:
        out.append(("reserved", f"is called {stem.upper()}, a name Windows keeps for itself"))
    if name != name.strip() or name.rstrip().endswith(".") or p.stem != p.stem.strip():
        out.append(("trailing", "ends or begins with a space or a dot (Windows drops it, and the file no longer matches)"))
    if len(name.encode("utf-8")) > 200:
        out.append(("long", f"has a very long name ({len(name.encode('utf-8'))} bytes; most systems stop at 255)"))
    try:
        full = str(p.resolve())
    except OSError:                                     # a name the system itself refuses to look up
        full = str(p)
    if len(full) > 240:
        out.append(("path", f"has a very long path ({len(full)} characters; Windows stops at 260)"))
    if any(ord(c) > 127 for c in name):
        out.append(("accents", "has accents or symbols in its name (fine on modern systems; older tools and zip files garble them)"))
    return out


def safe_name(name):
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = "".join("-" if c in BAD_CHARS or ord(c) < 32 else c for c in stem).strip().rstrip(". ")
    stem = stem or "file"
    if stem.lower() in RESERVED:
        stem += "-1"
    if len(stem.encode("utf-8")) > 100:
        stem = stem.encode("utf-8")[:100].decode("utf-8", "ignore").rstrip()
    return stem + ("." + ext if ext else "")


# ---------------------------------------------------------------- what sits in a folder or a project
def folder_files(path, recursive=False):
    p = Path(path)
    it = p.rglob("*") if recursive else p.iterdir()
    return sorted(x for x in it if x.is_file() and x.suffix.lower() in dsp.AUDIO_EXT and not x.name.startswith("."))


def project_sources(path):
    """(project, {path: [track names]}, [(track, clip name, path, where)] for files that are not there)."""
    from hypnomix import project as PJ
    proj = PJ.load(path)
    uses, missing = collections.OrderedDict(), []
    for t in proj.tracks:
        for c in t.clips:
            for tk in c.takes:
                if tk.kind != "audio" or tk.path is None:
                    continue
                for pth in [tk.path] + list(tk.extra_paths or []):
                    uses.setdefault(str(pth), [])
                    if t.name not in uses[str(pth)]:
                        uses[str(pth)].append(t.name)
                    if not Path(pth).exists():
                        missing.append((t.name, c.name, str(pth), proj.where(c.start) if hasattr(proj, "where") else ""))
    if PJ.daw_of(path) == "live":                  # Live's own way of finding files (absolute path, then next to the set)
        try:
            from hypnomix.session import refs
            _, miss, _ = refs.check(path)
            known = {Path(m[2]).name for m in missing}
            for trk, paths in miss.items():
                for pth in sorted(paths):
                    if Path(pth).name not in known:
                        missing.append((trk, "", pth, ""))
                        uses.setdefault(pth, [])
                        if trk not in uses[pth]:
                            uses[pth].append(trk)
        except Exception:
            pass
    return proj, uses, missing


# ---------------------------------------------------------------- findings
def fnd(kind, severity, track, problem, fix, applies="manual", where="", **extra):
    d = dict(kind=kind, severity=severity, track=track, where=where, problem=problem, fix=fix, applies=applies)
    d.update(extra)
    return d


def plural(n, one, many=None):
    return f"{n} {one if n == 1 else (many or one + 's')}"


def listing(names, n=6):
    names = list(names)
    return ", ".join(names[:n]) + (f" and {len(names) - n} more" if len(names) > n else "")


def mode_of(values):
    c = collections.Counter(values)
    top = c.most_common()
    if len(top) > 1 and top[0][1] == top[1][1]:
        return None, c
    return top[0][0], c


def check_files(files, proj_sr=None, folder=True, tol=0.05, max_lag=5.0, uses=None):
    """Every finding about a set of inspected files. `files`: the list from inspect()."""
    out = []
    ok = [f for f in files if f["readable"]]
    for f in files:
        if not f["readable"]:
            out.append(fnd("unreadable", "high", f["name"], f"could not be read ({f['error']})",
                           "export it again as WAV, or find the original; a file nothing can open cannot be mixed"))
    # sample rate and bit depth
    for key, label, sev, fixword in (("sr", "sample rate", "medium", "{v} Hz"), ("bits", "bit depth", "low", "{v}-bit")):
        vals = [f.get(key) for f in ok if f.get(key) is not None and not f.get("lossy")] if key == "bits" else [f[key] for f in ok]
        if len(set(vals)) < 2:
            continue
        top, c = mode_of(vals)
        fmt = (lambda v: f"{v} Hz") if key == "sr" else (lambda v: f"{v}-bit")
        if top is None:
            groups = ", ".join(f"{fmt(v)}: {n}" for v, n in sorted(c.items(), key=lambda x: str(x[0])))
            out.append(fnd(f"mixed-{key}", sev, f"{len(vals)} files", f"mixed {label}s with no majority ({groups})",
                           f"pick one {label} for the project and convert the rest: `hypnomix prep FOLDER --plan` makes "
                           "every stem one rate and 24-bit (its format step) into new files"))
            continue
        for v, n in c.items():
            if v == top:
                continue
            who = [f["name"] for f in ok if f.get(key) == v and not (key == "bits" and f.get("lossy"))]
            out.append(fnd(f"mixed-{key}", sev, plural(len(who), "file") + f" at {fmt(v)}", f"{plural(len(who), 'file')} "
                           f"{'is' if len(who) == 1 else 'are'} {fmt(v)}, the other {c[top]} {'is' if c[top] == 1 else 'are'} {fmt(top)}: {listing(who)}",
                           f"convert {'it' if len(who) == 1 else 'them'} to {fmt(top)} (`hypnomix prep FOLDER --plan`: its format "
                           "step does it into new files), or export again at the project's setting", where=listing(who, 12), files=who))
    if proj_sr:
        off = [f["name"] for f in ok if f["sr"] != proj_sr]
        if off and not any(x["kind"] == "mixed-sr" for x in out):
            out.append(fnd("project-rate", "low", plural(len(off), "file"), f"the project runs at {proj_sr} Hz and {listing(off)} "
                           f"{'is' if len(off) == 1 else 'are'} not: the DAW converts on playback",
                           "fine for a draft; for the final mix convert those files first (`prep`'s format step)", files=off))
    # lengths and starts: a folder of stems only
    if folder and len(ok) >= 3:
        durs = [f["dur"] for f in ok if f["dur"] > 0]
        med = float(np.median(durs)) if durs else 0
        for f in ok:
            d = f["dur"] - med
            if abs(d) > tol:
                out.append(fnd("length", "medium", f["name"], f"is {abs(d):.2f} s {'longer' if d > 0 else 'shorter'} than the middle "
                               f"stem ({med:.2f} s): {f['dur']:.2f} s",
                               "stems of one song should all start at the same point and have the same length: export this one again "
                               "from the same start and to the same end (or `hypnomix prep FOLDER --plan` pads or trims them to match)"))
        envs = {f["name"]: f.get("env") for f in ok}
        for n, (lag, c_best, c0, repeats) in lags(envs, max_lag).items():
            # musical stems play different rhythms, so a weak match is not evidence: it takes a good match that is clearly
            # better than lined up; and only a near-perfect one is called certain
            if abs(lag) >= 0.1 and c_best >= 0.6 and c_best - c0 >= 0.3:
                sure = c_best >= 0.9
                out.append(fnd("start", "high" if sure else "medium", n,
                               f"{'does not start together' if sure else 'may not start together'} with the others: its sound arrives about "
                               f"{abs(lag):.2f} s {'ahead of' if lag > 0 else 'behind'} theirs (envelopes match best at {lag:+.2f} s, "
                               f"correlation {c_best:.2f} against {c0:.2f} when lined up"
                               + ("; the rhythm repeats, so it could also be a whole number of beats off" if repeats else "")
                               + ("" if sure else "; check by ear") + ")",
                               "export it again from the same start point as the others (bar 1), or line it up by ear: "
                               "stems that do not start together will not play together"))
    # duplicates
    by_hash = collections.defaultdict(list)
    for f in ok:
        if f.get("hash"):
            by_hash[f["hash"]].append(f["name"])
    for h, names in by_hash.items():
        if len(names) > 1:
            out.append(fnd("duplicate", "low", names[0], f"{listing(names)} are exactly the same audio",
                           "keep one and delete the others (or check you did not export the same track twice); nothing was deleted",
                           files=names))
    # per file
    for f in ok:
        n = f["name"]
        if f.get("empty"):
            out.append(fnd("silent", "medium", n, "has no audio in it (zero length)", "export it again; check the track and the range"))
            continue
        if f["silent"]:
            out.append(fnd("silent", "medium", n, f"is silent (loudest sample {f['peak_db']:.0f} dBFS)",
                           "check the export (wrong track, muted, or an empty track on purpose); leave it out of the mix if it is empty"))
            continue
        if f["quiet"]:
            out.append(fnd("quiet", "low", n, f"is nearly silent (loudest sample {f['peak_db']:.0f} dBFS)",
                           "check it is meant to be this quiet: raising it also raises its noise"))
        if f["fake_stereo"]:
            out.append(fnd("fake-stereo", "low", n, "is a stereo file whose left and right are identical: really mono",
                           "keep it as a mono file (half the size, pans as one source): `prep`'s mono step writes a mono copy",
                           applies="audio", plan=dict(tool="prep", file=f["path"], step="mono")))
        if f["one_empty"]:
            out.append(fnd("one-channel", "medium", n, "has sound in one channel only (the other is empty)",
                           "export it again as mono, or check which side the mic was patched to"))
        dc = max(f["dc"]) if f["dc"] else 0
        if dc > 0.003:
            out.append(fnd("dc", "low", n, f"has a DC offset of {dc * 100:.1f}% of full scale (it eats headroom and clicks at edits)",
                           "remove it with a 25 Hz high-pass: `prep`'s rumble step writes a new file",
                           applies="audio", plan=dict(tool="prep", file=f["path"], step="rumble")))
        if f["clipped"] >= 5:
            out.append(fnd("clipped", "high" if f["clipped"] >= 50 else "medium", n,
                           f"is already clipped: {f['clipped']} runs of flat-topped peaks in the file itself",
                           "re-record or re-export at a lower level if you can; otherwise `prep`'s declip step rebuilds the flattened "
                           "tops into a new file (a repair, not a cure)", applies="audio",
                           plan=dict(tool="prep", file=f["path"], step="declip")))
        if f.get("lossy"):
            pass
    lossy = [f for f in ok if f.get("lossy")]
    if lossy:
        out.append(fnd("lossy", "medium", plural(len(lossy), "lossy file"),
                       f"{listing(f['name'] for f in lossy)} {'is' if len(lossy) == 1 else 'are'} compressed (mp3, aac or similar): "
                       "the quality is already spent, and every edit and re-encode makes it worse",
                       "find the original WAV or FLAC and use that; mixing from mp3 is fine for a sketch, not for a release",
                       files=[f["name"] for f in lossy]))
    monos = [f["name"] for f in ok if f.get("channels") == 1]
    if monos and len(monos) < len(ok):
        out.append(fnd("mono-files", "info", plural(len(monos), "mono file"), f"{plural(len(monos), 'file')} {'is' if len(monos) == 1 else 'are'} "
                       f"mono: {listing(monos)}", "nothing to do: single mics are mono; you pan them in the mix", files=monos))
    return out


KIND_TEXT = {"chars": "characters other systems refuse in their names", "reserved": "a name Windows keeps for itself",
             "trailing": "a space or dot at the start or end of the name", "long": "a very long name",
             "path": "a very long path", "accents": "accents or symbols in the name"}


def check_names(paths, project_path=None):
    """Name problems, grouped by the kind of problem so one review item covers many files."""
    out = []
    groups = collections.defaultdict(list)
    for p in paths:
        for kind, why in name_problems(p):
            groups[kind].append((Path(p).name, why))
    sev = {"chars": "medium", "reserved": "medium", "trailing": "medium", "long": "medium", "path": "medium", "accents": "info"}
    where = (". In a project, rename in the DAW's media list (or collect the files) so the links follow; nothing was renamed"
             if project_path else ". Nothing was renamed")
    for kind, rows in groups.items():
        names = sorted({r[0] for r in rows})
        if kind == "path":
            fix = "move the folder somewhere with a shorter path" + where
        elif kind == "accents":
            fix = "nothing to do unless the files will travel to older systems; then rename them" + where
        else:
            fix = "rename " + "; ".join(f"{n!r} to {safe_name(n)!r}" for n in names[:4]) + (" …" if len(names) > 4 else "") + where
        problem = (f"{names[0]} {rows[0][1]}" if len(names) == 1
                   else f"{len(names)} files have {KIND_TEXT[kind]}: {listing(names)}")
        out.append(fnd(f"name-{kind}", sev[kind], names[0] if len(names) == 1 else f"{len(names)} names", problem, fix, files=names))
    low = collections.defaultdict(set)
    for p in paths:
        low[Path(p).name.lower()].add(Path(p).name)
    for v in low.values():
        if len(v) > 1:
            c = sorted(v)
            out.append(fnd("name-case", "medium", c[0], f"{' and '.join(c)} differ only by capital letters (they overwrite each "
                           "other on macOS and Windows)", "rename one of them", files=c))
    return out


# ---------------------------------------------------------------- the report
def files_table(files):
    L = ["| file | format | sample rate | channels | length | loudest | notes |", "|---|---|---|---|---|---|---|"]
    for f in files:
        if not f["readable"]:
            L.append(f"| {f['name']} | - | - | - | - | - | **unreadable** |")
            continue
        bits = f"{f['bits']}-bit" if isinstance(f.get("bits"), int) else (f["bits"] or "") if f.get("bits") else "compressed"
        notes = [k for k, v in (("silent", f.get("silent")), ("nearly silent", f.get("quiet")), ("fake stereo", f.get("fake_stereo")),
                                ("clipped", f.get("clipped", 0) >= 5), ("lossy", f.get("lossy"))) if v]
        L.append(f"| {f['name']} | {f.get('ext', '').lstrip('.')} {bits} | {f['sr']} | {f['channels']} | {f['dur']:.2f} s | "
                 f"{f.get('peak_db', '-')} dBFS | {', '.join(notes)} |")
    return L


def report(source, files, findings, notes, kind):
    n_by = collections.Counter(f["severity"] for f in findings)
    L = [f"# Preflight: {Path(source).name}", "",
         f"{kind}: `{source}`  ", "Measured, not heard. Nothing was changed, renamed or deleted.", ""]
    L += [f"**{len(files)} audio file(s), {len(findings)} finding(s):** {n_by['high']} high, {n_by['medium']} medium, "
          f"{n_by['low']} low, {n_by['info']} info", ""]
    if notes:
        L += [f"- {x}" for x in notes] + [""]
    if not findings:
        L += ["Nothing to fix: the files look consistent and ready to work on.", ""]
    for i, f in enumerate(findings, 1):
        L += [f"### {i}. [{f['severity']}] {f['kind']}: {f['track']}",
              f"- problem: {f['problem']}", f"- what to do: {f['fix']}"]
        if f.get("plan"):
            L.append(f"- with `--plan` this becomes a `prep` step ({f['plan']['step']}) you can approve")
        L.append("")
    L += ["## Every file", ""] + files_table(files) + [""]
    return "\n".join(L)


def analyse(source, recursive=False, tol=0.05, max_lag=5.0, progress=True):
    """(files, findings, notes, kind) for a folder or a project. The whole check, no output written."""
    from hypnomix import project as PJ
    src = Path(source).expanduser()
    if not src.exists():
        raise SystemExit(f"not found: {source}")
    notes = []
    if src.is_dir() and PJ.daw_of(src) is None:
        paths = folder_files(src, recursive)
        if not paths:
            raise SystemExit(f"no audio files in {source}")
        kind, proj_sr, folder, uses, missing = "Folder", None, True, {}, []
        names_to_check = list(paths)
    elif PJ.daw_of(src) is not None:
        try:
            proj, uses, missing = project_sources(src)
        except Exception as e:
            what = {"reaper": "a REAPER project", "live": "an Ableton Live set", "ardour": "an Ardour session"}.get(PJ.daw_of(src), "a project")
            why = str(e).strip().splitlines()[-1][:100] if str(e).strip() else type(e).__name__
            raise SystemExit(f"{src.name}: not {what} I can read" if why.startswith("not a") else f"{src.name}: cannot be read as {what} ({why})")
        present = [Path(p) for p in uses if Path(p).exists()]
        paths = sorted(present, key=lambda p: str(p))
        kind, proj_sr, folder = {"reaper": "REAPER project", "live": "Live set", "ardour": "Ardour session"}[PJ.daw_of(src)], proj.sample_rate, False
        notes.append(f"{len(uses)} source file(s) used by the project, {len(missing)} place(s) where one is missing")
        notes.append("lengths and starts are not compared: the clips of a project are placed by their positions")
        names_to_check = list(uses) + [str(src)]
    else:
        raise SystemExit(f"{src.name}: give a folder of audio, or a .als, .rpp or .ardour project")
    files = []
    for k, p in enumerate(paths, 1):
        if progress:
            print(f"reading {p.name} ({k}/{len(paths)}) …", file=sys.stderr)
        files.append(inspect(p, envelope=folder))
    findings = check_files(files, proj_sr=proj_sr, folder=folder, tol=tol, max_lag=max_lag)
    seen = set()
    for track, clip, pth, where in missing:
        if pth in seen:
            continue
        seen.add(pth)
        users = uses.get(pth, [track])
        findings.append(fnd("missing", "high", Path(pth).name, f"is used by {listing(users)} and is not there: {pth}",
                            "find the file again before anything else (REAPER and Ardour offer to search when the project opens; "
                            "in Live use Manage Files or Locate); nothing was searched for or changed", where=where))
    findings += check_names([Path(p) for p in names_to_check], project_path=None if folder else src)
    findings.sort(key=lambda f: (SEV.get(f["severity"], 9), f["kind"], f["track"]))
    for f in files:
        f.pop("env", None)
    return files, findings, notes, kind


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix preflight", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="a folder of audio, or a .als / .rpp / .ardour project")
    ap.add_argument("--recursive", action="store_true", help="a folder: also the folders inside it")
    ap.add_argument("--length-tolerance", type=float, default=0.05, help="seconds two stems may differ in length (0.05)")
    ap.add_argument("--max-lag", type=float, default=5.0, help="how far, in seconds, to look for a stem that starts early or late (5)")
    ap.add_argument("--plan", nargs="?", const=True, metavar="SCAN_DIR",
                    help="put every finding into a scan folder for the normal review (nothing is changed)")
    ap.add_argument("--out", help="where PREFLIGHT.md goes (default hypnomix-out/preflight; with --plan, the scan folder)")
    a = ap.parse_args(argv)
    files, findings, notes, kind = analyse(a.source, a.recursive, a.length_tolerance, a.max_lag)
    text = report(a.source, files, findings, notes, kind)
    src = Path(a.source).expanduser()
    if a.plan:
        from hypnomix.workflow import plan as P
        od = P.scan_dir(a.plan if isinstance(a.plan, str) else a.out, src, " preflight")
        od.mkdir(parents=True, exist_ok=True)
        (od / "PREFLIGHT.md").write_text(text)
        notes2 = notes + [f"preflight: {len(files)} file(s) read. Findings that `prep` can repair are planned as prep steps; "
                          "the others are things to do yourself. Full report: PREFLIGHT.md"]
        for f in findings:
            f.setdefault("where", "")
        P.write(od, "preflight", src, findings, notes2)
        print(text)
        return
    od = out_at(a.out, "preflight")
    (od / "PREFLIGHT.md").write_text(text)
    (od / "preflight.json").write_text(json.dumps(dict(source=str(src), kind=kind, files=files, findings=findings, notes=notes),
                                                 indent=1, default=str))
    print(text)
    print(f"report: {od / 'PREFLIGHT.md'}")
    if findings:
        print("add --plan to put these into a scan folder for review (nothing is changed either way).")
    if any(f["severity"] == "high" for f in findings):
        sys.exit(1)


if __name__ == "__main__":
    main()
