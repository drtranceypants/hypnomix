# First pass: preferences → scan → review → fix → verify

The fastest safe way to clean up a song. Every check runs at once, nothing changes until a person approves
it, every approved change lands in **new files** next to the originals, and the result is measured again.

```
 hypnomix prefs  (once)      your targets, protected tracks, what is deliberate, how you like to review
        │
        ▼
             ┌─ names    (name, order)   default track names → names by sound (asks when unsure); track
             │                           order + vocal-stack parts by pitch (ON by default, opt out)
             ├─ files    (refs)          missing audio
             ├─ clips    (smooth)        clicks, level jumps at cuts, spikes
 Song.als ───┼─ timing   (timing)        hits out of time with the band
  (+ mix)    ├─ vocals   (render+tune)   pitch of every vocal, harmonies vs lead
             ├─ effects  (distortion,    distortion in takes and device chains,
             │            sidechain,     sidechain ducking, device-chain audit
             │            audit)
             └─ mix      (measure, qc,   loudness and true peak vs your target, release
                          translate)     checks (needs --mix)

 a folder ───┬─ recordings               clipping, levels, noise floor, DC, clicks (per file)
 of audio    └─ stems    (masking)       which parts fight over which frequencies
                    │
                    ▼
     findings.json + REVIEW.md  (most severe first, each with an id)
                    │  person: approve / skip / change, one item at a time
                    │  hypnomix fix DIR --decide ID=approve|skip|change     → decisions.json
                    ▼
     hypnomix fix DIR --approved --out "Song (fixed).als"
                    │  looks each finding up again, applies it, measures the new set
                    ▼
     A/B by ear, then  hypnomix prefs learn DIR
```

## 0. Preferences (once)

```bash
hypnomix prefs                  # what is saved, and what is still unanswered
hypnomix prefs questions        # the first-run questions (JSON, for an AI agent to ask one by one)
hypnomix prefs set targets.lufs=-14 targets.true_peak=-1 review.style=one-at-a-time \
                   protect.tracks="Lead Vox,Strings" protect.notes="long reverb tail in the outro"
```

Saved in `~/.hypnomix/preferences.json`. Every scan reads it:

- **targets**: the mix check compares loudness and true peak with your numbers (default -14 LUFS, -1 dBTP).
- **protect.tracks**: findings on these tracks are marked PROTECTED, and `fix` refuses them until you say yes
  again (`--allow-protected`).
- **protect.notes**: things that are deliberate. They are printed at the top of every review so nobody
  "fixes" your fade or your long delay.
- **review**, **taste**, **tools**: how you like to review, how strict tuning and timing should be, your DAW
  and the free plug-ins you have.
- **learned**: after each review, `hypnomix prefs learn DIR` counts what you approved and skipped per kind of
  finding. The next review shows it ("in past reviews you skipped 9 of 10 like this"). It is advice for the
  reviewer. Nothing is ever applied because of it.

`hypnomix profile build song1.wav song2.wav …` is the other half: your sound as measured ranges, from finished
songs you like.

## 1. Scan (read-only)

```bash
hypnomix scan "Song.als" --mix "Song mix.wav" --ref "Song instrumental.wav" --key "F# major"
hypnomix scan "raw takes/"          # recordings or exported stems from any DAW: no Live set needed
```

- `--mix`: a bounce of the whole song (loudness, true peak, release checks, and a fallback for `--ref`).
- `--ref`: the mix or an instrumental. The vocal check measures the song's real tuning from it (songs are often
  not at A=440; one test song sat at A=435.4 Hz) and its key. `hypnomix separate mix.wav` makes an instrumental.
- `--key`: the key, confirmed by the person. Vocal tuning is not applied without it.
  The vocals group also maps the key section by section (`raw/key.json`); bars where two scales fit equally
  become `key-N` questions ("in bars 17-52, is the note F or F#?"). Answer them with `fix DIR --answer F#`, then
  tune with `fix DIR --key sections`: each section is tuned in its own scale.
- Track roles come from `hypnomix name` (run automatically); override with `--vocal-track` / `--timing-track`
  / `--lead-track` when it's unsure.
- Groups run in parallel (`--jobs 4`). To spread them over several agents, run one group each with
  `--only GROUP --out SAME_DIR`, then `hypnomix scan --merge SAME_DIR`.

Output in `hypnomix-out/scan/<song>/`: `REVIEW.md`, `findings.json`, `scan.json` (what was scanned, and when the
set was last saved), one `<group>.json` per group, and `raw/` (each tool's own report, renders of the vocals).

If a check could not run, the review lists it under **"Checks that did NOT run"**. No findings from a check
that did not run means nothing.

### What a set scan also tells you

- **noise**: takes boosted +12 dB or more with clip gain whose own noise floor comes up with them.
- **doubles**: how far each harmony or double sits from the lead in time (part of the vocals group).
- **ducking**: whether the vocal reverb and delay returns duck while the singer sings (`duck`): tune the ducking you have, or add a Compressor fed by the vocals. Options only; when the vocals' own effects come before the sidechain, the item says to check the gain-reduction meter in Live first.
- **intent**: "is this deliberate?" Every automated control, hard-panned track and switched-off track with
  clips, as questions. Confirm them once and save them: `hypnomix prefs set protect.notes="…"`.
- **stems** (`--deep`): renders every track and reports each frequency fight between two tracks and the phase
  and polarity between mics on one source ("Kick In" / "Kick Out", "Snare Top" / "Snare Bottom").
- `--like REF.wav` with `--mix`: tone by band, dynamics, width and loudness against a song you love, as proposals.
  With `--mix`, sections of the song are found from the set's tempo and compared ("the 2nd chorus is 2 LU quieter").

### Plans: tools that make many moves

```bash
hypnomix prep "raw takes/" --plan        # every repair it would make, per file, as findings
hypnomix automix "stems/" --plan         # every EQ, compressor, level, pan and reverb move, plus a trial mix
hypnomix master "Song mix.wav" --plan    # every stage of the mastering chain
```

Nothing is written to your files. The moves land in a scan folder and are reviewed like any other finding;
`hypnomix fix DIR --approved` then runs the tool with only the approved moves, into `DIR/fixed/`.

## 1b. Hear it first

```bash
hypnomix ab "hypnomix-out/scan/Song"       # before/after clips for each fix, level-matched → ab/
hypnomix review "hypnomix-out/scan/Song" --serve    # a page: play A, play B, approve / skip / change
```

`ab` builds the "after" in a temporary copy that is deleted again. It can preview clip fixes (clicks, cuts,
spikes), vocal tuning and repaired recordings. It cannot preview timing nudges or device changes: for those,
apply that one fix into a new set and listen in Live. Previews are the track alone, without effects.

The page shows every finding with its players and saves each click to `decisions.json` (with `--serve`, on this
computer only). Without `--serve` it is a static `REVIEW.html`: download your decisions from it, then
`hypnomix review DIR --import ~/Downloads/decisions.json`.

## 2. Review (one item at a time)

Each finding has: `id`, `severity` (high / medium / low / info), `track`, `where` (bar.beat or m:ss), the
`problem`, the proposed `fix`, and how it `applies`:

| applies | meaning | done by |
|---|---|---|
| `set` | a change to the Live set | `hypnomix fix` (into one new set) |
| `audio` | a new audio file (a tuned vocal, a de-hissed take) | `hypnomix fix`; you put it on a track |
| `manual` | needs hands or ears in the DAW (a loop seam, a crowded hit, a re-record) | you |
| `info` | a measurement | nothing |

Copies of the same audio (a repeated loop, a pasted chorus) are grouped under one finding. Record each decision
as it is made, so a review can stop and resume:

```bash
hypnomix fix "hypnomix-out/scan/Song" --decide smooth-14=approve,timing-7=skip
hypnomix fix "hypnomix-out/scan/Song" --decide tune-Lead=change --note "lighter on the verse"
hypnomix fix "hypnomix-out/scan/Song" --list        # every finding with its decision
```

Always asked one at a time: high severity, PROTECTED tracks, and anything about taste.

## 3. Fix (only what was approved)

Close the set in Live first, then:

```bash
hypnomix fix "hypnomix-out/scan/Song" --approved --out "Song (fixed).als"
# or name the ids:   --approve distortion-2,smooth-14,timing-7,tune-Lead
```

Order inside the new set: distortion parameter fixes → sidechain settings → clip fades and volume eases →
warp-marker nudges → track order and vocal-stack clip moves → track names. Items marked "on by default"
(track order) are applied by `--approved` unless you recorded skip. To hear each change before the next, apply one id per run and chain them with
`--from "Song (fixed 1).als" --out "Song (fixed 2).als"`.

What `fix` checks itself, and stops on:

| check | what happens |
|---|---|
| the set was saved again after the scan | stops; re-scan (or `--stale-ok` if you know the change is unrelated) |
| the output name already exists, or is the original | stops; nothing is ever overwritten |
| an id was recorded as skip or change | stops; record the new decision first |
| a finding is on a protected track | stops; ask again, then `--allow-protected` |
| vocal tuning without a confirmed key | that item is refused; pass `--key "F# major"`, or `--key sections` to follow the scan's key map section by section |
| `--key sections` with a key question (`key-N`) unanswered | tunes only notes both scales share; notes on the disputed pitches stay exactly as sung. Answer with `--answer F#` (or `"17-24=F"`, or `both`) to tune them too |
| a finding is no longer in the set (already fixed, or ids moved) | skipped and listed, never swapped for its neighbour |
| a step fails | listed under FAILED, exit code 1; the other steps still apply |
| after writing: structure | `hypnomix check` runs on the new set; if it fails the file is renamed "(BROKEN, do not open)" |
| after writing: what changed | every change is listed in plain words in `fix-log.md` (`hypnomix diff OLD NEW`) |
| after writing: result | the new set is measured again: "N of M approved problems no longer measured" |

Tuned vocals go to `<project>/Samples/Tuned/` (a new numbered file if one exists): put each on a new track at
bar 1, warp off, and A/B with the original's mute. Folder scans write repaired copies to `<scan>/fixed/`.
`fix-log.md` records every run: approved, applied, skipped and why, failed, and the verification.

## 4. Listen, then learn

The numbers say the problem is no longer measured. Only ears say it sounds right: open the new set and compare
the changed spots with the original at the same bars. Then:

```bash
hypnomix prefs learn "hypnomix-out/scan/Song"
```

## 5. Before the final mixdown: keep it moving

Loops that repeat for 16 or 32 bars feel static. `motion` offers the moves a DJ-style producer draws by hand, on
the effects the set already has (sends to the reverb and delay returns, filters on Main or on instruments, filter
and reverb macros of your racks). Every move is an **option**: none is applied by default.

```bash
hypnomix motion --learn "Finished Song.als" "Another.als"     # once: your moves, lengths and depths
hypnomix motion "Song.als" --mix "Song mix.wav" --names DIR/raw/names/names.json --plan
hypnomix fix "hypnomix-out/scan/Song (motion)" --decide motion-3=approve --note "bars=6 depth=0.3"
hypnomix fix "hypnomix-out/scan/Song (motion)" --approved --out "Song (motion).als"
```

| move | where | what it writes |
|---|---|---|
| riser | into a bigger, repeated or louder section | filter opens / DJ filter sweeps up, reverb builds; snaps back on the one |
| dip | inside a repetitive section | a slow low-pass down and back up |
| drift | across 32+ bars | the filter wanders, a point every 16 bars |
| swell | second half of a section | a reverb send or return stepped up bar by bar, back at the end |
| throw | phrase ends | a delay send up for the last beat of each phrase |
| outro | the last section | the reverb rises to the end |
| stutter | transitions and 8-bar turnarounds | the last 2 beats of a drum clip re-triggered: 1/8s, then 1/16s (clip slices; the rest plays on time) |
| gate | transitions and turnarounds | a rhythmic volume chop (16ths, 8ths, dotted, triplet-ish) for the last bar |
| dropout | into a drop | drums or bass silent for the last beat, then hit the one |

Fine controls in the decision note: `bars=`, `depth=` (share of the control's range), `dB=` (sends), `every=`
(throws), `beats=` (stutter, drop-out), `pattern=` (gate), `track=` (another track with the same kind of control).
It never writes where you already automated that control, and never edits comped clips (stutters on comped tracks
are listed by hand).

### Borrow loops from the original project

`borrow` looks in the song's original project (a set of the same name elsewhere in your projects folder, or
`--from`) for clips the new version no longer plays: MIDI clips (Arrangement or Session view, on any track) and
audio recordings it doesn't use. Each is offered for a section it fits, on a new track that copies the original
one (instrument and effects), **switched off**:

- MIDI: the 1, 2 or 4-bar window that already sits closest to the song's groove (measured from the mix), only
  where its notes fit the section's scale. The whole clip is nudged by one small offset so its first note lands
  where the song's downbeats land; the notes inside are never moved. Loops more than 30 ms off are not offered.
- Audio: warped clips up to 16 bars, whole.

```bash
hypnomix borrow "Song (remix).als" --mix "Song mix.wav" --plan
hypnomix fix "hypnomix-out/scan/Song (remix) (borrow)" --decide borrow-2=approve
hypnomix fix "hypnomix-out/scan/Song (remix) (borrow)" --approved --out "Song (borrowed).als"
```

## Other DAWs

Export every track as a full-length file from the same start point, with processing off, then
`hypnomix scan "that folder/"`. The review works the same way; repaired audio comes back as new files, and
anything that has to happen in the DAW (an EQ cut, a fader move) is listed as a to-do. `prep`, `automix`,
`masking`, `tune`, `vocalign`, `master`, `translate` and `qc` all work on files from any DAW.

## With an AI agent

The `first-pass` skill (`skills/first-pass/SKILL.md`) runs the whole loop: preferences, one read-only
`hypnomix-scanner` subagent per group in parallel, a merged summary, the review one item at a time, then `fix`
and the verification. Any agent can follow `AGENTS.md` to do the same. Ask:

> "Do a first pass on ~/Music/Song Project/Song.als. The mix is Song.wav."

## What the checks deliberately leave alone

- **Grid.** Timing work snaps toward the song's own grid, detected bar by bar from the hits (straight 16ths, triplets or mixed; reported in the scan notes). `vocalign`'s pull toward the tempo uses the same detection.
- **Feel.** `timing` measures the band's own looseness and only flags outliers (downbeats held tightest,
  16ths loosest), comparing each instrument with the others before the grid. Melodic parts (guitar, keys,
  strings: `--melodic`) only get clear outliers, as OPTIONAL low-severity items, moved at most 30% of the way
  and 15 ms. Each nudge is pinned on both sides, and the whole clip is checked afterwards: outside the nudged
  hit, nothing may move (a nudge that would shift the rest of the clip is refused). `tune` keeps vibrato,
  scoops and slides and only moves each note's centre.
- **Taste.** No fixed rule is applied for you: harmony balance, how far a melodic part moves, how much a tuned
  note is pulled are choices with fine controls. Harmonies are never turned down by default; the scan asks.
- **Names.** Only default names ("9-Audio", "8-Group") are renamed, and only when approved. The lead vocal is
  chosen one way everywhere (`roles.choose_lead`): among the vocals that play, the one that sings longest of
  those whose vowels move most.
- **Music.** Drum-like tracks aren't checked for spikes; loops that grow louder by design aren't "jumps";
  lasting level changes inside a take are only checked with `smooth --steps`.
- **Intent.** Automation, effects and levels you set are treated as choices. Things you listed as deliberate
  are shown on every review.
- **Undecidable cases** are flagged for a person: a note sung halfway between two pitches, a hit with
  neighbours too close to stretch cleanly, a loop seam that clicks, a steady quiet sound that could be hiss or
  a pad.
