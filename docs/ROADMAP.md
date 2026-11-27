# Roadmap

What is built, what comes next in order, what comes later, and what is not planned. The aim stays the same: help
an independent artist get from recordings to a release quickly, with free tools, and with the person deciding
every change.

**What comes next, in one sentence:** open everything the newest release added in real DAWs and on real songs,
before building anything else on top of it.

## New in 0.4.0

The six changes you will notice most, in plain words:

1. **Projects from other DAWs.** `import` brings a .als, .logicx, .dawproject or .rpp project across as a new HypnoMix Studio
   session, with the audio copied and a report of what was left out; your project is only read. A .ptx session or an
   .aaf export needs the HypnoMix Studio add-on, which is not available yet, and no imported session has been opened in a
   released DAW.
2. **REAPER at Live's level.** The HypnoMix Probe, HypnoMix Main, Review and Align windows in REAPER now have built-in
   guides, and `reaper snapshot`, `reaper loop` and `reaper diagnose` do what their Live versions do. `vocallevel`
   measures and writes REAPER projects, and the scan judges each ReaComp and checks the project's structure. Tried in
   REAPER 7.86 on a two-track test project only: not on a real song, not on Windows, not by ear. Run
   `hypnomix reaper probes install` again to get the new windows.
3. **The DAW view, round 2.** Take lanes and comping, groups and sidechains, live meters, cue slots in the Session view
   and an A/B session. `tidy`, `order` and `duck` can write groups and compressors into the open session
   (`--engine --ids`), and `loops` and `variations` can fill cue slots (`--cues`). Tested against stand-in engines and a
   silent development engine only; HypnoMix Studio is not released, and its add-on is not available yet.
4. **MPE clips.** The scan of a HypnoMix Studio session lists what may spoil per-note bend, pressure and slide, with one
   fix: values stored so that they glide are held instead, in a new snapshot. Read from the files only; nothing has
   been played on a controller yet.
5. **Tests on macOS and Windows.** The test suite runs on macOS and Windows (Python 3.9 and 3.12) on every push. Tests
   that cannot work on Windows skip there, each with a reason. Linux had a first pass in 0.3.1 and is no longer tested.
6. **Windows fixes the new test runs found.** Reports hide a Windows home path inside saved data; a folder given where a
   file is expected, and a name longer than the file system allows, each end in one sentence; and the Live options
   command keeps the file's own line endings.

## New in 0.3.1

The six changes you will notice most, in plain words:

1. **One app, one installer, and HypnoMix Studio as an add-on.** There is one download for everyone. HypnoMix Studio (its engine is a
   separate GPL program) is built but not available yet: when its archive is published it is added from Setup, on a
   click, and checked against a fingerprint before it is used. `hypnomix engine` shows or removes it.
2. **Reporting a problem.** `report` and the app's Report button write a bug report, or the record of a crash, on your
   computer and show it to you first, with paths, names and keys hidden as far as HypnoMix can tell. Nothing is ever sent:
   you copy it, save it or paste it into the project's issue page yourself.
3. **A guided tour in the DAW page.** Short, optional spotlights on one real control at a time (first look, edit a
   region, mix, scan and review, ask the Assistant, save and export); they never change your song.
4. **A bigger Store.** 69 free plug-ins and sounds (it was 26), an MPE mark and filter, a bare installer package as the
   download where there is one, and a plain note where an item needs one.
5. **The wiki on GitHub too.** The same pages as the site's and the app's Wiki, built from the same sources and pushed to
   the repository's GitHub wiki by a workflow. That workflow has not run yet, and it needs a one-time setup first (its
   header says what to click).
6. **One name.** The product is HypnoMix and its own DAW is HypnoMix Studio; the old name of what that DAW is built on appears
   only where the licence needs it.

## New in 0.3.0

The ten changes you will notice most, in plain words:

1. **The Store (Mac only).** `store` finds and installs free plug-ins and sounds from their publishers' own pages, checks
   each download against a fingerprint before it installs, and keeps a list so it can remove them again.
2. **Live sets into HypnoMix Studio, and mastering in it.** `als2ardour` turns a Live set into a new session folder (the
   set is only read); `chain master --ardour` builds the mastering chain in the open HypnoMix Studio session.
3. **One download today.** The Assistant installer is the only download. The full app, with its own DAW, is built but not
   out: the download page does not offer it, and nothing in the Assistant adds it.
4. **Broken audio is refused in one sentence.** A file that is empty, has NaN in it, has more than five channels, or
   cannot be written to the `--out` folder stops the run with exit code 2 and one line saying what to fix.
5. **Earlier outputs are never replaced.** A second run makes a numbered new file ("(master 2)", "(2)") beside the first.
6. **`fix` says plainly what it did not do.** What FAILED, what is by hand, "nothing was written", and `--dry-run` with
   `--approve`; no phantom version in the history.
7. **Vocal-level findings are by hand.** Approving one in the review writes nothing by itself: `vocallevel --apply`
   writes the volume automation into a new set.
8. **Disk care.** The app's own temporary folders clear themselves after a day, and a button clears old leftovers.
9. **Rubber Band is checked.** `tune` stops with one line when it is missing, `doctor` lists it, and the Live rows are
   optional when you have no Live.
10. **Long scans come in pages.** `fix --list --undecided --top 15` and `fix --show ID`; in the app, a review of more than 150
    cards builds them 100 at a time (the standalone review page does the same above 300 findings).

## Checked where

- The Live devices and the Live fix paths were tested in Live 12.
- REAPER support was tested in REAPER 7.86.
- Everything newest passes unit tests and HypnoMix's own structure checks on synthetic data. On 2026-11-26 the REAPER
  files the newest code writes (the demo project, a project written by `fix`, masking cuts as ReaEQ bands, the
  hand-off marker and the A/B project) were opened in REAPER 7.86 and read back through its API: no offline media, and
  everything matched what HypnoMix wrote. On 2026-11-26 the newest REAPER parts were also tried in REAPER 7.86 on a two-track test project, never a real song and not judged by ear:
  the HypnoMix Probe, HypnoMix Main, Review and Align windows opened and their guides were captured by screenshot (not
  clicked through by hand); `reaper snapshot`, `diff` and `restore` were exact; `reaper loop --ab` measured its change
  and `--revert` put the mix back; `reaper diagnose` put every solo back (no project with folders was tried); a ReaComp
  written by `fix` and the `vocallevel --apply` envelopes read back as written. Not checked: clicking the windows by
  hand, Windows, ReaGate and ReaLimit settings, and `diagnose` with folders. The new Live sets (hand-off locators, the EQ Eight band, colour chains) have
  not been opened in Live, the `.ardour` snapshots have not been opened in a released DAW, the new tools have not been run on
  real songs, and nothing new has been judged by ear.
- DAW mode (the HypnoMix engine, the DAW view and the Assistant on it), the Store, `als2ardour`, `import` and
  `chain --ardour` were checked by unit tests on synthetic data and stand-in servers, and DAW mode against the real engine on its silent
  test backend only. No session written by `als2ardour` or `import` has been opened in a released DAW (for `import`: checked: .als through als2ardour's own tests; .logicx decoded from real packages saved by version 10.7, with fader values, mutes, plug-in names and region places compared with the window image each package stores of itself (the program that made them was not run), and one of them imported, opened in the HypnoMix engine on its silent test backend and its tracks, faders and regions read back; .dawproject, .rpp, .ptx and .aaf only with files made by the tests or stand-in readers.), and nothing was tried
  through a real sound card, in recording, or with real MPE controllers. The first engine (0.1.0) is published for Apple-silicon
  Macs only; adding it from Setup on an installed app, signing and notarising it, and Intel Macs have not been tried.
- Round 2 (take lanes and comping, groups and sidechains, the meter stream, the Session view's cue slots, the A/B session, and the `--engine` / `--cues` forms of `tidy`, `order`, `duck`, `loops` and `variations`) was tested against stand-in engines in the unit tests and against a development build of the engine on its silent test backend with a made-up session. Not verified: the meter stream inside the Mac app's own window (a same-origin WebSocket under the page's `connect-src 'self'`; if that window refuses it, the meters fall back to polling) and its reconnect after an engine restart, any of it on Windows or with real audio hardware, and anything by ear (comp crossfades, cue launches, the A/B level match, the duck and sidechain settings).

Items marked *(to verify)* below rest on research that has not been tested here yet.

## (a) Built

One line per area. Each command's own help (`hypnomix <command> -h`) and its wiki article say how it works.

- **The first pass:** `scan` (a Live set, a REAPER project, a HypnoMix Studio session, or a folder of recordings), `ab`,
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
- **Engineer and master:** `automix`, `balance`, `master`, `chain` (Live, REAPER, and with `--ardour` the HypnoMix Studio session), `rebalance`, `tonal`, `harsh`,
  `masking` (an approved cut is written as an EQ Eight band in Live or a ReaEQ band in REAPER, in a new file),
  `match`, `reference`, and `--plan` for `prep`, `automix` and `master`.
- **Release:** `translate`, `qc`, `release`, `versions`, `compare`, `album`.
- **Free plug-ins and sounds (Mac only):** `store` (`search`, `info`, `install`, `uninstall`, `updates`, `check`).
- **Live set into HypnoMix Studio, and mastering there:** `als2ardour` (a new session folder and an import report) and
  `chain master --ardour` (the chain built in the open HypnoMix Studio session).
- **DAW mode, for Apple-silicon Macs first:** `app --daw` runs the HypnoMix engine (the DAW's audio engine, a separate program) and
  drives its open session from the DAW view and the Assistant. It is an add-on added from Setup; the first engine (0.1.0) is
  for Apple-silicon Macs only, and there is none for Intel Macs or Windows yet.
- **Previews:** `ab` builds before and after pairs for clips, tuning, timing nudges, masking cuts and changes to six
  of Live's stock devices (labelled as a model of the device); `abset` puts every fix next to yours inside Live (or in a new REAPER project);
  `plugrender` and `plugins` bring your own VST3 and Audio Unit plug-ins in.
- **Inside Live:** `live`, `loop`, `diagnose`, `probe` and the Max for Live devices (HypnomixProbe, HypnomixMain,
  the review device, Hypnomix Align).
- **REAPER:** `project`, `scan` and `fix` on an `.rpp` (a new project), `reaper` (the bridge, HypnoMix Probe and
  HypnoMix Main, the A/B review panel, the Align panel, `snapshot`, `loop`, `diagnose`), `chain --reaper`.
- **HypnoMix Studio:** `project` and `scan` on a session (`.ardour`), and `fix` writes approved fades, gain, dips and
  fader, pan and mute moves into a new `.ardour` snapshot.
- **The app and teacher mode:** `app` (the first pass by clicking), the Assistant and the optional Listener, and the
  Teacher tab: three courses per DAW, including the complete course A to Z.
- **Your own profile in the scan:** `scan --mix` compares the mix with your own profile ranges (built by
  `profile build`); `--no-profile` skips it, and `prefs set taste.profile=off` turns it off for every scan.
- **Tested Live versions:** HypnoMix has been tested with Live 11 and Live 12. A tool that writes a new set refuses
  one saved by a newer major version of Live than 12 unless forced (the environment variable `HYPNOMIX_FORCE_LIVE_VERSION=1`, or
  `--force-live-version` on a command that has it); reading and scanning still work, with one warning line.
- **Safety and care:** a security pass (the Assistant runs only read-only commands without a click, wiki content is
  cleaned, updates are checked harder) and automatic disk care.

### Why the review is the product

The loop (scan, hear, approve, apply, measure again) is the same for every DAW: the same findings, the same
decisions, the same "new files only". What HypnoMix cannot change in a DAW becomes a to-do in that DAW's own words
(`handoff`). That is why a folder of exported tracks from any DAW already gets most of the value.

## (b) Next, in order

1. **Open everything the newest release added, in real DAWs and on real songs.** The REAPER files were opened in
   REAPER 7.86 and read back on 2026-11-26 (see "Checked where"); what is left is to judge them by ear and run them on
   real songs. The items still to open: the new EQ Eight band for masking cuts in Live; the handoff locators in a Live
   set; the colour chains in a Live set; `balance` on a real folder of stems; the `.ardour` snapshots, opened in
   a DAW that reads them (the snapshot opens without a warning, the audio is found, fades and gain are as written, the pan goes the
   way round expected with azimuth 0 on the left, the trim is unchanged), plus a session saved by a DAW that reads them, with
   HypnoMix's renders compared with its own export; `release`, `compare`, `versions`, `album`, `preflight` and
   `demo` on real music; the sets written by `tempomap`, `loops`, `variations`, `motion` and `borrow`, opened in
   Live and judged by ear; a session made by `import` from each file type, opened in a released DAW; the REAPER windows clicked through by
   hand, and on Windows; an MPE clip played on a controller after the glide fix; and take lanes, cue slots, the A/B
   session and the meters on real audio hardware, judged by ear.
2. **Colour beyond Live sets:** REAPER projects and HypnoMix Studio sessions, and an instrument doubling a line (from `midi`: it needs
   an instrument device chain and the MIDI clip written, both new).
3. **`ab` for REAPER projects** (it plays Live sets today), and models for Saturator, Reverb and Delay.
4. **Space checks in `devices`:** delay times against the tempo, reverb low cuts.
5. **A `comp` writer from ranked takes:** `takes` ranks them and lists the best take per section today; nothing
   writes the comp into a project yet.
6. **HypnoMix Studio, hands-on:** DAW mode needs the engine add-on, whose first version (0.1.0) is for Apple-silicon Macs
   only. With it, the app drives the open HypnoMix Studio session (regions, mixer, plug-ins, the review loop) and
   `chain master --ardour` builds the mastering chain there; next is an engine for Intel Macs and Windows, opening it on more real songs, and the DAW's own
   plug-ins (EQ, compressor, expander, delay, reverb) in the chain beyond the test sessions.
7. **Windows parity:** file pickers, and loopback capture without a macOS-only device for the loops that
   verify a chain.
8. **Signed installers:** signed with a publisher key, with the app checking that signature before it updates.
9. **A private access token for shared computers:** so the app on a shared machine is not open to everyone using it.

## (c) Later

- **A DAW with a session-info text export** (a widely used commercial one). Read: that export (tracks, clips, markers), parsed into the project model: no
  app control, works on every edition. An open-source reader for session files exists and can be an optional extra
  *(to verify: what it covers)*. Then drive: the official scripting SDK (a local service, in every edition since late
  2022 *(to verify)*): read the track list, add markers at each finding, import repaired audio as new tracks, bounce
  for a re-scan, and "save session as" before any write. Read-only by default; every write approved. It does not
  appear to control plug-ins or write automation *(to verify)*, so tone and dynamics moves stay as rendered audio or
  to-dos. The SDK's interface file has its own licence: the person downloads it rather than HypnoMix shipping it.
- **A DAW with an undocumented binary project bundle** (a commercial one for Mac). The project is a closed bundle. Reading track names, plug-in lists and tempo is
  possible but fragile: read-only, fail-soft, and it needs upkeep with each release of that DAW. Writing it is not safe and
  not planned. It has no scripting API for the mixer; the reliable route for live moves is to act as a control
  surface (faders, pans, mutes over a virtual MIDI port), with interface scripting only for bounce and export. Where
  its built-in assistants help, the review says "run this, bounce, and I'll measure the result".
- **A local, open-weights listening model**, so notes by ear need no cloud model. Advice only, labelled as such,
  never a source of numbers, run on the person's own computer.

### Which DAW can do what

| DAW | read the project | write your approved fixes | drive the open app |
|---|---|---|---|
| Ableton Live | yes (`.als`) | yes: a new `.als` | yes (AbletonOSC, the Max for Live devices) |
| REAPER | yes (`.rpp`) | yes: a new `.rpp` | yes: through the bridge |
| HypnoMix Studio | yes (`.ardour`) | yes: a new `.ardour` snapshot (not yet opened in a released DAW) | yes, in DAW mode: the open HypnoMix Studio session (an add-on; Apple-silicon Macs only so far) |
| A commercial DAW with a session-info text export | audio folders only today | audio folders only today | later |
| A commercial DAW with a closed binary project | audio folders only today (there is no reader for it) | audio folders only today | later (a control surface) |

For any DAW, `hypnomix scan FOLDER` on exported tracks works today: review, `fix` writes repaired copies, and
`handoff` turns what must happen in the DAW into a checklist in that DAW's words (with markers: a MIDI file and a
CSV when there is no project to write into).

## (d) Not planned

- Changing a project file in place, in any DAW.
- One-click "finish my song". Every assistant in this field that people trust keeps its moves visible,
  editable and reversible; the ones people abandon act as a black box.
- Anything that sends audio off the person's computer without asking each time.
- Naming or depending on paid plug-ins.
