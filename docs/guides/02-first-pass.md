---
title: The First Pass
subtitle: Preferences → scan → review → fix → verify, the safe way to clean up a song
---

# The loop

The first pass is the fastest safe way to clean up a song. Every check runs at once, nothing changes until
you approve it, every approved change lands in new files, and the result is measured again.

<!--toc-->

```
 prefs (once) ─► scan ─► review (you) ─► fix (only approved) ─► listen ─► prefs learn
                  │            │                 │
           changes nothing   A / B players    one NEW set, measured again
```

## 0. Preferences (once)

| setting | what it does |
|---|---|
| targets | loudness and true peak the mix check compares with (default -14 LUFS, -1 dBTP) |
| protect.tracks | findings on these tracks are marked PROTECTED; fix refuses them until you say yes again |
| protect.notes | things that are deliberate, printed at the top of every review so nobody "fixes" them |
| review, taste, tools | how you like to review, how strict tuning and timing should be, your free plug-ins |
| learned | after each review, what you approved and skipped per kind of finding: advice for next time, never applied by itself |

```bash
hypnomix prefs set targets.lufs=-14 targets.true_peak=-1 review.style=one-at-a-time \
                   protect.tracks="Lead Vox,Strings" protect.notes="long reverb tail in the outro"
```

## 1. Scan (read-only)

In the app: **Songs → choose a set → Start the first pass**. In the terminal:

```bash
hypnomix scan "Song.als" --mix "Song mix.wav" --ref "Song instrumental.wav" --key "F# major"
hypnomix scan "Song.rpp"            # a REAPER project: the same loop (guide 8)
hypnomix scan "Song.ardour"         # an Ardour session (or its folder)
hypnomix scan "raw takes/"          # recordings or stems from any DAW: no Live set needed
```

| option | why give it |
|---|---|
| `--mix` | a bounce of the whole song: loudness, true peak, release checks |
| `--ref` | the mix or an instrumental: the song's real tuning (songs are often not at A=440) and the chords under the vocals |
| `--key` | the key, confirmed by you; vocal tuning is never applied without it |
| `--deep` | renders every track and reports frequency fights and mic phase |
| `--like REF.wav` | tone, dynamics, width and loudness against a song you love, as proposals |

What a set scan checks, in parallel groups:

| group | checks |
|---|---|
| names | default track names → names by sound; track order and vocal-stack parts by pitch |
| files | missing audio |
| clips | clicks, level jumps at comp cuts, spikes; fades and edges that cut into a word |
| timing | hits out of time with the band (the song's own grid, drums first, then bass) |
| vocals | pitch of every vocal, harmonies against the lead, doubles' timing, harmony balance |
| effects | distortion in takes and device chains, sidechain ducking, every compressor and gate |
| mix | loudness, true peak, release checks (needs `--mix`); with a profile (`hypnomix profile build`), also the mix against your own ranges, as things to listen for (`--no-profile` skips it) |

The result is `REVIEW.md` and `findings.json`, most severe first, each item with an id. `REVIEW.md` explains each
kind of fix once, near the top ("Why these fixes"); each item holds only what is its own. If a check could not
run, the review lists it under **Checks that did NOT run**: no findings from a check that didn't run means
nothing.

**Scanning again.** Scan the same song into the same folder after you have changed it, and the decisions you made
follow their findings by what they are (same tool, track, kind and place), never by their number. "smooth-1 =
approve" cannot end up on a different clip because the list got shorter. Decisions that no longer match anything
are counted ("3 earlier decisions no longer match a finding and were set aside"), kept in
`decisions-orphaned.json` and never applied. Two songs with the same name ("Song.als" and an Ardour session also
called "Song") get separate folders, "Song" and "Song (2)".

## 1b. Hear it first

The app builds the before / after clips for you. In the terminal:

```bash
hypnomix ab "hypnomix-out/scan/Song"               # level-matched before / after clips
hypnomix review "hypnomix-out/scan/Song" --serve   # a page with players and buttons
```

Previews cover clip fixes, vocal tuning, repaired recordings, timing nudges (the clip stretched along its warp
markers, pitch kept), frequency-fight cuts, and changes to Live's Compressor, Glue Compressor, Gate, EQ Eight,
Utility and Limiter. A device preview is **a model of the device, not Live itself**, and says so on the page. What
can't be previewed offline (a Saturator or Reverb change, a plug-in, a return track, a MIDI note moved by a nudge)
says why next to the item: apply that one fix into a new set and listen in Live. `ab` plays Live sets and folders
of recordings. On a REAPER project it plays repaired recordings and says, for each other fix, why it has no clip; `abset` builds
a project with each fix switched off next to yours (guide 8), or apply one fix at a time and listen.

When `--deep` finds two parts fighting over a band, the fix is a bell cut on the part that should give way (2-3 dB
by default, adjustable per decision with the amount, e.g. approve at 50%). Approved, it is written as one band on
the track's own EQ in a new file: an EQ Eight in Live, a ReaEQ in REAPER. An EQ that is already there and has a
free band is reused; nothing else on the track changes. `fix` runs hypnomix's structure check on these new sets and
projects. The ReaEQ band was opened in REAPER 7.86 and read back as written, but the EQ Eight band has not yet been opened in Live, and neither has been judged by ear: open one and listen before you keep it. On a folder of
stems there is no set to write into, so the cut stays on the by-hand list (section 5).

## 2. Review: one item at a time

Every finding has a severity (high, medium, low, info), a track, a place (bar.beat or m:ss), the problem, the
proposed fix, and how it applies:

| applies | meaning | done by |
|---|---|---|
| set | a change to the Live set | `fix`, into one new set |
| audio | a new audio file (a tuned vocal, a de-hissed take) | `fix`; you put it on a track |
| manual | needs your hands or ears in the DAW | you |
| info | a measurement | nothing |

**From inside Live:** drag the **Hypnomix** device (`hypnomix device`) onto any track. With the app open on
a review, Prev / Next / Next open step through the findings and Live jumps to each one: the track is
selected, the playhead and loop brace move to the spot, the clip opens. Approve and Skip record your decision
exactly like the app. Nothing is applied from inside Live. Press **Float** on the device first: each jump
selects the finding's track, so Live shows that track's clip where the device was, and the floating panel
stays in view while you step.

**In the terminal:**

```bash
hypnomix fix "hypnomix-out/scan/Song" --decide smooth-14=approve,timing-7=skip
hypnomix fix "hypnomix-out/scan/Song" --decide tune-Lead=change --note "lighter on the verse"
hypnomix fix "hypnomix-out/scan/Song" --list
hypnomix fix "hypnomix-out/scan/Song" --list --undecided --top 15     # the next ones, on a long scan
hypnomix fix "hypnomix-out/scan/Song" --show smooth-14                 # one finding in full
```

`--list` also takes `--severity high|medium|low|info`, `--tool NAME` and `--offset N` (to page). `--decide` and
`--approve` can be repeated, and each takes a comma list.

> Tip: high-severity items, protected tracks and anything about taste are always asked one at a time.

## 3. Fix: only what you approved

Close the set in Live first. In the app: **Apply**. In the terminal:

```bash
hypnomix fix "hypnomix-out/scan/Song" --approved --out "Song (fixed).als"
```

Before it writes anything, fix prints every file it is about to create, and an "Also applied because they are on by
default" block: the clean-ups that run with `--approved` unless you skipped them (track order, retiring switched-off
tracks). Skip them first, or add `--no-defaults`, to apply only what you approved by name. At the end it prints "Not applied": what you decided as "change", what has to be done by hand, and what was no
longer found, each with what to do next.

The order inside the new set: distortion settings → sidechain settings → clip fades and volume eases →
warp-marker nudges → track order and stack clip moves → track names. To hear each change on its own, apply one
id per run and chain them with `--from "Song (fixed 1).als" --out "Song (fixed 2).als"`.

What fix checks, and stops on:

| check | what happens |
|---|---|
| the set was saved after the scan | stops; scan again (or `--stale-ok` if the change is unrelated) |
| the output exists, or is the original | stops: nothing is ever overwritten |
| a finding is on a protected track | stops; ask again, then `--allow-protected` |
| vocal tuning without a confirmed key | refused; pass `--key`, or `--key sections` for a song that changes key |
| a finding is no longer in the set | skipped and listed, never swapped for its neighbour |
| after writing: structure | `hypnomix check` runs; a broken set is renamed "(BROKEN, do not open)" |
| after writing: what changed | every change in plain words in `fix-log.md` (`hypnomix diff OLD NEW`) |
| after writing: result | measured again: "N of M approved problems no longer measured" |

Ardour: the same command with `--out "Song (fixed).ardour"` writes the approved region fades (with their curve),
region gain, gain dips over spikes and the eased level at a comp cut into **one new snapshot**, saved next to your
session file inside the same session folder (where Ardour keeps its own snapshots, so the new file finds the same
recordings). Track names and order, vocal stacks, timing, sidechain and tuning stay by hand. The new file is read
back and checked by hypnomix, and has not yet been opened in Ardour.

## 4. Listen, then teach it

The numbers say a problem is gone; only your ears say it sounds right. Open the new set and A/B the changed
spots. Then:

```bash
hypnomix prefs learn "hypnomix-out/scan/Song"
```

Next time, the review shows what you usually do ("in past reviews you skipped 9 of 10 like this").

## 5. What is left for your hands: handoff

`fix` writes what it can and lists the rest under "Not applied" or as "by hand". `handoff` turns that list into a
job you can walk down in your own DAW:

```bash
hypnomix handoff "hypnomix-out/scan/Song"
hypnomix handoff "hypnomix-out/scan/Song" --bpm 96 --daw reaper     # stems folder: give the tempo for bar.beat
```

It collects every approved finding that `fix` cannot make itself, and every one you skipped or changed with a note
(your words are kept on the line; `--undecided` adds the by-hand findings you have not answered). It writes, into
`handoff/` in the scan folder and never over anything:

- `HANDOFF.md`: a checklist in song order. Each line has the track, the bar.beat and m:ss, what to do in your DAW's
  own words (Live, REAPER, Ardour or plain wording: `--daw`, or your `tools.daw` preference) and what to listen for.
- when at least one item has a position, a marker at every such spot: a new `Song (handoff).als` with a locator at each
  (Live scan), a new `Song (handoff).rpp` with a marker at each (REAPER scan), and `markers.mid` and `markers.csv` for
  DAWs that import them. If no item has a position, only `HANDOFF.md` is written. `--no-markers` writes the checklist
  only.

An item with no position (a whole part) is listed at the end, without a marker. The new Live set is checked with
`hypnomix check` and the new REAPER project is read back and compared with yours; the REAPER project's marker was opened in REAPER 7.86 and read back as written, and the Live set has not yet been opened in Live. `handoff` itself is new: it passes unit tests and hypnomix's own checks on synthetic data and has not yet been run on a
real song. The checklist is measured, not heard: your ears decide each line.

## Plans: tools that make many moves

`prep`, `automix`, `master` and `balance` can also work as a review instead of doing everything at once:

```bash
hypnomix prep "raw takes/" --plan
hypnomix automix "stems/" --plan
hypnomix master "Song mix.wav" --plan
hypnomix balance "stems/" --plan        # one fader move per part, faders only
```

Each move becomes a finding, reviewed like any other; `fix --approved` then runs the tool with only the
approved moves. `preflight`, `album` and `colour` take `--plan` too: the same review, for file problems (guide 1),
for the songs of a record (guide 6) and for new colours (guide 5).

## Other DAWs

Export every track as a full-length file from the same start, processing off, then
`hypnomix preflight "that folder/"` (are the files fit to work on?) and `hypnomix scan "that folder/"`. Repaired
audio comes back as new files; anything that has to happen in the DAW (an EQ cut, a fader move) is listed as a
to-do, and `handoff` turns that list into a checklist with markers.

## What the checks deliberately leave alone

- **Feel**: timing measures the band's own looseness and flags only outliers; tuning keeps vibrato, scoops and slides.
- **Taste**: harmony balance, how far a part moves, how hard a note is pulled are options with fine controls, never a fixed rule.
- **Intent**: automation, effects and levels you set are treated as choices.
- **Undecidable cases** go to you: a note halfway between two pitches, a hit too crowded to stretch cleanly, a sound that might be hiss or a pad.
