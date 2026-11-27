# HypnoMix launch: posts for X

Each post is under 280 characters
(checked, a link counted as 23). Suggested media is in [brackets]: screen recordings at 1080p, 15–30 s, captions on.

---

## Launch thread

**1/**
I built a mixing and mastering engineer for Ableton Live and REAPER.

Hand it raw stems → it cleans them, mixes them, masters the song, and writes down why it made every move.

Free, open source, 98 commands, and it works with Claude Code.

github.com/drtranceypants/hypnomix

[video: drag a stems folder in, run one command, play before/after]

**2/**
Most AI music tools are built for MIDI.

HypnoMix is for people who record real things: vocals, guitars, drums, bass. The messy part. Clicks, plosives, hum, takes recorded on different days at different levels.

**3/**
Step 1 is the boring work an assistant engineer does before a mix:

• repair clicks and pops
• rebuild clipped peaks
• remove plosive thumps
• turn breaths down (not out)
• kill hum and hiss only where they exist
• silence the gaps, fade every edit

Every fix logged.

[screenshot: PREP REPORT.md]

**4/**
Then it mixes like an engineer would:

clean-up EQ → tone EQ → compression set by gain reduction → de-essing → balance by loudness → panning → one shared reverb → drum bus glue

Then it finds frequency fights between stems and carves the less important part.

**5/**
The part I'm proudest of: it explains itself.

"Cut 300 Hz on the guitars, −2 dB: that's where they were muddying the vocal."

You get a mix AND a lesson. Disagree with a move? Change it. Nothing is a black box.

[screenshot: MIX NOTES.md]

**6/**
No paid plug-ins needed.

In Live it builds the mastering chain from stock devices (EQ Eight, Glue Compressor, Utility, Limiter), sets every value, then records Live's output and trims the limiter until it measures exactly on target. REAPER gets its own stock chain.

[video: chain appearing on the Main track]

**7/**
It also does the stuff nobody wants to do by hand:

• align vocal doubles + harmonies to the lead (pitch untouched)
• even out clips recorded at different gain/mic positions
• rank your takes and build a comp list
• fix phase between two mics on one source

**8/**
And it checks your master like a release engineer:

• how it sounds on a phone, earbuds, in a car, in mono
• how much Spotify / Apple Music / YouTube will turn it down
• whether it clips after AAC/MP3 encoding (it fixes that itself)

Pass/fail before you upload.

**9/**
With Claude Code you just ask:

"Mix these stems and make it sound like this reference."
"I'm recording guitar on input 2, check my levels."
"Master this for Spotify."

It drives Live (and REAPER) directly: faders in exact dB, any plug-in parameter, no screen clicking.

**10/**
MIT licensed. Mac and Windows installers. Live 11/12 and REAPER.

It measures. An optional Listener (cloud model, your own key) adds notes by ear, only when you say so. A sharp assistant, not a replacement for your ears.

Tell me what it got wrong.

github.com/drtranceypants/hypnomix

**11/**
New: a free course is built in. The app's Teacher tab teaches the loop in your own DAW (Live, REAPER, and HypnoMix DAW, which is not released yet): a tour, a 101 crash course and a complete course A to Z. No AI needed.

Or practise on a 40-second demo song with six planted problems: hypnomix demo

---

## Standalone posts (for the days after launch)

**Before/after**
Raw stems in. Mastered song out. Every EQ cut, compressor setting and level explained in plain English.

This is HypnoMix, a free open-source mix engineer for Ableton Live and REAPER, with a HypnoMix DAW add-on on the way.

[video: 10 s raw rough mix → 10 s HypnoMix master, same section, level-matched]

github.com/drtranceypants/hypnomix

**Vocal stacks**
Tight vocal stacks are what make a production sound expensive.

hypnomix vocalign lines every double and harmony up with the lead vocal, word by word, without touching the pitch. In my test: 40 ms apart before, under 10 after.

Free + open source: github.com/drtranceypants/hypnomix

[audio: stack before/after]

**Loudness myth**
Your -8 LUFS master gets turned down 6 dB on Spotify. You keep the squashed drums and lose the loudness.

hypnomix translate shows exactly what every platform will do to your song before you upload it.

github.com/drtranceypants/hypnomix

**No plug-ins**
You don't need an expensive mastering plug-in.

HypnoMix builds a full mastering chain from Live's stock devices (or REAPER's own), sets every knob from an analysis of your mix, and checks the result by measuring what Live actually plays.

github.com/drtranceypants/hypnomix

**The boring stuff**
The least glamorous part of a mix: clicks, pops, plosives, breaths, hum, noisy gaps, missing fades, clips at different levels.

hypnomix prep does all of it in seconds and logs every fix with a timestamp.

github.com/drtranceypants/hypnomix

**Learning**
I wanted a tool that makes you a better engineer instead of hiding the work.

Every move HypnoMix makes comes with a reason: why that frequency, why that ratio, why that level. Read the notes, try your own version, compare.

github.com/drtranceypants/hypnomix

---

## Reply bank (for common questions)

**"Does it replace a mix engineer?"**
No. It's a strong, fast first pass and a teacher. It measures; the optional Listener (a cloud model, your own key) adds notes by ear, but that's an opinion. The taste calls (vocal level, reverb, character) are yours, and a good engineer will still beat it.

**"Do I need Claude Code?"**
No. Every tool is a plain command-line program, and the app lets you click through the same steps. Claude Code (or another agent) makes it conversational and can drive Live for you.

**"Windows?"**
There are installers for Mac and Windows. Windows is newer and less tested; recording what Live plays is set up for BlackHole on Mac for now.

**"What about Live Lite / Intro?"**
The offline tools work with any version, and so does REAPER. Building the chain in Live needs Glue Compressor and Limiter (Live Standard or Suite).

---

## Demo shot list

1. **Hero (thread post 1, 30 s):** Finder folder of raw stems → terminal `hypnomix automix` → progress lines → play 8 bars of the rough sum, then the master, level-matched, with a waveform.
2. **Prep (post 3, 15 s):** a vocal with a planted click and a plosive, scrubbed in Live, then the cleaned file at the same spot, with PREP REPORT.md on screen.
3. **Explainability (post 5, screenshot):** MIX NOTES.md, scrolled to the vocal section.
4. **Chain (post 6, 20 s):** Live with an empty Main track → run `hypnomix chain master --verify` → devices appear one by one → the calibration lines print.
5. **Vocalign (standalone, 15 s):** solo the lead and a harmony stack before and after, waveforms stacked.
