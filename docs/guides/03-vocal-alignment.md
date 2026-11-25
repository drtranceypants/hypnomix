---
title: Vocal Alignment
subtitle: Doubles and harmonies that land together, sit with the guide, and fill the stereo field
file: 3 - Vocal Alignment
---

# Tight stacks, human feel

Tight stacks are what make a vocal production sound expensive, but a stack snapped onto one lead sounds like
a machine. hypnomix aligns gently by default: only words clearly out of time move, and the original audio
stays sample for sample wherever nothing needs to change.

<!--toc-->

## Three ways in

| you have | use | you get |
|---|---|---|
| exported files from any DAW, all from the same start | `hypnomix vocalign` | new aligned files and a report |
| a saved Live set | `hypnomix alignset` | a new set where the timing is **warp markers on your own clips** |
| Live open, and you'd rather click | the **Hypnomix Align** device | the same as alignset, from inside Live |

All three use one engine, and every result is checked by a second, independent measurement. A part that
would not end up closer to the others is left exactly as it was.

## Timing: the two modes

### Gentle stack (the default for 2+ parts)

Nobody is forced onto one lead.

1. Only parts singing **the same words at the same time** are compared. A part on its own line keeps its timing.
2. Each word is measured against the other parts singing it.
3. A word clearly off the group (beyond the song's own looseness, and at least 30 ms) moves **80%** of the way.
4. Every other word moves only **10%**: a gentle tightening that keeps the feel.
5. With `--bpm`, the whole stack is pulled 30% toward the song's own grid (it detects triplets too).
6. Nothing ever moves more than 60 ms. Each word moves as a whole; the change happens in the gap before it.

```bash
hypnomix vocalign "Lead.wav" "Harm 1.wav" "Harm 2.wav" "Dbl.wav" --bpm 106
```

The report lists the problem areas ("1:50.2–1:51.4: Harmony 1 early, 20 ms") and the worst words fixed.

### To the guide

For a double that should sit right on the lead, or one part against one guide:

```bash
hypnomix vocalign "Lead.wav" "Double.wav" --to-lead --strength 1.0 --trim-tails
```

| option | does |
|---|---|
| `--strength 0-1` | how far toward the guide (0.7 keeps a little natural looseness) |
| `--mode gentle` | smoother speed changes if a part sounds warbly |
| `--trim-tails` | fades word endings that hang past the guide's (the classic stacked "s") |
| `--level -6` | sets the double this many dB under the guide while both sing |
| `--max-ms` | the largest move allowed |

> Tip: under ~10 ms reads as one voice; 20–40 ms as a natural double; above that you hear flams and smeared
> consonants.

## Presets

A preset is a starting point. Any option you set yourself still wins.

| preset | for | sets |
|---|---|---|
| `gentle-stack` | harmony stacks (the default, named) | worst words 80%, the rest 10%, grid 30%, cap 60 ms |
| `natural-double` | a double that should still sound like two takes | to the guide, 70%, smooth speed changes, cap 80 ms |
| `tight-pop` | pop and R&B stacks | to the guide, 100%, tails trimmed, pitch 0.35, vibrato 0.3 |
| `loose-folk` | folk, country, indie | worst words only, half way, no grid pull, cap 40 ms |
| `rap-doubles` | rap doubles and ad-lib stacks | to the guide, 100%, tails trimmed, cap 150 ms |

```bash
hypnomix vocalign "Lead.wav" "Dbl.wav" --preset natural-double
hypnomix vocalign --list-presets
```

## Protected areas

A phrase where the double's looseness is the point, a bit you love as it is:

```bash
hypnomix vocalign "Lead.wav" "Dbl.wav" --protect 1:02-1:10.5 --protect 2:40-2:44
```

Inside a protected area **nothing moves**, and the audio there is the original take sample for sample, through
the timing, pitch and formant steps alike. The move fades out over the 300 ms before the area and back in
after it, so nothing jumps.

## Sync points

A consonant that must land exactly, the first word of a chorus:

```bash
hypnomix vocalign "Lead.wav" "Dbl.wav" --sync 1:31.2               # find the matching moment near 1:31.2
hypnomix vocalign "Lead.wav" "Dbl.wav" --sync 95.10=95.03          # the guide at 95.10 s is the part at 95.03 s
```

The offset at a sync point is measured from the loudness shapes of both voices (they don't depend on pitch,
so it works on harmonies as well as doubles) to a fraction of a millisecond. A sync point overrides the
gentle settings there, within the cap. In stack mode the first part is the guide: it holds still at a sync
point and the others land on it.

## Pitch matching (off unless you ask)

```bash
hypnomix vocalign "Lead.wav" "Dbl.wav" "Harm.wav" --pitch 0.35 --chords "Song instrumental.wav"
```

Each note a part sings is compared with what the guide sings at the same moment:

| the part is | what happens |
|---|---|
| a **double** (unison or octave) | the note's centre moves toward the guide's |
| a **harmony** (any other interval) | the interval is kept; only the drift off it is corrected, so the third stays a third |

It is as gentle as `hypnomix tune`:

| option | default | means |
|---|---|---|
| `--pitch` | 0 (off) | how far each note moves: 0.35 is gentle, 1.0 all the way |
| `--pitch-tolerance` | 20 cents | closer than this: left alone |
| `--pitch-max` | 25 cents | never moves a note more than this |
| `--vibrato` | 0 | doubles also take this share of the guide's vibrato and inflection |
| `--pitch-only` | all | or `doubles` / `harmonies` |

A note more than 45 cents off the guide is halfway to another note: it is **flagged**, not moved.

**The chord under every note is checked first.** Give `--chords` (the song without vocals) or `--ref` (the
mix); alignset uses the set's own instrument tracks. If moving a note would clash with the chord while the
other neighbour fits it, the note is **asked about** and left as sung. Without a chord source it refuses
(`--no-chord-check` to override). Only the moved notes are replaced: every other sample is the part as it was.

## Formant and transpose: a wider stack

```bash
hypnomix vocalign "Lead.wav" "Dbl L.wav" "Dbl R.wav" --no-timing \
    --formant "Dbl L.wav=0.4" --formant "Dbl R.wav=-0.4"
```

| option | does |
|---|---|
| `--formant SEMIS` | moves the voice's character, not its pitch: + smaller and brighter, - bigger and darker |
| `--transpose SEMIS` | moves the pitch, keeps the character |
| `--formant-at 62-70` | only inside these ranges |
| `"PART.wav=SEMIS"` | one part only; a plain number applies to every part |

> Tip: small, opposite amounts (+0.4 and -0.4) on two doubles panned apart make them sound like two different
> singers: a wider stack without recording more takes.

The output always lines up with the input sample for sample and keeps its length.

## In a Live set: alignset

```bash
hypnomix alignset "Song.als" --guide "Lead Vox" --parts "Double" "Harmony Hi" --bars 33-49 --bpm 106
hypnomix alignset "Song.als" --guide "Lead Vox" --parts "Double" "Harmony Hi" --bars 33-49 --bpm 106 --apply
```

1. Each track is rendered from the saved set exactly as Live plays it: clip gain, fades, warps.
2. The same engine plans the moves, writes previews and checks them.
3. With `--apply`, the moves become **warp markers on the part's own clips** in `Song (aligned).als`: the
   fewest markers that follow the plan within half a millisecond. Your comp stays your comp, and every marker
   can be dragged or deleted.
4. Unwarped clips get warp switched on (Complex Pro, playing exactly as before) unless you pass
   `--keep-unwarped`. Looped clips are skipped: unroll them first (`hypnomix unroll`).
5. Pitch and formant can't be warp markers, so those parts are rendered as files from bar 1 (1.1.1) to put on
   a new track under the original.

All the vocalign options work here too. Times for `--protect` and `--sync` are song seconds. One tempo is
assumed. Close the set in Live before opening the new one.

> Tested on a real 106 BPM song: the new set plays within 1.5 ms (median) of the checked preview, and nothing
> outside the chosen bars changed.

## Inside Live: the Hypnomix Align device

```bash
hypnomix app            # leave it running
hypnomix aligndevice    # once: writes the device into your User Library
```

Drag **Hypnomix Align** (User Library → Presets → Audio Effects → Max Audio Effect) onto any track. Audio
passes through it untouched.

| control | what it does |
|---|---|
| Choose set | the saved `.als` you are working in (save first: alignset reads the saved file) |
| Guide ← | the selected track becomes the guide |
| + Part | adds the selected track as a part (repeat for each) |
| Range: brace / song | only the bars under the loop brace, or the whole song |
| Protect | adds the loop brace's span to the protected areas |
| Sync here | the playhead position becomes a sync point |
| Tight, Pitch, Vibrato, Formant | drag up and down; double-click resets. Pitch and Vibrato start off |
| Preset | steps through the presets, or none |
| Align | measures and makes previews; the lanes show each part before (grey) and after (amber) |
| Write set | when on, Align also writes the new set with your clips' warp markers |
| Open set | opens the aligned set in Live (Live asks to save the current one first) |
| Place | puts pitch / formant results on new tracks under their originals and mutes the originals |

### A session with the device

1. Save your set. Click **Choose set** and pick it.
2. Select the lead vocal track, click **Guide ←**. Select each harmony, click **+ Part**.
3. Loop-brace the chorus. Leave **Range: brace** on.
4. The ad-lib at bar 41 is perfect loose: brace it, click **Protect**. Put the playhead on the chorus's first
   "s", click **Sync here**. Brace the chorus again.
5. Leave **Tight** at 50%. Click **Align** and watch the lanes: amber should sit closer to the guide's shape.
6. Happy? Switch **Write set** on, **Align** again, then **Open set** and A/B against your original.

> Careful: the device is new. Its script is tested against a simulated Live set and the alignment it drives
> is tested on real sets, but it has not been loaded in Live yet. If something misbehaves, right-click the
> device's title → Open Max Window to see which line.

## Which tool when

| situation | reach for |
|---|---|
| a big harmony stack that's mostly fine | gentle stack (default), with `--bpm` |
| a double that should sit right on the lead | `--preset natural-double` or `tight-pop` |
| one phrase drags, the rest is lovely | gentle stack, or `--sync` on that phrase plus `--protect` around what you love |
| doubles slightly out of tune with the lead | `--pitch 0.35 --chords …` (asks on chord clashes) |
| a stack that sounds narrow | `--formant` +0.4 / -0.4 on a pair of doubles |
| a comped vocal in Live you don't want rendered | `alignset` or the Align device |
