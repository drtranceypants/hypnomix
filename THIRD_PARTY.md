# Third-party code

## AbletonOSC (bundled)
`hypnomix/remote_script/AbletonOSC` is [AbletonOSC](https://github.com/ideoforms/AbletonOSC) by its contributors,
MIT licence (its copyright notice and licence are in its `LICENSE.md`, which stays with it). It includes python-osc (Unlicense).

HypnoMix's changes, each marked `hypnomix patch` in the source:
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

## HypnoMix Studio: built on Ardour (the add-on; engine 0.2.0, Apple-silicon Macs only)
HypnoMix Studio is HypnoMix's own DAW, built on **Ardour** (https://ardour.org), a free open-source DAW under the GNU General
Public License. This is the notice of that origin and of its licence. HypnoMix Studio is an add-on to the one HypnoMix app,
not a second download: its engine is published as an archive of its own and added from Setup on a click. The engine is a
separate program, a rebranded fork of Ardour, under the **GNU General Public License, version 2 or later** (plus the
licences of the libraries in its kit, GPL and LGPL ones among them). HypnoMix itself stays **MIT**.

- It is a program of its own, started by the app as a separate process and spoken to over a local connection (MCP over
  HTTP on this computer, loopback only). HypnoMix contains none of the engine's code and none of its libraries, and
  nothing of HypnoMix is linked into it. The installer does not carry it. `hypnomix/app/engine_addon.py` fetches it
  (https, a size limit and a deadline, only from the address and with the SHA-256 in the manifest shipped inside the app,
  checked before anything is unpacked), unpacks it safely and puts it under `engine/<version>/` in HypnoMix's own folder (`~/.hypnomix` unless `HYPNOMIX_HOME` says otherwise);
  `hypnomix/app/daw.py` only starts, watches and stops it.
- The kit is built in the engine's own source tree (`tools/osx_build --hypnomix`, which writes `HypnomixEngine`).
  `packaging/mac/build_engine_archive.sh` refuses to package it unless the kit carries its licence text (`COPYING`) and a
  source notice (`SOURCE.txt`), and refuses a kit with the builder's home path or login name inside it; the app checks the
  licence text and the source notice again on what it downloaded, and does not put the engine in place without them.
- **Source:** the engine's source is public at https://github.com/drtranceypants/hypnomix-daw (GNU General Public
  License, version 2 or later). The first archive, engine 0.2.0, is on the HypnoMix release page for Apple-silicon Macs
  (`mac-arm64`) only; there is no engine for Intel Macs, Windows or Linux yet. Its `SOURCE.txt` says where the exact
  source of that build is.
- Not checked yet, and said so in the docs: playback and recording through a real sound card, real MPE controllers, signing and
  notarising the engine, and Intel Macs.
