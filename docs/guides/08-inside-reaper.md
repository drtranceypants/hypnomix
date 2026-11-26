---
title: hypnomix in REAPER
subtitle: Scan a REAPER project, approve the fixes, and build a mastering chain from REAPER's own plug-ins
file: 8 - hypnomix in REAPER
wiki_id: reaper
---

# hypnomix in REAPER

hypnomix works with REAPER projects the same way it works with Live sets: it **reads** your project, lists
what it finds, and writes what you approve into a **new** project next to the original. REAPER can stay open
the whole time. Nothing is installed into REAPER, and none of its settings are changed.

Everything here was checked against REAPER 7.86 itself: hypnomix built test projects inside REAPER, had REAPER
render them, and compared the result sample by sample with its own.

<!--toc-->

## What you need

- REAPER (the free evaluation works for everything here).
- hypnomix installed (`hypnomix doctor` checks it).
- Your project saved as an `.rpp` with its audio files where REAPER put them. hypnomix finds files the way
  REAPER does: next to the project, in its recording folder, or anywhere below the project folder.

Only REAPER's own plug-ins (ReaEQ, ReaComp, ReaLimit, the JS effects) are used when hypnomix builds anything.
Your own plug-ins are read and listed, never needed.

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
| vocals | the pitch of every vocal track, doubles that drift from the lead, how the harmonies sit together |
| effects | plug-ins that are switched off or offline, two limiters in a row; every sidechained ReaComp simulated hit by hit: how deep it ducks, whether it is back before the next hit, how even it is, whether its release bends the bass |
| recordings | every file the project plays: clipping, levels, hiss, DC offset, harsh "s" sounds, breaths |
| noise | items turned up so far that their hiss comes up with them |
| intent | things that look deliberate (automation, hard pans, muted tracks, big item volumes, flipped polarity): listed as questions, never changed |
| mix | with `--mix`: loudness, true peak, release checks, how it translates |
| stems | with `--deep`: which parts fight over the same frequencies, and mic phase |

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
| sidechain | the ReaComp set to the suggested threshold, ratio, attack, release, knee and detector (clarity for a kick trigger: 2-4 dB, back before the next hit; vocal-duck for a vocal feeding a reverb or delay); only those settings change, the routing is left alone |
| vocal tuning | each take file pitch-corrected into a new file in `Tuned/`, added to its items as a **new take** and made active |

Your comp is never replaced by a rendered copy. A tuned vocal is a second take on each of your own items, so
switching takes in REAPER gives you the original back. Volume rides go on the track's volume envelope and
multiply with what is already there: a ride you drew yourself is kept, and the fader is left alone.

Before anything changes, every approved finding is found again in the project by its item; if the project
changed since the scan, it is skipped and said so. Afterwards the new file is read back and checked: the same
tracks and folders, the same items in the same places, sends from the same tracks. A file that fails is renamed
"(BROKEN, do not open)" and the original stays yours. Then the clip checks run again on the new project, and the
log says which approved problems are gone and which are only smaller.

Open the new project in REAPER (File → Open, or drag it in). To hear each fix against what you have *before*
approving it, see section 8.

## 5. Master in REAPER, with REAPER's own plug-ins

```bash
hypnomix reaper start
hypnomix chain master "Song mix.wav" --reaper --verify
```

`reaper start` runs a small hypnomix script inside the REAPER that is open, so hypnomix can add plug-ins and set
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

With `--verify`, REAPER renders the loudest bars of the song, hypnomix measures them, and ReaLimit is trimmed
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

## 7. Measure while you play: Hypnomix Probe and Hypnomix Main

The same meters as the Live devices, as REAPER effects (JSFX), so the app hears every track **after all its
plug-ins**, while REAPER plays: nothing is rendered or exported.

```bash
hypnomix reaper probes install                 # once: copies them into REAPER's Effects/hypnomix
hypnomix reaper probes insert "Song.rpp"       # → "Song (probes).rpp": a probe last on every track, Main on the master
hypnomix reaper start                          # the bridge passes what they measure to the app
hypnomix app                                   # its Live tab: every track's loudness, peak, tone and width
```

Or add them by hand: Add FX → JS → **Hypnomix Probe** (last on a track) and **Hypnomix Main** (on the master).

- **On each probe:** *What it is* (lead vocal, harmony, kick, bass, guitar … or *auto*: the scan works it out by
  sound), *Priority* (focus: others give way to it; background: it gives way) and *Protect* (ask before any change).
- **On Hypnomix Main, the song card:** genre, key and scale (tuning and harmony use them instead of guessing),
  limiter character, loudness target, true-peak ceiling and amount (the loudness checks and mastering proposals use
  them).

The menus are saved in the project, so `scan` reads them (`hypnomix reaper probes cards "Song.rpp"` shows what it
reads). With the app open, press **Record** in its Live tab, play the song or a section in REAPER, press **Stop**: the
review is made from what was heard (frequency fights while parts play together, the lead vocal against the band
section by section, a low end that is not mono, Main's loudness against the card). From a terminal:
`hypnomix probe listen` while you play, then `hypnomix probe report`.

Measured against the same audio offline: loudness within 0.04 LU of a BS.1770 meter, peak, stereo correlation (also
below 120 Hz) and mid/side exactly. When the bridge starts it gives each probe a slot number (a hidden setting), so
REAPER may ask to save the project once.

## 8. Hear each fix before you approve it: A/B inside REAPER

```bash
hypnomix abset scan/Song                 # → "Song (A-B).rpp" next to your project
hypnomix app                             # open the song's review
hypnomix reaper review                   # the Hypnomix panel in REAPER
```

`abset` builds **one new project** in which every proposed fix sits next to what you have, switched off, so the
project plays exactly like yours until you switch:

- **A plug-in change** (a retuned ReaComp): the changed plug-in is copied in right after yours and bypassed.
- **Anything else** (fades, rides, edges, timing markers, a tuned take, moved items): the whole track is copied
  with the fix, named "*track* · B *id*", muted, right after yours, in the same folder and sending where yours sends.

Open the A/B project in REAPER (your original is not touched), then `hypnomix reaper review`. The Hypnomix panel
follows the review in the app:

| button | what it does |
|---|---|
| Prev / Next / Next open | step through the findings; REAPER selects the track and puts the time selection on the spot |
| A · now / B · fix | switch the finding's plug-ins or tracks, instantly, with every plug-in playing |
| Blind | X and Y in random order; **I like X / I like Y** records your choice, then tells you which it was |
| Match on / off | with Hypnomix Main on the master and the bridge running, B is turned up or down to A's loudness |
| Approve / Skip | your decision, recorded in the review |

Moving to another finding puts the last one back to A, and closing the panel leaves the whole project on A.
Approving still happens in the review, and `fix --approved` writes the real new project from your **original**,
not from the A/B project. Track names and order cannot be heard, so they are not in the A/B project. A folder that
has tracks in it is not copied (its fix is listed: apply it alone to hear it). If the panel is not the window in
front, the first click only brings it forward.

## Measured in REAPER

| what | result |
|---|---|
| item positions, offsets, loops, takes, item and take volume | the same as REAPER, sample for sample |
| fade shapes and crossfades | within 0.0001 and 0.003 |
| playrate, pitch following | identical |
| stretch markers | timing within 0.0002 |
| volume rides written by `fix` | REAPER plays them within 0.001 of what hypnomix expects |
| ReaEQ against the planned EQ | within 0.04 dB |
| mono low end | under -68 dB of leak at 400 Hz, -94 dB at 2 kHz; the low end mono |

## Not yet in REAPER

- Sidechain checks on compressors other than ReaComp (listed, not measured).
- The one-button *Record and review before export* (Live only). In REAPER: `probe listen` while you play, and a
  render of the master for `probe report --mix`.
- Where a stretch marker squeezes or stretches a segment, hypnomix's own render reads it at a slightly different
  pitch than REAPER plays it (REAPER keeps the pitch). The timing is exact.
