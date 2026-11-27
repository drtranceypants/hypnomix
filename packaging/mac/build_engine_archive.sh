#!/bin/bash
# Package a HypnoMix Studio engine kit as the archive people add from Setup. It never uploads anything.
#
#   packaging/mac/build_engine_archive.sh KIT                   # the platform is read from the program inside the kit
#   packaging/mac/build_engine_archive.sh KIT mac-arm64         # or named: mac-arm64 (Apple silicon) or mac-intel
#   packaging/mac/build_engine_archive.sh KIT mac-arm64 OUT     # into the folder OUT (default: packaging/dist)
#
# KIT is the folder the DAW's own repository builds (`tools/osx_build --hypnomix`: bin/hypnomix-engine, lib/, share/, with
# COPYING and SOURCE.txt at the top). The engine is a separate program under the GNU General Public License (version 2 or
# later), built on Ardour; HypnoMix itself is MIT and holds none of its code. So the kit is REFUSED, before anything is
# written, unless check_kit.sh passes: the licence text (COPYING), the source notice (SOURCE.txt), no symbolic links, and
# no home path or login name of the builder inside any file.
#
# It writes OUT/HypnoMix-engine-<engine version>-<platform>.tar.gz (the same kit always gives the same bytes: sorted entries,
# fixed times and owners) and prints its size and SHA-256, and the lines to paste into hypnomix/app/engine_addon.json under
# "platforms". Then, by hand: upload the archive to the release, paste the lines, tag (see packaging/README.md).
# The engine version is the manifest's "engine" (set it first). Needs python3 (3.9 or newer).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
. "$here/check_kit.sh"
case "${1:-}" in -h|--help|"") sed -n '2,17p' "$0"; [ -n "${1:-}" ] && exit 0 || exit 1 ;; esac
kit="$1"; plat="${2:-}"; out="${3:-$repo/packaging/dist}"
check_kit "$kit" || { echo "nothing was written: the engine kit is not fit to ship"; exit 1; }
kit="$(cd "$kit" && pwd)"
archs="$(lipo -archs "$kit/lib/hypnomix-engine" 2>/dev/null || true)"
case "$plat" in
  "") case " $archs " in *" arm64 "*) plat=mac-arm64 ;; *" x86_64 "*) plat=mac-intel ;;
        *) echo "could not tell which Mac this kit is for: name it (mac-arm64 or mac-intel)"; exit 1 ;; esac ;;
  mac-arm64|arm64) plat=mac-arm64; [ -z "$archs" ] || case " $archs " in *" arm64 "*) ;; *) echo "the kit is built for '$archs', not arm64"; exit 1 ;; esac ;;
  mac-intel|x86_64|intel) plat=mac-intel; [ -z "$archs" ] || case " $archs " in *" x86_64 "*) ;; *) echo "the kit is built for '$archs', not Intel"; exit 1 ;; esac ;;
  *) echo "unknown platform $plat (mac-arm64 or mac-intel)"; exit 1 ;;
esac
[ -n "$archs" ] || echo "(could not read the program's architecture: trusting the name '$plat')"
PY="${HYPNOMIX_PYTHON:-python3}"
version="$(sed -n 's/^version = "\(.*\)"/\1/p' "$repo/pyproject.toml" | head -1)"
engine="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["engine"])' "$repo/hypnomix/app/engine_addon.json")"
name="HypnoMix-engine-$engine-$plat.tar.gz"
mkdir -p "$out"
res="$("$PY" "$here/pack_engine.py" "$kit" "$out/$name")" || exit 1
size="$("$PY" -c 'import json,sys; print(json.loads(sys.argv[1])["size"])' "$res")"
sha="$("$PY" -c 'import json,sys; print(json.loads(sys.argv[1])["sha256"])' "$res")"
echo "archive:  $out/$name"
echo "size:     $size bytes"
echo "sha256:   $sha"
echo
echo "Paste this under \"platforms\" in hypnomix/app/engine_addon.json (the address assumes the release v$version: change it if you upload elsewhere):"
echo
echo "    \"$plat\": {\"url\": \"https://github.com/drtranceypants/hypnomix/releases/download/v$version/$name\", \"sha256\": \"$sha\", \"size\": $size}"
echo
echo "Nothing was uploaded and the manifest was not changed. Upload the archive to the release by hand, paste the line, then tag."
