---
name: tracking-session
description: Run a recording session for real instruments and vocals in Ableton Live with hypnomix: set input gain, route and arm tracks, punch-record takes, pick and comp the best take, align doubles, even out clip levels. Use when someone is about to record, is recording, or has raw takes to sort out.
---

# Tracking session

## Before recording
1. `hypnomix soundcheck --list`, then `hypnomix soundcheck --device "<interface>" --channel N` while they play the loudest part. Relay the advice exactly: aim for peaks of -12 to -6 dBFS in 24-bit. Hum or noise means fix the source (cable, socket, distance), not plugins.
2. `hypnomix soundcheck --watch` gives a live meter while they adjust the preamp.

## Recording in Live (AbletonOSC)
- `hypnomix live inputs <track>`, then `hypnomix live input <track> "Ext. In" "2"` to route interface input 2.
- `hypnomix live arm <track> 1` and `hypnomix live monitor <track> auto`.
- `hypnomix live record <bar> <bars> <passes>` punch-records with one bar of pre-roll. Several passes give several takes in Live 12's take lanes.
- Always confirm before recording. It writes into their set.

## After recording
- Export the takes from the same start bar, then run `hypnomix takes t1.wav t2.wav t3.wav --bpm <tempo>` (`--no-pitch` for drums or chords). Give the best whole take and the comp list per section.
- Doubles and harmonies: `hypnomix vocalign lead.wav double.wav --trim-tails`.
- Clips recorded on different days or at a different mic distance: `hypnomix clipmatch --als Set.als --track "Vox"` shows the gain and tone differences, and `--apply` sets Clip Gain in the open set. Confirm first and suggest saving a copy of the set.
- Two mics on one source: `hypnomix align close.wav far.wav`.
- Then `hypnomix prep` before mixing.
