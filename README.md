# hypnomix

**A mixing and mastering engineer for Ableton Live, driven by you or by Claude Code.**

Hand it a folder of raw stems and get back a cleaned, balanced, mastered song, plus notes that explain every EQ cut, compressor setting and level in plain words. Or keep your hands on your own session: hypnomix sets exact fader dB and plug-in parameters in the open Live set, records A/B loops, and measures what each change did.

Built for people who record **real instruments and vocals**, not just MIDI.

Made by **Dr. Trance**.

```
hypnomix automix "My Song stems/" --reference "song I love.wav"
```

```
prep pass (clicks, clipping, plosives, breaths, noise, silence, fades) …
  Kick          kick          (by name)
  Bass DI       bass          (by name)
  Gtr L         guitar        (by name)
  Lead Vox      lead vocal    (by name)
  …
→ My Song (automix).wav · My Song (master).wav · MIX NOTES.md · recipe.json
```

## What's in the box

**Engineer: stems in, song out**

| command | what it does |
|---|---|
| `automix` | Stems → balanced mix → master. Per stem: role detection, clean-up EQ (resonances, mud, harshness), tone EQ, compression set by gain reduction, de-essing, loudness-based balance, panning, shared plate reverb, drum bus glue. Then it finds frequency fights between stems and carves the less important part. |
| `master` | Subsonic clean-up, optional reference tone match, glue compression, mono low end, true-peak limiter to a LUFS target. It test-encodes AAC/MP3 and lowers the ceiling if they would clip, then tops and tails. |
| `chain` | **No paid plug-ins needed.** Builds the mastering chain on Live's Main track from stock devices (EQ Eight → Glue Compressor → Utility → Saturator → Limiter), dials in every value from an analysis of your bounce, then records the result from Live and trims the Limiter until it measures on target. `chain strips` builds a channel strip on every track from an automix recipe. |
| `masking` | Which stems fight over which frequencies, how often, and the exact cut that fixes it. |
| `align` | Phase, polarity and time offset between mics on one source (kick in/out, DI + amp, snare top/bottom). |
| `translate` | Mono fold-down, phone, earbuds and car simulations, how much each streaming service turns it down, clipping after encoding. `--render` to listen. |
| `qc` | Release checklist: format, head/tail silence, cut-off endings, DC, clipping, true peak, loudness, phase, codecs. Exits 1 on failure. |

**Studio: from raw takes to mix-ready stems**

| command | what it does |
|---|---|
| `prep` | The assistant-engineer pass: rebuilds clipped peaks, repairs clicks and pops, removes plosive thumps, turns breaths down, removes hum and hiss (only where present), silences gaps with fades, fades every edge, converts dual-mono to mono, matches formats and lengths, gain-stages, names files in mix order. Every fix is logged with a timestamp. |
| `vocalign` | Time-aligns doubles and harmonies to the lead without touching pitch (feature-based DTW + WSOLA), trims overdub tails, sets harmony levels. |
| `clipmatch` | Evens out clips recorded at different gain or mic positions: loudness and tone. Works on files, or on a track in your Live set, where it can set each clip's Clip Gain directly. |
| `takes` | Ranks takes by clipping, noise, hum, pitch and timing, and writes a comp list: the best take for each section. |
| `soundcheck` | Listens to your interface input and tells you how to set the preamp before you record. `--watch` gives a live meter. |
| `cleanup` | Demo rescue: hum, steady noise, rumble, DC, silence. |
| `dehiss` | Spectral de-hiss plus a smart gate for one track: learns the hiss from the quietest moments, turns down only the frequency bins that sit at hiss level (smoothed so it never sounds watery), and fades the gaps with look-ahead so note attacks and tails stay natural. The gate has hysteresis and a 150 ms hold, so soft note tails can't make it chatter (which sounds like crackle). |
| `voices` | Re-arranges harmony stems into **Voice 1 (lowest) … Voice N (highest)**: every phrase goes to the voice matching its pitch rank among the parts singing with it, so one fader per voice sets each step of the stack (e.g. lower parts louder, each higher part a little quieter). The voices add up to the input stems exactly, so the mix doesn't change until you move a fader. Use post-chain stems (Live: Export → All Individual Tracks) and put the voice tracks in the same group with no devices, 0 dB and centre pan. |

**Live: hands on the set** (through a patched [AbletonOSC](https://github.com/ideoforms/AbletonOSC), bundled)

| command | what it does |
|---|---|
| `live` | Faders in exact dB, sends, pans, mute and solo; any device or VST/AU parameter, raw or in displayed units ("2.5 kHz", "-3 dB"); transport; snapshots; input routing, arming, monitoring and punch recording with take lanes. |
| `loop` | Plays bars, records them, measures them, and compares with the previous take and your profile. `--ab "db Lead -2" --revert` for one-change A/Bs. |
| `diagnose` | Solos each group in the loudest section of a song: who owns the sub, the bass and the vocal band. |

**Session files:** `render` turns tracks in a `.als` into full-length stems without opening Live (clip gain, clip fades and warps baked in, warped clips stretched **without changing pitch** like Live does; `--sources` swaps in cleaned files, `--tighten` silences the hiss around each clip's performance). `name` names every track and group by how it sounds: drums, kick, bass, guitar (notes that die away), strings (held notes, steady tone), lead vocal and harmonies (moving vowels), keys, pads; text clues from names, files and presets first; unsure tracks become "Instrument" and are listed for you; `--apply` renames them in the open set, `--undo` puts them back. Also `mine`, `audit`, `automation`, `refs`, `profile`.

**Ears:** `measure`, `spectrogram`, `punch`, `stems`, `pitchcheck` (pitch and loudness difference between two captures: run it after any re-render), `clicks` (finds clicks and crackle). Run `hypnomix` for the full list and `hypnomix <command> -h` for each one.

## Install

Needs macOS (Windows should work for the file tools and Live control but is untested), Python 3.9+, ffmpeg, and Ableton Live 11 or 12 for the Live features. The file tools work without Live.

```bash
git clone https://github.com/drtranceypants/hypnomix && cd hypnomix
uv venv && uv pip install -e .
hypnomix install
hypnomix doctor
```

`hypnomix install` copies the AbletonOSC remote script into Live's User Library and walks you through the rest. Then restart Live and choose **Settings → Link, Tempo & MIDI → Control Surface: AbletonOSC**.

To give hypnomix access to more of your plug-ins' parameters, run `hypnomix install --plugin-params`. It adds one line to Live's `Options.txt`.

`loop` and `diagnose` record what Live plays through [BlackHole](https://github.com/ExistentialAudio/BlackHole). `hypnomix install` explains the two-minute setup.

Optional features:

| extra | adds | install |
|---|---|---|
| `reference` | `hypnomix reference` (Matchering; GPL-3.0, kept separate so hypnomix stays MIT) | `uv pip install -e ".[reference]"` |
| `ml` | `hypnomix separate` (split a finished song into stems) and `hypnomix midi` (audio → MIDI) | `uv pip install -e ".[ml]"` |
| `critique` | `hypnomix critique` (a written second opinion from Gemini; needs `GEMINI_API_KEY`) | `uv pip install -e ".[critique]"` |

## With Claude Code

Open the repo in Claude Code and ask for what you want:

> "Mix the stems in ~/Music/Bounces/Night Drive. Make it sound like this reference."
>
> "I'm about to record acoustic guitar on input 2. Set up a track and check my levels."
>
> "Align the harmonies to the lead vocal and tell me what you changed."
>
> "Master this for Spotify and check it'll survive on a phone."

Four skills ship in `skills/`: **mix-engineer**, **mastering-engineer**, **tracking-session** and **live-mixing**. They teach Claude the workflows, the safety rules (snapshot before touching your set, respect automation, ask before taste calls), and how to explain each move.

To use the skills from any project, add the repo as a plugin marketplace: `/plugin marketplace add drtranceypants/hypnomix`.

`.mcp.json` also connects the [Ableton MCP](https://github.com/ahujasid/ableton-mcp) (telemetry off), which lets Claude create tracks and load devices. Together with `hypnomix live` it can rebuild an automix inside your set from `recipe.json`.

## Only free, open-source or stock tools

hypnomix never needs a paid plug-in. Its own processing is built in, and everything it does offline it can also build inside Live from the devices every Live Standard or Suite owner already has:

```bash
hypnomix chain master "Song bounce.wav" --target -14 --reference "reference.wav" --verify
```

```
| EQ Eight        | low cut 22 Hz; low shelf 90 Hz +0.8 dB; bell 550 Hz -1.8 dB; high shelf 9 kHz +1.8 dB |
| Glue Compressor | threshold -20.3 dB, 2:1, attack 30 ms, release 0.2 s                                  |
| Utility         | bass mono below 120 Hz                                                                 |
| Limiter         | gain +4.6 dB, ceiling -1.0 dB                                                          |
```

Plug-ins already on the Main track are never deleted: `--existing bypass` switches them off, `--existing keep` adds the chain after them. A mixer snapshot is saved first.

### Free plug-ins that work with hypnomix

hypnomix controls a plug-in through the parameters Live exposes for it (`hypnomix live params <track> <plug-in>`), so any VST3 or AU works the same way as a stock device. These free and open-source ones are part of the setup hypnomix is developed with:

| plug-in | type | use it for |
|---|---|---|
| [TDR Nova](https://www.tokyodawn.net/tdr-nova/) | free | dynamic EQ: resonances and harshness that come and go. **Verified:** all 256 parameters reachable from hypnomix |
| [TDR Kotelnikov](https://www.tokyodawn.net/tdr-kotelnikov/) | free | transparent mix-bus and mastering compression |
| [LoudMax](https://loudmax.blogspot.com/) | free | look-ahead mastering limiter |
| [Airwindows Consolidated](https://www.airwindows.com/consolidated/) | open source (MIT) | hundreds of small processors: saturation, console emulation, dithering |
| [CHOWTapeModel](https://chowdsp.com/products.html#tape) | open source | tape saturation and warmth |
| [Dragonfly Reverb](https://michaelwillis.github.io/dragonfly-reverb/) (Hall, Room, Plate, Early Reflections) | open source (GPL-3) | natural reverbs; the Plate matches automix's send |
| [Valhalla Supermassive](https://valhalladsp.com/shop/reverb/valhalla-supermassive/), Space Modulator, Freq Echo | free | big ambient reverbs and delays, modulation |
| [Surge XT](https://surge-synthesizer.github.io/) (Effects) | open source (GPL-3) | multi-effects, plus a full synth |
| [SPAN](https://www.voxengo.com/product/span/) | free | spectrum analyser for checking hypnomix's EQ moves by eye |
| [Youlean Loudness Meter 2](https://youlean.co/youlean-loudness-meter/) | free version | LUFS and true-peak metering in Live |
| [sfizz](https://sfz.tools/sfizz/) | open source | SFZ sampler for instrument parts |

Plug-ins with more parameters than Live shows by default need `hypnomix install --plugin-params` (or Live's Configure button) before hypnomix can reach all of them.

## How it decides

Everything is measurement plus rules an engineer would use. There are no black-box models in the mixing chain, so every decision can be written down and argued with. Read [GUIDE.md](GUIDE.md) for the craft behind each tool and the workflows.

It measures; it doesn't listen. Treat the automix as a strong first pass by an assistant, then make the taste calls yourself.

## Licence

MIT. Bundles AbletonOSC (MIT, © Daniel John Jones and contributors) with small patches marked `hypnomix patch`; see [THIRD_PARTY.md](THIRD_PARTY.md). Not affiliated with Ableton.
