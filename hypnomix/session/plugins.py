#!/usr/bin/env python3
"""List the plug-ins installed on this computer, mark the free ones hypnomix knows, and keep the list so
proposals only name what is really there. Nothing is changed: the only file written is your preferences,
and only when you ask (--save).

  hypnomix plugins                      what is installed (VST3, Audio Units on a Mac, CLAP, LV2), by format
  hypnomix plugins --check              also load each one without its window, one at a time, each in its own
                                        process with a time limit, so a plug-in that crashes or hangs is
                                        reported and skipped and never stops the run  [extra: plugins]
  hypnomix plugins --save               keep the list in your preferences (tools.plugins and friends)
  hypnomix plugins --json [OUT.json]    the same as data for an agent (no file name: printed to the screen)

Where it looks (the standard folders of each system; add your own with --folder FORMAT=DIR, repeatable):
  Mac      VST3 /Library/Audio/Plug-Ins/VST3 and ~/Library/...; Audio Units .../Components; CLAP .../CLAP;
           LV2 .../LV2
  Windows  VST3 C:\\Program Files\\Common Files\\VST3; CLAP ...\\Common Files\\CLAP; LV2 ...\\Common Files\\LV2
  Linux    ~/.vst3, /usr/lib/vst3, /usr/local/lib/vst3; ~/.clap, /usr/lib/clap; ~/.lv2, /usr/lib/lv2

"Free list" means the free and open-source plug-ins named in the README under "Free plug-ins that work with
hypnomix". They are marked so a proposal can use them; every other plug-in is listed but never proposed.

  --check     loads VST3 and Audio Unit plug-ins only (that is what the host, pedalboard, can open). CLAP and LV2
              are listed as found and marked "not checked". A plug-in that fails to load, crashes or does not
              answer within --timeout seconds (default 60) is listed as FAILED with the reason, and the run
              goes on. Instruments are told from effects here.
  --no-system   skip the standard folders: look only in the --folder ones
  --only TEXT   only plug-ins whose name contains TEXT (repeatable)
  --free      only the plug-ins on the free list
  --save      writes your preferences file (~/.hypnomix/preferences.json):
                tools.plugins         the free-list plug-ins that are installed (and, with --check, load); what
                                      `colour` and other proposals may name. Entries you added by hand are kept
                                      unless you give --replace
                tools.plugins_found   every plug-in found: name, format, folder, and (with --check) whether it loaded
              Without --save nothing is written, and the report says how.

Measured from the folders, not from a host: a plug-in in a folder hypnomix doesn't know isn't listed (use
--folder). Audio Units are read from their Info.plist; the others by their file name.
"""
import argparse, json, os, plistlib, re, subprocess, sys, time
from pathlib import Path

HOME = Path.home()
EXT = {"vst3": ".vst3", "au": ".component", "clap": ".clap", "lv2": ".lv2"}
FORMAT_NAME = {"vst3": "VST3", "au": "Audio Unit", "clap": "CLAP", "lv2": "LV2"}
HOSTED = ("vst3", "au")                    # what pedalboard can load


def system_folders(platform=None, home=None):
    """{format: [folders]} the standard places on this operating system."""
    platform = platform or sys.platform
    home = Path(home) if home else HOME
    if platform == "darwin":
        lib, top = home / "Library/Audio/Plug-Ins", Path("/Library/Audio/Plug-Ins")
        return {"vst3": [top / "VST3", lib / "VST3"], "au": [top / "Components", lib / "Components"],
                "clap": [top / "CLAP", lib / "CLAP"], "lv2": [top / "LV2", lib / "LV2"]}
    if platform.startswith("win"):
        pf = Path(os.environ.get("COMMONPROGRAMFILES", r"C:\Program Files\Common Files"))
        loc = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData/Local")))
        return {"vst3": [pf / "VST3", loc / "Programs/Common/VST3"], "au": [],
                "clap": [pf / "CLAP", loc / "Programs/Common/CLAP"], "lv2": [pf / "LV2", Path(os.environ.get("APPDATA", str(home / "AppData/Roaming"))) / "LV2"]}
    return {"vst3": [home / ".vst3", Path("/usr/lib/vst3"), Path("/usr/local/lib/vst3")], "au": [],
            "clap": [home / ".clap", Path("/usr/lib/clap"), Path("/usr/local/lib/clap")],
            "lv2": [home / ".lv2", Path("/usr/lib/lv2"), Path("/usr/local/lib/lv2")]}


# The free and open-source plug-ins named in README.md ("Free plug-ins that work with hypnomix"). `keys` are matched
# against the plug-in's name with spaces and punctuation removed (see norm); `exact` keys must equal it. `use` is
# what `colour` may use it for; "" = not a colour tool. Names are the README's own.
FREE = [
    dict(name="TDR Nova", keys=["tdrnova"], use=""),
    dict(name="TDR Kotelnikov", keys=["tdrkotelnikov"], use=""),
    dict(name="LoudMax", keys=["loudmax"], use=""),
    dict(name="Airwindows Consolidated", keys=["airwindowsconsolidated", "consolidated"], use="grit"),
    dict(name="CHOWTapeModel", keys=["chowtapemodel", "chowtape"], use="grit"),
    dict(name="Dragonfly Reverb", keys=["dragonflyhallreverb", "dragonflyroomreverb", "dragonflyplatereverb",
                                          "dragonflyearlyreflections", "dragonfly"], use="space"),
    dict(name="Valhalla Supermassive", keys=["valhallasupermassive", "supermassive"], use="space"),
    dict(name="Space Modulator", keys=["valhallaspacemodulator", "spacemodulator"], use="movement"),
    dict(name="Freq Echo", keys=["valhallafreqecho", "freqecho"], use="movement"),
    dict(name="Surge XT", keys=["surgext", "surgextfx", "surgexteffects"], use="instrument"),
    dict(name="SPAN", exact=["span", "voxengospan"], keys=[], use=""),
    dict(name="Youlean Loudness Meter 2", keys=["youleanloudnessmeter"], use=""),
    dict(name="sfizz", keys=["sfizz"], use="instrument"),
]


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def free_match(name):
    """The FREE entry this plug-in name belongs to, or None."""
    n = norm(name)
    if not n:
        return None
    for f in FREE:
        if n in f.get("exact", []) or any(k in n for k in f.get("keys", [])):
            return f
    return None


def _bundles(folder, ext, depth=3):
    """Plug-in bundles (or files) with this extension under a folder, one vendor sub-folder deep or more; a bundle
    is never entered."""
    out = []
    try:
        entries = sorted(folder.iterdir())
    except (OSError, PermissionError):
        return out
    for p in entries:
        if p.name.startswith("."):
            continue
        if p.name.lower().endswith(ext):
            out.append(p)
        elif p.is_dir() and depth > 0 and not p.is_symlink():
            out += _bundles(p, ext, depth - 1)
    return out


def _au_components(bundle):
    """[(name, kind)] from a .component's Info.plist (one bundle can hold several)."""
    try:
        pl = plistlib.loads((bundle / "Contents" / "Info.plist").read_bytes())
    except Exception:
        return []
    out = []
    for c in pl.get("AudioComponents") or []:
        nm = str(c.get("name", "")).split(": ", 1)[-1].strip()
        kind = {"aumu": "instrument", "aufx": "effect", "aumf": "instrument", "aumi": "midi"}.get(str(c.get("type")), "")
        if nm:
            out.append((nm, kind))
    return out


def scan(folders=None, extra=None):
    """Every plug-in found: dicts with name, format, path, kind (instrument / effect / ""), free (README name or None)."""
    folders = {k: list(v) for k, v in (system_folders() if folders is None else folders).items()}
    for fmt, d in (extra or []):
        folders.setdefault(fmt, []).append(Path(d))
    found, seen = [], set()
    for fmt, dirs in folders.items():
        for d in dirs:
            for b in _bundles(Path(d), EXT[fmt]):
                names = _au_components(b) if fmt == "au" else []
                names = names or [(b.name[: -len(EXT[fmt])], "")]
                for nm, kind in names:
                    key = (fmt, norm(nm), str(b))
                    if key in seen:
                        continue
                    seen.add(key)
                    f = free_match(nm) or free_match(b.name[: -len(EXT[fmt])])
                    found.append(dict(name=nm, format=fmt, path=str(b), kind=kind, free=f["name"] if f else None,
                                      use=f["use"] if f else ""))
    found.sort(key=lambda r: (r["name"].lower(), r["format"]))
    return found


def have_pedalboard():
    try:
        import pedalboard  # noqa: F401
        return True
    except Exception:
        return False


def check(found, timeout=60, only=(), log=None, probe=None):
    """Load each hosted plug-in in its own process (plugrender.probe), adding `loads` (True / False / None when it
    cannot be checked), `error` and `kind` where the host knows. A crash or a hang is one row's problem."""
    if probe is None:
        from hypnomix.session.plugrender import probe as probe_
        probe = probe_
    for r in found:
        if only and not any(o.lower() in r["name"].lower() for o in only):
            r["loads"] = None
            continue
        if r["format"] not in HOSTED:
            r.update(loads=None, error="not checked: the host (pedalboard) opens VST3 and Audio Unit only")
            continue
        t0 = time.time()
        res = probe(r["path"], r["name"] if r["format"] == "au" else None, None, timeout=timeout)
        r["loads"] = bool(res.get("ok"))
        r["seconds"] = round(time.time() - t0, 1)
        if r["loads"]:
            if res.get("instrument"):
                r["kind"] = "instrument"
            elif not r["kind"]:
                r["kind"] = "effect"
            r["parameters"] = len(res.get("params") or {})
        else:
            r["error"] = res.get("error") or "did not load"
        if log:
            log(r)
    return found


def to_prefs(found, checked):
    """(tools.plugins names, tools.plugins_found rows). A free-list plug-in counts as installed when it was found
    and, when --check ran on it, loads."""
    usable = sorted({r["name"] for r in found if r["free"] and r.get("loads") is not False})
    rows = [dict(name=r["name"], format=r["format"], path=r["path"], free=bool(r["free"]),
                 **({"loads": r["loads"]} if checked and r.get("loads") is not None else {})) for r in found]
    return usable, rows


def save_prefs(found, checked, replace=False, path=None):
    from hypnomix.workflow import prefs as P
    prefs = P.load(path)
    usable, rows = to_prefs(found, checked)
    old = [x for x in (P.get(prefs, "tools.plugins", []) or []) if isinstance(x, str)]
    names = usable if replace else sorted(set(old) | set(usable), key=str.lower)
    P.put(prefs, "tools.plugins", names)
    P.put(prefs, "tools.plugins_found", rows)
    return P.save(prefs, path), names


def installed_free(prefs=None):
    """The free-list plug-ins the person has, from their preferences (what proposals may name). [] = stock only."""
    from hypnomix.workflow import prefs as P
    prefs = prefs if prefs is not None else P.load()
    return [x for x in (P.get(prefs, "tools.plugins", []) or []) if isinstance(x, str)]


def installed_with_use(prefs=None, use=None):
    """[(name, use)] for installed plug-ins whose free-list entry has this use ('space', 'grit', 'movement',
    'instrument'), from the saved list."""
    out = []
    for n in installed_free(prefs):
        f = free_match(n)
        if f and f["use"] and (use is None or f["use"] == use):
            out.append((n, f["use"]))
    return out


def report(found, folders, checked):
    lines = []
    by = {}
    for r in found:
        by.setdefault(r["format"], []).append(r)
    for fmt in ("vst3", "au", "clap", "lv2"):
        rows = by.get(fmt, [])
        if not rows and not folders.get(fmt):
            continue
        lines.append(f"{FORMAT_NAME[fmt]}: {len(rows)}")
        for r in rows:
            tag = f"  [free list: {r['free']}]" if r["free"] else ""
            st = ""
            if checked:
                st = "  loads" if r.get("loads") else ("  FAILED: " + r["error"] if r.get("loads") is False else
                                                      ("  (" + r["error"] + ")" if r.get("error") else ""))
            kind = f" ({r['kind']})" if r["kind"] else ""
            lines.append(f"  {r['name'][:44]:<44}{kind}{tag}{st}")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix plugins", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="load each VST3 / AU without its window (each in its own process)")
    ap.add_argument("--timeout", type=int, default=60, help="seconds a plug-in gets to load (default 60)")
    ap.add_argument("--only", action="append", default=[], metavar="TEXT", help="only plug-ins whose name contains TEXT")
    ap.add_argument("--free", action="store_true", help="only the plug-ins on the free list")
    ap.add_argument("--no-system", action="store_true", help="do not look in the standard folders, only in --folder ones")
    ap.add_argument("--folder", action="append", default=[], metavar="FORMAT=DIR", help="another folder to look in")
    ap.add_argument("--save", action="store_true", help="keep the list in your preferences (tools.plugins)")
    ap.add_argument("--replace", action="store_true", help="with --save: replace tools.plugins instead of adding to it")
    ap.add_argument("--prefs-file", help=argparse.SUPPRESS)
    ap.add_argument("--json", nargs="?", const="-", metavar="OUT.json", help="the list as data (no name: printed)")
    a = ap.parse_args(argv)

    extra = []
    for item in a.folder:
        fmt, _, d = item.partition("=")
        if fmt.lower() not in EXT or not d:
            sys.exit(f"--folder wants FORMAT=DIR with FORMAT one of {', '.join(EXT)}, got {item!r}")
        extra.append((fmt.lower(), d))
    folders = {} if a.no_system else system_folders()
    found = scan(folders, extra)
    if a.free:
        found = [r for r in found if r["free"]]
    if a.only:
        found = [r for r in found if any(o.lower() in r["name"].lower() for o in a.only)]
    out = sys.stderr if a.json == "-" else sys.stdout
    if a.check:
        if not have_pedalboard():
            from hypnomix.extras import hint
            sys.exit("--check needs pedalboard: " + hint("plugins"))
        n_host = sum(r["format"] in HOSTED for r in found)
        print(f"loading {n_host} plug-in(s), one at a time, each with {a.timeout} s to answer…", file=out)
        check(found, a.timeout, log=lambda r: print(f"  {r['name'][:40]:<40} " + ("loads" if r["loads"] else "FAILED: " + r["error"]),
                                                     file=out, flush=True))
    for line in report(found, folders, a.check):
        print(line, file=out)
    n_free = sum(1 for r in found if r["free"])
    names = sorted({r["free"] for r in found if r["free"]})
    print(f"\n{len(found)} plug-in(s) found; {n_free} on the free list" + (f" ({', '.join(names)})" if names else "")
          + ("" if a.check else ". Add --check to load each one."), file=out)
    if not found:
        print("none in the standard folders: if yours live elsewhere, add --folder FORMAT=DIR.", file=out)
    saved = None
    if a.save:
        p, kept = save_prefs(found, a.check, a.replace, a.prefs_file)
        saved = str(p)
        print(f"saved {len(kept)} free plug-in(s) as tools.plugins in {p}", file=out)
    else:
        print("nothing was written. `--save` keeps this list in your preferences so proposals only name what is installed.", file=out)
    if a.json:
        usable, rows = to_prefs(found, a.check)
        doc = dict(plugins=[{k: v for k, v in r.items() if k != "seconds"} for r in found], free_installed=usable,
                   checked=bool(a.check), saved=saved)
        if a.json == "-":
            print(json.dumps(doc, indent=1))
        else:
            Path(a.json).write_text(json.dumps(doc, indent=1))
            print(f"→ {a.json}")
    failed = [r for r in found if r.get("loads") is False]
    if failed:
        print(f"{len(failed)} plug-in(s) FAILED to load: listed above; the rest were checked.", file=out)


if __name__ == "__main__":
    main()
