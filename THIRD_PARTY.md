# Third-party code

## AbletonOSC (bundled)
`hypnomix/remote_script/AbletonOSC` is [AbletonOSC](https://github.com/ideoforms/AbletonOSC) by Daniel John Jones
and contributors, MIT licence (see its `LICENSE.md`). It includes python-osc (Unlicense).

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
