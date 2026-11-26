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
test beside a running copy, `HYPNOMIX_PORT` and `HYPNOMIX_UPDATE_URL` (a releases JSON) point the app elsewhere.

