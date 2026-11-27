"""Talk to the REAPER that is open: start the bridge, look at the project, list plug-ins and parameters.

  hypnomix reaper start           run the HypnoMix bridge inside REAPER (starts REAPER if it is closed). Nothing
                                  is installed and no setting is changed; it runs until REAPER quits or `stop`.
  hypnomix reaper stop
  hypnomix reaper status          is it running; REAPER version, open project, tempo, tracks
  hypnomix reaper tracks          tracks with their plug-ins, fader and pan
  hypnomix reaper fx [FILTER]     plug-ins REAPER has installed (e.g. `fx Rea`, `fx JS:`)
  hypnomix reaper params TRACK FX every parameter of one plug-in as the plug-in shows it (TRACK: name, number or
                                  master; FX: name or number)
  hypnomix reaper record          Record and review before export (the same as the button on HypnoMix Main): plays
                                  from the edit cursor while the probes listen; run it again or stop REAPER, and the
                                  HypnoMix app renders exactly what played and reviews it
  hypnomix reaper chain build [NAME] | match | save NAME | state
                                  the mastering chain (the same as the buttons on HypnoMix Main): build the stock
                                  chain of REAPER's own plug-ins (or a saved template) before Main, turn ReaLimit
                                  until the master hits the song card's target while REAPER plays, keep the chain
                                  as FXChains/hypnomix/NAME.RfxChain
  hypnomix reaper review          the HypnoMix Review panel in REAPER: step through the app's review, A / B / Blind
  hypnomix reaper align           the HypnoMix Align panel in REAPER: align a vocal stack (guide, parts, presets,
                                  protect, sync, pitch with the chord check, formant) into a NEW aligned project
  hypnomix reaper snapshot [OUT.json] | snapshot restore FILE | snapshot diff A B
                                  every track's fader, pan, mute, solo, sends and each plug-in's on/off state and
                                  parameters as JSON; put one back (one undo step); what changed, in plain words.
                                  An existing OUT.json is refused: nothing is ever overwritten
  hypnomix reaper loop --bars 33-40 [--ab "db Lead -2"] [--revert]
                                  render that stretch of the master, measure it, compare it with the previous take;
                                  --ab: one change, rendered before and after, B also at A's loudness;
                                  --revert (only with --ab) puts the mix back; a fader or send level must be
                                  within -150 to +12 dB
  hypnomix reaper diagnose [--bars 8]
                                  the loudest stretch with each top-level folder (or track) soloed: who owns the
                                  sub, the bass and the vocal band
  hypnomix reaper probes install|insert SONG.rpp|cards SONG.rpp
                                  HypnoMix Probe and HypnoMix Main for REAPER (JSFX): see `hypnomix reaper probes -h`

Every change the bridge makes is one undo step in REAPER, named "hypnomix: ...". See also `hypnomix chain`.
"""
import argparse
import json
import sys

from hypnomix.reaper.client import Reaper, ReaperError


def main():
    ap = argparse.ArgumentParser(prog="hypnomix reaper", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "probes":
        from hypnomix.reaper import probes
        return probes.main(_sys.argv[2:])
    if len(_sys.argv) > 1 and _sys.argv[1] == "review":
        from hypnomix.reaper import review
        return review.main(_sys.argv[2:])
    if len(_sys.argv) > 1 and _sys.argv[1] == "align":
        from hypnomix.reaper import align
        return align.main(_sys.argv[2:])
    if len(_sys.argv) > 1 and _sys.argv[1] in ("snapshot", "loop", "diagnose"):
        from hypnomix.reaper import mixer
        try:
            return getattr(mixer, "main_" + _sys.argv[1])(_sys.argv[2:])
        except ReaperError as e:
            sys.exit(str(e))
    ap.add_argument("cmd", choices=["start", "stop", "status", "tracks", "fx", "params", "probes", "review", "record", "chain",
                                    "align", "snapshot", "loop", "diagnose"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = Reaper()
    try:
        if a.cmd == "start":
            r.start()
            p = r.ping()
            print(f"bridge running in REAPER {p['reaper']}; project: {p['project'] or '(unsaved)'}")
            return
        if a.cmd == "record":
            out = r.call("record")
            print({"start": "recording the master from the edit cursor: run it again (or stop REAPER) to review",
                   "stop": "stopped: the HypnoMix app renders what played and reviews it",
                   "short": "stopped: under a second played, so there is nothing to review",
                   "no app": "the HypnoMix app is not relaying (start `hypnomix app`, with the bridge running)"}[out["did"]])
            return
        if a.cmd == "chain":
            return chain(r, a.args, a.json)
        if a.cmd == "stop":
            r.stop()
            print("bridge stopped")
            return
        if a.cmd == "status":
            if not r.alive():
                print("the bridge is not running (hypnomix reaper start)")
                sys.exit(1)
            out = r.ping()
        elif a.cmd == "tracks":
            out = r.tracks()
            if not a.json:
                for t in out:
                    fx = ", ".join(f["name"] + ("" if f["on"] else " (off)") for f in t["fx"])
                    print(f"{t['index']:3d}  {t['name']:<30} {20 * __import__('math').log10(max(t['volume'], 1e-9)):+6.1f} dB "
                          f"pan {t['pan']:+.2f}{'  MUTED' if t['mute'] else ''}" + (f"\n       fx: {fx}" if fx else ""))
                return
        elif a.cmd == "fx":
            out = r.installed(a.args[0] if a.args else "")
            if not a.json:
                print("\n".join(out))
                return
        else:
            if len(a.args) != 2:
                ap.error("params TRACK FX")
            out = r.params(*a.args)
            if not a.json:
                for p in out:
                    print(f"{p['index']:3d}  {p['name']:<28} {p['shown']}")
                return
        print(json.dumps(out, indent=1))
    except ReaperError as e:
        sys.exit(str(e))


STATES = {0: "idle", 1: "built", 2: "matching", 3: "matched", 4: "saved", 5: "no ReaLimit before HypnoMix Main",
          6: "matching stopped: REAPER stopped", 7: "cancelled", 8: "the master is silent", 9: "error (ReaScript console)",
          10: "matched as close as the limiter allows", 11: "no HypnoMix Main on the master",
          12: "nothing before HypnoMix Main to save", 13: "built from a template",
          14: "waiting for an answer in REAPER (a menu or a dialog)"}


def chain(r, args, as_json=False):
    """The mastering chain on HypnoMix Main, from a terminal (no dialogs: Build replaces without asking)."""
    what = args[0] if args else "state"
    if what == "build":
        out = r.call("chain_build", name=" ".join(args[1:]) or "HypnoMix stock", yes=1)
    elif what == "save":
        if len(args) < 2:
            sys.exit("hypnomix reaper chain save NAME")
        out = r.call("chain_save", name=" ".join(args[1:]))
    elif what == "match":
        out = r.call("chain_match")
    elif what == "state":
        out = r.call("chain_state")
    else:
        sys.exit("hypnomix reaper chain build [NAME] | match | save NAME | state")
    if as_json:
        print(json.dumps(out, indent=1))
        return
    print(STATES.get(int(out.get("state", 0)), out.get("state")))
    if what == "build":
        print(f"{out['added']} plug-ins before HypnoMix Main" + (f"; not set: {'; '.join(out['missing'])}" if out.get("missing") else ""))
    elif what == "save":
        print(f"{int(out['plugins'])} plug-ins → {out['dir']}")
    elif what == "state":
        for f in out["fx"]:
            print(f"  {f['renamed'] or f['name']}" + ("" if f["on"] else "  (off)"))
        print("templates: " + ", ".join(["HypnoMix stock"] + out.get("templates", [])))


if __name__ == "__main__":
    main()
