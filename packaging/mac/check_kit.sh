#!/bin/bash
# Check a Hypnomix engine kit before it goes into an app other people will get:
#
#   packaging/mac/check_kit.sh KIT          # prints what is wrong and exits 1, or says the kit is fine
#
# build_dmg.sh --daw runs the same check first (and `build_dmg.sh --check-kit KIT` is only this check).
#
# The engine is a separate program under the GNU General Public License (version 2 or later): a rebranded fork of a free
# DAW. hypnomix itself is MIT and contains none of its code, but a download that carries the engine must carry its
# licence and say where its source is. So a kit is refused unless it has, at its top level:
#   COPYING      the GNU General Public License text
#   SOURCE.txt   the source notice: the licence ("GNU General Public License", version 2 or later), that the source is
#                available and where or when it is published (an address, or "the source will be published with the first
#                release that includes the engine"), and the version or commit the program was built from
# It is also refused if it has symbolic links (one could point out of the app), if either program is missing, or if the
# builder's home path or login name is inside any file (a build writes its configuration into the program, and that is
# then published in a public download): rebuild it with a neutral prefix (-ffile-prefix-map) or strip the string.

check_kit() {
  local kit="$1" bad=0 user hits
  [ -d "$kit" ] || { echo "no engine kit folder: $kit"; return 1; }
  if [ ! -x "$kit/bin/hypnomix-engine" ] || [ ! -x "$kit/lib/hypnomix-engine" ]; then
    echo "$kit is not a Hypnomix engine kit (no bin/hypnomix-engine and lib/hypnomix-engine): build it with tools/osx_build --hypnomix"
    return 1
  fi
  if [ ! -s "$kit/COPYING" ] || ! grep -q "GNU GENERAL PUBLIC LICENSE" "$kit/COPYING"; then
    echo "the engine kit has no licence text: COPYING (the GNU General Public License) must be at the top of the kit"; bad=1
  fi
  # the notice must name the licence, say it is version 2 (or later), say the source is available, and say WHERE or WHEN
  # (a URL, or the sentence "the source will be published with the first release that includes the engine") and WHICH
  # version the program was built from (a version number or a commit)
  if [ ! -s "$kit/SOURCE.txt" ] || ! grep -qi "general public licen[sc]e" "$kit/SOURCE.txt" \
     || ! grep -qiE "version 2|v2|gpl-?2|2 or later" "$kit/SOURCE.txt" || ! grep -qi "source" "$kit/SOURCE.txt" \
     || ! grep -qiE "https?://|will be published with the first release that includes the engine" "$kit/SOURCE.txt" \
     || ! grep -qiE "(version|commit|revision|built from)[^[:alnum:]]+[A-Za-z0-9._-]*[0-9a-f.]{4,}" "$kit/SOURCE.txt"; then
    echo "the engine kit has no source notice: SOURCE.txt must say the licence (GNU General Public License, version 2 or later), that the source is available and where or when it is published (an address, or \"the source will be published with the first release that includes the engine\"), and the version or commit the program was built from"; bad=1
  fi
  if find "$kit" -type l | grep -q .; then
    echo "the engine kit has symbolic links (a link could point out of the app): rebuild it with tools/osx_build --hypnomix"; bad=1
  fi
  user="$(id -un 2>/dev/null || true)"
  hits="$({ { grep -raoE "/Users/[A-Za-z0-9._-]+/" "$kit" 2>/dev/null | grep -v ":/Users/Shared/$" | cut -d: -f1; } || true
            if [ -n "${HOME:-}" ] && [ "$HOME" != "/" ]; then grep -rlaF -- "$HOME" "$kit" 2>/dev/null || true; fi
            if [ "${#user}" -ge 5 ]; then grep -rlawF -- "$user" "$kit" 2>/dev/null || true; fi
          } | sort -u)"
  if [ -n "$hits" ]; then
    echo "the engine kit has the builder's home path or login name inside it (public downloads must not):"
    echo "$hits" | sed "s|^$kit/|   |"
    echo "rebuild it with a neutral prefix (-ffile-prefix-map) or strip that text"; bad=1
  fi
  return $bad
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  [ $# -eq 1 ] || { sed -n '2,5p' "$0"; exit 1; }
  if check_kit "$1"; then echo "the engine kit is fine: licence text, source notice, no builder's path"; else exit 1; fi
fi
