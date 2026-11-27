"""hypnomix report: write a problem report on this computer, show it, and help you send it yourself.

HypnoMix has no server of its own and never sends anything. This command writes the text a bug report needs (what
happened, what you expected, your version and setup, the last command or job and how it ended, the end of its log, the
last crash record, how many findings each tool made in the open scan) and prints it. Paths, file, track and song
names and API keys are hidden before anything is written ("<file 1>.wav", "<track 3>", "~"); `--names` keeps file and
track names when you think they help. It never contacts a DAW or the network.

  hypnomix report                       print the report it WOULD share; writes and sends nothing
  hypnomix report --what "..." --expected "..."     fill in the two parts only you can write
  hypnomix report --crash               the newest crash record, as a report (--crash 2: the one before it)
  hypnomix report --list                the crash records on this computer
  hypnomix report --out FILE            also save it as a new file (a folder: a new file in it)
  hypnomix report --copy                also put it on the clipboard (pbcopy, clip, wl-copy or xclip)
  hypnomix report --open                also copy it and open the project's new-issue page: paste it there

  --names                keep track and file names (default: hidden)
  --no-log  --no-crash  --no-scan       leave out the job's log, the crash record, the open scan's finding counts
  --scan DIR             take the finding counts from this scan folder (default: the newest in the app's folder)

Where reports go: the project's public issue tracker (github.com/drtranceypants/hypnomix/issues). Everything there is
public: read the report first and take out anything private. The new-issue page is opened with the template's name only;
no word of the report is ever put in an address. A crash record is saved by a command that hits a bug, in
<HypnoMix home>/crashes (the newest 20 are kept); delete the folder's files to remove them.
"""
import argparse
import sys
from pathlib import Path

from hypnomix.core import report as R


def _list(records):
    if not records:
        print("No crash records are saved on this computer.")
        return
    print(f"{len(records)} crash record(s), newest first (in {R.home_short(str(R.crash_dir()))}):")
    for n, r in enumerate(records, 1):
        print(f"  {n:>2}  {r.get('when', '')}  {r.get('where', ''):<5} {r.get('command', ''):<14} {r.get('exception', '')}")
    print("`hypnomix report --crash N` shows one as a report.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix report", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--what", default="", help="what happened, in your words")
    ap.add_argument("--expected", default="", help="what you expected instead")
    ap.add_argument("--names", action="store_true", help="keep track and file names in the report (default: hidden)")
    ap.add_argument("--no-log", action="store_true", help="leave out the end of the last job's log")
    ap.add_argument("--no-crash", action="store_true", help="leave out the last crash record")
    ap.add_argument("--no-scan", action="store_true", help="leave out the open scan's finding counts")
    ap.add_argument("--scan", metavar="DIR", help="the scan folder to take the finding counts from")
    ap.add_argument("--crash", nargs="?", const=1, type=int, metavar="N", help="report on the newest crash record (or the N-th newest)")
    ap.add_argument("--list", action="store_true", help="list the crash records on this computer")
    ap.add_argument("--out", metavar="FILE", help="also save the report as a new file (a folder: a new file in it)")
    ap.add_argument("--copy", action="store_true", help="also put the report on the clipboard")
    ap.add_argument("--open", action="store_true", help="also copy it and open the project's new-issue page in your browser")
    a = ap.parse_args(argv)

    if a.list:
        return _list(R.crashes())
    include = [p for p, off in (("log", a.no_log), ("crash", a.no_crash), ("scan", a.no_scan)) if not off]
    crash_id = None
    if a.crash is not None:
        rec = R.crash(a.crash) if a.crash >= 1 else None
        if not rec:
            have = len(R.crashes())
            sys.exit("no crash record is saved on this computer" if not have else
                     f"there is no crash record number {a.crash}: {have} {'is' if have == 1 else 'are'} saved (`hypnomix report --list`)")
        crash_id = rec["id"]
        if a.no_crash:
            include.append("crash")                 # asking for a crash record by name wins over --no-crash
    out_path = None
    if a.out:
        from hypnomix.core import paths
        paths.check_out(a.out)
        t = Path(a.out).expanduser()
        if t.exists() and not t.is_dir():
            sys.exit(f"'{t}' already exists: HypnoMix never writes over a file; choose a new name with --out")
        out_path = t
    r = R.compose("crash" if crash_id else "bug", a.what, a.expected, include, a.names, scan_dir=a.scan, crash_id=crash_id)
    text = r["text"]
    print(text, end="")
    note = []
    if out_path is not None:
        p = R.save_report(text, out_path, "hypnomix-report") if out_path.is_dir() else _write_new(out_path, text)
        note.append(f"saved as {p}")
    if a.copy or a.open:
        done, how = R.copy_text(text)
        note.append("copied to the clipboard" if done else f"NOT copied: {how}")
    if a.open:
        if R.open_issue_page():
            note.append("opened the project's new-issue page in your browser: paste it there"
                        if "NOT copied" not in " ".join(note) else
                        "opened the project's new-issue page in your browser: paste it there (it was not copied: save it with --out and attach it)")
        else:
            note.append(f"could not open a browser: go to {R.ISSUE_URL.split('?')[0].replace('/new', '')} and open a new issue, then paste the report")
    if note:
        print("\n".join(note), file=sys.stderr)
    else:
        print("\nThat is the report HypnoMix would share. Nothing was written and nothing was sent. Read it, then:\n"
              "  --out FILE saves it, --copy copies it, --open copies it and opens the issue page (paste it there).\n"
              f"Reports go to {R.ISSUES}: it is public, so take out anything private first.", file=sys.stderr)


def _write_new(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


if __name__ == "__main__":
    main()
