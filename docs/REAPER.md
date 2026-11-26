# REAPER: how hypnomix reads, writes and drives it

For people and agents changing hypnomix's REAPER code. The user guide is `docs/guides/08-inside-reaper.md`.
Every fact below was measured in REAPER 7.86 (how: see "Checking against REAPER" at the end).

## Where the code is

| file | what |
|---|---|
| `hypnomix/project/rpp.py` | parser and writer for REAPER's chunk format. An untouched load + save is byte-identical; `save` refuses the file it was read from |
| `hypnomix/project/model.py` | the DAW-neutral model (seconds), the renderer, fade curves, stretch-marker map, envelope interpolation |
| `hypnomix/project/reaper.py` | `.rpp` → model |
| `hypnomix/project/rpp_edit.py` | edits on the parsed chunks (fades, item volume, volume dips and eases, new takes, reorder, rename) and the structure check |
| `hypnomix/workflow/scan_project.py` | `scan` on an `.rpp` (and Ardour) |
| `hypnomix/workflow/scan_project.py` `stack_moves` | vocal stacks: Live's `order.assign_stack` on the model; `rpp_edit.move_item` moves the ITEM chunk (takes and take envelopes go with it); `check(moved=IGUIDs)` |
| `hypnomix/workflow/edges_project.py` | Live's word-edge detectors on the model; the REAPER edge fixes |
| `hypnomix/workflow/fix_project.py` | `fix` for an `.rpp`: one pass into one new file, structure check, re-measure |
| `hypnomix/reaper/bridge.lua`, `client.py`, `cli.py` | the bridge into the open REAPER, and `hypnomix reaper` |
| `hypnomix/engineer/chain_reaper.py` | `chain --reaper` |

New tools that should work in every DAW belong on the model (`project.load(path)`), not on raw `.rpp` or `.als`.

## The file format, as REAPER 7.86 writes it

| line | meaning |
|---|---|
| `TEMPO bpm num den` | tempo, time signature. A tempo map is `<TEMPOENVEX` (positions in the file are seconds anyway) |
| `SAMPLERATE sr use 0` | project rate; `use` 0 means it follows the audio device (renders then resample) |
| `ISBUS a b` | folders: `1 1` opens a folder, `2 -k` is the last track closing k folders, `0 0` normal |
| `VOLPAN vol pan ...` (track) | fader (linear) and pan |
| `MUTESOLO m s ...`, `IPHASE 1` | mute, solo, polarity |
| `AUXRECV src ...` | a send INTO this track from track `src` (0-based position): renumber on any reorder |
| `FX 0` | the whole FX chain bypassed |
| `BYPASS b offline ...` before each `<VST`/`<JS`/`<AU`/`<CLAP` | that plug-in off / offline |
| `VOLPAN itemvol takepan takevol panlaw` (item) | item volume (field 1) and the FIRST take's pan and volume |
| `TAKE [SEL]`, `TAKEVOLPAN pan vol ...` | each further take; `SEL` marks the one that plays. Negative take volume = polarity flipped |
| `SOFFS s`, `PLAYRATE rate keeppitch ...` | the take's start in its file (seconds), playrate, pitch kept (1) or varispeed (0) |
| `FADEIN shape len autolen shape2 ? equalpower ...` | shape (6 is written `5.1`), length, auto-crossfade length (wins when set), field 5 = 1 for equal-power crossfades |
| `SM pos src + pos src ...` | stretch markers on ONE line: take time (item time x playrate) and absolute source seconds |
| `<SOURCE SECTION` with `STARTPOS`, `LENGTH` | the take plays a section of the inner source |
| `<VOLENV2 ... VOLTYPE 1 ... PT t v shape>` | track volume envelope (post-FX). Values are AMPLITUDES even with `VOLTYPE 1` |

## How REAPER plays them (measured)

- Fade shapes, x = 0..1: 0 linear, 1 `1-(1-x)^2`, 2 `x^2`, 3 `1-(1-x)^4`, 4 `x^4`, 5 `3x^2-2x^3`, 6 sharp S
  (`0.5(2x)^4` mirrored); crossfades between overlapping items are equal power (`sin`). Sample i of n is at `x = i/n`.
- The track volume envelope MULTIPLIES with the fader. A new envelope at 1.0 leaves the fader alone.
- A fader-scaled envelope (`VOLTYPE 1`, the default) runs straight in fader position between points, not in
  amplitude. The curve is not a simple formula; `project/reaper_fader.json` holds REAPER's own
  `ScaleToEnvelopeMode(1, amp)` every 0.5 dB.
- Stretch markers: straight lines between markers; before the first and after the last, the source runs at normal
  speed from the nearest marker.
- Rendering with the project's sample rate following the device (`SAMPLERATE x 0`) resamples: set
  `PROJECT_SRATE` and `PROJECT_SRATE_USE` when comparing sample for sample.

## Stock plug-ins (what `chain --reaper` relies on)

- **ReaEQ**: 5 bands, no more (a second ReaEQ beyond that). Named config `BANDTYPEk`: 0 low shelf, 1 high shelf,
  3 low pass, 4 high pass, 5 all pass, 8 band (bell); `BANDENABLEDk`. Parameters by index `3k` freq, `3k+1` gain,
  `3k+2` bandwidth in OCTAVES (`Q → octaves = 2/ln2 · asinh(1/(2Q))`). Measured against the plan: within 0.04 dB.
- **ReaComp**: Threshold, Ratio (shows "inf" at the top), Attack, Release, RMS size, Knee.
- **ReaLimit**: Threshold, Ceiling, Release. The level goes up by `ceiling - threshold`. It limits SAMPLE peaks: the
  true peak can be over the ceiling, so `--verify` checks the whole song and lowers the ceiling.
- **JS: Bass Manager/Booster** "Mono" makes the WHOLE signal mono: not a bass-mono. hypnomix uses JS Mid/Side
  Encoder → ReaEQ (two high passes, pins on channel 2 only) → ReaEQ (all pass, pins on channel 1 only) → JS Mid/Side
  Decoder: leak under -68 dB at 400 Hz and -94 dB at 2 kHz.
- Plug-in pins: `TrackFX_SetPinMappings`; a channel no output pin writes passes through unchanged.
- Item lanes (REAPER 7): the track has `FREEMODE 2` (fixed lanes) or `1` (free positioning) and items carry `YPOS`;
  hypnomix never moves items off or onto such tracks.

## The bridge

`bridge.lua` runs inside REAPER, started by running REAPER's program with the script path (it runs in the
REAPER that is open, or starts REAPER). The folder is `~/.hypnomix/reaper-bridge`. A request is `req-<id>.txt`
(command, then `key=value` lines); the answer is `res-<id>.json`. Only the commands in the script exist; every
change is one undo step. Things that bit:

- `EnumerateFiles` caches the listing: list the folder once per pass (index 0 re-reads), and skip a request file
  that is already gone, or a stale listing answers it twice.
- Lua's `tonumber` does not read `+0.00`; displays also show `-inf` and `inf`.
- Plug-in displays can be Latin-1 (`°`): decode answers leniently.
- Closing a changed project tab asks "save?", and a dialog stops the bridge. Save a throwaway copy, reopen it with
  `Main_openProject("noprompt:" .. path)`, then close (action 40860). The bridge only closes tabs it opened.

## Checking against REAPER

Make REAPER the reference: a Lua script given on REAPER's command line builds a test project through the API,
saves it (`Main_SaveProjectEx`), renders stems (`RENDER_SETTINGS` 3, action 42230) and closes its tab. Then
compare REAPER's saved file with what the reader reads, and REAPER's render with hypnomix's. A **ramp** source
(each sample's value is its own position in the file) shows exactly which source position REAPER plays at
every moment, through stretches, loops and playrate. The tests in `tests/test_rpp.py` and
`tests/test_chain_reaper.py` hold the measured values.
