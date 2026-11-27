---
title: HypnoMix in REAPER
subtitle: Scan a REAPER project, approve the fixes, align a vocal stack, and build a mastering chain from REAPER's own plug-ins
wiki_id: reaper
---

# HypnoMix in REAPER

HypnoMix works with REAPER projects the same way it works with Live sets: it **reads** your project, lists
what it finds, and writes what you approve into a **new** project next to the original. REAPER can stay open
the whole time. Nothing is installed into REAPER, and none of its settings are changed.

How HypnoMix reads, renders and writes a project was checked against REAPER 7.86 itself: HypnoMix built test
projects inside REAPER, had REAPER render them, and compared the result sample by sample with its own. The windows
(section 7) were only opened and captured by screenshot, not clicked through by hand, and nothing was tried on Windows. The newest files were checked the same way on
2026-11-26: the demo project (section 0), a project written by `fix` (an item fade and a volume-envelope dip), the
frequency-fight cut written as a ReaEQ band (section 4), the hand-off project's marker (section 12) and the A/B project
(section 8) were opened in REAPER 7.86 and read back through its API. All opened with no offline media and matched what
HypnoMix wrote; the ReaEQ band's frequency, gain and bandwidth read back exactly as written, and REAPER's own renders with
the effect on and bypassed show the cut. None of this was judged by ear and none has been run on a real song, so listen
before you trust it. The list under "Not yet checked" repeats this and says what else was run (section 13, the
windows, the ReaComp and vocal-level files).

<!--toc-->

## What you need

- REAPER (the free evaluation works for everything here).
- HypnoMix installed (`hypnomix doctor` checks it).
- Your project saved as an `.rpp` with its audio files where REAPER put them. HypnoMix finds files the way
  REAPER does: next to the project, in its recording folder, or anywhere below the project folder.

Only REAPER's own plug-ins (ReaEQ, ReaComp, ReaLimit, the JS effects) are used when HypnoMix builds anything.
Your own plug-ins are read and listed, never needed.

## 0. Try it on a demo project

```bash
hypnomix demo --kind reaper       # → hypnomix-out/demo/Hypnomix Demo Song/Hypnomix Demo Song.rpp, the stems, Instrumental.wav, DEMO.md
hypnomix scan "hypnomix-out/demo/Hypnomix Demo Song/Hypnomix Demo Song.rpp" --key "A minor" \
  --backing "hypnomix-out/demo/Hypnomix Demo Song/Instrumental.wav"
```

A 40-second synthetic song (nothing downloaded, nothing recorded) with six problems put in on purpose: a click where
two take items meet, a level jump at a comp cut, hiss, clipped peaks, a harmony that drifts sharp and drums that fall
behind. `DEMO.md` lists each with its time. The comps are separate items on separate takes, so the scan sees all six.
Then run the loop of sections 3 and 4 on it: `ab` plays the de-hiss, and for a project the other fixes are applied into a
new `.rpp` and heard there (or use `abset`, section 8). The project was opened in REAPER 7.86 and read back (no offline media, matching what HypnoMix wrote), and REAPER does not need to be open to scan it.

## 1. Look inside a project

```bash
hypnomix project "Song.rpp"
```

Prints every track (folders indented), its fader, pan, mute and polarity, its plug-ins (switched-off ones marked),
and its automation. Add `--items` for every item: position, length, which take plays, its file, volume and fades.

```bash
hypnomix project "Song.rpp" --render
```

Renders every track you can hear to its own WAV from the start of the song, without opening REAPER: item and take
volume, fades and crossfades, loops, sections, playrate and stretch markers are included; faders, plug-ins and
automation are not (these are the raw parts, for checking and for stems).

## 2. Scan the song

```bash
hypnomix scan "Song.rpp" --mix "Song.wav"
```

The same first pass as for a Live set: every check runs and writes one list, `REVIEW.md`, most serious first.
Nothing is changed. For a REAPER project it checks:

| group | what it looks for |
|---|---|
| names | tracks still called "Track 3" or "Audio 2": named by how they sound; the tracks put in working order (drums, bass, keys and guitars, vocals, other parts; low to high) |
| files | items whose audio file is missing |
| clips | clicks at item edges, level jumps where comp takes meet, short spikes (a pop, a bump), and item edges or fades that cut off the first sound of a word |
| timing | instrument hits out of time with the band: the bass checked against the drums first, melodic parts only gently; each player's own push or lay-back is kept |
| vocals | the pitch of every vocal track, doubles that drift from the lead, how the harmonies sit together, the vocal level line to line and upper parts under the melody (`vocallevel`, when the project has two or more vocal tracks) |
| effects | plug-ins that are switched off or offline, two limiters in a row; every sidechained ReaComp simulated hit by hit: how deep it ducks, whether it is back before the next hit, how even it is, whether its release bends the bass |
| devices | every ReaComp on a track's own audio (not a sidechain): how much it turns the part down while it plays, whether it barely works or squashes, a release that bends the bass, drum hits clamped by a very fast attack; a suggested threshold, ratio, attack and release for that kind of part. A ReaEQ with no high-pass band on a part (not bass or drums) that rumbles under 80 Hz: a low cut to set by hand. ReaGate and ReaLimit are listed but not judged, because HypnoMix does not read their saved settings yet. A ReaComp after another plug-in (a JS effect, say) is listed but not judged: the level reaching it is unknown. Plug-ins on folder tracks are not judged |
| recordings | every file the project plays: clipping, levels, hiss, DC offset, harsh "s" sounds, breaths (`hypnomix preflight "Song.rpp"` checks the files themselves first: mixed rates, duplicates, lossy sources, missing files) |
| noise | items turned up so far that their hiss comes up with them |
| intent | things that look deliberate (automation, hard pans, muted tracks, big item volumes, flipped polarity): listed as questions, never changed |
| mix | with `--mix`: loudness, true peak, release checks, how it translates |
| stems | with `--deep`: which parts fight over the same frequencies, and mic phase |
| structure | from the project file alone: whether it reads back exactly as saved (if not, apply no fixes: save it again in REAPER and re-scan), folders that never close, a send from a track that is not there, a fader at the top (+12 dB) or nearly silent with items on the track |

Give `--ref` (the mix or an instrumental) for tuning: without it the key and tuning are read from a rough mix of
the project's own tracks.

## 3. Decide, item by item

```bash
hypnomix review "<scan folder>" --serve        # a page: listen, then approve / skip / change
hypnomix fix "<scan folder>" --decide clips-3=approve,name-2=skip
hypnomix fix "<scan folder>" --decide name-4=approve --note "Acoustic Guitar"
```

A note changes how a fix is made. For a track name, the note is the name. For a level jump at a comp cut,
`amount=0.3` takes less of the jump away and `method=item` sets the item's volume instead of riding the track.

## 4. Apply what you approved

```bash
hypnomix fix "<scan folder>" --approved --out "Song (fixed).rpp"
```

Everything you approved goes into **one new project** next to the original:

| finding | what is written |
|---|---|
| click at an item edge | a 5 ms fade on that item (an existing fade is never made shorter) |
| level jump at a comp cut | short fades either side of the cut, and a volume ride that eases the jump in over 300 ms |
| spike | a quick dip in the track's volume over the burst (at most 3 dB on a low "p" or "b" thump) |
| a word's first sound cut off | the item edge opened up to just before the consonant, the neighbouring item trimmed to match; the audio stays exactly where it was |
| a fade ducking a word | that fade made 10 ms long |
| track name | the track renamed |
| track order | the tracks reordered; folders keep their tracks, and every send still comes from the same track |
| vocal stack | where the parts swap tracks, each item moved to the track for its pitch (lowest part on the lowest track), its volume changed by the fader difference so it plays at the same level; items on lane tracks, under automation, or that would overlap another item are listed for you instead |
| out-of-time hit | stretch markers on the item: one on the hit, moved part of the way to where the band (or the drums) plays it, one on the hit either side holding it, so only that short stretch is stretched; drag or delete the markers in REAPER to change or undo one |
| frequency fight (from `--deep`) | one bell band on the ReaEQ of the part that should give way: a free band of a ReaEQ already on the track, else a new ReaEQ at the end of its chain, five bands at most per ReaEQ. Gentle by default (2 dB for a fight that happens less than half the time, 3 dB for more); approve at a smaller amount to make it smaller. Nothing else on the track changes. Opened in REAPER 7.86 and read back: frequency, gain and bandwidth exactly as written; REAPER's own renders with the effect on and bypassed show the cut |
| sidechain | the ReaComp set to the suggested threshold, ratio, attack, release, knee and detector (clarity for a kick trigger: 2-4 dB, back before the next hit; vocal-duck for a vocal feeding a reverb or delay); only those settings change, the routing is left alone; a ReaComp with Wet at 0 or a parallel dry and wet mix is listed and not judged |
| ReaComp settings (devices) | the suggested threshold, ratio, attack and release written into that ReaComp; nothing else in it changes, and an approval at an amount (`approve@50`) moves each setting that share of the way. If the ReaComp was changed after the scan it is skipped and said so. A ReaComp written this way was opened in REAPER 7.86 and read back exactly (2026-11-26, a two-track test project); not judged by ear, not run on a real song |
| vocal tuning | each take file pitch-corrected into a new file in `Tuned/`, added to its items as a **new take** and made active |

Your comp is never replaced by a rendered copy. A tuned vocal is a second take on each of your own items, so
switching takes in REAPER gives you the original back. Volume rides go on the track's volume envelope and
multiply with what is already there: a ride you drew yourself is kept, and the fader is left alone.

Before anything changes, every approved finding is found again in the project by its item; if the project
changed since the scan, it is skipped and said so. Afterwards the new file is read back and checked: the same
tracks and folders, the same items in the same places, sends from the same tracks. A file that fails is renamed
"(BROKEN, do not open)" and the original stays yours. Then the clip checks run again on the new project, and the
log says which approved problems are gone and which are only smaller.

The vocal level line to line is written by its own command, not by `fix`:

```bash
hypnomix vocallevel "Song.rpp" --apply "Song (levels).rpp"
```

It measures each vocal line (from the project, or `--heard` solo renders) and writes gentle S-curve moves on the
tracks' volume envelopes in a new project: upper harmonies at most 4 dB down where they sit over the melody, lines
evened out at most 3 dB, on the vocal folder only when it holds nothing but vocals. Your own envelope points are
kept. The new project gets the same structure check and is measured again. Opened in REAPER 7.86 (2026-11-26, a
two-track test project: 106 points, all within +-3 dB; written before the 2026-11-27 change that leaves untouched points as they are and refuses hot envelopes, which is unit-tested only); not judged by ear, not run on a real song. See the vocal guide (Level line to line) for the details.

Open the new project in REAPER (File → Open, or drag it in). To hear each fix against what you have *before*
approving it, see section 8. What fix could not do (a fix that needs your hands or ears) is listed under "Not applied"
at the end of the run; section 12 turns that list into a checklist with markers.

## 5. Master in REAPER, with REAPER's own plug-ins

```bash
hypnomix reaper start
hypnomix chain master "Song mix.wav" --reaper --verify
```

`reaper start` runs a small HypnoMix script inside the REAPER that is open, so HypnoMix can add plug-ins and set
them. It installs nothing; it stops when REAPER quits, or with `hypnomix reaper stop`. **Every change it makes is
one undo step** named "hypnomix: ...", so Edit → Undo takes it back.

`chain master` analyses the bounce of your mix, works out a mastering chain the same way as for Live, and builds
it on REAPER's master from stock plug-ins only:

| step | REAPER plug-in | set to |
|---|---|---|
| clean the sub, tone | ReaEQ (a second one when more than five bands are needed) | each band's type, frequency, gain and width |
| glue | ReaComp | threshold, 2:1, attack, release, RMS detection, soft knee |
| mono low end | JS: Mid/Side Encoder → ReaEQ → ReaEQ → JS: Mid/Side Decoder | everything below the frequency in mono, everything above untouched |
| warmth (if asked for) | JS: Saturation | a gentle amount |
| width (if asked for) | JS: Stereo Field Manipulator | width % |
| loudness | ReaLimit | ceiling, and the threshold that gives the gain |

Values are set by what the plug-in shows, so a 30 ms attack reads 30.0 in REAPER. Master plug-ins that are already
there are never removed: `--existing bypass` switches them off, `--existing keep` builds after them.

With `--verify`, REAPER renders the loudest bars of the song, HypnoMix measures them, and ReaLimit is trimmed
until they match the target. Then the **whole song** is rendered once more for true peak: ReaLimit limits the
samples, and the signal between samples can still go over (on one finished song it reached -0.43 dBTP with a
-1 dB ceiling). If it does, the ceiling is pulled down until the whole song is under. No routing through another
app is needed: REAPER writes the file itself.

`chain strips recipe.json --reaper` builds a channel strip on every track from an automix recipe (ReaEQ, ReaComp,
fader and pan). Sends to a reverb are listed for you to add.

## 6. Talk to the REAPER that is open

```bash
hypnomix reaper status        # REAPER version, open project, tempo, tracks
hypnomix reaper tracks        # each track with its plug-ins, fader and pan
hypnomix reaper fx Rea        # installed plug-ins whose name has "Rea" in it
hypnomix reaper params master 0
```

`params` lists every parameter of one plug-in as the plug-in shows it (the track by name, number or `master`; the
plug-in by name or number).

## 7. Measure while you play: HypnoMix Probe and HypnoMix Main

The same meters as the Live devices, as REAPER effects (JSFX), so the app hears every track **after all its
plug-ins**, while REAPER plays: nothing is rendered or exported.

```bash
hypnomix reaper probes install                 # once, and again after each HypnoMix update: copies them into REAPER's Effects/hypnomix (then press F5 in REAPER's Add FX window so it shows the current names)
hypnomix reaper probes insert "Song.rpp"       # → "Song (probes).rpp": a probe last on every track, Main on the master
hypnomix reaper start                          # the bridge passes what they measure to the app
hypnomix app                                   # its Live tab: every track's loudness, peak, tone and width
```

Or add them by hand: Add FX → JS → **HypnoMix Probe** (last on a track) and **HypnoMix Main** (on the master).

Each one draws its own window (REAPER's plain slider rows are hidden): a header with the amber lens, a pill that says
whether the bridge runs and the app listens (**bridge on · app on**), and a **?** in the top-right corner.

- **HypnoMix Probe** shows what it hears: loudness (momentary and short-term LUFS), left and right peaks, the 8 bands
  it measures (sub to air) and the width, with the low end marked mono (green) or wide. Its chips are its settings:
  *What it is* (lead vocal, harmony, kick, bass, guitar … or *auto*: the app works it out by sound while you play; a scan of the .rpp goes by the track name and the sound), *Priority*
  (focus: others give way to it; background: it gives way) and *Protect* (the app's review of what it heard lists the
  track as protected; see below for what does not read it yet). Click a chip: Protect switches on and off, the others open a menu.
- **HypnoMix Main** shows the mix against the card (short-term loudness with your target marked, peaks with your
  ceiling marked) and **the song card**: genre, key, scale and limiter character as chips; target, ceiling and amount
  with **-** and **+** (or the mouse wheel). Record and review (section 9) and the mastering chain (section 10) use
  the target, ceiling, limiter character and amount. The genre, key and scale are saved with the project, but
  nothing uses them for a REAPER project yet: for tuning, give the key on the Songs tab or with `--key`. Below: **Record and review** (section 9) and the mastering chain (section 10).

**The built-in guide.** The first time you open a HypnoMix Probe, HypnoMix Main, the Review panel or the Align panel
on a computer, a step-by-step guide walks through every control: the part it talks about is lit and the rest dimmed,
with **Next**, **Back**, **Done** and **Skip guide**. The **?** starts it again any time. (With the bridge running,
"seen" is remembered in REAPER's settings, so it is not shown again on every track.)

The settings are still REAPER parameters: saved in the project, automatable, and listed under the window's **Param**
button.

The menus are saved in the project (`hypnomix reaper probes cards "Song.rpp"` shows what they say). The app uses
them while you play: its review of what it heard takes each track's What it is and Priority, lists the protected
tracks, and checks Main's target and ceiling. `scan` and `fix` on a REAPER project do not read them yet: to keep
`fix` off a track, set it in Preferences (`protect.tracks`), and give the key on the Songs tab or with `--key`. With the app open, press **Record** in its Live tab, play the song or a section in REAPER, press **Stop**: the
review is made from what was heard (frequency fights while parts play together, the lead vocal against the band
section by section, a low end that is not mono, Main's loudness against the card). From a terminal:
`hypnomix probe listen` while you play, then `hypnomix probe report`. To review the whole master before export
in one go, see section 9.

Measured against the same audio offline: loudness within 0.04 LU of a BS.1770 meter, peak, stereo correlation (also
below 120 Hz) and mid/side exactly. When the bridge starts it gives each probe a slot number (a hidden setting), so
REAPER may ask to save the project once.

## 8. Hear each fix before you approve it: A/B inside REAPER

```bash
hypnomix abset scan/Song                 # → "Song (A-B).rpp" next to your project
hypnomix app                             # open the song's review
hypnomix reaper review                   # the HypnoMix Review panel in REAPER
```

`abset` builds **one new project** in which every proposed fix sits next to what you have, switched off, so the
project plays exactly like yours until you switch:

- **A plug-in change** (a retuned ReaComp): the changed plug-in is copied in right after yours and bypassed.
- **Anything else** (fades, rides, edges, timing markers, a tuned take, moved items): the whole track is copied
  with the fix, named "*track* · B *id*", muted, right after yours, in the same folder and sending where yours sends.

Open the A/B project in REAPER (your original is not touched), then `hypnomix reaper review`. The HypnoMix Review panel
follows the review in the app:

| button | what it does |
|---|---|
| Prev / Next / Next open | step through the findings; REAPER selects the track and puts the time selection on the spot |
| A · now / B · fix | switch the finding's plug-ins or tracks, instantly, with every plug-in playing |
| Blind | X and Y in random order; **I like X / I like Y** records your choice, then tells you which it was |
| Match on / off | with HypnoMix Main on the master and the bridge running, B is turned up or down to A's loudness |
| Approve / Skip | your decision, recorded in the review |
| Amount N% | on a fix that can scale: each click steps 25, 50, 75, 100% of the proposed move (timing and tuning start at the amount saved in Preferences) |

Moving to another finding puts the last one back to A, and stopping `hypnomix reaper review` (or closing the
panel) leaves the whole project on A. While the panel is in front, space plays and stops, and Esc closes the
guide when it is showing, otherwise the panel. Other keys do nothing there: click REAPER's own window first for its
shortcuts.
Approving still happens in the review, and `fix --approved` writes the real new project from your **original**,
not from the A/B project. Track names and order cannot be heard, so they are not in the A/B project. A folder that
has tracks in it is not copied (its fix is listed: apply it alone to hear it). If the panel is not the window in
front, the first click only brings it forward.

## 9. Review before export

With the probes in the project (section 7), the bridge running and the HypnoMix app open, press **Record and review
before export** on HypnoMix Main (open its window on the master), or run `hypnomix reaper record`.

REAPER plays from the edit cursor (or carries on, if it is already playing) while every probe listens, and Main's
window shows how long it has been recording. Press **Stop and review** (or run the command again, or just stop
REAPER) and the app:

- has REAPER render the master for **exactly the stretch that played** (32-bit float, into the app's `bounces`
  folder; your render settings are put back afterwards). It is a render rather than a live recording, so nothing
  can drop out, and it sounds exactly like what you heard;
- reviews it the same way as Live's Record and review: the live findings from the probes, loudness and true peak
  against Main's song card, `qc`, `translate`, and `master --plan` with the card's target, ceiling, limiter
  character and amount. The review opens in the app.

If you loop a section, the review covers from where you started to the furthest point played. Under a second of
playing is not reviewed (Main says so). If Main's window says the app did not answer, open the app (`hypnomix app`)
with the bridge running and press again; if it says the review could not run, the app shows why. REAPER's own
Render is still how you make the final file.

## 10. A mastering chain on HypnoMix Main

HypnoMix Main's window (open it on the master) has three more buttons, the same as HypnomixMain in Live. They
need the bridge running (`hypnomix reaper start`), not the app.

| button | what it does |
|---|---|
| **Build chain** | puts REAPER's own plug-ins just before HypnoMix Main, each renamed "HypnoMix · ..." (chains built before 2026-11-26 say "Hypnomix · ..." and are still recognised): Tone (ReaEQ: high-pass 25 Hz, low shelf 90 Hz, bells at 300 Hz and 3 kHz, high shelf 10 kHz, all at 0 dB), Glue (ReaComp 2:1, attack 30 ms, threshold -12 dB, RMS, soft knee), Tame (ReaXcomp, bypassed until a band jumps out), Warmth (JS: Saturation, bypassed), Width (bass mono below 120 Hz: M/S encoder, side high-pass, mid all-pass, decoder) and Limiter (ReaLimit, ceiling from the card, gain 0 dB). If you have saved templates, a menu asks which to build. Building again asks before it replaces the HypnoMix plug-ins. |
| **Match target** | plays (or keeps playing) and listens to Main after the chain, then turns ReaLimit's threshold (its gain) until the master lands on the card's Target LUFS, the master fader included, in up to four rounds of about 8 seconds. Play the loudest part. If REAPER was stopped, it stops it again when it is done. It works with any chain before Main that has a ReaLimit. |
| **Save chain** | asks for a name and keeps **everything before HypnoMix Main** as `FXChains/hypnomix/NAME.RfxChain` in REAPER's resource folder: your edited chain or a chain of your own, with every setting, third-party plug-ins included. REAPER's own Add FX chain opens these files too. |

While the plug-ins are the ones HypnoMix built (named "HypnoMix · ..."), they follow the song card: the Ceiling
sets ReaLimit's ceiling (its gain is kept) and the Limiter character sets ReaLimit's release (clean 120 ms, punch
60 ms, loud 20 ms) and the Glue's attack (loud: 10 ms). Plug-ins of your own are never changed, except ReaLimit's
gain by Match target. Every change is one undo step.

From a terminal: `hypnomix reaper chain build [NAME]`, `chain match`, `chain save NAME`, `chain state`.

ReaLimit limits sample peaks, so the true peak can land a little over the ceiling: Record and review (section 9)
measures true peak, or leave a little more room in the ceiling.

## 11. Align a vocal stack: the HypnoMix Align panel

The REAPER side of the Live **HypnoMix Align** device: doubles and harmonies that land together, with the same
engine, presets and options (see the vocal alignment guide). Your project is never written: the result is a
**new project**, `Song (aligned).rpp`, next to yours.

```bash
hypnomix app                     # leave it running
hypnomix reaper align            # the HypnoMix Align panel in REAPER
```

Save the project first (Align reads the saved `.rpp`), then in the panel:

| button | what it does |
|---|---|
| Guide ← | the selected track becomes the guide (the one the others are measured against) |
| Line up to | asked, never assumed: **The average** nudges every part toward the group's average timing (the guide too); **The guide** makes the parts follow the guide, which is never moved. With two or more parts, Align asks you to choose one first; an answer saved in the app's Preferences starts chosen |
| + Part / Clear | the selected tracks become parts (repeat); Clear empties the list |
| Range: selection / Song | only the time selection, or everywhere |
| Protect | the time selection is never moved (repeat for more) |
| Sync here | the edit cursor must line up exactly; Clear marks empties both lists |
| Tight, Pitch, Vibrato, Formant | drag left / right: how far timing moves; pitch matching (0 = off; the chord under every note is checked first, from the project's own instrument tracks); the guide's vibrato for doubles; formant in semitones, pitch unchanged |
| Preset | steps through the presets (gentle-stack, natural-double, tight-pop, loose-folk, rap-doubles) |
| Timing: markers / takes | how the timing is written (below) |
| Write project | off: Align only measures and makes previews; on: it also writes the new project |
| Align | runs it; the lanes show each part's loudness before (grey) and after (amber) |
| Open project | opens the aligned project in a new tab (yours stays open in its own) |

In the new project:

- **Timing** is **stretch markers on the active take of each part's own items**: the fewest that follow the plan
  within half a millisecond. Drag or delete any of them afterwards. Stretch markers already on an item are
  followed and replaced by the combined ones. Where two neighbouring words move opposite ways across a short gap,
  the change is eased over a little more time (stretch markers can't play audio backwards). An item that begins
  at its file's first sample but should start a little later in the file starts there and catches up. The report
  says by how much either was eased.
- **Pitch and formant** can't be stretch markers: each item of that part gets a **new take**, made active, playing
  a file rendered for that item (timing, then pitch, then formant). The original take stays on the item: switch
  takes to compare. The files go in a `hypnomix aligned` folder next to the project.
- **Timing: takes** puts the timing on new takes the same way, instead of stretch markers.

Only parts that measure closer to the group (or the guide) are written; the others are left exactly as they were.
Items that loop their source and MIDI items are left alone and listed. One tempo is assumed. Without the panel:

```bash
hypnomix alignset "Song.rpp" --guide "Lead Vox" --parts "Harmony 1" "Harmony 2" --to-average --bars 11-21 --bpm 64 --apply
```

Checked in REAPER 7.86 on a real stack (a lead and three harmonies over ten bars, one harmony a comp of three
items, one with stretch markers already on it): REAPER plays the new takes as the checked render (within 0.4%),
and places the stretch markers exactly where planned (median 0.00 ms in varispeed). With pitch kept (the default),
REAPER's stretch engine plays the words that moved about 4 ms later than planned (90% within 9 ms); **Timing:
takes** avoids that, at the cost of markers you can drag. If the panel is not the window in front, click its title
bar first: the first click only brings it forward.

## 12. The by-hand list, as markers in a new project

```bash
hypnomix handoff "hypnomix-out/scan/Song"
```

`fix` lists what it cannot do itself. `handoff` collects those approved findings, and any you skipped or changed with a
note of your own, and writes into `handoff/` in the scan folder: `HANDOFF.md`, a checklist in song order with the track,
the bar.beat and m:ss, what to do in REAPER's own words and what to listen for there, plus, when at least one item has a position, `markers.csv` and `markers.mid`.
For a REAPER scan with such an item it also writes a **new** project, `Song (handoff).rpp`, next to yours with one marker at each spot
(read back and compared with your project; yours is never touched). Jump from marker to marker in REAPER and tick the
list. An item with no position (a whole part) is listed at the end, without a marker. This new project was opened in REAPER 7.86 and the marker's position and name read back as written.

## 13. Hands on the mixer: snapshots, loop takes and a diagnosis

These three do in REAPER what `hypnomix live snapshot`, `hypnomix loop` and `hypnomix diagnose` do in Live. They are
new: they were run in REAPER 7.86 on a two-track test project (2026-11-26), not yet on a real song and not
judged by ear, so try them on a copy of a project first.

```bash
hypnomix reaper snapshot mix.json          # every fader, pan, mute, solo, send and plug-in setting, as JSON
hypnomix reaper snapshot restore mix.json  # put it back (one undo step: Edit > Undo takes it back)
hypnomix reaper snapshot diff old.json mix.json
```

A snapshot holds every track and the master: fader, pan, width, mute, solo, polarity, each send, and each plug-in
switched on or off with all its parameters. `restore` changes only what differs and lists anything it could not find
(a deleted track or plug-in, or a send that now goes elsewhere). `diff` says what changed in plain words, for
example `Kick: fader -6.0 dB → -4.5 dB (+1.5 dB)` or `Lead Vocal · ReaComp (Cockos): Thresh -12.0 → -6.0`.

```bash
hypnomix reaper loop --bars 33-40                        # render bars 33 to 40 of the master and measure them
hypnomix reaper loop --bars 33-40 --label vox-up --set "nudge 'Lead Vocal' +1"
hypnomix reaper loop --bars 33-40 --ab "fx 'Lead Vocal' ReaComp 0" --revert
hypnomix reaper loop --secs 60-80                        # by seconds instead
```

Each take is REAPER's own render of the master for that stretch (nothing to route, nothing played), measured and
compared with the previous take of the same stretch and with your profile. Takes go to
`hypnomix-out/loop/reaper-bars033-040/` with the measurements and a snapshot of the mixer at that moment, so
`snapshot restore` on a take's `.json` returns to it (and `snapshot diff` works on two takes' `.json` too). `--ab` renders as it is (A), makes the change, renders again (B),
shows B against A, and also writes B at A's loudness (`...-B-matched.wav`) so you hear the change and not the level.
`--revert` (only together with `--ab`) puts the mix back as it was before B, as one undo step. A change is one of `db TRACK -2.5`, `nudge TRACK +1`,
`pan TRACK -0.3`, `mute TRACK 0|1`, `fx TRACK FX 0|1`, `send TRACK N -12`, `param TRACK FX PARAM 0.4` (0 to 1) or
`paramd TRACK FX PARAM -3` (the value the plug-in shows). Bars count from the start of the project (bar 1 at 0 s).

```bash
hypnomix reaper diagnose                 # the loudest 8 bars, each top-level folder soloed in turn
hypnomix reaper diagnose --bars 16
```

`diagnose` renders the whole master, finds the loudest 8 bars, then solos each top-level folder (each track, when
the project has no folders) and renders that stretch. It says who owns the sub (20-60 Hz), the bass (60-250 Hz) and
the vocal band (1-4 kHz), and who is wide below 150 Hz. Every solo is put back as it was after each render. Each run keeps its renders and diagnose.json in a new numbered folder, hypnomix-out/diagnose/reaper-<song>/run-001, run-002 and so on, so an earlier run is never replaced; the command prints where. Muted
tracks are skipped; a reverb return soloed on its own is silent, and says so. Solo in place with folders and send
returns is unchecked in REAPER: so far `diagnose` was run on a two-track project with no folders.

## Measured in REAPER

| what | result |
|---|---|
| item positions, offsets, loops, takes, item and take volume | the same as REAPER, sample for sample |
| fade shapes and crossfades | within 0.0001 and 0.003 |
| playrate, pitch following | identical |
| stretch markers | timing within 0.0002 |
| Align: stretch markers written for a vocal stack | exactly on the plan in varispeed; with pitch kept, moved words about 4 ms late (REAPER's stretch engine) |
| Align: new takes for pitch / formant / timing | play the checked render within 0.4% |
| volume rides written by `fix` | REAPER plays them within 0.001 of what HypnoMix expects |
| ReaEQ against the planned EQ | within 0.04 dB |
| mono low end | under -68 dB of leak at 400 Hz, -94 dB at 2 kHz; the low end mono |

## Not yet checked

- `hypnomix reaper snapshot`, `loop` and `diagnose` (section 13) on a real song: so far they were run in REAPER 7.86
  (2026-11-26, a private instance on one Mac) on a two-track test project only: snapshot, diff and restore exact;
  `loop --ab "nudge Bass -3"` measured B at -1.4 LU and `--revert` put the mix back; `diagnose` put every solo back.
- `diagnose` on a project with folders or send returns (solo in place letting a folder's children and the send
  returns of a soloed track play): not tried.
- The HypnoMix Probe, HypnoMix Main, Review and Align windows (section 7): opened in REAPER 7.86 and their guides
  captured by screenshot (HypnoMix Main left an amount of 73 untouched; `ui.lua` and `mixer.lua` loaded with no
  error), but not clicked through by hand, and not tried on Windows (the windows, their menus, and the lessons'
  Windows steps such as the ASIO settings). After the second review's changes (2026-11-27) they were opened again:
  both plug-ins compiled and drew, the bridge and both panels loaded and drew, and snapshot, loop and diagnose ran
  again on the test project. The space and Esc keys in the panels were not tried.
- A ReaComp written by `fix` read back exactly in REAPER 7.86 (-17 dB, 4:1, 15 ms, 250 ms) and the `vocallevel
  --apply` envelopes opened again (106 points, all within +-3 dB; written before the 2026-11-27 change that leaves untouched points as they are and refuses hot envelopes, which is unit-tested only), both on the test project: not judged by ear, not
  run on a real song. ReaGate and ReaLimit settings are not read at all (listed, not judged).
- The Teacher's REAPER steps: the reverb (ReaVerbate reads back Wet 0 dB, Dry off) and saturation (JS: Saturation
  reads back Amount 20%) actions were run in REAPER 7.86; the lessons' other REAPER menu paths were not walked in
  REAPER.

- Opened in REAPER 7.86 and read back (2026-11-26), but not judged by ear: the ReaEQ band written for an approved
  frequency-fight cut (section 4), the `Song (handoff).rpp` marker (section 12), the demo project made by
  `hypnomix demo --kind reaper` (section 0), a project written by `fix` and the A/B project made by `abset` (section 8).
  None of these has been run on a real song.
- Sidechain checks on compressors other than ReaComp (listed, not measured).
- Where a stretch marker squeezes or stretches a segment, HypnoMix's own render reads it at a slightly different
  pitch than REAPER plays it (REAPER keeps the pitch). The timing is exact.
