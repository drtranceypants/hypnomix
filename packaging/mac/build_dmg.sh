#!/bin/bash
# Build the Mac installer: Hypnomix-<version>-mac-<arch>.dmg, a drag-to-Applications disk image whose app
# carries its own Python, hypnomix (with the Assistant and Listening extras) and ffmpeg. Nothing else to install.
#
#   packaging/mac/build_dmg.sh            # this Mac's architecture
#   packaging/mac/build_dmg.sh x86_64     # an Intel build (works from an Apple silicon Mac too)
#
# There is ONE installer per platform. HypnoMix Studio (HypnoMix's own DAW, built on Ardour) is not inside the app: it is an
# add-on that people fetch once from Setup (hypnomix/app/engine_addon.py). Its engine is a separate program under the GNU
# General Public License (version 2 or later) and is packaged on its own by packaging/mac/build_engine_archive.sh.
#
#   packaging/mac/build_dmg.sh x86_64 --app-only DIR   # just DIR/Hypnomix.app, no disk image (e.g. to try it beside an installed copy)
#
# Needs uv and the Swift compiler (xcode-select --install). Output goes to packaging/dist/.
#
# Signing (optional; without it the app is signed ad hoc and macOS asks people to allow it once):
#   HYPNOMIX_SIGN_ID="Developer ID Application: Name (TEAMID)"   sign with your Developer ID
#   HYPNOMIX_NOTARY_PROFILE=hypnomix                             then notarise and staple, using a profile saved
#                                                               with: xcrun notarytool store-credentials hypnomix
set -euo pipefail
arch="" appout=""
here="$(cd "$(dirname "$0")" && pwd)"
while [ $# -gt 0 ]; do
  case "$1" in
    --app-only) appout="${2:?--app-only needs a folder for Hypnomix.app}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    -*) echo "unknown option $1 (the engine is no longer put inside the app: see packaging/mac/build_engine_archive.sh)"; exit 1 ;;
    *) arch="$1"; shift ;;
  esac
done
arch="${arch:-$(uname -m)}"
case "$arch" in arm64|aarch64) arch=arm64; pyarch=aarch64; target=arm64-apple-macos12; plat=aarch64-apple-darwin ;;
                x86_64)        pyarch=x86_64; target=x86_64-apple-macos12; plat=x86_64-apple-darwin ;;
                *) echo "unknown architecture $arch (arm64 or x86_64)"; exit 1 ;; esac
PYVER="${HYPNOMIX_PYTHON:-3.12}"
EXTRAS="assistant,critique"            # the GPL extras (reference, plugins) and the big ml one stay out

repo="$(cd "$here/../.." && pwd)"
version="$(sed -n 's/^version = "\(.*\)"/\1/p' "$repo/pyproject.toml" | head -1)"
dist="$repo/packaging/dist"
work="$repo/packaging/build/mac-$arch"
app="$work/Hypnomix.app"
res="$app/Contents/Resources"
dmg="$dist/Hypnomix-$version-mac-$arch.dmg"

echo "== HypnoMix $version for macOS $arch"
rm -rf "$work"; mkdir -p "$res" "$app/Contents/MacOS" "$dist"

echo "-- Python $PYVER (python-build-standalone, through uv)"
UV_PYTHON_INSTALL_DIR="$work/pythons" uv python install --no-bin "cpython-$PYVER-macos-$pyarch-none" >/dev/null
src="$(find "$work/pythons" -maxdepth 1 -type d -name "cpython-$PYVER*-macos-$pyarch-none" | head -1)"
[ -n "$src" ] || { echo "uv did not install Python $PYVER for $pyarch"; exit 1; }
cp -R "$src" "$res/python"
rm -rf "$work/pythons"
py="$res/python/bin/python3"
rm -f "$res/python/lib/python$PYVER/EXTERNALLY-MANAGED"
rm -rf "$res/python/lib/python$PYVER/"{test,idlelib,tkinter,turtledemo,ensurepip} "$res/python/lib/"{tcl*,tk*,itcl*,thread*} 2>/dev/null || true

echo "-- HypnoMix and its packages"
# numba/llvmlite: wheels only (newer llvmlite has no Intel Mac wheel; the resolver picks one that does)
uv pip install --quiet --python "$py" --python-platform "$plat" --no-cache --only-binary llvmlite --only-binary numba "$repo[$EXTRAS]" imageio-ffmpeg pip   # pip: Setup → Extras installs the other extras with it

echo "-- ffmpeg"
mkdir -p "$res/bin"
ff="$(find "$res/python/lib/python$PYVER/site-packages/imageio_ffmpeg/binaries" -name 'ffmpeg-*' -type f | head -1)"
[ -n "$ff" ] || { echo "no ffmpeg binary in imageio-ffmpeg"; exit 1; }
cp "$ff" "$res/bin/ffmpeg"; chmod +x "$res/bin/ffmpeg"
uv pip uninstall --quiet --python "$py" imageio-ffmpeg
find "$res/python" -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -f "$res/python/bin/"{hypnomix,pip*,idle*,pydoc*,2to3*} 2>/dev/null || true   # their #! lines point at this build folder

echo "-- the window (Swift)"
swiftc -O -target "$target" -o "$app/Contents/MacOS/Hypnomix" "$repo/macapp/Hypnomix.swift" -framework Cocoa -framework WebKit
iconpy="$repo/.venv/bin/python"; [ "$arch" = "$(uname -m | sed s/aarch64/arm64/)" ] && iconpy="$py"
[ -x "$iconpy" ] || iconpy="$py"
"$iconpy" "$repo/macapp/icon.py" "$res/Hypnomix.icns" >/dev/null 2>&1 || echo "   (no icon: continuing)"
find "$res/python" -name '__pycache__' -type d -prune -exec rm -rf {} +

mictext="HypnoMix records what Live plays (through BlackHole) for loop and diagnose, and HypnoMix Studio (if you add it) records from the audio input you choose."
cat > "$app/Contents/Info.plist" <<PLIST
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
  <key>CFBundleVersion</key><string>$version</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>NSAppleEventsUsageDescription</key><string>HypnoMix shows a file chooser so you can pick a song.</string>
  <key>NSMicrophoneUsageDescription</key><string>$mictext</string>
</dict></plist>
PLIST

echo "-- compiling Python files ahead (the app never writes inside itself)"
"$py" -m compileall -q -j 0 "$res/python/lib" >/dev/null 2>&1 || "$py" -m compileall -q "$res/python/lib" >/dev/null 2>&1 || true
# an Intel build made on Apple silicon runs its Python through Rosetta, or not at all: then it ships without .pyc

echo "-- signing"
# every Mach-O inside (Python, its packages and ffmpeg), innermost first, then the app; with a Developer ID under the hardened runtime, otherwise ad hoc
machos() {
  find "$res" -type f \( -name '*.so' -o -name '*.dylib' -o -perm -u+x \) -print0 |
    while IFS= read -r -d '' f; do if file -b "$f" | grep -q Mach-O; then printf '%s\t%s\0' "$(echo "$f" | tr -cd / | wc -c)" "$f"; fi; done |
    sort -z -t $'\t' -k1,1nr | while IFS= read -r -d '' l; do printf '%s\0' "${l#*$'\t'}"; done
}
if [ -n "${HYPNOMIX_SIGN_ID:-}" ]; then
  ent="$here/entitlements.plist"
  machos | while IFS= read -r -d '' f; do
    codesign --force --timestamp --options runtime --entitlements "$ent" --sign "$HYPNOMIX_SIGN_ID" "$f"
  done
  codesign --force --timestamp --options runtime --entitlements "$ent" --sign "$HYPNOMIX_SIGN_ID" "$app"
else
  n=0
  while IFS= read -r -d '' f; do codesign --force --sign - "$f" 2>/dev/null || { echo "could not sign $f"; exit 1; }; n=$((n + 1)); done < <(machos)
  codesign --force --sign - "$app"
  echo "   ad hoc: $n Mach-O files, then the app (set HYPNOMIX_SIGN_ID to sign with a Developer ID)"
fi
codesign --verify --deep --strict "$app"

if [ -n "$appout" ]; then
  mkdir -p "$appout"
  rm -rf "$appout/Hypnomix.app"
  ditto "$app" "$appout/Hypnomix.app"
  codesign --verify --deep --strict "$appout/Hypnomix.app"
  rm -rf "$work"
  echo "built $appout/Hypnomix.app ($(du -sh "$appout/Hypnomix.app" | cut -f1)); no disk image (--app-only)"
  exit 0
fi

echo "-- disk image"
stage="$work/dmg"; mkdir -p "$stage"
mv "$app" "$stage/"
ln -s /Applications "$stage/Applications"
rm -f "$dmg"
hdiutil create -quiet -volname "HypnoMix" -srcfolder "$stage" -fs HFS+ -format UDZO -imagekey zlib-level=9 "$dmg"
if [ -n "${HYPNOMIX_SIGN_ID:-}" ]; then
  codesign --force --timestamp --sign "$HYPNOMIX_SIGN_ID" "$dmg"
  if [ -n "${HYPNOMIX_NOTARY_PROFILE:-}" ]; then
    echo "-- notarising (a few minutes)"
    xcrun notarytool submit "$dmg" --keychain-profile "$HYPNOMIX_NOTARY_PROFILE" --wait
    xcrun stapler staple "$dmg"
  fi
fi
echo "built $dmg ($(du -h "$dmg" | cut -f1))"
