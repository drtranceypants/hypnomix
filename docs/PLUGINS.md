# Rendering through your plug-ins

`hypnomix plugrender` plays the tracks of a saved Live set through their real plug-in chains, offline and
faster than real time, without opening Live. Each VST3 and Audio Unit plug-in on a track is loaded with the
settings Live saved in the set, the track's audio runs through the chain in order, then through its fader and
pan. Nothing in the set or its audio is changed: it only writes WAVs.

It is what lets `hypnomix ab --plugins` play a before / after of a device change (a compressor setting, a limiter gain)
as you would hear it on the track, with your real plug-ins in the chain, instead of the dry track.

## Install

The plug-in host is Spotify's [pedalboard](https://github.com/spotify/pedalboard). It is GPL-3.0, so it is an
optional extra and HypnoMix itself stays MIT:

```bash
uv pip install -e ".[plugins]"        # or: pip install pedalboard
```

Without it, `plugrender` still renders the clips, Live's devices that HypnoMix models and the mixer, and says
that each plug-in was skipped.

## Use

```bash
hypnomix plugrender "Song.als" --list                 # each track's chain: what can be rendered, what can't
hypnomix plugrender "Song.als" --check                # load every plug-in, restore its settings, report
hypnomix plugrender "Song.als" --tracks "Lead Vocal"  # render (WAVs + plugrender.json in hypnomix-out/)
hypnomix plugrender "Song.als" --group "Vocals" --no-stock   # third-party plug-ins only
```

`--check` says, per plug-in, whether it loaded, whether its saved state was restored, and how much of it reads
back the same: the parameter values Live saved against the plug-in's own, and for plug-ins that keep their
settings as readable state (many free ones do), setting by setting. Run it first on a new set.

## What it renders

| on the track | rendered? |
|---|---|
| audio clips | yes, as `hypnomix render` does: clip gain, fades, warps (as mono, fed to the chain as stereo) |
| VST3 plug-ins | yes, found by name in `/Library/Audio/Plug-Ins/VST3` and `~/Library/Audio/Plug-Ins/VST3` |
| Audio Unit plug-ins | yes, found by their component codes in the two `Components` folders |
| Live's Utility (gain), Compressor, Glue Compressor, Limiter, Gate, EQ Eight | yes, with HypnoMix's models of them (approximations; a compressor's sidechain from another track is followed; an EQ Eight in L/R or M/S mode and a Gate that listens to a sidechain have no model and are skipped) |
| other Live devices (Saturator, reverbs, delays…), racks, Max for Live | no: skipped, and listed as skipped |
| VST2 plug-ins | no: pedalboard hosts VST3 and AU only |
| switched-off devices | skipped, as in Live |
| fader and pan | yes (volume automation too); pan is an approximation of Live's |
| group tracks | yes: their playing tracks summed, then the group's chain and fader |
| sends, return tracks, the Main track | no |
| MIDI tracks (instruments) | no |
| automation of device or plug-in parameters | no: every device plays at its saved setting |

A plug-in that is missing, fails to load or fails to restore is skipped with a warning; the track still
renders without it. Every plug-in is first loaded in a separate process, so one that crashes is reported and
skipped and never takes the render down. When an Audio Unit will not load but the same plug-in is installed
as a VST3 and its saved state is a JUCE state (common in free plug-ins), the VST3 is used with that state, and
the report says so.

## How `ab` uses it

```bash
hypnomix ab "<SCAN_DIR>" --plugins
```

For each device-change finding (`devices`, `duck`, `sidechain`, `distortion`), `ab` writes a temporary copy
of the set with only that fix applied (next to the original, deleted afterwards), renders the track through
its chain in both, and writes a level-matched pair around the loudest part of the track. Findings on return
tracks (most `duck` items) can't be previewed, because returns are fed by sends; `ab.json` says so.

Without `--plugins` (or without pedalboard) `ab` still previews the device changes it can model (and timing nudges and
masking cuts, which need neither), with no real plug-in: the track is played through HypnoMix's models of Live's Compressor, Glue Compressor, Gate, EQ Eight, Utility
and Limiter, and the other plug-ins are left out of the chain (the pair says which). Those pairs are labelled
**a model of the device, not Live itself** in `ab.json` (`"model": true`) and on the review page: the curve of an EQ
Eight band lands where its settings say, a compressor follows the same gain-reduction model `devices` and `sidechain`
use, but Live's own filters and detectors differ in small ways. A change to a device with no model (Saturator,
Reverb, Delay, a rack, a Max for Live device, EQ Eight in L/R or M/S mode, a Gate listening to a sidechain) is
refused with that reason, and so is a plug-in change without `--plugins`.

The pair is the track on its own, through the devices that could be rendered: listen for what the change
does, then confirm in Live.

## Which plug-ins you have: `hypnomix plugins`

```bash
hypnomix plugins                      # everything installed, by format; the free list is marked
hypnomix plugins --check              # load each VST3 / Audio Unit without its window (needs pedalboard)
hypnomix plugins --save               # keep the list in your preferences
hypnomix plugins --json               # data for an agent (or --json OUT.json)
```

It looks in the standard folders of the system (Mac: `/Library/Audio/Plug-Ins` and `~/Library/Audio/Plug-Ins`, folders
`VST3`, `Components`, `CLAP`, `LV2`; Windows: `Common Files\VST3`, `CLAP`, `LV2`; Linux: `~/.vst3`, `/usr/lib/vst3`, and
the CLAP and LV2 equivalents), one vendor folder deep and more. Add your own with `--folder FORMAT=DIR`. Audio Units are
read from their `Info.plist` (which also says instrument or effect); the rest by file name.

**The free list** is the README's "Free plug-ins that work with HypnoMix". A plug-in on it is marked, and is what
`colour` may name; every other plug-in is listed and never proposed.

**`--check`** loads each plug-in the way `plugrender` does: in its own process, with a time limit (`--timeout`,
default 60 s). A plug-in that crashes, fails to load or does not answer is reported FAILED with the reason, and the run
goes on. CLAP and LV2 are not opened (the host, pedalboard, hosts VST3 and Audio Units only): they are listed as found,
"not checked". `--only TEXT` narrows it to some plug-ins.

**`--save`** is the only thing that writes anything, and only the preferences file: `tools.plugins` (the free-list
plug-ins that are installed and, with `--check`, load; names you added by hand are kept unless `--replace`) and
`tools.plugins_found` (everything found, with its format and folder). `hypnomix prefs` shows them, and `hypnomix colour`
reads them so its alternatives only name what is installed.
