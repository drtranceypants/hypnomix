"""Checks for numbers typed on the command line, shared by the commands.

Use them as `type=` in `add_argument`: a value that is not a finite number, or is outside the range, ends in ONE plain
sentence (argparse's own "error: argument --bpm: ..." line, exit code 2) instead of a traceback, a hang or a report
about a nonsense value.

    ap.add_argument("--bpm", type=A.number(20, 400))             # 20 to 400, finite
    ap.add_argument("--top", type=A.whole(1))                    # a whole number, at least 1
    ap.add_argument("--gap", type=A.number(above=0))             # more than 0
"""
import argparse
import math


def _n(x):
    """A bound as a person writes it: 4294967295, not 4.29497e+09; 0.5 stays 0.5."""
    return f"{int(x)}" if float(x).is_integer() and abs(x) < 1e15 else f"{x:g}"


def _words(lo, hi, above, integer):
    kind = "whole number" if integer else "number"
    if above is not None and hi is not None:
        return f"a {kind} above {_n(above)} and at most {_n(hi)}"
    if above is not None:
        return f"a {kind} above {_n(above)}"
    if lo is not None and hi is not None:
        return f"a {kind} from {_n(lo)} to {_n(hi)}"
    if lo is not None:
        return f"a {kind} of {_n(lo)} or more"
    if hi is not None:
        return f"a {kind} of {_n(hi)} or less"
    return f"a {kind}"


def number(lo=None, hi=None, above=None, integer=False):
    """An argparse `type=`: a finite number (a whole number with integer=True) that is at least `lo`, at most `hi`, and
    more than `above` when given. nan, inf and text are refused with a sentence that says what is expected."""
    def parse(text):
        want = _words(lo, hi, above, integer)
        try:
            v = int(text) if integer else float(text)
        except (TypeError, ValueError):
            raise argparse.ArgumentTypeError(f"'{text}' is not {want}") from None
        if isinstance(v, float) and not math.isfinite(v):
            raise argparse.ArgumentTypeError(f"'{text}' is not {want}")
        if ((lo is not None and v < lo) or (hi is not None and v > hi) or (above is not None and v <= above)):
            raise argparse.ArgumentTypeError(f"'{text}' is not {want}")
        return v
    parse.__name__ = "number"
    return parse


def whole(lo=None, hi=None):
    """An argparse `type=`: a whole number within the range."""
    return number(lo, hi, integer=True)


def positive():
    """An argparse `type=`: a finite number above 0."""
    return number(above=0)


def check(value, name, lo=None, hi=None, above=None, integer=False):
    """The same check for a value that did not come through argparse (a number inside a "KEY=VALUE" option). Returns
    the number; ends the program with one sentence naming the option when it is not acceptable."""
    try:
        return number(lo, hi, above, integer)(value)
    except argparse.ArgumentTypeError as e:
        raise SystemExit(f"{name}: {e}")


def live_set_only(path, command):
    """For commands that read Live sets (.als) only: a REAPER project, an Ardour session or a folder ends with one
    sentence that says what to do instead (it used to end in a gzip traceback, or in "do NOT open this set in Live")."""
    from pathlib import Path
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".rpp" or suffix == ".rpp-bak":
        what = "a REAPER project"
    elif suffix == ".ardour" or (p.is_dir() and any(p.glob("*.ardour"))):
        what = "an Ardour session"
    elif p.is_dir():
        what = "a folder"
    elif not p.exists():                       # a typo in the name is not "an error in the set"
        raise SystemExit(f"{command}: no such file: {path}; check the name and the folder, then try again.")
    else:
        return
    raise SystemExit(f"{command} reads Live sets (.als files), and {p.name} is {what}. For REAPER and Ardour projects, "
                     "`hypnomix scan` reads the project itself, and `hypnomix fix` reads the new project back after "
                     "writing it and lists any problem in fix-log.md.")
