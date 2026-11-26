"""`hypnomix install` and `hypnomix doctor`: get Live talking to hypnomix, and check that it does."""
import filecmp, os, platform, re, shutil, socket, subprocess, sys, time
from pathlib import Path

PKG = Path(__file__).resolve().parent
SCRIPT_SRC = PKG / "remote_script" / "AbletonOSC"
PARAM_LINE = "-_PluginAutoPopulateThreshold=128"


def remote_scripts_dir():
    home = Path.home()
    if platform.system() == "Darwin":
        return home / "Music/Ableton/User Library/Remote Scripts"
    return home / "Documents/Ableton/User Library/Remote Scripts"


def live_prefs_dir():
    base = Path.home() / ("Library/Preferences/Ableton" if platform.system() == "Darwin" else "AppData/Roaming/Ableton")
    if not base.exists():
        return None
    vers = [p for p in base.iterdir() if p.name.startswith("Live ") and (p / "Preferences.cfg").exists() or p.name.startswith("Live 1")]
    key = lambda p: [int(x) if x.isdigit() else 0 for x in re.findall(r"\d+|\D+", p.name.replace("Live ", ""))]
    return sorted(vers, key=key)[-1] if vers else None


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
            print(f"   existing copy moved to {bak.name}")
            if not dry:
                dest.rename(bak)
        if not dry:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(SCRIPT_SRC, dest, ignore=shutil.ignore_patterns(*COPY_IGNORE))
        print("   installed. Restart Live, then Settings → Link, Tempo & MIDI → Control Surface: AbletonOSC")

    prefs = live_prefs_dir()
    if "--plugin-params" in argv:
        if not prefs:
            print("2. couldn't find Live's preferences folder; add this line to Options.txt yourself:", PARAM_LINE)
        else:
            opt = prefs / "Options.txt"
            text = opt.read_text() if opt.exists() else ""
            if "PluginAutoPopulateThreshold" in text:
                print(f"2. {opt} already sets the plug-in parameter threshold")
            else:
                print(f"2. adding {PARAM_LINE} to {opt} (Live shows up to 128 parameters of every plug-in to hypnomix)")
                if not dry:
                    opt.write_text(text + ("\n" if text and not text.endswith("\n") else "") + PARAM_LINE + "\n")
    else:
        print("2. plug-in parameters: run `hypnomix install --plugin-params` to let hypnomix see up to 128 parameters\n"
              "   of every plug-in without clicking Configure (adds one line to Live's Options.txt)")

    print("3. Recording what Live plays (for `hypnomix loop` and `diagnose`): install BlackHole 2ch\n"
          "   (brew install blackhole-2ch), then in Audio MIDI Setup create a Multi-Output Device = your speakers +\n"
          "   BlackHole 2ch (speakers as clock source) and choose it as Live's audio output.")
    print("4. Claude Code: open this repo in Claude Code; the skills in skills/ and .mcp.json load automatically.\n"
          "   For the Ableton MCP (building tracks, loading devices) also install its remote script:\n"
          "   https://github.com/ahujasid/ableton-mcp#installation")
    print("\nThen run: hypnomix doctor")


def _port_open(port):
    s = socket.socket(); s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", port)); return True
    except OSError:
        return False
    finally:
        s.close()


def doctor(argv):
    if set(argv) & {"-h", "--help"}:
        print("usage: hypnomix doctor\n\nChecks Python packages, ffmpeg, the Live remote script, the Live connection, "
              "BlackHole, plug-in parameter access, your profile and optional extras. Changes nothing."); return
    ok = lambda b: "✓" if b else "✗"
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
    inst = dest.exists() and "volume_string" in (dest / "abletonosc/track.py").read_text(errors="ignore") if dest.exists() else False
    rows.append((ok(inst), "AbletonOSC remote script", str(dest) if inst else
                 "not installed (or the unpatched upstream version): hypnomix install"))

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
    rows.append((ok(live_ok), "Live via AbletonOSC", detail))
    rows.append(("·" if not _port_open(9877) else "✓", "Ableton MCP (optional, TCP 9877)",
                 "connected" if _port_open(9877) else "not running (only needed for building tracks/devices from Claude)"))

    try:
        import sounddevice as sd
        bh = [d["name"] for d in sd.query_devices() if "blackhole" in d["name"].lower()]
    except Exception:
        bh = []
    rows.append((ok(bool(bh)), "BlackHole (for loop/diagnose)", bh[0] if bh else "not found: brew install blackhole-2ch, then restart CoreAudio"))

    prefs = live_prefs_dir()
    opt = prefs / "Options.txt" if prefs else None
    has = bool(opt and opt.exists() and "PluginAutoPopulateThreshold" in opt.read_text(errors="ignore"))
    rows.append(("✓" if has else "·", "Plug-in parameter access", "Options.txt threshold set" if has else
                 "Live shows a limited set of a big plug-in's parameters: hypnomix install --plugin-params (or click Configure)"))

    from hypnomix.core.paths import PROFILE
    rows.append(("✓" if PROFILE.exists() else "·", "Your profile", str(PROFILE) if PROFILE.exists() else
                 "none yet (optional): hypnomix profile build song1.wav song2.wav …"))
    for mod, extra in (("matchering", "reference"), ("audio_separator", "ml"), ("basic_pitch", "ml"), ("openai", "critique")):
        try:
            __import__(mod); have = True
        except Exception:
            have = False
        rows.append(("✓" if have else "·", f"extra [{extra}] ({mod})", "installed" if have else f"not installed (pip install 'hypnomix[{extra}]')"))
    w = max(len(r[1]) for r in rows)
    for mark, name, d in rows:
        print(f" {mark} {name:<{w}}  {d}")
    print("\n✓ ok   ✗ needed   · optional")
    sys.exit(1 if any(r[0] == "✗" for r in rows[:4]) else 0)
