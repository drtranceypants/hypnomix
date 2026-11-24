---
name: first-pass
description: Scan a whole song with every hypnomix tool at once (parallel subagents), then walk the person through the proposed fixes one at a time and apply only what they approve. Use when someone brings a new or unfinished song (a Live set) and asks to check it, scan it, "find what's wrong", do a first pass, or clean it up before mixing.
---

# First pass: scan everything, fix one thing at a time

Goal: find every technical problem in a song quickly, then let the person decide on each fix. Nothing changes
until they approve it, and the original set is never overwritten.

## 0. Set up (ask only what you can't find)

- The Live set (`.als`). Optional but valuable: a bounce of the full mix (`--mix`: loudness, true peak,
  release checks) and the mix or an instrumental for vocal tuning (`--ref`; defaults to `--mix`).
  `hypnomix separate mix.wav` makes an instrumental if they have none.
- The key, if they know it (`--key "F# major"`); otherwise the scan estimates it and you confirm it in step 3.
- Scan folder: `hypnomix-out/scan/<song>/` (or `--out`).
- Run `hypnomix name "<SET>" --out "<SCAN_DIR>/raw/names"` once, first: it labels tracks (lead vocal,
  harmonies, drums, guitar…) and the scanners reuse it. If it labels key tracks "Instrument" with low
  confidence, ask what they are, then pass `--vocal-track` / `--timing-track` explicitly.

## 1. Scan in parallel

Start one `hypnomix-scanner` subagent per group, **all in the same message** so they run at once:
`files`, `clips`, `timing`, `vocals`, `effects`, and `mix` (only with `--mix`). Give each the set path, scan
folder, group, and the `--mix/--ref/--key` values. They are read-only and return a short summary.

No subagents available? Run `hypnomix scan "<SET>" --mix … --ref … --key … --out "<SCAN_DIR>"` (it runs
the groups in parallel itself, `--jobs 4`).

## 2. Merge and summarise

`hypnomix scan --merge "<SCAN_DIR>"` writes `findings.json` and `REVIEW.md` (most severe first). Tell the
person, in a few lines: how many findings by severity, the biggest 3–5 problems, and anything a scanner
couldn't check (from the notes). Ask whether to start the review.

## 3. Review, one item at a time

Go down `REVIEW.md` in order. For each item:

1. Say what is wrong and where (track, bar.beat or m:ss) in plain words, what the proposed fix does, and what to
   listen for there. Copies of the same audio are already grouped: one decision covers them.
2. Ask: **approve / skip / change / approve the rest of this kind** (use the question tool if available, with
   approve first). "Change" means they want something different: note it as a by-hand item, or re-run that tool
   with different options (e.g. `--amount 0.6`) and re-merge.
3. Record the decision in `<SCAN_DIR>/decisions.json` (`{"id": "approve"|"skip"|"change", "note": …}`) and
   tick the box in `REVIEW.md`, so the review can be resumed later.

Batch the easy ones when they ask (e.g. all low-severity clicks at once), but always ask before any item marked
high. Confirm the key before approving any vocal-tuning item. `info` items are read-outs: summarise, don't ask.

## 4. Apply what was approved

1. The set must be **closed in Live** (Live overwrites edits on its next save). If another session is driving
   Live, message it first and wait for its OK.
2. All at once: `hypnomix fix "<SCAN_DIR>" --approve id1,id2,… --out "<Song> (fixed).als"`.
   Or, if they want to hear each change before the next: one id per run, chaining
   `--from "<Song> (fixed 1).als" --out "<Song> (fixed 2).als"`.
3. Report what `fix` printed: the new set's name, tuned vocal files (in `Samples/Tuned/`: put each on a new
   track at bar 1, warp off, and A/B with the original's mute), and the by-hand list. `fix-log.md` in the scan
   folder has the details.
4. Suggest the A/B: open the new set, compare the fixed spots with the original set at the same bars.

## Rules

- Never apply anything that wasn't approved. Never write over the original set or a source audio file.
- You measured; you did not listen. Tell them what to listen for.
- Tools that can't decide (a note halfway between two pitches, crowded hits that would stretch audibly, loop
  seams) say so: hand those to the person rather than guessing.
- Keep the human feel: timing fixes only touch outliers against the band, pitch fixes keep vibrato and slides.
