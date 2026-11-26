---
title: The First Pass
subtitle: Preferences → scan → review → fix → verify, the safe way to clean up a song
---

# The loop

The first pass is the fastest safe way to clean up a song. Every check runs at once, nothing changes until
you approve it, every approved change lands in new files, and the result is measured again.

<!--toc-->

```
 prefs (once) ─► scan ─► review (you) ─► fix (only approved) ─► listen ─► prefs learn
                  │            │                 │
           changes nothing   A / B players    one NEW set, measured again
```

## 0. Preferences (once)

| setting | what it does |
|---|---|
| targets | loudness and true peak the mix check compares with (default -14 LUFS, -1 dBTP) |
| protect.tracks | findings on these tracks are marked PROTECTED; fix refuses them until you say yes again |
| protect.notes | things that are deliberate, printed at the top of every review so nobody "fixes" them |
| review, taste, tools | how you like to review, how strict tuning and timing should be, your free plug-ins |
| learned | after each review, what you approved and skipped per kind of finding: advice for next time, never applied by itself |

```bash
hypnomix prefs set targets.lufs=-14 targets.true_peak=-1 review.style=one-at-a-time \
                   protect.tracks="Lead Vox,Strings" protect.notes="long reverb tail in the outro"
```

## 1. Scan (read-only)

In the app: **Songs → choose a set → Start the first pass**. In the terminal:

```bash
hypnomix scan "Song.als" --mix "Song mix.wav" --ref "Song instrumental.wav" --key "F# major"
hypnomix scan "raw takes/"          # recordings or stems from any DAW: no Live set needed
```

| option | why give it |
|---|---|
| `--mix` | a bounce of the whole song: loudness, true peak, release checks |
| `--ref` | the mix or an instrumental: the song's real tuning (songs are often not at A=440) and the chords under the vocals |
| `--key` | the key, confirmed by you; vocal tuning is never applied without it |
| `--deep` | renders every track and reports frequency fights and mic phase |
| `--like REF.wav` | tone, dynamics, width and loudness against a song you love, as proposals |

What a set scan checks, in parallel groups:

| group | checks |
|---|---|
| names | default track names → names by sound; track order and vocal-stack parts by pitch |
| files | missing audio |
| clips | clicks, level jumps at comp cuts, spikes; fades and edges that cut into a word |
| timing | hits out of time with the band (the song's own grid, drums first, then bass) |
| vocals | pitch of every vocal, harmonies against the lead, doubles' timing, harmony balance |
| effects | distortion in takes and device chains, sidechain ducking, every compressor and gate |
| mix | loudness, true peak, release checks (needs `--mix`) |

The result is `REVIEW.md` and `findings.json`, most severe first, each item with an id. If a check could not
run, the review lists it under **Checks that did NOT run**: no findings from a check that didn't run means
nothing.

## 1b. Hear it first

The app builds the before / after clips for you. In the terminal:

```bash
hypnomix ab "hypnomix-out/scan/Song"               # level-matched before / after clips
hypnomix review "hypnomix-out/scan/Song" --serve   # a page with players and buttons
```

Previews cover clip fixes, vocal tuning and repaired recordings. Timing nudges and device changes can't be
previewed offline: apply that one fix into a new set and listen in Live.

## 2. Review: one item at a time

Every finding has a severity (high, medium, low, info), a track, a place (bar.beat or m:ss), the problem, the
proposed fix, and how it applies:

| applies | meaning | done by |
|---|---|---|
| set | a change to the Live set | `fix`, into one new set |
| audio | a new audio file (a tuned vocal, a de-hissed take) | `fix`; you put it on a track |
| manual | needs your hands or ears in the DAW | you |
| info | a measurement | nothing |

**From inside Live:** drag the **Hypnomix** device (`hypnomix device`) onto any track. With the app open on
a review, Prev / Next / Next open step through the findings and Live jumps to each one: the track is
selected, the playhead and loop brace move to the spot, the clip opens. Approve and Skip record your decision
exactly like the app. Nothing is applied from inside Live. Press **Float** on the device first: each jump
selects the finding's track, so Live shows that track's clip where the device was, and the floating panel
stays in view while you step.

**In the terminal:**

```bash
hypnomix fix "hypnomix-out/scan/Song" --decide smooth-14=approve,timing-7=skip
hypnomix fix "hypnomix-out/scan/Song" --decide tune-Lead=change --note "lighter on the verse"
hypnomix fix "hypnomix-out/scan/Song" --list
```

> Tip: high-severity items, protected tracks and anything about taste are always asked one at a time.

## 3. Fix: only what you approved

Close the set in Live first. In the app: **Apply**. In the terminal:

```bash
hypnomix fix "hypnomix-out/scan/Song" --approved --out "Song (fixed).als"
```

The order inside the new set: distortion settings → sidechain settings → clip fades and volume eases →
warp-marker nudges → track order and stack clip moves → track names. To hear each change on its own, apply one
id per run and chain them with `--from "Song (fixed 1).als" --out "Song (fixed 2).als"`.

What fix checks, and stops on:

| check | what happens |
|---|---|
| the set was saved after the scan | stops; scan again (or `--stale-ok` if the change is unrelated) |
| the output exists, or is the original | stops: nothing is ever overwritten |
| a finding is on a protected track | stops; ask again, then `--allow-protected` |
| vocal tuning without a confirmed key | refused; pass `--key`, or `--key sections` for a song that changes key |
| a finding is no longer in the set | skipped and listed, never swapped for its neighbour |
| after writing: structure | `hypnomix check` runs; a broken set is renamed "(BROKEN, do not open)" |
| after writing: what changed | every change in plain words in `fix-log.md` (`hypnomix diff OLD NEW`) |
| after writing: result | measured again: "N of M approved problems no longer measured" |

## 4. Listen, then teach it

The numbers say a problem is gone; only your ears say it sounds right. Open the new set and A/B the changed
spots. Then:

```bash
hypnomix prefs learn "hypnomix-out/scan/Song"
```

Next time, the review shows what you usually do ("in past reviews you skipped 9 of 10 like this").

## Plans: tools that make many moves

`prep`, `automix` and `master` can also work as a review instead of doing everything at once:

```bash
hypnomix prep "raw takes/" --plan
hypnomix automix "stems/" --plan
hypnomix master "Song mix.wav" --plan
```

Each move becomes a finding, reviewed like any other; `fix --approved` then runs the tool with only the
approved moves.

## Other DAWs

Export every track as a full-length file from the same start, processing off, then
`hypnomix scan "that folder/"`. Repaired audio comes back as new files; anything that has to happen in the
DAW (an EQ cut, a fader move) is listed as a to-do.

## What the checks deliberately leave alone

- **Feel**: timing measures the band's own looseness and flags only outliers; tuning keeps vibrato, scoops and slides.
- **Taste**: harmony balance, how far a part moves, how hard a note is pulled are options with fine controls, never a fixed rule.
- **Intent**: automation, effects and levels you set are treated as choices.
- **Undecidable cases** go to you: a note halfway between two pitches, a hit too crowded to stretch cleanly, a sound that might be hiss or a pad.
