# REAPER: how HypnoMix reads, writes and drives it

For people and agents changing HypnoMix's REAPER code. The user guide is `docs/guides/08-inside-reaper.md`.
Facts below were measured in REAPER 7.86 unless a row or section says otherwise (how: see "Checking against REAPER" at the end). That includes the files HypnoMix's newest code writes: on 2026-11-26 the demo project, a project written by `fix`, the masking cut as a ReaEQ band, the hand-off project's marker and the A/B project were opened in REAPER 7.86 and read back through its API. The same day, in a private REAPER 7.86 instance on one Mac with a two-track test project (see "Opened and read back in REAPER 7.86" at the end): the HypnoMix Probe, HypnoMix Main, Review and Align windows opened and their guides were captured by screenshot (not clicked through by hand), and HypnoMix Main left an amount of 73 untouched; `ui.lua` and `mixer.lua` loaded with no error; `reaper snapshot` / `diff` / `restore` were exact; `loop --ab "nudge Bass -3"` measured B at -1.4 LU and `--revert` put the mix back; `diagnose` put every solo back (no project with folders was tried); a ReaComp written by `fix` read back at -17 dB, 4:1, 15 ms, 250 ms; the `vocallevel --apply` envelopes opened again (106 points, all within +-3 dB; written before the 2026-11-27 change that leaves untouched points as they are and refuses hot envelopes, which is unit-tested only); and the Teacher's reverb (ReaVerbate Wet 0 dB, Dry -inf) and saturation (JS: Saturation Amount 20%) steps read back. Not checked: clicking the windows by hand, Windows, a real song, listening (nothing here has been judged by ear), the ReaGate and ReaLimit settings, and `diagnose` on a project with folders.

## Where the code is

| file | what |
|---|---|
| `hypnomix/project/rpp.py` | parser and writer for REAPER's chunk format. An untouched load + save is byte-identical; `save` refuses the file it was read from |
| `hypnomix/project/model.py` | the DAW-neutral model (seconds), the renderer, fade curves, stretch-marker map, envelope interpolation |
| `hypnomix/project/reaper.py` | `.rpp` → model |
| `hypnomix/project/rpp_edit.py` | edits on the parsed chunks (fades, item volume, volume dips and eases, new takes, reorder, rename) and the structure check |
| `hypnomix/workflow/scan_project.py` | `scan` on an `.rpp` (and a HypnoMix DAW session) |
| `hypnomix/workflow/scan_project.py` `stack_moves` | vocal stacks: Live's `order.assign_stack` on the model; `rpp_edit.move_item` moves the ITEM chunk (takes and take envelopes go with it); `check(moved=IGUIDs)` |
| `hypnomix/workflow/timing_project.py` | Live's timing judgement (`session/timing.judge`) on hits read from items; nudges written as stretch markers (`SM`), anchored on every onset either side |
| `hypnomix/workflow/devices_project.py` | the `devices` group: each ReaComp on its own track (detector on the track itself) read as `sidechain_project` reads it and judged with Live's `devices` model (`engineer/devices.judge_compressor`) on the track's render; `fix` writes the suggested threshold, ratio, attack and release as those four floats (`apply`; an approval amount moves each that share of the way) and refuses a ReaComp changed since the scan. ReaEQ (`rpp_edit.ReaEQ`): a low cut suggested, by hand, when no band is a high pass. ReaGate and ReaLimit are listed, not judged: their saved state's layout has not been measured. A ReaComp with Wet at 0, or with dry and wet mixed (parallel compression), is listed and not judged, and gets no fix; the master track's plug-ins are not read. On 2026-11-26 in REAPER 7.86 a ReaComp fix written by `fix` read back exactly (-17 dB, 4:1, 15 ms, 250 ms) on a two-track test project; not judged by ear, not run on a real song |
| `hypnomix/workflow/scan_project.py` `g_structure` | the `structure` group: the file reads back byte for byte (`rpp.load` + `dumps`), folders (`ISBUS`) close, every `AUXRECV` comes from a track that exists, faders at +12 dB or under -40 dB with items |
| `hypnomix/workflow/sidechain_project.py` | sidechained ReaComps: found by their detector channel and the sends landing there, simulated with Live's `sidechain` model, suggestions written as ReaComp floats. One with Wet at 0, or a parallel (dry and wet) mix, is listed and not judged (Dry / Wet read as the `devices` group reads them) |
| `hypnomix/reaper/jsfx/`, `reaper/probes.py` | HypnoMix Probe / Main as JSFX: 20 values per 100 ms into gmem `hypnomix`; the bridge assigns slots and keeps blocks (`probe_blocks`); `probes.feed` relays them into the app's `probe.Hub`; `insert` and `read_cards` for `.rpp` |
| Record and review (`bridge.lua` `rec_*`, `probes.handle`, `server.reaper_record`) | Main's `@gfx` button adds 1 to gmem[8]; the bridge plays from the cursor, keeps start and furthest position, and queues start/stop events for `probe_blocks rec=1` (only a relay that asks gets them, and only it counts as "an app is there"); state back to Main in gmem[9] (0 idle, 1 recording, 2 rendering, 3 no app, 4 reviewing, 5 under a second played: no event sent, 6 the app's review failed), seconds in gmem[10]. Main reads the mouse each `@gfx` frame (about 30 a second) and counts a press on RELEASE over the button: REAPER does not start playing while the mouse is still held in an FX window, so acting on mouse-down left a normal (held) click with no playback. The bridge also waits up to 3 s for playback to start before it calls a take finished. A synthetic click shorter than a frame can still be missed. On stop the app closes the probe capture FIRST (a render runs every JSFX again and would add its blocks), renders `render_master(start, end)` and runs the same review steps as Live's `master_record`. `hypnomix reaper record` = a press |
| `hypnomix/workflow/handoff.py` (`write_rpp`) | `handoff` on an `.rpp` scan: a NEW `Song (handoff).rpp` with one `MARKER` line per by-hand spot (position in seconds, a name, a new GUID), read back and compared with the original; nothing else in the project changes. Opened in REAPER 7.86 and read back: the marker's position and name matched what was written |
| `hypnomix/studio/demo.py` | `demo --kind reaper`: a short synthetic song as stems plus a project that plays them (the comps as separate items on separate takes), so every planted problem is visible to `scan`. Round-trips through `rpp.load`; opened in REAPER 7.86 with no offline media |
| `hypnomix/engineer/masking.py` (`write_project`), `rpp_edit.add_reaeq_cut` | `masking --apply NEW.rpp` and `fix` on an approved frequency-fight finding: a bell cut as one ReaEQ band on the track that should give way (see "ReaEQ in a saved project" below). Opened in REAPER 7.86: frequency, gain and bandwidth read back exactly as written |
| `hypnomix/workflow/edges_project.py` | Live's word-edge detectors on the model; the REAPER edge fixes |
| `hypnomix/workflow/fix_project.py` | `fix` for an `.rpp`: one pass into one new file, structure check, re-measure |
| `hypnomix/workflow/vocallevel_project.py` | `vocallevel` on a project: tracks rendered from the model, times fader x volume envelopes (VOLENV2, VOLENV, VOLENV3; fader-scaled ones through `envelope_at(fader=True)`) of the track and its folders; Live's `plan` unchanged; `--apply NEW.rpp` writes the S-curve points into `VOLENV2` (created at 1.0), existing points scaled where they sit, the folder only when it holds only vocals; `rpp_edit.check`, then re-measured (signals x new curve / old curve). Unit tests in `tests/test_vocallevel_reaper.py`; on 2026-11-26 in REAPER 7.86 the `--apply` envelopes opened (106 points, all within +-3 dB; written before the 2026-11-27 change that leaves untouched points as they are and refuses hot envelopes, which is unit-tested only) on a two-track test project; not judged by ear, not run on a real song. `--apply` and `--json` refuse an existing file, the original under any spelling of its name, and a folder that does not exist; envelope points far from every change are left exactly as they are; a track whose envelope is, or would go, above +6 dB in a change window is refused and listed (whether REAPER stores points above +6 dB was not checked in REAPER) |
| `hypnomix/reaper/bridge.lua`, `client.py`, `cli.py` | the bridge into the open REAPER, and `hypnomix reaper`. While a command runs the bridge writes a `busy` file next to `alive`, so a long render is not taken for a stopped bridge; a second `hypnomix reaper start` replaces the running bridge instead of adding one. Both files carry the bridge's start token and REAPER's process id (from `echo $PPID` at startup; 0 on Windows, where Lua has no quick way to get it): a `busy` file from an earlier bridge, or whose REAPER has ended, does not count, and `start` waits for a beat written after it launched. On Windows a `busy` file left by a REAPER that crashed mid-command still counts until it ages out (the command's limit plus a minute). A failure inside the bridge is written to `last-error.txt`, and a call that times out says what it was. The busy file was seen during a real `diagnose` in REAPER 7.86 (2026-11-27); the process-id check is unit-tested only |
| `hypnomix/engineer/chain_reaper.py` | `chain --reaper` |
| `hypnomix/workflow/abset_project.py` | `abset` on an `.rpp`: each fix built alone (`fix` on a throwaway scan copy), compared track by track (by GUID); plug-in-only changes copy the FX block after the original with `BYPASS 1` and a new `FXID`; other changes copy the whole track (`fresh_ids`, `MUTESOLO 1`) via `rpp_edit.insert_copies`, which keeps folders (`_layout` rebuilds ISBUS) and mirrors the original's sends (`AUXRECV` lives on the receiving track); writes `ab_live.json` with `daw: reaper` |
| `hypnomix/studio/alignset_rpp.py`, `hypnomix/reaper/align.py` | `alignset` on an `.rpp` (stretch markers via `rpp_edit.set_stretch`, pitch / formant / `--takes` as new takes via `add_take(offset=0, rate=1)` on per-item files that sum back to the checked render) and `hypnomix reaper align`: the HypnoMix Align panel (`panel_open mode=align`, `align_where`, `align_draw`) sending the Live device's request to `/api/align/*` |
| `hypnomix/reaper/jsfx/hypnomix_ui.jsfx-inc`, `hypnomix/reaper/ui.lua` | the HypnoMix look and the built-in guide: the JSFX windows (Probe, Main) and the bridge's panels (Review, Align) draw rounded cards, buttons, chips, steppers and meters in the app's palette at Retina resolution (`gfx_ext_retina`), and a step-by-step guide (dim everything but one spot, a card with Back / Next / Done / Skip guide) started by the **?** and shown once per computer while the bridge runs (otherwise once per plug-in and once per REAPER session). The JSFX sliders are hidden (`-`) and set from the window (`gfx_showmenu`, `slider_automate`); `probes.menus` reads them by name, skipping `INTERNAL` (slot, abgain, guide). In the Review and Align panels space plays and stops, and Esc closes the guide when it is showing, otherwise the panel; the Probe's labels read WIDTH (L/R) and LOW END (<120 Hz). Not checked in REAPER |
| `hypnomix/reaper/mixer.lua`, `mixer.py` | `hypnomix reaper snapshot / loop / diagnose`, the REAPER side of Live's `live snapshot`, `loop` and `diagnose`. `mixer.lua` is loaded by `bridge.lua` like `masterchain.lua` (`dofile`, then `MX.commands(C, CHANGES)`) and adds the `mixer_*` commands below. A snapshot is JSON from `mixer_snapshot`; a restore is a flat tab-separated file `mixer.py` `flatten` writes into the bridge folder (only whitelisted keys and numbers; the bridge has no JSON reader). Loop takes are `render_master` renders measured with `loop.py`'s metrics and `report`; diagnose renders the whole master, picks the loudest bars from `mixer_timemap`, then `mixer_solo_render` per top-level folder or track and measures the bands with `doctor.py`'s `band_db` / `low_corr`. Each run keeps its renders and diagnose.json in a new numbered folder, hypnomix-out/diagnose/reaper-<song>/run-001, run-002 and so on, so an earlier run is never replaced; the command prints where. On 2026-11-26 in REAPER 7.86 `reaper snapshot` / `diff` / `restore`, `loop` (with `--ab` and `--revert`) and `diagnose` ran on a two-track test project; nothing judged by ear, none on a real song |
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
  are `BASE` and `base`. A test checks the HypnoMix JSFX for names that differ only in case.
- Shared memory used by the JSFX windows: `gmem[2]` counts the bridge's passes (a count that moves = "bridge on");
  `gmem[3]` is set to that count whenever something asks the bridge for probe blocks ("app on" while the gap is small);
  `gmem[5]` / `gmem[6]` = the Probe's / Main's guide was seen, which the bridge keeps in REAPER's extended state
  (`hypnomix` / `guide_probe`, `guide_main`; the panels use `guide_review`, `guide_align`). Measured in REAPER 7.86:
  two imported files may each have an `@init`; both run and their functions are callable from the effect's `@gfx`.
  The plug-ins are named "HypnoMix Probe" / "HypnoMix Main" (older copies spell them with a small m): every lookup by name is
  case-insensitive. REAPER keeps an FX's display name in its JSFX cache: after updating, an old name can show until
  the FX browser is refreshed (F5); the bridge finds both.
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
- **JS: Bass Manager/Booster** "Mono" makes the WHOLE signal mono: not a bass-mono. HypnoMix uses JS Mid/Side
  Encoder → ReaEQ (two high passes, pins on channel 2 only) → ReaEQ (all pass, pins on channel 1 only) → JS Mid/Side
  Decoder: leak under -68 dB at 400 Hz and -94 dB at 2 kHz.
- Plug-in pins: `TrackFX_SetPinMappings`; a channel no output pin writes passes through unchanged.
- Item lanes (REAPER 7): the track has `FREEMODE 2` (fixed lanes) or `1` (free positioning) and items carry `YPOS`;
  HypnoMix never moves items off or onto such tracks.

## The mastering chain on HypnoMix Main

`hypnomix/reaper/masterchain.lua`, loaded by the bridge. Main's buttons count presses in gmem[11] (Build), [12]
(Match target), [13] (Save); the script answers in gmem[14] (state code, listed in the script and in
`reaper/cli.py` STATES) with gmem[15] and [16] (two numbers). The chain is the plug-ins before Main whose
`renamed_name` starts "HypnoMix · " (older chains "Hypnomix · "; `ours` compares lower-cased, so both are found and replaced). Plug-ins are inserted with `TrackFX_AddByName(..., -1000 - position)`.
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
  add to them). HypnoMix Main had its own `@init`/`@sample` for the A/B gain and silently stopped measuring; the gain
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

### The mixer commands (`mixer.lua`; run on a two-track test project in REAPER 7.86, not on a real song)

| command | arguments | what it does |
|---|---|---|
| `mixer_snapshot` | `max_params` (default 4096) | the master first (index -1), then every track: name, GUID, `D_VOL`, `D_PAN`, `D_WIDTH`, `B_MUTE`, `B_PHASE`, `I_SOLO`, `I_FOLDERDEPTH`, the sends (index, destination name, volume, pan, mute, mode) and each plug-in (index, name, FX GUID, on, offline, every parameter's normalized value, name and what it shows; `truncated` past `max_params`). HypnoMix Probe / Main slot parameters are left out (the bridge sets them). No change |
| `mixer_restore` | `file` (a restore file in the bridge folder) | sets only the values that differ, matching tracks and plug-ins by GUID (then by index and name), a send only while it still goes to the same track; one undo step, "hypnomix: snapshot restore". Answers `changed` and `missing` |
| `mixer_send` | `track`, `send` (0-based), `volume_db`, `pan`, `mute` | one send; one undo step, "hypnomix: mixer_send" |
| `mixer_timemap` | none | `length` (s), `tempo`, `bars`: the start of every bar from 0 s (`TimeMap2_beatsToTime(0, 0, m)`), through the first one at or past the end |
| `mixer_solo_render` | `tracks` (GUIDs, comma-separated), `start`, `end`, `path` | solos those tracks in place (`I_SOLO` 2) and every other track off, runs `render_master`, then puts every track's solo back as it was: nothing is left changed, so no undo step |

Send destinations come from `GetTrackSendName(track, hardware outputs + i)`: that function counts hardware outputs
first. Unchecked in REAPER: the destination names, solo in place letting a folder's children and the send returns of a
soloed track play in the render, and how long `mixer_snapshot` takes on a project with large plug-ins.

## Checking against REAPER

Make REAPER the reference: a Lua script given on REAPER's command line builds a test project through the API,
saves it (`Main_SaveProjectEx`), renders stems (`RENDER_SETTINGS` 3, action 42230) and closes its tab. Then
compare REAPER's saved file with what the reader reads, and REAPER's render with HypnoMix's. A **ramp** source
(each sample's value is its own position in the file) shows exactly which source position REAPER plays at
every moment, through stretches, loops and playrate. The tests in `tests/test_rpp.py` and
`tests/test_chain_reaper.py` hold the measured values.

## Opened and read back in REAPER 7.86

On 2026-11-26 these files, written by HypnoMix's newest code, were opened in REAPER 7.86 and read back through its API. Each opened with no offline media and matched what HypnoMix wrote:

- the demo project (`hypnomix demo --kind reaper`);
- a project written by `fix`, with an item fade and a volume-envelope dip;
- masking cuts written as ReaEQ bands (`masking --apply NEW.rpp`, and `fix`): frequency, gain and bandwidth read back exactly as written, and REAPER's own renders with the effect on and bypassed show the cut;
- the `Song (handoff).rpp` marker (position and name);
- the A/B project (`abset`);
- a ReaComp fix written by `fix`: threshold, ratio, attack and release read back exactly (-17 dB, 4:1, 15 ms, 250 ms);
- `vocallevel --apply NEW.rpp`: the envelopes opened (106 points, all within +-3 dB; written before the 2026-11-27 change that leaves untouched points as they are and refuses hot envelopes, which is unit-tested only);
- `hypnomix reaper snapshot`, `diff` and `restore` (exact), `loop --ab "nudge Bass -3"` (B measured at -1.4 LU) with `--revert` (the mix put back) and `diagnose` (every solo put back), run against a two-track test project with no folders;
- the HypnoMix Probe, HypnoMix Main, Review and Align windows and their guides, captured by screenshot (HypnoMix Main left an amount of 73 untouched), and `ui.lua` and `mixer.lua`, loaded with no error;
- On 2026-11-27, after the second review's changes, the same private instance again: both JSFX compiled and drew their new texts and labels, the bridge, `ui.lua` and `mixer.lua` loaded, the Review window (titled "HypnoMix Review") and the Align panel drew, `snapshot` (no "guide seen" values in it), `diff`, `restore`, the refusal of an existing OUT.json and `snapshot -h` behaved as described, `loop --ab "nudge 1 -3"` on a track named "1" measured B at -1.4 LU and `--revert` put it back, and `diagnose` wrote the bridge's `busy` file during its renders (the bridge stayed "running") and removed it after. Still not tried: the space and Esc keys in the panels, and clicking through the guides by hand.
- the Teacher's reverb step (ReaVerbate reads back Wet 0 dB, Dry -inf) and saturation step (JS: Saturation reads back Amount 20%).

What this does not cover: none of these has been run on a real song, and nothing here was judged by ear. The windows were not clicked through by hand, nothing was tried on Windows (the gfx windows, the `gfx_showmenu` menus and the lessons' Windows steps included), the ReaGate and ReaLimit settings are not read, and `diagnose` has not been run on a project with folders or send returns. The new lessons' REAPER menu paths were not walked in REAPER, apart from the Teacher's reverb and saturation steps above. Open one in REAPER and listen before you rely on it, and add what you measure to this file.
