"""`hypnomix motion` on a HypnoMix Studio session: filter sweeps, as options, written as plug-in automation.

  hypnomix motion SESSION.ardour [--mix MIX.wav] [--json OUT.json]                              the options
  hypnomix motion SESSION.ardour [--mix MIX.wav] --ids motion-1,motion-3 (--engine [URL] | --apply NEW.ardour)

The moves are the sweeps of `motion` on a Live set, on the filter plug-ins the session already has (a parameter whose
name says cut-off or frequency; never a new plug-in), measured in octaves from where the filter sits:
  riser   into a section: a low-pass opens from `depth` x 8 octaves below where it sits up to it, landing on the
          section's first downbeat; a high-pass sweeps up and snaps back on the downbeat
  dip     inside a section of 16 bars or more: a low-pass dips down (a high-pass up) and back over 8 bars
  drift   across a song of 64 bars or more: the filter wanders slowly, a point every 16 bars, never the same twice
Lengths and depths come from your learned style (`hypnomix motion --learn`), else gentle defaults. Sections come
from --mix (the same section finder as `hypnomix sections`), else 8-bar blocks. Bars follow the session's tempo map
(ramps exactly).

Nothing is written by default: every move is an option (--ids). All the moves chosen for one control are ONE write:
into the open engine (--engine: automation_write, one engine undo step; it must have this very session open) or a new
snapshot in the session's folder (--apply NEW.ardour). A control that already has automation is never offered (your
moves are intent). A bus's filter is preferred (one sweep moves a whole group), but never a bus, a group's bus or the
master that carries a track that is not a vocal: its plug-in automation is never written (it would move those tracks
too), so motion skips it, says which buses it skipped and why, and uses the next filter (a bus of vocals only, else a
track's). Filter moves are not level moves; the reverb and delay throws and swells of a Live set are, on sends, and
motion does not write them in HypnoMix Studio (a throw is far steeper than the smooth-automation rules allow): make
those by hand.
"""
import json
import math
import re
import sys
from pathlib import Path

from hypnomix.engineer import automation_rules as RULES
from hypnomix.project import ardour_automation as AA

FREQ = re.compile(r"cut ?-?off|freq", re.I)
HIGHPASS = re.compile(r"high ?-?pass|\bhpf?\b|low ?-?cut", re.I)
OCTAVES = 8.0
EPS_S = 0.01


def _others(facts, read=None):
    """What a route carries that is not a vocal (automation_rules.non_vocal; [] for a track or a bus of vocals only)."""
    return RULES.non_vocal(facts, read)


def _safe(eng):
    """eng.call as non_vocal's reader: None (counts as not only vocals) when a feeding bus cannot be read."""
    def read(tool, args):
        try:
            return eng.call(tool, args)
        except Exception:
            return None
    return read


def targets_engine(eng):
    """Filter frequency parameters the open session has and nothing automates: [target]. Each carries `others`: what
    its route carries that is not a vocal (a bus that does is never swept: propose skips it and says so)."""
    out = []
    for r in eng.call("tracks_list", {}).get("tracks") or []:
        try:
            facts = eng.call("automation_list", {"track_id": str(r.get("id"))})
        except Exception:
            continue
        others = None
        for c in facts.get("controls") or []:
            name = str(c.get("parameterName") or c.get("name") or "")
            if c.get("kind") != "plugin" or not FREQ.search(name) or c.get("points") or c.get("toggled"):
                continue
            if not isinstance(c.get("current"), (int, float)) or c["current"] <= 0:
                continue
            if others is None:
                others = _others(facts, _safe(eng))
            out.append(dict(track=facts.get("trackName") or r.get("name"), route=str(r.get("id")), control=c["control"],
                            label=f"{c.get('pluginName') or 'plug-in'}: {name}", base=float(c["current"]),
                            lo=float(c.get("min") or 20.0) if (c.get("min") or 0) > 0 else 20.0,
                            hi=float(c.get("max") or 20000.0), high=bool(HIGHPASS.search(name)),
                            bus=r.get("type") == "bus", others=others))
    return out


def targets_file(p):
    """The same, read from the session file (what a bus carries: what feeds it in the file, as the file writer reads it)."""
    out = []
    for t in p.tracks:
        rt = t.native
        if rt is None:
            continue
        for pr in rt.findall("Processor"):
            if pr.get("type") in ("amp", "trim", "intsend", "send", "meter", "main-outs", "diskreader", "diskwriter",
                                  "triggerbox", "polarity", "intreturn", "monitor", None):
                continue
            for c in pr.findall("Controllable"):
                name, idx = c.get("name") or "", c.get("parameter")
                if idx is None or not FREQ.search(name) or "Toggle" in (c.get("flags") or ""):
                    continue
                try:
                    base = float(c.get("value"))
                except (TypeError, ValueError):
                    continue
                al = next((x for x in pr.iter("AutomationList") if x.get("automation-id") == f"parameter-{idx}"), None)
                if base <= 0 or al is None or (al.findtext("events") or "").strip() or al.get("state", "Off") != "Off":
                    continue
                out.append(dict(track=t.name, route=rt.get("id"), control=f"plugin:{pr.get('id')}:{idx}",
                                label=f"{pr.get('name')}: {name}", base=base, lo=20.0, hi=20000.0,
                                high=bool(HIGHPASS.search(name)), bus=t.kind in ("folder", "return", "master"),
                                others=_others(AA.facts_of(p, t))))
    return out


def allowed(tg_list):
    """-> (the targets motion may sweep, the ones it skips: [dict(track, label, others, why)]). A bus, a group's bus or
    the master that carries a track that is not a vocal is skipped: its plug-in automation is never written."""
    ok, skipped = [], []
    for t in tg_list:
        others = t.get("others") or []
        if others:
            skipped.append(dict(track=t["track"], label=t["label"], others=list(others),
                                why=RULES.mixed_bus({"trackName": t["track"]}, others, "plugin")))
        else:
            ok.append(t)
    return ok, skipped


def _oct(tg, f, octaves):
    return float(min(tg["hi"], max(tg["lo"], f * 2.0 ** octaves)))


def points(move, tg, a, b, prm):
    """[(seconds, value)] for one move between section times a and b (seconds); bar = seconds a bar."""
    base, bar = tg["base"], prm["bar"]
    depth = OCTAVES * prm["depth"]
    if move == "riser":
        s = b - prm["bars"] * bar
        if tg["high"]:
            return [(s, base), (b - EPS_S, _oct(tg, base, depth)), (b, base)]
        return [(s, _oct(tg, base, -depth)), (b, base)]
    if move == "dip":
        L = prm["bars"] * bar
        s = a + max(0.0, ((b - a) - L) / 2) // bar * bar
        low = _oct(tg, base, depth if tg["high"] else -depth)
        return [(s, base), (s + 0.4 * L, low), (s + 0.6 * L, low), (s + L, base)]
    if move == "drift":
        shape = [0.0, 0.55, 0.2, 0.85, 0.35, 0.65, 0.1, 0.0]
        step = 16 * bar
        n = max(2, int((b - a) // step) + 1)
        sign = 1 if tg["high"] else -1
        return [(a + i * step, _oct(tg, base, sign * (shape[i % len(shape)] if i < n - 1 else 0.0) * depth)) for i in range(n)]
    raise ValueError(move)


def propose(p, tg_list, mix=None, style=None):
    """-> (findings, meta). Each finding carries its move (target, points). A bus's filter is preferred, but a target
    whose route carries a track that is not a vocal is never used: meta["skipped"] names each one and why."""
    from hypnomix.project import ardour as AR
    from hypnomix.session import motion as MO
    tempo = float(p.tempo)
    bpb = int(round(p.beats_per_bar or 4))
    clock, *_ = AR.tempo_map(p.native, p.sample_rate, AR.session_version(p.native), [])
    nbars = max(1, int(math.ceil(clock.s_to_beats(p.end()) / bpb)))
    secs, how = MO.sections_from(mix, tempo, nbars)
    at = lambda bar: clock.beats_to_s((bar - 1) * bpb)
    bar_s = lambda bar: at(bar + 1) - at(bar)
    tg_list, skipped = allowed(tg_list)
    if not tg_list:
        return [], dict(tempo=tempo, sections=secs, how=how, learned=bool(style), skipped=skipped)
    first = sorted(tg_list, key=lambda t: (not t["bus"], t["high"]))[0]
    other = next((t for t in tg_list if t is not first), first)
    moves = []
    for s in secs[1:]:
        prm = MO.params_for("riser", style)
        if s["a"] - 1 >= prm["bars"]:
            moves.append(("riser", first, at(s["a"] - prm["bars"]), at(s["a"]), dict(prm, bar=bar_s(s["a"] - 1)), s))
    for s in secs:
        prm = MO.params_for("dip", style)
        if s["b"] - s["a"] >= 16:
            moves.append(("dip", other, at(s["a"]), at(s["b"]), dict(prm, bar=bar_s(s["a"])), s))
    if nbars >= 64 and other is not first:
        prm = MO.params_for("drift", style)
        moves.append(("drift", first, at(1), at(nbars + 1), dict(prm, bar=bar_s(1)), dict(a=1, b=nbars + 1, label="song")))
    fs, n = [], 0
    for mv, tg, a, b, prm, s in moves:
        pts = points(mv, tg, a, b, prm)
        n += 1
        words = {"riser": "opens into", "dip": "dips inside", "drift": "drifts across"}[mv]
        fs.append(dict(id=f"motion-{n}", tool="motion", kind=f"motion-{mv}", severity="low", track=tg["track"],
                       where=f"bars {s['a']}-{s['b'] - 1}" if mv != "riser" else f"into bar {s['a']}",
                       problem=f"section {s.get('label', '?')} repeats without movement",
                       fix=f"{tg['label']} on {tg['track']} {words} the section over {prm['bars']} bars "
                           f"({min(v for _, v in pts):.0f} to {max(v for _, v in pts):.0f} Hz). An option: nothing is "
                           "written unless you pick it",
                       applies="motion", move=dict(move=mv, route=tg["route"], control=tg["control"], track=tg["track"],
                                                   points=[[round(t, 6), round(v, 3)] for t, v in pts])))
    return fs, dict(tempo=tempo, sections=secs, how=how, learned=bool(style), skipped=skipped)


def merged(fs, want):
    """The chosen moves, one point list per control (sorted, no two moves overlapping): {(route, control): [..]}."""
    by = {}
    for f in fs:
        if f["id"] in want:
            m = f["move"]
            by.setdefault((m["route"], m["control"], m["track"]), []).append([tuple(x) for x in m["points"]])
    out = {}
    for key, runs in by.items():
        runs.sort()
        for r0, r1 in zip(runs, runs[1:]):
            if r1[0][0] < r0[-1][0] + EPS_S:
                raise ValueError(f"two of the chosen moves overlap on {key[2]}: pick one of them")
        out[key] = [pt for r in runs for pt in r]
    return out


def main(a):
    from hypnomix import project as PJ
    src = Path(a.als)
    p = PJ.load(src)
    style = json.loads(Path(a.style).read_text(encoding="utf-8", errors="replace")) if Path(a.style).exists() else None
    eng = None
    if getattr(a, "engine", None) is not None:
        from hypnomix.project import ardour_groups as AG
        try:
            eng = AG.Engine(a.engine or None)
            if not eng.has("automation_list", "automation_write"):
                sys.exit(f"the engine at {eng.url} does not answer, or has no automation tools (an older HypnoMix "
                         f"engine); {AG.WHERE_URL}")
            AG.require_open(eng, p.path)
            tg = targets_engine(eng)
        except AG.EngineError as e:
            sys.exit(f"nothing written: {e}")
    else:
        tg = targets_file(p)
    fs, meta = propose(p, tg, a.mix, style)
    ok = [t for t in tg if not t.get("others")]
    print(f"{src.name}: {meta['tempo']:g} BPM, {len(meta['sections'])} sections ({meta['how']}); filters to move: "
          + (", ".join(f"{t['label']} on {t['track']}" for t in ok) or "none")
          + ("" if meta["learned"] else "; gentle defaults (nothing learned yet)"))
    for s in meta.get("skipped") or []:
        print(f"  skipped {s['label']} on {s['track']}: {s['why']}")
    for f in fs:
        print(f"  {f['id']:<10} {f['where']:<14} {f['fix'].split('. An option')[0]}")
    if not fs:
        print("  no moves to offer (no filter plug-in with a cut-off or frequency that nothing automates yet"
              + (", on a track or a bus of vocals only" if meta.get("skipped") else "") + ")")
    if a.json:
        if Path(a.json).exists():
            sys.exit(f"{Path(a.json).name} already exists: choose a new name for --json (nothing is ever overwritten)")
        Path(a.json).write_text(json.dumps({"tool": "motion", "set": str(src), "findings": fs, "meta": meta}, indent=1,
                                           default=str), encoding="utf-8")
    if eng is None and not a.apply:
        return 0
    want = {x.strip() for x in (a.ids or "").split(",") if x.strip()}
    if not want:
        sys.exit("say which moves: --ids motion-1,motion-3 (every move is an option; none is applied by default)")
    unknown = want - {f["id"] for f in fs}
    if unknown:
        sys.exit(f"{', '.join(sorted(unknown))} is not among the options listed, so nothing was written")
    try:
        todo = merged(fs, want)
    except ValueError as e:
        sys.exit(str(e))
    done, refused = [], []
    if eng is not None:
        from hypnomix.project import ardour_groups as AG
        for (route, control, track), pts in todo.items():
            try:
                AA.write_engine(eng, route, control, pts)
                done.append(f"{track}: {len(pts)} points")
            except (ValueError, AG.EngineError) as e:
                refused.append(f"{track}: {e}")
        for r in refused:
            print(f"  not written: {r}")
        if done:
            print("wrote into the open session: " + "; ".join(done) + f" (one undo step each). {AG.APP_NOTICES}.")
        return 1 if refused else 0
    out = Path(a.apply)
    if out.suffix.lower() != ".ardour":
        sys.exit("--apply writes a new snapshot of this session: give it a name ending in .ardour")
    if str(out.parent) in ("", "."):
        out = Path(p.path).parent / out.name
    if out.resolve().parent != Path(p.path).resolve().parent:
        sys.exit(f"--apply: a snapshot lives in its session's folder: give a name only, or a path in {Path(p.path).parent}")
    if out.exists():
        sys.exit(f"{out.name} already exists: choose a new name (nothing is ever overwritten)")
    for (route, control, track), pts in todo.items():
        t = next((x for x in p.tracks if x.native is not None and x.native.get("id") == route), None)
        try:
            if t is None:
                raise ValueError("no such route")
            n = AA.write_file(p, t, control, pts)
            done.append(f"{track}: {n} points")
        except ValueError as e:
            refused.append(f"{track}: {e}")
    for r in refused:
        print(f"  not written: {r}")
    if not done:
        print(f"nothing written: {out.name} was not made")
        return 1
    from hypnomix.project import ardour_edit as AE
    AE.save(p, out)
    errs = AE.check(p.path, out, automation=True)
    if errs:
        from hypnomix.project import rpp
        bad = rpp.free_name(out.with_name(out.stem + " (BROKEN, do not open).ardour.txt"))     # never over an earlier one
        out.replace(bad)
        print(f"check FAILED: the written snapshot is not sound. Renamed to {bad.name}; keep using the original.")
        for e in errs:
            print(f"  {e}")
        return 1
    print(f"wrote {out}: " + "; ".join(done) + "; structure check OK")
    return 0
