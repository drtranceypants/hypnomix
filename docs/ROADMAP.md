# Roadmap

What is built, what comes next in order, what comes later, and what is not planned. The aim stays the same: help
an independent artist get from recordings to a release quickly, with free tools, and with the person deciding
every change.

**What comes next, in one sentence:** open everything the newest release added in real DAWs and on real songs,
before building anything else on top of it.

## Checked where

- The Live devices and the Live fix paths were tested in Live 12.
- REAPER support was tested in REAPER 7.86.
- Everything newest passes unit tests and hypnomix's own structure checks on synthetic data only. The new Live
  sets, REAPER projects and Ardour snapshots have not been opened in their DAWs, and the new tools have not been run
  on real songs.

Items marked *(to verify)* below rest on research that has not been tested here yet.

## (a) Built

One line per area. Each command's own help (`hypnomix <command> -h`) and its wiki article say how it works.

- **The first pass:** `scan` (a Live set, a REAPER project, an Ardour session, or a folder of recordings), `ab`,
  `review`, `fix`, `history` (every version, undo into a new file), `watch`, `prefs`, `taste`, `profile`. `fix --list`
  pages through a long scan and `fix --show ID` prints one finding in full.
- **Around the scan:** `preflight` (the files before any work), `demo` (a 40-second song with labelled problems, to
  learn the loop on nothing of your own), `handoff` (the by-hand list in your DAW's words, with markers).
- **Clean-up in a set:** `smooth`, `edges`, `clicks`, `name`, `order`, `tidy`, `unroll`, `devices`, `distortion`,
  `sidechain`, `duck`, `automation`, `check`, `diff`.
- **Vocals and recordings:** `tune` (with the chord check), `key`, `vocalign`, `alignset` (and the Hypnomix Align
  device and panel), `voices`, `cliplevel`, `vocallevel`, `deess`, `breaths`, `dehiss`, `cleanup`, `clipmatch`,
  `takes`, `soundcheck`.
- **Feel and variety:** `timing`, `tighten`, `tempomap`, `loops`, `breathe`, `variations`, `borrow`, `motion`, and
  `colour` (Live sets).
- **Engineer and master:** `automix`, `balance`, `master`, `chain` (Live and REAPER), `rebalance`, `tonal`, `harsh`,
  `masking` (an approved cut is written as an EQ Eight band in Live or a ReaEQ band in REAPER, in a new file),
  `match`, `reference`, and `--plan` for `prep`, `automix` and `master`.
- **Release:** `translate`, `qc`, `release`, `versions`, `compare`, `album`.
- **Previews:** `ab` builds before and after pairs for clips, tuning, timing nudges, masking cuts and changes to six
  of Live's stock devices (labelled as a model of the device); `abset` puts every fix next to yours inside Live;
  `plugrender` and `plugins` bring your own VST3 and Audio Unit plug-ins in.
- **Inside Live:** `live`, `loop`, `diagnose`, `probe` and the Max for Live devices (HypnomixProbe, HypnomixMain,
  the review device, Hypnomix Align).
- **REAPER:** `project`, `scan` and `fix` on an `.rpp` (a new project), `reaper` (the bridge, Hypnomix Probe and
  Main, the A/B review panel, the Align panel), `chain --reaper`.
- **Ardour:** `project` and `scan` on a session (Ardour 3 to 9), and `fix` writes approved fades, gain, dips and
  fader, pan and mute moves into a new `.ardour` snapshot.
- **The app and teacher mode:** `app` (the first pass by clicking), the Assistant and the optional Listener, and the
  Teacher tab: three courses per DAW, including the complete course A to Z.
- **Safety and care:** a security pass (the Assistant runs only read-only commands without a click, wiki content is
  cleaned, updates are checked harder) and automatic disk care.

### Why the review is the product

The loop (scan, hear, approve, apply, measure again) is the same for every DAW: the same findings, the same
decisions, the same "new files only". What hypnomix cannot change in a DAW becomes a to-do in that DAW's own words
(`handoff`). That is why a folder of exported tracks from any DAW already gets most of the value.

## (b) Next, in order

1. **Open everything the newest release added, in real DAWs and on real songs.** The items: the new EQ bands for
   masking cuts (EQ Eight in Live, ReaEQ in REAPER); the handoff markers (locators in a Live set, markers in a REAPER
   project); the colour chains in a Live set; `balance` on a real folder of stems; the Ardour snapshots, opened in
   Ardour (the snapshot opens without a warning, the audio is found, fades and gain are as written, the pan goes the
   way round expected with azimuth 0 on the left, the trim is unchanged), plus a session saved by Ardour 8 or 9 with
   hypnomix's renders compared with Ardour's own export; `release`, `compare`, `versions`, `album`, `preflight` and
   `demo` on real music; and the sets written by `tempomap`, `loops`, `variations`, `motion` and `borrow`, opened in
   Live and judged by ear.
2. **Colour beyond Live sets:** REAPER and Ardour projects, and an instrument doubling a line (from `midi`: it needs
   an instrument device chain and the MIDI clip written, both new).
3. **`ab` for REAPER projects** (it plays Live sets today), and models for Saturator, Reverb and Delay.
4. **Space checks in `devices`:** delay times against the tempo, reverb low cuts.
5. **A `comp` writer from ranked takes:** `takes` ranks them and lists the best take per section today; nothing
   writes the comp into a project yet.
6. **Ardour, hands-on:** drive the open session through its Lua scripting and OSC, for `chain` with Ardour's own
   plug-ins (EQ, compressor, expander, delay, reverb).
7. **Windows and Linux parity:** file pickers, and loopback capture without a macOS-only device for the loops that
   verify a chain.
8. **Signed installers:** signed with a publisher key, with the app checking that signature before it updates.
9. **A private access token for shared computers:** so the app on a shared machine is not open to everyone using it.

## (c) Later

- **Pro Tools.** Read: the "session info as text" export (tracks, clips, markers), parsed into the project model: no
  app control, works on every edition. An open-source reader for session files exists and can be an optional extra
  *(to verify: what it covers)*. Then drive: the official scripting SDK (a local service, in every edition since late
  2022 *(to verify)*): read the track list, add markers at each finding, import repaired audio as new tracks, bounce
  for a re-scan, and "save session as" before any write. Read-only by default; every write approved. It does not
  appear to control plug-ins or write automation *(to verify)*, so tone and dynamics moves stay as rendered audio or
  to-dos. The SDK's interface file has its own licence: the person downloads it rather than hypnomix shipping it.
- **Logic Pro.** The project is an undocumented binary bundle. Reading track names, plug-in lists and tempo is
  possible but fragile: read-only, fail-soft, and it needs upkeep with each Logic release. Writing it is not safe and
  not planned. Logic has no scripting API for the mixer; the reliable route for live moves is to act as a control
  surface (faders, pans, mutes over a virtual MIDI port), with interface scripting only for bounce and export. Where
  its built-in assistants help, the review says "run this, bounce, and I'll measure the result".
- **A local, open-weights listening model**, so notes by ear need no cloud model. Advice only, labelled as such,
  never a source of numbers, run on the person's own computer.

### Which DAW can do what

| DAW | read the project | write your approved fixes | drive the open app |
|---|---|---|---|
| Ableton Live | yes (`.als`) | yes: a new `.als` | yes (AbletonOSC, the Max for Live devices) |
| REAPER | yes (`.rpp`) | yes: a new `.rpp` | yes: through the bridge |
| Ardour | yes (`.ardour`, Ardour 3 to 9) | yes: a new `.ardour` snapshot (not yet opened in Ardour) | planned |
| Pro Tools | audio folders only today | audio folders only today | later |
| Logic Pro | audio folders only today (there is no Logic reader) | audio folders only today | later (a control surface) |

For any DAW, `hypnomix scan FOLDER` on exported tracks works today: review, `fix` writes repaired copies, and
`handoff` turns what must happen in the DAW into a checklist in that DAW's words (with markers: a MIDI file and a
CSV when there is no project to write into).

## (d) Not planned

- Changing a project file in place, in any DAW.
- One-click "finish my song". Every assistant in this field that people trust keeps its moves visible,
  editable and reversible; the ones people abandon act as a black box.
- Anything that sends audio off the person's computer without asking each time.
- Naming or depending on paid plug-ins.
