"""Where hypnomix writes things. Override with HYPNOMIX_OUT / HYPNOMIX_HOME."""
import os
from pathlib import Path

OUT = Path(os.environ.get("HYPNOMIX_OUT", "hypnomix-out")).expanduser()          # reports, captures (relative to cwd)
HOME = Path(os.environ.get("HYPNOMIX_HOME", "~/.hypnomix")).expanduser()          # your profile lives here
PROFILE = HOME / "profile.json"


def out(*parts):
    p = OUT.joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


def out_at(custom, *parts):
    """--out if given (created), else hypnomix-out/<parts>."""
    if custom:
        p = Path(custom).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p
    return out(*parts)
