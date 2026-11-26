#!/usr/bin/env python3
"""Turn a finished master into the folder you upload: the files a distributor asks for, tagged, and a
plain-words report on every one of them.

What it writes (always into a NEW folder "<Artist> - <Title>/", and it refuses if that folder exists):
  the master as 24-bit WAV     the file you gave it, byte for byte when it is already a 24-bit WAV; never
                               re-processed
  a 16-bit / 44.1 kHz WAV      made from the unrounded master with the same dither `master` uses (resampled
                               first if the master is not 44.1 kHz)
  MP3 320 and AAC 256 (.m4a)   encoded from the master, with title, artist, album, track, year, genre, ISRC
                               and the cover embedded (MP3 and FLAC carry the ISRC; AAC .m4a has no standard
                               place for it, so it is kept in release.json)
  FLAC (if you ask)            the 24-bit master, losslessly, with the same tags and cover
  the cover, release.json      a copy of your cover as it is, and the metadata you gave
  RELEASE.md                   for every file: loudness, true peak and the release checks (`hypnomix qc`);
                               for the lossy files, the true peak AFTER decoding them again, which is what a
                               listener's player actually plays

If a lossy file overshoots 0 dBTP after decoding, RELEASE.md says by how much and how far lower the master's
ceiling would have to be. The audio is never changed to hide it: that is a mastering decision, and yours.

Read-only form: `--check` runs the release checks on the master, checks the cover (square, at least 3000 px,
JPEG or PNG), checks the ISRC is shaped like one, and prints exactly what would be written. It writes nothing.
A package written with a cover that fails those checks still gets written, and says so on the console, in
RELEASE.md and in release.json (cover_warnings).

Never: modify the master or the cover, write over an existing folder, process the audio of the 24-bit file.
Needs ffmpeg (already required) and ffprobe.

Usage:
    hypnomix release MASTER.wav --title T --artist A [--album ALBUM] [--track N] [--year 2026] [--genre G]
                     [--isrc CCXXXYYNNNNN] [--art cover.jpg] [--meta release.json]
                     [--formats wav24,wav16,mp3,aac,flac] [--dither tpdf|shaped|off] [--target -14]
                     [--out DIR] [--check]

    --formats   which files to make (default wav24,wav16,mp3,aac; add flac if you want it)
    --meta      read the same details from a release.json (a file this command wrote works); options given on the
                command line win
    --out       the folder to create the "<Artist> - <Title>" folder in (default hypnomix-out/release)
    --target    the loudness the release checks compare with (default -14 LUFS)
"""
import argparse, datetime, hashlib, json, math, re, shutil, subprocess, sys, tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix.core import dsp, paths
from hypnomix.engineer import qc

FORMATS = ("wav24", "wav16", "mp3", "aac", "flac")
DEFAULT_FORMATS = ("wav24", "wav16", "mp3", "aac")
META_KEYS = ("title", "artist", "album", "track", "year", "genre", "isrc", "art")
LOSSY_EXT = (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wma")
ISRC_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}[0-9]{2}[0-9]{5}$")
MIN_COVER = 3000
WHAT = {"wav24": "24-bit WAV, the master as it is", "wav16": "16-bit / 44.1 kHz WAV, dithered",
        "mp3": "MP3 320 kbit/s", "aac": "AAC 256 kbit/s (.m4a)", "flac": "FLAC, lossless, 24-bit"}


class ReleaseError(Exception):
    """Something the person has to fix (bad option, existing folder, unreadable cover). Message is plain words."""


# ---------------------------------------------------------------- small helpers
def safe_name(s):
    """A file or folder name from free text: no slashes or characters Windows refuses, no trailing dots or spaces."""
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", str(s)).strip().strip(".").strip()
    return s or "untitled"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def normalise_isrc(text):
    """'us-rc1-76-07839' -> 'USRC17607839' (None when it is not shaped like an ISRC)."""
    s = re.sub(r"[\s-]", "", str(text or "")).upper()
    return s if ISRC_RE.match(s) else None


def pretty_isrc(isrc):
    return f"{isrc[:2]}-{isrc[2:5]}-{isrc[5:7]}-{isrc[7:]}"


def mmss(sec):
    return f"{int(sec // 60)}:{sec % 60:04.1f}"


def parse_formats(text):
    out = []
    for f in re.split(r"[,\s]+", str(text or "").strip().lower()):
        if not f:
            continue
        if f not in FORMATS:
            raise ReleaseError(f"unknown format {f!r}: choose from {', '.join(FORMATS)}")
        if f not in out:
            out.append(f)
    if not out:
        raise ReleaseError("--formats is empty: choose from " + ", ".join(FORMATS))
    return out


def load_meta(args_meta, meta_file=None):
    """The release details: from --meta release.json if given, then the command line on top. Relative `art`
    in the file is taken relative to that file."""
    meta = {}
    if meta_file:
        p = Path(meta_file).expanduser()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ReleaseError(f"can't read --meta {meta_file}: {e}")
        if not isinstance(data, dict):
            raise ReleaseError(f"--meta {meta_file} must hold a JSON object like {{\"title\": ..., \"artist\": ...}}")
        meta = {k: data[k] for k in META_KEYS if data.get(k) not in (None, "")}
        if meta.get("art") and not Path(str(meta["art"])).expanduser().is_absolute():
            meta["art"] = str((p.parent / str(meta["art"])).resolve())
    for k, v in args_meta.items():
        if v not in (None, ""):
            meta[k] = v
    return {k: str(v).strip() for k, v in meta.items()}


def meta_problems(meta):
    """[(name, status, detail)] for the details themselves: required fields, ISRC shape, year, track."""
    res = []
    for k in ("title", "artist"):
        res.append((k.capitalize(), "PASS" if meta.get(k) else "FAIL", meta.get(k) or "missing (give --" + k + ")"))
    if meta.get("isrc"):
        n = normalise_isrc(meta["isrc"])
        res.append(("ISRC", "PASS" if n else "FAIL",
                    pretty_isrc(n) if n else f"{meta['isrc']!r} is not an ISRC: 2 letters (country), 3 letters or digits "
                                             "(registrant), 2 digits (year), 5 digits, e.g. US-RC1-76-07839"))
    else:
        res.append(("ISRC", "WARN", "none given: distributors can assign one, but add yours here if you have it"))
    if meta.get("year"):
        ok = re.fullmatch(r"\d{4}", meta["year"]) and 1900 <= int(meta["year"]) <= datetime.date.today().year + 1
        res.append(("Year", "PASS" if ok else "FAIL", meta["year"] if ok else f"{meta['year']!r} is not a year like 2026"))
    if meta.get("track"):
        ok = re.fullmatch(r"\d{1,3}(/\d{1,3})?", meta["track"])
        res.append(("Track number", "PASS" if ok else "FAIL", meta["track"] if ok else f"{meta['track']!r} is not a number like 3 or 3/12"))
    return res


# ---------------------------------------------------------------- the cover
def probe_image(path):
    """(codec, width, height) of an image file by ffprobe, or None if it can't be read as an image."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=codec_name,width,height", "-of", "json", "-i", str(path)],
                           capture_output=True, text=True, timeout=60)
        s = json.loads(r.stdout or "{}").get("streams") or []
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if not s or not s[0].get("width"):
        return None
    return s[0].get("codec_name"), int(s[0]["width"]), int(s[0]["height"])


def cover_checks(path):
    """[(name, status, detail)]: readable, JPEG or PNG, square, at least 3000 px. (Empty list: no cover given.)"""
    if not path:
        return [("Cover", "WARN", "no cover given (--art): distributors need a square JPEG or PNG, 3000 px or more")]
    p = Path(path).expanduser()
    if not p.is_file():
        return [("Cover", "FAIL", f"{p} not found")]
    info = probe_image(p)
    if info is None:
        return [("Cover", "FAIL", f"{p.name} could not be read as an image")]
    codec, w, h = info
    kind = {"mjpeg": "JPEG", "png": "PNG"}.get(codec)
    res = [("Cover format", "PASS" if kind else "FAIL",
            kind or f"{codec}: use a JPEG or PNG"),
           ("Cover shape", "PASS" if w == h else "FAIL", f"{w} x {h}" + ("" if w == h else " (must be square)")),
           ("Cover size", "PASS" if min(w, h) >= MIN_COVER else "FAIL",
            f"{min(w, h)} px" + ("" if min(w, h) >= MIN_COVER else f" (at least {MIN_COVER} px; most distributors reject smaller)"))]
    return res


# ---------------------------------------------------------------- measuring files as written
def decode_to_float(path, td):
    """Decode any audio file (mp3, m4a, flac, wav) to a float WAV in `td` and load it: what a player plays."""
    dec = Path(td) / "decoded.wav"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-vn", "-c:a", "pcm_f32le", str(dec)],
                       capture_output=True, text=True)
    if r.returncode or not dec.exists():
        raise ReleaseError(f"could not decode {Path(path).name} again: {r.stderr.strip()[-200:]}")
    return dsp.load(dec)


def measure(path, decoded=False):
    """{lufs, true_peak} of the file as written. decoded=True decodes it through ffmpeg first (lossy files)."""
    if decoded:
        with tempfile.TemporaryDirectory() as td:
            y, sr = decode_to_float(path, td)
    else:
        y, sr = dsp.load(path)
    return dict(lufs=round(dsp.lufs(y, sr), 2), true_peak=round(dsp.true_peak(y, sr), 2), sr=sr)


def qc_summary(results):
    fails = [(n, d) for n, s, d in results if s == "FAIL"]
    warns = [(n, d) for n, s, d in results if s == "WARN"]
    status = "FAIL" if fails else "WARN" if warns else "PASS"
    return dict(status=status, fails=[f"{n}: {d}" for n, d in fails], warns=[f"{n}: {d}" for n, d in warns])


# ---------------------------------------------------------------- the plan
def master_info(path):
    p = Path(path)
    if not p.is_file():
        raise ReleaseError(f"{p} not found")
    if p.suffix.lower() in LOSSY_EXT:
        raise ReleaseError(f"{p.name} is a lossy file ({p.suffix}). Give the lossless master (WAV, AIFF or FLAC): "
                           "a release made from an MP3 or AAC has the encoder's damage in every file.")
    try:
        i = sf.info(str(p))
    except Exception as e:
        raise ReleaseError(f"can't read {p.name} as audio: {e}")
    return dict(path=str(p), sr=i.samplerate, channels=i.channels, subtype=i.subtype, format=i.format,
                seconds=i.frames / i.samplerate)


def plan_files(info, meta, formats, folder):
    """[(fmt, filename, plain-words how)] and notes, without touching anything."""
    base = f"{safe_name(meta['artist'])} - {safe_name(meta['title'])}"
    names = {"wav24": f"{base} (24-bit).wav", "wav16": f"{base} (16-bit).wav", "mp3": f"{base}.mp3",
             "aac": f"{base}.m4a", "flac": f"{base}.flac"}
    sr, sub = info["sr"], info["subtype"]
    out = []
    for f in formats:
        how = WHAT[f]
        if f == "wav24":
            if sub == "PCM_24" and info["format"] == "WAV":
                how += ": a byte-for-byte copy"
            elif sub == "PCM_16":
                how += ": your 16-bit master widened to 24-bit (exact, no processing)"
            else:
                how += f": your {sub} master written as 24-bit with TPDF dither (it was not 24-bit)"
        elif f == "wav16":
            if sr != 44100:
                how += f", resampled from {sr} Hz first"
            elif sub == "PCM_16" and info["format"] == "WAV":
                how += ": your master is already 16-bit, so this is a copy and is not dithered again"
        elif f in ("mp3", "aac") and sr > 48000:
            how += f", sample rate brought down from {sr} Hz to 44.1 kHz"
        out.append((f, names[f], how))
    return out


def folder_for(meta, out_parent, create=False):
    parent = Path(out_parent).expanduser() if out_parent else paths.OUT / "release"
    if create:
        parent.mkdir(parents=True, exist_ok=True)
    return parent / f"{safe_name(meta['artist'])} - {safe_name(meta['title'])}"


def check_all(master, meta, formats, out_parent=None, target=-14.0):
    """The read-only pass. Returns dict(info, meta_res, cover_res, qc_res, files, folder, exists, ok)."""
    info = master_info(master)
    meta_res = meta_problems(meta)
    cover_res = cover_checks(meta.get("art"))
    if not meta.get("title") or not meta.get("artist"):
        return dict(info=info, meta_res=meta_res, cover_res=cover_res, qc_res=[], files=[], folder=None, exists=False, ok=False)
    folder = folder_for(meta, out_parent)
    qc_res = qc.check(master, target, "streaming")
    files = plan_files(info, meta, formats, folder)
    bad = [s for _, s, _ in meta_res + qc_res if s == "FAIL"] + [s for n, s, _ in cover_res if s == "FAIL"]
    return dict(info=info, meta_res=meta_res, cover_res=cover_res, qc_res=qc_res, files=files, folder=folder,
                exists=folder.exists(), ok=not bad and not folder.exists())


MARK = {"PASS": "✓", "WARN": "!", "FAIL": "✗"}


def print_results(title, res):
    print(title)
    for name, s, d in res:
        print(f"  {MARK[s]} {name:<38} {d}")


def print_check(master, meta, formats, c):
    print(f"\nRelease check: {Path(master).name}   (read-only: nothing is written)\n")
    i = c["info"]
    print(f"master: {i['sr']} Hz, {i['subtype']}, {i['channels']} channel(s), {mmss(i['seconds'])}")
    print_results("\ndetails", c["meta_res"])
    print_results("\ncover", c["cover_res"])
    if c["qc_res"]:
        print_results("\nthe master, release checks", c["qc_res"])
    if c["folder"] is not None:
        print(f"\nWould write a new folder: {c['folder']}" + ("   <- ALREADY EXISTS: it would refuse, pick another --out" if c["exists"] else ""))
        for f, name, how in c["files"]:
            print(f"  {name}\n      {how}")
        if meta.get("art") and Path(meta["art"]).is_file():
            print(f"  cover{Path(meta['art']).suffix.lower()}\n      a copy of your cover, as it is")
        print("  release.json\n      the details above")
        print("  RELEASE.md\n      per file: loudness, true peak, release checks; lossy files measured again after decoding")
        lossy = [n for f, n, _ in c["files"] if f in ("mp3", "aac")]
        if lossy:
            print("\nthe lossy files are measured after decoding when they are written, and a true peak over 0 dBTP is reported "
                  "with how much lower the master's ceiling should be. The audio is never changed to hide it.")
    fails = [n for n, s, _ in c["meta_res"] + c["cover_res"] + c["qc_res"] if s == "FAIL"]
    print("\n" + ("Ready to write." if c["ok"] else "Not ready: " + ("; ".join(fails) if fails else "the folder exists") + "."))


# ---------------------------------------------------------------- writing
def tag_args(meta, fmt):
    tags = {"title": meta.get("title"), "artist": meta.get("artist"), "album": meta.get("album"),
            "album_artist": meta.get("artist") if meta.get("album") else None,
            "track": meta.get("track"), "date": meta.get("year"), "genre": meta.get("genre")}
    isrc = normalise_isrc(meta.get("isrc"))
    if isrc and fmt == "mp3":
        tags["TSRC"] = isrc
    elif isrc and fmt == "flac":
        tags["ISRC"] = isrc
    a = ["-map_metadata", "-1"]
    for k, v in tags.items():
        if v:
            a += ["-metadata", f"{k}={v}"]
    return a


def encode(master, dest, fmt, meta, sr):
    """ffmpeg: master -> mp3 / m4a / flac with tags and the cover embedded as the front-cover picture."""
    art = meta.get("art")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(master)]
    if art:
        cmd += ["-i", str(art)]
    cmd += ["-map", "0:a"]
    if art:
        cmd += ["-map", "1:v", "-c:v", "copy", "-disposition:v:0", "attached_pic",
                "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
    if fmt == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", "320k", "-id3v2_version", "3"]
    elif fmt == "aac":
        cmd += ["-c:a", "aac", "-b:a", "256k"]
    else:
        cmd += ["-c:a", "flac", "-sample_fmt", "s32"]
    if fmt in ("mp3", "aac") and sr > 48000:
        cmd += ["-ar", "44100"]
    cmd += tag_args(meta, fmt) + [str(dest)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode or not Path(dest).exists():
        raise ReleaseError(f"ffmpeg could not write {Path(dest).name}: {r.stderr.strip()[-300:]}")


def make_wav24(master, dest, info):
    if info["subtype"] == "PCM_24" and info["format"] == "WAV":
        shutil.copyfile(master, dest)
        return "copy"
    y, sr = dsp.load(master)
    dsp.save(dest, y, sr, 24, dither=None if info["subtype"] == "PCM_16" else "tpdf")
    return "converted"


def make_wav16(master, dest, info, dither):
    if info["subtype"] == "PCM_16" and info["format"] == "WAV" and info["sr"] == 44100:
        shutil.copyfile(master, dest)
        return "copy"
    y, sr = dsp.load(master)
    if sr != 44100:
        from hypnomix.engineer.master import resample_to
        y = resample_to(y, sr, 44100)
    dsp.save(dest, y, 44100, 16, dither=dither)
    return f"{dither} dither"


def lossy_advice(tp, master_tp):
    """What to tell the person when a decoded lossy file is over 0 dBTP (None when it is fine)."""
    if tp > 0.0:
        n = math.ceil(tp * 10) / 10 + 0.1
        to = round(master_tp - n, 1) + 0.0
        return (f"overshoots 0 dBTP by {tp:.2f} dB after decoding, so a listener's player will clip it. Mastering again "
                f"with the true-peak ceiling {n:.1f} dB lower would fix it (the master measures {master_tp:+.2f} dBTP now; "
                f"about {to:+.1f} dBTP leaves room). The audio here was not changed.")
    if tp > -0.1:
        return (f"peaks at {tp:+.2f} dBTP after decoding: no headroom left. A ceiling 0.5 to 1 dB lower in the master gives it "
                "room. The audio here was not changed.")
    return None


def write_package(master, meta, formats, out_parent=None, dither="tpdf", target=-14.0, log=print):
    """Write the folder. Returns the report dict (also saved as release.json). Raises ReleaseError on a refusal."""
    info = master_info(master)
    problems = [d for n, s, d in meta_problems(meta) if s == "FAIL"]
    if problems:
        raise ReleaseError("fix the details first: " + "; ".join(problems))
    art = meta.get("art")
    if art:
        ci = probe_image(Path(art).expanduser())
        if ci is None or ci[0] not in ("mjpeg", "png"):
            raise ReleaseError(f"the cover {art} can't be embedded: it must be a JPEG or PNG image (run with --check to see)")
    final = folder_for(meta, out_parent)
    if final.exists():
        raise ReleaseError(f"{final} already exists. Nothing was written: pick another --out, or move that folder away.")
    final.parent.mkdir(parents=True, exist_ok=True)
    master = Path(master)
    before = sha256(master)
    partial = final.with_name(final.name + f".partial-{datetime.datetime.now():%H%M%S%f}")
    partial.mkdir()
    try:
        files, master_tp, master_lufs = [], None, None
        ymaster, srm = dsp.load(master)
        master_tp, master_lufs = round(dsp.true_peak(ymaster, srm), 2), round(dsp.lufs(ymaster, srm), 2)
        del ymaster
        plan = plan_files(info, meta, formats, final)
        qc_master = None
        for fmt, name, how in plan:
            dest = partial / name
            log(f"writing {name} …")
            row = dict(format=fmt, file=name, what=how)
            if fmt == "wav24":
                row["method"] = make_wav24(master, dest, info)
            elif fmt == "wav16":
                row["method"] = make_wav16(master, dest, info, dither)
            else:
                encode(master, dest, fmt, meta, info["sr"])
                row["method"] = "ffmpeg"
            row["bytes"] = dest.stat().st_size
            if fmt in ("mp3", "aac"):
                m = measure(dest, decoded=True)
                row.update(lufs=m["lufs"], true_peak_decoded=m["true_peak"], lossy=True)
                row["advice"] = lossy_advice(m["true_peak"], master_tp)
                row["qc"] = dict(status="FAIL" if m["true_peak"] > 0 else "WARN" if m["true_peak"] > -0.1 else "PASS",
                                 fails=[f"True peak after decoding: {m['true_peak']:+.2f} dBTP"] if m["true_peak"] > 0 else [],
                                 warns=[f"True peak after decoding: {m['true_peak']:+.2f} dBTP"] if 0 >= m["true_peak"] > -0.1 else [],
                                 note="lossy: the release checks that need a PCM file do not apply; loudness and the decoded true peak do")
            else:
                m = measure(dest)
                row.update(lufs=m["lufs"], true_peak=m["true_peak"], lossy=False)
                if fmt in ("wav24", "flac") and qc_master is not None:
                    row["qc"] = dict(qc_master, note="same audio as the first lossless file: the same checks apply")
                else:
                    log(f"  checking {name} …")
                    res = qc.check(dest, target, "cd" if fmt == "wav16" else "streaming")
                    row["qc"] = qc_summary(res)
                    row["qc_full"] = [dict(check=n, status=s, detail=d) for n, s, d in res]
                    if fmt in ("wav24", "flac"):
                        qc_master = row["qc"]
            files.append(row)
        if art:
            ext = Path(art).suffix.lower() or ".jpg"
            shutil.copyfile(Path(art).expanduser(), partial / f"cover{ext}")
        report = dict(
            tool="hypnomix release", written=datetime.datetime.now().isoformat(timespec="seconds"),
            title=meta["title"], artist=meta["artist"], **{k: meta[k] for k in ("album", "track", "year", "genre") if meta.get(k)},
            **({"isrc": normalise_isrc(meta["isrc"])} if meta.get("isrc") else {}),
            **({"art": f"cover{Path(art).suffix.lower() or '.jpg'}"} if art else {}),
            cover_warnings=[f"{n}: {d}" for n, st, d in cover_checks(art) if st != "PASS"],
            master=dict(file=master.name, sha256=before, sample_rate=info["sr"], subtype=info["subtype"],
                        lufs=master_lufs, true_peak=master_tp), files=files)
        (partial / "release.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
        (partial / "RELEASE.md").write_text(report_text(report, meta, dither), encoding="utf-8")
        if sha256(master) != before:                          # cannot happen; it would be a bug worth stopping for
            raise ReleaseError("the master changed while it was read: stopped")
        partial.rename(final)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    report["folder"] = str(final)
    return report


# ---------------------------------------------------------------- the report
def report_text(r, meta, dither):
    L = [f"# Release: {r['artist']} - {r['title']}", "",
         f"Written {r['written']} by `hypnomix release` from `{r['master']['file']}`. The master was only read: "
         f"its checksum is the same before and after (`{r['master']['sha256'][:16]}…`). "
         "The numbers below were measured, not listened to: play every file once before you upload.", ""]
    L += ["## Details", "", "| | |", "|---|---|"]
    for k, lab in (("title", "Title"), ("artist", "Artist"), ("album", "Album"), ("track", "Track"), ("year", "Year"),
                   ("genre", "Genre"), ("isrc", "ISRC")):
        if r.get(k):
            L.append(f"| {lab} | {pretty_isrc(r[k]) if k == 'isrc' else r[k]} |")
    L.append(f"| Cover | {r['art'] if r.get('art') else 'none'} |")
    if r.get("cover_warnings"):
        L += ["", "**Check the cover before you upload.** The package was still written (a cover is copied as it is, never changed), but a distributor may reject it:", ""]
        L += [f"- {t}" for t in r["cover_warnings"]]
    L += ["", "## Files", "", "| file | what it is | size | loudness | true peak | release checks |", "|---|---|---|---|---|---|"]
    for f in r["files"]:
        tp = f"{f['true_peak_decoded']:+.2f} dBTP after decoding" if f.get("lossy") else f"{f['true_peak']:+.2f} dBTP"
        L.append(f"| {f['file']} | {f['what']} | {f['bytes'] / 1e6:.1f} MB | {f['lufs']:.1f} LUFS | {tp} | {f['qc']['status']} |")
    L += ["", f"The master measures {r['master']['lufs']:.1f} LUFS and {r['master']['true_peak']:+.2f} dBTP.", ""]

    L += ["## What each check found", ""]
    for f in r["files"]:
        q = f["qc"]
        L.append(f"### {f['file']}: {q['status']}")
        if q.get("note"):
            L.append(f"_{q['note']}_")
        L.append("")
        if not q["fails"] and not q["warns"]:
            L.append("Nothing to flag.")
        for t in q["fails"]:
            L.append(f"- FAIL {t}")
        for t in q["warns"]:
            L.append(f"- WARN {t}")
        L.append("")

    lossy = [f for f in r["files"] if f.get("lossy")]
    if lossy:
        L += ["## After the lossy encode", "",
              "Every MP3 and AAC file is decoded again, the way a player decodes it, and measured. Encoding can push a peak "
              "that was just under 0 dBTP over it, and a listener hears that as a crackle.", ""]
        for f in lossy:
            L.append(f"- **{f['file']}**: {f['true_peak_decoded']:+.2f} dBTP after decoding"
                     + (f". It {f['advice']}" if f.get("advice") else ": fine, with headroom."))
        if any(f.get("advice") and f["true_peak_decoded"] > 0 for f in lossy):
            L += ["", "Nothing was done to the audio to hide this. Lowering the master's ceiling and releasing again is a "
                      "mastering call (`hypnomix master --ceiling`); this command only reports it."]
        L.append("")
    L += ["## Notes", ""]
    if any(f["format"] == "wav16" for f in r["files"]):
        w = next(f for f in r["files"] if f["format"] == "wav16")
        L.append(f"- The 16-bit file: {w['method']}, from the unrounded master (the same dither `hypnomix master --cd` uses, "
                 f"`{dither}` here), so the rounding happens once.")
    if any(f["format"] == "aac" for f in r["files"]) and r.get("isrc"):
        L.append("- AAC (.m4a) has no standard ISRC tag, so the ISRC is in the MP3, the FLAC and release.json, not the .m4a.")
    if any(f["format"] in ("wav24", "wav16") for f in r["files"]):
        L.append("- WAV files carry no tags or cover; the details are in release.json and the file names.")
    L += ["- The cover is a copy of your file, never re-saved.", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- command line
def main():
    ap = argparse.ArgumentParser(prog="hypnomix release", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("master")
    ap.add_argument("--title"); ap.add_argument("--artist"); ap.add_argument("--album")
    ap.add_argument("--track"); ap.add_argument("--year"); ap.add_argument("--genre"); ap.add_argument("--isrc")
    ap.add_argument("--art", help="cover image: square, 3000 px or more, JPEG or PNG")
    ap.add_argument("--meta", help="a release.json with the same details")
    ap.add_argument("--formats", default=",".join(DEFAULT_FORMATS), help="wav24,wav16,mp3,aac,flac (default %(default)s)")
    ap.add_argument("--dither", choices=["tpdf", "shaped", "off"], default="tpdf", help="for the 16-bit file (default tpdf, as master)")
    ap.add_argument("--target", type=float, default=-14.0, help="loudness the release checks compare with")
    ap.add_argument("--out", help="folder to create the release folder in (default hypnomix-out/release)")
    ap.add_argument("--check", action="store_true", help="read-only: run the checks and print what would be written")
    a = ap.parse_args()
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            sys.exit(f"hypnomix release: {tool} is not installed, and the MP3 and AAC files and the cover check need it "
                     "(run `hypnomix doctor`; on a Mac: brew install ffmpeg)")
    try:
        formats = parse_formats(a.formats)
        meta = load_meta({k: getattr(a, k) for k in META_KEYS}, a.meta)
        if not meta.get("title") or not meta.get("artist"):
            miss = [k for k in ("title", "artist") if not meta.get(k)]
            raise ReleaseError("missing " + " and ".join("--" + k for k in miss) + " (or give them in --meta release.json)")
        if a.check:
            c = check_all(a.master, meta, formats, a.out, a.target)
            print_check(a.master, meta, formats, c)
            sys.exit(0 if c["ok"] else 1)
        c_meta = [d for n, s, d in meta_problems(meta) if s == "FAIL"]
        if c_meta:
            raise ReleaseError("fix the details first: " + "; ".join(c_meta))
        r = write_package(a.master, meta, formats, a.out, a.dither, a.target)
    except ReleaseError as e:
        sys.exit(f"hypnomix release: {e}")
    print(f"\nwrote {r['folder']}")
    for f in r["files"]:
        tp = f.get("true_peak_decoded", f.get("true_peak"))
        print(f"  {f['file']:<48} {f['lufs']:.1f} LUFS  {tp:+.2f} dBTP{' (decoded)' if f.get('lossy') else ''}  checks: {f['qc']['status']}")
        if f.get("advice"):
            print(f"      ! {f['advice']}")
    for t in r.get("cover_warnings") or []:
        print(f"  ! cover, {t}")
    print("  RELEASE.md and release.json: the full report")


if __name__ == "__main__":
    main()
