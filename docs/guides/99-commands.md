---
title: Command Reference
subtitle: Every hypnomix command, by group, in one line each
file: 7 - Command Reference
---

# Every command

Run `hypnomix` for this list, `hypnomix <command> -h` for a command's full options and examples. Commands that change a Live set always write a new set next to the original.

## Engineer: stems in, song out

| command | what it does |
|---|---|
| `automix` | stems folder → balanced mix + master, with notes on every move |
| `master` | stereo mix → release master at a loudness target (or matched to a reference) |
| `chain` | build the mastering chain (or channel strips) in Live from stock devices: no paid plug-ins |
| `devices` | check every Live device by what it does (compressors, gates, limiters, EQ low cut) and suggest settings (writes a new set) |
| `duck` | duck the vocal reverb and delay: tune the ducking you have, or add a sidechained Compressor fed by the vocals (writes a new set) |
| `sidechain` | sidechain compressors: measure the ducking (depth, recovery, timing) and suggest settings |
| `masking` | which stems fight over which frequencies, and the cut that fixes it |
| `align` | phase/polarity/time offset between mics on one source |
| `translate` | mono, phone, earbuds, car, streaming normalisation, codec clipping |
| `qc` | release checks: format, silence, true peak, loudness, phase (exit 1 on fail) |

## Studio: recording real instruments

| command | what it does |
|---|---|
| `prep` | raw takes → mix-ready stems: clicks, clipping, plosives, breaths, hiss, silence, fades |
| `soundcheck` | set your input gain before recording; live meter |
| `takes` | rank takes by clipping, noise, pitch, timing; comp list per section |
| `vocalign` | align doubles and harmonies to the lead: timing, optional pitch match, formant |
| `alignset` | align vocal parts inside a Live set: warp markers on your own clips |
| `tune` | natural pitch correction: each note's centre to the song's tuning, vibrato and slides kept |
| `clipmatch` | even out clips recorded at different gain / mic positions (files or a Live track) |
| `dehiss` | spectral de-hiss + smart gate for one track (free stand-in for a spectral de-noiser) |
| `deess` | split-band de-esser for one vocal: turns down only the 's' moments, lists each one |
| `breaths` | turn breaths between phrases down (not off) on one vocal; report first |
| `voices` | re-arrange harmony stems into Voice 1 (lowest) … Voice N tracks: one fader per harmony step |
| `cleanup` | demo rescue: hum, noise, rumble, DC, silence |

## Ears: measure and compare

| command | what it does |
|---|---|
| `measure` | loudness, true peak, bands, stereo, tempo, key → JSON |
| `spectrogram` | spectrogram + loudness curve + average spectrum PNG |
| `key` | song key + section-by-section scale map with confidence; names the disputed note when unsure |
| `pitchcheck` | pitch (cents) + loudness difference between two captures: check every re-render |
| `clicks` | find clicks and crackle in renders and processed files |
| `punch` | transient punch / pumping / harmonics A/B at matched loudness |
| `stems` | who owns which band (and a resonance) in a folder of stems |
| `reference` | what it would take to sound like a reference  [extra: reference] |
| `match` | mix vs a reference as a list of proposals: tone by band, dynamics, width, loudness |
| `sections` | find the song's sections; loudness and vocal balance per section (give --bpm) |
| `separate` | split a mixed song into stems  [extra: ml] |
| `midi` | audio → MIDI (+ into a Live clip)  [extra: ml] |
| `critique` | second opinion from Gemini on a mix  [extra: critique, needs GEMINI_API_KEY] |

## Live: hands on the set (AbletonOSC)

| command | what it does |
|---|---|
| `live` | mixer, devices, VST parameters, transport, snapshots, arm/record |
| `loop` | play bars → record → measure → compare; one-change A/Bs |
| `diagnose` | solo every group in the loudest section: who owns the sub, bass, vocal band |

## Projects: REAPER (.rpp) and Live (.als)

| command | what it does |
|---|---|
| `project` | look inside a REAPER or Live project (tracks, folders, items, takes, plug-ins, automation) and render its tracks |

## Session files (.als, Live closed or open)

| command | what it does |
|---|---|
| `render` | render tracks from a .als to stems without opening Live (clip gain, fades, warps) |
| `name` | name every track and group by how it sounds (vocal, harmony, guitar, strings, drums…) |
| `mine` | tempo, key, tracks, plug-in chains, routing, levels from a set |
| `audit` | flags EQ, stacked limiters, bypassed devices; bounce vs your profile |
| `automation` | list/show/offset/dip automation envelopes (writes a new set) |
| `smooth` | find clicks, level jumps at cuts and spikes on clips; ease them (writes a new set) |
| `cliplevel` | lower harmony clips sitting well under the rest of their track: propose clip-gain raises (writes a new set) |
| `borrow` | offer unused loops from the song's original project as switched-off layers (MIDI nudged to the song's downbeat; writes a new set) |
| `motion` | keep repetitive sections alive: filter sweeps, reverb/delay throws, stutters, gate chops, drop-outs, as options learned from your own automation (writes a new set) |
| `unroll` | turn looped Arrangement clips into one copy per pass, so each pass can be edited on its own (writes a new set) |
| `edges` | clip edges and fades that cut into a word (a long fade-in ducking the first consonant, a comp edit that loses a sound) |
| `tidy` | retire switched-off tracks (after an archive copy) and put one instrument's clips on one track (writes a new set) |
| `order` | put tracks in working order (drums, bass, keys/guitar/synth, vocals, other; low to high) and vocal-stack clips on the track for their pitch (writes a new set) |
| `timing` | find hits out of time with the band; nudge only those with warp markers (writes a new set) |
| `tempomap` | map the tempo of a take played without a click; warp it to the grid, or make the grid follow it |
| `loops` | find the best loops in a free-played take; line them up in Session slots to try |
| `tighten` | pull a take's hits part of the way toward the click, in place (a gentle quantise) |
| `breathe` | let a click-recorded song breathe: small tempo changes by section, with a preview |
| `variations` | vary repetitive loops with unused takes, on new switched-off tracks next to each part |
| `distortion` | find audible distortion (clipped takes, overs, hot drive, fast bass compression); propose fixes |
| `refs` | find missing audio files in sets |
| `diff` | what changed between two sets, in plain words (faders, devices, clips, automation) |
| `check` | structural check of a written set before anyone opens it in Live (exit 1 on errors) |
| `profile` | build your sound profile from songs you love |

## Workflow: scan a song, review, fix

| command | what it does |
|---|---|
| `scan` | first pass: run every check on a set or a folder of recordings, change nothing, write REVIEW.md |
| `fix` | apply only the findings you approved, into ONE new set (original untouched) |
| `taste` | your tastes and standards from your own finished songs: levels, pans, sends, chains, vocals (TASTE.md) |
| `prefs` | your preferences, asked once: targets, protected tracks, how you like to review |
| `ab` | before/after clips for each proposed fix, level-matched, so you hear it before approving |
| `review` | the review as one page: play each A/B, tick approve / skip / change |

## App: no terminal, no AI needed

| command | what it does |
|---|---|
| `app` | the first pass in a window: choose a song, hear each fix, approve, apply (this computer only) |
| `device` | make the Max for Live device: review from inside Live, and jump Live to each finding |
| `aligndevice` | make the Hypnomix Align device: align a vocal stack from inside Live |

## Setup

| command | what it does |
|---|---|
| `install` | install the Live remote script, write Claude Code config |
| `doctor` | check Live, AbletonOSC, BlackHole, ffmpeg, plug-in parameter access |
