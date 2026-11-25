#!/bin/bash
# Build Hypnomix.app (a window around `hypnomix app`). Run from the repo:  macapp/build.sh
# Needs the Swift compiler (xcode-select --install). The app is built for this Mac and signed ad hoc:
# it runs here; to give it to someone else they build it themselves, or it must be signed and notarised.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(dirname "$here")"
out="$here/dist/Hypnomix.app"
py="$repo/.venv/bin/python"
[ -x "$py" ] || { echo "no $py: run the install steps first (uv venv && uv pip install -e .)"; exit 1; }
rm -rf "$out"
mkdir -p "$out/Contents/MacOS" "$out/Contents/Resources"
swiftc -O -o "$out/Contents/MacOS/Hypnomix" "$here/Hypnomix.swift" -framework Cocoa -framework WebKit
"$py" "$here/icon.py" "$out/Contents/Resources/Hypnomix.icns" || echo "(no icon: continuing)"
cat > "$out/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Hypnomix</string>
  <key>CFBundleDisplayName</key><string>Hypnomix</string>
  <key>CFBundleIdentifier</key><string>org.hypnomix.app</string>
  <key>CFBundleExecutable</key><string>Hypnomix</string>
  <key>CFBundleIconFile</key><string>Hypnomix</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>NSAppleEventsUsageDescription</key><string>hypnomix shows a file chooser so you can pick a song.</string>
  <key>HypnomixPython</key><string>$py</string>
</dict></plist>
PLIST
codesign --force --sign - "$out" >/dev/null 2>&1 || echo "(not signed: continuing)"
echo "built $out"
echo "open it, or drag it to Applications"
