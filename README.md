# hypnomix

**A mixing and mastering engineer for Ableton Live and REAPER, driven by you or by Claude Code.**

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
| Finding the hit that's late | detects the song's own grid, locks the bass to the drums first, compares each hit with the band, nudges only clear outliers, part of the way, drums first, then bass, then the rest (audio and MIDI; one pass of a loop can be nudged on its own) | `timing`, `tighten`, `unroll` |
| Tuning a vocal note by note | measures the song's real tuning and key by section; moves only each note's centre; checks the chord under every note and asks when the target clashes with it or the key is unsure | `tune`, `key` |
| Lining up doubles and harmonies | word by word: only the words clearly out of time move; presets, protected areas and sync points; optional pitch matching (harmonies keep their interval, chord checked) and formant for width; in a Live set, warp markers on your own clips, or from the Hypnomix Align device | `vocalign`, `alignset`, `aligndevice` |
| Balancing a harmony stack | lists the parts, asks which one leads, turns down only what overshadows it, by your own spacing, judged as heard after each track's effects and written as volume automation | `voices`, `cliplevel` |
| Chasing hiss, hum, breaths, "s" sounds | de-hiss, de-hum, breaths down (not off), de-ess with a list of every "s", clipped peaks rebuilt | `prep`, `dehiss`, `deess`, `breaths` |
| Finding what's distorting | clipped takes, hot drive, hard limiting, too-fast bass compression, each with a setting to try | `distortion` |
| Sidechains and ducking | measures depth and recovery, proposes settings; vocal reverb and delay that step back for the words | `sidechain`, `duck` |
| Naming, ordering and tidying 40 tracks | names by sound, working order, each harmony on the track for its pitch; switched-off old takes retired after an archive copy, one instrument on one track | `name`, `order`, `tidy` |
| Checking every compressor and gate | plays each track through its own chain and judges every stock device by what it actually does: barely working, squashing, releasing too fast; suggests threshold, attack and release for the part and tempo | `devices` |
| A take played without a click | follows the beat, click check for your ears, then warp to the grid or let the grid follow; best loops lined up | `tempomap`, `loops` |
| A looped song that feels static | tempo that breathes, effect moves in your own style, unused takes and loops on switched-off tracks | `breathe`, `motion`, `variations`, `borrow` |
| Working out which parts clash | which two parts fight over which frequencies, and the cut that fixes it; mic phase | `masking`, `align`, `stems` |
| Getting loud without wrecking it | a measured mastering chain, test-encoded so it won't clip after upload; offline or built in Live | `master`, `chain` |
| The pre-release checklist | phone, car and mono checks, streaming loudness, true peak, section-by-section balance | `translate`, `qc`, `sections`, `match` |
| Measuring every track while you play | a Max for Live probe last on each track measures it after all its plug-ins; one play of the song is a deep scan, no renders or exports | `probe` |
| Hearing each fix with your real chain | every fix as a switched-off B inside Live: A / B / Blind, loudness-matched; or offline renders through your own VST3/AU plug-ins | `abset`, `plugrender`, `ab --plugins` |
| Learning how you mix | reads every set on your computer: your standards, your taste calls, and where you could improve (with the evidence) | `taste --library` |
| Mastering to your sound | target tone ranges from your own releases; stabilizer, dynamic EQ, width by band, limiter character, harshness, dither, an overall amount; rebalance a finished mix; hear it as MP3/AAC | `tonal`, `master`, `harsh`, `rebalance`, `translate --preview` |
| Deciding 140 findings | amounts per fix, the same decision for the ones like this, a question budget, why each technique, notes and a collaborator's review merged; every version kept and undoable | `review`, `fix --decide-like`, `history` |
| Re-checking after every change | a quick scan in seconds, only the tracks you changed, or on every save | `scan --quick`, `scan --since`, `watch` |

What stays yours: the playing, the sounds, the effects, the arrangement and every taste call. It learns your
habits from your own finished songs (`taste`, `voices --learn`, `motion --learn`, `profile`) and from what you
approve and skip (`prefs`), so proposals start from your standards.

## No terminal, no AI: the app and the Live device

```
hypnomix app        # a web app on your own computer: choose a song, hear each fix, approve, apply
hypnomix device     # optional: a Max for Live device to step through the findings inside Live
hypnomix probe device # optional: HypnomixProbe (every track) and HypnomixMain (Main): meters, what each track is,
                      #   the song card (genre, key, chords, loudness), record and review before export
hypnomix abset DIR    # optional: every fix as a switch in Live: A / B / Blind on the device (docs/LIVE.md)
hypnomix aligndevice  # optional: Hypnomix Align, a Max for Live device to align a vocal stack (docs/ALIGN.md)
macapp/build.sh     # optional: build your own Hypnomix.app (a Dock icon around the same web app)
```

The app runs the scan, builds the before / after clips, shows the review with play buttons, and writes only
what you approved into a new set. Every other command is on its Tools screen with a form. The device sits on
any track in your Live set, shows the finding you are on, and moves Live to it: track selected, playhead and
loop brace on the spot, clip open. See [docs/APP.md](docs/APP.md).

### The Assistant: chat with an AI inside the app, your own key

No Claude Code needed. Open the app's **Assistant** tab, choose a provider, paste a key, and talk about your
song: "do a first pass on this set", "what does the review say about the vocals?", "apply what I approved".
The assistant runs hypnomix for you and explains each finding.

- **Any provider:** Claude (Anthropic), OpenAI, Google Gemini, OpenRouter (many models on one key), Groq,
  Mistral, any other service with an OpenAI-compatible address, or a free model running on your own computer
  in Ollama (no key at all). **List models** shows what your key can use.
- **Your key and your audio stay with you:** the key is kept in `~/.hypnomix/ai.json` (readable by you only) and
  sent only to the provider you chose. The assistant reads hypnomix's text reports, not the audio.
- **Listening (optional, off by default):** switch it on and a cloud model can *hear* a bounce and give notes by
  ear with timestamps (arrangement, energy, balance, vocal clarity, low-end feel), checked against hypnomix's own
  measurements. Use a Google Gemini key (free tier at aistudio.google.com) or an OpenRouter key; your chat model
  can stay whatever you like. Each listen shows the song, its length and rough cost, and waits for **Send it**.
  Only a reduced mono copy goes out (Gemini hears 16 kHz mono anyway), at about 25 tokens a second: a 4-minute
  song is around a cent. It can't judge stereo width, air or exact loudness by ear; those stay hypnomix's numbers.
- **Nothing changes without your click:** reading, scanning and measuring run straight away. Anything that
  writes a set (an `--apply`, `fix --approved`, an `.als` output) shows the exact command with **Run it /
  Don't**. Every write is still a new set next to the original.
- **With the Live device loaded**, it can point Live at a finding (track selected, playhead and loop there).

```
pip install "hypnomix[assistant]"     # the two official SDKs it talks through
hypnomix app                          # then open the Assistant tab
```

## First pass on a new song

```
hypnomix prefs                                   # once: your targets, protected tracks, how you like to review
hypnomix scan "Song.als" --mix "Song.wav"        # every check at once; changes nothing
hypnomix scan "Song.rpp"                         # or a REAPER project (REAPER can stay open)
hypnomix scan "Song/"                            # or an Ardour session folder (or its Song.ardour)
hypnomix scan "raw takes/"                       # or a folder of recordings / stems from any DAW
#   → REVIEW.md: clicks, cuts, spikes, timing, vocal pitch, distortion, sidechains, loudness, noise…
hypnomix ab     <scan folder>                    # before/after clips for each fix, level-matched
hypnomix review <scan folder> --serve            # a page: play A and B, click approve / skip / change
hypnomix fix  <scan folder> --decide smooth-3=approve,timing-7=skip      # or record decisions by hand
hypnomix fix  <scan folder> --approved --out "Song (fixed).als"          # apply only what you approved
```

**REAPER:** `hypnomix project Song.rpp` shows what is in a project (folders, items, takes, plug-ins, automation)
and `--render` renders its tracks without opening REAPER. `scan` on an `.rpp` checks missing files, item edges and
comp cuts, spikes, item edges that cut into a word, vocal pitch and doubles, plug-ins, the source recordings,
boosted noise and automation, and names default-named tracks and puts them in working order.
`fix … --out "Song (fixed).rpp"` writes what you approved into **one new project**: item fades, volume eases at
comp cuts and dips over spikes (as track volume automation), item edges opened to give a word back its first
consonant, track names and order (folders and sends kept), and tuned vocals as **new takes** on your own items,
so the original take is one click away. Checked against REAPER 7.86's own renders.
`hypnomix reaper start` runs a small bridge inside the REAPER that is open (nothing is installed; every change is
one undo step), and `hypnomix chain master BOUNCE.wav --reaper --verify` builds the mastering chain on REAPER's
master from stock plug-ins only (ReaEQ, ReaComp, ReaLimit, JS Mid/Side for a clean bass-mono), then has REAPER
render the song and trims it to your loudness target and true-peak ceiling. The REAPER guide:
`docs/guides/08-inside-reaper.md`; how it works underneath: `docs/REAPER.md`.

**Ardour:** the same for an Ardour session (Ardour 3 to 9): `hypnomix project "Song/"` lists tracks, buses,
regions, plug-ins and automation, `--render` plays the regions the way Ardour layers them (upper regions cover
lower ones, with their own fade curves and gain envelopes), and `scan` runs the same checks as on an `.rpp`.
Project changes are listed for you to make in Ardour for now.

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
| `vocalign` | Timing for doubles and harmonies, pitch untouched. With a stack (2+ parts) it works **word by word**: each word sung together with other parts is measured against them (onset cross-correlation); only the clearly-off words (beyond the song's own looseness, at least 30 ms: `--fix-over-ms`) move most of the way (`--fix-strength 0.8`), every other word barely (`--stack-strength 0.1`), each word as a whole with the change in the gap before it; the report names the problem areas. Gentle: nobody is forced onto one lead; each part moves halfway (`--stack-strength`) toward the group's average timing, and with `--bpm` the whole stack is pulled 30% (`--grid`) toward the song's 8th-note grid, never more than 60 ms (`--cap-ms`), and only where a part sings the same words at the same time as another (`--same-words 0.6`, onset correlation); a part on its own line, and every stretch that doesn't move, keeps its original audio sample for sample. `--to-lead` aligns every part to the lead instead. Every result is measured again with an independent check (onset envelopes, per 2 s) and a part that would not end up tighter is left as it was; with both engines available it keeps whichever measures better. **Presets** (`--preset natural-double`, `tight-pop`, `loose-folk`, `rap-doubles`, `gentle-stack`), **protected areas** (`--protect 1:02-1:10`, kept sample for sample) and **sync points** (`--sync 1:31.2`, lined up exactly, measured to a fraction of a millisecond). **Pitch matching** (`--pitch 0.35`, off by default): a double's notes move toward the guide's, a harmony keeps its interval and only loses the drift; as gentle as `tune` and the chord under every note is checked first. **Formant / transpose** (`--formant "Dbl L.wav=0.4"`) for a wider stack. `alignset` does it all inside a saved Live set and writes the timing as warp markers on the parts' own clips in a new set (within 1.5 ms of the checked preview on a real song); the **Hypnomix Align** device (`aligndevice`) runs it from inside Live. See [docs/ALIGN.md](docs/ALIGN.md). |
| `tune` | Natural pitch correction for a vocal take. Finds every sung note and moves only its centre to the nearest semitone in the **song's** tuning (measured from `--ref MIX.wav`, not assumed A=440), so vibrato, scoops and slides stay as sung. The key only settles notes sung near a quarter-tone; `--guide LEAD.wav` settles harmony notes toward a consonant interval, and every part locked to the same grid matches the others. Extremely gentle by default: `--amount 0.35` (how far to pull), notes within `--tolerance` 20 cents untouched, never more than `--max` 25 cents moved (no note becomes another), undecidable notes flagged rather than changed. **Chord check (default):** before any note moves, the chord the instruments play under it is read from `--chords INSTRUMENTAL.wav` (the song without vocals; else the `--ref` mix). A note whose nearest semitone clashes with that chord while the other neighbour fits it (B sung sharp over a C chord: C was likely meant) is left as sung and listed as ASK with the chord and the suggestion; you answer with `--note-answer 0:15.32=C`. Flagged notes carry the chord's suggestion too. Correcting without a chord source is refused (`--no-chord-check` to override); `scan --backing INSTRUMENTAL.wav` passes it on, and `fix` lays the chords into each take's own time through the comp clips. Rubber Band (formants kept) shifts each phrase, but only the notes that move are spliced in (±20 ms, 10 ms crossfades): everything else stays the original take bit for bit (97% of a real harmony take). Output lines up with the input sample-for-sample and keeps float overs. Writes a note-by-note report and a pitch plot. From a Live set, `fix` tunes the take files under a track's comp clips (one `--key`) and points those clips at the tuned takes in the new set: the comp stays the person's own clips, natively in Live, and no rendered copy of the track is made. On a real harmony: median 25 → 6 cents off, notes within ±15 cents 30% → 83%, syllable timing unchanged (median 0 ms). |
| `clipmatch` | Evens out clips recorded at different gain or mic positions: loudness and tone. Works on files, or on a track in your Live set, where it can set each clip's Clip Gain directly. |
| `takes` | Ranks takes by clipping, noise, hum, pitch and timing, and writes a comp list: the best take for each section. |
| `soundcheck` | Listens to your interface input and tells you how to set the preamp before you record. `--watch` gives a live meter. |
| `cleanup` | Demo rescue: hum, steady noise, rumble, DC, silence. |
| `dehiss` | Spectral de-hiss plus a smart gate for one track: learns the hiss from the quietest moments, turns down only the frequency bins that sit at hiss level (smoothed so it never sounds watery), and fades the gaps with look-ahead so note attacks and tails stay natural. The gate has hysteresis and a 150 ms hold, so soft note tails can't make it chatter (which sounds like crackle). |
| `voices` | Balances vocal harmonies around the part **you** choose. Run it with the stems first: it lists the parts (usual note, level, how long they sing together) and asks. Then `--anchor lead|lowest|highest|TRACK` (left as it is), `--reduce above|below|both`, `--above-db` / `--below-db` per step (0, 1, 1.5, 3, 4.5, 6 or any value), `--spread ladder|flat`, `--max-cut`: only turns parts down, bar by bar, where they sing together, into balanced copies. Spacing can also be stated: `--root-step 4 --upper-step 5.5` (the lowest harmony is the basis, the next one up 4 dB under it, higher ones 5.5 dB under it), saved as your default with `voices --confirm`. The suggested setting is `--tame`: harmonies stay a little under the lead (at least 1.5 dB, `--lead-margin`), a higher part more than 1.5 dB louder than the part below it (`--tolerance`) comes down to that edge, the lead is never turned down, and it reports where the harmonies sit at one level (no space between them); nothing goes further unless you choose a step size. With raw renders, `--fader NAME=dB` compares the parts as heard; better, `--set SET.als` measures each part after its track's compressors and fader (loudness per window, BS.1770) and `--apply-set NEW.als` writes the spacing as track volume automation, which comes after the chain and lands exactly. Where the parts above would need more than the cut limit, the lowest harmony comes up instead (`--root-raise`, never closer to the lead than the margin). It reports the spacing it actually achieved. `--split` re-arranges the stems into Voice 1 (lowest) … Voice N (highest) so one fader per voice sets each step of the stack; the voices add up to the inputs exactly. Use post-chain stems (Live: Export → All Individual Tracks). |

**Live: hands on the set** (through a patched [AbletonOSC](https://github.com/ideoforms/AbletonOSC), bundled)

| command | what it does |
|---|---|
| `live` | Faders in exact dB, sends, pans, mute and solo; any device or VST/AU parameter, raw or in displayed units ("2.5 kHz", "-3 dB"); transport; snapshots; input routing, arming, monitoring and punch recording with take lanes. |
| `loop` | Plays bars, records them, measures them, and compares with the previous take and your profile. `--ab "db Lead -2" --revert` for one-change A/Bs. |
| `diagnose` | Solos each group in the loudest section of a song: who owns the sub, the bass and the vocal band. |
| `probe` | Max for Live meters on every track, after their plug-ins: loudness (BS.1770), peak, 8 bands, width, low-end mono, ten times a second with the bar. Each probe says what its track is, its priority and whether it is protected; HypnomixMain on Main carries the song card and records Main for a review before export. `probe listen` / the app's Live tab turn one play of the song into a review. See docs/LIVE.md. |
| `abset` | One new set with every proposed fix next to what you have, switched off (a copy of the changed device, or a muted copy of the track): the Hypnomix device switches A / B / Blind instantly with every plug-in, loudness-matched from the probe on Main. |
| `plugrender` | Renders tracks from a set offline through their real VST3/AU plug-ins, restored from the state Live saved (optional `plugins` extra, pedalboard). Live's Utility, Compressor, Glue and Limiter are modelled; other devices are named as skipped. `ab --plugins` previews device fixes through the chain. |

**Session files** (a saved `.als`, with Live open or closed; every change goes into a new set)

- `render` turns tracks in a `.als` into full-length stems without opening Live (clip gain, clip fades and warps baked in, warped clips stretched **without changing pitch** like Live does; `--sources` swaps in cleaned files, `--tighten` silences the hiss around each clip's performance).
- `name` names every track and group by how it sounds: drums, kick, bass, guitar (notes that die away), strings (held notes, steady tone), lead vocal and harmonies (moving vowels), keys, pads; text clues from names, files and presets first; unsure tracks become "Instrument" and are listed for you; `--apply` renames them in the open set, `--undo` puts them back.
- `motion` keeps repetitive sections alive before the final mixdown: it learns the effect moves you draw by hand (`--learn` your finished songs) and offers risers, low-pass dips, slow filter drifts, reverb swells, delay throws, outro washes, drum stutter rolls, gate chops and drop-outs on the sends, filters and racks the set already has, each an option with fine controls (length, depth, dB, pattern), written as automation or clip slices in a new set.
- `devices` checks every Live device on every track by what it actually does to that track's audio (rendered from the set and played through the chain in order): compressors and Glue (reduction while the part plays, squashing, releases faster than the bass notes, attacks that clamp drum transients; a suggested threshold fitted to the usual amount for that kind of part, with attack and release for the part and the tempo), gates (threshold against the noise floor and the phrases), limiters on tracks, and missing low cuts on parts that aren't bass. Third-party plug-ins are skipped (their settings aren't readable); suggestions are options, written to a new set when approved. `duck` keeps the vocal reverb and delay out of the way of the words: for each reverb or delay return the vocals send to, it measures the ducking you already have (from the vocals, rendered from the set) and proposes a re-tune when it barely ducks, ducks too hard or doesn't let go in the gaps, or proposes adding a sidechained Compressor at the end of the return, fed by the vocal group (Post FX), ratio 4, ~1 ms attack, ~205 ms release, threshold fitted to about 3 dB while the singer sings (reverbs lighter); options only, part of the vocals scan.
- `cliplevel` finds clips of the lower harmonies sitting well under the rest of their track (more than 4 dB, as heard with the fader) and offers clip-gain raises up to the track's usual level, never closer than 1.5 dB to the lead, never applied unless approved (the vocals scan proposes them).
- `borrow` offers loops the song's original project had and the new version no longer plays (MIDI and audio, Arrangement or Session view) as layers on new switched-off tracks; a MIDI loop is the window that already sits in the song's groove, only where its notes fit the section's scale, nudged as a whole so its first note lands with the song's downbeats.
- `order` puts tracks in working order (drums, bass, keys/guitar/synth, vocals, other melodic; lowest to highest pitch inside each, groups as blocks) and, in a vocal stack, moves each part onto the track for its pitch so one fader sets one voice (level kept with clip gain; comped clips are listed by hand); on by default in the first pass, `hypnomix prefs set cleanup.order=off` to opt out.
- `tidy` retires switched-off tracks (old takes, replaced originals, copies: removed, or `--mode bottom` to move them down renamed "old: …") after writing a full "(archive, all takes)" copy, and consolidates one instrument's clips onto one track where two neighbouring tracks sound the same (same devices, sends, pan, output; fader difference made up with clip gain). Clips may overlap only where the overlap is silence: one clip is then cut back to the other's edge, and only when the part cut off renders under `--silence-db` (-55 dBFS), so no sound is overwritten; on by default in the first pass (`cleanup.retire=off` / `cleanup.consolidate=off` to opt out). Afterwards `check --allow-removed` treats the retired and merged tracks as expected.
- `edges` finds clip edges and fades that cut into a word. Main check: **consonants**. Each take is rendered with its edges opened and the track as it plays. An "s", "sh" or "t" (a 30-300 ms run where 3.5-10 kHz is within 25 dB of the take's own high-band peak and dominates the sound) that the comp plays 6 dB or more down is flagged, but only where the comp goes on with the word right after it; where the comp leaves the word out, adding its first consonant would leave a stray "s". Fixes, in order: shorten the fade that eats it; move the start to 10 ms before it (trimming a clip that ends right there and any muted clip under it); move a comp switch later when a take sings the consonant across it. They are re-checked until clean, then render-compared: a change is undone if the peak rises more than 2.5 dB beyond what it restores (two takes doubling). It also lists long fades that duck the start of a word, and sound running across a clip edge (listen-only). Switched-off comp originals are checked too. It runs in the scan's `clips` group.
- `check NEW --against OLD` matches tracks by id: a new order or new names (from `order`, `name`) are reported as info, not errors.
- `timing` first detects the song's grid from where the hits land, bar by bar (straight 16ths, 8th- or 16th-note triplets, or a mix; conservative: straight unless triplets are clearly there, triplet sections of 2+ bars), so a triplet is never nudged onto a 16th; then it finds instrument hits (audio and MIDI: drum racks and synth bass too; a MIDI fix moves the note, and a note in a looped clip only if it is off the same way on every pass, while one that is identical on every pass is marked as probably a programmed feel). The low end comes first: bass is checked against the drums on every beat and downbeat with a tight tolerance (at least 12 ms) and moved 70% toward them, drums are the reference (never pulled toward the band), and bass and drum findings rank first; `--apply` works in passes: the drums first (against the other drums or the grid), then the bass measured again against the corrected drums, then everything else against the band as corrected (a hit that no longer needs a fix is skipped); a hit on a looped clip can be fixed with `--unroll-loops` (the loop becomes one copy per pass, checked to play sample for sample the same, and only the copy holding the outlier is nudged; `hypnomix unroll` does just the unrolling); optional items (melodic parts, notes that look deliberate) only with `--ids` or `--all-listed`; it finds instrument hits that are out of time with the band and nudges only those: each hit is compared with the other instruments on the same 16th (or the grid plus that player's own push/lay-back), tolerances follow the song's own looseness and are tightest on downbeats and loosest on 16ths, and `--apply` adds a few warp markers around each fixed hit in a new set (editable in Live, nothing quantized); hits too crowded to stretch cleanly are listed as needing a hand.
- `smooth` finds sudden volume jumps on Arrangement audio clips: clicks at clip edges and loop seams, level jumps where one clip cuts to the next mid-phrase (comped vocals), and short spikes such as pops and plosives; it skips drum-like tracks, switched-off tracks and repeated loop copies, and `--apply` writes a new set with short fades, quick dips and eased ramps that scale your existing automation.
- `distortion` finds audible distortion and proposes a fix for each case: in the recordings (clipped, flat-topped takes with count and bar; clicks and crackle; possible saturation, where a source's loud passages carry far more odd harmonics than its own quieter ones; aliasing; true-peak overs in renders and the mix) and in the device chains (it estimates the level hitting every device from the clip audio and each gain change before it, then flags Saturator, Dynamic Tube, Amp, Overdrive, Drum Buss and Roar driven hard, Limiters doing heavy gain reduction, compressors and limiters releasing faster than a bass cycle, Glue Compressor's Soft Clip pushed by its makeup, extreme EQ boosts and limiters stacked in series). Give it Live's individual-track export with `--post` and it confirms each finding: every audio track's clips are rendered without devices and compared with its stem. A linear path (EQ, delay, gain riding) is fitted on the quiet passages, and whatever the loud passages add beyond it is distortion. `--apply` writes only the pure parameter fixes (for example Saturator Drive 18 dB → 4 dB) to a new set in the same folder, skipping automated parameters; declipping, re-recording and new devices stay as advice. `scan()` returns the findings for scripts.
- `unroll` turns a looped Arrangement clip into one copy per pass (same sound, checked by rendering before and after), so a single pass can be nudged or changed on its own.
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
| `critique` | `hypnomix critique` (a cloud model listens and writes notes by ear; Gemini or OpenRouter key, from the app's settings or `GEMINI_API_KEY` / `OPENROUTER_API_KEY`) | `uv pip install -e ".[critique]"` |

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
