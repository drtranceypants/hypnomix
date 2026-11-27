"""HypnoMix Probe and HypnoMix Main for REAPER (JSFX), the same as the Live devices for the HypnoMix app.

  hypnomix reaper probes install            copy the two effects into REAPER's Effects folder (Effects/hypnomix)
  hypnomix reaper probes insert SONG.rpp     a NEW project with a probe last on every track and Main on the master
  hypnomix reaper probes cards SONG.rpp      what the probes and the song card say, read from the saved project

The probe (last on a track) measures what the track plays after all its plug-ins: the 20 values the app reads from
the Live probe, ten times a second, with the song position. Its menus say what the track is, its priority and
whether it is protected. HypnoMix Main on the master is the song card (genre, key, scale, limiter, loudness target,
ceiling, amount) and measures the mix.

The effects write into REAPER's shared memory; the HypnoMix bridge (`hypnomix reaper start`) gives each its slot and
keeps the blocks, and the app (or `hypnomix probe listen`) fetches them: the Live tab's meters, Record, the review
and `probe report` work the same as with Live: that review uses each probe's What it is, Priority and Protect, and
Main's target and ceiling. `probes cards SONG.rpp` reads the menus and the card back from the saved project, but
`scan` and `fix` on an .rpp do not use them yet (give the key with --key, and keep `fix` off a track with protect.tracks
in Preferences).
"""
import json
import os
import platform
import re
import shutil
import queue
import threading
import time
import uuid
from pathlib import Path

JSFX = Path(__file__).with_name("jsfx")
FILES = ("hypnomix_probe.jsfx", "hypnomix_main.jsfx", "hypnomix_meter.jsfx-inc", "hypnomix_ui.jsfx-inc")
INTERNAL = {"slot", "abgain", "guide"}               # set by hypnomix or by the window, not part of the card
PROBE_PATH, MAIN_PATH = "hypnomix/hypnomix_probe.jsfx", "hypnomix/hypnomix_main.jsfx"
TRACK_KEYS = ["role", "priority", "protect"]
MAIN_KEYS = ["genre", "key", "scale", "mode", "target", "ceiling", "amount"]


def resource_dir():
    """REAPER's resource folder (where Effects/ lives)."""
    env = os.environ.get("HYPNOMIX_REAPER_RESOURCES")
    if env:
        return Path(env)
    s = platform.system()
    if s == "Darwin":
        return Path.home() / "Library" / "Application Support" / "REAPER"
    if s == "Windows":
        return Path(os.environ.get("APPDATA", Path.home())) / "REAPER"
    return Path.home() / ".config" / "REAPER"


def install(dest=None):
    """Copy the effects into REAPER's Effects/hypnomix (only that folder is written). Returns it."""
    d = Path(dest) if dest else resource_dir() / "Effects" / "hypnomix"
    d.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        shutil.copyfile(JSFX / f, d / f)
    return d


# ---------------------------------------------------------------- menus: labels from the effects themselves
def menus():
    """{effect file: [(key, [labels] or None)]} read from the JSFX slider lines (one source of truth)."""
    out = {}
    for f in ("hypnomix_probe.jsfx", "hypnomix_main.jsfx"):
        rows = []
        for line in (JSFX / f).read_text(encoding="utf-8").splitlines():
            m = re.match(r"slider\d+:(\w+)=[^<]*<[^{>]*(\{([^}]*)\})?>(-?)", line)
            # every slider is hidden from REAPER's generic view (the effect draws its own); these are not the card
            if m and m.group(1) not in INTERNAL:
                rows.append((m.group(1), m.group(3).split(",") if m.group(3) else None))
        out[f] = rows
    return out


def _cards_from_values(values, rows):
    card = {}
    for (key, labels), v in zip(rows, values):
        try:
            x = float(v)
        except ValueError:
            continue
        card[key] = labels[int(round(x))] if labels and 0 <= int(round(x)) < len(labels) else x
    return card


def read_cards(path, cards_file=None):
    """The probes' menus and the song card, from a saved .rpp (the same shape as `probe.read_cards` for Live)."""
    from hypnomix.app.probe import signature
    from hypnomix.project import rpp
    root = rpp.load(path)
    mm = menus()
    out = {"tracks": {}, "song": {}}
    names = []

    def card_of(chain):
        for js in (chain.chunks("JS") if chain is not None else []):
            src = (js.tokens[1].replace("\\", "/") if len(js.tokens) > 1 else "").lower()
            kind = "hypnomix_main.jsfx" if src.endswith("hypnomix_main.jsfx") else \
                "hypnomix_probe.jsfx" if src.endswith("hypnomix_probe.jsfx") else None
            if kind:
                first = next((l for l in js.children if isinstance(l, rpp.Line)), None)
                return kind, _cards_from_values(first.tokens if first else [], mm[kind])
        return None, {}

    for tr in root.chunks("TRACK"):
        nm = tr.get("NAME", default="") or ""
        names.append(nm)
        kind, card = card_of(tr.chunk("FXCHAIN"))
        if kind == "hypnomix_probe.jsfx":
            out["tracks"][nm] = card
        elif kind == "hypnomix_main.jsfx":
            out["song"] = card
    kind, card = card_of(root.chunk("MASTERFXLIST"))
    if kind == "hypnomix_main.jsfx":
        out["song"] = card
    out["sig"] = signature(names)
    if cards_file and Path(cards_file).exists():
        kept = json.loads(Path(cards_file).read_text(encoding="utf-8")).get(out["sig"], {})
        if kept.get("chords"):
            out["song"]["chords"] = kept["chords"]
    return out


# ---------------------------------------------------------------- putting the probes in
def _js_chunk(path, values, indent):
    from hypnomix.project import rpp
    js = rpp.Chunk(["JS", path, ""], indent=indent)
    js.add(rpp.Line([" ".join(str(v) for v in values) + " " + " ".join(["-"] * (64 - len(values)))], indent=indent + "  "))
    js.children[-1].raw = indent + "  " + js.children[-1].tokens[0]
    return js


def _add_fx(chain, path, values):
    """Append a JSFX to an FXCHAIN / MASTERFXLIST chunk, the way REAPER writes one."""
    from hypnomix.project import rpp
    ind = chain._child_indent()
    for toks in (["BYPASS", 0, 0, 0],):
        chain.add(rpp.Line(toks, indent=ind))
    chain.add(_js_chunk(path, values, ind))
    for toks in (["FLOATPOS", 0, 0, 0, 0], ["FXID", "{" + str(uuid.uuid4()).upper() + "}"], ["WAK", 0, 0]):
        chain.add(rpp.Line(toks, indent=ind))


def insert(path, out=None):
    """A NEW project with a HypnoMix Probe last on every track (one already there is kept) and HypnoMix Main on the
    master. Every probe starts at "auto"; the card at "not set". Returns the new file."""
    from hypnomix.project import rpp
    path = Path(path)
    out = Path(out) if out else rpp.free_name(path.with_name(f"{path.stem} (probes).rpp"))   # a rerun: " 2", " 3" ...
    root = rpp.load(path)
    added = 0

    def has(chain, file):
        want = file.lower()
        return chain is not None and any(len(j.tokens) > 1 and j.tokens[1].replace("\\", "/").lower().endswith(want)
                                         for j in chain.chunks("JS"))

    for tr in root.chunks("TRACK"):
        chain = tr.chunk("FXCHAIN")
        if has(chain, "hypnomix_probe.jsfx"):
            continue
        if chain is None:
            chain = rpp.Chunk(["FXCHAIN"])
            first_item = next((k for k, c in enumerate(tr.children) if isinstance(c, rpp.Chunk) and c.name == "ITEM"), None)
            tr.add(chain, at=first_item)
            for toks in (["SHOW", 0], ["LASTSEL", 0], ["DOCKED", 0]):
                chain.add(rpp.Line(toks))
        _add_fx(chain, PROBE_PATH, [0, 0, 0, -1])
        added += 1
    master = root.chunk("MASTERFXLIST")
    if not has(master, "hypnomix_main.jsfx"):
        if master is None:
            master = rpp.Chunk(["MASTERFXLIST"])
            at = next((k for k, c in enumerate(root.children) if isinstance(c, rpp.Chunk) and c.name == "TRACK"), None)
            root.add(master, at=at)
            for toks in (["SHOW", 0], ["LASTSEL", 0], ["DOCKED", 0]):
                master.add(rpp.Line(toks))
        _add_fx(master, MAIN_PATH, [0, 0, 0, 0, -14, -1, 100, -1])
        added += 1
    rpp.save(root, out)
    return out, added


# ---------------------------------------------------------------- feeding the app's hub
_FEEDERS = {}


class NoApp(RuntimeError):
    pass


def handle(hub, ev, r):
    """One Record and review event from the bridge. start: the app opens a capture (or says it cannot); stop: the
    app closes the capture, has REAPER render the master for exactly what played, and reviews it."""
    fn = getattr(hub, "on_record", None)
    if fn is None:
        raise NoApp("no app to review it (start `hypnomix app`)")
    out = fn(ev, r)
    if ev.get("ev") == "stop":
        r.call("rec_status", code=4)
    return out


def feed(hub, interval=0.2):
    """Relay REAPER's probe blocks into a `probe.Hub` while the bridge runs (one thread per hub; quiet otherwise)."""
    if id(hub) in _FEEDERS:
        return _FEEDERS[id(hub)]
    stop = threading.Event()
    jobs = queue.Queue()

    def records():                                    # Record and review events, one at a time (a render takes a while)
        from hypnomix.reaper.client import Reaper, ReaperError
        while True:
            ev = jobs.get()
            r = Reaper(timeout=10.0)
            try:
                handle(hub, ev, r)
            except Exception as e:                    # tell Main, so the button does not hang on "rendering"
                try:
                    r.call("rec_status", code=3 if isinstance(e, NoApp) else 6)
                except (ReaperError, OSError):
                    pass
                print(f"record and review: {e}", flush=True)

    threading.Thread(target=records, daemon=True, name="reaper-record").start()

    def run():
        from hypnomix.app.probe import signature
        from hypnomix.reaper.client import Reaper, ReaperError
        r = Reaper(timeout=3.0)
        since = None
        while not stop.is_set():
            try:
                if not r.alive():
                    since = None
                    stop.wait(2.0)
                    continue
                d = r.call("probe_blocks", since=since if since is not None else 10 ** 12, rec=1)
                if since is None:                         # first contact: only what comes from now on
                    since = int(d.get("seq") or 0)
                else:
                    for b in d.get("blocks") or []:
                        hub.on_block(b["id"], b["name"], 1 if b["main"] else 0, b["beat"], b["playing"], b["fader"],
                                     b["pan"], b["sr"], *b["vals"])
                        since = max(since, int(b["seq"]))
                for ev in d.get("rec") or []:
                    jobs.put(ev)
                sig = signature(d.get("names") or [])
                for m in d.get("meta") or []:
                    params = m.get("params") if isinstance(m.get("params"), dict) else {}
                    hub.on_meta(m["id"], m["name"], 1 if m["main"] else 0, sig, json.dumps(params), "")
            except (ReaperError, OSError, ValueError, KeyError):
                stop.wait(1.0)
                continue
            stop.wait(interval)

    t = threading.Thread(target=run, daemon=True, name="reaper-probes")
    t.start()
    _FEEDERS[id(hub)] = stop
    return stop


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="hypnomix reaper probes", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["install", "insert", "cards"])
    ap.add_argument("project", nargs="?")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.cmd == "install":
        d = install()
        print(f"installed in {d}\nIn REAPER: Add FX → JS → HypnoMix Probe (last on each track), HypnoMix Main (on the "
              "master). Or `hypnomix reaper probes insert SONG.rpp` puts them on every track.")
        return
    if not a.project:
        ap.error(f"{a.cmd} needs a project (.rpp)")
    if a.cmd == "insert":
        out, n = insert(a.project, a.out)
        print(f"wrote {out}: {n} effect(s) added (every probe starts at 'auto'). Open it in REAPER; "
              "`hypnomix reaper start` and the app's Live tab show what they measure.")
    else:
        from hypnomix.app.probe import read_cards as cards
        print(json.dumps(cards(a.project), indent=1))
