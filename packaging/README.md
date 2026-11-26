# Installers

One-click installers for people who don't use a terminal. Each one carries its own Python
([python-build-standalone](https://github.com/astral-sh/python-build-standalone), fetched by `uv`), hypnomix with
the `assistant` and `critique` extras, and an ffmpeg program. The GPL extras (`reference`, `plugins`) and the large
`ml` extra stay out: they are for source installs.

| file | built by | what it is |
|---|---|---|
| `Hypnomix-<v>-mac-arm64.dmg` / `-mac-x86_64.dmg` | `packaging/mac/build_dmg.sh [arm64\|x86_64]` | drag-to-Applications disk image; `Hypnomix.app` is `macapp/Hypnomix.swift` with Python inside `Contents/Resources/python` |
| `Hypnomix-<v>-windows-x64-setup.exe` | `packaging/windows/build.ps1` (on Windows; Inno Setup 6) | per-user install to `%LOCALAPPDATA%\Programs\Hypnomix`, Start menu entries, optional Live setup |

Output lands in `packaging/dist/` (ignored by git). Both Mac architectures build on one Apple silicon Mac.

## Releases

`.github/workflows/installers.yml` builds all three. Run it from the Actions tab for test builds (downloadable
artifacts), or push a tag to publish a release:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

The release also gets stable names (`Hypnomix-mac-arm64.dmg`, `Hypnomix-mac-intel.dmg`, `Hypnomix-windows-setup.exe`),
so `https://github.com/drtranceypants/hypnomix/releases/latest/download/<name>` always points at the newest one. The
Windows job installs the result silently, checks that the app answers, and uninstalls it.

A tagged release starts as a **draft**, so nobody gets it yet. `.github/workflows/scan-release.yml` then scans the
three installers with Microsoft Defender, ClamAV and VirusTotal (it waits for every engine's verdict), attaches
`SECURITY-SCAN.md`, and only if nothing is flagged publishes the draft as the latest release, the one the download
page and the app's updater follow. If anything is flagged, the release stays a draft and the run fails, naming the
engine. Tags can't be moved, so cut the next version: machine-learning engines sometimes flag one particular build of
unchanged code (v0.1.4's Apple silicon image got Microsoft's `Wacatac.B!ml`; two rebuilds of the same tag were clean).
To publish a draft by hand after reading the report: `gh release edit vX.Y.Z --draft=false --latest`.

VirusTotal is required for publishing: it needs a free API key stored as the repository secret `VT_API_KEY`. Without
it the scan run fails with a message saying so, the report is still attached, and the release stays a draft. Add the
secret, then run scan-release again from the Actions tab with the tag and "publish" ticked. The tag you give it must
look like `v0.1.1` (an optional `-suffix` is allowed); anything else is refused.

The workflows are locked down because they build and publish what people install: the build jobs get a read-only
token, only the release job can write, and every action is pinned to an exact commit (the version is in the comment
beside it). To update an action, look up the new release's commit and change both together. The optional Ableton
connector in `.mcp.json` is likewise pinned to one version of `ableton-mcp`.

## Signing

Unsigned installers work, but macOS Gatekeeper and Windows SmartScreen ask people to allow them once.

- **Mac**: with an Apple Developer ID (Apple Developer Program, $99 a year) set `HYPNOMIX_SIGN_ID` and
  `HYPNOMIX_NOTARY_PROFILE` (see the top of `build_dmg.sh`), or add the secrets listed at the top of the workflow.
  `mac/entitlements.plist` holds the hardened-runtime exceptions Python needs.
- **Windows**: set `HYPNOMIX_SIGNTOOL` to a signtool command line with a code-signing certificate. An OV
  certificate still shows SmartScreen until the file builds reputation; an EV certificate does not.

## What the app does on first run

The app opens its **guided setup** (`hypnomix/app/setup.py` + `setup.js`): how you want to work (the app alone, an
AI key, a local model, or a desktop AI app such as Claude Code), the provider and key, a connection test, the
Ableton Live connection (`hypnomix install`, on a click), and for desktop AI apps a `hypnomix` command plus an
agent folder. On Windows the installer's "Set up Ableton Live" box also runs `hypnomix install`.

## Updates

`hypnomix/app/update.py` asks the GitHub API for the latest release (at most daily; `~/.hypnomix/update.json`),
downloads this platform's stable-named asset into `~/.hypnomix/updates/`, and checks it against the release's
`SHA256SUMS.txt`. Installing starts a helper outside the server: on a Mac it mounts the `.dmg`, quits the app,
swaps `Hypnomix.app` in place and reopens it; on Windows it runs the setup with `/VERYSILENT` over the install
(Inno Setup keeps the folder and tasks) and starts the launcher with `--quiet`. The helper logs to
`~/.hypnomix/updates/update.log`. The Windows CI job tests an in-place update after its smoke test. For a local
test beside a running copy, `HYPNOMIX_PORT` and `HYPNOMIX_UPDATE_URL` (a releases JSON) point the app elsewhere; while
`HYPNOMIX_UPDATE_URL` is set, `http://127.0.0.1` and `http://localhost` addresses are also accepted, nothing else.

What the check protects against: a damaged download, and a file swapped on GitHub's download servers (the SHA-256 in
`SHA256SUMS.txt` must match; the app hashes the file again right before it runs the helper, and the helper once more
before it opens the image). Release names must be a plain version (ASCII digits and dots), and asset and checksum
addresses must be https on github.com in that same release's download folder,
`/drtranceypants/hypnomix/releases/download/<tag>/<file>`, with no encoded dots, slashes or `;` (redirects must stay on
https and end on github.com or `*.githubusercontent.com`; the system proxy settings are used). On a Mac the helper
runs `codesign --verify --deep --strict` on the new app and compares its `CFBundleShortVersionString` with the release
version, and keeps the old app if either fails: that shows the bundle is whole and is the version claimed, not who made it. What it does **not** protect against: anyone who
controls the GitHub release (they publish the installer and its checksum together), until installers are signed with
a publisher key the app checks. Nothing in the updater touches quarantine attributes.

