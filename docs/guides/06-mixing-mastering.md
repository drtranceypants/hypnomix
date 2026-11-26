---
title: Mixing, Mastering & Release
subtitle: From stems to a master that survives phones, cars and every streaming service
---

# Balance, tone, dynamics, space

The order that works: **balance → tone → dynamics → space**. Most mixing problems are balance problems in
disguise. hypnomix can do a whole mix from stems, or check and tune the mix you're building in Live, and it
writes down the reason for every move so you can disagree with it.

<!--toc-->

## Stems in, song out: automix

```bash
hypnomix automix "Song stems/" --name "Song" --reference "song I love.wav"
hypnomix automix "Song stems/" --plan          # every move as a finding to approve, plus a trial mix
```

| stage | what it does, and the rule behind it |
|---|---|
| roles | reads each stem's name (kick, snr, bass, gtr, vox, bv…), then the sound. Name your stems: it's the best thing you can do for the result |
| clean-up EQ | high-passes parts with nothing useful down low; cuts resonances present in most of the song (one that comes and goes is a note); mud (200–500 Hz) and harshness (2.5–5 kHz) only when they stand out |
| tone EQ | only where the audio needs it: kick weight and click, bass harmonics for small speakers, vocal air and presence |
| compression | set by the result, not the threshold: vocal ~5 dB at 3:1, bass ~5 dB at 4:1, drum bus ~2 dB at 2:1; de-essing after compression |
| balance | by loudness while each part plays: lead vocal on top, kick ~3 dB under, bass and snare ~4, guitars and keys ~7, pads ~12 |
| panning | kick, snare, bass and lead centred; pairs spread; low end mono |
| masking | finds two parts fighting over one band at one time; the less important one gives way with a 2–3 dB cut. The lead vocal is never the one cut |
| space | one shared plate (1.8 s, 25 ms pre-delay) for one room; kick and bass dry |

You get the mix, the master, `MIX NOTES.md` (every move with its reason) and `recipe.json` (every move in
Live's terms). Read the notes, listen on headphones and a phone, and change what your ears disagree with. Most
often that's vocal level and reverb amount.

## Checking a mix you're building in Live

| question | tool |
|---|---|
| Which two parts fight, where, and what cut fixes it? | `masking` |
| Are my two kick mics (or DI + amp) cancelling? | `align` |
| Is every compressor and gate doing something sensible? | `devices` |
| Is my sidechain clear, pumping, or distorting the bass? | `sidechain` (styles: `clarity`, `pump`, `vocal-duck`) |
| Do the vocal reverb and delay step back for the words? | `duck` |
| What's distorting, and where? | `distortion` |
| Which group owns the sub, the bass, the vocal band? | `diagnose` |

`devices` plays each track through its own chain and judges every stock device by what it actually does:
barely working, squashing, releasing faster than the bass notes, clamping drum transients. It suggests
threshold, attack and release for the part and the tempo. `distortion` finds clipped takes, crackle,
saturation, true-peak overs and devices driven too hard, and `--apply` writes only the pure parameter fixes
(Saturator Drive 18 dB → 4 dB) into a new set.

## Hands on the open set: live and loop

```bash
hypnomix live snapshot                      # before changing anything (live restore FILE to undo)
hypnomix live db "Lead Vox" -3.5
hypnomix live paramd "Lead Vox" "EQ Eight" "1 Frequency A" 2500
hypnomix loop --bar 49 --bars 8 --ab "db Bass -1.5" --revert
```

The A/B loop is the most useful habit in mixing: it plays a section, records it, makes one change, records it
again, prints the difference (loudness, bands, width, low-end mono) and puts the mix back. Close calls: run it
twice, since the noise is about ±0.3 dB.

## Mastering: master

```bash
hypnomix master "Song mix.wav" --target -14
hypnomix master "Song mix.wav" --target -14 --reference "reference.wav" --match 0.6
```

1. **Subsonic high-pass at 22 Hz**: energy no speaker plays still eats limiter headroom.
2. **Reference tone match** (optional): part of the way toward a reference (`--match`, default 60%), capped at ±3 dB.
3. **Glue compression**: 1.5:1, slow attack, about 1.5 dB.
4. **Mono low end** below 120 Hz, only if it's wide.
5. **Saturation** (optional, `--warmth`): harmonics so bass reads on small speakers.
6. **True-peak limiter to the target**, with 4× oversampled peak detection.
7. **Codec-safe ceiling**: AAC and MP3 test copies; if they'd clip after encoding, the ceiling comes down.
8. **Top and tail**: lead-in trimmed to 50 ms, short fade-in, fade-out if the end is abrupt.

**The same chain inside Live, from stock devices:**

```bash
hypnomix chain master "Song bounce.wav" --target -14 --verify --existing bypass
```

EQ Eight → Glue Compressor → Utility → Saturator → Limiter on the Main track, every value dialled in from
your bounce. `--verify` records the loudest 8 bars from Live and trims the Limiter until it measures on
target. Nothing is deleted: `--existing bypass` switches off what was already on Main.

No bounce yet? **HypnomixMain** on Main has its own mastering chain: **Build chain** puts an editable rack of
Live's own devices (every gain at 0 dB) before it, **Match target** turns the Limiter until Main sits on the song
card's loudness, and **Save** keeps your edited chain, or a rack of your own, as a template (guide 7).

> Tip: watch the limiter line in the notes. Under ~2 dB of reduction is transparent; 3–6 dB starts to flatten
> drums; more means the mix needs work (usually a kick, snare or bass peaking far above the rest).

## Choosing a loudness

Spotify, YouTube, Tidal and Amazon play everything at about -14 LUFS; Apple Music at -16. A louder master is
simply turned down, keeping only the squashed dynamics. **-14 LUFS is the safe default.** Go louder only if
your genre's references are louder and you've compared them at matched volume.

## Release checks: translate and qc

```bash
hypnomix translate "Song (master).wav" --render
hypnomix qc "Song (master).wav"                 # --for cd | vinyl
```

| translate shows | why |
|---|---|
| mono fold-down | how much is lost, and in which band |
| phone, earbuds, car | at equal loudness; `--render` lets you listen |
| streaming normalisation | how many dB each platform turns it down or up |
| encoding | whether MP3 and AAC copies clip |

`qc` is the pass/fail list a mastering engineer runs before delivery: format, head and tail silence, cut-off
endings, clicks at the start, DC, clipped runs, true peak, loudness, dynamic range, phase, low-end mono, L/R
balance, codec peaks. It exits with code 1 if anything fails, so it can gate a script.

## Numbers cheat sheet

| what | target | why |
|---|---|---|
| stems going into a mix | ~-20 LUFS while playing, peaks ≤ -3 dBFS | plug-ins behave; faders near 0 |
| pre-master mix | ~-18 LUFS, peaks ≤ -3 dBFS | room for the master chain |
| master for streaming | -14 LUFS integrated, ≤ -1 dBTP | matches platform playback, codec-safe |
| limiter reduction | under ~2 dB transparent | more means fix the mix |
| low end below 120 Hz | L/R correlation > 0.9 | mono, club and vinyl safe |
| silence at the head | under 0.5 s | playlists add their own gaps |

## Your own standards

Good defaults are someone else's taste. Teach it yours:

```bash
hypnomix profile build "song1.wav" "song2.wav" "song3.wav"     # your sound as measured ranges
hypnomix taste "Finished 1.als" "Finished 2.als"                # levels, pans, sends, chains you use
```

What you do the same way every time becomes a standard the tools keep to; what varies becomes a question they
ask. All of it is plain files in `~/.hypnomix/`.
