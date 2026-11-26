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
  and the free plug-ins you have. `review.max_questions=N` asks N fixes one by one and batches the rest (0 asks
  everything). `review.style`, `review.explain` and `targets.delivery` are read by AI agents and the Assistant,
  who follow them when they run the review with you; the scan itself does not change. `taste.tuning` and
  `taste.timing` (`off`, or gentle or tight) tell a scan how far to go; `off` means that kind of fix is not proposed.
- **cleanup**: the tidy steps of the first clean-up, all on by default: `cleanup.order`, `cleanup.retire`,
  `cleanup.consolidate` (`on` or `off`). They are also in the app's Preferences tab.
- **tools.daw** is `live`, `reaper`, `ardour` or `other`, the same choice as the app's Setup page: until you
  answer in Preferences, Setup's answer is used, so the two never disagree.

Every answer is checked when it is saved: `hypnomix prefs set targets.lufs=abc` is refused with "targets.lufs must
be a number from -40 to -1", and a choice that is not on the list names the choices that are. Nothing in the
command is saved unless every answer in it is good; the app's Preferences tab uses the same check.
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
  tune with `fix DIR --key sections`: each section is tuned in its own scale. In a Live set the takes under the
  comp are what gets tuned, so the map is laid out in each take's own time through the comp clips: every part
  of a take is tuned in the scale of the section it is heard in. If the song's own MIDI parts settle the
  question (count F against F# in those bars), that is the answer.
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
hypnomix balance "stems/" --plan         # one fader move per part (faders only: no EQ, no compression)
```

Nothing is written to your files. The moves land in a scan folder and are reviewed like any other finding;
`hypnomix fix DIR --approved` then runs the tool with only the approved moves, into `DIR/fixed/`.

### A first balance: `hypnomix balance`

`hypnomix balance "stems/"` reports one fader move per part with the measurement behind it: the part's role, how
loud it plays (while it plays, not over the gaps), where the move leaves it against the anchor part, and how the
lead vocal sits against the band (everything else played together). If you built a profile with
`hypnomix profile build … --sets …`, each move is also compared with the fader range of your own finished songs.
It differs from `automix` in what it touches: faders only, no EQ, no compression, no pan, no reverb. Options:
`--anchor NAME`, `--vocal-over-band DB`, `--offset bass=-1.5,hats=-2`, `--keep-level`, `--min-move`, `--max-move`.
`--plan` sends the moves to the review; `fix --approved` writes only the approved stems (each with its move baked
in) and a trial mix into `DIR/fixed/balance/`. Measured, not heard: move the faders until it feels right.

### The by-hand list: `hypnomix handoff`

`fix` lists what it cannot do itself under "by hand". `hypnomix handoff "SCAN_DIR"` turns that list (the approved
by-hand items, plus any item you skipped or changed with a note) into `handoff/HANDOFF.md`: a checklist in song
order, each line with track, bar.beat and m:ss, what to do in your DAW's words (Live, REAPER, Ardour or plain
wording; `--daw`, or your `tools.daw` preference), and what to listen for. A Live scan also gets a NEW set
"Song (handoff).als" with a locator at each spot (checked like any written set), a REAPER scan a new
"Song (handoff).rpp" with a marker at each spot, and every scan gets `markers.mid` (a MIDI file with a marker per
spot) and `markers.csv` for DAWs that import those. For a folder of stems give `--bpm` for bar.beat. Nothing is
changed in place.

## 1b. Hear it first

```bash
hypnomix ab "hypnomix-out/scan/Song"       # before/after clips for each fix, level-matched → ab/
hypnomix review "hypnomix-out/scan/Song" --serve    # a page: play A, play B, approve / skip / change
```

`ab` builds the "after" in a temporary copy that is deleted again. It can preview clip fixes (clicks, cuts,
spikes), vocal tuning, repaired recordings, timing nudges (the clip stretched along the markers the nudge
writes, with Rubber Band, so the pitch stays), masking cuts and changes to a Compressor, Glue Compressor, Gate,
EQ Eight, Utility or Limiter. Device pairs are labelled "a model of the device, not Live itself": hypnomix plays
the track through its own model of the device. It cannot preview a device it has no model of (Saturator, Reverb,
racks, plug-ins), a MIDI note moved by a nudge, or a return track: `ab.json` and the review page say why, and for
those you apply that one fix into a new set and listen in Live. Clip previews are the track alone, without effects.

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

On a long scan, do not read every finding at once. `--list` narrows and pages: `--undecided`, `--severity high|medium|low`,
`--tool NAME`, `--top N`, `--offset N` (for example `--list --undecided --top 15`), and `--show ID` prints one finding in
full: everything `REVIEW.md` says about it plus the explanation of its kind of fix. `--decide` and `--approve` can be
repeated and each takes a comma list. `REVIEW.md` writes the explanation of each kind of fix once, under "Why these
fixes", and each item only what is its own; it has no checkboxes (decisions go through `--decide` or the review page).

Always asked one at a time: high severity, PROTECTED tracks, and anything about taste.

## 3. Fix (only what was approved)

Close the set in Live first, then:

```bash
hypnomix fix "hypnomix-out/scan/Song" --approved --out "Song (fixed).als"
# or name the ids:   --approve distortion-2,smooth-14,timing-7,tune-Lead
```

Order inside the new set: distortion parameter fixes → sidechain settings → clip fades and volume eases →
warp-marker nudges → track order and vocal-stack clip moves → track names. Items marked "on by default"
(track order, retiring switched-off tracks, merging one instrument's tracks, vocal-stack moves) are applied by
`--approved` unless you recorded skip; `--no-defaults` applies only what was approved by name. Before it writes
anything, `fix` prints which defaults it is adding and every file it is about to create (the new set, the
"(archive, all takes)" copy that tidy keeps, repaired audio, the log). At the end it prints "Not applied": what you
decided as "change" (with your note), what you approved that has to be done by hand, and what was no longer found,
each with what to do next. To hear each change before the next, apply one id per run and chain them with
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

## 4b. You stay in charge, faster

### How much of a fix (amount)

```bash
hypnomix fix DIR --decide smooth-3=approve@60      # 60% of the proposed move (default 100)
```

`fix` scales what can be scaled: `smooth` (share of each jump eased, fade length), `timing` (strength of each
nudge), `duck` (ducking depth), `tune` (correction strength), and device, sidechain, clip-gain and edge fixes (each
changed value moves that share of the way toward the proposed one; gains in dB; switches and modes all or
nothing). Kinds that can't be scaled (renames, track order, tidy, plans, borrowed loops, motion moves: use the
note's `depth=` instead) say so and apply in full for any amount above 0; `@0` applies nothing. The review page has
an amount slider on every finding that can scale.

### Grouped decisions

```bash
hypnomix fix DIR --decide-like smooth-3=approve@60 --dry-run     # lists the findings it would match
hypnomix fix DIR --decide-like smooth-3=approve@60               # records them (each marked via "like:smooth-3")
```

It matches undecided findings of the same tool and kind, the same track role (for per-track kinds, when the scan
named the tracks) and a size (dB, ms, cents) within ±50% of the example (`--band`). High-severity and protected
items are only matched by an example that is one too. Decided items are never touched, and a decision made on one
item afterwards wins. The page: "Approve the N like this" / "Skip the N like this".

### A question budget

`hypnomix prefs set review.max_questions=25`. REVIEW.md and the page list the most severe 25 questions (high
severity, protected items and key questions are always asked, budget or not); the rest go into a collapsed
"Low priority: batch" section, grouped by kind with a suggested decision for each group (from your past reviews,
else from the tool's confidence). A suggestion is advice: nothing is decided until you click or run it.

### On every finding: you usually, common practice, confidence

- **you usually**: from your past reviews (`prefs learn`), your finished songs (`~/.hypnomix/taste.json`, made by
  `hypnomix taste`) and `library.json` when present. Missing files just mean no line.
- **common practice**: what engineers commonly do about it (a habit, not a rule).
- **confidence**: the tool's own measure where it has one (names, edges, optional timing nudges, tuning), else a
  default for that kind of finding.

### Teach mode

`review.teach=on` (the default) adds a few plain words per finding on why the technique exists (clicks and fades,
level jumps, tuning, timing, de-ess, breaths, de-hiss, compression, sidechain, ducking, masking, harmony balance,
loudness and true peak...). `hypnomix prefs set review.teach=off` hides them.

### Collaborators

Every decision records `by` (`--as NAME`, else `prefs review.name`) and `at`. On the page a reviewer sets their
name and adds notes at a bar (`33.2`) or a time (`1:23.5`) to any finding.

```bash
hypnomix review DIR --export "review (Sam).json"     # decisions + notes, portable (findings matched by what they are)
hypnomix review DIR --merge "review (Sam).json"      # fills in what you haven't decided; lists every conflict
hypnomix review DIR --settle smooth-3=mine            # or =theirs
```

Your decision is never overwritten by a merge: where you decided differently, theirs is kept beside yours as a
conflict (shown on the page and in `fix --list`) until you settle it.

### History and undo

Every `fix` run that applies something is a version in `DIR/history/` (the approved ids with amounts, the list of
changes, and a copy of the set it started from and the set it wrote).

```bash
hypnomix history DIR                    # every version
hypnomix history DIR --diff 1 2         # what changed between two versions (0 = what v1 started from)
hypnomix history DIR --undo 2           # a NEW set equal to what v2 started from
hypnomix history DIR --undo-item timing-7    # the latest version again, without timing-7 (fix runs again)
```

Nothing is deleted or overwritten; undo sets go next to the original with a new name, and are versions too.

### Faster scans: quick, incremental, watch

```bash
hypnomix scan Song.als --quick                     # files, intent, structure: from the set alone, seconds
hypnomix scan Song.als --since "hypnomix-out/scan/Song"     # only the groups the changes since then can affect
hypnomix watch Song.als                            # on every save: a quick incremental scan; Ctrl-C to stop
```

Every scan keeps a copy of the set it read (`raw/scanned.als`). `--since` compares the set with it, re-runs the
groups those changes can affect (a clip edit: clips, timing or vocals, noise; a device change: effects, devices; a
fader or pan: intent; tempo or added tracks: everything) and carries the rest over (marked carried; carried
groups whose tracks changed are marked stale). New findings are marked new; decisions follow their findings by
what they are, and decisions whose finding is gone are kept in `decisions-orphaned.json`. `watch` only reads the set.

Every re-scan into a folder that already holds decisions does the same, not only `--since`: a decision follows its
finding (same tool, track, kind and position, within half a second or about a beat), never its number, so
"smooth-1 = approve" can not end up on a different clip after the set changed. Decisions that no longer match are
counted ("3 earlier decisions no longer match a finding and were set aside") and kept in `decisions-orphaned.json`;
nothing is applied from them. A scan never writes into the folder of a different source: "Song.als" and then an
Ardour session also called "Song" get "Song" and "Song (2)". Decisions, findings, the scan record and the log are
written whole or not at all, and the version before is kept next to each as `<name>.bak`; a file cut off by a crash
is read from its backup, with a warning.

### Render cache

`render` (and every check that renders: vocals, names, edges, previews) keeps each rendered clip in
`~/.hypnomix/cache/render/`, keyed by the source file (path, modification time, size), the clip's settings, its
length, the tempo, the sample rate and the stretcher. Rendering the same set again only renders what changed, and
the files are bit for bit the same. Capped at 2 GB (`HYPNOMIX_RENDER_CACHE_MB`), least recently used first;
`render --no-cache` or `HYPNOMIX_NO_CACHE=1` turns it off.

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

## REAPER

The same loop on a REAPER project; REAPER can stay open:

```bash
hypnomix scan "Song.rpp" --mix "Song mix.wav"
hypnomix fix "hypnomix-out/scan/Song" --approved --out "Song (fixed).rpp"
hypnomix reaper start && hypnomix chain master "Song mix.wav" --reaper --verify
```

`fix` writes fades, volume rides, word-edge fixes, track names and order into one new `.rpp`, and tuned vocals as
new takes on the person's own items. Vocal stacks: where harmony parts swap tracks, each item moves to the track for its pitch (same level in the
mix). Timing: out-of-time hits are nudged with stretch markers on the items. Sidechained ReaComps are measured and retuned in the new .rpp.
Details: `docs/guides/08-inside-reaper.md`.

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
