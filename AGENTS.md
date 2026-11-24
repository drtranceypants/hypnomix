# AGENTS.md: hypnomix for AI agents

Read this first if you are an AI agent (Claude Code, Codex, Cursor, Aider…) working with hypnomix, either
to use it on someone's music or to change its code. Humans: see `README.md` and `GUIDE.md`.

## What it is

A command-line mixing and mastering toolkit for Ableton Live (`hypnomix <command>`). Three kinds of tool:

- **File tools:** read audio files (stems, takes, mixes). Never need Live.
- **Session tools:** read a saved Live set (`.als`, gzipped XML) plus the audio its clips play. Live can be
  closed. Tools that change a set always write a **new** `.als` next to the original.
- **Live tools:** drive the open Live set through AbletonOSC (`hypnomix live`, `loop`, `diagnose`, `chain`).

## Setup

```bash
uv venv && uv pip install -e .     # Python 3.9+
hypnomix doctor                    # checks ffmpeg, Rubber Band, Live, AbletonOSC, BlackHole
```

`tune` and `vocalign` need Rubber Band 3+ (`brew install rubberband`). Run commands with
`hypnomix …` or `python -m hypnomix.cli …`. `hypnomix` with no arguments lists every command;
`hypnomix <command> -h` gives full help (the module docstring). Output goes to `hypnomix-out/` unless `--out`.

## Start here: the first-pass workflow

For "check my song / what's wrong / clean it up", use the workflow rather than individual tools:

```bash
hypnomix name  "Song.als" --out "hypnomix-out/scan/Song/raw/names"      # track roles, once
hypnomix scan  "Song.als" --mix mix.wav --ref instrumental.wav --key "F# major"   # read-only
#   → hypnomix-out/scan/Song/REVIEW.md + findings.json (most severe first, each with an id)
hypnomix fix   "hypnomix-out/scan/Song" --approve smooth-3,timing-12 --out "Song (fixed).als"
```

The scan changes nothing. Review the findings **one at a time with the human** and apply only what they
approve. Claude Code: the `first-pass` skill (`skills/first-pass/SKILL.md`) does this with parallel
`hypnomix-scanner` subagents (`agents/`). Details: `docs/WORKFLOW.md`.

## Commands by job

| job | commands |
|---|---|
| Find problems in a set (read-only) | `scan` (all of the below), `smooth`, `timing`, `distortion`, `sidechain`, `audit`, `refs`, `mine` |
| Fix a set (writes a new `.als`) | `fix` (approved scan findings), `smooth --apply`, `timing --apply`, `distortion --apply`, `sidechain --apply`, `automation offset/dip` |
| Vocals | `tune` (pitch), `vocalign` (timing vs lead), `voices` (harmony stack by pitch), `takes` (rank takes), `dehiss` |
| Raw takes / stems | `prep`, `cleanup`, `clipmatch`, `render` (tracks from a set to WAVs, no Live) |
| Mix and master files | `automix`, `master`, `masking`, `align`, `translate`, `qc` |
| Measure / compare | `measure`, `spectrogram`, `pitchcheck`, `clicks`, `punch`, `stems`, `reference` |
| Inside Live | `live` (faders in dB, devices, plug-in params, snapshots), `loop` (record bars, A/B), `diagnose`, `chain`, `name --apply` |

Every tool prints a human report. Most analysis tools also take `--json OUT.json`; `smooth`, `timing` and
`distortion` give each finding an `id`, and `--apply OUT.als --ids id1,id2` fixes only those.

## Rules (they protect the person's work)

1. **Report before you change.** Run the read-only form first, show the findings, get approval per change.
2. **Never overwrite** the person's `.als` or source audio. Set writers refuse a path equal to the input and
   refuse a folder other than the original's (samples linked by relative path go offline elsewhere).
3. **Close the set in Live before writing a new `.als`** from it: Live overwrites the file on its next save.
   Another agent may be driving Live; ask before quitting, opening or saving anything in Live, and never
   choose "Save" on a set you didn't create.
4. **Respect automation.** Setting an automated control overrides its envelope: check
   `hypnomix automation list Song.als` first; after Live edits run `hypnomix live reenable`.
5. **Keep it human.** `timing` only nudges outliers against the band (downbeats tight, upbeats loose);
   `tune` moves note centres and keeps vibrato and slides; `smooth` eases jumps instead of flattening them.
   When a tool says it can't decide (ambiguous note, crowded hits, loop seam), hand it to the person.
6. **You measured, you didn't listen.** Tell the person what to listen for and where (bar.beat or m:ss).
7. **Free tools only.** Code and docs here use free, open-source or Live's stock devices. Don't add or name
   paid plug-ins anywhere in this repo.

## Changing the code

- One command = one module; register it in `hypnomix/cli.py` (`GROUPS`) and add a row to `README.md`.
- Module docstring = the command's help (what it finds, how it fixes, usage). Keep it current.
- Session tools follow `hypnomix/session/smooth.py`: parse with `hypnomix/session/automation.py` helpers
  (`load`, `save`, envelopes), map clips to audio with `smooth.clip_info` / `file_seconds` (warp markers,
  loops, clip gain), report by default, `--json` with ids, `--apply OUT.als` (+ `--ids`) to a new set.
- Facts about the `.als` format that the code relies on (checked in Live 12.4): arrangement clips live in
  `DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events`; take lanes are separate; clip fade lengths
  are in **beats**; mixer volume is linear gain (1.0 = 0 dB, max 1.995 = +6 dB); a track is off when
  `Mixer/Speaker/Manual` is `false`.
- New checks should plug into `scan` (`hypnomix/workflow/scan.py`): add a group function returning
  normalised findings `{id, tool, kind, severity, track, where, problem, fix, applies}` and, if it writes a set,
  a step in `hypnomix/workflow/fix.py`.
- Test on real material in report mode first; compare before/after numbers (the README quotes them).
  There is no unit-test suite yet: verify by re-measuring the output (e.g. `tune` re-tracks pitch, `timing`
  re-scans the new set).
