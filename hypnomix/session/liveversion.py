#!/usr/bin/env python3
"""Which Live saved this set, and has hypnomix been tested with it?

A Live set is a gzipped XML file whose first element, <Ableton>, says which Live saved it (Creator="Ableton Live
12.0.5", MinorVersion="12.0_12049"). hypnomix has been tested with Live 11 and Live 12. A later major version may
change the file format, so a tool that writes a NEW set from a set saved by a later major version refuses, unless
you say it may. Reading and scanning are never refused; they print one warning line.

  an older or equal version     passes silently
  a newer major version         refuses to write (a clear message); reading prints one warning line
  a version that cannot be read a one-line warning; the write goes ahead

To let a write through (you accept that the new set may not open in Live):
  HYPNOMIX_FORCE_LIVE_VERSION=1 hypnomix <command> ...
  or, in a command that has the flag, --force-live-version

For tools that write sets:
    from hypnomix.session import liveversion as LV
    LV.guard_write(root)                  # root = the <Ableton> element; exits with the message when refused
    LV.guard_write_text(xml_text)         # the same for a set held as text (before it is parsed)
    LV.check_write(root)                  # the same, raising LV.NewerLive instead (for code that handles errors)
    LV.add_force_flag(parser)             # one line: adds --force-live-version to an argparse parser
and for tools that read them:
    LV.warn_read(path_or_root)            # one warning line (once per set version per run), never refuses
"""
import argparse, gzip, os, re, sys

TESTED_MAJORS = (11, 12)                # the Live versions hypnomix has been tested with (README, docs/LIVE.md)
NEWEST_TESTED = max(TESTED_MAJORS)
ENV_FORCE = "HYPNOMIX_FORCE_LIVE_VERSION"
FORCE = False                           # set by allow(); the environment variable does the same
_TRUE = ("1", "true", "yes", "on")
_warned = set()


class NewerLive(Exception):
    """A set saved by a later major version of Live than hypnomix has been tested with (the message says what to do)."""


def parse(creator=None, minor=None):
    """(major, minor, patch, text) from the <Ableton> element's Creator ("Ableton Live 12.0.5") or, failing that,
    its MinorVersion ("12.0_12049"); None when neither names a Live version. Missing parts are 0."""
    m = re.search(r"Live\s+(\d+)((?:\.\d+)*)", creator or "")
    if not m:
        m = re.match(r"\s*(\d+)((?:\.\d+)*)", minor or "")
    if not m:
        return None
    nums = [int(m.group(1))] + [int(x) for x in m.group(2).split(".") if x]
    nums += [0] * (3 - len(nums))
    text = ".".join(str(x) for x in ([m.group(1)] + [x for x in m.group(2).split(".") if x]))
    return nums[0], nums[1], nums[2], text


def version_of(root):
    """The parsed Live version of an <Ableton> element (or of an ElementTree), or None."""
    if hasattr(root, "getroot"):
        root = root.getroot()
    return parse(root.get("Creator"), root.get("MinorVersion")) if root is not None else None


def read_header(path):
    """The Live version of a set file, read from its first few KB (no full parse); None when it cannot be read."""
    try:
        with gzip.open(path) as fh:
            head = fh.read(8192).decode("utf-8", "replace")
    except (OSError, EOFError, ValueError):
        return None
    m = re.search(r"<Ableton\b[^>]*>", head)
    if not m:
        return None
    attr = lambda k: (re.search(rf'\b{k}="([^"]*)"', m.group(0)) or [None, None])[1]
    return parse(attr("Creator"), attr("MinorVersion"))


def header_of_text(text):
    """The Live version from the first part of a set held as text (an unparsed .als body); None when it cannot be read."""
    m = re.search(r"<Ableton\b[^>]*>", (text or "")[:8192])
    if not m:
        return None
    attr = lambda k: (re.search(rf'\b{k}="([^"]*)"', m.group(0)) or [None, None])[1]
    return parse(attr("Creator"), attr("MinorVersion"))


def is_newer(ver):
    return ver is not None and ver[0] > NEWEST_TESTED


def tested_text():
    return f"Live {NEWEST_TESTED}"


def forced():
    return FORCE or os.environ.get(ENV_FORCE, "").strip().lower() in _TRUE


def allow():
    """Let writes from a newer Live's sets through for this run (and for any tool this run starts)."""
    global FORCE
    FORCE = True
    os.environ[ENV_FORCE] = "1"


def refusal_text(ver):
    return (f"this set was saved by Live {ver[3]}; hypnomix has been tested up to {tested_text()}: it will not write "
            f"a new set from it unless you set {ENV_FORCE}=1 (or pass --force-live-version, in a command that has "
            f"that flag), because the format may have changed. Reading and scanning still work.")


def _decide(ver, force):
    if ver is None:
        _warn_once("unreadable", "warning: hypnomix could not read which version of Live saved this set, so it cannot "
                   "tell whether the format is one it has been tested with; writing the new set anyway.")
    elif is_newer(ver) and not (forced() if force is None else force):
        raise NewerLive(refusal_text(ver))
    return ver


def check_write(root, force=None):
    """Raise NewerLive when `root` (the <Ableton> element) was saved by a newer major version of Live than the
    newest tested, unless forced. A version that cannot be read prints one warning line and passes."""
    return _decide(version_of(root), force)


def check_text(text, force=None):
    """check_write for a set that is still text (a tool that edits the XML as a string)."""
    return _decide(header_of_text(text), force)


def guard_write_text(text, force=None):
    """guard_write for a set held as text."""
    try:
        return check_text(text, force)
    except NewerLive as e:
        sys.exit(str(e))


def check_file(path, force=None):
    """check_write for a set file that has not been parsed (reads only its header)."""
    return _decide(read_header(path), force)


def guard_write(root, force=None):
    """check_write for command-line tools: on a refusal, exit with the message (as the other write guards do)."""
    try:
        return check_write(root, force)
    except NewerLive as e:
        sys.exit(str(e))


def warn_read(src):
    """One warning line on stderr when a set was saved by a newer major version of Live than the newest tested.
    Never refuses; says nothing about an older set or one whose version cannot be read. `src` is a path or the
    <Ableton> element. Once per version per run."""
    try:
        ver = read_header(src) if isinstance(src, (str, os.PathLike)) else version_of(src)
    except Exception:
        return None
    if is_newer(ver):
        _warn_once(("read", ver[3]), f"warning: this set was saved by Live {ver[3]}; hypnomix has been tested up to "
                   f"{tested_text()}. Reading and scanning work, but a new set written from it may not open in Live.")
    return ver


def _warn_once(key, text):
    if key not in _warned:
        _warned.add(key)
        print(text, file=sys.stderr)


class ForceAction(argparse.Action):
    """--force-live-version: lets a write from a newer Live's set through (sets the environment variable too)."""
    def __init__(self, option_strings, dest, **kw):
        kw.pop("nargs", None)
        super().__init__(option_strings, dest, nargs=0, default=False, **kw)

    def __call__(self, parser, namespace, values, option_string=None):
        allow()
        setattr(namespace, self.dest, True)


def add_force_flag(parser):
    parser.add_argument("--force-live-version", action=ForceAction, dest="force_live_version",
                        help=f"write a new set even though it was saved by a Live newer than {tested_text()}, "
                             "the newest hypnomix has been tested with (the format may have changed)")


def main():
    ap = argparse.ArgumentParser(prog="hypnomix liveversion", description="Which Live saved a set, and is that tested?")
    ap.add_argument("sets", nargs="+")
    for p in ap.parse_args().sets:
        v = read_header(p)
        print(f"{p}: " + ("version not readable" if v is None else
              f"Live {v[3]}, " + ("newer than the newest tested (" + tested_text() + ")" if is_newer(v) else "tested")))


if __name__ == "__main__":
    main()
