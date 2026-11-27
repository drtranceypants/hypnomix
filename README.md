# HypnoMix

**A mixing and mastering engineer for Ableton Live, REAPER and HypnoMix DAW, driven by you or by Claude Code.**

Hand it a folder of raw stems and get back a cleaned, balanced, mastered song, plus notes that explain every EQ cut, compressor setting and level in plain words. Or keep your hands on your own session: HypnoMix sets exact fader dB and plug-in parameters in the open Live set, records A/B loops, and measures what each change did.

Built for people who record **real instruments and vocals**, not just MIDI.

HypnoMix DAW is HypnoMix's own DAW. It is built on Ardour, a free open-source DAW under the GNU General Public License. HypnoMix DAW is not released yet. Until it is, everything written here for it is written for Ardour 8 or 9, the free DAW it is built on, and has not yet been tried in either.

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

| the chore | what HypnoMix does | commands |
|---|---|---|
| Hunting clicks, pops and level jumps | Finds clicks at clip edges and loop seams, jumps where one comped clip cuts to the next, plosives and spikes, and eases each with a short fade or dip. It also catches the opposite mistake: a fade or comp edit that cuts into a word. | `smooth`, `edges`, `clicks` |
| Finding the hit that's late | Detects the song's own grid (straight, triplets or a mix), locks the low end first (bass to the drums), compares every hit with the rest of the band, and nudges only the clear outliers part of the way. Drums go first, then the bass toward the corrected drums, then everything else. Audio gets warp markers you can still drag; MIDI drums and bass are checked too. One pass of a loop can be nudged on its own. | `timing`, `tighten`, `unroll` |
| Tuning a vocal note by note | Measures the song's real tuning and key (section by section), then moves only each note's centre. Vibrato, scoops and slides stay as sung. It checks the chord under every note, and asks when the target clashes with it or the key is unsure; those notes stay as sung until you answer. | `tune`, `key` |
| Lining up doubles and harmonies | Works word by word: only the words clearly out of time with the other parts move, the rest stay bit-exact. Optional pitch matching (a harmony keeps its interval, the chord is checked) and formant for width. In Live it writes warp markers on your own clips; in REAPER, stretch markers or new takes on your own items; always into a new set or project. The same from inside Live (the Hypnomix Align device) or from the HypnoMix Align panel in REAPER. | `vocalign`, `alignset`, `aligndevice`, `reaper align` |
| Balancing a harmony stack | Lists each part with its note and level, asks which one leads, and turns down only the parts that overshadow it, by the amount you pick or the spacing you use in your own finished songs. It is judged as heard, after each track's effects, and written as volume automation. | `voices`, `cliplevel` |
| Keeping the vocal level even, line to line | Measures the vocal as heard, one lyric line at a time: a line that drops away or jumps out, and an upper harmony louder than the melody. Run it in the first pass and again before every final export, because edits since then can change it. Fixes are written as volume automation into a new set, only if you ask: approving one in the review writes nothing by itself, `vocallevel --apply` does. | `vocallevel` |
| Chasing hiss, hum, breaths and "s" sounds | Spectral de-hiss, hum and rumble removal, breaths turned down (not off), a split-band de-esser that lists every "s" it touched, clipped peaks rebuilt. `cleanup` rescues a rough demo with the same gentle hand. | `prep`, `dehiss`, `deess`, `breaths`, `cleanup` |
| Evening out clips recorded on different days | Matches the loudness and tone of clips recorded at different preamp gain or mic distance, so a part sounds like one performance. On files, or on a track in your Live set, where it can set each clip's Clip Gain. | `clipmatch` |
| Setting your level, picking the take | Listens to your interface input and says how to set the preamp before you record, with a live meter. Afterwards it ranks takes by clipping, noise, hum, pitch and timing and writes a comp list: the best take for each section. The numbers find problems; you pick the performance. | `soundcheck`, `takes` |
| Finding what's distorting | Clipped takes, drive set too hot, limiters working too hard, compressors releasing faster than a bass note: each named with its track, bar and a setting to try. | `distortion` |
| Setting up sidechains and ducking | Measures how deep each sidechain ducks and whether it recovers in time, proposes settings for the style you want, and can make the vocal reverb and delay step back while the singer sings. | `sidechain`, `duck` |
| Naming, ordering and tidying 40 tracks | Names every track by how it sounds, puts them in working order (drums, bass, keys and guitars, vocals) and puts each harmony on the track for its pitch, so one fader is one voice. Switched-off old takes are retired after a full archive copy of the set is saved, and one instrument's clips go on one track. | `name`, `order`, `tidy` |
| Checking every compressor and gate | In a Live set, plays each track through its own chain and judges every stock device on the signal it really gets: a compressor that barely works, squashes, or lets go too fast for a bass note; a gate that chops words. It suggests threshold, attack and release for that part and tempo. | `devices` |
| Mapping a take played without a click | Follows the beat through the take, writes a click check for your ears, then either warps the take onto the grid or makes Live's tempo follow the player. It also picks the best loops and lines them up to try. | `tempomap`, `loops` |
| Making a looped song feel alive | Small tempo pushes into choruses, filter sweeps and delay throws in the style of your own automation, and unused takes or loops from the original project offered on new, switched-off tracks. Live sets. | `breathe`, `motion`, `variations`, `borrow` |
| A song that sounds the same throughout | Finds the parts that repeat themselves section after section (measured: tone and texture) and proposes a new colour for the repeat: width, grit, space, movement or an octave copy. Each is a chain of Live's own devices on a switched-off copy of the part, with a before and after clip. Live sets only for now. | `colour` |
| Working out which parts clash | Which two parts fight over which frequencies, how often, and the exact cut that fixes it, written once you approve it as a band on the part's EQ, or on a new EQ added to its chain if it has none (EQ Eight in Live, ReaEQ in REAPER). Mic pairs checked for phase and polarity. | `masking`, `align`, `stems` |
| Stems in, song out | Give it a folder of stems: it cleans them, works out what each one is, EQs, compresses, de-esses, balances, pans, adds one shared reverb and masters the result. MIX NOTES.md explains every move in plain words. With `--plan`, every move becomes a finding you approve first. | `automix` |
| A first balance of a folder of stems | One fader move per part, with the measurement behind it: its role, how loud it plays, and how the vocal sits against the band, compared with your own fader range when you have a profile. Faders only: no EQ or compression. Anchor part, vocal level and per-role offsets are yours to set. | `balance` |
| Getting loud without wrecking it | A mastering chain set by measurement, test-encoded to AAC and MP3 so it won't clip after upload, built offline or inside Live from stock devices, or as an editable rack on HypnomixMain that you save as your own template. | `master`, `chain` |
| Mastering to your sound | Target tone ranges built from your own releases or records you choose; a tonal stabilizer, dynamic EQ, width by band, limiter character, harshness taming, dither and an overall amount. Turn the vocal, drums or bass up or down in a finished mix, true-peak safe. Hear it as MP3 or AAC. Match a reference with Matchering (an extra). | `tonal`, `harsh`, `rebalance`, `reference` |
| The pre-release checklist | Phone, earbuds, car and mono checks; how much each streaming service will turn it down; silence, true peak, phase and format. Section by section: "the second chorus is 2 LU quieter than the first". Your mix against a song you love, as proposals. | `translate`, `qc`, `sections`, `match` |
| Packaging the release | One folder to upload: your master as 24-bit WAV (untouched), a dithered 16-bit WAV, MP3 320 and AAC 256 with tags and cover, and a report that measures every file, including the true peak after the lossy ones are decoded. `--check` first. | `release` |
| Instrumental, a cappella, TV mix, radio edit | From your own exported stems, no separation. Checks the stems really add up to your mix, matches each version to its loudness with gain only, crossfades the cuts of a radio edit (to bar lines with `--bpm`) and runs the release checks on every file. | `versions` |
| Is the new bounce better than the last one? | Lines the two up and says in plain words what changed: loudness, peaks, dynamics, tone and stereo width by band, each section, with level-matched A/B clips of the three spots that differ most. | `compare` |
| Making an EP or album sit together | The songs side by side in plain words: which sit apart in level (judged on the loudest section as well as the whole, so a quiet ballad may be quieter), which are brighter, darker or boomier and by how much, the gap each pair could have, and order options. Any trim, gentle tilt or silence change is a finding you approve, applied into new files. | `album` |
| Checking the files before you start | Mixed sample rates or bit depths and which file is the odd one out, stems of different length or that start apart, duplicates, fake stereo, silent or clipped files, lossy sources, missing files, names that will not travel. Report first; `prep` repairs what it can. | `preflight` |
| A second opinion by ear | A cloud AI model listens to a bounce and writes notes with timestamps, checked against HypnoMix's own measurements. It needs your own key, sends a reduced mono copy, and only when you say so: in a terminal `critique` prints the length, model and estimated cost and asks y/N, anywhere else it refuses unless `--yes`, and `--estimate` only prints. Its notes are an opinion; the numbers stay measurements. | `critique` |
| Splitting a song, or turning audio into notes | Splits a finished song into stems, or turns audio into MIDI (and into a Live clip). Both are optional extras and run on your computer. | `separate`, `midi` |
| Learning the loop on nothing of your own | A 40-second synthetic song with six labelled problems (a click, a level jump, hiss, clipped peaks, a drifting harmony, late hits), as stems or a REAPER project. The REAPER project (`demo --kind reaper`) is the one that gives the full loop: scan it, hear each fix, apply two. The folder of stems has fewer fixes you can apply. | `demo` |
| Finding every problem in a song at once | Runs every check on a Live set, a REAPER project, a HypnoMix DAW session or a folder of recordings, changes nothing, and writes one review list, most severe first. What looks deliberate (your automation, a long reverb tail) is listed as a question, never fixed on its own. | `scan` |
| Hearing a fix before you say yes | A before and after clip for every fix it can preview, level-matched, so the louder one does not win. In Live, every fix as a switched-off B next to your own device (A / B / Blind), or offline through your own VST3 and AU plug-ins. | `ab`, `abset`, `plugrender` |
| Deciding 100+ findings | Amounts per fix, the same decision for the ones like this, a question budget, why each technique, notes and a collaborator's review merged. `fix` writes only what you approved into one new set, and every version is kept and can be undone. | `review`, `fix`, `history` |
| What's left to do by hand | Turns the by-hand list into a checklist in your DAW's words, in song order, with what to listen for, and puts a marker at each spot: locators in a new Live set, markers in a new REAPER project, or a MIDI and CSV marker file for any other DAW. | `handoff` |
| Re-checking after every change | A quick scan in seconds, only the tracks you changed, or on every save. | `watch` |
| Learning how you mix | Asks your targets once, reads your own finished songs for your standards and taste calls, and shows where you could improve, with the evidence. Once you have built a profile, `scan --mix` also compares the mix with your own ranges (`--no-profile` skips it). Everything stays on your computer. | `prefs`, `taste`, `profile` |
| Knowing which plug-ins you have | Lists what is installed (VST3, Audio Units, CLAP, LV2), marks the free ones HypnoMix knows, loads each one safely (a plug-in that crashes or hangs is reported, not fatal) and keeps the list in your preferences so proposals only name what you have. | `plugins` |
| Measuring every track while you play | A Max for Live probe last on each track measures it after all its plug-ins; one play of the song is a deep scan, no renders or exports. | `probe` |
| Looking at the numbers | Loudness, true peak, bands, stereo, tempo and key as data; a spectrogram; pitch and loudness difference between two captures; transient punch and pumping at matched loudness. | `measure`, `spectrogram`, `pitchcheck`, `punch` |
| Looking inside a project, checking what was written | Tracks, folders, items, takes, plug-ins and automation of a REAPER, HypnoMix DAW or Live project without opening the DAW, and every track rendered to a full-length file. Tempo, key, routing and plug-in chains of a set; stacked limiters and bypassed devices; missing files; automation envelopes. Every set HypnoMix writes gets a structure check and a plain list of what changed. `reaper` talks to the REAPER that is open. | `project`, `render`, `reaper`, `mine`, `audit`, `refs`, `automation`, `check`, `diff` |
| Hands on the open Live set | Faders in exact dB, any device or plug-in parameter, transport, snapshots, arming and punch recording. Play bars, record, measure and compare for one-change A/Bs. Solo every group in the loudest section to see who owns the sub, the bass and the vocal band. | `live`, `loop`, `diagnose` |
| Working with no terminal | The whole first pass in a window on your own computer: choose a song, hear each fix, approve, apply. A Max for Live device steps through the findings inside Live and jumps Live to each one. | `app`, `device` |
| Getting free plug-ins and sounds | 69 free plug-ins, synths, instruments, drum kits and sample packs (68 open source), installed from their publishers' own downloads, each with its licence and source; 12 are marked MPE where the maker documents per-note pitch bend, pressure and slide. Mac only for now; nothing downloaded is run, and a download that cannot be checked against a SHA-256 is refused unless you confirm it. | `store` |
| Adding HypnoMix DAW | Adds or removes HypnoMix DAW, HypnoMix's own DAW, an add-on that is not available yet. Report first: nothing is fetched or changed without --yes; a fetch is checked against a SHA-256 before it is used and can be removed again. | `engine` |
| Moving a Live song into HypnoMix DAW | Brings a Live set across as a NEW HypnoMix DAW session (`.ardour`): tracks, clips, fades, gain, automation, tempo, with the audio copied, and a report of everything that was not carried. The Live project is only read. | `als2ardour` |
| Learning audio production as you go | The app's Teacher tab is a free course in your own DAW (Live, REAPER or HypnoMix DAW): the complete course from what sound is to releasing a song (13 chapters, 138 to 146 lessons depending on your DAW, with audio examples, exercises, quizzes and a glossary), a 101 crash course, or a tour of HypnoMix for engineers. In Live and REAPER a step can do the hands-on part for you, after saying what it will change. | `app` |
| Setting up, and checking your setup | Copies the AbletonOSC remote script into Live's User Library and walks you through the rest, then checks ffmpeg and Rubber Band, and (if you use Live) Live, AbletonOSC, BlackHole and plug-in parameter access, saying what to fix. | `install`, `doctor` |
| Reporting a problem | Writes a bug report, or the record of a crash, on your computer and shows it to you first, with your paths, names and keys hidden as far as HypnoMix can tell (read it before you share it). Copy it, save it, or open the project's issue page and paste it yourself: HypnoMix has no server and never sends anything. | `report` |

What stays yours: the playing, the sounds, the effects, the arrangement and every taste call. It learns your
habits from your own finished songs (`taste`, `voices --learn`, `motion --learn`, `profile`) and from what you
approve and skip (`prefs`), so proposals start from your standards.

### Checked where

- The Live devices and the Live fix paths were tested in Live 12.
- REAPER support was tested in REAPER 7.86.
- Everything newest passes unit tests and HypnoMix's own structure checks on synthetic data. That is the new commands (`balance`, `handoff`, `plugins`, `colour`, `release`, `compare`, `versions`, `album`, `preflight`, `demo`), masking cuts written as an EQ band, `ab` previews of timing nudges and device changes, and `fix` on a HypnoMix DAW scan. The REAPER files the newest code writes (the demo project, a project written by `fix` with an item fade and a volume-envelope dip, masking cuts as ReaEQ bands, the hand-off marker and the A/B project) were opened in REAPER 7.86 on 2026-11-26 and read back through its API: no offline media, and everything matched what HypnoMix wrote. Still unchecked: the new Live sets (hand-off locators, the EQ Eight band, colour chains) have not been opened in Live, the new `.ardour` snapshots have not been opened in a released DAW, the new tools have not been run on real songs, and nothing new has been judged by ear. Where a page says "new", read it that way: keep your original and listen.
- DAW mode (the HypnoMix engine, the DAW view and the Assistant on it) was tested against stand-in engines in the unit tests and against the real engine on its silent test backend only. Not tried: sound through a real sound card, recording, the native File menu of a test build, the add-on's download and unpacking from a real release (none is published), signing and notarisation, and Intel Macs. The Store, `als2ardour` and `chain --ardour` are checked by unit tests on synthetic data and stand-in servers only: no session written by `als2ardour` has been opened in a released DAW.

## No terminal, no AI: the app and the Live device

```
hypnomix app        # a web app on your own computer: choose a song, hear each fix, approve, apply
hypnomix device     # optional: a Max for Live device to step through the findings inside Live
hypnomix probe device # optional: HypnomixProbe (every track) and HypnomixMain (Main): meters, what each track is,
                      #   the song card (genre, key, chords, loudness), an editable mastering chain of
                      #   Live's own devices (Build, Match target, Save), record and review before export
hypnomix abset DIR    # optional: every fix as a switch in Live: A / B / Blind on the device (docs/LIVE.md)
hypnomix aligndevice  # optional: Hypnomix Align, a Max for Live device to align a vocal stack (docs/ALIGN.md)
hypnomix reaper align # optional: the same in REAPER, as the HypnoMix Align panel (a new .rpp; yours untouched)
macapp/build.sh     # optional: build your own Hypnomix.app (a Dock icon around the same web app)
hypnomix app --daw  # only with the HypnoMix engine (the add-on, not available yet): HypnoMix DAW's window on it (docs/APP.md)
```

The app runs the scan, builds the before / after clips, shows the review with play buttons, and writes only
what you approved into a new set. Every other command is on its Tools screen with a form. The device sits on
any track in your Live set, shows the finding you are on, and moves Live to it: track selected, playhead and
loop brace on the spot, clip open. See [docs/APP.md](docs/APP.md).

New to audio? The app's **Teacher** tab is a free course in your own DAW (Live, REAPER or HypnoMix DAW): the complete course from what sound is to releasing a song
(138 to 146 lessons depending on your DAW, with audio examples, exercises, quizzes and a glossary), a 101 crash course, or a tour of HypnoMix for engineers. Turn it on in the app's guided setup.

### The Assistant: chat with an AI inside the app, your own key

No Claude Code needed. Open the app's **Assistant** tab, choose a provider, paste a key, and talk about your
song: "do a first pass on this set", "what does the review say about the vocals?", "apply what I approved".
The assistant runs HypnoMix for you and explains each finding.

- **Any provider:** Claude (Anthropic), OpenAI, Google Gemini, OpenRouter (many models on one key), Groq,
  Mistral, any other service with an OpenAI-compatible address, or a free model running on your own computer
  in Ollama (no key at all). **List models** shows what your key can use.
- **Your key and your audio stay with you:** the key is kept in `~/.hypnomix/ai.json` and
  sent only to the provider you chose. On a Mac only your account can read that file. On Windows the file sits in your own user folder, which Windows keeps to your account and the computer's administrators; HypnoMix adds no lock of its own there. The assistant reads HypnoMix's text reports, not the audio.
- **A Listener (optional, off by default):** a second model, with its own key, that can *hear* a bounce and give
  notes by ear with timestamps (arrangement, energy, balance, vocal clarity, low-end feel), checked against
  HypnoMix's own measurements. The chat model stays whatever you like (say Claude); the listener is a Google model,
  with a Google Gemini key (aistudio.google.com/apikey, free tier available) or an OpenRouter key. Click **Set up a
  listener** under the chat settings. **List models** shows the models your key can send audio to; the default,
  `gemini-4-carbon`, had the best ear in our test (tempo, lyric timing and arrangement all right on a known song),
  with `gemini-4-hydrogen` and `gemini-3.5-flash` as faster, cheaper picks. Each listen shows the song, its length and rough cost, and waits for **Send it**.
  Only a reduced mono copy goes out (Gemini hears 16 kHz mono anyway), at about 25 tokens a second: a 4-minute
  song is around a cent. It can't judge stereo width, air or exact loudness by ear; those stay HypnoMix's numbers.
- **Nothing changes without your click:** reading, scanning and measuring run straight away. Anything that
  writes a set (an `--apply`, `fix --approved`, an `.als` output) shows the exact command with **Run it /
  Don't**. Every write is still a new set next to the original.
- **With the Live device loaded**, it can point Live at a finding (track selected, playhead and loop there).

```
# the installers already include it; from source, in the hypnomix folder:
uv pip install -e ".[assistant]"      # the two official SDKs it talks through
hypnomix app                          # then open the Assistant tab
```

## First pass on a new song

```
hypnomix prefs                                   # once: your targets, protected tracks, how you like to review
hypnomix scan "Song.als" --mix "Song.wav"        # every check at once; changes nothing
hypnomix scan "Song.rpp"                         # or a REAPER project (REAPER can stay open)
hypnomix scan "Song/"                            # or a HypnoMix DAW session folder (or its Song.ardour)
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

**HypnoMix DAW:** the same for a HypnoMix DAW session (`.ardour`; the wiki article "HypnoMix DAW" says what that is): `hypnomix project "Song/"` lists tracks, buses,
regions, plug-ins and automation, `--render` plays the regions the way the DAW layers them (upper regions cover
lower ones, with their own fade curves and gain envelopes), and `scan` runs the same checks as on an `.rpp`.
`hypnomix fix` writes approved region fades, gain, dips and fader/pan/mute moves into ONE new `.ardour` snapshot next to the original (written and re-read by HypnoMix; not yet opened in a released DAW); the rest is listed to do by hand.

The scan runs every check below in parallel and writes one review list, most severe first. You (or an AI agent,
item by item with you) approve what to fix; `fix` writes only those changes into **one new set** next to the
original, then measures the new set again and tells you which problems are gone. It refuses to run if the set
changed since the scan, never overwrites a file, and won't touch tracks you marked as protected without asking
again. Every set it writes gets a structure check (`hypnomix check`) and a plain list of what changed
(`hypnomix diff`). `prep`, `automix` and `master` take `--plan`: instead of doing everything at once, each move
becomes a finding you approve or skip. `prefs` remembers what you usually approve and skip, so each review starts closer to how you work.
See [docs/WORKFLOW.md](docs/WORKFLOW.md). What comes next is opening everything the newest release added in real DAWs and on real songs; after that, colour for REAPER and HypnoMix DAW and previews (`ab`) for REAPER projects, then readers for more DAWs: [docs/ROADMAP.md](docs/ROADMAP.md).

## What's in the box

**Engineer: stems in, song out**

| command | what it does |
|---|---|
| `automix` | Stems → balanced mix → master. Per stem: role detection, clean-up EQ (resonances, mud, harshness), tone EQ, compression set by gain reduction, de-essing, loudness-based balance, panning, shared plate reverb, drum bus glue. Then it finds frequency fights between stems and carves the less important part. |
| `balance` | A first fader balance for a folder of stems, as proposals: one move per part with its role, its loudness while it plays and the vocal-to-band relation, compared with your own fader range when you have a profile. Faders only (no EQ, compression or pan: that is `automix`). Options: anchor part, vocal level against the band, per-role offsets. `--plan` sends the moves to the review. |
| `master` | Subsonic clean-up, optional reference tone match, glue compression, mono low end, true-peak limiter to a LUFS target. It test-encodes AAC/MP3 and lowers the ceiling if they would clip, then tops and tails. |
| `chain` | **No paid plug-ins needed.** Builds the mastering chain on Live's Main track from stock devices (EQ Eight → Glue Compressor → Utility → Saturator → Limiter), dials in every value from an analysis of your bounce, then records the result from Live and trims the Limiter until it measures on target. `chain strips` builds a channel strip on every track from an automix recipe. |
| `sidechain` | Makes sidechain compression sound good. Finds every Compressor and Glue Compressor in a set with its sidechain on (Glue suggestions snap to its menu values), simulates it on the trigger (audio tracks render straight from the set; drum racks and synths come from an individual-track export via `--stems`) and measures each hit: how deep it ducks, how much has come back by the next hit, how even it is, and whether the release is so short it distorts the bass's low end. Then it suggests settings for a style: `clarity` (2-4 dB, back before the next hit), `pump` (6-10 dB, back right on the next hit) or `vocal-duck` (delay and reverb returns duck under the singer and bloom in the gaps). Writes a gain-reduction plot on the beat grid and before/after previews; `--apply` writes the settings to a new set; `--glue-to-compressor` swaps sidechained Glue Compressors for Live's Compressor with lookahead (same routing, makeup and dry/wet). |
| `masking` | Which stems fight over which frequencies, how often, and the exact cut that fixes it. Approved in a `--deep` scan, `fix` writes the cut as one band on the part's EQ, or on a new EQ added to its chain if it has none, in a new set / project (EQ Eight, ReaEQ). |
| `align` | Phase, polarity and time offset between mics on one source (kick in/out, DI + amp, snare top/bottom). |
| `translate` | Mono fold-down, phone, earbuds and car simulations, how much each streaming service turns it down, clipping after encoding. `--render` to listen. |
| `qc` | Release checklist: format, head/tail silence, cut-off endings, DC, clipping, true peak, loudness, phase, codecs. Exits 1 on failure. |
| `release` | Turns a finished master into the folder you upload, always a new folder: your master as a 24-bit WAV (byte for byte when it already is one), a dithered 16-bit / 44.1 kHz WAV, MP3 320 and AAC 256 with title, artist, album, track, year, genre, ISRC and cover, and a plain-words report on every file, including the true peak after the lossy files are decoded. `--check` first. |
| `versions` | The other versions a release asks for, from your own exported stems (no separation): instrumental, a cappella, TV mix and radio edit. Checks the stems add up to your mix, matches loudness with gain only, crossfades radio-edit cuts, and runs the release checks on every file. `--check` first. |
| `compare` | This bounce against the previous one: lines them up, then says in plain words what changed (loudness, peaks, dynamics, tone and stereo width by band, each section), with level-matched A/B clips of the three spots that differ most. |
| `album` | An EP or album as a whole: which songs sit apart in level (judged on the loudest section as well as the whole), which are brighter, darker or boomier, the gap each pair could have, order options. Writes `ALBUM.md`; report first, and `--plan` turns any trim, tilt or silence change into a finding you approve. |

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
| `vocallevel` | Vocal level line to line: does the vocal stay even from one lyric line to the next, and do the upper parts sit under the melody (1.5 dB by default)? Measured as heard (solo exports) or from renders. Run it in the first scan and again before every final export, because edits made since (restored comps, re-tuned notes, fader moves) can change it. `--apply` writes the fixes as volume automation in a new set. |
| `dehiss` | Spectral de-hiss plus a smart gate for one track: learns the hiss from the quietest moments, turns down only the frequency bins that sit at hiss level (smoothed so it never sounds watery), and fades the gaps with look-ahead so note attacks and tails stay natural. The gate has hysteresis and a 150 ms hold, so soft note tails can't make it chatter (which sounds like crackle). |
| `voices` | Balances vocal harmonies around the part **you** choose. Run it with the stems first: it lists the parts (usual note, level, how long they sing together) and asks. Then `--anchor lead|lowest|highest|TRACK` (left as it is), `--reduce above|below|both`, `--above-db` / `--below-db` per step (0, 1, 1.5, 3, 4.5, 6 or any value), `--spread ladder|flat`, `--max-cut`: only turns parts down, bar by bar, where they sing together, into balanced copies. Spacing can also be stated: `--root-step 4 --upper-step 5.5` (the lowest harmony is the basis, the next one up 4 dB under it, higher ones 5.5 dB under it), saved as your default with `voices --confirm`. The suggested setting is `--tame`: harmonies stay a little under the lead (at least 1.5 dB, `--lead-margin`), a higher part more than 1.5 dB louder than the part below it (`--tolerance`) comes down to that edge, the lead is never turned down, and it reports where the harmonies sit at one level (no space between them); nothing goes further unless you choose a step size. With raw renders, `--fader NAME=dB` compares the parts as heard; better, `--set SET.als` measures each part after its track's compressors and fader (loudness per window, BS.1770) and `--apply-set NEW.als` writes the spacing as track volume automation, which comes after the chain and lands exactly. Where the parts above would need more than the cut limit, the lowest harmony comes up instead (`--root-raise`, never closer to the lead than the margin). It reports the spacing it actually achieved. `--split` re-arranges the stems into Voice 1 (lowest) … Voice N (highest) so one fader per voice sets each step of the stack; the voices add up to the inputs exactly. Use post-chain stems (Live: Export → All Individual Tracks). |

**First pass and review**

| command | what it does |
|---|---|
| `scan` | Runs every check on a Live set, a REAPER project, a HypnoMix DAW session or a folder of recordings. Changes nothing; writes `REVIEW.md`. |
| `preflight` | Sanity of the files before any work: mixed sample rates or bit depths, stems of different length, duplicates, fake stereo, silent or clipped files, lossy sources, missing files, names that will not travel. Report first; `prep` repairs what it can. |
| `demo` | A 40-second synthetic song with six labelled problems, as a folder of stems or a REAPER project (`--kind reaper`, the one with the full scan, hear, apply loop), to try it on nothing of your own. |
| `handoff` | Turns the by-hand list into your DAW's own words: `HANDOFF.md`, a checklist in song order, plus markers (a new Live set with locators, a new REAPER project with markers, or a MIDI marker file and CSV for any DAW). |
| `als2ardour` | Brings a Live set across as a NEW HypnoMix DAW session folder (`.ardour`; tracks, clips, fades, gain, automation, tempo; the audio is copied): `als2ardour SET.als OUTDIR`. The Live project is only read, and `IMPORT-REPORT.md` lists everything that was not carried (devices, plug-ins, warp maps, Session clips). Written and re-read by HypnoMix; not yet opened in a released DAW. |
| `store` | Free and open-source plug-ins, synths, instruments, drum kits and sample packs, installed from their publishers' own downloads (`store search reverb`, `info`, `install`, `uninstall`, `updates`; `--mpe` keeps only the items whose maker documents MPE). **Mac only for now**: on another system it says so and does nothing. Nothing downloaded is run: an installer package, whether inside a disk image or the download itself, is kept and opened in Apple's Installer for you to click through. A download that cannot be checked against a published SHA-256 is refused unless you pass `--unverified`. The app's Store tab does the same, with an MPE mark and filter. |
| `engine` | HypnoMix DAW, the add-on (HypnoMix's own DAW; not available yet): `engine` and `engine status` say what is added, `engine where` the folder, `engine install` and `engine remove` report what they would do and change nothing until you add `--yes`. The address and SHA-256 come only from the manifest shipped inside the app; the download is checked before anything is unpacked; the engine is a separate program under the GNU General Public License (version 2 or later). |

**Live: hands on the set** (through a patched [AbletonOSC](https://github.com/ideoforms/AbletonOSC), bundled)

| command | what it does |
|---|---|
| `live` | Faders in exact dB, sends, pans, mute and solo; any device or VST/AU parameter, raw or in displayed units ("2.5 kHz", "-3 dB"); transport; snapshots; input routing, arming, monitoring and punch recording with take lanes. |
| `loop` | Plays bars, records them, measures them, and compares with the previous take and your profile. `--ab "db Lead -2" --revert` for one-change A/Bs. |
| `diagnose` | Solos each group in the loudest section of a song: who owns the sub, the bass and the vocal band. |
| `probe` | Max for Live meters on every track, after their plug-ins: loudness (BS.1770), peak, 8 bands, width, low-end mono, ten times a second with the bar. Each probe says what its track is, its priority and whether it is protected; HypnomixMain on Main carries the song card, builds an editable mastering chain of Live's own devices in a rack (Build chain; Match target turns its Limiter to your loudness target; Save keeps your edited chain or your own rack as a template) and records Main for a review before export. `probe listen` / the app's Live tab turn one play of the song into a review. See docs/LIVE.md. |
| `abset` | One new set with every proposed fix next to what you have, switched off (a copy of the changed device, or a muted copy of the track): the Hypnomix device switches A / B / Blind instantly with every plug-in, loudness-matched from the probe on Main. |
| `plugrender` | Renders tracks from a set offline through their real VST3/AU plug-ins, restored from the state Live saved (optional `plugins` extra, pedalboard). Live's Utility, Compressor, Glue and Limiter are modelled; other devices are named as skipped. `ab --plugins` previews device fixes through the chain. |
| `plugins` | Lists the plug-ins installed on this computer in the standard folders (VST3, Audio Units, CLAP, LV2), marks the ones on the free list below, and with `--check` loads each VST3 / AU without its window, each in its own process with a time limit (optional `plugins` extra). `--save` keeps the list in your preferences (`tools.plugins`); `--json` for agents. Read-only apart from your preferences file. |

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

**Ears:** `measure`, `key` (the song's key, section by section, with a confidence), `sections`, `match`, `tonal` (a tone target from your own songs), `harsh` (harsh 2-6 kHz build-ups), `compare` (this bounce against the last), `spectrogram`, `punch`, `stems`, `separate` (a mix into stems), `midi` (audio to MIDI), `pitchcheck` (pitch and loudness difference between two captures: run it after any re-render), `clicks` (finds clicks and crackle). Run `hypnomix` for the full list and `hypnomix <command> -h` for each one.

**Tempo and variety** ([docs/TEMPO.md](docs/TEMPO.md))

| command | what it does |
|---|---|
| `tempomap` | Follows the beat of a take played without a click and reports the tempo of every bar. Then either warps the take onto Live's grid, or makes Live's tempo follow the take. A click check and an offline preview come first. |
| `loops` | Finds the best 1, 2, 4 and 8 bar loops in a free-played take, grouped by groove, and lines them up in Session slots to try. |
| `tighten` | A gentle quantise: hits move part of the way to the click, close ones stay put, a full snap is refused. |
| `breathe` | Small tempo changes by section for a song recorded to a rigid click, with a preview of your mix bent along the new tempo. |
| `variations` | Finds parts that loop the same bars over and over, and unused takes of the same part that fit; adds them on new, switched-off tracks next to each part. |
| `colour` | Proposes new timbres where a part sounds the same throughout (measured per section: tone in six bands, texture in notes a bar): width, grit, space, movement or an octave copy, as a chain of Live's own devices (started from Live's library presets) on a new, switched-off copy of the part beside it, holding only the bars concerned, each with a before / after clip. Options: `--part`, `--family`, `--max`, `--amount`, `--static`, `--block`. Proposals only: `--apply NEW.als --ids colour-1,…` writes the ones you pick, `--plan` puts them in the review. Live sets only so far (REAPER and HypnoMix DAW not written yet); an instrument doubling a line is not built; installed free plug-ins are named as alternatives, never written into a set. |

## Install

**One download for everyone.** There is one app and one installer for each computer (below), with every HypnoMix tool, for
Live, REAPER, HypnoMix DAW or any DAW. **HypnoMix DAW**, HypnoMix's own DAW, is an add-on to the one app: you add it from the app's Setup only if you want it, so nobody who keeps
their own DAW downloads an engine they do not use. It is **not available yet**: no archive of it is published, so there
is nothing to add and the app downloads nothing. When it is, Setup adds it with one click (expected to be about 100 MB, fetched once from the
project's release page and checked against a SHA-256 fingerprint before it is used; it runs only while the DAW view is open,
and Setup removes it again). Its engine is a separate program under the GNU General Public License (version 2 or later);
HypnoMix itself stays MIT and contains none of the engine's code (see [THIRD_PARTY.md](THIRD_PARTY.md)).
The source will be published with the first release that includes the engine.

**The easy way: download the installer.** It carries its own Python and ffmpeg, so there is nothing else to set up.

| | download |
|---|---|
| Mac with Apple silicon (M1 and later) | [Hypnomix-mac-arm64.dmg](https://github.com/drtranceypants/hypnomix/releases/latest/download/Hypnomix-mac-arm64.dmg): open it, drag HypnoMix to Applications |
| Mac with an Intel chip | [Hypnomix-mac-intel.dmg](https://github.com/drtranceypants/hypnomix/releases/latest/download/Hypnomix-mac-intel.dmg) |
| Windows 10 / 11 (64-bit) | [Hypnomix-windows-setup.exe](https://github.com/drtranceypants/hypnomix/releases/latest/download/Hypnomix-windows-setup.exe): installs for you only, no administrator needed |

The installers are not yet signed, so the first time macOS or Windows asks you to allow it (the download page at
[hypnomix.bradfieldenterprises.org](https://hypnomix.bradfieldenterprises.org) shows how). On first open the Mac app offers to copy the
AbletonOSC remote script into Live (on Windows it is a box to tick in the installer); then restart Live and pick **Control Surface: AbletonOSC**. The installed app is the app only: for the
command line and Claude Code, install from source as below. The app's guided setup and the four ways to work
with AI (just the app, an AI key, a local model, a desktop AI app), with costs: [Setting up, and choosing an AI](docs/guides/09-setup-and-ai.md).
Building the installers yourself: [packaging/README.md](packaging/README.md).

**From source** (the command line, Claude Code, and every extra). Needs macOS or Windows 10/11 (Windows is newer and less tested; the unit tests run on both for every change). Linux: HypnoMix may run from source there, but the project does not test on Linux. Python 3.9+ (the Assistant's Claude provider needs 3.10+: Anthropic's library does not support 3.9, and the other providers work there), ffmpeg, Rubber Band 3+ (for `tune`, and for `vocalign`'s formant and transpose options; on a Mac `brew install ffmpeg rubberband`), and Ableton Live 11 or 12 for the Live features (a set saved by a newer major version of Live is read with one warning, and the tools that write a new set refuse it unless forced). The file tools work without Live; REAPER projects and HypnoMix DAW sessions are read directly.

```bash
git clone https://github.com/drtranceypants/hypnomix && cd hypnomix
uv venv && uv pip install -e .
source .venv/bin/activate        # puts `hypnomix` on your path; do it in each new terminal (Windows: .venv\Scripts\activate)
hypnomix install                 # only if you use Ableton Live
hypnomix doctor
```

`hypnomix install` copies the AbletonOSC remote script into Live's User Library and walks you through the rest. Then restart Live and choose **Settings → Link, Tempo & MIDI → Control Surface: AbletonOSC**.

To give HypnoMix access to more of your plug-ins' parameters, run `hypnomix install --plugin-params`. It adds one line to Live's `Options.txt`.

`loop` and `diagnose` record what Live plays through [BlackHole](https://github.com/ExistentialAudio/BlackHole). `hypnomix install` explains the two-minute setup.

Optional features. In the installed app, Setup → Extras installs `reference`, `ml` and `plugins` on a click; the installers already include `assistant` and `critique`. From source, run the install line in the `hypnomix` folder:

| extra | adds | install |
|---|---|---|
| `reference` | `hypnomix reference` (Matchering; GPL-3.0, kept separate so HypnoMix stays MIT) | `uv pip install -e ".[reference]"` |
| `ml` | `hypnomix separate` (split a finished song into stems) and `hypnomix midi` (audio → MIDI) | `uv pip install -e ".[ml]"` |
| `plugins` | `hypnomix plugrender` and `ab --plugins`: render through your real VST3 / AU chains (pedalboard; GPL-3.0) | `uv pip install -e ".[plugins]"` |
| `assistant` | the app's Assistant tab: chat with your own key from Anthropic, OpenAI or any OpenAI-compatible service, or a model on your own computer (already in the installers) | `uv pip install -e ".[assistant]"` |
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

HypnoMix never needs a paid plug-in. Its own processing is built in, and everything it does offline it can also build inside Live from the devices every Live Standard or Suite owner already has:

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

### Free plug-ins that work with HypnoMix

HypnoMix controls a plug-in through the parameters Live exposes for it (`hypnomix live params <track> <plug-in>`), so any VST3 or AU works the same way as a stock device. These free and open-source ones are part of the setup HypnoMix is developed with:

| plug-in | type | use it for |
|---|---|---|
| [TDR Nova](https://www.tokyodawn.net/tdr-nova/) | free | dynamic EQ: resonances and harshness that come and go. **Verified:** all 256 parameters reachable from HypnoMix |
| [TDR Kotelnikov](https://www.tokyodawn.net/tdr-kotelnikov/) | free | transparent mix-bus and mastering compression |
| [LoudMax](https://loudmax.blogspot.com/) | free | look-ahead mastering limiter |
| [Airwindows Consolidated](https://www.airwindows.com/consolidated/) | open source (MIT) | hundreds of small processors: saturation, console emulation, dithering |
| [CHOWTapeModel](https://chowdsp.com/products.html#tape) | open source | tape saturation and warmth |
| [Dragonfly Reverb](https://michaelwillis.github.io/dragonfly-reverb/) (Hall, Room, Plate, Early Reflections) | open source (GPL-3) | natural reverbs; the Plate matches automix's send |
| [Surge XT](https://surge-synthesizer.github.io/) (Effects) | open source (GPL-3) | multi-effects, plus a full synth |
| [SPAN](https://www.voxengo.com/product/span/) | free | spectrum analyser for checking HypnoMix's EQ moves by eye |
| [Youlean Loudness Meter 2](https://youlean.co/youlean-loudness-meter/) | free version | LUFS and true-peak metering in Live |
| [sfizz](https://sfz.tools/sfizz/) | open source | SFZ sampler for instrument parts |

Plug-ins with more parameters than Live shows by default need `hypnomix install --plugin-params` (or Live's Configure button) before HypnoMix can reach all of them.

## How it decides

Everything is measurement plus rules an engineer would use. There are no black-box models in the mixing chain, so every decision can be written down and argued with. Read [GUIDE.md](GUIDE.md) for the craft behind each tool and the workflows.

Its checks measure; they don't listen. The optional Listener (or `critique`) can add notes by ear from a cloud model, but those are an opinion, and the numbers stay measurements. Treat the automix as a strong first pass by an assistant, then make the taste calls yourself.

## Contributing

Bug reports, ideas and pull requests are welcome, and so is building with your own AI coding agent: the repo is set up for one (`AGENTS.md`). [CONTRIBUTING.md](CONTRIBUTING.md) has the bug report form, the feature idea form and the steps, from forking to testing on your own songs to opening a pull request. No GitHub account? Use the [feedback form](https://hypnomix.bradfieldenterprises.org/feedback/).

## Licence

MIT. Bundles AbletonOSC (MIT, © its contributors) with small patches marked `hypnomix patch`; see [THIRD_PARTY.md](THIRD_PARTY.md). Not affiliated with Ableton. The HypnoMix engine that DAW mode runs (an add-on fetched from Setup, not available yet) is a separate program, a rebranded fork of Ardour, the free open-source DAW that HypnoMix DAW is built on, under the GNU General Public License (version 2 or later): HypnoMix contains none of its code and starts it as its own process. Its source will be published with the first release that includes the engine.
