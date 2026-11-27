"""`hypnomix install` and `hypnomix doctor`: get Live talking to HypnoMix, and check that it does."""
import filecmp, os, platform, re, shutil, socket, subprocess, sys, time
from pathlib import Path

PKG = Path(__file__).resolve().parent
SCRIPT_SRC = PKG / "remote_script" / "AbletonOSC"
PARAM_LINE = "-_PluginAutoPopulateThreshold=128"


def _windows_documents():
    """The Documents folder Windows says this person has (it may be moved, for example into a synced folder), or None."""
    try:
        import ctypes
        guid = (ctypes.c_ubyte * 16)(*bytes.fromhex("D09AD3FD8F23AF46ADB46C85480369C7"))     # FOLDERID_Documents
        got = ctypes.c_void_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(got)) != 0:
            return None
        try:
            return Path(ctypes.wstring_at(got.value)) if got.value else None
        finally:
            ctypes.windll.ole32.CoTaskMemFree(got)
    except Exception:
        return None


def documents_dir():
    """The person's Documents folder: on Windows the one the system names (a moved Documents folder included), else
    ~/Documents."""
    if platform.system() == "Windows":
        d = _windows_documents()
        if d:
            return d
    return Path.home() / "Documents"


def user_library():
    """Where Live keeps the User Library (where it would be, whether or not it exists yet): ~/Music/Ableton/User
    Library on a Mac, <Documents>/Ableton/User Library on Windows and elsewhere. Only a custom Library location
    chosen inside Live is not followed: use --out for that."""
    if platform.system() == "Darwin":
        return Path.home() / "Music/Ableton/User Library"
    return documents_dir() / "Ableton/User Library"


def user_library_words():
    """The default User Library as the person sees it, for messages ("~/Music/Ableton/User Library")."""
    lib = user_library()
    try:
        return "~/" + lib.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(lib)


def remote_scripts_dir():
    return user_library() / "Remote Scripts"


def live_prefs_dir():
    """The folder that holds Live's Preferences.cfg and Options.txt, newest Live version first. On a Mac that is
    ~/Library/Preferences/Ableton/Live x.y.z; on Windows it is the Preferences folder inside %APPDATA%\\Ableton\\Live x.y.z."""
    win = platform.system() == "Windows"
    if platform.system() == "Darwin":
        base = Path.home() / "Library/Preferences/Ableton"
    else:
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData/Roaming")) / "Ableton"
    if not base.exists():
        return None
    inner = (lambda p: p / "Preferences") if win else (lambda p: p)
    vers = [p for p in base.iterdir() if p.name.startswith("Live ") and ((inner(p) / "Preferences.cfg").exists() or p.name.startswith("Live 1"))]
    key = lambda p: [int(x) if x.isdigit() else 0 for x in re.findall(r"\d+|\D+", p.name.replace("Live ", ""))]
    return inner(sorted(vers, key=key)[-1]) if vers else None


# What the copy leaves out; the "is it up to date" check must skip exactly the same things (plus Finder's
# .DS_Store), or Live's own files inside the installed copy (it writes logs/ there) look like a difference.
COPY_IGNORE = ("__pycache__", "*.pyc", "logs")


def _files(root):
    """{relative path: absolute path} of the files a fresh copy would hold."""
    skip = shutil.ignore_patterns(*COPY_IGNORE, ".DS_Store")
    out = {}
    for d, dirs, names in os.walk(root):
        gone = set(skip(d, dirs + names))
        dirs[:] = sorted(x for x in dirs if x not in gone)
        for n in names:
            if n not in gone:
                full = Path(d) / n
                out[str(full.relative_to(root))] = full
    return out


def _same_tree(a, b):
    fa, fb = _files(a), _files(b)
    return fa.keys() == fb.keys() and all(filecmp.cmp(fa[k], fb[k], shallow=False) for k in fa)


INSTALL_HELP = """usage: hypnomix install [--dry-run] [--plugin-params]

Copies the bundled AbletonOSC remote script into Live's User Library (an existing copy is backed up first)
and prints the remaining setup steps. --plugin-params also adds one line to Live's Options.txt so plug-ins
expose up to 128 parameters. --dry-run shows what would happen and changes nothing."""


def install(argv):
    if set(argv) & {"-h", "--help"}:
        print(INSTALL_HELP); return
    unknown = [x for x in argv if x not in ("--dry-run", "--plugin-params")]
    if unknown:
        sys.exit(f"unknown option(s) {unknown}\n\n{INSTALL_HELP}")
    dry = "--dry-run" in argv
    dest = remote_scripts_dir() / "AbletonOSC"
    print(f"1. Live remote script → {dest}")
    if dest.exists() and _same_tree(SCRIPT_SRC, dest):
        print("   already up to date")
    else:
        if dest.exists():
            bak = dest.with_name(f"AbletonOSC (backup {time.strftime('%Y%m%d-%H%M%S')})")
            print(f"   {'would move the existing copy to' if dry else 'existing copy moved to'} {bak.name}")
            if not dry:
                dest.rename(bak)
        if not dry:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(SCRIPT_SRC, dest, ignore=shutil.ignore_patterns(*COPY_IGNORE))
            print("   installed. Restart Live, then Settings → Link, Tempo & MIDI → Control Surface: AbletonOSC")
        else:
            print("   would install it here (--dry-run: nothing was copied). Without --dry-run: restart Live, then "
                  "Settings → Link, Tempo & MIDI → Control Surface: AbletonOSC")

    prefs = live_prefs_dir()
    if "--plugin-params" in argv:
        if not prefs:
            print("2. couldn't find Live's preferences folder; add this line to Options.txt yourself:", PARAM_LINE)
        else:
            opt = prefs / "Options.txt"
            text = opt.read_bytes().decode("utf-8", "surrogateescape") if opt.exists() else ""   # bytes of the person's own lines come back unchanged (text mode would turn CRLF into LF)
            if "PluginAutoPopulateThreshold" in text:
                print(f"2. {opt} already sets the plug-in parameter threshold")
            else:
                print(f"2. {'would add' if dry else 'adding'} {PARAM_LINE} to {opt} "
                      "(Live shows up to 128 parameters of every plug-in to HypnoMix)")
                if not dry:
                    opt.parent.mkdir(parents=True, exist_ok=True)
                    eol = "\r\n" if ("\r\n" in text or (not text and os.name == "nt")) else "\n"   # the new line ends the way the person's own lines do; a new file gets the system's
                    opt.write_bytes((text + (eol if text and not text.endswith("\n") else "") + PARAM_LINE + eol)
                                    .encode("utf-8", "surrogateescape"))
    else:
        print("2. plug-in parameters: run `hypnomix install --plugin-params` to let HypnoMix see up to 128 parameters\n"
              "   of every plug-in without clicking Configure (adds one line to Live's Options.txt)")

    print("3. Recording what Live plays (for `hypnomix loop` and `diagnose`): install BlackHole 2ch\n"
          "   (brew install blackhole-2ch), then in Audio MIDI Setup create a Multi-Output Device = your speakers +\n"
          "   BlackHole 2ch (speakers as clock source) and choose it as Live's audio output.")
    print("4. Claude Code: open this repo in Claude Code; the skills in skills/ and .mcp.json load automatically.\n"
          "   For the Ableton MCP (building tracks, loading devices) also install its remote script:\n"
          "   https://github.com/ahujasid/ableton-mcp#installation")
    print("\n" + ("That was a dry run: nothing was changed." if dry else "Then run: hypnomix doctor"))


def _port_open(port):
    s = socket.socket(); s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", port)); return True
    except OSError:
        return False
    finally:
        s.close()


LIVE_APP_DIRS = (Path("/Applications"), Path("C:/ProgramData/Ableton"), Path("C:/Program Files/Ableton"))


def uses_live():
    """True when this computer looks like it belongs to someone who uses Ableton Live: its User Library or its
    preferences folder exist, or the app is installed. REAPER, HypnoMix DAW and folder-of-stems users never need the Live parts."""
    try:
        if remote_scripts_dir().parent.exists() or live_prefs_dir() is not None:
            return True
        return any(any(d.glob("Ableton Live*")) or d.name == "Ableton" and d.exists() for d in LIVE_APP_DIRS)
    except OSError:
        return False


def live_mark(found, live_here):
    """The mark for a part only Live needs: ✓ when it is there; ✗ (needed) for someone who uses Live; · (optional)
    for everyone else, so a REAPER or HypnoMix DAW user is not told something is missing that they never need."""
    return "✓" if found else ("✗" if live_here else "·")


def doctor_exit(rows):
    """1 when something needed is missing: the first four rows (Python, packages, ffmpeg and, for a Live user, the
    remote script). The Live-only rows are marked · for everyone else, so they never count."""
    return 1 if any(r[0] == "✗" for r in rows[:4]) else 0


def _live_answer():
    """(answers, detail): is Live answering on UDP 11000 (the only part of doctor that talks to a running Live)."""
    live_ok, detail = False, "Live not answering on UDP 11000 (open Live; Control Surface: AbletonOSC)"
    try:
        from hypnomix.live.osc import Live, LiveError
        l = Live(timeout=1.0)
        if l.ping():
            live_ok = True
            detail = f"connected: {l.tempo():.1f} BPM, {len([t for t in l.tracks() if t[0] >= 0])} tracks"
        l.close()
    except Exception as e:
        detail = f"{detail} ({e})"
    return live_ok, detail


def _blackhole():
    try:
        import sounddevice as sd
        return [d["name"] for d in sd.query_devices() if "blackhole" in d["name"].lower()]
    except Exception:
        return []


def doctor(argv):
    if set(argv) & {"-h", "--help"}:
        print("usage: hypnomix doctor\n\nChecks Python packages, ffmpeg, the Live remote script, the Live connection, "
              "BlackHole, plug-in parameter access, your profile and optional extras. Changes nothing. The Live parts "
              "are marked optional (·) on a computer without Ableton Live and only count as needed (✗) when Live is there."); return
    rows = doctor_rows()
    w = max(len(r[1]) for r in rows)
    for mark, name, d in rows:
        print(f" {mark} {name:<{w}}  {d}")
    print("\n✓ ok   ✗ needed   · optional")
    sys.exit(doctor_exit(rows))


def doctor_rows():
    """[(mark, name, detail)] for every row doctor prints. Nothing is changed."""
    ok = lambda b: "✓" if b else "✗"
    live_here = uses_live()
    rows = []
    py = sys.version_info
    rows.append((ok(py >= (3, 9)), "Python", f"{py.major}.{py.minor}"))
    missing = []
    for m in ("numpy", "scipy", "soundfile", "sounddevice", "pyloudnorm", "librosa", "matplotlib", "pythonosc", "noisereduce"):
        try:
            __import__(m)
        except Exception:
            missing.append(m)
    rows.append((ok(not missing), "Python packages", "all present" if not missing else f"missing: {', '.join(missing)}"))
    rows.append((ok(bool(shutil.which("ffmpeg"))), "ffmpeg", shutil.which("ffmpeg") or "not found: brew install ffmpeg"))

    dest = remote_scripts_dir() / "AbletonOSC"
    try:
        inst = dest.exists() and "volume_string" in (dest / "abletonosc/track.py").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        inst = False
    rows.append((live_mark(inst, live_here), "AbletonOSC remote script", str(dest) if inst else
                 ("not installed (or the unpatched upstream version): hypnomix install" if live_here else
                  "not installed: only needed to talk to an open Ableton Live set (`hypnomix install` puts it there)")))

    live_ok, detail = _live_answer()
    rows.append((live_mark(live_ok, live_here), "Live via AbletonOSC", detail))
    rows.append(("·" if not _port_open(9877) else "✓", "Ableton MCP (optional, TCP 9877)",
                 "connected" if _port_open(9877) else "not running (only needed for building tracks/devices from Claude)"))

    bh = _blackhole()
    rows.append((live_mark(bool(bh), live_here), "BlackHole (for loop/diagnose)",
                 bh[0] if bh else "not found: brew install blackhole-2ch, then restart CoreAudio"
                 + ("" if live_here else " (only for recording what an open Live plays)")))

    prefs = live_prefs_dir()
    opt = prefs / "Options.txt" if prefs else None
    has = bool(opt and opt.exists() and "PluginAutoPopulateThreshold" in opt.read_text(encoding="utf-8", errors="ignore"))
    rows.append(("✓" if has else "·", "Plug-in parameter access", "Options.txt threshold set" if has else
                 "Live shows a limited set of a big plug-in's parameters: hypnomix install --plugin-params (or click Configure)"))

    from hypnomix.core import tools
    rows.append(("✓" if tools.rubberband_path() else "·", "Rubber Band (tune, vocal alignment)", tools.rubberband_path() or
                 f"not found (optional; tune and vocalign need it): {tools.rubberband_how()}"))

    from hypnomix.core.paths import PROFILE
    rows.append(("✓" if PROFILE.exists() else "·", "Your profile", str(PROFILE) if PROFILE.exists() else
                 "none yet (optional): hypnomix profile build song1.wav song2.wav …"))
    for mod, extra in (("matchering", "reference"), ("audio_separator", "ml"), ("basic_pitch", "ml"), ("openai", "critique")):
        try:
            __import__(mod); have = True
        except Exception:
            have = False
        rows.append(("✓" if have else "·", f"extra [{extra}] ({mod})", "installed" if have else f"not installed (in the app: Setup, then Extras; from source, in the HypnoMix folder: uv pip install -e \".[{extra}]\")"))
    return rows
