#!/usr/bin/env python3
"""Write an engine kit as one deterministic archive (called by build_engine_archive.sh; nothing is uploaded).

    python3 packaging/mac/pack_engine.py KIT OUT.tar.gz

The same kit gives the same bytes: sorted entries, one fixed time, no owners, plain modes, no file name or time in the gzip
header. The kit is checked first (the engine program, the licence text, the source notice, no symbolic links, no home path
or login name of this computer inside any file). Prints the archive's size and SHA-256 as JSON."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hypnomix.app import engine_addon as EA      # noqa: E402


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    try:
        print(json.dumps(EA.pack(argv[0], argv[1])))
    except EA.AddonError as e:
        print(f"nothing was written: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
