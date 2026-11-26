"""The optional extras, for the installed app too.

The installers ship hypnomix with the `assistant` and `critique` extras. The other three stay out of the download:
`reference` (matchering) and `plugins` (pedalboard) are GPL-3.0, so hypnomix itself stays MIT, and `ml` pulls in an
ML runtime of about a gigabyte. The app's Setup (Extras step) installs any of them from PyPI on a click, into
~/.hypnomix/extras/pyXY, never inside the app itself: so the signed app stays untouched, an update to the app keeps
them, and deleting that folder removes them. Packages the app already has are pinned to its own versions, so an extra
can never swap out a library the app depends on (it fails with pip's message instead).

A source install (a venv or any other Python) gets them installed into that same Python instead.

Importing hypnomix adds the extras folder to sys.path when it exists (hypnomix/__init__.py), so the app, its
`hypnomix` command and the agents all see them."""
import os, re, shutil, site, subprocess, sys, sysconfig, threading, time
from importlib import metadata, util
from pathlib import Path

EXTRAS = {
    "reference": dict(title="Reference matching", modules=["matchering"], license="GPL-3.0 (matchering)",
                      size="about 150 MB", commands=["reference"],
                      what="Compares your master with a song you want to sound like and says what it would take: level, tone, width."),
    "plugins": dict(title="Your own plug-ins", modules=["pedalboard"], license="GPL-3.0 (pedalboard, from Spotify)",
                    size="about 10 MB", commands=["plugrender", "ab --plugins"],
                    what="Renders tracks through their real VST3 / AU plug-in chains, offline, so a scan and the A/B players hear the plug-ins too."),
    "ml": dict(title="Stem separation and audio to MIDI", modules=["audio_separator", "basic_pitch"],
               license="MIT (audio-separator, basic-pitch); brings PyTorch (BSD) and ONNX Runtime (MIT)",
               size="about 1 GB, plus a 320 MB model fetched the first time stem separation runs", commands=["separate", "midi"],
               what="Splits a finished song into stems (vocals, drums, bass, other), and turns a recorded part into MIDI notes."),
    "assistant": dict(title="The Assistant tab", modules=["anthropic", "openai"], license="MIT", size="included",
                      commands=[], what="Talks to Claude or any OpenAI-compatible AI service.", included=True),
    "critique": dict(title="The Listener", modules=["openai"], license="MIT", size="included", commands=["critique"],
                     what="Gemini or OpenRouter hears a bounce and gives notes by ear.", included=True),
}

# basic-pitch 0.4 asks for TensorFlow < 2.15.1, which has no build for Python 3.12 (the app's), so pip can't install
# it as published. It ships its model for ONNX Runtime too and uses that when TensorFlow is absent, so the app installs
# its other requirements plus onnxruntime first, then basic-pitch itself without dependencies. (The old resampy it
# needs imports pkg_resources, which setuptools 81 removed. audio-separator imports audioread without listing it:
# librosa 1.0 stopped bringing it.)
SPLIT = {"ml": [["audio-separator>=0.30", "audioread", "onnxruntime", "librosa>=0.8.0", "mir-eval>=0.6", "pretty-midi>=0.2.9",
                 "resampy>=0.2.2,<0.4.3", "setuptools<81", "scikit-learn", "scipy>=1.4.1", "typing-extensions"],
                ["--no-deps", "basic-pitch>=0.4"]]}

_jobs = {}                      # extra -> dict(running, ok, log, started, ended)
_lock = threading.Lock()


def bundled():
    """Running from an installer (the Mac app, the Windows setup), not a source checkout."""
    exe = Path(sys.executable).resolve()
    return "Hypnomix.app" in exe.parts or (exe.parent.name.lower() == "python" and (exe.parent.parent / "launcher.pyw").exists())


def base_dir():
    return Path.home() / ".hypnomix" / "extras" / f"py{sys.version_info[0]}{sys.version_info[1]}"


def site_dir(base=None):
    scheme = sysconfig.get_preferred_scheme("user")
    return Path(sysconfig.get_path("purelib", scheme, vars={"userbase": str(base or base_dir())}))


def add_to_path():
    """Called on import: make what Setup installed importable. Cheap when nothing was ever installed."""
    try:
        d = site_dir()
        if d.is_dir() and str(d) not in sys.path:
            site.addsitedir(str(d))
    except Exception:
        pass


def requirements(name):
    """The extra's requirements, as hypnomix's own metadata lists them (pyproject.toml)."""
    out = []
    try:
        reqs = metadata.requires("hypnomix") or []
    except metadata.PackageNotFoundError:
        reqs = []
    for r in reqs:
        spec, _, marker = r.partition(";")
        if re.search(r"""extra\s*==\s*['"]%s['"]""" % re.escape(name), marker):
            out.append(spec.strip())
    return out


def installed(name):
    return all(util.find_spec(m) is not None for m in EXTRAS[name]["modules"])


def hint(name):
    """What to tell someone who runs a command that needs a missing extra."""
    if bundled():
        return f"this needs the optional extra '{name}': in the hypnomix app click Setup, then Extras, and install \"{EXTRAS[name]['title']}\""
    return f"this needs the optional extra '{name}': in the hypnomix folder, run: uv pip install -e \".[{name}]\""


def _python():
    py = Path(sys.executable)
    if sys.platform == "win32" and py.name.lower() == "pythonw.exe":
        py = py.with_name("python.exe")
    return str(py)


def _pins():
    """Every package this Python already has, pinned to its version: an extra may add packages, never replace one."""
    seen, lines = set(), []
    mine = str(base_dir())
    for d in metadata.distributions(path=[p for p in sys.path if not p.startswith(mine)]):   # the app's own, not earlier extras
        n = (d.metadata["Name"] or "").lower()
        if n and n not in seen and n != "hypnomix" and d.version:
            seen.add(n)
            lines.append(f"{n}=={d.version}")
    return "\n".join(sorted(lines)) + "\n"


def commands(name):
    """The pip commands for an extra (one, or two for `ml`), and their environment."""
    reqs = requirements(name)
    if not reqs:
        raise ValueError(f"hypnomix's metadata lists no packages for the extra '{name}'")
    env, base = _env()
    return [base + part for part in SPLIT.get(name, [reqs])], env


def _env():
    env = dict(os.environ)
    env.pop("PYTHONNOUSERSITE", None)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    if not has_pip() and not bundled():                     # a uv venv has no pip: uv installs into it instead
        return env, [shutil.which("uv"), "pip", "install", "--python", sys.executable]
    cmd = [_python(), "-m", "pip", "install", "--prefer-binary", "--progress-bar", "off", "--no-warn-script-location"]
    if bundled():
        base = base_dir()
        base.mkdir(parents=True, exist_ok=True)
        pins = base / "app-packages.txt"
        pins.write_text(_pins())
        env["PYTHONUSERBASE"] = str(base)
        cmd += ["--user", "--constraint", str(pins)]
    return env, cmd


def has_pip():
    return util.find_spec("pip") is not None


def can_install():
    return has_pip() or (not bundled() and shutil.which("uv") is not None)


def status():
    rows = []
    for k, e in EXTRAS.items():
        with _lock:
            j = dict(_jobs.get(k, {}))
        rows.append(dict(id=k, **{x: e[x] for x in ("title", "license", "size", "commands", "what")},
                         included=bool(e.get("included")), installed=installed(k),
                         running=bool(j.get("running")), ok=j.get("ok"), log=j.get("log", "")[-6000:]))
    return dict(extras=rows, bundled=bundled(), pip=can_install(), where=_tilde(base_dir()) if bundled() else sys.prefix)


def _tilde(p):
    h = str(Path.home())
    return "~" + str(p)[len(h):] if str(p).startswith(h + os.sep) else str(p)


def _show(cmd):
    return "$ " + " ".join(c if " " not in c else f'"{c}"' for c in cmd) + "\n"


def _run(name, cmds, env):
    job = _jobs[name]
    kw = dict(creationflags=0x08000000) if sys.platform == "win32" else {}       # CREATE_NO_WINDOW
    ok = True
    try:
        for i, cmd in enumerate(cmds):
            if i:
                with _lock:
                    job["log"] += _show(cmd)
            p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, **kw)
            for line in p.stdout:
                with _lock:
                    job["log"] += line
            p.wait()
            if p.returncode != 0:
                ok = False
                break
    except Exception as e:
        ok = False
        with _lock:
            job["log"] += f"\n{e}\n"
    if ok:
        add_to_path()
        import importlib
        importlib.invalidate_caches()
        ok = installed(name)
        if not ok:
            with _lock:
                job["log"] += "\npip finished, but the extra still can't be imported. Quit and reopen the app, then check again.\n"
    with _lock:
        job.update(running=False, ok=ok, ended=time.time())


def install(name):
    if name not in EXTRAS or EXTRAS[name].get("included"):
        raise ValueError(f"no extra to install called '{name}'")
    if not can_install() and not bundled():
        raise ValueError(f"No pip or uv to install with. In a terminal, in the hypnomix folder: uv pip install -e \".[{name}]\"")
    if not can_install():
        raise ValueError("This copy of the app has no pip to install extras with. Download the newest installer from "
                         "hypnomix.bradfieldenterprises.org/download/ and install it over this one.")
    with _lock:
        if _jobs.get(name, {}).get("running"):
            return status()
    cmds, env = commands(name)
    with _lock:
        _jobs[name] = dict(running=True, ok=None, started=time.time(), log=_show(cmds[0]))
    threading.Thread(target=_run, args=(name, cmds, env), daemon=True).start()
    return status()
