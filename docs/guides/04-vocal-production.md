---
title: Vocal Production
subtitle: Tuning, harmony balance, comp edges, hiss, breaths and esses, without losing the singer
---

# The voice first

Vocals carry the song, and listeners hear every flaw in them. hypnomix's vocal tools share one idea:
**fix what distracts, keep what's human.** Every tool is gentle by default, changes only the moments that need
it, and leaves the rest of the take bit for bit as it was.

<!--toc-->

## The usual order

| step | tool | why this order |
|---|---|---|
| 1. clean the raw takes | `dehiss`, `prep` | noise first: every later step measures cleaner audio |
| 2. pick and comp | `takes`, then comp in Live | choose the performance before polishing it |
| 3. check the comp's edges | `edges` | a fade that eats the first "s" of a word |
| 4. tune | `tune` | gentle, note by note, chord-checked |
| 5. align the stack | `vocalign`, `alignset` | see guide 3 |
| 6. balance the harmonies | `voices`, `cliplevel` | levels, once timing and pitch are settled |
| 7. polish | `deess`, `breaths` | the last details, on the finished parts |

## Clean the takes: dehiss

```bash
hypnomix dehiss "Lead Vox.wav" --reduce 12 --gate 18 --report
```

Two gentle stages. A spectral reduction learns the hiss from the quietest moments and lowers only the
frequencies sitting at hiss level, by at most `--reduce` dB, smoothed so it never sounds watery. Then a
look-ahead gate fades the gaps by `--gate` dB, opening 20 ms before each note and closing slowly so tails
decay naturally (it has a 150 ms hold, so soft tails can't make it chatter). Use `--gate 0` to keep a room
sound you like. Run it on raw takes, before clip gain.

## Choose the best take: takes

```bash
hypnomix takes "Take 1.wav" "Take 2.wav" "Take 3.wav" --bpm 92 --section-bars 4
```

Scores each take section by section on clipping (a hard fail), noise and hum, pitch, timing (with `--bpm`) and
level consistency, and writes a comp list: the best take for each section. All takes must start at the same
point. `--no-pitch` for drums, strummed chords and pads.

## Comp edges: edges

When you comp in Live, a clip fade or a clip start can cut off the first consonant of a word: the "s" of
"say", the "t" of "time". `edges` finds them.

Each take is rendered with its edges opened and compared with the comp as it plays. A consonant the comp plays
6 dB or more down is flagged, but only where the comp carries on with the word right after it (adding the
consonant where the comp leaves the word out would leave a stray "s"). The fixes, in order of preference:

1. shorten the fade that eats it
2. move the clip start to 10 ms before the consonant
3. move a comp switch later, when another take sings the consonant across it

Each fix is checked again, then compared by render. It is undone if the peak rises more than 2.5 dB beyond what
it restores (two takes doubling). The fixes are clip edits on **your** comp, never a rendered replacement. It
runs as part of the first pass (the clips group).

## Tuning: tune

```bash
hypnomix tune "Lead.wav" "Lead (tuned).wav" --ref "Song mix.wav" --chords "Song instrumental.wav" --key "A minor"
hypnomix tune "Lead.wav" --report-only --ref "Song mix.wav"      # just measure
```

How it stays natural:

- **The song's own tuning.** The reference pitch is measured from the mix, not assumed to be A=440 (one test song sat at A=435.4 Hz).
- **Only each note's centre moves.** Vibrato, scoops, slides and breath stay as sung.
- **Extremely gentle by default.** `--amount 0.35` (how far), notes within 20 cents untouched (`--tolerance`), never more than 25 cents moved (`--max`): no note becomes another note.
- **Undecidable notes are flagged**, not changed: a note sung halfway between two pitches that neither the key nor the guide can settle.
- **The chord under every note is checked.** A note whose nearest semitone clashes with the chord while the other neighbour fits it (B sung sharp over a C chord: C was probably meant) is left as sung and marked ASK, with the chord and a suggestion. Answer with `--note-answer 0:15.32=C`. Tuning without a chord source is refused unless you pass `--no-chord-check`.
- **Only the moved notes are spliced in** (±20 ms, 10 ms crossfades). Everything else is the original take, bit for bit: 97% of a real harmony take stayed untouched.

| option | for |
|---|---|
| `--guide LEAD.wav` | harmony notes near a quarter-tone settle toward a consonant interval with the lead |
| `--scales KEY.json` | songs that change key: per-section scales from `hypnomix key --sections` |
| `--drift 0.5` | also flatten slow drift inside long notes; vibrato stays |

From a Live set, the first pass tunes the take files under a track's comp clips and points those clips at the
tuned takes in the new set: your comp stays your own clips, natively in Live.

> Tip: on a real harmony, tune took the median from 25 to 6 cents off, and notes within ±15 cents from 30% to
> 83%, with syllable timing unchanged.

## Harmony balance: voices

Harmonies should support the lead, not compete with it. `voices` balances a stack around the part **you**
choose, and only turns parts down where they actually sing together.

```bash
hypnomix voices "stems/"                                  # first: it lists the parts and asks
hypnomix voices "stems/" --anchor lead --tame              # the suggested setting
hypnomix voices --set "Song.als" --apply-set "Song (voices).als" --tame
```

| choice | options |
|---|---|
| which part leads | `--anchor lead`, `lowest`, `highest`, or a track name; it is never turned down |
| which way to reduce | `--reduce above`, `below`, `both` |
| how much per step | `--above-db`, `--below-db` (0, 1, 1.5, 3, 4.5, 6 or any value), `--spread ladder` or `flat` |
| stated spacing | `--root-step 4 --upper-step 5.5`, saved as your default with `voices --confirm` |

The suggested `--tame` keeps harmonies a little under the lead (at least 1.5 dB) and brings down only a part
that is more than 1.5 dB louder than the part below it. With `--set` it measures each part **after** its
track's compressors and fader and writes the spacing as volume automation, so it lands exactly. Nothing is
turned down by default: the scan asks first.

`cliplevel` handles the opposite problem: a clip of a lower harmony sitting more than 4 dB under the rest of its
track. It offers clip-gain raises up to the track's usual level, never closer than 1.5 dB to the lead.

## Level line to line: vocallevel

Does the vocal stay at an even level from one lyric line to the next, and do the upper harmonies sit just under
the melody? `vocallevel` checks both, line by line (a line is one phrase of the lead singer's track). The first
pass runs it for you; run it again before every final export, because restored comps, re-tuned notes and fader
moves made since the scan can change it.

```bash
hypnomix vocallevel "Song.als" --heard "solo exports/"              # each vocal track exported solo, as heard
hypnomix vocallevel "Song.als" --renders "renders/" --melody "Harmony low"
hypnomix vocallevel "Song.als" --heard "solo exports/" --apply "Song (levels).als"
```

| check | what it flags |
|---|---|
| upper | a part pitched above the melody that is louder than the melody minus 1.5 dB on a line (`--upper-under`); parts below the melody are never flagged |
| jump | a line where the whole stack is 1.5 dB or more louder or quieter than the lines around it (`--jump`) |

`--melody` names the part the others are measured against: the lead as heard. If the track called "Lead" is
turned well down and a lower harmony carries the tune, name that harmony. `--heard` (solo exports) measures what
you actually hear; `--renders` is a quicker first look, and differences read larger because track compressors
aren't applied.

`--apply` writes the fixes as volume automation on a **new** set: each upper part lowered on the lines where it
is over, then the stack's lines evened out on the vocal group's volume. Changes ramp in the gaps between lines,
existing automation is kept, and the song's last two lines are never raised (`--keep-ending`), because an ending
that dies away is usually on purpose.

## Polish: deess and breaths

```bash
hypnomix deess "Lead (tuned).wav" --amount 0.7 --max-db 8
hypnomix breaths "Lead (tuned).wav" --reduce 8
```

**deess** learns where this voice's "s" lives (it centres its band on that voice's own sibilance peak), finds
each "s" as a short burst louder than the body of the voice, and turns down **only that band, only during that
"s"**, by at most `--max-db`. Everywhere else the audio is bit-identical, and the report lists every "s" it
touched.

**breaths** finds breaths between phrases and turns each down by `--reduce` dB with short fades inside the
breath. Not removed: no breaths at all sounds robotic. A breath is 150-900 ms of sound that is quieter than the
singing, has no pitch, and is airier than that singer's own voice, so it works on dark microphones too. A short
"s" or "f" straight after a word is left alone. Use it on vocals only (a drum track gives false breaths), run
`--report` first, and listen: if a word's start or end got quieter, lower `--reduce` or skip that file.

Both take `--report` to analyse without writing anything, and neither ever overwrites its input.

## Clips recorded on different days: clipmatch

```bash
hypnomix clipmatch --als "Song.als" --track "Lead Vox"            # report only
hypnomix clipmatch --als "Song.als" --track "Lead Vox" --apply    # sets Clip Gain in the open set
```

Matches loudness while the part is sounding (not over the silence between phrases) and reports tone
differences as EQ Eight moves: a low shelf for proximity effect, a high shelf for an off-axis or distant mic.

## Vocal numbers to remember

| what | target |
|---|---|
| recording peaks (24-bit) | -12 to -6 dBFS |
| noise floor between phrases | below -60 dBFS |
| tuning: leave alone within | 20 cents |
| tuning: never move more than | 25 cents |
| stack timing: one voice / natural double | under 10 ms / 20–40 ms |
| harmonies under the lead | at least 1.5 dB |
| breaths turned down | about 8 dB, never removed |
