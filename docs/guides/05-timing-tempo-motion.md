---
title: Timing, Tempo & Motion
subtitle: Tidy what distracts, keep the groove, and keep long loops alive
---

# A grid is a tool, not a target

Players push choruses, lay back in verses and never hit two 16ths the same way. That is most of why a
recording feels alive. The tools here tidy what distracts and leave the rest. **Nothing here snaps a
performance to a grid.**

<!--toc-->

## Which tool for which job

| you have | you want | tool |
|---|---|---|
| a band recording with a few hits that stick out | only those hits fixed | `timing` (part of the first pass) |
| a take played to a click, a bit loose | it tighter overall, still human | `tighten` |
| a looped clip where one pass is off | to fix only that pass | `unroll`, or `timing --unroll-loops` |
| a take played without a click | its tempo, bar by bar | `tempomap --click` |
| | the take on Live's steady grid | `tempomap --conform` |
| | Live's grid following the take | `tempomap --follow` |
| | the best loops in it | `loops` |
| a finished song on a rigid click | it to breathe between sections | `breathe` |
| loops that repeat for minutes | variety | `variations`, `borrow`, `motion` |

## Fix only what sticks out: timing

```bash
hypnomix timing "Song.als" --track Drums --track Bass --track "Gtr L"
hypnomix timing "Song.als" --track Drums --track Bass --apply "Song (timing).als"
```

1. **It finds the song's own grid first**, bar by bar: straight 16ths, 8th- or 16th-note triplets, or a mix.
   A triplet is never nudged onto a 16th.
2. **It measures the band's own looseness** and flags only clear outliers. Downbeats are held tightest, 16ths loosest.
3. **The low end comes first.** Drums are the reference (compared only with other drums or the grid, never
   pulled toward the band). Bass is checked against the drums on every beat and moved 70% toward them.
4. **It fixes in passes:** drums first, then the bass against the corrected drums, then everything else
   against the band as it now is.

| slot | tolerance | moved |
|---|---|---|
| downbeat | 2.0 × the song's looseness (at least 12 ms) | 80% |
| beat | 2.5 × (at least 20 ms) | 60% |
| 8th upbeat | 3.0 × (at least 30 ms) | 40% |
| 16th | 3.5 × (at least 40 ms) | 30% |

Each fix is a few warp markers around the hit: one on the hit, moved part of the way, and one on each
neighbour holding it, so only that small stretch of audio moves. Drag or delete any of them in Live. MIDI
notes move too; a note in a looped clip moves only if it is off the same way on every pass, and one that is
identical on every pass is marked as probably a programmed feel. Melodic parts (guitar, keys, strings) get
only clear outliers, as optional items, moved at most 30% and 15 ms.

## Tighter, on request: tighten

```bash
hypnomix tighten "Song.als" --track "Rhythm Gtr" --strength 0.5 --preview "tight.wav"
hypnomix tighten "Song.als" --track "Rhythm Gtr" --strength 0.5 --apply "Song (tight).als"
```

A partial quantise for one take: hits within `--keep-within` ms stay put, the rest move `--strength` of the
way (0.1 to 0.9, default 0.5). It refuses a full snap. Listen to the preview with and without the click first.

## One pass of a loop: unroll

A looped clip plays the same audio every pass, so a nudge would move every pass. `unroll` turns the loop into
one copy per pass, checks they play sample for sample the same, and then only the copy holding the outlier is
nudged.

## No click? Map it: tempomap and loops

```bash
hypnomix tempomap "Drums take.wav" --click "check.wav"                   # listen: does the click sit right?
hypnomix tempomap "Song.als" --track Drums --conform --preview "conformed.wav"
hypnomix tempomap "Song.als" --track Drums --conform --apply "Song (grid).als"
hypnomix tempomap "Song.als" --track Drums --follow --apply "Song (follow).als"
hypnomix loops "Song.als" --track Drums --apply "Song (loops).als"
```

1. **Check the map by ear first.** The click file plays the beats it found over the take. If fewer than half the
   beats sit on a real hit, it says the map is guesswork and refuses to write a set. Correct it with `--bpm`,
   `--half`, `--double` or `--downbeat SECONDS`. Which beat is "one" is your call.
2. **Then choose.** `--conform` puts warp markers on the take's bar lines, so it sits on Live's steady grid and
   the feel inside each bar stays exactly as played. `--follow` leaves the take alone and writes tempo
   automation, so everything you overdub breathes with the drummer.
3. **loops** offers the steadiest, best-joining 1, 2, 4 and 8 bar loops, grouped by groove, in empty Session slots.

## Let it breathe: breathe

```bash
hypnomix breathe "Song.als" --mix "Song mix.wav" --preview "breathing.wav"
```

What a band does without thinking: a percent or two faster into the big sections, a little slower in the quiet
ones, a glide between (at most -2% to +2.5%). Hear it on your bounce first.

> Careful: unwarped clips don't follow a tempo change, so breathe lists them and writes nothing unless you pass
> `--warp-clips`. The song's length changes, so anything cut to the old audio (a video) will no longer line up.
> Run `tighten` and `variations` before breathe, not after: they need a constant tempo.

## Keep long loops alive

Eight bars repeating for two minutes feel static. Three sources of variety, all offered **switched off** or as
review items. Nothing plays until you turn it on.

### variations: takes you never used

```bash
hypnomix variations "Song.als"
```

Finds parts that repeat the same whole-bar loop and unused material that fits: other stretches of the same
recording, and other takes of the part in the project's `Samples/Recorded` that the set no longer uses. Each
gets a new track next to it, with the same devices, switched off. Turn it on to hear it; delete it to undo.

### colour: a different sound for the repeat

```bash
hypnomix colour "Song.als" --part Pad
hypnomix colour "Song.als" --plan          # the proposals as findings for the review
```

Measures every part section by section (tone in six bands, notes per bar) and finds where a part, and the whole mix,
sounds like an earlier section. There it proposes a colour (`--family width|grit|space|movement|octave`, or the one
the measurements suggest) as a chain of Live's own devices on a switched-off copy of the part, holding only those bars,
with a four-bar before / after clip. `--max`, `--per-part`, `--amount` and `--static` (how close counts as "the same",
2 dB) are yours to set. Nothing is added unless you pick a number: `--apply "Song (colour).als" --ids colour-1`. Live sets
only for now; the clip "after" is a model of the chain, so listen in Live.

### borrow: from the song's original project

```bash
hypnomix borrow "Song (remix).als" --mix "Song mix.wav" --plan
```

Clips the song's first project had and the rework dropped (MIDI and audio, Arrangement or Session), each for a
section it fits. MIDI loops are offered only where their notes fit the section's scale, nudged as a whole so
the first note lands with the song's downbeats.

### motion: effect moves in your own style

```bash
hypnomix motion --learn "Finished Song.als" "Another.als"       # once: your moves, lengths and depths
hypnomix motion "Song.als" --mix "Song mix.wav" --plan
```

| move | where | what it writes |
|---|---|---|
| riser | into a bigger section | filter opens, reverb builds; snaps back on the one |
| dip | inside a repetitive section | a slow low-pass down and back up |
| drift | across 32+ bars | the filter wanders, a point every 16 bars |
| swell | second half of a section | a reverb send stepped up bar by bar |
| throw | phrase ends | a delay send up for the last beat |
| outro | the last section | the reverb rises to the end |
| stutter | transitions and turnarounds | the last 2 beats of a drum clip re-triggered: 8ths, then 16ths |
| gate | transitions and turnarounds | a rhythmic volume chop for the last bar |
| dropout | into a drop | drums or bass silent for the last beat, then hit the one |

Fine controls go in the decision note: `bars=`, `depth=`, `dB=`, `every=`, `beats=`, `pattern=`, `track=`.
It never writes where you already automated that control, and never edits comped clips.

## Limits worth knowing

- `tighten`, `variations` and `alignset` assume one tempo; `timing` assumes a constant tempo and 4/4.
- Every set these tools write passes hypnomix's structural check. Open it in Live and listen before keeping it.
