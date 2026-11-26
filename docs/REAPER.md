# REAPER: how hypnomix reads, writes and drives it

For people and agents changing hypnomix's REAPER code. The user guide is `docs/guides/08-inside-reaper.md`.
Every fact below was measured in REAPER 7.86 (how: see "Checking against REAPER" at the end). That includes the files hypnomix's newest code writes: on 2026-11-26 the demo project, a project written by `fix`, the masking cut as a ReaEQ band, the hand-off project's marker and the A/B project were opened in REAPER 7.86 and read back through its API (see "Opened and read back in REAPER 7.86" at the end). None of that has been run on a real song, and none has been judged by ear.

## Where the code is

| file | what |
|---|---|
| `hypnomix/project/rpp.py` | parser and writer for REAPER's chunk format. An untouched load + save is byte-identical; `save` refuses the file it was read from |
| `hypnomix/project/model.py` | the DAW-neutral model (seconds), the renderer, fade curves, stretch-marker map, envelope interpolation |
| `hypnomix/project/reaper.py` | `.rpp` → model |
| `hypnomix/project/rpp_edit.py` | edits on the parsed chunks (fades, item volume, volume dips and eases, new takes, reorder, rename) and the structure check |
| `hypnomix/workflow/scan_project.py` | `scan` on an `.rpp` (and Ardour) |
| `hypnomix/workflow/scan_project.py` `stack_moves` | vocal stacks: Live's `order.assign_stack` on the model; `rpp_edit.move_item` moves the ITEM chunk (takes and take envelopes go with it); `check(moved=IGUIDs)` |
| `hypnomix/workflow/timing_project.py` | Live's timing judgement (`session/timing.judge`) on hits read from items; nudges written as stretch markers (`SM`), anchored on every onset either side |
| `hypnomix/workflow/sidechain_project.py` | sidechained ReaComps: found by their detector channel and the sends landing there, simulated with Live's `sidechain` model, suggestions written as ReaComp floats |
| `hypnomix/reaper/jsfx/`, `reaper/probes.py` | Hypnomix Probe / Main as JSFX: 20 values per 100 ms into gmem `hypnomix`; the bridge assigns slots and keeps blocks (`probe_blocks`); `probes.feed` relays them into the app's `probe.Hub`; `insert` and `read_cards` for `.rpp` |
| Record and review (`bridge.lua` `rec_*`, `probes.handle`, `server.reaper_record`) | Main's `@gfx` button adds 1 to gmem[8]; the bridge plays from the cursor, keeps start and furthest position, and queues start/stop events for `probe_blocks rec=1` (only a relay that asks gets them, and only it counts as "an app is there"); state back to Main in gmem[9] (0 idle, 1 recording, 2 rendering, 3 no app, 4 reviewing, 5 under a second played: no event sent, 6 the app's review failed), seconds in gmem[10]. Main reads the mouse each `@gfx` frame (about 30 a second) and counts a press on RELEASE over the button: REAPER does not start playing while the mouse is still held in an FX window, so acting on mouse-down left a normal (held) click with no playback. The bridge also waits up to 3 s for playback to start before it calls a take finished. A synthetic click shorter than a frame can still be missed. On stop the app closes the probe capture FIRST (a render runs every JSFX again and would add its blocks), renders `render_master(start, end)` and runs the same review steps as Live's `master_record`. `hypnomix reaper record` = a press |
| `hypnomix/workflow/handoff.py` (`write_rpp`) | `handoff` on an `.rpp` scan: a NEW `Song (handoff).rpp` with one `MARKER` line per by-hand spot (position in seconds, a name, a new GUID), read back and compared with the original; nothing else in the project changes. Opened in REAPER 7.86 and read back: the marker's position and name matched what was written |
| `hypnomix/studio/demo.py` | `demo --kind reaper`: a short synthetic song as stems plus a project that plays them (the comps as separate items on separate takes), so every planted problem is visible to `scan`. Round-trips through `rpp.load`; opened in REAPER 7.86 with no offline media |
| `hypnomix/engineer/masking.py` (`write_project`), `rpp_edit.add_reaeq_cut` | `masking --apply NEW.rpp` and `fix` on an approved frequency-fight finding: a bell cut as one ReaEQ band on the track that should give way (see "ReaEQ in a saved project" below). Opened in REAPER 7.86: frequency, gain and bandwidth read back exactly as written |
| `hypnomix/workflow/edges_project.py` | Live's word-edge detectors on the model; the REAPER edge fixes |
| `hypnomix/workflow/fix_project.py` | `fix` for an `.rpp`: one pass into one new file, structure check, re-measure |
| `hypnomix/reaper/bridge.lua`, `client.py`, `cli.py` | the bridge into the open REAPER, and `hypnomix reaper` |
| `hypnomix/engineer/chain_reaper.py` | `chain --reaper` |
| `hypnomix/workflow/abset_project.py` | `abset` on an `.rpp`: each fix built alone (`fix` on a throwaway scan copy), compared track by track (by GUID); plug-in-only changes copy the FX block after the original with `BYPASS 1` and a new `FXID`; other changes copy the whole track (`fresh_ids`, `MUTESOLO 1`) via `rpp_edit.insert_copies`, which keeps folders (`_layout` rebuilds ISBUS) and mirrors the original's sends (`AUXRECV` lives on the receiving track); writes `ab_live.json` with `daw: reaper` |
| `hypnomix/studio/alignset_rpp.py`, `hypnomix/reaper/align.py` | `alignset` on an `.rpp` (stretch markers via `rpp_edit.set_stretch`, pitch / formant / `--takes` as new takes via `add_take(offset=0, rate=1)` on per-item files that sum back to the checked render) and `hypnomix reaper align`: the Hypnomix Align panel (`panel_open mode=align`, `align_where`, `align_draw`) sending the Live device's request to `/api/align/*` |
| `hypnomix/reaper/review.py` | `hypnomix reaper review`: polls the app's `/api/live/*`, drives the bridge's gfx panel (`panel_open/set/events/close`), switches plug-ins (`fx_enable`) or mutes, jumps (`jump`: beats × 60/tempo), and sets Main's hidden `match` slider from the app's matching gain |

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
- Timing: hits are found with the same onset detector as Live's `timing`. Stretch-marker nudges checked in
  REAPER's own render: the hit moves by the planned amount (-34.9 for -35 ms, +15.0 for +15), its neighbours by 0.0.
  An attack refinement was tried and dropped: on synthetic pure tones the detector read bass and guitar ~45 ms
  early, but on real songs its lean is a few ms and the refinement only swapped early flags for late ones.
- REAPER saves projects with CRLF line ends, on macOS too: `rpp.load`/`save` read and write bytes, so a load + save
  is byte-identical and new lines use the file's own line ends.
- **ReaComp** state in the `.rpp`: a header (plug-in id, pin counts and masks, then the state size), the state (8-byte
  marker `efbeadde0df0adde`, then every parameter's raw value as a 32-bit float, in parameter order), a short tail.
  Raw → units: threshold = amplitude; ratio = 1 + 99·raw (1 = ∞); attack = 500·raw ms; release = 5000·raw ms;
  pre-comp = 250·raw ms; detector low-pass / high-pass = 20000·raw Hz (1 / 0 = off); RMS size = 100·raw ms
  (0 = peak); knee = 24·raw dB; detector input ("SignIn") = first channel (0-based) = 1084·raw: 0 is the track,
  2 is channels 3/4. A send's `AUXRECV` field 9 is the channel pair it lands on (2 = 3/4).
- A sidechain retune checked in REAPER's render: the bad setting (release 1000 ms on hits 500 ms apart) ducked
  21.0 dB (model 20.7), the suggested one 4.0 dB (model 3.0) and was fully back by the next kick (model 99%).
  ReaComp's release recovers more slowly than Live's model at long settings (6% back vs 36% modelled).
- **JSFX variable names are case-insensitive**: `N` and `n` are one variable (it made every sample a "block"), and so
  are `BASE` and `base`. A test checks the hypnomix JSFX for names that differ only in case.
- Probe shared memory (gmem `hypnomix`): `gmem[0]` = layout version; slot k at `64 + k·194`: count of blocks, sample
  rate, then a ring of 8 records of (beat, playing, play position, block number, the 20 values). The block count is
  written last, so the bridge only reads a record once it is complete. A new JSFX needs no REAPER restart when added by
  path: `TrackFX_AddByName(tr, "JS:hypnomix/hypnomix_probe.jsfx", …)`.
- The probe measured against the same audio offline: loudness -12.36 vs -12.40 LUFS (BS.1770), peak, L/R and low-end
  correlation, mid and side identical to 0.01 dB.
- Rendering with the project's sample rate following the device (`SAMPLERATE x 0`) resamples: set
  `PROJECT_SRATE` and `PROJECT_SRATE_USE` when comparing sample for sample.

## Stock plug-ins (what `chain --reaper` relies on)

- **ReaEQ**: 5 bands, no more (a second ReaEQ beyond that). Named config `BANDTYPEk`: 0 low shelf, 1 high shelf,
  3 low pass, 4 high pass, 5 all pass, 8 band (bell); `BANDENABLEDk`. Parameters by index `3k` freq, `3k+1` gain,
  `3k+2` bandwidth in OCTAVES (`Q → octaves = 2/ln2 · asinh(1/(2Q))`). Measured against the plan: within 0.04 dB.
- **ReaEQ in a saved project** (read from a chunk REAPER 7.86 saved; `rpp_edit.ReaEQ`): three base64 parts. Header: the
  plug-in id, two input and two output pins, then the state's byte count, 1 and 0x00100000. State: a record size (33),
  the band count, then per band the type, enabled, frequency (Hz), gain (as an amplitude, 1 = 0 dB) and bandwidth (in
  octaves) as doubles and one flag byte; then a 32-byte trailer. Tail: `00 00 10 00 00 00`. The band types are the
  named-config numbers above. `masking` / `fix` write a cut as a bell (8) into a free band (switched off, or a bell at
  0 dB) of a ReaEQ already on the track, else a new ReaEQ at the end of the chain with that one band; a ReaEQ stays
  within five bands and the rest of its state is written back byte for byte. Checked by reading a REAPER-saved chunk
  back and writing it again unchanged; a chunk `masking` wrote was then opened in REAPER 7.86 and the band's frequency, gain and bandwidth read back exactly as written (REAPER's own renders with the effect on and bypassed show the cut).
- **ReaComp**: Threshold, Ratio (shows "inf" at the top), Attack, Release, RMS size, Knee.
- **ReaLimit**: Threshold, Ceiling, Release. The level goes up by `ceiling - threshold`. It limits SAMPLE peaks: the
  true peak can be over the ceiling, so `--verify` checks the whole song and lowers the ceiling.
- **JS: Bass Manager/Booster** "Mono" makes the WHOLE signal mono: not a bass-mono. hypnomix uses JS Mid/Side
  Encoder → ReaEQ (two high passes, pins on channel 2 only) → ReaEQ (all pass, pins on channel 1 only) → JS Mid/Side
  Decoder: leak under -68 dB at 400 Hz and -94 dB at 2 kHz.
- Plug-in pins: `TrackFX_SetPinMappings`; a channel no output pin writes passes through unchanged.
- Item lanes (REAPER 7): the track has `FREEMODE 2` (fixed lanes) or `1` (free positioning) and items carry `YPOS`;
  hypnomix never moves items off or onto such tracks.

## The mastering chain on Hypnomix Main

`hypnomix/reaper/masterchain.lua`, loaded by the bridge. Main's buttons count presses in gmem[11] (Build), [12]
(Match target), [13] (Save); the script answers in gmem[14] (state code, listed in the script and in
`reaper/cli.py` STATES) with gmem[15] and [16] (two numbers). The chain is the plug-ins before Main whose
`renamed_name` starts "Hypnomix · ". Plug-ins are inserted with `TrackFX_AddByName(..., -1000 - position)`.
Templates are `.RfxChain` files written from the master's state chunk (each plug-in's BYPASS line, block and
FLOATPOS / WAK lines; FXID lines dropped so REAPER gives new ids) and loaded by splicing them back into the chunk
just before Main. Match target reads Main's own K-weighted blocks from the probe relay (100 ms each, BS.1770 gate
over 400 ms windows), adds the master fader, and moves ReaLimit's threshold; if it started playback itself it stops
it again when it is done or cancelled. Build with saved templates asks with `gfx.showmenu`: on macOS the menu only
stays open from a real window that is already up, so a 1x1 window opens at the mouse and the menu follows a few
loop passes later (`menu_poll`); a 0x0 window with the menu in the same pass closed by itself after under a second,
answering "cancelled" (measured in REAPER 7.86). Before every menu or dialog the script reports state 14 (waiting
for an answer), so Main does not say the bridge is gone while the dialog blocks it.

## The bridge

`bridge.lua` runs inside REAPER, started by running REAPER's program with the script path (it runs in the
REAPER that is open, or starts REAPER). The folder is `~/.hypnomix/reaper-bridge`. A request is `req-<id>.txt`
(command, then `key=value` lines); the answer is `res-<id>.json`. Only the commands in the script exist; every
change is one undo step. Things that bit:

- `EnumerateFiles` caches the listing: list the folder once per pass (index 0 re-reads), and skip a request file
  that is already gone, or a stale listing answers it twice.
- Lua's `tonumber` does not read `+0.00`; displays also show `-inf` and `inf`.
- Plug-in displays can be Latin-1 (`°`): decode answers leniently.
- JSFX `import`: an effect's own `@init` / `@slider` / `@sample` REPLACE the imported file's sections (they do not
  add to them). Hypnomix Main had its own `@init`/`@sample` for the A/B gain and silently stopped measuring; the gain
  now lives in the include (`abgain`, 0 = unity on probes) and Main only adds `@gfx`. A test keeps it that way.
- `match` is a built-in EEL2 string function: a slider or variable with that name stops the effect compiling.
- The panel is a `gfx` window: it reads the real mouse, so background (synthetic) clicks do not reach it, and the
  first click on it while REAPER is behind another app only focuses it. Redraws lag a poll or two.
- The Align panel shares that window (`panel_open mode=align`). After a click in REAPER's own windows, a click on
  the panel's body does not reach it: the panel window has to become key first (a click on its title bar does).
  Its sliders follow a drag and report `set:<name>=<value>` on release; values sent from Python are ignored for a
  moment after a drag so the slider does not jump back.
- Stretch markers (`SM`): the source time includes the take's offset (`SetTakeStretchMarker(take, -1, 10, 40)` with
  SOFFS 30 saves `SM 10 40`). With "preserve pitch", REAPER's stretch engine plays stretched or shifted stretches
  about 4 ms later than the marker map (median; the same in every élastique mode); in varispeed it is exact.
- `Main_SaveProjectEx(proj, path, 0)` saves a copy: the tab stays "[Unsaved]". Quitting REAPER (40004) then asks
  to save it, and the dialog stops every script. Several sessions' command-line scripts all run in the one open
  REAPER, in whatever tab is current: open a tab of your own (40859), and close only that.
- Stems: `RENDER_SETTINGS` 3 with the tracks selected (2 renders one mix of the selected tracks).
- Closing a changed project tab asks "save?", and a dialog stops the bridge. Save a throwaway copy, reopen it with
  `Main_openProject("noprompt:" .. path)`, then close (action 40860). The bridge only closes tabs it opened.

## Checking against REAPER

Make REAPER the reference: a Lua script given on REAPER's command line builds a test project through the API,
saves it (`Main_SaveProjectEx`), renders stems (`RENDER_SETTINGS` 3, action 42230) and closes its tab. Then
compare REAPER's saved file with what the reader reads, and REAPER's render with hypnomix's. A **ramp** source
(each sample's value is its own position in the file) shows exactly which source position REAPER plays at
every moment, through stretches, loops and playrate. The tests in `tests/test_rpp.py` and
`tests/test_chain_reaper.py` hold the measured values.

## Opened and read back in REAPER 7.86

On 2026-11-26 these files, written by hypnomix's newest code, were opened in REAPER 7.86 and read back through its API. Each opened with no offline media and matched what hypnomix wrote:

- the demo project (`hypnomix demo --kind reaper`);
- a project written by `fix`, with an item fade and a volume-envelope dip;
- masking cuts written as ReaEQ bands (`masking --apply NEW.rpp`, and `fix`): frequency, gain and bandwidth read back exactly as written, and REAPER's own renders with the effect on and bypassed show the cut;
- the `Song (handoff).rpp` marker (position and name);
- the A/B project (`abset`).

What this does not cover: none of these has been run on a real song, and nothing here was judged by ear. Open one in REAPER and listen before you rely on it, and add what you measure to this file.
