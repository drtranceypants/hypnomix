# Aligning vocals: timing, pitch, formant

Doubles and harmonies that land together, notes that sit with the guide, and a wider stack, without paid
plug-ins. Three ways in, one engine:

| you have | use | what you get |
|---|---|---|
| exported files (any DAW), all from the same start | `hypnomix vocalign LEAD.wav PART.wav …` | new files next to a report |
| a saved Live set | `hypnomix alignset SET.als --guide … --parts …` | a new set: the timing as **warp markers on your own clips** |
| Live open, and you'd rather click | the **Hypnomix Align** device (`hypnomix aligndevice`) | the same as alignset, from inside Live |

Nothing overwrites your takes or your set. Every part is measured again afterwards with an independent check,
and a part that would not end up closer is left as it was.

## Timing

Two modes, chosen for you:

- **Gentle stack** (2+ parts, the default): nobody is forced onto one lead. Only the parts singing the same
  words at the same time are compared. Word by word, a word clearly off the group (beyond the song's own
  looseness, at least 30 ms) moves 80% of the way; every other word 10%. With `--bpm` the stack is pulled 30%
  toward the song's own grid. Never more than 60 ms.
- **To the guide** (`--to-lead`, or one part): the part follows the guide's timing all the way (`--strength 1`),
  with smooth speed changes (`--mode gentle`) if it sounds warbly.

## Presets

`--preset NAME` is a starting point. Anything you set yourself still wins. `--list-presets` lists them.

| preset | for | what it sets |
|---|---|---|
| `gentle-stack` | harmony stacks (the default behaviour, named) | worst words 80%, the rest 10%, grid 30%, cap 60 ms |
| `natural-double` | a double that should still sound like two takes | to the guide, 70%, gentle speed changes, cap 80 ms |
| `tight-pop` | pop / R&B stacks | to the guide, 100%, tails trimmed, pitch 0.35, vibrato 0.3 |
| `loose-folk` | folk, country, indie | worst words only, 50%, no grid pull, cap 40 ms |
| `rap-doubles` | rap doubles and ad-lib stacks | to the guide, 100%, tails trimmed, cap 150 ms |

## Protected areas and sync points

```bash
hypnomix vocalign Lead.wav Dbl.wav --protect 1:02-1:10.5 --sync 1:31.2 --sync 95.10=95.03
```

- `--protect START-END`: never moved. The original audio stays sample for sample there (also through the pitch
  and formant steps); the move fades out in the 300 ms before and back in after.
- `--sync T`: at T, the part lines up exactly with the guide. The offset is measured to a fraction of a
  millisecond from the loudness shapes of both (pitch-independent, so harmonies work). `--sync G=P` says
  the guide's moment G is the part's moment P. A sync point overrides the gentleness, within the cap.
- Times are seconds or m:ss. In a Live set: song time (the device sends the loop brace and the playhead).

## Pitch matching (off unless you ask)

```bash
hypnomix vocalign Lead.wav Dbl.wav Harm.wav --pitch 0.35 --chords "Song instrumental.wav"
```

Each note of a part is compared with what the guide sings at that moment:

- **double** (unison or octave): the note's centre moves toward the guide's
- **harmony** (any other interval): the interval is kept; only the drift off it is corrected
- `--vibrato 0-1` (doubles): the shape inside the note moves that far toward the guide's

As gentle as `tune`: only notes more than 20 cents off (`--pitch-tolerance`), by 35% (`--pitch`), never more
than 25 cents (`--pitch-max`). A note 45+ cents off is halfway to another note: flagged, not moved.
**The chord under every note is checked first** (`--chords INSTRUMENTAL.wav` or `--ref MIX.wav`; alignset
uses the set's own instrument tracks). A target that clashes with the chord while the other neighbour fits is
ASKED, not moved. Without a chord source it refuses (`--no-chord-check` to override). Only the moved notes
are replaced; every other sample is the part as it was.

## Formant and transpose

```bash
hypnomix vocalign Lead.wav "Dbl L.wav" "Dbl R.wav" --formant "Dbl L.wav=0.4" --formant "Dbl R.wav=-0.4"
```

- `--formant SEMIS`: the voice's character moves, the pitch doesn't. +0.3 to +0.8 sounds smaller and brighter;
  negative amounts sound bigger and darker. Opposite small amounts on two doubles widen a stack without more takes.
- `--transpose SEMIS`: the pitch moves, the character stays.
- `--formant-at 62-70`: only inside these ranges. For every part, or one part by file name (`NAME=SEMIS`).

## In a Live set: alignset

```bash
hypnomix alignset "Song.als" --guide "Lead Vox" --parts "Double" "Harmony Hi" --bars 33-49 --bpm 106
hypnomix alignset "Song.als" --guide "Lead Vox" --parts "Double" "Harmony Hi" --bars 33-49 --bpm 106 --apply
```

1. Each track is rendered from the saved set exactly as Live plays it (clip gain, fades, warps).
2. The same engine plans the moves, renders previews (`<track> (stack aligned).wav`) and checks them.
3. With `--apply`, the planned moves become **warp markers on the part's own clips** in
   `Song (aligned).als` next to yours: the fewest markers that follow the plan within half a millisecond.
   Unwarped clips get warp switched on (Complex Pro, playing exactly as before) unless `--keep-unwarped`.
   Looped clips are skipped (unroll them first: `hypnomix unroll`).
4. Pitch and formant can't be warp markers: those parts are rendered as files from bar 1 (1.1.1), for a new
   track under the original (the device places them and mutes the original).

Measured on a real 106 BPM song: the new set plays within 1.5 ms (median) of the checked preview, and nothing
outside the chosen bars changes. Close the set in Live before opening the new one. One tempo is assumed.

## Inside Live: the Hypnomix Align device

```bash
hypnomix app            # leave it running
hypnomix aligndevice    # once: writes the device into your User Library
```

Drag **Hypnomix Align** onto any track (audio passes through). Save your set, then:

1. **Choose set**: the saved `.als` you are in.
2. Select the guide track → **Guide ←**. Select each part → **+ Part**.
3. Loop-brace the bars → **Range: brace** (or **Range: song**).
4. Optional: brace a bit you love → **Protect**. Put the playhead on a consonant that must land → **Sync here**.
5. Drag the dials: **Tight**, **Pitch** (off by default), **Vibrato**, **Formant**. Or click **Preset**.
6. **Align**: measures and makes previews; the lanes show each part before (grey) and after (amber).
7. Happy? Switch **Write set** on and **Align** again, then **Open set**. **Place** puts pitch/formant files on
   new tracks.

The device is new: its script is tested against a simulated Live set, and the alignment it drives is tested
on real sets, but it has not been loaded in Live yet. If something misbehaves, the Max window says which line.

## For an AI agent

- Ask before pitch matching: it's off by default, and the person's own tuning rules apply (gentle, chord check).
- Never align every part to one lead unless asked: the stack mode is the default for a reason.
- Fixes go on the person's own comp clips (alignset), not rendered replacements, unless they ask for files.
