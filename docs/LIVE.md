# Working inside Live: the probe, the song card and A/B

Everything in this guide happens in Ableton Live with three small Max for Live devices, while the hypnomix app
runs in the background. Nothing is rendered or exported to make a measurement or a comparison, and the set you
work in is never changed by hypnomix: every change still goes through the review and lands in a new set.

| device | where | what it does |
|---|---|---|
| **HypnomixProbe** | last on every track (and on returns, groups) | measures the track after all its plug-ins; you say what the track is, its priority, and whether it is protected |
| **HypnomixMain** | on Main | measures the mix; the song card (genre, key, scale, chords, loudness target, ceiling, limiter character, amount); a mastering chain of Live's own devices (build, match the target, save as a template); Record and review before export |
| **Hypnomix** | on any track | follows the review in the app: jumps Live to each finding, Approve / Skip, and A / B / Blind in an A/B set |

Make them once:

```bash
hypnomix probe device      # HypnomixProbe + HypnomixMain
hypnomix device            # Hypnomix (the review device)
hypnomix app               # keep it running while you work
```

They appear in Live's browser under User Library → Presets → Audio Effects → Max Audio Effect → Hypnomix.
Max for Live is needed (Live Suite, or the add-on). All three are pass-through: audio is untouched (the probe on
Main changes level only while you A/B with loudness matching on).

## 1. Put the probes in

Drag HypnomixProbe onto the last slot of one track and HypnomixMain onto Main, and save. Then:

```bash
hypnomix probe insert "Song.als"        # → "Song (probes).als": a probe on every track, return and group
```

Every copy starts at "auto". Open the new set.

## 2. Tell it what things are

On each probe:

- **What it is:** lead vocal, harmony, double, backing vocals, kick, snare, drums, percussion, bass, guitar,
  acoustic guitar, piano, keys, synth, strings, pad, brass, fx, other, or **auto** (the scan works it out by sound).
- **Priority:** *focus* (others give way to it in a frequency fight), *background* (it gives way), or normal.
- **Protect:** on means no change to this track is applied without asking again.

On HypnomixMain (the song card):

- **Genre**, **Key** and **Scale**. Tuning and harmony tools use this key as confirmed by you. Modes are tuned with
  the notes of the major key they share (A dorian = the notes of G major).
- **Chords:** type them and press Enter (for example `| Am | F | C | G |`). They are kept by the app, matched to
  the song by its track names, so they come back when you open the set again.
- **Target LUFS**, **Ceiling dBTP**, **Limiter** (clean, punch, loud) and **Amount %**: the loudness checks and the
  mastering proposals use these instead of your general preferences.

The menus are Live parameters, so they are saved in the set and can even be automated. `hypnomix scan` reads them
from the saved set; `hypnomix probe cards SET.als` shows what it reads.

## 3. Measure while you play

In the app's **Live** tab every probe shows its loudness, peak, tone and stereo width as Live plays. Press
**Record**, play the song or a section, press **Stop**: a review is made from what was heard:

- frequency fights between tracks while they play together (band, how often, who gives way: your priority wins)
- the lead vocal's level against the band section by section
- a low end that is not mono; a mix that is too wide
- Main's loudness and sample peak against the song card
- tracks running over 0 dBFS into what comes next

From a terminal: `hypnomix probe listen --bars 49-64 --play` (Live plays those bars through AbletonOSC), or
`hypnomix probe status`.

How it measures: K-weighted loudness with the BS.1770 filters at Live's sample rate (checked against a
reference meter within 0.04 LU), sample peak per channel, 8 bands (the same as `match`), L/R correlation overall
and below 120 Hz. Ten blocks a second, with the song position, so each number has a bar. The probe sits before
the fader; the fader is read and added.

## 4. A/B every fix inside Live

```bash
hypnomix abset "hypnomix-out/scan/Song"       # or: Build A/B set for Live, in the app's review
```

writes `Song (A-B).als` next to the original. In it, each proposed fix sits next to what you have, switched off:

- a device change: a copy of the device with the new settings, named `B · <finding id>`, off
- a clip or mixer change: a copy of the track with the fix, named `<track> · B <finding id>`, muted
- a track the fix adds: muted; a track it removes: muted in B

Close the original, open the A/B set, put the Hypnomix device on any track. For the finding you are on:

- **A · now** / **B · fix** switch instantly, with every plug-in playing
- **Match on**: with HypnomixMain on Main, B is turned up or down to A's loudness while it plays
- **Blind**: X and Y are A and B in random order; choose with **I like X / Y**, then it tells you which was which.
  Choices are kept (`blind.json`) and shown in the review.

Moving to another finding puts the last one back to A. The A/B set is for listening; approving happens in the
review and Apply writes the real new set from the original.

## 5. The mastering chain on HypnomixMain

HypnomixMain has a **Mastering chain** column. It builds the chain out of Live's own devices, in an Audio Effect
Rack called **Hypnomix Master** just before HypnomixMain on Main, so the meters and Record and review hear the
mastered sound. Open the rack and change anything: move, swap, add, remove or switch off devices.

| Stage | Device | Starts as |
|---|---|---|
| Tone | EQ Eight | low cut 12 dB/oct at 25 Hz; low shelf 90 Hz, bells 300 Hz and 3 kHz, high shelf 10 kHz, all at 0 dB |
| Glue | Glue Compressor | 2:1, attack 30 ms, release Auto, threshold -12 dB, Range 3 dB (never more than 3 dB) |
| Tame | Multiband Dynamics | off: switch on when one band jumps out in places |
| Warmth | Saturator | off: Soft Sine, 1.5 dB drive, 30 % wet |
| Width | Utility | bass mono below 120 Hz, width 100 %, DC filter |
| Limiter | Limiter | ceiling from the song card (true peak where offered), gain 0 dB until Match target |

- **Build chain**: builds the template chosen in the menu (the stock one above, or one you saved). If a Hypnomix
  Master rack is already there, it asks you to press again before replacing it.
- **Match target**: play the loudest part; it listens after the chain and turns the Limiter's Gain until Main
  lands on the card's Target LUFS (up to four rounds of about 8 s). It works with any chain before HypnomixMain
  that has a Limiter, yours included.
- **Save**: type a name and press Save. Whatever is before HypnomixMain is kept as a template, your edited
  Hypnomix Master or a rack of your own, with every setting of Live's own devices and racks. Plug-ins, Max for
  Live devices and macro mappings cannot be rebuilt through Live's API, so they are listed as left out. Templates
  are files in `~/.hypnomix/master-chains/` (the app must be running); `hypnomix probe chains` lists and shows them.
- While the rack is the one hypnomix built, it follows the song card: Ceiling sets the Limiter's ceiling, and the
  Limiter character sets lookahead and release (clean 6 ms, punch 3 ms, loud 1.5 ms with manual release) and the
  Glue attack (loud: 10 ms). A rack of your own is never changed, except the Limiter Gain by Match target.

Building needs Live 12.3 or later (Max for Live can insert devices from then on).

## 6. Review before export

Press **Record and review before export** on HypnomixMain. Live plays; the device records Main exactly as you
hear it (32-bit float, a real-time bounce) while every probe listens. When Live stops (or you press Stop) the app
runs: the live findings, loudness and true peak of the recording against the song card, `qc`, `translate`, and
`master --plan` with the card's target, ceiling, limiter character and amount. The review opens in the app.

Live's own Export makes the final file: no device can start an export in Live.

## Limits (to verify on your machine)

- Tested in Live 12 Suite on a real set (2026-11-25): the probe and HypnomixMain measuring playback, the menus and song card reaching the app and `scan`, A / B / Blind and loudness matching on an A/B set, and Record and review before export. Not yet tested: the track-copy switch for clip fixes by ear, and other Live versions.
- The mastering chain's parameter names follow Live 12; any it cannot find are named in the device after
  Build, so you can set them by hand.
- The probe's loudness is measured on 100 ms blocks with the BS.1770 gate; short sections read slightly
  differently from a full-file meter. Peaks are sample peaks: use `measure` on a bounce for true peak.
- Record and review writes a 32-bit float WAV with Max's `sfrecord~` into `~/Documents/Hypnomix/bounces/`.
