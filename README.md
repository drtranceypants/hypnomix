# hypnomix

**A mixing and mastering engineer for Ableton Live, driven by you or by Claude Code.**

Hand it a folder of raw stems and get back a cleaned, balanced, mastered song, plus notes that explain every EQ cut, compressor setting and level in plain words. Or keep your hands on your own session: hypnomix sets exact fader dB and plug-in parameters in the open Live set, records A/B loops, and measures what each change did.

Built for people who record **real instruments and vocals**, not just MIDI.

Made by **Dr. Trance**.

```
hypnomix automix "My Song stems/" --reference "song I love.wav"
```

```
prep pass (clicks, clipping, plosives, breaths, noise, silence, fades) …
  Kick          kick          (by name)
  Bass DI       bass          (by name)
  Gtr L         guitar        (by name)
  Lead Vox      lead vocal    (by name)
  …
→ My Song (automix).wav · My Song (master).wav · MIX NOTES.md · recipe.json
```

## What it takes off your plate

The slow, technical jobs get found for you, explained in plain words, and fixed only with your yes. That
leaves your time for playing, dialling in sounds and listening.

| the chore | what hypnomix does | commands |
|---|---|---|
| Hunting clicks, pops and level jumps | finds them at clip edges, loop seams and comp cuts; eases each with a short fade or dip | `smooth`, `clicks` |
| Finding the hit that's late | detects the song's own grid, locks the bass to the drums first, compares each hit with the band, nudges only clear outliers, part of the way (audio and MIDI) | `timing`, `tighten` |
| Tuning a vocal note by note | measures the song's real tuning and key by section; moves only each note's centre; asks when the key is unsure | `tune`, `key` |
| Lining up doubles and harmonies | word by word: only the words clearly out of time move | `vocalign` |
| Balancing a harmony stack | lists the parts, asks which one leads, turns down only what overshadows it, by your own spacing | `voices`, `cliplevel` |
| Chasing hiss, hum, breaths, "s" sounds | de-hiss, de-hum, breaths down (not off), de-ess with a list of every "s", clipped peaks rebuilt | `prep`, `dehiss`, `deess`, `breaths` |
| Finding what's distorting | clipped takes, hot drive, hard limiting, too-fast bass compression, each with a setting to try | `distortion` |
| Sidechains and ducking | measures depth and recovery, proposes settings; vocal reverb and delay that step back for the words | `sidechain`, `duck` |
| Naming and ordering 40 tracks | names by sound, working order, each harmony on the track for its pitch | `name`, `order` |
| A take played without a click | follows the beat, click check for your ears, then warp to the grid or let the grid follow; best loops lined up | `tempomap`, `loops` |
| A looped song that feels static | tempo that breathes, effect moves in your own style, unused takes and loops on switched-off tracks | `breathe`, `motion`, `variations`, `borrow` |
| Working out which parts clash | which two parts fight over which frequencies, and the cut that fixes it; mic phase | `masking`, `align`, `stems` |
| Getting loud without wrecking it | a measured mastering chain, test-encoded so it won't clip after upload; offline or built in Live | `master`, `chain` |
| The pre-release checklist | phone, car and mono checks, streaming loudness, true peak, section-by-section balance | `translate`, `qc`, `sections`, `match` |

What stays yours: the playing, the sounds, the effects, the arrangement and every taste call. It learns your
habits from your own finished songs (`taste`, `voices --learn`, `motion --learn`, `profile`) and from what you
approve and skip (`prefs`), so proposals start from your standards.

## First pass on a new song

```
hypnomix prefs                                   # once: your targets, protected tracks, how you like to review
hypnomix scan "Song.als" --mix "Song.wav"        # every check at once; changes nothing
hypnomix scan "raw takes/"                       # or a folder of recordings / stems from any DAW
#   → REVIEW.md: clicks, cuts, spikes, timing, vocal pitch, distortion, sidechains, loudness, noise…
hypnomix ab     <scan folder>                    # before/after clips for each fix, level-matched
hypnomix review <scan folder> --serve            # a page: play A and B, click approve / skip / change
hypnomix fix  <scan folder> --decide smooth-3=approve,timing-7=skip      # or record decisions by hand
hypnomix fix  <scan folder> --approved --out "Song (fixed).als"          # apply only what you approved
```

The scan runs every check below in parallel and writes one review list, most severe first. You (or an AI agent,
item by item with you) approve what to fix; `fix` writes only those changes into **one new set** next to the
original, then measures the new set again and tells you which problems are gone. It refuses to run if the set
changed since the scan, never overwrites a file, and won't touch tracks you marked as protected without asking
again. Every set it writes gets a structure check (`hypnomix check`) and a plain list of what changed
(`hypnomix diff`). `prep`, `automix` and `master` take `--plan`: instead of doing everything at once, each move
becomes a finding you approve or skip. Also new: `deess`, `breaths`, `sections` (loudness and vocal balance per
section) and `match` (your mix against a reference, as proposals). `prefs` remembers what you usually approve and skip, so each review starts closer to how you work.
See [docs/WORKFLOW.md](docs/WORKFLOW.md); what's coming, including Logic Pro and Pro Tools: [docs/ROADMAP.md](docs/ROADMAP.md).

## What's in the box

**Engineer: stems in, song out**

| command | what it does |
|---|---|
| `automix` | Stems → balanced mix → master. Per stem: role detection, clean-up EQ (resonances, mud, harshness), tone EQ, compression set by gain reduction, de-essing, loudness-based balance, panning, shared plate reverb, drum bus glue. Then it finds frequency fights between stems and carves the less important part. |
| `master` | Subsonic clean-up, optional reference tone match, glue compression, mono low end, true-peak limiter to a LUFS target. It test-encodes AAC/MP3 and lowers the ceiling if they would clip, then tops and tails. |
| `chain` | **No paid plug-ins needed.** Builds the mastering chain on Live's Main track from stock devices (EQ Eight → Glue Compressor → Utility → Saturator → Limiter), dials in every value from an analysis of your bounce, then records the result from Live and trims the Limiter until it measures on target. `chain strips` builds a channel strip on every track from an automix recipe. |
| `sidechain` | Makes sidechain compression sound good. Finds every Compressor and Glue Compressor in a set with its sidechain on (Glue suggestions snap to its menu values), simulates it on the trigger (audio tracks render straight from the set; drum racks and synths come from an individual-track export via `--stems`) and measures each hit: how deep it ducks, how much has come back by the next hit, how even it is, and whether the release is so short it distorts the bass's low end. Then it suggests settings for a style: `clarity` (2-4 dB, back before the next hit), `pump` (6-10 dB, back right on the next hit) or `vocal-duck` (delay and reverb returns duck under the singer and bloom in the gaps). Writes a gain-reduction plot on the beat grid and before/after previews; `--apply` writes the settings to a new set; `--glue-to-compressor` swaps sidechained Glue Compressors for Live's Compressor with lookahead (same routing, makeup and dry/wet). |
| `masking` | Which stems fight over which frequencies, how often, and the exact cut that fixes it. |
| `align` | Phase, polarity and time offset between mics on one source (kick in/out, DI + amp, snare top/bottom). |
| `translate` | Mono fold-down, phone, earbuds and car simulations, how much each streaming service turns it down, clipping after encoding. `--render` to listen. |
| `qc` | Release checklist: format, head/tail silence, cut-off endings, DC, clipping, true peak, loudness, phase, codecs. Exits 1 on failure. |

**Studio: from raw takes to mix-ready stems**

| command | what it does |
|---|---|
| `prep` | The assistant-engineer pass: rebuilds clipped peaks, repairs clicks and pops, removes plosive thumps, turns breaths down, removes hum and hiss (only where present), silences gaps with fades, fades every edge, converts dual-mono to mono, matches formats and lengths, gain-stages, names files in mix order. Every fix is logged with a timestamp. |
| `vocalign` | Timing for doubles and harmonies, pitch untouched. With a stack (2+ parts) it works **word by word**: each word sung together with other parts is measured against them (onset cross-correlation); only the clearly-off words (beyond the song's own looseness, at least 30 ms: `--fix-over-ms`) move most of the way (`--fix-strength 0.8`), every other word barely (`--stack-strength 0.1`), each word as a whole with the change in the gap before it; the report names the problem areas. Gentle: nobody is forced onto one lead; each part moves halfway (`--stack-strength`) toward the group's average timing, and with `--bpm` the whole stack is pulled 30% (`--grid`) toward the song's 8th-note grid, never more than 60 ms (`--cap-ms`), and only where a part sings the same words at the same time as another (`--same-words 0.6`, onset correlation); a part on its own line, and every stretch that doesn't move, keeps its original audio sample for sample. `--to-lead` aligns every part to the lead instead. Every result is measured again with an independent check (onset envelopes, per 2 s) and a part that would not end up tighter is left as it was; with both engines available it keeps whichever measures better. |
| `tune` | Natural pitch correction for a vocal take. Finds every sung note and moves only its centre to the nearest semitone in the **song's** tuning (measured from `--ref MIX.wav`, not assumed A=440), so vibrato, scoops and slides stay as sung. The key only settles notes sung near a quarter-tone; `--guide LEAD.wav` settles harmony notes toward a consonant interval, and every part locked to the same grid matches the others. `--amount 0.8` (how far to pull), notes within `--tolerance` 10 cents untouched, undecidable notes flagged rather than changed. Rubber Band (formants kept) shifts each phrase; output lines up with the input sample-for-sample and keeps float overs. Writes a note-by-note report and a pitch plot. On a real harmony: median 25 → 6 cents off, notes within ±15 cents 30% → 83%, syllable timing unchanged (median 0 ms). |
| `clipmatch` | Evens out clips recorded at different gain or mic positions: loudness and tone. Works on files, or on a track in your Live set, where it can set each clip's Clip Gain directly. |
| `takes` | Ranks takes by clipping, noise, hum, pitch and timing, and writes a comp list: the best take for each section. |
| `soundcheck` | Listens to your interface input and tells you how to set the preamp before you record. `--watch` gives a live meter. |
| `cleanup` | Demo rescue: hum, steady noise, rumble, DC, silence. |
| `dehiss` | Spectral de-hiss plus a smart gate for one track: learns the hiss from the quietest moments, turns down only the frequency bins that sit at hiss level (smoothed so it never sounds watery), and fades the gaps with look-ahead so note attacks and tails stay natural. The gate has hysteresis and a 150 ms hold, so soft note tails can't make it chatter (which sounds like crackle). |
| `voices` | Balances vocal harmonies around the part **you** choose. Run it with the stems first: it lists the parts (usual note, level, how long they sing together) and asks. Then `--anchor lead|lowest|highest|TRACK` (left as it is), `--reduce above|below|both`, `--above-db` / `--below-db` per step (0, 1, 1.5, 3, 4.5, 6 or any value), `--spread ladder|flat`, `--max-cut`: only turns parts down, bar by bar, where they sing together, into balanced copies. Spacing can also be stated: `--root-step 4 --upper-step 5.5` (the lowest harmony is the basis, the next one up 4 dB under it, higher ones 5.5 dB under it), saved as your default with `voices --confirm`. The suggested setting is `--tame`: harmonies stay a little under the lead (at least 1.5 dB, `--lead-margin`), a higher part more than 1.5 dB louder than the part below it (`--tolerance`) comes down to that edge, the lead is never turned down, and it reports where the harmonies sit at one level (no space between them); nothing goes further unless you choose a step size. With raw renders, `--fader NAME=dB` compares the parts as heard. `--split` re-arranges the stems into Voice 1 (lowest) … Voice N (highest) so one fader per voice sets each step of the stack; the voices add up to the inputs exactly. Use post-chain stems (Live: Export → All Individual Tracks). |

**Live: hands on the set** (through a patched [AbletonOSC](https://github.com/ideoforms/AbletonOSC), bundled)

| command | what it does |
|---|---|
| `live` | Faders in exact dB, sends, pans, mute and solo; any device or VST/AU parameter, raw or in displayed units ("2.5 kHz", "-3 dB"); transport; snapshots; input routing, arming, monitoring and punch recording with take lanes. |
| `loop` | Plays bars, records them, measures them, and compares with the previous take and your profile. `--ab "db Lead -2" --revert` for one-change A/Bs. |
| `diagnose` | Solos each group in the loudest section of a song: who owns the sub, the bass and the vocal band. |

**Session files** (a saved `.als`, with Live open or closed; every change goes into a new set)

- `render` turns tracks in a `.als` into full-length stems without opening Live (clip gain, clip fades and warps baked in, warped clips stretched **without changing pitch** like Live does; `--sources` swaps in cleaned files, `--tighten` silences the hiss around each clip's performance).
- `name` names every track and group by how it sounds: drums, kick, bass, guitar (notes that die away), strings (held notes, steady tone), lead vocal and harmonies (moving vowels), keys, pads; text clues from names, files and presets first; unsure tracks become "Instrument" and are listed for you; `--apply` renames them in the open set, `--undo` puts them back.
- `motion` keeps repetitive sections alive before the final mixdown: it learns the effect moves you draw by hand (`--learn` your finished songs) and offers risers, low-pass dips, slow filter drifts, reverb swells, delay throws, outro washes, drum stutter rolls, gate chops and drop-outs on the sends, filters and racks the set already has, each an option with fine controls (length, depth, dB, pattern), written as automation or clip slices in a new set.
- `duck` keeps the vocal reverb and delay out of the way of the words: for each reverb or delay return the vocals send to, it measures the ducking you already have (from the vocals, rendered from the set) and proposes a re-tune when it barely ducks, ducks too hard or doesn't let go in the gaps, or proposes adding a sidechained Compressor at the end of the return, fed by the vocal group (Post FX), ratio 4, ~1 ms attack, ~205 ms release, threshold fitted to about 3 dB while the singer sings (reverbs lighter); options only, part of the vocals scan.
- `cliplevel` finds clips of the lower harmonies sitting well under the rest of their track (more than 4 dB, as heard with the fader) and offers clip-gain raises up to the track's usual level, never closer than 1.5 dB to the lead, never applied unless approved (the vocals scan proposes them).
- `borrow` offers loops the song's original project had and the new version no longer plays (MIDI and audio, Arrangement or Session view) as layers on new switched-off tracks; a MIDI loop is the window that already sits in the song's groove, only where its notes fit the section's scale, nudged as a whole so its first note lands with the song's downbeats.
- `order` puts tracks in working order (drums, bass, keys/guitar/synth, vocals, other melodic; lowest to highest pitch inside each, groups as blocks) and, in a vocal stack, moves each part onto the track for its pitch so one fader sets one voice (level kept with clip gain; comped clips are listed by hand); on by default in the first pass, `hypnomix prefs set cleanup.order=off` to opt out.
- `timing` first detects the song's grid from where the hits land, bar by bar (straight 16ths, 8th- or 16th-note triplets, or a mix; conservative: straight unless triplets are clearly there, triplet sections of 2+ bars), so a triplet is never nudged onto a 16th; then it finds instrument hits (audio and MIDI: drum racks and synth bass too; a MIDI fix moves the note, and a note in a looped clip only if it is off the same way on every pass, while one that is identical on every pass is marked as probably a programmed feel). The low end comes first: bass is checked against the drums on every beat and downbeat with a tight tolerance (at least 12 ms) and moved 70% toward them, drums are the reference (never pulled toward the band), and bass and drum findings rank first; `--apply` works in passes: the drums first (against the other drums or the grid), then the bass measured again against the corrected drums, then everything else against the band as corrected (a hit that no longer needs a fix is skipped); a hit on a looped clip can be fixed with `--unroll-loops` (the loop becomes one copy per pass, checked to play sample for sample the same, and only the copy holding the outlier is nudged; `hypnomix unroll` does just the unrolling); optional items (melodic parts, notes that look deliberate) only with `--ids` or `--all-listed`; it finds instrument hits that are out of time with the band and nudges only those: each hit is compared with the other instruments on the same 16th (or the grid plus that player's own push/lay-back), tolerances follow the song's own looseness and are tightest on downbeats and loosest on 16ths, and `--apply` adds a few warp markers around each fixed hit in a new set (editable in Live, nothing quantized); hits too crowded to stretch cleanly are listed as needing a hand.
- `smooth` finds sudden volume jumps on Arrangement audio clips: clicks at clip edges and loop seams, level jumps where one clip cuts to the next mid-phrase (comped vocals), and short spikes such as pops and plosives; it skips drum-like tracks, switched-off tracks and repeated loop copies, and `--apply` writes a new set with short fades, quick dips and eased ramps that scale your existing automation.
- `distortion` finds audible distortion and proposes a fix for each case: in the recordings (clipped, flat-topped takes with count and bar; clicks and crackle; possible saturation, where a source's loud passages carry far more odd harmonics than its own quieter ones; aliasing; true-peak overs in renders and the mix) and in the device chains (it estimates the level hitting every device from the clip audio and each gain change before it, then flags Saturator, Dynamic Tube, Amp, Overdrive, Drum Buss and Roar driven hard, Limiters doing heavy gain reduction, compressors and limiters releasing faster than a bass cycle, Glue Compressor's Soft Clip pushed by its makeup, extreme EQ boosts and limiters stacked in series). Give it Live's individual-track export with `--post` and it confirms each finding: every audio track's clips are rendered without devices and compared with its stem. A linear path (EQ, delay, gain riding) is fitted on the quiet passages, and whatever the loud passages add beyond it is distortion. `--apply` writes only the pure parameter fixes (for example Saturator Drive 18 dB → 4 dB) to a new set in the same folder, skipping automated parameters; declipping, re-recording and new devices stay as advice. `scan()` returns the findings for scripts.
- Also `mine`, `audit`, `automation`, `refs`, `profile`.

**Ears:** `measure`, `key` (the song's key, section by section, with a confidence), `sections`, `match`, `spectrogram`, `punch`, `stems`, `separate` (a mix into stems), `midi` (audio to MIDI), `pitchcheck` (pitch and loudness difference between two captures: run it after any re-render), `clicks` (finds clicks and crackle). Run `hypnomix` for the full list and `hypnomix <command> -h` for each one.

**Tempo and variety** ([docs/TEMPO.md](docs/TEMPO.md))

| command | what it does |
|---|---|
| `tempomap` | Follows the beat of a take played without a click and reports the tempo of every bar. Then either warps the take onto Live's grid, or makes Live's tempo follow the take. A click check and an offline preview come first. |
| `loops` | Finds the best 1, 2, 4 and 8 bar loops in a free-played take, grouped by groove, and lines them up in Session slots to try. |
| `tighten` | A gentle quantise: hits move part of the way to the click, close ones stay put, a full snap is refused. |
| `breathe` | Small tempo changes by section for a song recorded to a rigid click, with a preview of your mix bent along the new tempo. |
| `variations` | Finds parts that loop the same bars over and over, and unused takes of the same part that fit; adds them on new, switched-off tracks next to each part. |

## Install

Needs macOS (Windows should work for the file tools and Live control but is untested), Python 3.9+, ffmpeg, and Ableton Live 11 or 12 for the Live features. The file tools work without Live.

```bash
git clone https://github.com/drtranceypants/hypnomix && cd hypnomix
uv venv && uv pip install -e .
hypnomix install
hypnomix doctor
```

`hypnomix install` copies the AbletonOSC remote script into Live's User Library and walks you through the rest. Then restart Live and choose **Settings → Link, Tempo & MIDI → Control Surface: AbletonOSC**.

To give hypnomix access to more of your plug-ins' parameters, run `hypnomix install --plugin-params`. It adds one line to Live's `Options.txt`.

`loop` and `diagnose` record what Live plays through [BlackHole](https://github.com/ExistentialAudio/BlackHole). `hypnomix install` explains the two-minute setup.

Optional features:

| extra | adds | install |
|---|---|---|
| `reference` | `hypnomix reference` (Matchering; GPL-3.0, kept separate so hypnomix stays MIT) | `uv pip install -e ".[reference]"` |
| `ml` | `hypnomix separate` (split a finished song into stems) and `hypnomix midi` (audio → MIDI) | `uv pip install -e ".[ml]"` |
| `critique` | `hypnomix critique` (a written second opinion from Gemini; needs `GEMINI_API_KEY`) | `uv pip install -e ".[critique]"` |

## With Claude Code

Open the repo in Claude Code and ask for what you want:

> "Mix the stems in ~/Music/Bounces/Night Drive. Make it sound like this reference."
>
> "I'm about to record acoustic guitar on input 2. Set up a track and check my levels."
>
> "Align the harmonies to the lead vocal and tell me what you changed."
>
> "Master this for Spotify and check it'll survive on a phone."

Six skills ship in `skills/`: **first-pass** (ask your preferences once, scan a whole song with parallel subagents, then review and apply fixes one at a time), **mix-engineer**, **mastering-engineer**, **tracking-session**, **live-mixing** and **harmony-balance** (`voices --learn` measures how far your harmonies sit under the lead and from each other in your own finished songs; `--tame` then only corrects what falls outside your habits). `agents/` holds the **hypnomix-scanner** subagent the first pass uses. They teach Claude the workflows, the safety rules (snapshot before touching your set, respect automation, ask before taste calls), and how to explain each move.

To use the skills from any project, add the repo as a plugin marketplace: `/plugin marketplace add drtranceypants/hypnomix`.

`.mcp.json` also connects the [Ableton MCP](https://github.com/ahujasid/ableton-mcp) (telemetry off), which lets Claude create tracks and load devices. Together with `hypnomix live` it can rebuild an automix inside your set from `recipe.json`.

**Other AI agents** (Codex, Cursor, Aider…): start with [AGENTS.md](AGENTS.md): setup, the loop every job follows, the safety rules, the command map and how to extend the code. [docs/LESSONS.md](docs/LESSONS.md) lists the mistakes those rules come from.

## Only free, open-source or stock tools

hypnomix never needs a paid plug-in. Its own processing is built in, and everything it does offline it can also build inside Live from the devices every Live Standard or Suite owner already has:

```bash
hypnomix chain master "Song bounce.wav" --target -14 --reference "reference.wav" --verify
```

```
| EQ Eight        | low cut 22 Hz; low shelf 90 Hz +0.8 dB; bell 550 Hz -1.8 dB; high shelf 9 kHz +1.8 dB |
| Glue Compressor | threshold -20.3 dB, 2:1, attack 30 ms, release 0.2 s                                  |
| Utility         | bass mono below 120 Hz                                                                 |
| Limiter         | gain +4.6 dB, ceiling -1.0 dB                                                          |
```

Plug-ins already on the Main track are never deleted: `--existing bypass` switches them off, `--existing keep` adds the chain after them. A mixer snapshot is saved first.

### Free plug-ins that work with hypnomix

hypnomix controls a plug-in through the parameters Live exposes for it (`hypnomix live params <track> <plug-in>`), so any VST3 or AU works the same way as a stock device. These free and open-source ones are part of the setup hypnomix is developed with:

| plug-in | type | use it for |
|---|---|---|
| [TDR Nova](https://www.tokyodawn.net/tdr-nova/) | free | dynamic EQ: resonances and harshness that come and go. **Verified:** all 256 parameters reachable from hypnomix |
| [TDR Kotelnikov](https://www.tokyodawn.net/tdr-kotelnikov/) | free | transparent mix-bus and mastering compression |
| [LoudMax](https://loudmax.blogspot.com/) | free | look-ahead mastering limiter |
| [Airwindows Consolidated](https://www.airwindows.com/consolidated/) | open source (MIT) | hundreds of small processors: saturation, console emulation, dithering |
| [CHOWTapeModel](https://chowdsp.com/products.html#tape) | open source | tape saturation and warmth |
| [Dragonfly Reverb](https://michaelwillis.github.io/dragonfly-reverb/) (Hall, Room, Plate, Early Reflections) | open source (GPL-3) | natural reverbs; the Plate matches automix's send |
| [Valhalla Supermassive](https://valhalladsp.com/shop/reverb/valhalla-supermassive/), Space Modulator, Freq Echo | free | big ambient reverbs and delays, modulation |
| [Surge XT](https://surge-synthesizer.github.io/) (Effects) | open source (GPL-3) | multi-effects, plus a full synth |
| [SPAN](https://www.voxengo.com/product/span/) | free | spectrum analyser for checking hypnomix's EQ moves by eye |
| [Youlean Loudness Meter 2](https://youlean.co/youlean-loudness-meter/) | free version | LUFS and true-peak metering in Live |
| [sfizz](https://sfz.tools/sfizz/) | open source | SFZ sampler for instrument parts |

Plug-ins with more parameters than Live shows by default need `hypnomix install --plugin-params` (or Live's Configure button) before hypnomix can reach all of them.

## How it decides

Everything is measurement plus rules an engineer would use. There are no black-box models in the mixing chain, so every decision can be written down and argued with. Read [GUIDE.md](GUIDE.md) for the craft behind each tool and the workflows.

It measures; it doesn't listen. Treat the automix as a strong first pass by an assistant, then make the taste calls yourself.

## Licence

MIT. Bundles AbletonOSC (MIT, © Daniel John Jones and contributors) with small patches marked `hypnomix patch`; see [THIRD_PARTY.md](THIRD_PARTY.md). Not affiliated with Ableton.
