"""Programs HypnoMix calls that are not Python packages, and the one plain sentence for when one is missing.

    rubberband_path()       the `rubberband` program on this computer, or None
    need_rubberband()       its path; raises MissingToolError (cli.main() prints the sentence, exit code 2) when it is missing
"""
import platform
import shutil


class MissingToolError(RuntimeError):
    """A program HypnoMix needs is not installed: the message says how to get it on this computer."""


def rubberband_how():
    """How to get Rubber Band on this operating system."""
    sysname = platform.system()
    if sysname == "Darwin":
        return "install it with `brew install rubberband`"
    if sysname == "Windows":
        return ("download the free Rubber Band command-line program from breakfastquay.com/rubberband, unzip it and "
                "add its folder to your PATH")
    return "install it with your package manager (for example `sudo apt install rubberband-cli`)"


def rubberband_path():
    return shutil.which("rubberband")


def need_rubberband(what="this"):
    """The path of the `rubberband` program. Missing: MissingToolError with one sentence that says how to get it."""
    p = rubberband_path()
    if not p:
        raise MissingToolError(f"{what} needs Rubber Band (the `rubberband` program), which is not installed: "
                               f"{rubberband_how()}, then run this again")
    return p
