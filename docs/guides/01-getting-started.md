---
title: Getting Started
subtitle: What HypnoMix is, how it thinks, and your first hour with it
---

# Welcome

HypnoMix is a free mixing and mastering engineer for any kind of music, recorded or made in the box. It
does the slow, technical jobs (clicks, timing, tuning, lining up doubles, hiss, levels, sidechains, loudness)
and explains every move in plain words. The playing, the sounds, the arrangement and every taste call stay
yours.

<!--toc-->

## The promise: nothing changes without your yes

Every part of HypnoMix follows the same rules. They are why you can let it loose on a song you care about.

| rule | what it means for you |
|---|---|
| Looking is free | scans and reports never change a file |
| You decide each fix | every proposed change is a finding you approve, skip, or change |
| New files, always | approved changes go into a **new** set (or new audio files) next to the original; nothing is ever overwritten |
| Measured twice | after a fix the result is measured again, with a different method from the one that found the problem |
| Refuses rather than guesses | if a fix wouldn't make things measurably better, it is left out and the report says why |
| Your intent wins | automation, hard pans and effects you set are treated as choices; things you mark as deliberate are shown on every review |

> Tip: keep the original until you have opened the new set or project in your DAW and listened. HypnoMix checks
> the structure of everything it writes, but only your DAW can confirm that it opens.

## Four ways to use it

| you'd rather… | use | start with |
|---|---|---|
| click | **the app**: a page on your own computer with players, Approve / Skip buttons and forms for every tool | `hypnomix app` |
| stay in Live | **the Live devices**: the Hypnomix device (steps through findings) and Hypnomix Align (vocal alignment) | `hypnomix device`, `hypnomix aligndevice` |
| type | **the terminal**: every feature is a command | `hypnomix` |
| talk | **an AI agent** (Claude Code): it runs the same commands and asks you about each item | "Do a first pass on my song" |

They all drive the same commands and follow the same rules, so you can mix them: scan in the app, review
from inside Live, apply in the app.

What works where: Live sets (`.als`), REAPER projects (`.rpp`) and HypnoMix Studio sessions (`.ardour`) can be scanned, and
approved fixes are written into a new file of the same kind. Any other DAW works from exported tracks: see
"Other DAWs" in guide 2.

## Install

Most people should use the **HypnoMix installer** for Mac or Windows from hypnomix.bradfieldenterprises.org/download (one
installer for everyone; HypnoMix Studio, HypnoMix's own DAW, is an add-on you can add from Setup on an Apple-silicon
Mac, and it is not available for Intel Macs or Windows yet): no
terminal, and a guided setup on first open. The guide "Setting Up, and Choosing an AI" covers it. The steps below are the
**source install**, for the terminal and for working on HypnoMix itself. (The installed app also installs the
optional extras from its setup, and gives Claude Code the HypnoMix skills.)

You need macOS, Python 3.9 or newer, ffmpeg, Rubber Band 3+ (for tuning and alignment) and, for the Live
features, Ableton Live 11 or 12 (Max for Live for the devices). The file tools work without Live and with
files from any DAW.

```bash
brew install ffmpeg rubberband
git clone https://github.com/drtranceypants/hypnomix && cd hypnomix
uv venv && uv pip install -e .
source .venv/bin/activate # puts `hypnomix` on your path; do it in each new terminal (Windows: .venv\Scripts\activate)
hypnomix install          # Live users only: copies the Live remote script (AbletonOSC) into your User Library
hypnomix doctor           # checks everything is connected
```

Then restart Live and choose **Settings → Link, Tempo & MIDI → Control Surface: AbletonOSC**. You need this
only for the commands that talk to an open set (`live`, `loop`, `chain`); everything that works on saved sets
or audio files runs without it.

## Your first hour

### 0. Try it on a song that cannot be hurt (optional)

```bash
hypnomix demo                   # a 40-second synthetic song with six labelled problems: plain WAV stems, as exported from any DAW
hypnomix demo --kind reaper     # the same song, and a REAPER project that plays the stems
```

It writes `hypnomix-out/demo/Hypnomix Demo Song/`: drums, bass, keys, a sung-like lead and a harmony made from
scratch (nothing is downloaded, nothing is a recording; a second run makes "Hypnomix Demo Song 2" beside it), and `DEMO.md`, which lists each planted problem with its
time and the command that finds it: a click, a level jump, hiss, clipped peaks, a harmony that drifts off pitch and
drums that fall behind. Then follow `DEMO.md`: scan it, hear each fix, approve two, apply them. With `--kind reaper`
a REAPER project plays the stems, so the scan sees all six; the plain folder shows the hiss and the clipping. That
project was opened in REAPER 7.86 and read back (no offline media, matching what HypnoMix wrote); REAPER does not need to be open to scan it. There is no Live set kind, because a set
written from scratch has not been opened in Live.

### 0b. Check the files before any work (optional, any song)

```bash
hypnomix preflight "Song stems/"            # or Song.als, Song.rpp, Song.ardour
hypnomix preflight "Song stems/" --plan     # the same findings, as a review (see guide 2)
```

It only reads. It tells you what is wrong with the files themselves: stems with different sample rates or bit
depths, stems of different length or that start apart, exact duplicates, stereo that is really mono, silent or
already-clipped files, lossy sources, files a project cannot find, and names other systems refuse. The report is
`PREFLIGHT.md`; the exit code is 1 when something serious turns up. A file it calls silent may be an empty track on
purpose: say so and move on. `preflight` is new: it passes unit tests on synthetic data and has not yet been run on the
files of a real song.

### 1. Tell it your standards (five minutes, once)

A few questions, answered once: your loudness target, tracks it must never touch without asking again, things
that are deliberate ("the long reverb tail in the outro"), how you like to review. Answer them on the app's
**Preferences** screen, or in the terminal:

```bash
hypnomix prefs                       # what is saved, and what is still unanswered
hypnomix prefs set targets.lufs=-14 protect.tracks="Lead Vox" protect.notes="long reverb tail in the outro"
```

Saved in `~/.hypnomix/preferences.json`; every scan reads it.

### 2. Open the app and scan a song

```bash
hypnomix app
```

Choose your Live set (or a folder of recordings from any DAW), optionally a bounce of the mix and the key, and
press **Start the first pass**. It runs every check at once and builds a before / after clip for each fix.
Nothing in your song changes.

### 3. Review

Each finding shows the track, the bar, the problem, the proposed fix and A / B players at matched loudness.
Approve, Skip, or Change with a note. Your clicks are saved as you go, so you can stop and come back.

### 4. Apply

Close the set in Live, then **Apply**: only what you approved goes into one new set next to yours, called
something like `Song (fixed).als`. The log says what was applied, what was skipped and why, and which problems
are no longer measured.

### 5. Listen

Open the new set, compare the changed spots with the original, and keep what you like.

## Where things go

| what | where |
|---|---|
| your preferences and learned habits | `~/.hypnomix/` |
| scans from the app | `~/Documents/Hypnomix/` |
| reports and audio from the terminal | `hypnomix-out/` in the folder you run from (set `HYPNOMIX_OUT` to change it) |
| new sets and projects | next to the original, with a new name |
| the by-hand checklist | `handoff/` inside the scan folder (guide 2) |
| the files you upload | `hypnomix-out/release/<Artist> - <Title>/` (guide 6) |
| tuned vocals from a set | `<project>/Samples/Tuned/` (a REAPER project: `<project>/Tuned/`) |
| the Live devices | Live's User Library → Presets → Audio Effects → Max Audio Effect |

Every tool writes a Markdown report next to its audio: what it found, what it did, and the numbers before and
after.

## The guides in this set

| guide | read it when |
|---|---|
| 1 · Getting Started | now |
| 2 · The First Pass | you want the whole clean-up loop in depth: scan, review, fix, verify |
| 3 · Vocal Alignment | you have doubles and harmonies to line up, match or widen |
| 4 · Vocal Production | tuning, harmony balance, comp edges, hiss, breaths and esses |
| 5 · Timing, Tempo & Motion | tightening a band, songs without a click, keeping loops alive |
| 6 · Mixing, Mastering & Release | from stems to a master that survives every speaker, and from a master to the files you upload |
| 7 · Inside Live, Faster Reviews | measuring while you play, hearing each fix inside Live, and deciding a long review quickly |
| 8 · HypnoMix in REAPER | the same loop on a REAPER project, from inside REAPER |
| 9 · Setting Up, and Choosing an AI | installing, and how to connect an AI, or none |
| Command Reference | you need the one-line answer for any command |
