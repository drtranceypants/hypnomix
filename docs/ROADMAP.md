# Roadmap

What to build next, in order, and how hypnomix reaches Logic Pro and Pro Tools. The aim stays the same: help
an independent artist get from recordings to a release quickly, with free tools, and with the person deciding
every change.

Items marked *(to verify)* rest on research that has not been tested here yet.

**Built since this was first written** (sections 1 to 3 below are kept for the reasoning): `ab`, `diff`, `check`,
the review page (`review`), the wider scan (noise under clip gain, harmony timing, mic phase, masking as
findings, the "is this deliberate?" inventory, sections, `--like`), `--plan` for `prep` / `automix` / `master`,
`deess`, `breaths`, `sections`, `match`, and a first test suite. Still open from those sections: `balance`,
`plugins`, `listen`, `handoff`, the profile comparison in scan, masking fixes written into a set as stock EQ
bands, and previews for timing nudges and device changes. `deess`, `breaths`, `sections` and `match` need real
songs before they are trusted.

**Tempo and variety (built, see `docs/TEMPO.md`):** `tempomap`, `loops`, `tighten`, `breathe`, `variations`.
Open: opening their sets in Live; a first-bar-line check that does not rely on the low end; matching spare
takes to a part by sound, not only by recording name; `variations` findings in the review page.

**Also built since:** `key` (by section), `order`, `duck`, `cliplevel`, `motion`, `borrow`, `taste`,
`voices` balance with `--learn` (as heard, written as volume automation), word-by-word `vocalign`, `devices`,
`tidy`, `unroll`, and in `timing`: grid detection (straight, triplets, mixed), MIDI, and passes (drums, then
bass toward the drums, then the rest). Open for all of them: more real songs, and opening every written set in Live.

**Inside Live, faster reviews, mastering (built, see `docs/LIVE.md`, `docs/MASTERING.md`, `docs/PLUGINS.md`,
`docs/LIBRARY.md`, `docs/WORKFLOW.md` 4b):** `probe` (Max for Live meters on every track, after their plug-ins; one
play of the song is a deep scan), the probe menus and HypnomixMain's song card (read by `scan` from the set),
Record and review before export, `abset` (every fix as a switched-off B inside Live; A / B / Blind with loudness
matching), `plugrender` (offline renders through real VST3/AU chains; `ab --plugins`), `taste --library`
(style and where to improve, from every set on the computer), mastering stages (`tonal`, `--stabilize`, `--dyneq`,
`--width-bands`, `--limiter-mode`, `--harsh`, dither, `rebalance`, `translate --preview`), amounts per decision,
grouped decisions, a question budget, teach, collaborator export/merge, `history` and undo, `scan --quick` and
`--since`, `watch`, the render cache. Open: loading the three devices in Live on a real set (tested against a
simulated Live API only); `sfrecord~` settings in Live; take lanes as the A/B switch for clip fixes (the LOM
support needs checking); an EQ Eight model for `plugrender`; Audio Units that crash in the offline host; the
probe's numbers next to a full-file meter on the same song.

**Next idea: `colour`.** Propose new timbres for a song that sounds the same throughout: an effect chain from
stock devices or installed free plug-ins on a copy of a part, or a new instrument doubling a line (from
`midi`), each on a new switched-off track like `variations`, each with a before / after clip. Needs the
`plugins` list (item 17) so it only proposes what is installed.

## 1. Make the review audible and visible

The review is the product. Right now it is text; it should be something you can hear and see.

| # | tool | what it does | stands on |
|---|---|---|---|
| 1 | `ab` | For each proposed fix, render the few bars around it before and after, **at matched loudness**, into `REVIEW/ab/<id> A.wav` / `B.wav`. The person hears the proposal before approving it. | `render`, `measure` |
| 2 | `diff` | Plain-language difference between two sets: track → device → parameter, before → after; clips faded, markers added. Shown before approval and logged after. | `automation` helpers |
| 3 | `check` | Structural check of a written set before anyone opens it: no duplicate ids, every automation target resolves, Live version on the tested list, unchanged parts identical to the original. | `automation` helpers |
| 4 | review page | `REVIEW.html` next to `REVIEW.md`: play A/B, tick approve / skip / change, writes `decisions.json`. No server, one file. | `ab`, `decisions.json` |

## 2. Widen the scan

Checks that exist as tools but are not in the first pass yet, and a few new ones.

| # | check | what it adds to `scan` |
|---|---|---|
| 5 | noise | Per track: noise floor of the rendered track, and a warning where large clip gain sits on a noisy take. Fix: `dehiss` on the source, as an `audio` item. |
| 6 | doubles | Timing of doubles and harmonies against the lead (`vocalign` in report mode). Vocals currently get pitch only. |
| 7 | phase | Multi-mic sources (kick in/out, DI + amp): offset and polarity (`align`). |
| 8 | masking | Render the groups, run `masking`, and turn each fight into a finding with a concrete cut. In Live the fix is a stock EQ band (`set`); for a folder it is a rendered copy (`audio`) plus the to-do. |
| 9 | intent | An inventory of what is automated and what is unusual (very long tails, hard-panned parts, big boosts), listed as "is this deliberate?" questions at the first scan and saved to preferences. |
| 10 | sections | Find verse / chorus / bridge, then report loudness and vocal-to-band balance per section: "the second chorus is 2 dB quieter than the first". |
| 11 | profile | Compare the mix with the person's own profile ranges (`profile build`), not only fixed targets. |

## 3. New tools

| # | tool | what it does |
|---|---|---|
| 12 | `deess` | Split-band de-esser for one vocal file: turns down only the "s" moments, reports each one. |
| 13 | `breaths` | Standalone breath and mouth-noise control (today only inside `prep`), report first. |
| 14 | `--plan` for `prep`, `automix`, `master` | These apply many moves in one go. `--plan` writes the same moves as findings into a scan folder, so they go through the same review, and `fix` renders only the approved ones. |
| 15 | `balance` | A static first balance for a folder of stems as proposals: fader per part, with the measurement behind each. |
| 16 | `match` | Reference matching as findings: "your low end is 3 dB heavier than the reference between 60 and 120 Hz", each with a proposed move. |
| 17 | `plugins` | List the free plug-ins installed on this computer, check each loads without its window, and save the list to preferences so proposals only name what is there. |
| 18 | `listen` | Optional: a local, open-weights audio model writes "listening notes" on a bounce. Advice only, labelled as such, never a source of numbers. Runs on the person's machine. |
| 19 | `handoff` | Turn the by-hand list into the person's DAW's terms and, where possible, into markers at each spot. |

## 4. Trust

| # | item | why |
|---|---|---|
| 20 | test suite | Small synthetic sets and audio files with known problems; every writer round-trips them; `fix` is tested for skipped, stale and protected cases. Nothing public should rely on "it worked on my song". |
| 21 | Live versions | A tested-versions list for the set format; refuse to write a set from an unknown newer version without `--force`. |
| 22 | Windows and Linux | Install steps, loopback capture without a macOS-only device, remote-script paths. |
| 23 | verify the Live tools | `chain` and `clipmatch --als --apply` tested in Live, or kept behind `--dry-run`. |

## 5. Other DAWs

Only Ableton Live stores a project as XML that can be read and rewritten safely. So support comes in tiers,
and the review loop is identical in every tier: the same findings, the same decisions, the same "new files only".

```
            tier 0: audio          tier 1: read project        tier 2: drive the app
Ableton     yes (scan FOLDER)      yes (.als)                  yes (write new .als; OSC)
REAPER      yes                    yes (.rpp is text)          planned (write new .rpp)
Ardour      yes                    yes (.ardour is XML)        planned (write new .ardour; Lua, OSC)
Pro Tools   yes                    planned (session text)      planned (scripting SDK)
Logic Pro   yes                    experimental                control surface only
```

**Tier 0, any DAW (works today).** Export each track full-length from the same start, processing off.
`hypnomix scan FOLDER` → review → `fix` writes repaired copies; DAW moves are a to-do list. Next: `handoff`
(item 19) and `--plan` (item 14) make this tier much stronger, and it is where most of the value is.

**A session model first.** Before any second DAW: one neutral description of a session (tracks, roles, clips
with positions and gains, device names, tempo, markers) that every reader fills and every check consumes.
`scan` then runs on the model, not on `.als` XML. The open DAWproject format is a good shape to follow
*(to verify: it is supported by several DAWs but not Logic Pro or Pro Tools)*.

**REAPER (do this second).** Its project file is plain text and its scripting API covers effects, envelopes
and rendering, so it can reach the same level as Live: read the project, write a **new** project with approved
changes. It also hosts free plug-ins on every platform. Roughly a week once the session model exists.

**Ardour (free and open source, Mac, Windows, Linux).** Reading works: `hypnomix/project/ardour.py` reads
sessions from Ardour 3 to 9 (sample times before Ardour 7; superclock and beat times after), with region
layering, fade curves, gain envelopes, multi-channel regions, buses and aux returns. Next, as for REAPER: write a
**new** `.ardour` with approved changes (region gain, fades, fader and pan, mute), then drive the open session
through its Lua scripting and OSC for `chain` with Ardour's own ACE plug-ins (EQ, compressor, expander, delay,
reverb). Not yet checked against Ardour itself: open a session saved by Ardour 8 or 9, compare our renders with
its own export, and confirm pan direction and the trim gain.

**Pro Tools.**
- *Read:* the "session info as text" export (tracks, clips, markers) parsed into the session model: no app
  control, works on every edition. An open-source reader for session files exists and can be an optional extra
  *(to verify: what it covers)*.
- *Drive:* the official scripting SDK (a local service, in every edition since late 2022 *(to verify)*): read
  the track list, add markers at each finding, import repaired audio as new tracks, bounce for a re-scan, and
  "save session as" before any write. Read-only by default; every write approved. It does not appear to control
  plug-ins or write automation *(to verify)*, so tone and dynamics moves stay as rendered audio or to-dos.
  The SDK's interface file has its own licence: have the person download it rather than shipping it here.
- *Write offline:* an AAF with repaired clips for import, as the "new file" path *(to verify)*.

**Logic Pro.** The project is an undocumented binary bundle. Reading track names, plug-in lists and tempo is
possible but fragile (experimental, fail-soft). Writing it is not safe and is not planned. Logic has no
scripting API for the mixer; the reliable route for live moves is to act as a control surface (faders, pans,
mutes over a virtual MIDI port), with interface scripting only for bounce and export. Its built-in assistants
have no programmatic access: where they help, the review says "run this, bounce, and I'll measure the result".
Expect anything beyond tier 0 to need upkeep with each Logic release.

**Order:** tier 0 polish (14, 19) → session model → REAPER → Ardour → Pro Tools read → Pro Tools drive → Logic read →
Logic control surface.

## Not planned

- Changing a project file in place, in any DAW.
- One-click "finish my song". Every assistant in this field that people trust keeps its moves visible,
  editable and reversible; the ones people abandon act as a black box.
- Anything that sends audio off the person's computer without asking each time.
- Naming or depending on paid plug-ins.
