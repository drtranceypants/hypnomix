---
title: Mixing, Mastering & Release
subtitle: From stems to a master that survives phones, cars and every streaming service
---

# Balance, tone, dynamics, space

The order that works: **balance → tone → dynamics → space**. Most mixing problems are balance problems in
disguise. hypnomix can do a whole mix from stems, or check and tune the mix you're building in Live, and it
writes down the reason for every move so you can disagree with it.

<!--toc-->

## A first balance: balance

```bash
hypnomix balance "Song stems/"                                 # the report: one fader move per part, and why
hypnomix balance "Song stems/" --vocal-over-band 1 --offset bass=-1.5
hypnomix balance "Song stems/" --plan                          # the moves as findings to approve
```

Start here when the faders are all at zero and you only want a first balance. `balance` measures how loud each stem plays
(while it plays, not over the gaps), works out what the part is (by its name, then its sound) and proposes **one fader
move per part**. Faders only: no EQ, no compression, no pan, no reverb (that is what `automix` adds). For every part the
report shows its role, how loud it plays, the move and where that leaves it against the anchor part (the lead vocal, or the
most important part when there is no vocal); it also shows how the lead vocal sits against the whole band together.
`--anchor`, `--vocal-over-band DB`, `--offset ROLE=DB`, `--min-move` and `--max-move` are yours to set. If you built a
profile (`hypnomix profile build`), each move is also checked against the fader range of your own finished songs.

With `--plan`, each move is a finding. Approve the ones you like, and `fix --approved` writes only those stems, each with
its move baked in, and a trial mix into `fixed/balance/` in the scan folder. It is measured, not heard: play the trial
mix and move the faders until it feels right.

> Careful: `balance`, `compare`, `album`, `versions` and `release` are new. They pass unit tests and hypnomix's own
> checks on synthetic data only, and have not yet been run on real songs. Keep your originals and listen.

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

When `masking` finds a fight you agree with, the cut can be written for you: approve the finding in a review (or run
`hypnomix masking Song.als --apply "Song (cut).als" --findings SCAN/findings.json --ids mask-1`) and the cut goes on the part
that should give way, as one bell band on its own EQ in a new file: an EQ Eight in a Live set, a ReaEQ in a REAPER project.
It is gentle (2 dB for a fight that happens less than half the time, 3 dB for more), `--scale` or the approval's amount
makes it smaller, and nothing else on the track changes. When `fix` writes it, the new file gets hypnomix's structure
check; it has not yet been opened in Live or REAPER. For a folder of stems there is no set to write into, so the cut stays on the by-hand list.

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

Before the first run: `hypnomix install` and restart Live (it adds the piece that lets hypnomix load Live's
devices), and for `--verify` install BlackHole and set Live's output to a Multi-Output Device (your speakers +
BlackHole). `--dry-run` prints the plan and touches nothing. Checked in Live 12 on a real song: the chain is
built with the planned values, and verify took Live from 6 dB under the target to on it in two passes. It plays
the loudest bars out loud while it measures.

```bash
hypnomix chain strips "hypnomix-out/automix/Song/recipe.json"      # a channel strip on every matching track
```

`chain strips` puts EQ Eight, Compressor and Utility on each track **whose name contains the stem's name**
(stem "Bass" finds the track "3-Detuned Lowpass Bass"). A stem with no matching track is listed, never
guessed: name the track after the stem and run it again.

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

## From master to release

You have a finished master. The steps from here to the files you upload go in this order, and each one only reads your
master and writes new files into new folders. Every figure is measured, not heard: play what it points at.

**1. Check it: `qc` and `translate`** (the section above). Fix anything `qc` fails before you go on.

**2. Compare with the last bounce, after every round of changes.**

```bash
hypnomix compare "Song v3.wav" "Song v4.wav" --names "v3,v4"
```

It lines the two exports up (and says so if one starts later), then writes `COMPARE.md` into
`hypnomix-out/compare/<old> vs <new>/`. The first line says in plain words what changed ("v4 is 1.2 dB louder, 1.5 dB
brighter above 8 kHz, a little narrower in the lows; the 2nd chorus-like section changed most"). Under it: loudness, peaks,
dynamics, tone and stereo width in 8 bands, each section's loudness, and the three spots where the two sound least alike
once the loudness is matched, as A / B clips in `ab/` that `hypnomix review` can play (when the two differ by more than
level). Listen to those. It stops politely when the two do not look like the same song (`--force` compares anyway) or the
sample rates differ (`--resample`).

**3. Several songs? `album`.**

```bash
hypnomix album "Masters/" --order "Song C,Song A,Song B" --suggest-order
hypnomix album "Masters/" --plan album-scan        # the proposed moves, as findings to approve
```

`qc` checks one file; `album` puts the songs side by side and writes `ALBUM.md`. It says which song sits apart in level
(a quiet ballad is allowed to be quieter, so it looks at the loudest section as well as the whole song and only calls a song
apart when both are off), which is brighter, darker or boomier than the rest and by how many dB, which is wider or narrower,
and what gap each pair of songs could have, from how the first one ends and the next one starts. `--suggest-order` lists one
or two running orders as options; they are never applied. With `--plan`, a gain trim, a gentle tonal tilt and trimmed or
padded silence become findings: `ab` plays each level-matched, and `fix --approved` writes the approved ones as new files in
`fixed/`. Play each transition with the next song queued, at one volume, and trust your ears over the figures.

**4. Other versions? `versions`.**

```bash
hypnomix versions --stems "Song stems/" --vocals "Lead*,Harm*" --mix "Song master.wav" --tv -6 --cut 1:12-1:40 --check
hypnomix versions --stems "Song stems/" --vocals "Lead*,Harm*" --mix "Song master.wav" --tv -6 --cut 1:12-1:40
```

From stems you exported yourself (no separation): an instrumental, an a cappella, a TV mix (`--tv`) and a radio edit
(`--cut`). With `--mix` it first adds the stems up and subtracts them from your master: a tiny leftover means the stems are
the mix; a big one means master-bus processing, a different level, a different start or a missing stem, and then the
versions are built from the stems, not carved out of the master. Each version is matched to the master's loudness with gain
only. `--check` prints the plan and writes nothing. The folder is `hypnomix-out/versions/<name> (versions)/` with
`VERSIONS.md`. Listen across every join of the radio edit.

**5. Package it: `release`.**

```bash
hypnomix release "Song master.wav" --title "Song Title" --artist "Artist Name" --album "Album Name" --track 1 --year 2026 \
    --art cover.jpg --check                       # read-only: the checks, the cover, the ISRC, what it would write
hypnomix release "Song master.wav" --title "Song Title" --artist "Artist Name" --album "Album Name" --track 1 --year 2026 \
    --art cover.jpg
```

It writes a new folder, `hypnomix-out/release/Artist Name - Song Title/`: your master as 24-bit WAV (a byte-for-byte copy
when it already is one), a 16-bit / 44.1 kHz WAV made from the unrounded master with the same dither `master` uses, MP3 320
and AAC 256 with the tags and the cover embedded (add `flac` to `--formats` if you want it), a copy of the cover,
`release.json` and `RELEASE.md`. The files are named "Artist Name - Song Title (24-bit).wav" and so on, and it refuses if
the folder already exists. `--check` first: the cover has to be square, at least 3000 px, JPEG or PNG, and the ISRC has to be
shaped like one. A package written with a cover that fails still says so
on the console and in `RELEASE.md`.

Read `RELEASE.md`: for every file, loudness, true peak and the release checks, and for the MP3 and AAC the true peak
**after** decoding them again, which is what a listener's player plays. If it is over 0 dBTP it says by how much and that
mastering again with the ceiling that many dB lower would fix it. It never changes the audio to hide that: it is your
decision. Open each file once before you upload.

`docs/MASTERING.md` has the same three commands (`release`, `versions`, `compare`) and `album` in more detail.

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
