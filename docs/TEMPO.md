# Tempo and variety: five tools

All five read a saved Live set (or an audio file), write only **new** files, run `hypnomix check` on every
set they write, and can be previewed without opening Live. Nothing here snaps a performance to a grid.

| you have | you want | tool |
|---|---|---|
| a take played without a click | to know its tempo, bar by bar | `tempomap TAKE.wav --click CHECK.wav` |
| | the take on Live's steady grid | `tempomap SET.als --track T --conform --apply NEW.als` |
| | Live's grid to follow the take | `tempomap SET.als --track T --follow --apply NEW.als` |
| | the best loops in it, lined up to try | `loops SET.als --track T --apply NEW.als` |
| a take played to a click, a bit loose | it tighter, still human | `tighten SET.als --track T --apply NEW.als` |
| a finished song on a rigid click | it to breathe between sections | `breathe SET.als --mix MIX.wav --preview OUT.wav` |
| a song whose loops repeat too much | variety from takes you never used | `variations SET.als` |

## The order that works

1. **Check the map by ear before anything else.** `tempomap --click` writes the take with a click on the
   beats it found. If fewer than half the beats sit on a real hit, the tool says the map is guesswork and
   refuses to write a set from it. Correct it with `--bpm`, `--half`, `--double`, `--downbeat SECONDS`.
   Which beat is "one" is a guess (a kick on 1 and 3 looks the same both ways): the person confirms it.
2. **Preview, then apply.** `tempomap --conform --preview`, `tighten --preview` and `breathe --preview`
   render the result offline (the audio stretched along the same time map, pitch unchanged). It is close
   to what Live will play, not identical: Live's own warp modes do the final stretching.
3. **Open the new set in Live and listen.** Only Live confirms that a written set opens and sounds right.

## What each one changes

- **tempomap --conform**: warp markers on the take's bar lines (or beats); the take starts on a bar line.
  Markers on bar lines keep the feel inside each bar exactly as played.
- **tempomap --follow**: tempo automation, one value per bar; the take is left unwarped. Every warped clip in
  the set follows the new tempo; unwarped clips do not.
- **loops**: adds looping clips to empty Session slots of the take's track. The Arrangement is untouched.
  Windows where the beat was filled in rather than played are never offered.
- **tighten**: a warp marker on every hit. Hits within `--keep-within` ms stay put; the rest move
  `--strength` of the way (0.1 to 0.9, default 0.5; a full snap is refused). Unwarped clips get warp
  switched on first (they play the same).
- **breathe**: tempo automation by section (at most -2% to +2.5%), with a glide into each section. Unwarped
  clips would drift, so it lists them and writes nothing unless `--warp-clips` is given. The song's length
  changes: anything cut to the old audio (a video) will no longer line up.
- **variations**: finds parts that repeat the same whole-bar loop, and unused material that fits it: other
  stretches of the same recording, and other takes of the same part in the project's `Samples/Recorded`
  that the set no longer uses (matched by the recording's name, locked to the song's tempo). Each part gets
  a new track next to it, in the same group, with the same devices, **switched off**. Turn it on to hear the
  variation over the mix; delete it to undo. `--mode replace` builds a full alternate part instead.
  Takes that do not lock to the song's tempo are reported, not used: try `loops` on them.

## For an AI agent

- These are taste tools. Offer them, do not run `--apply` unasked. Show the report and the preview files first.
- Say "measured" for fit and steadiness scores; the person decides by ear.
- Before `breathe --apply --warp-clips`, tell the person which clips will have warp switched on, and that
  exposed vocals can pick up warp artefacts.
- `tighten` and `variations` need a constant tempo; run them before `breathe`, not after.
- Not yet verified in Live (say so): every set these five write. They pass the structural check and the
  offline previews measure as intended; opening them in Live is the remaining test.

## Related tools

- `timing` (first-pass check) fixes only the hits that disagree with the band, on the song's detected grid.
  `tighten` is the whole-take version for when you want a part tighter overall.
- `borrow` offers clips from the song's original project; `motion` offers effect moves for the same
  repetitive stretches. Like `variations`, both arrive switched off or as review items.

## Limits

One time signature per take (`--bpb`). Long silences and free-time passages are bridged at the last tempo.
`variations` skips clips with bent timing (several warp markers at different speeds) and only matches spare
takes by recording name; point it at other folders with `--takes`. "Fits" is a harmony and level measure,
not a judgement of the playing.
