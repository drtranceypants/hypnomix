# Roadmap

What is built, what comes next in order, what comes later, and what is not planned. The aim stays the same: help
an independent artist get from recordings to a release quickly, with free tools, and with the person deciding
every change.

**What comes next, in one sentence:** open everything the newest release added in real DAWs and on real songs,
before building anything else on top of it.

## New in 0.3.1

The six changes you will notice most, in plain words:

1. **One app, one installer, and HypnoMix DAW as an add-on.** There is one download for everyone. HypnoMix DAW (its engine is a
   separate GPL program) is built but not available yet: when its archive is published it is added from Setup, on a
   click, and checked against a fingerprint before it is used. `hypnomix engine` shows or removes it.
2. **Reporting a problem.** `report` and the app's Report button write a bug report, or the record of a crash, on your
   computer and show it to you first, with paths, names and keys hidden as far as HypnoMix can tell. Nothing is ever sent:
   you copy it, save it or paste it into the project's issue page yourself.
3. **A guided tour in the DAW page.** Short, optional spotlights on one real control at a time (first look, edit a
   region, mix, scan and review, ask the Assistant, save and export); they never change your song.
4. **A bigger Store.** 69 free plug-ins and sounds (it was 26), an MPE mark and filter, a bare installer package as the
   download where there is one, and a plain note where an item needs one.
   MPE checks in the scan of a HypnoMix DAW session (the wiki article "MPE clips"), with one fix: bend, pressure and
   slide stored so that they hold instead of gliding, written into a new snapshot. Read from the files only; nothing
   has been played on a controller yet.
5. **The wiki on GitHub too.** The same pages as the site's and the app's Wiki, built from the same sources and pushed to
   the repository's GitHub wiki by a workflow. That workflow has not run yet, and it needs a one-time setup first (its
   header says what to click).
6. **One name.** The product is HypnoMix and its own DAW is HypnoMix DAW; the old name of what that DAW is built on appears
   only where the licence needs it.

## New in 0.3.0

The ten changes you will notice most, in plain words:

1. **The Store (Mac only).** `store` finds and installs free plug-ins and sounds from their publishers' own pages, checks
   each download against a fingerprint before it installs, and keeps a list so it can remove them again.
2. **Live sets into HypnoMix DAW, and mastering in it.** `als2ardour` turns a Live set into a new session folder (the
   set is only read); `chain master --ardour` builds the mastering chain in the open HypnoMix DAW session.
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
  through a real sound card, in recording, or by adding HypnoMix DAW from Setup (no archive is published yet).

Items marked *(to verify)* below rest on research that has not been tested here yet.

## (a) Built

One line per area. Each command's own help (`hypnomix <command> -h`) and its wiki article say how it works.

- **The first pass:** `scan` (a Live set, a REAPER project, a HypnoMix DAW session, or a folder of recordings), `ab`,
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
- **Engineer and master:** `automix`, `balance`, `master`, `chain` (Live, REAPER, and with `--ardour` the HypnoMix DAW session), `rebalance`, `tonal`, `harsh`,
  `masking` (an approved cut is written as an EQ Eight band in Live or a ReaEQ band in REAPER, in a new file),
  `match`, `reference`, and `--plan` for `prep`, `automix` and `master`.
- **Release:** `translate`, `qc`, `release`, `versions`, `compare`, `album`.
- **Free plug-ins and sounds (Mac only):** `store` (`search`, `info`, `install`, `uninstall`, `updates`, `check`).
- **Live set into HypnoMix DAW, and mastering there:** `als2ardour` (a new session folder and an import report) and
  `chain master --ardour` (the chain built in the open HypnoMix DAW session).
- **DAW mode, built but not available yet:** `app --daw` runs the HypnoMix engine (the DAW's audio engine, a separate program) and
  drives its open session from the DAW view and the Assistant. It is an add-on added from Setup, and no archive is published yet.
- **Previews:** `ab` builds before and after pairs for clips, tuning, timing nudges, masking cuts and changes to six
  of Live's stock devices (labelled as a model of the device); `abset` puts every fix next to yours inside Live (or in a new REAPER project);
  `plugrender` and `plugins` bring your own VST3 and Audio Unit plug-ins in.
- **Inside Live:** `live`, `loop`, `diagnose`, `probe` and the Max for Live devices (HypnomixProbe, HypnomixMain,
  the review device, Hypnomix Align).
- **REAPER:** `project`, `scan` and `fix` on an `.rpp` (a new project), `reaper` (the bridge, HypnoMix Probe and
  HypnoMix Main, the A/B review panel, the Align panel, `snapshot`, `loop`, `diagnose`), `chain --reaper`.
- **HypnoMix DAW:** `project` and `scan` on a session (`.ardour`), and `fix` writes approved fades, gain, dips and
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
   `demo` on real music; and the sets written by `tempomap`, `loops`, `variations`, `motion` and `borrow`, opened in
   Live and judged by ear.
2. **Colour beyond Live sets:** REAPER projects and HypnoMix DAW sessions, and an instrument doubling a line (from `midi`: it needs
   an instrument device chain and the MIDI clip written, both new).
3. **`ab` for REAPER projects** (it plays Live sets today), and models for Saturator, Reverb and Delay.
4. **Space checks in `devices`:** delay times against the tempo, reverb low cuts.
5. **A `comp` writer from ranked takes:** `takes` ranks them and lists the best take per section today; nothing
   writes the comp into a project yet.
6. **HypnoMix DAW, hands-on:** DAW mode is built but not available yet (it needs the engine add-on, which is not
   published). With it, the app drives the open HypnoMix DAW session (regions, mixer, plug-ins, the review loop) and
   `chain master --ardour` builds the mastering chain there; next is releasing the engine, opening it on more real songs, and the DAW's own
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
| HypnoMix DAW | yes (`.ardour`) | yes: a new `.ardour` snapshot (not yet opened in a released DAW) | yes, in DAW mode: the open HypnoMix DAW session (built; an add-on, not available yet) |
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
