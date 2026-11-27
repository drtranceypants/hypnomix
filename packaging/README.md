# Installers

One-click installers for people who don't use a terminal. Each one carries its own Python
([python-build-standalone](https://github.com/astral-sh/python-build-standalone), fetched by `uv`), HypnoMix with
the `assistant` and `critique` extras, and an ffmpeg program. The GPL extras (`reference`, `plugins`) and the large
`ml` extra stay out: they are for source installs.

| file | built by | what it is |
|---|---|---|
| `Hypnomix-<v>-mac-arm64.dmg` / `-mac-x86_64.dmg` | `packaging/mac/build_dmg.sh [arm64\|x86_64]` | drag-to-Applications disk image; `Hypnomix.app` is `macapp/Hypnomix.swift` with Python inside `Contents/Resources/python` |
| `HypnoMix-engine-<engine version>-<platform>.tar.gz` | `packaging/mac/build_engine_archive.sh KIT` | the **HypnoMix Studio add-on**, not an installer: the engine kit as an archive of its own, uploaded by hand to a release and added from Setup on a click. The first one, engine 0.1.0, is published for `mac-arm64` only (see "HypnoMix Studio, the add-on") |
| `Hypnomix-<v>-windows-x64-setup.exe` | `packaging/windows/build.ps1` (on Windows; Inno Setup 6) | per-user install to `%LOCALAPPDATA%\Programs\Hypnomix`, Start menu entries, optional Live setup |

Output lands in `packaging/dist/` (ignored by git). Both Mac architectures build on one Apple silicon Mac.

## HypnoMix Studio, the add-on (its own DAW)

There is **one app and one installer** for everyone (the three files above). HypnoMix Studio, HypnoMix's own DAW built on
Ardour, a free open-source DAW, is not inside them. Its engine is published as an archive of its own for each platform
and added from Setup (**Add HypnoMix Studio**, on a click), or with `hypnomix engine install --yes`, only when the person
wants it: someone who keeps their own DAW never downloads it. The first archive, engine **0.1.0**, is published on the
HypnoMix release page for **Apple-silicon Macs only** (`mac-arm64`), and the manifest shipped in the app,
`hypnomix/app/engine_addon.json`, names its address, size and SHA-256. Nothing in the workflows builds or publishes the
engine: the archive is built and uploaded by hand (below). There is no engine for Intel Macs (`mac-intel`), Windows or
Linux yet: there the manifest names no archive, the app says "HypnoMix Studio is not available for <place> yet" and
downloads nothing.

**Licence.** The engine is a separate program under the GNU General Public License (version 2 or later), a rebranded
fork of Ardour; HypnoMix stays MIT and contains none of its code. The app starts the engine as a process of its own and
talks to it over the loopback connection. An archive that carries the engine must carry its licence and say where its
source is, so `packaging/mac/build_engine_archive.sh` **refuses to package** a kit unless it has, at its top level,
`COPYING` (the GNU General Public License text) and `SOURCE.txt` (the source notice: the licence, where the exact source
of that build is, the same for the libraries in the kit), has no symbolic links, and has no home path or login name of
the builder inside any file (a build writes its configuration into the program; that would then be public). The check
is `packaging/mac/check_kit.sh KIT` (exit 1 when the kit is not fit). The app runs the same checks again, in Python
(`engine_addon.kit_problems`), on what it downloaded, before anything is put in place. The engine's source is public at
https://github.com/drtranceypants/hypnomix-daw, and `SOURCE.txt` in every archive says where the exact source of that
build is.

### Making a release that carries an engine

1. Build the engine kit in the engine's own repository: `tools/osx_build --hypnomix` writes
   `tools/osx_packaging/HypnomixEngine` (`bin/hypnomix-engine`, a launcher that runs only from the kit, plus `lib/` and
   `share/`; about 105 MB, no links, every Mach-O signed), with `COPYING` and `SOURCE.txt` at its top level and no build
   path inside. It must be built for the Mac it is for (Apple silicon: `mac-arm64`, Intel: `mac-intel`).
2. Set `"engine"` in `hypnomix/app/engine_addon.json` to the engine's version (it names the folder
   `engine/<version>/` the engine is put in, and the version the app works with). Give every new archive a new version
   string, so people see it as an update. (If a rebuilt kit is ever published under the same string, an app that
   already has that version notices that the fingerprint in the manifest is not the one it was added from, says a rebuilt
   one is published, and fetches it again on a click; it is never replaced while the engine runs.)
3. `packaging/mac/build_engine_archive.sh /path/to/HypnomixEngine [mac-arm64|mac-intel] [OUT]` runs the kit check, writes
   `OUT/HypnoMix-engine-<version>-<platform>.tar.gz` (default OUT: `packaging/dist`) and prints its size and SHA-256 and
   the line to paste into the manifest. The archive is deterministic: sorted entries, one fixed time, no owners, plain
   modes, no name or time in the gzip header, so the same kit always gives the same bytes. **It never uploads anything**
   and does not touch the manifest.
4. Upload the archive to the release by hand (the draft of the tag the line names).
5. Paste the line under `"platforms"` in `engine_addon.json`: `{"url": "https://github.com/drtranceypants/hypnomix/releases/download/<tag>/<file>", "sha256": "…", "size": N}`
   (the address is https only; `tests/test_engine_addon.py` checks that any address in the manifest is the project's own
   release page). Then tag the release as usual (below).

An app that names a newer engine than the one a person has says so in the DAW view and in Setup and offers the new one;
the old engine is kept until the new one has run once, then removed. Updating the app never touches the engine folder
(`~/.hypnomix/engine`), and an app that was an old test build with the engine inside it updates to the ordinary app and
finds its engine at the add-on's place, or is offered it from Setup.

What the add-on does (`hypnomix/app/engine_addon.py`): downloads over https with a size limit (the manifest's size plus a
megabyte) and a deadline (30 minutes), checks the SHA-256 **before** anything is unpacked (a mismatch deletes the download),
unpacks with the Store's protections (no entry outside the folder, no link pointing out, entry and size limits), checks
the kit, and moves it into place in one step; a failed or interrupted add leaves nothing half-added and can simply be
run again. The address and the fingerprint come only from the manifest shipped in the app, never from a request.

What is different when the engine is there (everything else is the same app: its own Python, ffmpeg, the guided setup,
the updater, the Assistant):

- The supervisor (`hypnomix/app/daw.py`) finds `engine/<version>/bin/hypnomix-engine` in the HypnoMix folder; nothing needs
  configuring. The Studio tab appears when an engine is found. It reopens the session that was open last time (`daw.json`
  "last"); the first time there is none and the view says to make or open one.
- The window (`macapp/Hypnomix.swift`) always has a **File** menu: **New Session…** (⌘N), **Open Session…** (⌘O) and
  **Import Project…**. Its items are dimmed until HypnoMix Studio has been added. A test build made with
  `macapp/build.sh --daw KIT` carries a kit inside the app (`Contents/Resources/engine`) and opens on the DAW view; the
  supervisor still finds that kit for one more version, and nothing depends on it; the installer does not carry it.
- Audio: CoreAudio on the Mac's default output (System Settings → Sound), with no input device, so macOS never holds
  the engine's start on the microphone question (to record, give `--input-device NAME` in `daw.json` "args"; the app's
  microphone text says HypnoMix Studio records from the input you choose, as well as what the Assistant records). If no
  device starts, or the device never answers (seen with a loopback driver as the first device in the list), the engine
  is started again on the Dummy backend and the DAW view says so plainly: no sound, everything else works; Restart
  tries the device again. If another program changes the device's sample rate while a session is open, the engine sets
  it back by itself, and stops with a clear message only if the device refuses or the two programs keep changing it.
- **Unsaved work.** The server tracks whether the open session has changes nobody saved (`dirty` in
  `GET /api/daw/state`, any changing engine call from the page or the Assistant since the last save). **Install and
  restart** answers 409 and installs nothing while that is so (save in the Studio tab first). **Quit** (⌘Q, closing the
  window) asks the server, and if it is dirty offers Save / Don't Save / Cancel (Save is `POST /api/daw/save`; if it
  fails, or if the server does not answer the question at all, the quit is not done unless you say to quit anyway), then stops the server and **waits for it to exit**
  (it stops the engine first, up to about 15 s) before the app quits. The update helper waits for the app, the server
  and the engine (45 s, then it stops what is left, the engine's whole process group included) before it swaps the
  bundle. A SIGTERM sent to the app (the helper, a logout) quits without the question.
- The bundle id stays **`org.hypnomix.app`**: one product, one `/Applications/Hypnomix.app`, which the updater swaps in
  place and whose version it checks. A second copy for testing runs with `open -n` and its own `HYPNOMIX_PORT`,
  `HYPNOMIX_PROBE_PORT` and homes, not a second id.
- Checked for the first archive: `packaging/mac/build_engine_archive.sh` ran the kit check (`COPYING` and `SOURCE.txt`
  present, no links, no builder home path or login name) before writing it, its size and SHA-256 are the ones in the
  manifest, and the app checks the SHA-256 again before unpacking and the kit again before putting it in place.
  Run on an Apple-silicon Mac with a fresh HypnoMix home and the archive supplied from disk in place of the download:
  the add from Setup's own call, the fingerprint check, the unpack and kit check, the engine started by the app from
  `engine/0.1.0/`, a new session, an imported tone, play, a bounce with the tone in it, save, stop and remove, on the
  silent test backend and on CoreAudio with a virtual loopback device; the DAW view connected to it in a browser; in a
  test copy of the app, File listed its three items and Open Session… opened its chooser.
- Not verified yet: the download itself from the release page (it can only run once the release is public), playing through a real sound card and recording from an input (the silent backend and a virtual loopback device have been run), choosing a session through the native File menu's chooser inside the installed app,
  signing and notarising the engine, Intel Macs (there is no Intel engine), and MPE with real MPE controllers (the
  engine's MPE passed its automated tests only).
- Signing: every Mach-O inside the app (Python, its packages, ffmpeg) is signed innermost first, then the app;
  `codesign --verify --deep --strict` must pass, ad hoc or with a Developer ID. The engine's own Mach-O files are signed
  in the kit (`osx_build --hypnomix`); a file the app downloads carries no quarantine mark, and a Developer ID build with
  the engine added has not been tried yet.
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

The app opens its **guided setup** (`hypnomix/app/setup.py` + `setup.js`): how you want to work (the app alone, an
AI key, a local model, or a desktop AI app such as Claude Code), which DAW you use (Ableton Live, REAPER, HypnoMix Studio or
something else: choosing HypnoMix Studio shows what the add-on is and an **Add HypnoMix Studio** button on an Apple-silicon
Mac, or, where no archive is published for the computer (Intel Macs, Windows), says it is not available there yet and
remembers the choice; nothing is downloaded without that click), the provider and key, a connection test, the
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
session has unsaved changes (see "HypnoMix Studio, the add-on"). The Windows CI job tests an in-place update after its smoke test. For a local
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

