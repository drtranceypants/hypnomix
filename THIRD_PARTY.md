# Third-party code

## AbletonOSC (bundled)
`hypnomix/remote_script/AbletonOSC` is [AbletonOSC](https://github.com/ideoforms/AbletonOSC) by its contributors,
MIT licence (its copyright notice and licence are in its `LICENSE.md`, which stays with it). It includes python-osc (Unlicense).

hypnomix's changes, each marked `hypnomix patch` in the source:
- `abletonosc/resolve.py`: negative track ids address the master (-1) and return tracks (-2, -3, …)
- `abletonosc/track.py`: `/live/track/get/volume_string` (fader value as Live displays it, for exact dB);
  arrangement clip gain get/set, gain display strings and end times
- `abletonosc/osc_server.py`: listens on 127.0.0.1 only

## Dependencies
numpy, scipy (BSD) · soundfile (BSD) · sounddevice (MIT) · pyloudnorm (MIT) · librosa (ISC) ·
matplotlib (PSF-based) · python-osc (Unlicense) · noisereduce (MIT).

Optional extras install separately and keep their own licences: matchering (GPL-3.0),
audio-separator (MIT), basic-pitch (Apache-2.0), google-genai (Apache-2.0),
pedalboard (GPL-3.0; the `plugins` extra, used by `hypnomix plugrender` to host VST3 and AU plug-ins).

## In the installers (packaging/)
The Mac .dmg and Windows setup .exe also carry, unchanged, each under its own licence:
- CPython (PSF License), as built by [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
  (MIT / Apache-2.0), with the packages above and the `assistant` and `critique` extras (anthropic, openai: MIT / Apache-2.0)
- an FFmpeg program (`bin/ffmpeg`) from [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg)'s builds. FFmpeg is
  LGPL/GPL software run as a separate program; its source is at https://ffmpeg.org/download.html and the build scripts
  at https://github.com/imageio/imageio-binaries

## The Hypnomix engine (the full download only; not released yet)
The full Hypnomix, a second and larger download that replaces the Assistant app, will carry **the Hypnomix engine**: a
separate program, a rebranded fork of the free DAW Ardour, under the **GNU General Public License, version 2 or later**
(plus the licences of the libraries in its kit, GPL and LGPL ones among them).

- It is a program of its own, started by the app as a separate process and spoken to over a local connection (MCP over
  HTTP on this computer, loopback only). hypnomix itself stays **MIT** and contains none of the engine's code and none of
  its libraries; nothing of hypnomix is linked into it. `hypnomix/app/daw.py` only starts, watches and stops it.
- The kit is built in the engine's own source tree (`tools/osx_build --hypnomix`, which writes `HypnomixEngine`).
  `packaging/mac/build_dmg.sh --daw` refuses to build unless the kit carries its licence text (`COPYING`) and a source
  notice (`SOURCE.txt`), and refuses a kit with the builder's home path or login name inside it. Both files are copied
  into the app (`Contents/Resources/engine`, and `Contents/Resources/LICENSES/engine`).
- **Source:** the source will be published with the first release that includes the engine. No download that carries
  the engine is offered before that, and `SOURCE.txt` must say where the exact source of that build is.
- Not checked yet, and said so in the docs: playing through a real sound card (only the silent test backend was
  run), recording, the app's native File menu, the full app's disk image, its signing, and Intel Macs.
