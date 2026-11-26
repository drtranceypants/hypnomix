"""Import a project from another DAW into a NEW HypnoMix DAW session folder. The project is only read.

    hypnomix import PROJECT OUTDIR [--sr 48000] [--from KIND] [--allow-outside]

PROJECT is any of these (the kind is found from the file itself, or named with --from):

  live        a .als set                                  -> hypnomix als2ardour's full import
  logicx      a .logicx project (a folder; a .band too)   read natively (decoded from packages saved by version 10.7)
  ptx         a .ptx / .ptf / .pts session                read by a reader that comes with the HypnoMix DAW add-on,
                                                          which is not available yet: until then this kind cannot run
  dawproject  a .dawproject file: the open project format several DAWs save and open
  reaper      a .rpp project
  aaf         an .aaf export: a project exchange file some DAWs and video editors can write. Read by the same
              add-on as .ptx (not available yet)

OUTDIR becomes the session folder (it must not exist yet, or be empty, and must not be inside the project). The
audio is copied in; nothing points back into the old project. For every kind but .als only audio inside the
project is taken (--allow-outside also takes audio the project points to elsewhere); a .als set goes through
als2ardour, which copies its samples wherever they are and lists the ones from outside its project folder.
IMPORT-REPORT.md beside the session lists what the reader knew it could not carry and what was left out or changed;
plug-ins and instruments are listed by name where the file type has them (a .logicx plug-in name is the first
readable text of its record, and may be wrong). The written session is read back before it is kept.
"""
import argparse
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

KINDS = {
    "live": ".als set", "logicx": ".logicx project", "ptx": ".ptx session",
    "dawproject": ".dawproject file", "reaper": ".rpp project", "aaf": ".aaf export",
}
EXT = {".als": "live", ".logicx": "logicx", ".band": "logicx", ".ptx": "ptx", ".ptf": "ptx",
       ".pts": "ptx", ".dawproject": "dawproject", ".rpp": "reaper", ".aaf": "aaf"}
FOLDER_KINDS = ("live", "reaper", "ptx")       # projects whose whole folder belongs to them (audio beside the file)


def kind_of(path):
    """What a project is: from its contents first (a renamed file still works), then its name."""
    p = Path(path)
    if p.is_dir():
        if (p / "Alternatives").is_dir() or p.suffix.lower() in (".logicx", ".band"):
            return "logicx"
        return None
    try:
        if not stat.S_ISREG(p.stat().st_mode):            # a pipe or a device would block or never end
            return None
        with open(p, "rb") as fh:
            h = fh.read(16)
    except OSError:
        return None
    if h[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":       # a compound file: AAF (a .ptx session is not this)
        return "aaf"
    if h[:2] == b"\x1f\x8b":                                  # gzip: a Live set
        return "live"
    if h[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(p) as z:
                if "project.xml" in z.namelist():
                    return "dawproject"
        except zipfile.BadZipFile:
            return None
    if h.lstrip().startswith(b"<REAPER_PROJECT"):
        return "reaper"
    if h.lstrip().startswith(b"<?xml") and p.suffix.lower() == ".als":
        return "live"
    if h[:1] == b"\x03" and p.suffix.lower() in (".ptx", ".ptf", ".pts"):   # a .ptx session's scrambled header
        return "ptx"
    return EXT.get(p.suffix.lower())


def guard_of(project, kind):
    """What the new session must not be inside: a .logicx package itself; for a .als, .rpp or .ptx the folder it is
    in (its audio lives there); a .dawproject or .aaf file only itself."""
    p = Path(project).expanduser().resolve()
    return p.parent if kind in FOLDER_KINDS else p


def default_out(project, kind=None):
    """Where a new session goes when no folder is named: "<name> (HypnoMix)" beside the project, or, for a project
    that owns its folder (.als, .rpp, .ptx), beside that folder. When that place cannot be written to (the top of a
    disk, a folder of another user), or is the project's own guard, the HypnoMix folder in Documents. Made unique."""
    p = Path(project).expanduser().resolve()
    kind = kind or kind_of(p)
    where = p.parent.parent if kind in FOLDER_KINDS else p.parent
    guard = guard_of(p, kind)
    if where == guard or guard in where.parents or not os.access(where, os.W_OK) or where.parent == where:
        where = Path.home() / "Documents" / "HypnoMix" / "Imported"
    base = where / f"{p.stem} (HypnoMix)"
    out, i = base, 2
    while out.exists():
        out, i = Path(f"{base} {i}"), i + 1
    return out


def roots_of(project, kind):
    """Where a project's own audio may be: its folder, the package, the zip's unpacked media."""
    p = Path(project).expanduser().resolve()
    if kind == "logicx":
        return [p, p.parent / "Audio Files"]
    return [p.parent]


def read(path, kind, media):
    if kind == "ptx":
        from hypnomix.project import import_ptx as M
        return M.read(path)
    if kind == "aaf":
        from hypnomix.project import import_aaf as M
        return M.read(path, media)
    if kind == "dawproject":
        from hypnomix.project import import_dawproject as M
        return M.read(path, media)
    if kind == "reaper":
        from hypnomix.project import import_reaper as M
        return M.read(path)
    if kind == "logicx":
        from hypnomix.project import import_logic as M
        return M.read(path)
    raise SystemExit(f"{Path(path).name}: not a project this can import")


def convert(project, out, sr=None, kind=None, log=print, allow_outside=False):
    """-> (the .ardour file, the report, a short summary line)."""
    project = Path(project).expanduser().resolve()
    if not project.exists():
        raise SystemExit(f"{project}: no such project")
    kind = kind or kind_of(project)
    if kind is None:
        raise SystemExit(f"{project.name}: not a project this can import. It reads: "
                         + ", ".join(KINDS.values()) + " (see `hypnomix import --help`)")
    if kind == "logicx" and not project.is_dir():
        raise SystemExit(f"{project.name}: a .logicx project is a folder (package)")
    if kind != "logicx" and not project.is_file():
        what = "a folder" if project.is_dir() else "not a regular file"
        raise SystemExit(f"{project.name}: not a {KINDS[kind]} ({what})")
    from hypnomix.project import importer
    guard = guard_of(project, kind)
    importer.check_out(out, guard, sr)                    # before anything is read or unpacked (every kind)
    if kind == "live":
        from hypnomix.project import als2ardour
        outp = Path(out).expanduser().resolve()
        existed = outp.exists()
        f, rep, w = als2ardour.convert(project, out, sr, log=log)
        n = sum(t.get("regions", 0) for t in w.song["tracks"])
        try:                                              # read back, as every other kind is
            from hypnomix.project import ardour
            rb = ardour.read(f)
            got = sum(len(x.clips) for x in rb.tracks)
            if not rb.tracks or got < n:
                raise ValueError(f"{len(rb.tracks)} track(s) and {got} region(s), not {n} regions")
        except Exception as e:
            if existed:
                for x in outp.iterdir():
                    shutil.rmtree(x, ignore_errors=True) if x.is_dir() else x.unlink(missing_ok=True)
            else:
                shutil.rmtree(outp, ignore_errors=True)
            raise SystemExit(f"{project.name}: the written session did not read back ({e}); nothing was kept") from e
        rep.write_text(file_type_words(rep.read_text(encoding="utf-8")).rstrip("\n") + "\n\n- Read back by HypnoMix's "
                       f"own session reader after writing: {len(rb.tracks)} track(s) and {got} region(s).\n",
                       encoding="utf-8")
        extra = "; --allow-outside does nothing for a .als (its samples are copied wherever they are)" \
            if allow_outside else ""
        return f, rep, f".als set: {plural(len(w.song['tracks']), 'track')}, {plural(n, 'region')}{extra}"
    media = Path(tempfile.mkdtemp(prefix="hypnomix-import-media-"))
    model = None
    try:
        try:
            model = read(project, kind, media)
        except (SystemExit, KeyboardInterrupt, MemoryError):
            raise
        except Exception as e:                            # a reader's surprise is one sentence, not a crash report
            raise SystemExit(f"{project.name}: could not be read as a {KINDS[kind]} ({type(e).__name__}: {e}); "
                             f"nothing was written") from e
        model["roots"] = roots_of(project, kind) + [media] + list(model.get("roots") or [])
        model["allow_outside"] = allow_outside
        f, rep, w = importer.convert(model, out, sr, log=log, guard=guard)
    finally:
        shutil.rmtree(media, ignore_errors=True)              # extracted audio: copied into the session already
        if model and model.get("media_dir") and Path(model["media_dir"]) != media:
            shutil.rmtree(model["media_dir"], ignore_errors=True)
    left = len(w.made["missing"]) + len(w.made["outside"])
    summary = (f"{model['daw']}: {plural(len(w.tracks), 'track')}, {plural(w.made['regions'], 'audio region')}, "
               f"{plural(w.made['midi'], 'MIDI region')}" + (f", {left} left out (see the report)" if left else ""))
    return f, rep, summary


LIVE_WORDS = [                    # the .als route's report, in this command's file-type words
    ("a set saved by Live ", "a .als set saved by version "), ("Live project folder", ".als project folder"),
    ("Live devices", "devices"), ("## Live settings", "## Settings"), ("Live's library", "the program's library"),
    ("Live's", "the source's"), ("in Live", "in the source"), ("Live mix", "source mix"),
    ("from Live", "from the source"), ("where Live", "where the source"), ("Live plays", "the source plays"),
    ("Live moves", "the source moves"), ("Live pans", "the source pans"), ("Live changes", "the source changes"),
    ("Live has", "the source has"), ("Live between", "the source between"),
]


def file_type_words(text):
    """The .als route's report (als2ardour's own words) said in file types, as the rest of `import` is. Only these
    phrases change: a track or file name that holds the word is the person's own and stays."""
    for a, b in LIVE_WORDS:
        text = text.replace(a, b)
    return text


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix import", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", help="the project to import (only read)")
    ap.add_argument("out", help="the new session folder (must not exist yet, or be empty)")
    ap.add_argument("--sr", type=int, help="session sample rate in Hz (default: the project's, or what most of its audio uses)")
    ap.add_argument("--from", dest="kind", choices=sorted(KINDS), help="what the project is (found from the file when left out)")
    ap.add_argument("--allow-outside", action="store_true",
                    help="also copy in audio the project points to outside its own folder (left out by default; a "
                         ".als copies its samples wherever they are)")
    a = ap.parse_args(argv)
    f, rep, summary = convert(a.project, a.out, a.sr, a.kind, allow_outside=a.allow_outside)
    print(f"wrote {f}")
    print(f"  {summary}; report: {rep}")


if __name__ == "__main__":
    main()
