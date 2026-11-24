# First pass: scan → review → fix

The fastest safe way to clean up a song: every check runs at once, nothing changes until a person approves
it, and every approved change lands in **one new set** next to the original.

```
             ┌─ files    (refs)          missing audio
             ├─ clips    (smooth)        clicks, level jumps at cuts, spikes
 Song.als ───┼─ timing   (timing)        hits out of time with the band
  (+ mix)    ├─ vocals   (render+tune)   pitch of every vocal, harmonies vs lead
             ├─ effects  (distortion,    distortion in takes and device chains,
             │            sidechain,     sidechain ducking, device-chain audit
             │            audit)
             └─ mix      (measure, qc,   loudness, true peak, release checks
                          translate)     (needs --mix)
                    │
                    ▼
     findings.json + REVIEW.md  (most severe first, each with an id)
                    │  person: approve / skip / change, one item at a time
                    ▼
     hypnomix fix --approve … --out "Song (fixed).als"
```

## 1. Scan (read-only)

```bash
hypnomix name "Song.als" --out "hypnomix-out/scan/Song/raw/names"   # track roles: lead, harmonies, drums…
hypnomix scan "Song.als" --mix "Song mix.wav" --ref "Song instrumental.wav" --key "F# major"
```

- `--mix`: a bounce of the whole song (loudness, true peak, release checks, and a fallback for `--ref`).
- `--ref`: the mix or an instrumental. The vocal check measures the song's real tuning from it (songs are often
  not at A=440; one test song sat at A=435.4 Hz) and its key. `hypnomix separate mix.wav` makes an instrumental.
- `--key`: confirm it; it only decides notes sung near a quarter-tone.
- Groups run in parallel (`--jobs 4`). To spread them over several agents, run one group each with
  `--only GROUP --out SAME_DIR`, then `hypnomix scan --merge SAME_DIR`.
- Track roles come from `hypnomix name`; override with `--vocal-track` / `--timing-track` when it's unsure.

Output in `hypnomix-out/scan/<song>/`: `REVIEW.md`, `findings.json`, one `<group>.json` per group, and `raw/`
(each tool's own report, renders of the vocal tracks).

## 2. Review (one item at a time)

Each finding has: `id`, `severity` (high / medium / low / info), `track`, `where` (bar.beat or m:ss), the
`problem`, the proposed `fix`, and how it `applies`:

| applies | meaning | done by |
|---|---|---|
| `set` | a change to the Live set | `hypnomix fix` (into one new set) |
| `audio` | a new audio file (pitch-corrected vocal) | `hypnomix fix` writes it to `Samples/Tuned/`; you put it on a track |
| `manual` | needs hands or ears in Live (e.g. a loop seam, a crowded hit) | you |
| `info` | a measurement | nothing |

Copies of the same audio (a repeated loop, a pasted chorus) are grouped under one finding. Decisions can be kept
in `decisions.json` in the scan folder so a review can be resumed.

## 3. Fix (only what was approved)

Close the set in Live first, then:

```bash
hypnomix fix "hypnomix-out/scan/Song" --approve distortion-2,smooth-14,timing-7,tune-Lead --out "Song (fixed).als"
```

Order inside the new set: distortion parameter fixes → sidechain settings → clip fades and volume eases → warp-
marker nudges. Each step re-runs its tool on the previous step's set with the approved ids only. To hear each
change before the next, apply one id per run and chain them with `--from "Song (fixed 1).als" --out "Song (fixed 2).als"`.
`fix-log.md` records every run.

## With Claude Code

The `first-pass` skill runs the whole thing: one `hypnomix-scanner` subagent per group in parallel, a merged
summary, then the review one item at a time (approve / skip / change), then `fix`. Ask:

> "Do a first pass on ~/Music/Song Project/Song.als. The mix is Song.wav."

## What the checks deliberately leave alone

- **Feel.** `timing` measures the band's own looseness and only flags outliers (downbeats held tightest,
  16ths loosest), comparing each instrument with the others before the grid; `tune` keeps vibrato, scoops and
  slides and only moves each note's centre.
- **Music.** Drum-like tracks aren't checked for spikes; loops that grow louder by design aren't "jumps";
  lasting level changes inside a take are only checked with `smooth --steps`.
- **Undecidable cases** are flagged for a person: a note sung halfway between two pitches, a hit with
  neighbours too close to stretch cleanly, a loop seam that clicks.
