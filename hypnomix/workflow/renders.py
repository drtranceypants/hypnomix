"""hypnomix renders: the folder a song's renders go in, so exports don't pile up loose on the Desktop.

    hypnomix renders "Hollow"                     → ~/Desktop/HypnoMix/Hollow/ (created if missing)
    hypnomix renders "~/Music/Hollow Project/Hollow (recheck 3).als"
    hypnomix renders --root                        → ~/Desktop/HypnoMix

One folder per song, named after the set without version words ("v2", "(remix final)", " Project").
Point Live's or REAPER's export dialog here; the library scan and other commands look here for a song's mix.
Set HYPNOMIX_RENDERS to use another root folder.
"""
import argparse

from hypnomix.workflow import library as L


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix renders", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("song", nargs="?", help="a set (.als / .rpp), a project folder or a song's name")
    ap.add_argument("--root", action="store_true", help="print the root folder instead")
    a = ap.parse_args(argv)
    if a.root or not a.song:
        r = L.renders_root()
        r.mkdir(parents=True, exist_ok=True)
        print(r)
        return
    print(L.renders_dir(a.song))


if __name__ == "__main__":
    main()
