# Installers

One-click installers for people who don't use a terminal. Each one carries its own Python
([python-build-standalone](https://github.com/astral-sh/python-build-standalone), fetched by `uv`), hypnomix with
the `assistant` and `critique` extras, and an ffmpeg program. The GPL extras (`reference`, `plugins`) and the large
`ml` extra stay out: they are for source installs.

| file | built by | what it is |
|---|---|---|
| `Hypnomix-<v>-mac-arm64.dmg` / `-mac-x86_64.dmg` | `packaging/mac/build_dmg.sh [arm64\|x86_64]` | drag-to-Applications disk image; `Hypnomix.app` is `macapp/Hypnomix.swift` with Python inside `Contents/Resources/python` |
| `Hypnomix-<v>-full-mac-arm64.dmg` / `-full-mac-x86_64.dmg` | `packaging/mac/build_dmg.sh --daw KIT [arm64\|x86_64]` | the **full** Hypnomix: the same app with the Hypnomix engine kit inside (`Contents/Resources/engine`). Mac only, and **not released**: no workflow builds or publishes it (see "The full download") |
| `Hypnomix-<v>-windows-x64-setup.exe` | `packaging/windows/build.ps1` (on Windows; Inno Setup 6) | per-user install to `%LOCALAPPDATA%\Programs\Hypnomix`, Start menu entries, optional Live setup |

Output lands in `packaging/dist/` (ignored by git). Both Mac architectures build on one Apple silicon Mac.

## The full download (its own DAW)

Today there is one download, the Hypnomix Assistant (the installers above). The plan is a second one, the full Hypnomix,
the same app with the Hypnomix DAW's engine inside; the download page will offer it when it is released. The full one is a **local build** for now, not a release: nothing in the workflows
builds or publishes it, and it is for the Mac only (there is no Windows build of the engine).

**It is a separate download that replaces the Assistant app.** Both are the same `/Applications/Hypnomix.app`. Nothing
in the Assistant adds the full one to itself (Setup → Extras only explains what it is and that it is not available
yet), and the updater never turns one into the other: see "Which edition" below.

**Licence.** The engine is a separate program under the GNU General Public License (version 2 or later), a rebranded
fork of a free DAW. hypnomix stays MIT and contains none of its code; the app starts the engine as a process of its
own and talks to it over the loopback connection. A download that carries the engine must carry its licence and say
where its source is, so `build_dmg.sh --daw` **refuses to build** unless the kit has, at its top level, `COPYING` (the
GNU General Public License text) and `SOURCE.txt` (the source notice: the licence, where the exact source of that
build is, the same for the libraries in the kit), has no symbolic links, and has no home path or login name of the
builder inside any file (a build writes its configuration into the program; that would then be public). The check is
`packaging/mac/check_kit.sh KIT`, also as `build_dmg.sh --check-kit KIT` (builds nothing, exit 1 when the kit is not
fit). The two files are copied to `Contents/Resources/LICENSES/engine/`. No public source address exists yet: the
source will be published with the first release that includes the engine, and `SOURCE.txt` has to say where before
any download carrying the engine is offered. `macapp/build.sh --daw` (a build for this Mac only) runs the same check
but only warns: never give that app to anyone.

1. Build the engine kit in the Hypnomix DAW source (an Ardour fork): `tools/osx_build --hypnomix` writes
   `tools/osx_packaging/HypnomixEngine` (`bin/hypnomix-engine`, a launcher that runs only from the kit, plus `lib/`
   and `share/`; about 100 MB, no links, every Mach-O signed), with `COPYING` and `SOURCE.txt` at its top level and
   no build path inside (see Licence above). It must be built for the same architecture as the app.
2. `packaging/mac/build_dmg.sh --daw /path/to/HypnomixEngine` makes `Hypnomix-<v>-full-mac-<arch>.dmg`;
   add `--app-only DIR` to get just `DIR/Hypnomix.app` (no disk image, e.g. to try it beside an installed copy).

What is different from the Assistant's app (everything else is the same: its own Python, ffmpeg, the guided setup,
the updater, the Assistant):

- The kit is copied to `Contents/Resources/engine`. The window (`macapp/Hypnomix.swift`) sees it and starts the
  server with `--daw`, so the DAW view opens first, and adds **File → New Session…** (⌘N, a save panel: folder and
  name) and **Open Session…** (⌘O, a `.ardour` file or its folder). Both go through the DAW view to the server's
  supervisor (`POST /api/daw/new`, `/api/daw/open`, with the page's own token), asking first if a session is open.
- The supervisor (`hypnomix/app/daw.py`) finds `Contents/Resources/engine/bin/hypnomix-engine` from the bundled
  Python's own path; nothing needs configuring. It reopens the session that was open last time (`daw.json` "last");
  the first time there is none and the view says to make or open one.
- Audio: CoreAudio on the Mac's default output (System Settings → Sound), with no input device, so macOS never holds
  the engine's start on the microphone question (to record, give `--input-device NAME` in `daw.json` "args"; the app's
  microphone text says the DAW records from the input you choose, as well as what the Assistant records). If no
  device starts, or the device never answers (seen with a loopback driver as the first device in the list), the engine
  is started again on the Dummy backend and the DAW view says so plainly: no sound, everything else works; Restart
  tries the device again.
- **Which edition** is known one way: the engine program is inside the app, at
  `Contents/Resources/engine/bin/hypnomix-engine`. `daw.app_edition()` looks at it, and Setup's "Your download" step,
  the DAW tab, the window (`dawMode`) and the updater all use that one answer (no Info.plist key, no setting a person
  can edit). A kit anywhere else does not make the full app. The updater takes `Hypnomix-full-mac-arm64.dmg` /
  `Hypnomix-full-mac-intel.dmg` for the full app and the Assistant's files for the Assistant, never the other: an update
  can't swap one for the other. On a release that has no full file the full app is told, plainly, that this version
  has no full download yet and offers nothing (`no_full_download` in the update state; no link to the Assistant).
  (Release plumbing still to do before a first full release: the stable-name step in `installers.yml` and the file list
  in `scan-release.yml` know only the Assistant's three files, and the build names the Intel file `x86_64`, the updater
  `intel`.)
- **Unsaved work.** The server tracks whether the open session has changes nobody saved (`dirty` in
  `GET /api/daw/state`, any changing engine call from the page or the Assistant since the last save). **Install and
  restart** answers 409 and installs nothing while that is so (save in the DAW tab first). **Quit** (⌘Q, closing the
  window) asks the server, and if it is dirty offers Save / Don't Save / Cancel (Save is `POST /api/daw/save`; if it
  fails, or if the server does not answer the question at all, the quit is not done unless you say to quit anyway), then stops the server and **waits for it to exit**
  (it stops the engine first, up to about 15 s) before the app quits. The update helper waits for the app, the server
  and the engine (45 s, then it stops what is left, the engine's whole process group included) before it swaps the
  bundle. A SIGTERM sent to the app (the helper, a logout) quits without the question.
- The bundle id stays **`org.hypnomix.app`**. The Assistant and the full download (once it is released) are one product installed as the same
  `/Applications/Hypnomix.app` (the updater swaps that bundle in place and checks its version), so the full one
  replaces the Assistant rather than sitting beside it. One id keeps the user's settings, window place and the
  macOS permissions they already gave when they move from one to the other. A second copy for testing runs with
  `open -n` and its own `HYPNOMIX_PORT`, `HYPNOMIX_PROBE_PORT` and homes, not a second id.
- Not verified yet: playing through a real sound card (only the silent test backend has been run), recording, the
  native File menu inside the built app, the full app's `.dmg` (no disk image of it has been built or opened),
  signing and notarising it, and Intel Macs.
- Signing: every Mach-O inside (Python, its packages, ffmpeg and the kit's 128) is signed innermost first, then the
  app; `codesign --verify --deep --strict` must pass, ad hoc or with a Developer ID. The hardened-runtime exceptions
  in `mac/entitlements.plist` (library validation off) also cover the engine's own libraries and plug-ins; a
  Developer ID build of the full app has not been tried yet.
- `macapp/build.sh --daw KIT` does the same for a developer build that runs this checkout's `.venv` (it passes the
  kit to the server as `HYPNOMIX_ENGINE`).

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

The app opens its **guided setup** (`hypnomix/app/setup.py` + `setup.js`), including the first time in the full app:
the window opens on the DAW view only once the setup is done or skipped. Which download (these installers are the
Hypnomix Assistant; the full Hypnomix with its own DAW is a local build for now, above, and shows as not available yet
in the Assistant, "Mac only for now" off a Mac; in the full app this step says it is the full one, and the Extras step
shows the DAW as built in), how you want to work (the app alone, an
AI key, a local model, or a desktop AI app such as Claude Code), the provider and key, a connection test, the
Ableton Live connection (`hypnomix install`, on a click), and for desktop AI apps a `hypnomix` command plus an
agent folder. On Windows the installer's "Set up Ableton Live" box also runs `hypnomix install`.

## Updates

`hypnomix/app/update.py` asks the GitHub API for the latest release (at most daily; `~/.hypnomix/update.json`),
downloads this platform's stable-named asset into `~/.hypnomix/updates/`, and checks it against the release's
`SHA256SUMS.txt`. Installing starts a helper outside the server: on a Mac it mounts the `.dmg`, quits the app,
swaps `Hypnomix.app` in place and reopens it; on Windows it runs the setup with `/VERYSILENT` over the install
(Inno Setup keeps the folder and tasks) and starts the launcher with `--quiet`. The helper logs to
`~/.hypnomix/updates/update.log`. The helper waits for the app, the server and the audio engine to be gone (up to 45 s,
longer than the engine's own stop) before it swaps the bundle, and **Install and restart** is refused while a DAW
session has unsaved changes (see "The full download"). The Windows CI job tests an in-place update after its smoke test. For a local
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

