---
name: first-pass
description: Scan a whole song with every hypnomix tool at once (parallel subagents), then walk the person through the proposed fixes one at a time and apply only what they approve. Use when someone brings a new or unfinished song (a Live set), a folder of raw recordings or exported stems from any DAW, and asks to check it, scan it, "find what's wrong", do a first pass, or clean it up before mixing.
---

# First pass: scan everything, fix one thing at a time

Goal: find every technical problem in a song quickly, then let the person decide on each fix. Nothing changes
until they approve it, originals are never overwritten, and every applied fix is measured again.

## 0. Preferences, then set up (ask only what you can't find)

1. Run `hypnomix prefs`. If there are none, or keys are unanswered, ask the questions from
   `hypnomix prefs questions` one at a time in plain words (each has options, a default and a "why") and save
   with `hypnomix prefs set KEY=VALUE …`. Never fill them in yourself. If preferences exist, read them and
   follow them: review style, how much to explain, protected tracks, what is deliberate.
2. What to scan: a Live set (`.als`), or a folder of recordings / stems (any DAW; ask for full-length files
   from the same start point, processing off).
3. For a set, optional but valuable: a bounce of the full mix (`--mix`: loudness, true peak, release checks)
   and the mix or an instrumental for vocal tuning (`--ref`; defaults to `--mix`). `hypnomix separate mix.wav`
   makes an instrumental if they have none. The key if they know it (`--key "F# major"`).
4. Scan folder: `hypnomix-out/scan/<song>/` (or `--out`). Use an empty one per scan.
5. For a set, run `hypnomix name "<SET>" --out "<SCAN_DIR>/raw/names"` once, first: it labels tracks (lead
   vocal, harmonies, drums, guitar…) and the scanners reuse it. If it labels key tracks "Instrument" with low
   confidence, ask what they are, then pass `--vocal-track` / `--timing-track` / `--lead-track`.

## 1. Scan in parallel

Start one `hypnomix-scanner` subagent per group, **all in the same message** so they run at once.
A set: `files`, `clips`, `timing`, `vocals`, `effects`, and `mix` (only with `--mix`).
A folder: `recordings`, `stems`. Give each the path, scan folder, group, and the `--mix/--ref/--key` values.
They are read-only and return a short summary.

No subagents available? Run `hypnomix scan "<SET or FOLDER>" [--mix … --ref … --key …] --out "<SCAN_DIR>"`
(it runs the groups in parallel itself, `--jobs 4`).

## 2. Merge and summarise

`hypnomix scan --merge "<SCAN_DIR>"` writes `findings.json` and `REVIEW.md` (most severe first). Tell the
person, in a few lines: how many findings by severity, the biggest 3–5 problems, and **every check that did
not run** (the review lists them; an area whose check failed is not clean). If a number looks odd, check the
measurement before presenting it as a problem. Ask whether to start the review.

## 3. Review, one item at a time

Go down `REVIEW.md` in order. For each item:

1. Say what is wrong and where (track, bar.beat or m:ss) in plain words, what the proposed fix does, and what to
   listen for there. With `review.explain = teach`, add one sentence on the technique and why. Copies of the same
   audio are already grouped: one decision covers them. If the item has a `history` line, mention it.
2. Ask: **approve / skip / change** (use the question tool if available, with your recommendation first).
   "Change" means they want something different: note what, then re-run that tool with different options
   (e.g. `--amount 0.6`) and re-merge, or list it as a by-hand item.
3. Record it straight away: `hypnomix fix "<SCAN_DIR>" --decide <id>=approve|skip|change [--note "…"]`.
   The review can then stop and resume (`hypnomix fix "<SCAN_DIR>" --list` shows where you are).

Batch the easy ones only when they ask or their preferences say so ("all the low click fades"). Always one at
a time: anything **high**, anything **PROTECTED**, anything about taste (reverb, delay, tone, vocal level,
tuning amount). Things they listed as deliberate are not problems: don't propose fixes for them. Confirm the
key before approving any vocal-tuning item. `info` items are read-outs: summarise, don't ask.

## 4. Apply what was approved

1. A set must be **closed in Live** (Live overwrites edits on its next save, and unsaved Live changes are not
   in the file). If another session is driving Live, ask the person first.
2. `hypnomix fix "<SCAN_DIR>" --approved --out "<Song> (fixed).als"` (add `--key "<key>"` for tuning items).
   Or, to hear each change before the next: `--approve <one id>`, chaining
   `--from "<Song> (fixed 1).als" --out "<Song> (fixed 2).als"`.
3. If `fix` refuses (set changed since the scan, protected track, name exists, key not confirmed), tell the
   person what it said and do that. Never work around it.
4. Report exactly what `fix` printed: the new set's name; per tool, how many approved problems are **no longer
   measured** and which are **still measured**; anything **skipped** (no longer found) or **FAILED**; tuned
   vocal files (in `Samples/Tuned/`: put each on a new track at bar 1, warp off, A/B with the original's
   mute); repaired recordings (in `<SCAN_DIR>/fixed/`); and the by-hand list.
5. Give the A/B: open the new set, compare the fixed spots with the original at the same bars.
6. When the review is finished: `hypnomix prefs learn "<SCAN_DIR>"`.

Then stop and ask what they heard. Don't start another round on your own.

## Rules

- Never apply anything that wasn't approved. Never write over the original set, a source audio file or an
  earlier output.
- You measured; you did not listen. Tell them what to listen for, and let their ears overrule the number.
- Existing automation, effects and levels are the person's choices. Flag what looks odd; never "fix" it unasked.
- Tools that can't decide (a note halfway between two pitches, crowded hits that would stretch audibly, loop
  seams, a steady quiet sound that might be a pad) say so: hand those to the person rather than guessing.
- Keep the human feel: timing fixes only touch outliers against the band, pitch fixes keep vibrato and slides.
- Say plainly what failed or was not checked. "Done" means applied and measured again.
