---
name: harmony-balance
description: Balance stacked vocal harmonies the way THIS person does: first learn, from their own finished songs, how far their harmonies usually sit under the lead and how far apart the harmonies sit from each other, then only correct what falls outside their own habits. Use when someone has a lead vocal with harmonies or doubles and wants the harmony levels checked, "space between the harmonies", harmonies "a little quieter than the lead", or asks what dB amounts to use on harmony clips.
---

# Harmony balance from the person's own habits

Goal: harmonies a little under the lead and some space between them, measured against how this person
already mixes, not against numbers someone picked. Nothing is turned down unless it falls outside their pattern,
the lead is never turned down, and anything stronger is their choice.

## 1. Learn their pattern (once, and again when they finish more songs)

1. Check for `~/.hypnomix/harmony-style.json`. If it exists, read its `songs` list and the date it was written;
   if the person has finished songs since, offer to learn again.
2. Find their **own** finished songs: their original projects, not reworked copies another tool or agent made
   (a "Claude Producer" or "(remix)" copy is not their habit). Ask if unsure which projects count.
3. Run:
   `hypnomix voices --learn "Song A.als" "Song B.als" …`
   For each song it names the tracks, renders the vocal clips straight from the set (no Live needed), adds each
   track's fader, and measures, wherever the lead and harmonies sing together (2-second readings):
   - how far each harmony sits under the lead (dB)
   - how much louder or quieter each higher harmony is than the one below it (dB)
   It prints one line per song and the pattern, and saves it. It's slow the first time (naming and rendering);
   results are cached.
4. Show the person the per-song lines in plain words ("in Song A your harmonies sit about 4 dB under the lead;
   higher ones are about 1 dB quieter than the one below"). Ask whether any song is not typical of how they want
   it (a demo, a rough mix). If so, learn again without it.

What it derives (each song counts once):
- **lead margin** = how far under the lead 3 in 4 of their harmony readings already sit (the 25th percentile).
  Harmonies closer to the lead than that are the unusual ones.
- **tolerance** = how much louder than the part below it a higher harmony gets in 9 of 10 readings (the 90th
  percentile). Only a part beyond that is overshadowing by their own standard.

## 1b. Their confirmed spacing (wins over everything learned)

The person can state their spacing; record it with `hypnomix voices --confirm …` and it becomes the `--tame`
default. Current example of a confirmed spacing: the lowest harmony at each moment is the basis (never turned
down), the next harmony up sits about 4 dB under it, higher ones about 5.5 dB under it (5-6 on average), the
lead at least 1.5 dB over every harmony; act only where a part is more than 1 dB over its step (it is drowning
out the ones below), cut at most 4 dB in any 2-second window, 250 ms ramps. They have set clip gains by hand:
respect that, the tool only catches the spots they missed.
`hypnomix voices --confirm lead_margin=1.5 tolerance=1 root_step=4 upper_step=5.5 max_cut=4`

## 2. Apply it

`hypnomix voices STEMS… --tame` (post-chain stems), or in a first pass approve the `harmony-1` item with no note:
`hypnomix fix DIR --decide harmony-1=approve`. Scan renders are raw clips, so the scan passes each track's fader
(`--fader NAME=dB`) to compare levels as heard. `--tame` uses the learned numbers automatically:

- a harmony closer to the lead than their lead margin comes down to exactly that margin, no further
- a higher harmony louder than the part below it by more than their tolerance comes down to that edge, no further
- the lead is never turned down
- windows where all the harmonies sit at one level (no space between them) are reported, never "fixed"

Say which numbers were used and where they came from ("from your 7 songs: 3.2 dB under the lead"). If the
person wants something different, every number can be overridden in the note
(`--note "lead-margin=2 tolerance=1"`), and the stronger options (a part to prioritise, a step in dB, ladder or
flat) are theirs to ask for.

Before every final export, `hypnomix vocallevel` re-checks the vocal level line to line and the upper parts under the melody, as heard.

## 2b. Lower harmonies sitting too low

The scan also proposes `cliplevel-N` items: a clip of a lower harmony more than 4 dB under the rest of its track
gets an optional clip-gain raise, up to the track's usual level and never closer than 1.5 dB to the lead. Offer
them; never approve them unasked. A clip whose gain the person already pulled far down (-10 dB or lower) is
flagged as probably deliberate: ask.

## 3. Report

What was turned down, where (bars), by how much, and what was only reported (same-level harmonies). Write
balanced copies, never over the originals; the person A/Bs them against the originals by ear.

## Rules

- Their own songs set the numbers. Don't substitute "rules of thumb" (lower harmonies louder, -3 dB per part).
- Learn only from finished songs they made; never from sets an agent changed.
- Measured, not heard: levels are before each track's compressor, so they are close, not exact. Ears decide.
- Never turn the lead down; never push a harmony below their own pattern unless they ask for a step size.
