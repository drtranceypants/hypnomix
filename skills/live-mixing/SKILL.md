---
name: live-mixing
description: Mix inside the open Ableton Live set with hypnomix through AbletonOSC: exact fader dB, sends, pans, any device or plug-in parameter (VST/AU, no mouse or screen control), looped A/B captures measured against the person's profile. Use when someone wants changes made in their Live session rather than on exported files.
---

# Mixing in Live

Requirements: `hypnomix doctor` shows Live connected; for `loop` also BlackHole and a Multi-Output Device.

Mixing in the open set is the last resort: prefer `hypnomix scan` + `fix` (new set, nothing overwritten) when
the job can be done on the saved file. Read `hypnomix prefs` first (protected tracks, what is deliberate).

## Safety rules
- **One change, one approval.** Propose the move, get a yes, make it, A/B it, report the numbers and what to
  listen for. After three moves, stop and ask what they hear.
- **One driver.** If another agent or session may be using Live, ask the person before touching it.
- **Snapshot first:** `hypnomix live snapshot` (faders, pans, sends). `hypnomix live restore <file>` undoes.
- **Automation:** setting an automated control overrides its envelope. Check with `hypnomix automation list Set.als` before touching a control, and run `hypnomix live reenable` after edits, or exports lose the automation.
- Ask before taste-defining moves (signature reverb, delay character, vocal tone) and before saving the set.
- `--revert` puts back what the loop changed; check with `hypnomix live snapshot` before and after if unsure.

## Controls
- Mixer: `hypnomix live db Lead -3.5`, `nudge`, `pan`, `send Lead A 0.3`, `mute`, `solo`.
- Plug-ins: `hypnomix live devices Vox`, `hypnomix live params Vox "TDR Nova"`, then `hypnomix live param Vox "TDR Nova" "<name from that list>" 0.42` (raw value) or `hypnomix live paramd Vox EQ "1 Frequency A" 2500` (as displayed: Hz, dB, ms). Big plug-ins expose more parameters after `hypnomix install --plugin-params` (restart Live) or Live's Configure button.

## The A/B loop
`hypnomix loop --bar 33 --bars 8 --ab "db Lead -2" --revert` plays the section, records A, applies the change, records B, prints the difference (loudness, bands, width, punch) and puts the mix back. Use `hypnomix punch A.wav B.wav` for compressor and limiter decisions. Repeat close calls: noise is about ±0.3 dB.

`hypnomix diagnose Set.als bounce.wav` solos each top-level group in the loudest section and reports who owns the sub, bass and vocal band. It's the fastest way into an unfamiliar mix.
