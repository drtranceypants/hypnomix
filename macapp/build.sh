#!/bin/bash
# Build Hypnomix.app (a window around `hypnomix app`). Run from the repo:  macapp/build.sh
# Needs the Swift compiler (xcode-select --install). The app is built for this Mac and signed ad hoc:
# it runs here; to give it to someone else they build it themselves, or it must be signed and notarised.
#
#   macapp/build.sh --daw /path/to/HypnomixEngine   also embed the HypnoMix engine kit (the DAW's `osx_build --hypnomix`)
#                                                   in Contents/Resources/engine: the app opens on the DAW view
# (a test build for this Mac only, and never to give to anyone: the engine is under the GNU GPL and the kit must carry its
# licence text and a source notice, which this script only warns about. The engine people get is the add-on archive that
# packaging/mac/build_engine_archive.sh makes; the installer no longer carries it, and the app finds one in its bundle
# only for one more version)
set -euo pipefail
kit=""
if [ "${1:-}" = "--daw" ]; then kit="$(cd "${2:?--daw needs the engine kit folder}" && pwd)"; fi
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(dirname "$here")"
out="$here/dist/Hypnomix.app"
py="$repo/.venv/bin/python"
[ -x "$py" ] || { echo "no $py: run the install steps first (uv venv && uv pip install -e .)"; exit 1; }
version="$(sed -n 's/^version = "\(.*\)"/\1/p' "$repo/pyproject.toml" | head -1)"   # the same one build_dmg.sh and the updater use
[ -n "$version" ] || { echo "no version = \"...\" line in $repo/pyproject.toml"; exit 1; }
rm -rf "$out"
mkdir -p "$out/Contents/MacOS" "$out/Contents/Resources"
swiftc -O -o "$out/Contents/MacOS/Hypnomix" "$here/Hypnomix.swift" -framework Cocoa -framework WebKit
"$py" "$here/icon.py" "$out/Contents/Resources/Hypnomix.icns" || echo "(no icon: continuing)"
cat > "$out/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>HypnoMix</string>
  <key>CFBundleDisplayName</key><string>HypnoMix</string>
  <key>CFBundleIdentifier</key><string>org.hypnomix.app</string>
  <key>CFBundleExecutable</key><string>Hypnomix</string>
  <key>CFBundleIconFile</key><string>Hypnomix</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$version</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>NSAppleEventsUsageDescription</key><string>HypnoMix shows a file chooser so you can pick a song.</string>
  <key>HypnomixPython</key><string>$py</string>
</dict></plist>
PLIST
if [ -n "$kit" ]; then
  [ -x "$kit/bin/hypnomix-engine" ] || { echo "$kit is not a HypnoMix Studio engine kit (no bin/hypnomix-engine)"; exit 1; }
  # a build for this Mac only: the licence and home-path checks only warn here. The result must never be given to anyone
  # (packaging/mac/build_engine_archive.sh refuses such a kit).
  . "$repo/packaging/mac/check_kit.sh"
  check_kit "$kit" || echo "WARNING: this kit is not fit to ship (see above). This app is for this Mac only: do not give it to anyone."
  ditto "$kit" "$out/Contents/Resources/engine"
  find "$out/Contents/Resources/engine" -type f -print0 | while IFS= read -r -d '' f; do   # each Mach-O, then the app
    if file -b "$f" | grep -q Mach-O; then codesign --force --sign - "$f"; fi
  done
  codesign --force --sign - "$out" && codesign --verify --deep --strict "$out"
else
  codesign --force --sign - "$out" >/dev/null 2>&1 || echo "(not signed: continuing)"
fi
echo "built $out"
echo "open it, or drag it to Applications"
