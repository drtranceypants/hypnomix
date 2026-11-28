# AGENTS.md: HypnoMix for AI agents

Read this first if you are an AI agent (any model, any harness: Claude Code, Codex, Cursor, Aider…) working
with HypnoMix, either to use it on someone's music or to change its code. Humans: see `README.md` and `GUIDE.md`.

Your job is to be a fast, careful assistant engineer to a musician. **You find and propose; the person decides;
the tools apply only what was approved, into new files.** Everything below serves that sentence.

## What it is

A command-line mixing and mastering toolkit (`hypnomix <command>`; `hypnomix` alone lists every command). The kinds of tool:

- **File tools:** read audio files (stems, takes, mixes). Work with any DAW. Never need Live.
- **Session tools:** read a saved Ableton Live set (`.als`, gzipped XML) plus the audio its clips play. Live can
  be closed. Tools that change a set always write a **new** `.als` next to the original.
- **Project tools (REAPER, HypnoMix Studio):** read a REAPER project (`.rpp`, plain text) or a HypnoMix Studio session
  (`.ardour` XML, or the session folder; what that format is: the wiki article "HypnoMix Studio", `28-ardour.html`) through the shared model in `hypnomix/project/` (`project`, and `scan` on either).
  Times are in seconds. The DAW can stay open: `scan` writes nothing next to the project, and `fix` on a REAPER
  scan writes ONE new `.rpp` (`workflow/fix_project.py`, edits in `project/rpp_edit.py`; tuned vocals become new
  takes on the person's own items, never a rendered copy); on a HypnoMix Studio scan it writes ONE new `.ardour` snapshot beside the
  original (`workflow/fix_ardour.py`, edits in `project/ardour_edit.py`: region fades and gain, gain-envelope dips, fader, pan,
  mute; names, order, stacks, timing, sidechain, tuning stay by hand; written and re-read by HypnoMix, NOT YET OPENED in a released DAW). The same model also reads `.als` sets; new tools that should work in both DAWs
  belong there (`project.load(path)`), not on raw XML.
- **REAPER tools:** `hypnomix reaper start|status|tracks|fx|params|snapshot|loop|diagnose` talk to the open REAPER through
  `hypnomix/reaper/bridge.lua` (request files in `~/.hypnomix/reaper-bridge`, a fixed list of commands, never code;
  each change is one REAPER undo step). `reaper snapshot` (and `snapshot restore` / `diff`), `reaper loop` and `reaper
  diagnose` are the REAPER side of `live snapshot`, `loop` and `diagnose` (`reaper/mixer.py`, `mixer.lua`). `scan` on an
  `.rpp` also runs the `devices` group (each ReaComp judged on its own track; `fix` writes threshold, ratio, attack and
  release; ReaGate and ReaLimit listed, not judged) and the `structure` group (the file reads back exactly, folders
  close, sends come from real tracks, faders; listed only). `chain … --reaper` builds chains from stock plug-ins (`engineer/chain_reaper.py`).
  Starting the bridge installs nothing, but it does run a script in the person's REAPER: say so before starting it.
  `reaper snapshot restore`, `reaper loop --ab` (without `--revert` the change stays) and `reaper diagnose` (it solos
  each folder while it renders) change the project open in REAPER, one undo step each: ask first, never from a test run.
- **Live tools:** drive the open Live set through AbletonOSC (`hypnomix live`, `loop`, `diagnose`, `chain`).
  The last resort, not the first: they need Live running, a remote script, and a person at the screen.
- **The app:** `hypnomix app` is the first pass in a window (scan, hear each fix, approve, apply), with an
  Assistant tab (chat with the person's own AI key), an optional Listener (a cloud model hears a bounce, only on
  their click) and **teacher mode**: free courses in their own DAW (Live, REAPER or HypnoMix Studio), from the complete course
  A to Z to a 101 crash course and a tour of HypnoMix. Point a newcomer at the Teacher tab; it is theirs to use, not
  something for an agent to drive.

## Setup

```bash
uv venv && uv pip install -e .     # Python 3.9+
hypnomix doctor                    # checks ffmpeg, Rubber Band, Live, AbletonOSC, BlackHole
```

`tune` needs Rubber Band 3+, and so do `vocalign`'s formant and transpose options (`brew install rubberband`; on Windows and Linux HypnoMix says how to get it). Run commands with `hypnomix …` or
`python -m hypnomix.cli …`. `hypnomix` with no arguments lists every command; `hypnomix <command> -h` gives full
help (the module docstring). Output goes to `hypnomix-out/` unless `--out`.

**Never run `hypnomix install` without asking.** It puts a remote script into the person's Live and needs a
Live restart. `device`, `aligndevice` and `probe device` also write into the person's Live User Library: do not run
them bare either (`--out FOLDER`, or `install --dry-run`, shows the result without touching it). `store install`,
`store uninstall` and `store updates` use the internet and write into `~/Library/Audio/Plug-Ins` and
`~/Music/Hypnomix Library` (Mac only): ask first, and in a test run set `HYPNOMIX_STORE_ROOT` to a scratch folder.
`store check` is offline and read-only (it only validates the catalogue), and `store list`, `search` and `info` read it too.
`als2ardour SET.als OUTDIR` and `import PROJECT OUTDIR` write a whole new session folder (OUTDIR must not exist
yet or be empty); give them a folder you made for the purpose. `app --daw` and `chain … --ardour` start, or talk to, the HypnoMix engine (a separate
program, GPL-2.0-or-later, an add-on that is not in the installer; engine 0.2.0, for Apple-silicon Macs only): ask first, never start it from
a test run, and an `app --daw` session that was changed must be saved or discarded on purpose (the engine never saves by
itself). `tidy|order|duck SESSION.ardour --engine --ids …` and `loops|variations … --cues` write into whatever
engine answers at `HYPNOMIX_ENGINE_URL` (default http://127.0.0.1:4820/mcp; on a shared machine that can be another
session's engine): groups, compressors and cue-slot clips that are not in the engine's undo history. The app shows
them as unsaved only through the engine's own flag, read at most every 2 s and only for an engine the app started (a
window it attached to is not covered), so a write just before Stop or quit can be missed. `--cues` has no `--ids` gate, so its first run already writes. Ask first, never from a
test run; if one is ever approved, set `HYPNOMIX_ENGINE_URL` to a scratch loopback address whose engine you started.
Without `--engine --ids` (tidy, order, duck) or `--cues` (loops, variations) they only report. `engine install --yes` downloads that add-on (and `engine remove --yes` deletes it): only when the person asked,
never from a test run (the report-first forms, `engine` and `engine status`, change nothing and are always fine). In a test run,
point `HOME`, `HYPNOMIX_HOME`, `HYPNOMIX_APP_HOME` and `HYPNOMIX_USER_HOME` at scratch folders that exist (see
CONTRIBUTING.md); the unit tests move themselves onto temporary folders when you leave these unset
(`tests/_isolate.py`).

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
they like; offer it, don't require it. Once built, `scan --mix` also compares the mix with those ranges, as things to listen for (`--no-profile` skips it).

Preferences shape proposals. They never replace asking: taste calls are always asked.

### 1. Scan (read-only)

| the person has | run |
|---|---|
| a Live set | `hypnomix scan "Song.als" --mix mix.wav --ref instrumental.wav --key "F# major"` |
| a REAPER project or a HypnoMix Studio session | `hypnomix scan "Song.rpp"`, `hypnomix scan "Song/"` (or its `.ardour`); the DAW can stay open |
| raw recordings or exported stems (any DAW) | `hypnomix scan "folder/"` |
| stems to clean up, mix or master | `hypnomix prep FOLDER --plan`, `automix FOLDER --plan`, `master MIX.wav --plan` |
| a finished stereo mix only | `hypnomix measure`, `translate`, `qc`, `sections --bpm N`, `match MIX REF` on it; `separate` if stems would help |
| nothing recorded yet | the `tracking-session` skill (`soundcheck` first) |
| not sure the files are in good shape | `hypnomix preflight` on the folder, set, project or session first (read-only: sample rates, lengths, duplicates, fake stereo, missing files) |
| nothing of their own to try it on | `hypnomix demo` (a 40-second song with six labelled problems, as stems or a REAPER project) |

The scan writes `hypnomix-out/scan/<song>/REVIEW.md` and `findings.json` (most severe first, each with an id),
plus each tool's own report under `raw/`. Several agents can scan in parallel: one group each with
`--only GROUP --out SAME_DIR`, then `hypnomix scan --merge SAME_DIR`.

`--deep` frequency fights are findings with a concrete cut: approved, `fix` writes it as one bell band on the DAW's
own EQ in a NEW file (an EQ Eight in Live, a ReaEQ in REAPER; an EQ already on the track is reused when it has a free
band, else a new one goes at the end of the chain; gentle by default, 2-3 dB; `fix --decide mask-1=approve@50` makes it half). A protected track still needs
`--allow-protected`.

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
fix it can render offline (clip fixes, tuning, repaired recordings, timing nudges, masking cuts, and changes to a
Compressor, Glue Compressor, Gate, EQ Eight, Utility or Limiter), level-matched, in `<SCAN_DIR>/ab/`, and says
in `ab.json` which fixes it cannot preview and why (a device HypnoMix has no model of, a MIDI note, a return
track: those are heard by applying that one fix into a new set). Say what a pair is: the track alone without
effects (clip fixes, timing, tuning); a nudge stretched along its warp markers with Rubber Band, not Live's
warp engine; and for device changes **a model of the device, not Live itself** (the pair says so).

If the scan prints **"check(s) did NOT run"**, say so. A group with no findings because its check failed is not
a clean group.

### 2. Review with the person

On a long scan do not read `REVIEW.md` from top to bottom. Read `hypnomix fix "<SCAN_DIR>" --list --undecided --top 15`
first (`--offset 15` for the next page; `--severity` and `--tool` narrow it), then `hypnomix fix "<SCAN_DIR>" --show ID`
for the item under discussion: it prints everything `REVIEW.md` says about it, with the explanation of its kind of
fix. Read `REVIEW.md` whole only for a small scan or when the person asks. For each item say, in plain words: what is wrong, where (track, bar.beat or m:ss),
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

Before it writes anything `fix` prints the clean-ups it adds because they are on by default (`order-1`, `retire-1`,
`merge-N`; `--no-defaults` leaves them out) and every file it is about to create, the archive copy included: read
that to the person. At the end it prints **Not applied**: what they decided as "change" (with their note), what they
approved that must be done by hand, and what was no longer found, each with what to do next. To give them that
by-hand list in their DAW's own words, run `hypnomix handoff "<SCAN_DIR>"`: a `HANDOFF.md` checklist in song order
with what to listen for, and a marker at each spot (locators in a new Live set, markers in a new REAPER project, or
`markers.mid` and `markers.csv` for anything else). `fix` enforces the
safety rules itself and stops rather than guesses. It refuses when: the set changed since the
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
7. **Doubt odd numbers.** If a measurement looks strange, check the measurement (a second tool, a shorter
   range, the raw file) before proposing a fix. The tool can be wrong.
8. **You measured, you didn't listen.** Say "measured", tell the person what to listen for and where, and let
   their ears overrule the number. If they disagree with a move, they're right.
9. **Offline first, Live last.** Prefer file and session tools. Ask before opening, saving or quitting anything
   in Live; never choose "Save" on a set you didn't create. One agent drives Live at a time: if another session
   may be using it, ask the person first. Close the set in Live before opening a new one written from it.
10. **Keep it human.** `timing` only nudges outliers against the band; `tune` moves note centres and keeps
   vibrato and slides; `smooth` eases jumps instead of flattening them. When a tool says it can't decide
   (a note between two pitches, crowded hits, a loop seam), hand it to the person.
11. **Report honestly.** If a step failed, was skipped, or wasn't checked, say so in those words. "Done" means
    applied and measured again. Features marked untested (below) are described as untested.
12. **Verify the whole, not just the spot.** After a pass, compare a full export with the previous bounce
    (length, intro and fade loudness, true peak). Lossy encodes overshoot: `translate` and `qc` check that.
13. **Their audio stays on their machine.** `critique` (and the app's Listening) uploads a reduced mono copy
    of the mix to a cloud model: ask first, every time (`critique --estimate` says what would be sent and its
    rough cost). `critique` asks y/N itself in a terminal and refuses elsewhere: never pass `--yes` until the person
    has said yes to what `--estimate` printed (for a song over 12 minutes it prints a warning: pass `--minutes 12`
    unless the person chose the whole file). Nothing else leaves the computer. Its notes are an opinion by ear:
    measurements win on numbers. Bug and crash reports are written on the computer too (`hypnomix report`, the app's
    "Report a problem", crash records in `~/.hypnomix/crashes`) and only the person copies, saves or posts them: never
    send one for them, never put a report's text in an address.
14. **Free tools only.** Code and docs here use free, open-source or the DAW's stock devices. Don't add or name
    paid plug-ins anywhere in this repo, and only propose plug-ins the person said they have.
15. **Small steps.** One kind of change per pass, then listen. Stop and check in after a review round; don't
    start a second round of re-runs on your own. Two attempts at the same fix that the person rejects means
    stop and ask what they're hearing.

## Commands by job

| job | commands | changes |
|---|---|---|
| Preferences, sound profile, the person's own standards | `prefs`, `profile`, `taste` (levels, pans, sends, chains from their finished songs), `voices --learn`, `motion --learn` | `~/.hypnomix/` only |
| Find problems in a set | `scan`, `smooth`, `edges`, `timing`, `distortion`, `sidechain`, `audit`, `refs`, `mine`, `automation list` | nothing |
| Check files before the work, practise | `preflight` (sample rates, lengths, duplicates, fake stereo, missing files; `--plan` for the review), `demo` (a practice song with labelled problems) | nothing; `demo` writes a new folder or project |
| A REAPER project (see `docs/REAPER.md`) | `project SONG.rpp`, `scan SONG.rpp`, `fix DIR --approved --out NEW.rpp`, `reaper start` (and `status`, `tracks`, `fx`, `params`), `reaper snapshot OUT.json` / `snapshot restore` / `snapshot diff`, `reaper loop --bars A-B [--ab CHANGE --revert]`, `reaper diagnose`, `vocallevel SONG.rpp --apply NEW.rpp`, `chain master MIX.wav --reaper --verify` | a new `.rpp`; plug-ins on the open REAPER's master (undo steps); `snapshot restore`, `loop --ab`, `diagnose`: the project open in REAPER (undo steps) |
| Find problems in recordings | `scan FOLDER`, `stems`, `masking`, `clicks`, `takes`, `align`, `measure`, `spectrogram` | nothing (reports) |
| Judge a mix | `sections` (give `--bpm`), `match MIX REF`, `translate`, `qc`, `reference`, `punch`, `pitchcheck`, `key` (the song's key, and a section-by-section map with a confidence) | nothing (reports) |
| Listen by ear (an extra; sends a reduced mono copy to a cloud model, so ask first every time) | `critique MIX` (the Listener: a cloud model's notes by ear; `--estimate` says what would be sent first) | nothing (notes only; the numbers stay measurements) |
| Plan many moves for review | `prep --plan`, `automix --plan`, `master --plan`, `balance --plan` (a first fader balance of stems, faders only), `colour --plan`, `album --plan` | nothing (findings) |
| Hear and review | `ab` (before/after clips), `review` (the page; `--serve` saves clicks) | the scan folder only |
| Hand the by-hand list to the DAW | `handoff SCAN_DIR` (`HANDOFF.md`, a marker at every spot; `--daw` picks the wording: `live`, `reaper`, `ardour` or `generic`) | files in `SCAN_DIR/handoff/`; a new set with locators (Live) or a new project with markers (REAPER) |
| Fix a set | `fix` (approved findings); or `order --apply` (track order, vocal stacks; `order SESSION.ardour --engine --ids …` writes groups into the open HypnoMix Studio engine instead), `smooth --apply`, `timing --apply`, `distortion --apply`, `sidechain --apply`, `automation offset/dip` | a new `.als`; with `--engine --ids`, the session open in the HypnoMix engine |
| Keep it moving (last step before mixdown; see `docs/WORKFLOW.md` §5) | `motion --learn` (your moves from finished songs), `motion SET --mix MIX --plan` (riser, dip, drift, swell, throw, outro, stutter, gate, drop-out: all options), `borrow SET --mix MIX --plan` (unused loops from the song's original project, on switched-off tracks) | a scan folder; `fix` writes a new `.als` |
| Tempo and variety (see `docs/TEMPO.md`) | `tempomap` (free-played take: `--click` check, then `--conform` or `--follow`), `loops`, `tighten`, `breathe`, `variations`, `loopset` (best loops from stems or `--takes SET.als`, variations and combos into Session scenes with `--apply NEW.als`), `loopedges`, `turnaround` (offline fills preview), `turnarounddevice` (Max for Live fills device; Ableton only), `colour` (new timbres where a part repeats itself: Live-device chains on switched-off copies, `--plan` for the review; Live sets only); `loops … --cues` and `variations SESSION.ardour --cues` (HypnoMix Studio: clips into cue slots on a track of their own, written at once) | a new `.als`, or preview files; with `--cues`, cue slots in the session open in the HypnoMix engine |
| Clicking, not typing (see `docs/APP.md`) | `app` (the first pass in a window; decisions land in the same `decisions.json`; its Teacher tab is the free course in the person's DAW; `app --daw`: HypnoMix Studio's window on its engine, the Assistant asking before each engine change), `device` (Max for Live: step through findings in Live, jump to each) | scans in `~/Documents/Hypnomix`; a new `.als` on Apply |
| Free plug-ins and sounds (Mac only; see `docs/APP.md`) | `store` (`search`, `info`, `install`, `uninstall`, `updates`, with `--kind`, `--format`, `--open`, `--licence`, `--mpe`, `--replace`; the catalogue holds 69 items, 12 with `mpe` true; `--unverified` only after the person has confirmed that the download cannot be checked against a SHA-256) | files under `~/Library/Audio/Plug-Ins` and `~/Music/Hypnomix Library`; its own manifest |
| HypnoMix Studio, the add-on (HypnoMix's own DAW; engine 0.2.0 for Apple-silicon Macs only, none for Intel Macs or Windows yet; see `docs/APP.md` and the wiki article `28-ardour.html`) | `engine` (status, `where`; `install` and `remove` report first and change nothing until `--yes`) | the engine under `<hypnomix home>/engine/<version>/` only; the address and SHA-256 come from the manifest shipped in the app |
| A project from another DAW into HypnoMix | `import PROJECT OUTDIR [--sr N] [--from live\|logicx\|ptx\|dawproject\|reaper\|aaf] [--allow-outside]` (a new session folder plus `IMPORT-REPORT.md`; the project is only read; only audio inside the project is copied unless `--allow-outside` (a .als copies its samples wherever they are); ptx and aaf need the HypnoMix Studio add-on, Apple-silicon Macs only so far; in DAW mode `POST /api/daw/import {path, out?}` runs it as a job, `GET /api/daw/import?job=ID` follows it) | a new session folder |
| Live set into HypnoMix Studio, and mastering in it | `als2ardour SET.als OUTDIR [--sr N]` (a new session folder plus `IMPORT-REPORT.md`; the set is only read), `chain master --ardour [--mcp-url URL] [--existing bypass|keep]` (builds the chain in the open session over MCP; `chain strips --ardour` is not built; not together with `--reaper`) | a new session folder; the open HypnoMix Studio session |
| Inside Live without renders (see `docs/LIVE.md`) | `probe device`, `probe insert SET.als` (new set with every device, no manual placing; also `scan --devices`), `probe listen` / `status` / `report` / `cards SET.als`, `abset SCAN_DIR` (every fix as a switched-off B for A / B / Blind on the device; from the scan of a REAPER project, a new `.rpp` for `reaper review`; from the scan of a HypnoMix Studio session, a new snapshot `<Song> (A-B).ardour` in its folder for the app's Review) | a new `.als` (or `.rpp`, or `.ardour` snapshot); captures in the app folder |
| Learn the person's style first | `taste --library` (every set on the computer: standards, taste calls, where to improve), `tonal build` (a tone target from their releases) | `~/.hypnomix/` only |
| Decide faster, stay in charge (see `docs/WORKFLOW.md` 4b) | `fix --decide ID=approve@60` (timing and tuning findings without an amount use the saved `taste.timing_amount` / `taste.tuning_amount`), `scan --retune DIR --key "A minor"` (the tuning findings again in the key the person chose; ask, never pick it), `--decide-like ID=approve --dry-run`, `review --export / --merge / --settle`, `history` (`--diff`, `--undo`, `--undo-item`) | decisions; undo writes a new `.als` |
| Faster re-checks | `scan --quick`, `scan --since DIR`, `watch SET.als` | nothing |
| Mastering options (see `docs/MASTERING.md`) | `tonal check`, `harsh`, `master --plan` with `--stabilize`, `--dyneq`, `--width-bands`, `--limiter-mode`, `--harsh`, `--dither`, `--amount`; `rebalance`; `translate --preview` | new audio files |
| Real plug-ins offline (see `docs/PLUGINS.md`) | `plugins` (what is installed; `--check` loads each safely, `--save` into the preferences), `plugrender SET --list / --check / --tracks`, `ab DIR --plugins` | new audio files; `plugins --save` writes the preferences only |
| Check what was written | `check NEW.als --against OLD.als`, `diff OLD.als NEW.als` | nothing |
| Vocals | `tune` (and `key` for the song's key), `vocalign`, `voices`, `takes`, `dehiss`, `deess`, `breaths` (`--report` first) | new audio files |
| Vocal level, line to line (run in the first scan and before every final export) | `vocallevel SET --heard DIR` (or `--renders DIR`); `--apply NEW.als` writes volume automation. `vocallevel SONG.rpp` measures from the project itself; `--apply NEW.rpp` writes volume envelope points | nothing, or a new `.als` / `.rpp` |
| Vocal alignment in a set | `alignset` (timing as warp markers on the parts' own clips; pitch/formant as files from bar 1), the `aligndevice` for Live; see docs/ALIGN.md. Pitch matching is off unless the person asks. With 2+ parts, ask what they line up to and pass `--to-average` or `--to-lead` (never choose for the person) | a new set |
| Device settings and tidy-up in a set | `devices` (stock compressors, gates, limiters, EQ low cut judged on the signal they get), `tidy` (retire switched-off tracks after an archive copy; consolidate; on a HypnoMix Studio session, the group option, written with `--engine --ids`), `unroll` (a looped clip into one copy per pass) | a new `.als`; with `--engine --ids`, the session open in the HypnoMix engine |
| Vocals inside a set (options from the vocals scan) | `duck` (vocal reverb / delay ducking: tune or add; on a HypnoMix Studio session, written with `--engine --ids`), `cliplevel` (lower-harmony clips far under their track) | a new `.als`; with `--engine --ids`, the session open in the HypnoMix engine |
| Raw takes / stems | `prep`, `cleanup`, `clipmatch`, `render` (set → WAVs, no Live), `separate` (mix → stems) | new audio files |
| Mix and master files | `automix`, `master` (after their `--plan` was reviewed) | new audio files |
| Release (see the wiki articles on each) | `release MASTER.wav --check` first, then without it (the upload folder: WAV 24-bit and 16-bit, MP3, AAC, tags, cover); `versions --stems DIR --vocals "…" --check` (instrumental, a cappella, TV mix, radio edit from the person's own stems); `compare OLD.wav NEW.wav`; `album SONGS` (level, tone and gaps across a record) | a new folder or new files; the reports are read-only |
| Inside Live | `live`, `loop`, `diagnose`, `chain`, `name --apply`, `clipmatch --als --apply`, `midi`, `soundcheck` (audio input) | the open set |
| Setup | `doctor` (checks), `install` (ask first) | Live's remote scripts |
| Report a problem (see the wiki article "Reporting a problem") | `report` (prints the report it would share: version, setup, last job and its log, the last crash record, finding counts; paths, names and keys hidden as far as it can tell, so read it before you share it; `--crash`, `--list`, `--what`, `--expected`, `--names`; `--out`, `--copy`, `--open` are the person's own choices) | nothing; `--out` writes a new file |

Every tool prints a human report. Most analysis tools also take `--json OUT.json`; `smooth`, `timing` and
`distortion` give each finding an `id`, and `--apply OUT.als --ids id1,id2` fixes only those. Those ids are
positions in that run's list: valid for the set that was analysed, not for a changed one. `fix` handles that;
if you call the tools directly, re-run the report on the current set and take the ids from it.

**Checked in Live 12 on a real set:** `chain master` (builds EQ Eight, Glue Compressor, Utility and Limiter on
Main and sets their values; needs `hypnomix install`) and `clipmatch --als --apply` (sets clip gains). Still use
`--dry-run` and show the plan first: `clipmatch` can propose large gains on quiet clips.
`chain master --verify` (records the loudest bars through BlackHole and trims the Limiter until Live lands on
the target) and `chain strips` (EQ Eight, Compressor and Utility on each track whose name matches a stem) are
checked in Live 12 too. Stems that match no track name are listed, not guessed.

**Opened in Live 12, not yet judged by ear** (say so): the sets written by `tighten` (warp markers on every
hit) and `breathe` (tempo automation, read back from Live at the right tempo), and `fix` sets with `tidy` and
`order` applied.
**New, not yet opened in Live** (say so): the sets written by `tempomap`, `loops`, `variations`, `motion`, `borrow` and
`colour`. They pass `check` and their offline previews measure as intended. They are taste tools: show
the report and the preview, and apply only when asked. A tempo map with under half its beats on real hits is
guesswork: the tools say so and refuse to write from it.

**New and only tested on synthetic audio so far** (say so): `deess`, `breaths`, `sections`, `match`. `sections`
needs the tempo (`--bpm`; a set scan passes it): without it the bar lines, and so the sections, can be wrong.
Present their output as "measured, please check by ear", and prefer `--report` before writing a file.

**The newest release: checked on synthetic data, and its REAPER files in REAPER 7.86** (say exactly this, never more): the Live devices and the Live
fix paths were tested in Live 12, and REAPER support in REAPER 7.86. Everything newer passes unit tests and HypnoMix's
own structure checks on synthetic data: `balance`, `handoff`, `plugins`, `colour`, `release`, `compare`,
`versions`, `album`, `preflight`, `demo`; masking cuts written as an EQ Eight or ReaEQ band; `ab` previews of timing
nudges and device changes (models of the devices, not Live); and `fix` on a HypnoMix Studio scan (the snapshot is written and
re-read by HypnoMix and has NOT been opened in a released DAW). On 2026-11-26 the REAPER files this code writes were opened in
REAPER 7.86 and read back through its API: the demo project (`demo --kind reaper`), a project written by `fix` (an item
fade and a volume-envelope dip), masking cuts as ReaEQ bands (frequency, gain and bandwidth read back exactly; REAPER's
own renders with the effect on and bypassed show the cut), the handoff project's marker (position and name) and the
A/B project (`abset`): all opened with no offline media and matched what HypnoMix wrote. The same day, in a private
REAPER 7.86 instance on one Mac, on a two-track test project (never a real song, nothing judged by ear): the HypnoMix
Probe, HypnoMix Main, Review and Align windows opened and their guides were captured by screenshot (not clicked through
by hand), and HypnoMix Main left an amount of 73 untouched; `ui.lua` and `mixer.lua` loaded with no error; `reaper
snapshot` / `diff` / `restore` were exact; `reaper loop --ab "nudge Bass -3"` measured B at -1.4 LU and `--revert` put
the mix back; `reaper diagnose` put every solo back (no project with folders was tried); a ReaComp written by `fix`
read back at -17 dB, 4:1, 15 ms, 250 ms; the `vocallevel --apply` envelopes opened again (106 points, all within +-3
dB; written before the 2026-11-27 change that leaves untouched points as they are and refuses hot envelopes, which is unit-tested only); and the Teacher's reverb (Wet 0 dB, Dry -inf) and saturation (Amount 20%) actions read back. On 2026-11-27, after the second review's changes, the same private instance again: both JSFX compiled and drew their new texts and labels, the bridge, `ui.lua` and `mixer.lua` loaded, the Review window (titled "HypnoMix Review") and the Align panel drew, `snapshot` (no "guide seen" values in it), `diff`, `restore`, the refusal of an existing OUT.json and `snapshot -h` behaved as described, `loop --ab "nudge 1 -3"` on a track named "1" measured B at -1.4 LU and `--revert` put it back, and `diagnose` wrote the bridge's `busy` file during its renders (the bridge stayed "running") and removed it after. Still not tried: the space and Esc keys in the panels, and clicking through the guides by hand. Not checked in
REAPER: clicking the windows by hand, Windows, a real song, listening, ReaGate and ReaLimit settings, and `diagnose`
with folders. `scan` on an `.rpp` does not read the probe menus, Protect or the song card (only the app's review of
what was heard, Record and review and the mastering chain use them). Still unchecked, and to be
said: the new Live sets (handoff locators, the EQ Eight band, colour chains) have not been opened in Live, the HypnoMix Studio
snapshots have not been opened in a released DAW, none of the new tools has been run on real songs, and nothing new has been
judged by ear. Tell the person to keep their original and listen.

**Which tool for which job** (several overlap on purpose):

- Timing: `timing` fixes the few hits that disagree with the band (use it first, it is the first-pass check).
  `tighten` treats a whole take, part of the way to the click (only when the person asks for a tighter take).
  `vocalign` is for sung words against other sung words. None of them snaps anything fully to a grid.
- Variety: `variations` uses spare takes of the same part from this project's recordings. `borrow` uses clips
  the song's original project had. `motion` adds effect moves to what is already there. All three arrive as
  options on switched-off tracks or as review items.
- Tempo: `tempomap` is for takes played without a click. `breathe` is for songs recorded to one. Run
  `timing`, `tighten`, `variations` and `borrow` before `breathe`: they need a constant tempo.
- Vocal level: `vocallevel` measures the vocal line by line (an even level, upper parts under the melody) and is
  run in the first pass and again before every final export. `voices` spaces the harmony parts around the one the
  person chooses, or splits them into one track per voice. `cliplevel` raises single lower-harmony clips that sit far
  under the rest of their own track.
- Clip edges: `smooth` eases clicks, level jumps and spikes at clip edges and seams. `edges` finds the edges and
  fades that cut into a word (a lost first consonant). They run in the same scan group; do not mix them up.
- Pitch and timing of vocals: `tune` corrects the pitch of one take, gently. `vocalign` times (and, if asked,
  pitch-matches) doubles and harmonies as audio files. `alignset` does that timing inside a saved Live set or REAPER
  project, as warp or stretch markers on the person's own clips, in a new file. With two or more parts both need
  the person's answer to "what do the parts line up to?": `--to-average` (every part is nudged toward the group's
  average timing, the lead a little too) or `--to-lead` (the parts follow the lead named with `--lead` / `--guide`,
  which is never moved). Ask it for every song unless `hypnomix prefs` shows `harmony.reference` saved as `average`
  or `lead`; without an answer the command stops with one sentence and writes nothing.
- Noise and mouth sounds: `deess` turns down the "s" moments of one vocal. `breaths` turns breaths down, not off.
  `dehiss` is a spectral de-hiss with a gate for one track. `cleanup` rescues a rough demo (hum, noise, rumble, DC,
  silence). `prep` is the whole pass over a folder of stems (those steps plus clipping, clicks, plosives, formats and
  fades); run it with `--plan` first.
- Master and balance: `balance` proposes a first fader balance for a folder of stems (faders only). `automix` takes
  stems to a mix and a master (EQ, compression, pan, reverb too). `master` makes a mastered file from a stereo mix.
  `chain` builds a mastering chain as real devices in Live (or REAPER). `rebalance` turns the vocals, drums, bass or
  the rest up or down inside a finished stereo mix.
- Tone against a target: `tonal` builds a target from the person's own songs and says where a mix sits outside it.
  `match` lists, as proposals, how a mix differs from a song they love. `reference` (an extra) does it with
  Matchering. `compare` is different: two bounces of the same song, old then new.
- Hearing a fix: `ab` writes level-matched before and after clips offline (a model for some devices). `abset` writes
  one new Live set (or REAPER project, or HypnoMix Studio snapshot) with every fix as a switched-off B, to switch A, B or Blind inside Live. `plugrender` renders
  tracks through the real VST3 and AU plug-ins offline (an extra; `ab --plugins` uses it).
- Tracks: `tidy` retires switched-off tracks (after an archive copy) and puts one instrument's clips on one track.
  `order` puts tracks in working order and each part of a vocal stack on the track for its pitch.
- Release: `qc` checks one file, pass or fail. `translate` checks how it survives elsewhere (mono, phone, earbuds,
  car, streaming, codecs). `release` builds the folder to upload and measures every file in it. `album` is not `qc`:
  it puts the songs of a record side by side (level, tone, gaps). Report first, whichever you run.
- Before the work: `preflight` checks the files (formats, lengths, duplicates, fake stereo, missing). `scan` checks
  the sound and the set. Run `preflight` first.
- After the fixes: `fix` makes the changes it can, into new files. `handoff` turns what `fix` lists as by hand into a
  checklist and markers in the person's DAW's own words. It changes nothing in place.

## Other DAWs (anything but Live, REAPER and HypnoMix Studio)

REAPER is supported directly (`scan`/`fix` on the `.rpp`, the bridge, `chain --reaper`: `docs/REAPER.md`), and
HypnoMix Studio sessions (`.ardour`) can be scanned and fixed into a new `.ardour` snapshot (fades, gain, dips, fader, pan and mute; the
rest stays by hand; not yet opened in a released DAW). There is NO reader for the sessions of any other DAW. For those:

Today: the file tools and `scan FOLDER`. Ask the person to export each track as a full-length file from the
same start point, with processing off. Scan the folder, review as above, and `fix` writes repaired copies to
`<SCAN_DIR>/fixed/`. Anything that must happen in their DAW (an EQ cut, a fader move) is by hand:
`hypnomix handoff "<SCAN_DIR>"` writes it as a checklist in their DAW's terms (`--daw generic` if unsure), with
`markers.mid` and `markers.csv` to import as markers. You cannot edit another DAW's project file, and you
don't drive those apps. The plan for deeper support (later) is in `docs/ROADMAP.md`.

## Changing the code

- One command = one module; register it in `hypnomix/cli.py` (`GROUPS`), add it to the chores table (the same
  row in `README.md` and `hypnomix/app/wiki/articles/25-chores.html`) and to `26-features.html`, and document it in
  the guide or doc it belongs to (see "Keep the wiki current" below).
- Module docstring = the command's help (what it finds, how it fixes, usage). Keep it current.
- Session tools follow `hypnomix/session/smooth.py`: parse with `hypnomix/session/automation.py` helpers
  (`load`, `save`, envelopes), map clips to audio with `smooth.clip_info` / `file_seconds` (warp markers,
  loops, clip gain), report by default, `--json` with ids, `--apply OUT.als` (+ `--ids`) to a new set.
- Facts about the `.als` format that the code relies on (checked in Live 12.4): arrangement clips live in
  `DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events`; take lanes are separate; clip fade lengths
  are in **beats**; mixer volume is linear gain (1.0 = 0 dB, max 1.995 = +6 dB); a track is off when
  `Mixer/Speaker/Manual` is `false`. HypnoMix's list of tested versions is Live 11 and Live 12 (the checks on real sets so far were in Live 12): a set saved by a newer major version is read with one warning, and the tools that write a new set refuse it unless forced (`HYPNOMIX_FORCE_LIVE_VERSION=1`; `session/liveversion.py`). Never touch plug-in state blobs; address parameters by name, not index.
- New checks plug into `scan` (`hypnomix/workflow/scan.py`): add a group function returning normalised findings
  `{id, tool, kind, severity, track, where, problem, fix, applies}` and, if it writes a set, a step in
  `hypnomix/workflow/fix.py`. `fix` re-finds each approved finding by `(tool, track, kind, where, device)`, so
  those fields must be stable for the same problem across runs. A finding that repairs one audio file can carry
  `run` (a HypnoMix command with `{out}` for the output folder) and `applies: "audio"`.
- Every writer: refuse to overwrite, write only into its own output folder or next to the original set, undo
  everything it touched if it offers a revert, and say which method ran when it has a fallback.
- Read-only commands write only into their report folder. A check that fails must say so in its notes with the
  word "failed" (the review lists it under "did NOT run").
- Names with spaces, slashes and non-ASCII characters are normal for tracks and files: quote and test them.
- Tests: `python -m unittest discover -s tests` (synthetic audio and sets built in a temp folder; no audio in
  the repo). Add a test with every new check or writer, and for every bug you fix. Then test on real material in
  report mode and compare before/after numbers (the README quotes them). The run moves itself onto temporary folders
  and scrubs the developer's keys from the environment (`tests/_isolate.py`), and names at its start what it will
  skip (a missing extra or tool). Run one file as `python -m unittest tests.test_NAME`, or with discover as
  `-s tests -t . -p 'test_NAME.py'`: without `-t .` the run is not isolated and writes into the real folders.
  `.github/workflows/tests.yml` runs the suite on macOS and Windows (Python 3.9 and 3.12) for every push and pull request, so a test
  that only passes on a Mac shows up there (Windows has no Rubber Band, so the tests that need it are skipped, each saying so; the project does not test on Linux); read a red run before blaming the change.
- A tool that makes many moves gets a `--plan` (see `hypnomix/workflow/plan.py`): each move is a finding with a
  `plan` dict (`tool`, `file`, and a `step` or `key`), and the tool accepts "only these moves" so `fix` can run
  the approved subset.
- Before committing: no paid product names (nor the brand of a paid plug-in, a hardware product or its maker, an
  artist, a song title or a person: describe by function, "a classic six-operator FM synth", "a concert grand"), no
  home-folder paths of this computer, no audio files. The one exception is the Store catalogue
  (`hypnomix/store/catalogue.json`): it may name a free or open-source project and its publisher as the project styles
  it, and a credit that a licence requires (CC-BY, say), in the item's own `credit` field. `tests/test_repo_rules.py`
  checks every tracked file (the names as fingerprints, never in plain text; a short list of older mentions that
  cannot be reworded is kept in that file and can only shrink). Other agents may be committing here too: commit only
  the files you changed.
- Names: text a person reads says "HypnoMix" (capital H, capital M) and "HypnoMix Studio" (the third DAW, after Ableton
  Live and REAPER). What a program looks up or a person types stays as it is: `hypnomix scan`, `~/.hypnomix`, `.ardour`,
  `als2ardour`, `--ardour`, `Hypnomix.app`, the installer file names. The name of the underlying engine appears in text people read only
  where the origin of HypnoMix Studio is disclosed: `README.md`, `THIRD_PARTY.md`, the wiki article "HypnoMix Studio"
  (`28-ardour.html`), the Setup card for the add-on, the engine's licence notices in `packaging/` and the first step of
  the HypnoMix Studio courses. Everywhere else write "HypnoMix Studio", and "HypnoMix Studio sessions (`.ardour`)" for the files.

## Keep the wiki current (every change)

The app's Wiki tab, the website's wiki (https://hypnomix.bradfieldenterprises.org/wiki/) and the repository's GitHub wiki
are built from the files in this repo, so **every change that alters what a person sees or does updates its article in the same
commit**: a new command, option, check, fix, default or workflow, a renamed thing, a limit that is lifted.

| what changed | edit |
|---|---|
| how to use a feature | the guide that covers it, `docs/guides/NN-*.md` (the wiki reads the Markdown; there is no PDF to rebuild) |
| how a part works in depth | `docs/<TOPIC>.md`, or a new one (list a new file in `pyproject.toml`'s force-include) |
| the overview, setup, the rules | `README.md`, `GUIDE.md`, `AGENTS.md`, `CLAUDE.md`, `THIRD_PARTY.md` |
| a skill or a subagent | `skills/<name>/SKILL.md`, `agents/<name>.md` |
| lessons, install, the FAQ, how-to pages | `hypnomix/app/wiki/articles/NN-id.html` (`teaser:` is its home page summary) |
| a command's one-line description | `hypnomix/cli.py` (the command reference article is built from it) |
| the list of what HypnoMix does | the chores table (`README.md` and `25-chores.html`, the same rows), `26-features.html`, "Commands by job" above |
| what comes next, which DAWs can do what | `docs/ROADMAP.md`, then `27-next.html`, `28-faq.html`, `28-ardour.html`, `28-other-daws.html`, `18-setup.html` |

The tests hold the line: a command with no hand-written article, or a new top-level `.md` that the wiki does not
read, fails `python -m unittest discover -s tests`. Pushing to `main` publishes: the website rebuilds within
about 10 minutes and every copy of the app shows the newer articles. Never edit the website's wiki pages by hand.
The repository's GitHub wiki is a third copy of the same articles, built by `hypnomix/app/wiki_github.py` and pushed by
`.github/workflows/wiki.yml` on the same push: never edit it by hand either (the next build replaces every page).

More: `docs/WORKFLOW.md` (the loop in detail), `docs/LESSONS.md` (the mistakes these rules come from),
`docs/ROADMAP.md` (what to build next, other DAWs).
