# Mastering with hypnomix

`hypnomix master` turns a finished stereo mix into a release master with free DSP written in this repo. The classic
chain (sub clean-up, optional reference tone match, glue, mono low end, width, warmth, limiter to a loudness target,
codec-safe ceiling, top and tail) is described in `hypnomix master -h`. This page covers the optional stages and the
tools around them. Every one of them is **off unless you ask for it**, every one has fine controls, and every move
is written to the notes with a plain-words "why".

Always start with a plan: `hypnomix master MIX.wav --plan [options]` changes nothing and lists each stage as a
finding (same review as everything else: `hypnomix review`, then `hypnomix fix DIR --approved`). The approved run
reads the optional stages' settings back from the plan, so what you approved is what runs.

Measured is not heard. For each stage below, "how to hear it" says where to listen. Compare at matched loudness
(the louder version always sounds better for the first few seconds).

---

## Intensity: `--amount 0..100`

**What.** One control that scales every move: EQ and tone moves, glue, warmth, width changes, the optional stages'
cuts and boosts, the clipper, and the loudness the limiter adds (`--target` is approached by that share of the
distance). 100 = the chain as set; 50 = half of every move; 0 = only the safety ceiling (the file comes out as the
mix, except peaks above `--ceiling`).

**When.** When a plan sounds right in direction but too much. Easier than turning ten knobs down.

**How to hear it.** Render 100, 60 and 30 of the same plan and A/B them at matched loudness on the loudest chorus.

## Tonal targets: `hypnomix tonal`

**What.** A curve with a range at every frequency, built from songs: your own released masters and/or references
you choose. Each song is measured on its loudest ~45 s, at matched loudness, as 1/3-octave levels and as 8 named
bands, lined up on its own 250 Hz-4 kHz average (so only shape counts, never level).

```bash
hypnomix tonal build mine1.wav mine2.wav mine3.wav --name mine          # your sound
hypnomix tonal build --ref a.wav b.wav --name genre --spread std --k 1   # records you pick
hypnomix tonal build mine1.wav mine2.wav --ref a.wav --ref-weight 0.5 --name blend
hypnomix tonal check MIX.wav --target mine            # report + PNG; proposals only
hypnomix tonal list
```

**Options.** `--spread minmax` (range = lowest to highest of the songs, the default) or `std` (average ± `--k`
standard deviations); `--margin` (smallest half-width, 1 dB); `--ref-weight`. `check`: `--toward edge|mean`
(propose moving to the range edge, or to its average), `--max-db` (3), `--min-db` (0.5), `--amount`.

**When.** Before mastering, to see where a mix leaves your own sound; after, to check the master landed inside it.
Three to six songs make a useful range; one song gives only its curve ± the margin.

**How to hear it.** The PNG shows where the mix leaves the shaded range. Listen to that frequency region in the
loudest section against one of the songs the target came from.

Targets live in `~/.hypnomix/tonal/` (or `$HYPNOMIX_HOME/tonal/`). Code that wants a meter can call
`hypnomix.ears.tonal.target_bands(name)` and measure audio with `tonal.measure(y, sr, loudest=False)`.

## Tonal stabilizer: `--stabilize TARGET`

**What.** A slow dynamic EQ toward a tonal target. Per band, the short-term level (over `--stabilize-window`
seconds, default 3) is lined up the same way the target is. While it sits inside the target's range, nothing moves.
When it leaves, the band's gain moves toward the range edge (or the average with `--stabilize-toward mean`), never
more than `--stabilize-max-cut` (3 dB) or `--stabilize-max-boost` (2 dB), with a time constant of
`--stabilize-speed` seconds (2). Quiet passages and silence are left alone. `--stabilize-bands third` uses 30
1/3-octave bands instead of the 8 named bands (finer, more moves).

**When.** A song whose sections drift away from your sound (a dull verse, a chorus whose low-mids pile up), where a
static EQ would fix one section and spoil another.

**How to hear it.** The notes list each band's range of movement and how much of the time it moved. Listen at the
section changes: the move should feel like the mix staying itself, not like an EQ sweeping.

## Dynamic EQ: `--dyneq "freq:thresh:ratio:q[:range],…"`

**What.** Bells that turn down only while their band is above a threshold. `thresh` is the band's RMS level in dBFS
(the notes print each band's 95th-percentile level so you can set it), `ratio` how hard (2 = half of the overshoot is
removed), `q` the width, `range` the deepest cut (6 dB). `--dyneq-attack` (10 ms) and `--dyneq-release` (150 ms).
Below the threshold the audio passes untouched. `k` works in frequencies: `3k:-30:3:2`.

**When.** One note of the bass booms, a vocal gets sharp only when it is belted, a guitar's 300 Hz builds up only
when it is doubled.

**How to hear it.** Loop the loud moment and toggle the band (render with and without). The quiet parts must sound
identical.

## Harshness: `hypnomix harsh FILE` and `--harsh`

**What.** Finds sustained build-ups between 2 and 6 kHz (`--harsh-range`) relative to the bands around them: each
2/3-octave band is compared with the bands an octave below and above, judged against the song's own usual balance,
and only in loud moments. A moment counts when a band sits more than `--harsh-thresh` dB (6) over its usual place
for at least 0.25 s. `hypnomix harsh FILE` lists the moments with timestamps and changes nothing. `master --harsh`
turns down only those moments: `--harsh-depth` dB of cut per dB over the threshold (0.7), at most `--harsh-max` (4).

**When.** A mix that tires the ears on loud playback or bright earbuds, where a static cut would dull the whole song.
A bright song is not "harsh" by this measure (that is a tone choice: EQ or `tonal`).

**How to hear it.** Jump to the timestamps the report lists. Listen there on earbuds at a high level, then at the
same spot in the master with `--harsh`.

## Multiband width: `--width-bands "lo:hi:amount,…"` and `--mono-below HZ`

**What.** Side (L-R) level per frequency range: `200:800:0.8` narrows the low-mids 20 %, `6000:16000:1.2` widens the
top 20 %. Edges crossfade over 1/6 octave. Only the side signal is scaled, so anything in the centre (vocal, kick,
bass) is untouched. `--mono-below HZ` makes everything under HZ mono, replacing the automatic check at 120 Hz.

**When.** A wide pad clouding the centre, a top end that feels narrow next to your references, a stereo sub.

**How to hear it.** Sum the result to mono (`hypnomix translate`): widening that falls apart in mono shows there.
The notes print the L/R correlation before and after; under about +0.2 is risky.

## Limiter modes: `--limiter-mode clean|punch|loud`

**What.** All three reach the same loudness target on true peaks.

- `clean`: the limiter alone (look-ahead, true-peak detection). The most transparent when it works under ~2 dB.
- `punch`: an oversampled clipper with a narrow (1.5 dB, `--clip-knee`) knee before the limiter shaves the tallest samples of each
  hit, so the limiter does at most `--clip-db` dB (default 3) instead of ducking the whole mix around every kick.
  Drums keep their snap. (A pure hard clip, and a 1 dB knee driven hard, left measurable clicks on a real mix; 1.5 dB
  removed them.)
- `loud`: an oversampled soft clipper (3 dB knee) into the limiter, `--clip-db` default 1. Denser, louder for the same
  limiting, more harmonics.

Every mode writes a **loudness vs damage** line: LU gained over the mix, crest factor before and after (how many dB
of peaks were traded), how many samples went through the clipper, the limiter's average reduction, and for punch and
loud the clean limiter's numbers at the same target, for comparison.

Clipped peaks are rebuilt by lossy encoders as overshoots: with punch or loud, the codec-safe check often lowers the
ceiling (on one test song from -1 to -2.1 dBTP). The notes say when it does.

**When.** `clean` first. Try `punch` when a loud target makes the drums flatten or the mix pump; `loud` when you
want the density and accept the colour.

**How to hear it.** Same target, three renders, matched loudness: listen to the snare and kick in the loudest chorus,
and to the cymbals for crunch (too much clipping). Fewer than ~0.1 % of samples clipped is usually inaudible.

## Dither: `--dither tpdf|shaped|off`

**What.** Every 24-bit export and the 16-bit CD copy are rounded with dither: `tpdf` (triangular, ±1 LSB, flat
spectrum, the default), `shaped` (the same inside a first-order error-feedback loop: the noise moves up toward the
top octave, where hearing is least sensitive), or `off` (plain rounding; only for files that will be processed again).
The CD copy is made from the unrounded master, so it is dithered once, not twice. Other tools keep their own
behaviour (16-bit files dithered, 24-bit not) unless they pass `dither=`.

**When.** Always on for release files. `shaped` for 16-bit masters of quiet, dynamic music.

**How to hear it.** You shouldn't, at normal levels. On a long fade-out turned up loud, undithered 16-bit sounds
grainy; dithered sounds like a soft, steady hiss.

## Rebalance a finished mix: `hypnomix rebalance`

**What.** Turns vocals, drums, bass or "other" up or down in a stereo file. The mix is split into stems
(`hypnomix separate`, the ml extra) or you give stems you have with `--stems DIR`. Each stem's change is added on
top of the mix, so whatever the separation missed stays where it was, and with every gain at 0 dB the output is the
mix (the report prints the error of that identity, and how much of the mix the stems leave unexplained). The result
is true-peak safe: `--safety gain` (turn the file down to `--ceiling`) or `limit`; `--keep-loudness` matches the
mix's loudness first.

```bash
hypnomix rebalance MIX.wav --vocals +1.5 --bass -1
hypnomix rebalance MIX.wav --stems "stems/Song" --drums +1 --keep-loudness
```

**When.** The mix bounce is all you have and the vocal is a dB too low. It is a rescue, not a remix: separation is
imperfect, and big moves (over ~3 dB) also move its leakage and artefacts.

**How to hear it.** A/B with the mix at matched loudness. Listen for watery cymbals and a ghost of the vocal in
quiet passages.

## Codec preview: `hypnomix translate --preview`

**What.** Writes what the streaming encoders hand back, decoded to WAV so any player (and the review page) can play
it: MP3 320, AAC 256, and "as Spotify plays it" (the AAC decode turned to -14 LUFS the way its default
normalisation does: louder songs turned down, quieter songs up only as far as -1 dBTP allows). Same length and start
as the original. Code can call `hypnomix.engineer.translate.codec_preview(path, outdir)`.

**When.** Before release, on the master. A master that is much louder than -14 LUFS shows here what loudness bought:
the same level as everything else, with less punch.

**How to hear it.** A/B the original against "as Spotify plays it", then against a reference at the same level.

---

## Order of the chain

sub clean-up → reference tone match → tonal stabilizer → dynamic EQ → harshness → glue → mono low end → width →
multiband width → warmth → clipper (punch / loud) → limiter (codec-safe ceiling) → top and tail → dither on export.

## Known limits

- The stages run offline on files. `hypnomix chain` (building the chain in Live from stock devices) does not build the
  new stages yet. To master by ear inside Live instead, HypnomixMain on Main builds an editable rack of Live's own
  devices, matches the Limiter to your loudness target and saves your chain as a template (docs/LIVE.md, section 5).
- The harshness measure is a measurement, not a judgement: a bright hi-hat pattern entering can count. Listen at the
  timestamps before approving `--harsh`.
- Separation quality limits `rebalance`; the identity is exact only because the residual is kept.
- The spectral stages use 2048-point frames (46 ms at 44.1 kHz): fast moves are smoothed by design.
- Time: on a 4-minute song the classic chain takes about 40 s; every spectral stage adds 5-15 s, and punch / loud
  add the clipper to each limiter pass (about 1.5-3 minutes in all with the codec-safe check).
- The codec-safe check lowers the ceiling at most 3 dB, keeps the attempt whose encodes peak lowest, and warns when
  the encodes still overshoot: then lower `--target` or go back to `clean`.
