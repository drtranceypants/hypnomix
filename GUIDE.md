# The HypnoMix guide

How to get from a recording to a released song, the craft behind each step, and which command does it. Read it top to bottom once; after that, jump to the section you need.

1. [The workflow at a glance](#1-the-workflow-at-a-glance)
2. [Recording: get it right at the source](#2-recording-get-it-right-at-the-source)
3. [Editing and prep: the boring part that makes mixes sound expensive](#3-editing-and-prep)
4. [Mixing: balance, then tone, then dynamics, then space](#4-mixing)
5. [Mastering: loud enough, safe everywhere](#5-mastering)
6. [Release checks](#6-release-checks)
7. [Working inside Live](#7-working-inside-live)
8. [Numbers cheat sheet](#8-numbers-cheat-sheet)
9. [Feel, tempo and variety](#9-feel-tempo-and-variety)
10. [Your own standards](#10-your-own-standards)

---

## 1. The workflow at a glance

```
record ──► prep ──► (align vocals / match clips) ──► mix ──► master ──► translate + qc ──► release
  │          │                 │                       │        │              │
soundcheck  prep          vocalign, clipmatch,      automix   master        translate, qc
takes                     align                     masking
```

Starting from an unfinished song or a pile of raw takes? Do a first pass before anything else: `hypnomix prefs`
once, then `hypnomix scan` (a Live set, a REAPER project, a HypnoMix Studio session, or a folder of recordings from any
DAW), review the list, and `hypnomix fix` applies only what you approve. What it cannot change in your DAW comes
back as a checklist in your DAW's words (`hypnomix handoff`). See [docs/WORKFLOW.md](docs/WORKFLOW.md).

New to audio? The app's **Teacher** tab (`hypnomix app`) is a free course in your own DAW (Live, REAPER or HypnoMix Studio):
the complete course from what sound is to releasing a song, a 101 crash course, or a tour of HypnoMix. No AI needed.
No song of your own to practise on? `hypnomix demo` writes a 40-second song with six labelled problems.

From a folder of stems to a checked master in one go:

```bash
hypnomix automix "Night Drive stems/" --name "Night Drive" --reference "reference.wav"
hypnomix translate "hypnomix-out/automix/Night Drive/Night Drive (master).wav" --render
hypnomix qc "hypnomix-out/automix/Night Drive/Night Drive (master).wav"
```

Everything lands in `hypnomix-out/` in the folder you run from (set `HYPNOMIX_OUT` to change it). Every tool writes a Markdown report next to its audio.

---

## 2. Recording: get it right at the source

No plug-in fixes a bad recording as well as moving the mic does.

**Gain.** In 24-bit, record with peaks around **-12 to -6 dBFS**. There's no benefit to recording hot: the noise floor of a 24-bit converter is far below anything you'll hear. Clipping at the converter is permanent.

```bash
hypnomix soundcheck --list                          # find your interface
hypnomix soundcheck --device "USB Audio" --channel 2 # play the loudest part for 15 s (any part of the device name works)
hypnomix soundcheck --watch --device "USB Audio"     # live meter while you set the preamp
```

Soundcheck tells you how many dB to turn the preamp up or down. It also flags a noise floor that's too high (fans, a dirty cable, a preamp turned up on a quiet source) and mains hum at 50/60 Hz (ground loops, single-coil pickups near screens).

**Mic placement in one paragraph.** Closer gives more bass (proximity effect), less room and more isolation. Further gives a more natural tone and more room. Pointing a mic off-axis darkens it. If you record a part across several days, mark the mic position and preamp setting: `clipmatch` can fix differences later, but it can't fix a different room.

**Recording in Live without the mouse:**

```bash
hypnomix live inputs "Gtr"                 # what inputs exist
hypnomix live input "Gtr" "Ext. In" "2"    # route interface input 2
hypnomix live arm "Gtr" 1
hypnomix live monitor "Gtr" auto
hypnomix live record 17 8 3                # bars 17–24, three passes → three takes
```

Live 12 keeps every pass as a take lane.

**Picking the take:**

```bash
hypnomix takes "Vox take 1.wav" "Vox take 2.wav" "Vox take 3.wav" --bpm 92
```

You get the best whole take, plus a comp list naming the best take for each 4-bar section and what was wrong with the others: clipped samples, pitch drift in cents, timing in ms off the grid, noise. The numbers find problems; you pick the performance. A slightly pitchy take with feeling usually wins.

---

## 3. Editing and prep

Junior engineers in a studio spend hours on this before a mix starts. `hypnomix prep` does it in seconds and logs every fix. Check the files first, so a bad export is caught before it costs you an hour:

```bash
hypnomix preflight "raw stems/"     # read-only: mixed sample rates, stems of different length, duplicates, fake stereo, missing files
hypnomix prep "raw stems/"
```

| step | what it fixes | why it matters |
|---|---|---|
| format | one sample rate, 24-bit, every file the same length from the same start | stems drop into any DAW at bar 1 and line up |
| DC and rumble | offset, sub-25 Hz junk | wasted headroom; compressors react to energy you can't hear |
| declip | rebuilds flattened waveform tops | clipped takes sound harsh, and compression makes it worse |
| declick | pops, ticks, edit clicks, mouth clicks | it predicts each sample from its neighbours; only isolated spikes the instrument couldn't have made are repaired, so drum hits and consonants are left alone |
| plosives | the low "thump" of p and b on vocals | removes only the burst's low end, only during the burst |
| breaths | loud breaths between vocal phrases | turned down 8 dB, not cut: no breaths at all sounds robotic |
| hum and hiss | 50/60 Hz hum, steady noise | only when the quiet parts are actually noise, never on drums |
| silence | the noise between parts | 20 stems × a little noise each = a hissy mix |
| fades | every edit and both ends of the file | no clicks, anywhere |
| mono | stereo files whose L and R are identical | true mono pans properly and halves the CPU |
| gain staging | about -20 LUFS while playing, peaks below -3 dBFS | plug-ins behave as designed, and faders sit near 0 dB |
| names | `01 Kick.wav`, `02 Snare.wav` … | mix order: drums, bass, music, vocals |

Flags: `--keep-levels` keeps your rough balance, `--no-breaths`, `--no-silence`, `--no-noise`.

**Hiss on one track that matters (a vocal recorded in a noisy room):**

```bash
hypnomix dehiss "Lead Vox.wav" --reduce 12 --gate 18 --report
```

Two gentle stages. First, a spectral reduction learns the hiss from the quietest moments and lowers only the bins near hiss level, by at most `--reduce` dB, smoothed across time and frequency so it never "chirps". Second, a look-ahead gate fades the gaps by `--gate` dB, opening 20 ms before each note and closing slowly so tails decay naturally. Use `--gate 0` on parts whose room sound you want to keep.

**Stems straight from a Live set:**

```bash
hypnomix render "Song.als" --group "Vocals" --tighten 35
hypnomix render "Song.als" --group "Vocals" --sources "hypnomix-out/dehiss" --tighten 35   # with cleaned sources
```

This renders each track from bar 1 with clip gain, clip fades and warping applied, without opening Live. It finds moved files the way Live does. `--tighten 35` silences each clip outside its performance (where the hiss lives). Clips warped with more than two markers are rendered as a straight stretch, and HypnoMix warns you when that happens.

**Doubles and harmonies:**

```bash
hypnomix vocalign "Lead.wav" "Double.wav" "Harmony hi.wav" --trim-tails --level -6
```

Tight stacks are what make vocal productions sound expensive. vocalign matches the *timing* of each word to the lead using features that don't depend on pitch (loudness envelope, onsets, consonant energy), so a harmony a third above aligns just as well as a unison double. It then re-times the overdub with a pitch-preserving method, so the pitch and formants don't change. `--trim-tails` fades overdub word endings that ring past the lead's (stacked "s" sounds are the classic giveaway). The report shows the timing difference before and after: under ~10 ms reads as one voice, 20–40 ms as a natural double.

**Clips recorded on different days:**

```bash
hypnomix clipmatch "Verse 1.wav" "Verse 2.wav" "Chorus.wav" --ref "Verse 1.wav"
hypnomix clipmatch --als "Song.als" --track "Lead Vox"            # report only
hypnomix clipmatch --als "Song.als" --track "Lead Vox" --apply    # set Clip Gain in the open set
```

Loudness is matched while the part is sounding, not over the silence between phrases. Tone differences are measured after loudness and reported as EQ Eight moves: a low shelf for proximity effect, a high shelf for an off-axis or distant mic.

**A vocal that stays even, line to line:**

```bash
hypnomix vocallevel "Song.als" --heard "solo exports/"        # each vocal track exported solo, as heard
```

It checks that the vocal does not drop away or jump out from one lyric line to the next, and that the upper harmonies sit under the melody. Run it in the first pass and again before every final export: restored comps, re-tuned notes and fader moves made since can change it. `--apply NEW.als` writes the fixes as volume automation into a new set.

**Two mics on one source:**

```bash
hypnomix align "Kick In.wav" "Kick Out.wav" "Kick Sub.wav"
```

This finds the polarity and the offset in samples, and reports how much low end comes back once it's fixed. A few dB is common: two mics fighting is the most frequent cause of a thin kick or acoustic guitar.

---

## 4. Mixing

The order that works: **balance → tone → dynamics → space**. Most mixing problems are balance problems in disguise.

```bash
hypnomix automix "prepped stems/" --name "Song"           # prep runs first by default
hypnomix balance "prepped stems/"                         # or only a first fader balance, as proposals (faders only)
```

### What automix does, and the rule behind each move

**Roles.** It reads each stem's name first (kick, snr, bass, gtr, keys, vox, bv, pad …), then the sound. Name your stems: it's the single best thing you can do for the result.

**Clean-up EQ.**
- *High-pass* every part that has nothing useful down low: vocals at ~90 Hz, guitars ~90 Hz, hats ~300 Hz. Low-frequency rubbish from ten tracks adds up to mud and steals headroom from the kick and bass.
- *Resonances* are narrow peaks that ring through the whole song (room modes, drum rings, a cheap mic). automix only cuts a peak that's present in most of the song. A peak that comes and goes is a note being played, not a resonance.
- *Mud* (200–500 Hz) on vocals, guitars, keys and snare when it's well above the part's mids. Wide, gentle cuts.
- *Harshness* (2.5–5 kHz) when it's well above 1–2.5 kHz: the ear is most sensitive there.

**Tone EQ, only where the audio needs it.** Kick weight at 60 Hz and click at 4 kHz (so it's heard on phones), boxiness cut at 380 Hz. Bass harmonics around 800 Hz (so the bass line survives small speakers). Vocal air shelf at 10 kHz and presence at 3 kHz. Pads tucked under the vocal at 2.5 kHz.

**Compression, set by result, not by threshold.** Each role has a target amount of gain reduction (vocal ~5 dB at 3:1, bass ~5 dB at 4:1, drum bus ~2 dB at 2:1), and the threshold is found to hit it. Slow attacks let transients through (punch); fast attacks control them. The vocal gets a split-band de-esser after compression, because compression and air EQ both make esses louder.

**Balance by loudness while playing.** Levels are set from each part's loudness *while it is sounding* (silence between phrases doesn't count), against a role balance: lead vocal on top, kick about 3 dB under, bass and snare ~4 dB under, guitars and keys ~7, pads ~12. This is the biggest single factor in whether a mix sounds "right".

**Panning.** Kick, snare, bass and lead in the centre. Doubled guitars, backing vocals and keys spread in pairs. Files named L/R go to their side. Stereo stems keep their image; bass and kick keep their low end mono.

**Masking.** After the first balance, automix looks for frequency fights: two parts, same band, same time, similar level. The less important part gives way with a 2–3 dB cut. The low end always belongs to kick and bass, and the lead vocal is never the one that gets cut. Check what's left with:

```bash
hypnomix masking "hypnomix-out/automix/Song/prepped stems/"
```

**Space.** One shared plate (1.8 s, 25 ms pre-delay) for most parts puts everything in the same room. The pre-delay keeps words clear of their own tail. Kick and bass stay dry.

**Drum bus.** All drum stems are glued with 2:1, 30 ms attack and 100 ms release, ~2 dB, so the kit moves as one instrument.

### Read the notes, then disagree

`MIX NOTES.md` lists every move with its reason. Listen on headphones and a phone, and change what your ears disagree with. Most often that's vocal level (genre-dependent) and reverb amount (taste).

### Rebuild it in Live

`recipe.json` describes every move in Live's terms: EQ Eight bands, Compressor, Utility gain, pan, send. In Claude Code, ask: *"Rebuild this automix in my open set from recipe.json."* Claude creates the tracks and loads the devices through the Ableton MCP, then dials in exact values with `hypnomix live paramd`. You get the same mix, made of your own devices, ready to tweak.

---

## 5. Mastering

```bash
hypnomix master "Song mix.wav" --target -14
hypnomix master "Song mix.wav" --target -14 --reference "reference.wav" --match 0.6
hypnomix master "Song mix.wav" --warmth 0.3 --cd          # gentle saturation, plus a 16-bit/44.1k copy
```

The chain, in order:

1. **Subsonic high-pass at 22 Hz.** Energy no speaker plays still eats limiter headroom.
2. **Reference tone match (optional).** A linear-phase EQ moves your tonal balance part of the way (`--match`, default 60%) toward a reference, capped at ±3 dB. Your mix keeps its character but sits next to the reference in a playlist.
3. **Glue compression.** 1.5:1 with a slow attack, about 1.5 dB. The mix breathes together; more than ~2 dB becomes an effect.
4. **Mono low end** below 120 Hz, only if the low end is wide. Stereo bass cancels on mono speakers and makes the limiter work harder.
5. **Saturation (optional).** Harmonics that make bass audible on small speakers.
6. **True-peak limiter to the loudness target.** It searches for the input gain that lands exactly on the target, with 4× oversampled peak detection.
7. **Codec-safe ceiling.** It encodes AAC 256 and MP3 320 test copies. If they overshoot, it lowers the ceiling and limits again. Lossy encoders rebuild the waveform, and dense masters clip after encoding even when the WAV doesn't.
8. **Top and tail.** Silence before the first note trimmed to 50 ms, a 3 ms fade-in, and a fade-out if the song ends abruptly.

**Mastering inside Live with stock devices.** The same decisions, built as a real device chain on the Main track that you can tweak:

```bash
hypnomix chain master "Song bounce.wav" --target -14 --verify --existing bypass
```

| HypnoMix stage | Live device | settings |
|---|---|---|
| subsonic + reference tone | EQ Eight | band 1 low cut 12 dB/oct at 22 Hz; bands 2–7 low shelf, bells and high shelf fitted to the reference curve |
| glue | Glue Compressor | 2:1, 30 ms attack, 0.2 s release, threshold set for ~1.5 dB of gain reduction |
| mono low end, width | Utility | Bass Mono on at 120 Hz (Live 12), Width |
| warmth | Saturator | drive in dB, 35% dry/wet |
| loudness | Limiter | gain to the target, codec-safe ceiling, true peak on where available |

`--verify` records the loudest 8 bars from Live through BlackHole, measures them against the offline master, and trims the Limiter gain until they match. Nothing is deleted: `--existing bypass` switches off what was on Main (a third-party limiter, say), and a mixer snapshot is saved first. `hypnomix chain strips recipe.json` does the same per track for an automix: EQ Eight, Compressor and Utility on each track named after a stem, plus pan and send.

**Choosing a loudness.** Spotify, YouTube, Tidal and Amazon play everything at about -14 LUFS; Apple Music at -16. A louder master is simply turned down, keeping only the squashed dynamics. -14 is the safe default. Go louder only if your genre's references are louder *and* you've compared at matched volume.

**Watch the limiter line in the notes.** "Avg dB when it does" under ~2 dB is transparent. 3–6 dB starts to flatten drums. More than that means the mix needs work (usually the kick, snare or bass peaking far above everything else). Pushing the master harder won't help.

---

## 6. Release checks

```bash
hypnomix translate "Song (master).wav" --render
hypnomix qc "Song (master).wav"                 # --for cd | vinyl
```

**translate** shows how the song survives elsewhere:
- **Mono fold-down:** how much is lost, and in which band.
- **Phone, earbuds and car simulations:** compared at equal loudness. `--render` writes them so you can listen.
- **Streaming normalisation:** how many dB each platform will turn it down or up.
- **Encoding:** whether MP3 and AAC copies clip.

**qc** is the pass/fail list a mastering engineer runs before delivery: format, leading and trailing silence, cut-off endings, clicks at the start, DC, clipped runs, true peak, loudness, dynamic range, phase, low-end mono, L/R balance, codec peaks. It exits with code 1 if anything fails, so it can gate a script.

**Packaging and comparing.**

```bash
hypnomix release "Song (master).wav" --title "Song" --artist "Me" --art cover.jpg --check   # read-only first
hypnomix release "Song (master).wav" --title "Song" --artist "Me" --art cover.jpg           # the folder you upload
hypnomix versions --stems "Song stems/" --vocals "Lead*,Harm*" --mix "Song (master).wav"    # instrumental, a cappella, TV mix, radio edit
hypnomix compare "Song (bounce 1).wav" "Song (bounce 2).wav"                                # is the new bounce better than the last?
hypnomix album "Song 1.wav" "Song 2.wav" "Song 3.wav"                                       # do the songs of a record sit together?
```

`release` writes a new folder with your master as a 24-bit WAV (untouched), a dithered 16-bit WAV, MP3 320 and AAC 256 with tags and cover, and a report that measures every file, including the true peak after the lossy ones are decoded. `versions` makes the other versions from your own exported stems (no separation) and checks the stems add up to your mix. `compare` says in plain words what changed between two bounces, with level-matched A/B clips of the spots that differ most. `album` puts the songs side by side (level, tone, the gap between each pair) and writes a report first; any change is a finding you approve.

---

## 7. Working inside Live

HypnoMix talks to Live through AbletonOSC (bundled, patched: exact dB readout, master and return tracks, clip gain, localhost only). Run `hypnomix doctor` to see what's connected.

**Ground rules:**
- `hypnomix live snapshot` before changing anything; `hypnomix live restore <file>` to undo.
- Setting an automated control overrides its automation. Check with `hypnomix automation list Song.als`, and run `hypnomix live reenable` after edits.

**Mixer and plug-ins:**

```bash
hypnomix live tracks
hypnomix live db "Lead Vox" -3.5
hypnomix live send "Lead Vox" A 0.25
hypnomix live devices "Lead Vox"
hypnomix live params "Lead Vox" "TDR Nova"
hypnomix live paramd "Lead Vox" "EQ Eight" "1 Frequency A" 2500   # set what Live displays: Hz, dB, ms
```

Live shows HypnoMix (and its own automation lanes) a limited set of parameters for large plug-ins. `hypnomix install --plugin-params` raises the limit to 128 via `Options.txt` (restart Live), or click the plug-in's Configure button and touch the parameters you want.

**The A/B loop**, the most useful habit in mixing:

```bash
hypnomix loop --bar 49 --bars 8 --ab "db Bass -1.5" --revert
```

This plays the section, records it, applies the change, records it again and prints the difference (loudness, bands, width, low-end mono), then puts the mix back. For compressors and limiters, compare the two takes with `hypnomix punch A.wav B.wav` (transient punch, pumping, added harmonics, all at matched loudness). Close calls: run them twice, since the noise is about ±0.3 dB.

**Find who owns what in an unfamiliar mix:**

```bash
hypnomix diagnose "Song.als" "Song bounce.wav"
```

**Your sound as a reference.** Build a profile from finished songs you love (yours or anyone's):

```bash
hypnomix profile build song1.wav song2.wav song3.wav song4.wav song5.wav
```

`loop` and `audit` then flag anything outside your usual range, and so does `scan` when you give it `--mix` (`--no-profile` leaves that out).

### In REAPER, and in HypnoMix Studio

The same loop works on a REAPER project, with REAPER open: `hypnomix scan "Song.rpp"`, review, then
`hypnomix fix DIR --approved --out "Song (fixed).rpp"` writes what you approved into a new project (fades, rides,
word edges, track names and order; tuned vocals as new takes on your own items). For the master,
`hypnomix reaper start` and `hypnomix chain master MIX.wav --reaper --verify` build the chain from REAPER's own
plug-ins and land it on your loudness target. Every change in REAPER is one undo step. The full walk-through is
guide 8, `docs/guides/08-inside-reaper.md`.

For a HypnoMix Studio session (`.ardour`; the wiki article "HypnoMix Studio" says what that is), `hypnomix scan "Song/"` and `hypnomix project "Song/"` read it the same way, and
`fix` writes approved fades, gain, dips and fader, pan and mute moves into one new `.ardour` snapshot beside it. That
snapshot is written and re-read by HypnoMix and has not yet been opened in a released DAW, so open it in a DAW that reads `.ardour` sessions and look first. Whatever
else belongs in the session comes back as a checklist: `hypnomix handoff "<scan folder>"`.

---

## 8. Numbers cheat sheet

| what | target | why |
|---|---|---|
| Recording peaks (24-bit) | -12 … -6 dBFS | headroom for the loud take; noise is irrelevant at 24-bit |
| Noise floor between notes | below -60 dBFS | above -50 is audible once compressed |
| Stems going into a mix | ~-20 LUFS while playing, peaks ≤ -3 dBFS | plug-ins behave; faders near 0 |
| Pre-master mix | ~-18 LUFS, peaks ≤ -3 dBFS | room for the master chain |
| Master for streaming | -14 LUFS integrated, ≤ -1 dBTP | matches platform playback, codec-safe |
| Limiter reduction | under ~2 dB transparent, 3–6 dB audible | more means fix the mix |
| Vocal stack timing | under 10 ms tight, 20–40 ms natural double | above that, flams |
| Low end below 120 Hz | L/R correlation > 0.9 | mono-safe, club-safe, vinyl-safe |
| Silence at the head | under 0.5 s | playlists add their own gaps |

---

## 9. Feel, tempo and variety

A grid is a tool, not a target. Players push choruses, lay back in verses and never hit two 16ths the same
way, and that is most of why a recording feels alive. The tools here tidy what distracts and leave the rest.

**Fix only what sticks out.** `hypnomix timing` works out the song's own grid first (straight 16ths, triplets
or a mix), measures how loose the band is as a whole, and flags only hits that disagree with the other
players. Downbeats are held tightest. Fixes go in passes: the drums first, then the bass toward the corrected
drums, then everything else toward the band as it now is. Each fix is a few warp markers you can drag or
delete (or a moved note, for MIDI). A hit inside a looped clip can be fixed on that one pass only
(`--unroll-loops`).

**Tighter, on request.** `hypnomix tighten` is a partial quantise for one take: hits within a few milliseconds
stay put, the rest move a share of the way (half by default). It refuses a full snap. Listen to the preview
with and without the click before you write a set.

**No click? Map it.** `hypnomix tempomap TAKE.wav --click CHECK.wav` follows the beat and plays it back to you
as a click. When the click sits right, choose: `--conform` puts the take on Live's steady grid (markers on bar
lines keep the feel inside each bar), `--follow` leaves the take alone and makes Live's tempo follow it, so
everything you overdub breathes with the drummer. `hypnomix loops` then offers the steadiest, best-joining
loops in the take, grouped by groove.

**Recorded to a click, and it shows?** `hypnomix breathe` adds what a band does without thinking: a percent
or two faster into the big sections, a little slower in the quiet ones, a glide between. Hear it first on your
bounce with `--preview`. Mind two things: unwarped clips will not follow a tempo change, and the song's length
changes.

**When eight bars repeat for two minutes.** Three sources of variety, all offered as options you switch on:
`variations` (spare takes of the same part that fit the loop), `borrow` (clips the song's first project had and
the rework dropped) and `motion` (filter sweeps, reverb swells, delay throws and drop-outs on the effects the
set already has, in the lengths and depths of your own automation). Full details: [docs/TEMPO.md](docs/TEMPO.md)
and [docs/WORKFLOW.md](docs/WORKFLOW.md).

## 10. Your own standards

Good defaults are someone else's taste. HypnoMix can measure yours:

```bash
hypnomix prefs                                        # asked once: targets, protected tracks, what is deliberate
hypnomix profile build "song1.wav" "song2.wav"        # your sound as measured ranges
hypnomix taste "Finished 1.als" "Finished 2.als"      # levels, pans, sends, chains, what you automate
hypnomix voices --learn "Finished 1.als" …            # how far your harmonies sit under the lead, and apart
hypnomix motion --learn "Finished 1.als" …            # the effect moves you draw, their length and depth
```

What you do the same way every time becomes a standard the tools keep to. What varies from song to song
becomes a question they ask. `hypnomix prefs learn` adds what you approve and skip in each review. All of it
is plain files in `~/.hypnomix/`.
