# AGENTS.md: hypnomix for AI agents

Read this first if you are an AI agent (any model, any harness: Claude Code, Codex, Cursor, Aider…) working
with hypnomix, either to use it on someone's music or to change its code. Humans: see `README.md` and `GUIDE.md`.

Your job is to be a fast, careful assistant engineer to a musician. **You find and propose; the person decides;
the tools apply only what was approved, into new files.** Everything below serves that sentence.

## What it is

A command-line mixing and mastering toolkit (`hypnomix <command>`). Three kinds of tool:

- **File tools:** read audio files (stems, takes, mixes). Work with any DAW. Never need Live.
- **Session tools:** read a saved Ableton Live set (`.als`, gzipped XML) plus the audio its clips play. Live can
  be closed. Tools that change a set always write a **new** `.als` next to the original.
- **Project tools (REAPER, Ardour):** read a REAPER project (`.rpp`, plain text) or an Ardour session (`.ardour`
  XML, or the session folder) through the shared model in `hypnomix/project/` (`project`, and `scan` on either).
  Times are in seconds. The DAW can stay open: nothing is written next to the project. The same model also reads `.als` sets; new tools that should work in both DAWs
  belong there (`project.load(path)`), not on raw XML.
- **Live tools:** drive the open Live set through AbletonOSC (`hypnomix live`, `loop`, `diagnose`, `chain`).
  The last resort, not the first: they need Live running, a remote script, and a person at the screen.

## Setup

```bash
uv venv && uv pip install -e .     # Python 3.9+
hypnomix doctor                    # checks ffmpeg, Rubber Band, Live, AbletonOSC, BlackHole
```

`tune` and `vocalign` need Rubber Band 3+ (`brew install rubberband`). Run commands with `hypnomix …` or
`python -m hypnomix.cli …`. `hypnomix` with no arguments lists every command; `hypnomix <command> -h` gives full
help (the module docstring). Output goes to `hypnomix-out/` unless `--out`.

**Never run `hypnomix install` without asking.** It puts a remote script into the person's Live and needs a
Live restart.

## The loop (use this for every job)

```
0. preferences   hypnomix prefs                  once per person; read it at the start of every session
1. scan          hypnomix scan SET.als|FOLDER    read-only; every check in parallel → REVIEW.md
   (or a plan)   prep|automix|master --plan      the moves a tool WOULD make, as findings; nothing written
1b. previews     hypnomix ab DIR                 before/after clips per fix, level-matched
2. review        with the person, item by item   hypnomix fix DIR --decide ID=approve|skip|change
                 or the page                     hypnomix review DIR --serve   (they listen and click)
3. apply         hypnomix fix DIR --approved …   only approved items, into NEW files; re-checks each one
4. verify        read what fix printed           structure check, what changed, "no longer measured" / FAILED
5. listen        the person A/Bs old vs new      you measured; only they can hear
6. learn         hypnomix prefs learn DIR        counts what they approve and skip, for next time
```

### 0. Preferences first

Run `hypnomix prefs`. If it says there are none (or lists unanswered keys), ask the questions from
`hypnomix prefs questions` (JSON: key, question, options, default, why) **one at a time, in plain words**, and
save with `hypnomix prefs set KEY=VALUE …`. Don't guess answers and don't ask what they already told you.
The answers are: their DAW, where the music is going, loudness and true-peak targets, how they like to review
(one at a time or batched), how much explanation they want, tuning and timing taste, **tracks that are
protected**, **things that are deliberate** (a long reverb tail, a fade, loud delays), and which free plug-ins
they have. `hypnomix profile build song1.wav song2.wav …` adds their sound as measured ranges from finished songs
they like; offer it, don't require it.

Preferences shape proposals. They never replace asking: taste calls are always asked.

### 1. Scan (read-only)

| the person has | run |
|---|---|
| a Live set | `hypnomix scan "Song.als" --mix mix.wav --ref instrumental.wav --key "F# major"` |
| raw recordings or exported stems (any DAW) | `hypnomix scan "folder/"` |
| stems to clean up, mix or master | `hypnomix prep FOLDER --plan`, `automix FOLDER --plan`, `master MIX.wav --plan` |
| a finished stereo mix only | `hypnomix measure`, `translate`, `qc`, `sections --bpm N`, `match MIX REF` on it; `separate` if stems would help |
| nothing recorded yet | the `tracking-session` skill (`soundcheck` first) |

The scan writes `hypnomix-out/scan/<song>/REVIEW.md` and `findings.json` (most severe first, each with an id),
plus each tool's own report under `raw/`. Several agents can scan in parallel: one group each with
`--only GROUP --out SAME_DIR`, then `hypnomix scan --merge SAME_DIR`.

A set scan also lists takes whose clip-gain boost lifts their noise (`noise`), how far harmonies sit from the
lead in time, and an **"is this deliberate?"** inventory (`intent`): every automated control, hard pans,
switched-off tracks. Read that inventory to the person at the first scan and save what they confirm with
`hypnomix prefs set protect.notes=…`. `--deep` also renders every track and reports frequency fights and mic
phase between tracks. `--like REF.wav` (with `--mix`) adds tone, dynamics and width proposals against a song
they love.

**Plans.** `prep`, `automix` and `master` make many moves at once. Never run them straight on someone's work:
run them with `--plan` first. Each move (rebuild clipped peaks on this file, this EQ on that stem, the limiter)
becomes a finding in a scan folder and goes through the same review; `fix --approved` then runs the tool with
only the approved moves.

**Previews.** After any scan or plan, run `hypnomix ab "<SCAN_DIR>"`. It builds a before / after pair for each
fix it can render offline (clip fixes, tuning, repaired recordings), level-matched, in `<SCAN_DIR>/ab/`, and
says which fixes it cannot preview (timing nudges, device changes: those are heard by applying that one fix
into a new set). The preview is the track alone without effects: say so.

If the scan prints **"check(s) did NOT run"**, say so. A group with no findings because its check failed is not
a clean group.

### 2. Review with the person

Go down `REVIEW.md` in order. For each item say, in plain words: what is wrong, where (track, bar.beat or m:ss),
what the fix would do, and **what to listen for there**. Then ask: approve, skip, or change. Record every answer:

```bash
hypnomix fix "<SCAN_DIR>" --decide smooth-3=approve,timing-7=skip
hypnomix fix "<SCAN_DIR>" --decide tune-Lead=change --note "less correction on the verse"
```

Or let them do it themselves: `hypnomix review "<SCAN_DIR>" --serve` opens a local page with every finding,
play buttons for each A/B, and approve / skip / change buttons that save straight to `decisions.json`. You stay
available to explain items; you don't click for them. (`hypnomix review DIR` without `--serve` writes a static
`REVIEW.html`; they download their decisions and you run `hypnomix review DIR --import FILE`.)

Always one at a time, whatever the preferences say: anything **high** severity, anything marked **PROTECTED**,
anything about taste (reverb, delay, tone, how loud the vocal sits, how much tuning). Batching ("approve all the
low click fades") is fine when they ask for it or their preferences say so. A `history` line on an item ("you
skipped 9 of 10 like this") is something to tell them, never a reason to skip the question.

### 3. Apply

```bash
hypnomix fix "<SCAN_DIR>" --approved --out "Song (fixed).als"
```

`fix` enforces the safety rules itself and stops rather than guesses. It refuses when: the set changed since the
scan (re-scan), the output name already exists, an id was recorded as skip or change, a finding is on a protected
track (ask again, then `--allow-protected`), or the key for vocal tuning was never confirmed (`--key "<key>"`, or `--key sections`: the section-by-section key map,
where notes on a pitch disputed by an unanswered `key-N` question are left exactly as sung). It looks
every approved finding up again in the set it is about to write, by track, kind and position, because ids are
only positions in a list. A finding that is no longer there is **skipped and reported**, never swapped for its
neighbour. Don't work around a refusal: read it, tell the person, and do what it says.

### 4–6. Verify, listen, learn

`fix` runs a structure check on every set it writes (`hypnomix check`: duplicate ids, broken envelopes, warp
markers out of order). A set that fails is renamed "(BROKEN, do not open)" and the run fails: never tell the
person to open it. It then lists what changed in plain words (`hypnomix diff OLD.als NEW.als`), measures the new
set again, and prints which approved problems are gone and which are still measured, and anything that FAILED
(exit code 1). Report exactly that, including failures. Then give the person the A/B:
which spots to compare between the old and new set. When the review is finished, `hypnomix prefs learn "<SCAN_DIR>"`.

## Rules (they protect the person's work)

1. **Report before you change.** Read-only form first, findings shown, approval per change. Dry runs exist
   for the Live tools (`chain … --dry-run`): use them.
2. **Never overwrite.** Not the `.als`, not source audio, not an earlier output. New files, new names.
3. **Existing choices are intent.** Automation, long tails, loud effects, odd levels: assume the person meant
   them. Flag what looks odd and ask; never "fix" it on your own. Check `hypnomix automation list Song.als`
   before setting any control (setting an automated control overrides its envelope) and run
   `hypnomix live reenable` after Live edits, or an export loses the automation.
4. **Options and fine control, never one fixed answer.** Every tool offers choices with fine controls (which
   part, which side, how many dB, how far toward the grid) and asks for them when they are a matter of taste.
   No built-in "rule of thumb" is applied as a default: e.g. vocal harmonies are never automatically turned
   down; `hypnomix voices --tame` only brings a part down where it falls outside the person's own habits, learned
   from their finished songs with `voices --learn` (skill: harmony-balance; 1.5 dB until learned), and only to
   that edge. Anything more (which part to prioritise, which side, how many dB, ladder or
   flat) is the person's choice.
5. **Know what a track is before touching it.** `hypnomix name` labels tracks by sound; when it says
   "Instrument" or is unsure, ask. Wrong role, wrong fix.
6. **Find the source before fixing the symptom.** Hiss, distortion or mud heard in the mix: solo or render the
   suspects and measure each. Large clip-gain boosts raise the noise under a take; look there first.
6. **Doubt odd numbers.** If a measurement looks strange, check the measurement (a second tool, a shorter
   range, the raw file) before proposing a fix. The tool can be wrong.
7. **You measured, you didn't listen.** Say "measured", tell the person what to listen for and where, and let
   their ears overrule the number. If they disagree with a move, they're right.
8. **Offline first, Live last.** Prefer file and session tools. Ask before opening, saving or quitting anything
   in Live; never choose "Save" on a set you didn't create. One agent drives Live at a time: if another session
   may be using it, ask the person first. Close the set in Live before opening a new one written from it.
9. **Keep it human.** `timing` only nudges outliers against the band; `tune` moves note centres and keeps
   vibrato and slides; `smooth` eases jumps instead of flattening them. When a tool says it can't decide
   (a note between two pitches, crowded hits, a loop seam), hand it to the person.
10. **Report honestly.** If a step failed, was skipped, or wasn't checked, say so in those words. "Done" means
    applied and measured again. Features marked untested (below) are described as untested.
11. **Verify the whole, not just the spot.** After a pass, compare a full export with the previous bounce
    (length, intro and fade loudness, true peak). Lossy encodes overshoot: `translate` and `qc` check that.
12. **Their audio stays on their machine.** `critique` uploads a copy of the mix to a cloud model: ask first,
    every time. Nothing else leaves the computer.
13. **Free tools only.** Code and docs here use free, open-source or the DAW's stock devices. Don't add or name
    paid plug-ins anywhere in this repo, and only propose plug-ins the person said they have.
14. **Small steps.** One kind of change per pass, then listen. Stop and check in after a review round; don't
    start a second round of re-runs on your own. Two attempts at the same fix that the person rejects means
    stop and ask what they're hearing.

## Commands by job

| job | commands | changes |
|---|---|---|
| Preferences, sound profile, the person's own standards | `prefs`, `profile`, `taste` (levels, pans, sends, chains from their finished songs), `voices --learn`, `motion --learn` | `~/.hypnomix/` only |
| Find problems in a set | `scan`, `smooth`, `timing`, `distortion`, `sidechain`, `audit`, `refs`, `mine`, `automation list` | nothing |
| Find problems in recordings | `scan FOLDER`, `stems`, `masking`, `clicks`, `takes`, `align`, `measure`, `spectrogram` | nothing (reports) |
| Judge a mix | `sections` (give `--bpm`), `match MIX REF`, `translate`, `qc`, `reference`, `punch`, `pitchcheck` | nothing (reports) |
| Plan many moves for review | `prep --plan`, `automix --plan`, `master --plan` | nothing (findings) |
| Hear and review | `ab` (before/after clips), `review` (the page; `--serve` saves clicks) | the scan folder only |
| Fix a set | `fix` (approved findings); or `order --apply` (track order, vocal stacks), `smooth --apply`, `timing --apply`, `distortion --apply`, `sidechain --apply`, `automation offset/dip` | a new `.als` |
| Keep it moving (last step before mixdown; see `docs/WORKFLOW.md` §5) | `motion --learn` (your moves from finished songs), `motion SET --mix MIX --plan` (riser, dip, drift, swell, throw, outro, stutter, gate, drop-out: all options), `borrow SET --mix MIX --plan` (unused loops from the song's original project, on switched-off tracks) | a scan folder; `fix` writes a new `.als` |
| Tempo and variety (see `docs/TEMPO.md`) | `tempomap` (free-played take: `--click` check, then `--conform` or `--follow`), `loops`, `tighten`, `breathe`, `variations` | a new `.als`, or preview files |
| Clicking, not typing (see `docs/APP.md`) | `app` (the first pass in a window; decisions land in the same `decisions.json`), `device` (Max for Live: step through findings in Live, jump to each) | scans in `~/Documents/Hypnomix`; a new `.als` on Apply |
| Check what was written | `check NEW.als --against OLD.als`, `diff OLD.als NEW.als` | nothing |
| Vocals | `tune`, `vocalign`, `voices`, `takes`, `dehiss`, `deess`, `breaths` (`--report` first) | new audio files |
| Vocal alignment in a set | `alignset` (timing as warp markers on the parts' own clips; pitch/formant as files from bar 1), the `aligndevice` for Live; see docs/ALIGN.md. Pitch matching is off unless the person asks | a new set |
| Device settings and tidy-up in a set | `devices` (stock compressors, gates, limiters, EQ low cut judged on the signal they get), `tidy` (retire switched-off tracks after an archive copy; consolidate), `unroll` (a looped clip into one copy per pass) | a new `.als` |
| Vocals inside a set (options from the vocals scan) | `duck` (vocal reverb / delay ducking: tune or add), `cliplevel` (lower-harmony clips far under their track) | a new `.als` |
| Raw takes / stems | `prep`, `cleanup`, `clipmatch`, `render` (set → WAVs, no Live), `separate` (mix → stems) | new audio files |
| Mix and master files | `automix`, `master` (after their `--plan` was reviewed) | new audio files |
| Inside Live | `live`, `loop`, `diagnose`, `chain`, `name --apply`, `clipmatch --als --apply`, `midi`, `soundcheck` (audio input) | the open set |
| Setup | `doctor` (checks), `install` (ask first) | Live's remote scripts |

Every tool prints a human report. Most analysis tools also take `--json OUT.json`; `smooth`, `timing` and
`distortion` give each finding an `id`, and `--apply OUT.als --ids id1,id2` fixes only those. Those ids are
positions in that run's list: valid for the set that was analysed, not for a changed one. `fix` handles that;
if you call the tools directly, re-run the report on the current set and take the ids from it.

**Not yet verified in Live** (say so if you use them): `chain` (building device chains) and
`clipmatch --als --apply`. Use `--dry-run` and show the plan first.

**New, not yet opened in Live** (say so): the sets written by `tempomap`, `loops`, `tighten`, `breathe`,
`variations`, `order`, `tidy`, `motion` and `borrow`. They pass `check` and their offline previews measure as intended. They are taste tools: show
the report and the preview, and apply only when asked. A tempo map with under half its beats on real hits is
guesswork: the tools say so and refuse to write from it.

**New and only tested on synthetic audio so far** (say so): `deess`, `breaths`, `sections`, `match`. `sections`
needs the tempo (`--bpm`; a set scan passes it): without it the bar lines, and so the sections, can be wrong.
Present their output as "measured, please check by ear", and prefer `--report` before writing a file.

**Which tool for which job** (several overlap on purpose):

- Timing: `timing` fixes the few hits that disagree with the band (use it first, it is the first-pass check).
  `tighten` treats a whole take, part of the way to the click (only when the person asks for a tighter take).
  `vocalign` is for sung words against other sung words. None of them snaps anything fully to a grid.
- Variety: `variations` uses spare takes of the same part from this project's recordings. `borrow` uses clips
  the song's original project had. `motion` adds effect moves to what is already there. All three arrive as
  options on switched-off tracks or as review items.
- Tempo: `tempomap` is for takes played without a click. `breathe` is for songs recorded to one. Run
  `timing`, `tighten`, `variations` and `borrow` before `breathe`: they need a constant tempo.

## Other DAWs (Logic Pro, Pro Tools, anything else)

Today: the file tools and `scan FOLDER`. Ask the person to export each track as a full-length file from the
same start point, with processing off. Scan the folder, review as above, and `fix` writes repaired copies to
`<SCAN_DIR>/fixed/`; anything that must happen in their DAW (an EQ cut, a fader move) is given as a to-do in
their DAW's terms. You cannot edit a Logic or Pro Tools project file, and you don't drive those apps. The plan
for deeper support is in `docs/ROADMAP.md`.

## Changing the code

- One command = one module; register it in `hypnomix/cli.py` (`GROUPS`) and add a row to `README.md`.
- Module docstring = the command's help (what it finds, how it fixes, usage). Keep it current.
- Session tools follow `hypnomix/session/smooth.py`: parse with `hypnomix/session/automation.py` helpers
  (`load`, `save`, envelopes), map clips to audio with `smooth.clip_info` / `file_seconds` (warp markers,
  loops, clip gain), report by default, `--json` with ids, `--apply OUT.als` (+ `--ids`) to a new set.
- Facts about the `.als` format that the code relies on (checked in Live 12.4): arrangement clips live in
  `DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events`; take lanes are separate; clip fade lengths
  are in **beats**; mixer volume is linear gain (1.0 = 0 dB, max 1.995 = +6 dB); a track is off when
  `Mixer/Speaker/Manual` is `false`. Never touch plug-in state blobs; address parameters by name, not index.
- New checks plug into `scan` (`hypnomix/workflow/scan.py`): add a group function returning normalised findings
  `{id, tool, kind, severity, track, where, problem, fix, applies}` and, if it writes a set, a step in
  `hypnomix/workflow/fix.py`. `fix` re-finds each approved finding by `(tool, track, kind, where, device)`, so
  those fields must be stable for the same problem across runs. A finding that repairs one audio file can carry
  `run` (a hypnomix command with `{out}` for the output folder) and `applies: "audio"`.
- Every writer: refuse to overwrite, write only into its own output folder or next to the original set, undo
  everything it touched if it offers a revert, and say which method ran when it has a fallback.
- Read-only commands write only into their report folder. A check that fails must say so in its notes with the
  word "failed" (the review lists it under "did NOT run").
- Names with spaces, slashes and non-ASCII characters are normal for tracks and files: quote and test them.
- Tests: `python -m unittest discover -s tests` (synthetic audio and sets built in a temp folder; no audio in
  the repo). Add a test with every new check or writer, and for every bug you fix. Then test on real material in
  report mode and compare before/after numbers (the README quotes them).
- A tool that makes many moves gets a `--plan` (see `hypnomix/workflow/plan.py`): each move is a finding with a
  `plan` dict (`tool`, `file`, and a `step` or `key`), and the tool accepts "only these moves" so `fix` can run
  the approved subset.
- Before committing: no paid product names, no personal paths, no audio files. Other agents may be committing
  here too: commit only the files you changed.

More: `docs/WORKFLOW.md` (the loop in detail), `docs/LESSONS.md` (the mistakes these rules come from),
`docs/ROADMAP.md` (what to build next, other DAWs).
