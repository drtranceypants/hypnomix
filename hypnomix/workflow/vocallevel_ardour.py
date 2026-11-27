"""`hypnomix vocallevel` on a HypnoMix Studio session: the plan's moves written as automation (session/vocallevel.py
measures and plans; workflow/vocallevel_project.py reads the session).

  upper trims   (at most 4 dB) on each upper part's TRIM
  line evening  (at most 3 dB) on the vocal group's bus FADER when that bus carries only vocals and every vocal
                track is in it; else on each vocal track's FADER
Every change is one gentle S-curve (project/ardour_automation.py edge_points), checked against HypnoMix's
smooth-automation rules before it is written (engineer/automation_rules.py: S-curves, at most 3 dB from the original line (a trim
4), the steepest point under 7 dB/s, on the line at both ends, never a bus that carries a track that is not a vocal).

  --engine [URL]      into the open HypnoMix engine (automation_write: one engine undo step a track and control).
                      It must have this very session file open (ardour_groups.require_open)
  --apply NEW.ardour  a new snapshot in the session's folder (the original is never written); the open engine's
                      session is not changed

A control that already plays automation is left alone and listed (make those moves by hand), and so is one whose level
is not known (a fader at -inf: 0 dB is never assumed). Every point stays within 3 dB (a trim 4) of the lane's original
line, kept in the session's folder (engineer/automation_original.py). Checked by unit tests
and against the engine on the Dummy backend (tests/test_ardour_automation_live.py); not judged by ear.
"""
import sys
from pathlib import Path

from hypnomix.engineer import automation_rules as RULES
from hypnomix.project import ardour_automation as AA


def plan_controls(p, gains, group, vocals):
    """-> ([(track name, control, segs)], notes): where each move goes."""
    from hypnomix.workflow import vocallevel_project as VP
    gains = {k: list(v) for k, v in gains.items()}
    gg = gains.pop("__group__", [])
    out, notes = [], []
    for name, segs in gains.items():
        if any(abs(g) > 1e-3 for _, _, g in segs):
            out.append((name, "trim", segs))
    if not any(abs(g) > 1e-3 for _, _, g in gg):
        return out, notes
    bus = next((t for t in p.tracks if t.name == group), None) if group else None
    if bus is not None and bus.kind in ("folder", "return"):
        facts = AA.facts_of(p, bus)
        other = RULES.non_vocal(facts)
        inside = {f["name"] for f in facts["feeders"]}
        outside = [v for v in vocals if v not in inside]
        if not other and not outside:
            out.append((bus.name, "gain", gg))
            return out, notes
        if other:
            notes.append(f"{bus.name} also carries {', '.join(other[:6])}: its fader is not automated (it would ride "
                         "them with every vocal line); the line evening goes on each vocal track's fader instead")
        else:
            notes.append(f"{', '.join(outside)} not in {bus.name}: the line evening goes on each vocal track's fader")
    elif group:
        notes.append(f"{group} is not a bus: the line evening goes on each vocal track's fader")
    for v in vocals:
        if VP.find_track(p, v) is not None:
            out.append((VP.find_track(p, v).name, "gain", gg))
    return out, notes


def run(p, src, a, gains, vocals, melody):
    from hypnomix.workflow import vocallevel_project as VP
    group = a.group or VP.folder_of(p, melody)
    todo, notes = plan_controls(p, gains, group, vocals)
    for n in notes:
        print("  " + n)
    if not todo:
        print("nothing to change: nothing written")
        return 0
    done, refused = [], []
    if getattr(a, "engine", None) is not None:
        from hypnomix.project import ardour_groups as AG
        try:
            eng = AG.Engine(a.engine or None)
            if not eng.has("automation_list", "automation_write"):
                sys.exit(f"the engine at {eng.url} does not answer, or has no automation tools (an older HypnoMix "
                         f"engine); {AG.WHERE_URL}")
            if AG.require_open(eng, p.path):
                print("  note: the engine has unsaved changes, so the saved file may be behind it; each control is "
                      "read from the engine first")
            ids = {r.get("name"): r.get("id") for r in (eng.call("tracks_list", {}).get("tracks") or [])}
        except AG.EngineError as e:
            sys.exit(f"nothing written: {e}")
        for name, control, segs in todo:
            what = f"{name} {'trim' if control == 'trim' else 'fader'}"
            try:
                pts = AA.edge_points(segs, 0.0, cap=RULES.cap(RULES.kind(control)))
                if not pts:
                    continue
                if name not in ids:
                    raise ValueError("no such track in the engine's session")
                cur = _current(eng, ids[name], control)
                if cur is None:
                    raise ValueError(_unknown(control))
                pts = [(t, round(v + cur, 4)) for t, v in pts]
                r = AA.write_engine(eng, ids[name], control, pts)
                done.append(f"{what}: {_lines(segs)} line(s), {len(pts)} points, steepest "
                            f"{AA.steepest_of(r) if AA.steepest_of(r) is not None else RULES.steepest(pts):.1f} dB/s")
            except (ValueError, AG.EngineError) as e:
                refused.append(f"{what}: {e}")
        for r in refused:
            print(f"  not written: {r}")
        if done:
            print("wrote into the open session: " + "; ".join(done))
            print(f"  smooth S-curves (about {AA.RAMP_S:g} s each, the engine's cosine between the points); one undo "
                  f"step each. {AG.APP_NOTICES}.")
        return 1 if refused and not done else 0
    out = Path(a.apply)
    if out.parent == Path("") or str(out.parent) == ".":
        out = Path(p.path).parent / out.name
    if out.resolve().parent != Path(p.path).resolve().parent:
        sys.exit(f"--apply: a snapshot lives in its session's folder: give a name only, or a path in {Path(p.path).parent}")
    if out.exists():
        sys.exit(f"{out.name} already exists: choose a new name (nothing is ever overwritten)")
    for name, control, segs in todo:
        what = f"{name} {'trim' if control == 'trim' else 'fader'}"
        t = VP.find_track(p, name)
        try:
            if t is None:
                raise ValueError("no such track")
            al, ctl = AA._list_of(t.native, control)
            base = _stored_db(ctl)
            if base is None:
                raise ValueError(_unknown(control))
            pts = [(tt, round(v + base, 4)) for tt, v in AA.edge_points(segs, 0.0, cap=RULES.cap(RULES.kind(control)))]
            if not pts:
                continue
            n = AA.write_file(p, t, control, pts)
            done.append(f"{what}: {_lines(segs)} line(s), {n} points, steepest {RULES.steepest(pts):.1f} dB/s")
        except ValueError as e:
            refused.append(f"{what}: {e}")
    for r in refused:
        print(f"  not written: {r}")
    if not done:
        print(f"nothing written: {out.name} was not made")
        return 1 if refused else 0
    from hypnomix.project import ardour_edit as AE
    AE.save(p, out)
    errs = AE.check(src if Path(src).is_file() else p.path, out, automation=True)
    if errs:
        from hypnomix.project import rpp
        bad = rpp.free_name(out.with_name(out.stem + " (BROKEN, do not open).ardour.txt"))     # never over an earlier one
        out.replace(bad)
        print(f"check FAILED: the written snapshot is not sound. Renamed to {bad.name}; keep using the original.")
        for e in errs:
            print(f"  {e}")
        return 1
    print(f"wrote {out}: " + "; ".join(done))
    print(f"  smooth S-curves ({AA.RAMP_S:g} s, a point every 0.05 s); open it in HypnoMix Studio (File → Open, the snapshot)")
    return 0


def _lines(segs):
    return sum(1 for _, _, g in segs if abs(g) > 1e-3)


def _current(eng, rid, control):
    """The control's value in dB as the engine reports it; None when it is not known (silence, -inf, reads as null):
    never 0 dB in its place."""
    return RULES.current_of(eng.call("automation_list", {"track_id": str(rid)}), control)


def _stored_db(ctl):
    """The control's value in dB as the session file keeps it (a gain factor); None when it is not there, is not a
    number, or is silence."""
    import math
    try:
        g = float(ctl.get("value")) if ctl is not None and ctl.get("value") is not None else None
    except (TypeError, ValueError):
        return None
    return 20 * math.log10(g) if g is not None and math.isfinite(g) and g > 0 else None


def _unknown(control):
    what = "trim" if control == "trim" else "fader"
    return (f"its {what} level is not known (it reads as silence, -inf, or is not in the session), so nothing is "
            f"written: HypnoMix never assumes 0 dB; set the {what} to where it should sit, then run this again")
