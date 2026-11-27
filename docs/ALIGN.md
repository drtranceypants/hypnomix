# Aligning vocals: timing, pitch, formant

Doubles and harmonies that land together, notes that sit with the guide, and a wider stack, without paid
plug-ins. Five ways in, one engine:

| you have | use | what you get |
|---|---|---|
| exported files (any DAW), all from the same start | `hypnomix vocalign LEAD.wav PART.wav …` | new files next to a report |
| a saved Live set | `hypnomix alignset SET.als --guide … --parts …` | a new set: the timing as **warp markers on your own clips** |
| Live open, and you'd rather click | the **Hypnomix Align** device (`hypnomix aligndevice`) | the same as alignset, from inside Live |
| a saved REAPER project | `hypnomix alignset SONG.rpp --guide … --parts …` | a new project: **stretch markers on your own items**, pitch / formant as new takes |
| REAPER open, and you'd rather click | the **HypnoMix Align** panel (`hypnomix reaper align`) | the same as alignset on the .rpp, from inside REAPER |

Nothing overwrites your takes or your set. Every part is measured again afterwards with an independent check,
and a part that would not end up closer is left as it was.

## Timing

HypnoMix asks what the parts should line up to. It never assumes. Two answers:

- **The group's average** (`--to-average`): nobody is forced onto one lead; every part is nudged, the first
  one too. Only the parts singing the same words at the same time are compared. Word by word, a word clearly off
  the group (beyond the song's own looseness, at least 30 ms) moves 80% of the way (`--fix-strength`); every
  other word 10% (`--stack-strength`). With `--bpm` the stack is pulled 30% toward the song's own grid. Never
  more than 60 ms (`--cap-ms`).
- **One lead** (`--to-lead`): the parts follow the lead you name, and the lead itself is never moved. The lead
  is the first file (or `--guide` in a set); `--lead NAME` names another one. `--strength` says how far the parts
  go (1 = all the way, 0.7 keeps some looseness) and `--max-ms` is the largest move; `--mode gentle` gives
  smooth speed changes if a part sounds warbly.

Where the answer comes from, in this order: a flag (`--to-average`, `--to-lead`, `--lead NAME`); a preset that
follows the guide; your saved answer (`hypnomix prefs set harmony.reference=average` or `=lead`, also in the
app's Preferences; `=ask` asks every time); the **To** button in the Align device or **Line up to** in the Align
panel. With two or more parts and no answer, the command stops with one sentence that says what it needs, and
writes nothing. One part on its own follows its guide. The report's second line says what was used and why.

## Presets

`--preset NAME` is a starting point. Anything you set yourself still wins. `--list-presets` lists them.

| preset | for | what it sets |
|---|---|---|
| `gentle-stack` | harmony stacks lined up to the group's average (its own defaults, named) | worst words 80%, the rest 10%, grid 30%, cap 60 ms |
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
hypnomix vocalign Lead.wav Dbl.wav Harm.wav --to-average --pitch 0.35 --chords "Song instrumental.wav"
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
hypnomix vocalign Lead.wav "Dbl L.wav" "Dbl R.wav" --to-lead --formant "Dbl L.wav=0.4" --formant "Dbl R.wav=-0.4"
```

- `--formant SEMIS`: the voice's character moves, the pitch doesn't. +0.3 to +0.8 sounds smaller and brighter;
  negative amounts sound bigger and darker. Opposite small amounts on two doubles widen a stack without more takes.
- `--transpose SEMIS`: the pitch moves, the character stays.
- `--formant-at 62-70`: only inside these ranges. For every part, or one part by file name (`NAME=SEMIS`).

## In a Live set: alignset

```bash
hypnomix alignset "Song.als" --guide "Lead Vox" --parts "Double" "Harmony Hi" --to-average --bars 33-49 --bpm 106
hypnomix alignset "Song.als" --guide "Lead Vox" --parts "Double" "Harmony Hi" --to-average --bars 33-49 --bpm 106 --apply
```

1. Each track is rendered from the saved set exactly as Live plays it (clip gain, fades, warps).
2. The same engine plans the moves, renders previews (`<track> (stack aligned).wav`) and checks them.
3. With `--apply`, the planned moves become **warp markers on the part's own clips** in
   `Song (aligned).als` next to yours: the fewest markers that follow the plan within half a millisecond.
   Unwarped clips get warp switched on (Complex Pro, playing exactly as before) unless `--keep-unwarped`.
   Looped clips are skipped (unroll them first: `hypnomix unroll`). Where the plan would play audio backwards
   (two neighbouring words moved opposite ways across a short gap, as the gentle stack mode does on harmonies),
   the map is eased instead of the clip being skipped: the mean of the closest forward and backward paths that
   never play slower than 0.25x (`alignset.MIN_SPEED`). Everywhere else the markers still follow the plan, and the
   `ALIGNSET.md` row gives the largest change in ms ("eased by up to … ms"). A clip that starts at its file's first
   sample and is asked to play earlier starts there and catches up the same way (counted in the same figure).
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
2. Select the guide track → **Guide ←**. Select each part → **+ Part**. (A track name that starts with a dash is
   refused with a message: rename the track.) Click **To** until it says what the parts should line up to:
   **To: average** (every part is nudged toward the group's average timing, the guide too) or **To: guide** (the
   parts follow the guide, which is never moved). **To: ?** means not chosen: with two or more parts, Align asks
   you to choose first. An answer saved in Preferences is where the button starts.
3. Loop-brace the bars → **Range: brace** (or **Range: song**).
4. Optional: brace a bit you love → **Protect**. Put the playhead on a consonant that must land → **Sync here**.
5. Drag the dials: **Tight**, **Pitch** (off by default), **Vibrato**, **Formant**. Or click **Preset**.
6. **Align**: measures and makes previews; the lanes show each part before (grey) and after (amber).
7. Happy? Switch **Write set** on and **Align** again, then **Open set**. **Place** puts pitch/formant files on
   new tracks.

The device is new: its script is tested against a simulated Live set, and the alignment it drives is tested
on real sets, but it has not been loaded in Live yet. If something misbehaves, the Max window says which line.

## In REAPER: alignset on a .rpp, and the HypnoMix Align panel

```bash
hypnomix alignset "Song.rpp" --guide "Lead Vox" --parts "Harmony 1" "Harmony 2" --to-average --bars 11-21 --bpm 64 --apply
hypnomix reaper align          # the panel (needs `hypnomix app` running)
```

Every option is the same as for a Live set. The differences (`hypnomix/studio/alignset_rpp.py`):

1. Each track is rendered from the saved project as REAPER plays its items (item and take volume, fades,
   playrate, stretch markers already there), without fader or plug-ins.
2. Timing becomes **stretch markers on the active take of the part's own items** (`rpp_edit.set_stretch`; REAPER's
   `SM take-time source-time + …`, the source time including the take's offset, as `SetTakeStretchMarker` saves
   it). Existing stretch markers are followed, and replaced by the combined map. Where the plan would play audio
   backwards (two neighbouring words moved opposite ways across a short gap), the map is eased: the mean of the
   closest forward and backward paths that never play slower than 0.25x of the item's current speed. Where it
   wants audio from before the file starts (an item that begins at the file's first sample, pulled later), the
   item starts at the first sample and catches up at no less than 0.25x: the same rule as Live's alignset. The
   report gives the largest change.
3. Pitch / formant (and timing, with `--takes`) become a **new active take on each item**
   (`rpp_edit.add_take(offset=0, rate=1)`), playing a file made for that item: the part's final render divided by
   the items' own gain and fades (each item gets its share where items crossfade), so played through the item it
   sums back to exactly the checked render. The original take stays.
4. `Song (aligned).rpp` is written next to yours (`(aligned 2)` and on if it exists), then checked against yours
   with `rpp_edit.check` (every track, item position and length, folder and send kept; only takes added). A
   project that fails is renamed `… (FAILED check).rpp`.

The panel is a `gfx` window run by the bridge (`bridge.lua` `align_where`, `panel_open mode=align`, `align_draw`)
and `hypnomix/reaper/align.py`, which sends the same request to `/api/align/*` as the Live device. Measured in
REAPER 7.86 on a real stack: stretch markers land exactly on the plan in varispeed (median 0.00 ms, 90% 0.12 ms);
with pitch kept, REAPER's stretch engine plays moved words about 4 ms late (median 4 ms, 90% 9 ms; identical in
REAPER's élastique modes); new takes play the checked render within 0.4%.

## For an AI agent

- Ask before pitch matching: it's off by default, and the person's own tuning rules apply (gentle, chord check).
- Ask what the parts line up to before any stack alignment, and pass the answer (`--to-average` or `--to-lead`,
  with `--lead` / `--guide` naming the lead). Never choose for the person; skip the question only when
  `hypnomix prefs` shows `harmony.reference` saved as `average` or `lead`. Keep the moves gentle either way.
- Fixes go on the person's own comp clips (alignset), not rendered replacements, unless they ask for files.
