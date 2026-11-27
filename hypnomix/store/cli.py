#!/usr/bin/env python3
"""The HypnoMix store from the command line: free and open-source plug-ins, synths, instruments, drum kits and
sample packs, from their publishers' own downloads. The app's Store tab does the same with buttons.

macOS only for now: on another system this command says so and does nothing else (HYPNOMIX_STORE_ROOT, below, is
only for trying it out).

  hypnomix store                       list everything, with what is installed
  hypnomix store search reverb         search names, makers and descriptions
  hypnomix store search --kind synth --format CLAP --open
  hypnomix store list --mpe            only the items whose maker documents MPE (per-note pitch bend, pressure and slide)
  hypnomix store info surge-xt         licence, formats, source, and the exact download it would fetch
  hypnomix store install surge-xt      download (HTTPS, sha256-checked when known), unpack, copy into place
  hypnomix store install surge-xt --replace   also replace copies the store did not install (moved to its trash)
  hypnomix store install NAME --unverified    install a download that has no fingerprint to check it against (the plain
                                       install refuses it and says why; use this only if you trust the publisher's address)
  hypnomix store uninstall surge-xt    remove exactly what the store installed for it
  hypnomix store updates               which installed items have a newer release
  hypnomix store check                 validate the catalogue (for people adding items)

Plug-ins go into ~/Library/Audio/Plug-Ins/<VST3|Components|CLAP|LV2>/, content into ~/Music/Hypnomix Library/.
Downloads have limits (size, time, free disk space, and how far an archive may unpack), so a wrong or hostile file
stops early (an unpack may take 15 minutes plus a second per 2 MB, at most 2 hours; Ctrl-C or the app's Cancel stops it
sooner). Nothing from a download is run. Items that ship only as an installer package (.pkg), whether it is found inside
a disk image or archive or is the download itself, are kept (marked as downloaded from the internet) and opened in Apple's
Installer for you to read and run yourself; uninstall those with the publisher's instructions. `info` also shows a
catalogue item's note (what to know before installing it) and what its maker documents about MPE.
HYPNOMIX_STORE_ROOT=/a/folder puts every target under that folder instead (for trying it out).
"""
import argparse
import contextlib
import io
import shlex
import sys

from hypnomix.store import catalogue as C, install as I


def _row(it, st):
    s = st.get(it["id"], {})
    mark = "installed " + (s.get("version") or "") if s.get("installed") else ""
    oss = "open source" if it["open_source"] else "freeware"
    return f"  {it['id']:<26} {it['name']:<34} {it['kind']:<15} {it['licence']:<13} {oss:<12} {'MPE' if it.get('mpe') else '':<4}{mark}"


def _parser():
    """The command's own parser. No abbreviations: '--unv' is not '--unverified', so what the person approves on the
    Assistant's card is exactly what the command will do."""
    ap = argparse.ArgumentParser(prog="hypnomix store", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 allow_abbrev=False)
    ap.add_argument("action", nargs="?", default="list", choices=["list", "search", "info", "install", "uninstall", "updates", "check"])
    ap.add_argument("words", nargs="*")
    ap.add_argument("--kind", default="", choices=[""] + list(C.KINDS))
    ap.add_argument("--format", default="", choices=[""] + list(C.FORMATS))
    ap.add_argument("--open", action="store_true", help="open-source only")
    ap.add_argument("--mpe", action="store_true", help="only items whose maker documents MPE (per-note pitch bend, pressure and slide)")
    ap.add_argument("--licence", default="")
    ap.add_argument("--replace", action="store_true", help="replace copies the store did not install")
    ap.add_argument("--unverified", action="store_true",
                    help="install even though the download has no sha256 to be checked against (not verified)")
    return ap


def main():
    a = _parser().parse_args()
    if a.action == "check":
        data = C.load(check=False)
        errs = C.validate(data)
        print("\n".join(errs) if errs else f"catalogue OK: {len(data['items'])} items")
        sys.exit(1 if errs else 0)
    if not I.supported():                                   # a plain explanation, not a failure
        print(I.PLATFORM_NOTE)
        return
    try:
        its = C.items()
    except C.CatalogueError as e:
        sys.exit(str(e))
    if a.action in ("list", "search"):
        st = I.status(its)
        hits = C.search(its, " ".join(a.words), a.kind, a.format, a.licence, True if a.open else None, True if a.mpe else None)
        print("\n".join(_row(it, st) for it in hits) or "nothing matches")
        return
    if not a.words:
        sys.exit(f"hypnomix store {a.action} needs an item id (see hypnomix store list)")
    try:
        it = C.get(a.words[0])
        if a.action == "info":
            for k in ("name", "kind", "vendor", "licence", "open_source", "formats", "macos_arm64", "homepage", "about"):
                print(f"{k:>12}: {it[k]}")
            if it.get("credit"):
                print(f"{'credit':>12}: {it['credit']}")
            if it.get("mpe"):
                print(f"{'MPE':>12}: {it['mpe_note']}")
            if it.get("note"):
                print(f"{'note':>12}: {it['note']}")
            r = I.resolve(it)
            print(f"{'download':>12}: {r.get('url') or r.get('page')}\n{'version':>12}: {r.get('version')}\n"
                  f"{'sha256':>12}: {r.get('sha256') or 'not published: NOT VERIFIED, installing needs --unverified'}")
            print(f"{'installed':>12}: {I.status([it])[it['id']]}")
        elif a.action == "install":
            last = [0]

            def prog(phase, got=0, total=0):
                if phase == "download" and total and got - last[0] > total / 20:
                    last[0] = got
                    print(f"  downloading {got * 100 // total}%", flush=True)
                elif phase != "download":
                    print(f"  {phase}", flush=True)
            e = I.install(it, confirm_overwrite=a.replace, progress=prog, confirm_unverified=a.unverified)
            if e["method"] == "pkg":
                print(e["note"] + f"\n  installer: {e['installer']}" + ("" if e["opened"] else " (open it yourself)"))
            else:
                print("installed:\n  " + "\n  ".join(e["paths"]))
        elif a.action == "uninstall":
            gone = I.uninstall(it["id"])
            print("removed:\n  " + "\n  ".join(gone) if gone else "nothing left to remove; forgotten")
        elif a.action == "updates":
            for iid, s in I.status(its).items():
                if s.get("installed"):
                    u = I.check_update(C.get(iid))
                    print(f"  {iid:<26} {u['installed']} -> {u['latest']}" + ("  UPDATE" if u["update"] else ""))
    except I.NeedsConfirm as e:
        sys.exit(f"{e}\nRun again with --replace to replace them.")
    except I.NotVerified as e:
        sys.exit(f"{e}\nNothing was downloaded or installed. To install it anyway, run again with --unverified.")
    except (I.StoreError, KeyError) as e:
        sys.exit(str(e).strip('"'))


def card_text(command, args):
    """What the Assistant's approval card says for a store command, or None for the ordinary text (the command
    itself). An --unverified install says so in plain words: the person is about to accept a download nobody checked."""
    a = [str(x) for x in args]
    if command != "store":
        return None
    try:                                                    # decide with the command's own parser, wherever the flag sits
        with contextlib.redirect_stderr(io.StringIO()):
            ns = _parser().parse_args(a)
        risky = ns.action == "install" and ns.unverified
    except SystemExit:                                      # it would not run; but never show a plain card for something
        risky = any(len(x) >= 3 and "--unverified".startswith(x) for x in a if x.startswith("--"))   # that looks like the flag
    if risky:
        return ("hypnomix store " + " ".join(shlex.quote(x) for x in a) + "\n\nNOT VERIFIED: this download has no fingerprint (sha256) from its "
                "publisher to be checked against, so HypnoMix cannot tell whether the file is the one the publisher "
                "released. Say yes only if you trust where it comes from. (An installer package would run with "
                "administrator rights once you click through Apple's Installer.)")
    return None


if __name__ == "__main__":
    main()
