"""Teacher mode: a guided walk from an empty song to a mastered one, for people who have never used a DAW.

Four chapters, each a list of steps: the words and the screen, your first recording (tempo, the click, an optional
drum beat to play over, a track armed with the right input, the input gain, record), mixing one effect at a time
(what it does, why, where to start), and mastering (what it is, and a good chain). Ableton Live gets the most depth,
REAPER a little less, Ardour the short version (the least tested).

A step can carry a hands-on action ("Set the tempo", "Add a drum beat"). Every action that changes the person's
set or project shows exactly what it will do and waits for their click: the browser asks, and the server refuses
an action without `ok`. Live is driven through AbletonOSC (hypnomix/live/osc.py), REAPER through its bridge
(hypnomix/reaper/client.py); where the DAW can't be driven (Ardour, or no connection) the step's own instructions
say how to do it by hand. Nothing here needs an AI: the Assistant can narrate a step when one is set up.

Two courses (LEVELS): "tour" for people who already engineer and only need hypnomix, its devices and their DAW;
"101" for people new to audio, which adds the basics first. The DAW and the course come from the guided setup (~/.hypnomix/setup.json); progress is kept in
~/.hypnomix/teacher.json. The same lessons are the wiki's "Make a song from scratch" articles (wiki_md), so the app
and the website always teach the same thing: change them here and the wiki follows.
"""
import json
import random
import re
import threading
import time
from pathlib import Path

DAWS = {"live": "Ableton Live", "reaper": "REAPER", "ardour": "Ardour"}
# two courses: "tour" for people who already engineer (hypnomix, its devices and the DAW they use it with), "101"
# for people new to audio (the words, recording, mixing and mastering, then the same tour)
LEVELS = {"tour": "hypnomix in your DAW", "101": "The 101 crash course"}
ALL = ("live", "reaper", "ardour")
LR = ("live", "reaper")


def _home():
    from hypnomix.core.paths import HOME
    return Path(HOME)


def progress_file():
    return _home() / "teacher.json"


# ---------------------------------------------------------------- the lessons
# A step: id, title, daws (which DAWs teach it), say (paragraphs), terms ([word, meaning]), how ({daw: [steps]}),
# settings ([control, where to start, why]; per DAW when the controls differ), listen (what to listen for),
# action ({daw: action spec}), app (a button into another tab of the app). **bold** works in the text.

CHAPTERS = [
 dict(id="words", levels=("101",), title="The words and the screen", sub="what a DAW is, and the names for everything on it", steps=[
  dict(id="daw", title="What a DAW is", daws=ALL,
       say=["A **DAW** (digital audio workstation) is a recording studio inside your computer: a tape machine, a mixing desk "
            "and a rack of effects in one program. You record into it, arrange the parts, mix them, and export one stereo "
            "file at the end.",
            "Everything you'll do follows one path: **record → edit → mix → master → export**. This course walks it once, "
            "start to finish, with your own song. Take it slowly: nothing here can break your music, and every change "
            "hypnomix makes asks you first."],
       terms=[["Project / set / session", "your song's file. Live calls it a Set (.als), REAPER a Project (.rpp), Ardour a Session (a folder)."],
              ["Track", "one lane for one sound: a vocal, a guitar, the drums. Audio tracks hold recordings; MIDI tracks hold notes that play an instrument."],
              ["Clip / item / region", "a piece of recording or notes on a track. Live says clip, REAPER item, Ardour region."],
              ["Audio interface", "the box your mic and guitar plug into. It turns sound into numbers (and back, for your headphones)."],
              ["Input", "which socket on your interface a track records from: input 1, input 2…"],
              ["Bar and beat", "music's ruler. Most songs count 4 beats to a bar; the DAW's timeline is numbered in bars."],
              ["BPM", "beats per minute: the song's tempo."]]),
  dict(id="screen-live", title="A tour of Live's screen", daws=("live",),
       say=["Live has two main views of the same song, and you switch with the **Tab** key.",
            "**Session View** is a grid of clips: every column is a track, every row a *scene*. It's a sketchpad for trying "
            "loops and ideas; clips play when you click them. **Arrangement View** is the timeline you'll know from other "
            "programs: left to right is time, and this is where a finished song lives. In this course you record in the "
            "Arrangement View."],
       terms=[["Browser", "the column on the left: instruments, drum kits, audio effects, samples, and your files. Drag things from it onto tracks."],
              ["Device View", "the strip along the bottom (Shift+Tab shows it): the instrument and effects on the selected track, left to right in the order the sound flows."],
              ["Mixer", "volume, pan, sends and the arm button for each track. In the Arrangement View, View → Mixer shows it on the right."],
              ["I/O", "where each track's sound comes from and goes to (View → In/Out). You choose the interface input here."],
              ["Transport", "play, stop, record, the tempo and the metronome, along the top."],
              ["Master", "the last track on the right: everything ends up here, and this is what you export."],
              ["Return track", "a shared effect, like one reverb, that many tracks send a bit of themselves to."]],
       how={"live": ["Open Live and make a new set: File → New Live Set.", "Press Tab a few times to flip between Session and Arrangement.",
                     "Press Shift+Tab to show or hide the Device View.", "Turn on View → Mixer and View → In/Out in the Arrangement View: you'll use both.",
                     "Live → Settings → Audio (Options → Preferences on Windows): choose your audio interface for both Input and Output."]}),
  dict(id="screen-reaper", title="A tour of REAPER's screen", daws=("reaper",),
       say=["REAPER keeps it all in one window: the **track control panel** on the left (each track's name, arm button, volume "
            "and FX), the **arrange view** in the middle (time runs left to right), the **transport** below it, and the "
            "**mixer** at the bottom (View → Mixer, Ctrl+M / Cmd+M)."],
       terms=[["TCP / MCP", "the track control panel (left of the timeline) and the mixer control panel (the mixer): two views of the same tracks."],
              ["Item and take", "a recording on a track is an item; record over it again and each pass is a take inside the item."],
              ["FX chain", "the effects on a track, in order: click the track's FX button."],
              ["Master", "the master track: everything ends up here. View → Master track shows it if it's hidden."],
              ["Actions", "every command in REAPER is an action, findable with ? (Actions → Show action list)."]],
       how={"reaper": ["Make a new project: File → New project.",
                       "Options → Settings (Preferences) → Audio → Device: choose your audio interface.",
                       "Ctrl+T (Cmd+T on a Mac) adds a track; double-click its name to rename it.",
                       "Ctrl+M / Cmd+M shows the mixer."]}),
  dict(id="screen-ardour", title="A tour of Ardour's screen", daws=("ardour",),
       say=["Ardour has two main windows: the **Editor** (the timeline, with tracks top to bottom) and the **Mixer** "
            "(Alt+M switches between them). A song is a *session*: a folder with the session file and every recording."],
       terms=[["Region", "a piece of recording on a track."], ["Bus", "a track with no recordings of its own, that other tracks feed: used for groups and effects."],
              ["Strip", "one track's column in the Mixer: input, plug-ins, pan, fader."]],
       how={"ardour": ["Start Ardour, choose your audio interface in the Audio/MIDI Setup window, and make a new session.",
                       "Track → Add Track, Bus or VCA… adds tracks.", "Alt+M shows the Mixer; Alt+E goes back to the Editor."]}),
  dict(id="signal", title="Where the sound goes", daws=ALL,
       say=["Sound travels one way: **interface input → track → its effects, left to right → its fader → the master → your "
            "speakers** (and, when you export, a file).",
            "Two habits save beginners a lot of grief. Keep every track's peaks well under 0 dB (the top of the meter), so "
            "nothing distorts. And change one thing at a time, listening before and after: that's how your ears learn "
            "what each control does."],
       terms=[["dB (decibel)", "how loud. 0 dBFS is the very top of the digital scale; going over it distorts. A change of 1 dB is small, 6 dB is a lot."],
              ["Fader", "the slider that sets a track's volume."], ["Pan", "where a sound sits from left to right."],
              ["Headroom", "the space left between your loudest peak and 0 dB."]]),
 ]),

 dict(id="record", levels=("101",), title="Your first recording", sub="tempo, the click, a beat to play over, a track that's ready, the right level", steps=[
  dict(id="tempo", title="Choose a tempo", daws=ALL,
       say=["Before you record, give the song a tempo. Tap your foot to the song and count: most songs sit between 70 and "
            "130 BPM. The tempo sets the click and the bar lines, so a part recorded to it lines up with everything else.",
            "Not sure? Pick something close; you can change the tempo before you record, not easily after."],
       how={"live": ["Click the tempo field at the top left (it says 120.00) and type a number, or click **TAP** in time with your foot."],
            "reaper": ["Double-click the BPM box in the transport bar and type the tempo, or click **TAP** (or press T) in time."],
            "ardour": ["Double-click the tempo marker at the start of the Tempo ruler and type the BPM."]},
       action={d: dict(kind="tempo") for d in LR}),
  dict(id="click", title="Record to a click", daws=ALL,
       say=["The **click** (metronome) ticks on every beat while you play. Recording to it keeps the bar lines meaningful, so "
            "later you can copy a chorus, drop in drums or fix one word without everything drifting.",
            "It doesn't make you a machine. Play with it, not *at* it: being a little ahead or behind is the feel of the "
            "song, and hypnomix never forces your playing onto the grid. Give yourself a **count-in** (one or two bars of "
            "click before recording starts) so you come in on time.",
            "In your headphones, not the speakers: a click in the room ends up on the vocal mic."],
       how={"live": ["Click the metronome icon (the two circles next to the tempo) so it lights up.",
                     "Its little arrow menu: set **Count-In** to 1 Bar.", "The click goes to your headphones through Live's Cue output (Settings → Audio, and the Mixer's Cue Out)."],
            "reaper": ["Click the metronome button in the transport bar (or Options → Metronome) so it's on.",
                       "Right-click it → Metronome settings: tick **Count-in before recording** (2 bars is comfortable)."],
            "ardour": ["Click the **Click** button in the toolbar so it lights up.", "Transport → Count In, or record with the count-in button, gives you a bar first."]},
       action={d: dict(kind="click") for d in LR}),
  dict(id="drums", title="A drum beat to play over (optional)", daws=ALL,
       say=["A click is honest but dull. A simple drum beat on a **MIDI track** is nicer to play to, and you can replace it "
            "with real drums or a better beat later.",
            "MIDI is notes, not sound: each note says *which drum, when, how hard*. The drum kit on the track turns those "
            "notes into sound, so you can change the kit, the tempo or a single hit at any time.",
            "hypnomix can add a four-bar beat: kick, snare on 2 and 4, eighth-note hi-hats, with small differences in how "
            "hard each hit lands so it doesn't sound like a typewriter."],
       terms=[["MIDI track", "a track that holds notes and plays an instrument (here a drum kit) instead of holding a recording."],
              ["Velocity", "how hard a note is played, 1 to 127."], ["Loop", "a clip or region that repeats."]],
       how={"live": ["Cmd+Shift+T (Ctrl+Shift+T) makes a MIDI track.", "In the Browser, open **Drums** and drag a kit (any Kit-…) onto it.",
                     "Double-click an empty slot (Session View) or drag in the Arrangement to make a clip, then click notes in with the pencil (B)."],
            "reaper": ["Insert → Virtual instrument on new track → ReaSynDr (REAPER's own drum synth), or your own drum plug-in.",
                       "Insert → New MIDI item, double-click it, and draw notes in the piano roll."],
            "ardour": ["Track → Add Track: a **MIDI track** with an instrument (ACE Reasonable Synth, or a drum plug-in you have).",
                       "Draw a region with the Draw tool (D) and click notes in."]},
       action={d: dict(kind="drums") for d in LR}),
  dict(id="track", title="Make a track and arm it", daws=ALL,
       say=["Make one **audio track** for what you're about to record, name it after the instrument (\"Vocal\", \"Guitar\"), "
            "and tell it which **input** of your interface to listen to: the socket your mic or guitar is plugged into.",
            "Then **arm** it: the red record button on the track. Only armed tracks record. **Monitoring** decides whether "
            "you hear yourself through the DAW: on (or Auto) while you record, so you hear the effects and the backing; "
            "if your interface has its own \"direct monitor\" knob, use that instead and turn the DAW's off, so you don't hear "
            "yourself twice."],
       terms=[["Arm", "make a track ready to record."], ["Monitoring", "hearing the input through the track while you play."],
              ["Mono / stereo", "one mic or one guitar is mono (one input). A keyboard's left and right outputs are stereo (two)."]],
       how={"live": ["Cmd+T (Ctrl+T) makes an audio track; double-click its name to call it Vocal.",
                     "In its I/O section: **Audio From → Ext. In**, and below it the input number your mic is on (1, 2…).",
                     "Monitor: **Auto**. Click the track's **Arm** button (the circle) so it turns red."],
            "reaper": ["Ctrl+T / Cmd+T makes a track; name it.", "Click the input selector on the track (or right-click the arm button) → Input: Mono → Input 1.",
                       "Click the record-arm button (red circle) and the speaker icon next to it for monitoring."],
            "ardour": ["Track → Add Track, Bus or VCA…: an Audio track, Mono, named Vocal.", "In the Mixer, the input button at the top of the strip: choose the interface input (capture_1).",
                       "Click the track's record button (the pink circle) to arm it."]},
       action={d: dict(kind="track") for d in LR}),
  dict(id="gain", title="Set the input gain", daws=ALL,
       say=["**Input gain** is the knob on your audio interface for each input, not a fader in the DAW. It sets how strongly "
            "the mic or guitar is recorded, and it's the one level you can't fix later: too hot and it distorts for good, "
            "too quiet and you turn up the hiss with it.",
            "Sing or play the **loudest** part of the song and turn the knob until the track's meter peaks around **-12 to "
            "-6 dB**, about two-thirds of the way up, never in the red. That leaves room for the moment you sing louder than "
            "you did in the soundcheck. Recording quieter than you'd think is normal in 24-bit: there's no need to record hot.",
            "hypnomix can listen to your input for a few seconds and tell you which way to turn the knob."],
       settings=[["Peaks while you play your loudest", "-12 to -6 dBFS", "room for a louder take; never touches 0"],
                 ["Recording format", "24-bit, 44.1 or 48 kHz", "24-bit keeps quiet parts clean at sensible levels"],
                 ["Mic distance (vocal)", "a hand's width, with a pop filter", "closer is boomier, further is roomier"]],
       how={"live": ["Arm the track and watch its meter in the Mixer while you sing the loudest line.", "Turn the interface's gain knob, not Live's fader (the fader doesn't change what's recorded)."],
            "reaper": ["With the track armed, its meter shows the input. Turn the interface's knob until the peaks sit around -12 to -6."],
            "ardour": ["With the track armed, watch the strip's meter while you sing, and set the interface's knob."]},
       action={d: dict(kind="level") for d in ALL}),
  dict(id="take", title="Record a take", daws=ALL,
       say=["Press record, let the count-in go by, and perform. Don't stop for small mistakes: keep going, and record two or "
            "three whole **takes**. The best moments of each can be joined later (that's called **comping**).",
            "When you're done, stop, unarm the track, and listen back once without touching anything. Save the song."],
       terms=[["Take", "one pass of recording."], ["Comping", "building one best performance from the best parts of several takes."],
              ["Punch in", "recording over just a few bars to fix one spot."]],
       how={"live": ["Go to the Arrangement View, put the cursor at bar 1, and press the **Arrangement Record** button (the circle in the transport, or F9).",
                     "Press Space to stop. Record again over the same bars: Live 12 keeps each pass as a take lane (right-click the track → Show Take Lanes)."],
            "reaper": ["Press Ctrl+R / Cmd+R (or the transport's record button). Space stops; REAPER asks whether to keep the files.",
                       "Record again over the same spot and each pass becomes a take: press T to cycle them, or right-click → Take → Show all takes in lanes."],
            "ardour": ["Shift+R enables the session's record, then Space starts it (or the big record and play buttons). Space again stops.",
                       "Recording again over the same spot stacks a new region on top (Layers in the track's context menu)."]},
       action={"live": dict(kind="record"), "reaper": dict(kind="record")}),
  dict(id="session-sketch", title="Sketch ideas in Session View", daws=("live",),
       say=["Live's **Session View** is made for trying things before they're a song. Each slot holds a clip; record a "
            "four-bar loop into one slot, another idea into the next, and play them against each other. A row of clips "
            "across the tracks is a **scene**: a verse, a chorus.",
            "When an idea works, record it into the Arrangement: press the Arrangement Record button and launch scenes as "
            "the song plays, or drag clips across. The drum beat hypnomix adds lands in the Session View for this reason."],
       terms=[["Scene", "one row of clips, launched together."], ["Launch quantisation", "clips start on the next bar, so they stay in time when you click them."]],
       how={"live": ["Press Tab for the Session View. With a track armed, click a slot's record button (the circle) to record a clip; click again to stop and loop it.",
                     "Click a scene's play button on the right to launch the whole row.",
                     "To record what you launch into the timeline: Arrangement Record (F9), then launch scenes."]}),
  dict(id="takes-hypnomix", title="Let hypnomix help with the takes", daws=ALL,
       say=["Once you have takes, hypnomix's **first pass** (the Songs tab) checks the recording for the technical things "
            "ears miss at first: clicks where a take was cut, the level jumping between takes, notes that drifted flat, "
            "hum and hiss. It suggests a fix for each, lets you hear before and after, and changes nothing until you say yes.",
            "For now, keep recording the rest of the song: each instrument gets its own track, recorded the same way."],
       app=dict(view="home", label="Open the Songs tab")),
 ]),

 dict(id="mix", levels=("101",), title="Mixing, one effect at a time", sub="balance first, then each effect: what it does, why, where to start", steps=[
  dict(id="balance", title="Balance and pan first", daws=ALL,
       say=["Most of a good mix is just **levels**. Before any effect, pull every fader down, then bring them up one at a "
            "time, starting with the most important part (usually the vocal or the drums), until the song sounds like a song.",
            "Then **pan**: spread things left and right so they don't sit on top of each other. Keep the vocal, kick, snare and "
            "bass in the middle; move guitars, keys and backing vocals out to the sides, often in pairs.",
            "Leave the master fader at 0 and keep the master's peaks around -6 dB: if it's hotter, turn the tracks down, not the master."],
       settings=[["Lead vocal, kick, snare, bass", "pan centre", "the song's anchors"], ["Two guitars or two keyboard parts", "one left, one right (30-70%)", "they make room for each other"],
                 ["Master peaks", "about -6 dBFS", "headroom for mastering"]],
       how={"live": ["The track faders and pan knobs are in the Mixer section (View → Mixer)."],
            "reaper": ["Each track's volume and pan knobs are on the track, and in the mixer (Ctrl+M / Cmd+M)."],
            "ardour": ["The faders and pan are in the Mixer window (Alt+M)."]}),
  dict(id="eq", title="EQ: shape the tone", daws=ALL,
       say=["An **equaliser** turns some frequencies up or down: the low thump, the middle body, the high air. Use it to "
            "remove what you don't need and to make each part sit in its own space.",
            "Start with a **low cut** (high-pass): almost nothing but bass and kick needs the deep lows, and cutting them "
            "clears mud you can't hear on its own. Then cut before you boost: a narrow cut where something boxy or harsh "
            "rings, a wide gentle boost where you want more. Small moves: 1 to 3 dB."],
       terms=[["Hz (hertz)", "how low or high: 100 Hz is a deep thump, 1 kHz the middle, 10 kHz the air."],
              ["Low cut / high-pass", "removes everything below a frequency."], ["Bell", "a boost or cut around one frequency."],
              ["Q", "how narrow a bell is: high Q is narrow."], ["Shelf", "raises or lowers everything above (or below) a frequency."]],
       settings=[["Low cut (vocal, guitar)", "80-120 Hz", "removes rumble and mic thumps"], ["Mud", "200-400 Hz, -2 to -4 dB, only if it sounds boxy", "clears space for the bass and kick"],
                 ["Presence", "3-5 kHz, +1 to +2 dB, wide", "brings the words forward"], ["Air", "a shelf above 10 kHz, +1 to +2 dB", "a little sparkle"]],
       listen="Switch the EQ off and on at the same loudness: better should mean clearer, not just louder.",
       how={"live": ["Browser → Audio Effects → **EQ Eight**, drag it onto the track (or onto its Device View).",
                     "Band 1: click its type and choose the low cut, then drag its dot to about 100 Hz.", "Click a dot and drag up or down for gain; Alt+drag (Option+drag) changes Q."],
            "reaper": ["Click the track's **FX** button → Cockos → **ReaEQ**.", "Right-click band 1's type → High pass, frequency about 100 Hz.",
                       "Drag the other bands' dots up or down; the scroll wheel on a dot changes its width."],
            "ardour": ["Double-click in the strip's plug-in box → **ACE EQ** (a-EQ in older Ardour)."]},
       fx={"live": dict(device="EQ Eight", set=[["disp", ["1 Frequency A"], 100], ["raw", ["1 Filter Type A"], 1], ["raw", ["1 Filter On A"], 1],
                                               ["raw", ["3 Filter Type A"], 3], ["disp", ["3 Frequency A"], 3500], ["disp", ["3 Gain A"], 1.5], ["disp", ["3 Resonance A", "3 Q A"], 0.8]]),
           "reaper": dict(device="ReaEQ (Cockos)", set=[["named", "BANDTYPE0", "4"], ["shown", 0, 100], ["named", "BANDTYPE2", "8"], ["shown", 6, 3500], ["shown", 7, 1.5]])},
       action={d: dict(kind="fx") for d in LR}),
  dict(id="comp", title="Compression: even out the loud and quiet", daws=ALL,
       say=["A **compressor** turns a sound down when it gets loud, so the quiet words and the loud ones sit closer "
            "together. A vocal without it jumps in and out of the mix; with too much it sounds flat and squashed.",
            "Set the **ratio** (how hard it turns down), then lower the **threshold** until the meter shows it turning the "
            "loudest words down by 3 to 6 dB. **Attack** is how fast it grabs: slower lets the start of each word through, "
            "which keeps it lively. Then raise the **makeup** (output) gain until it's as loud as it was with the "
            "compressor off, so you judge the sound, not the volume."],
       terms=[["Threshold", "the level where it starts turning down."], ["Ratio", "how much: at 4:1, 4 dB over the threshold comes out as 1 dB over."],
              ["Attack / release", "how fast it turns down, and how fast it lets go."], ["Gain reduction", "how much it's turning down right now, in dB."]],
       settings=[["Ratio", "3:1 (2:1 gentle, 4:1 firm)", "vocals and bass usually sit between 2 and 4"], ["Attack", "10-30 ms", "faster catches peaks but dulls the consonants"],
                 ["Release", "50-150 ms (or Auto)", "lets go between words"], ["Threshold", "until the loudest words show 3-6 dB of gain reduction", "control without squashing"],
                 ["Makeup / output", "the same loudness as bypassed", "a fair comparison"]],
       listen="Listen to the quietest and the loudest line: they should feel closer, with the words still breathing.",
       how={"live": ["Audio Effects → **Compressor**, after the EQ Eight on the same track.", "Watch the orange gain-reduction meter while the loudest part plays."],
            "reaper": ["FX → **ReaComp**, after ReaEQ.", "The gain-reduction meter is the one on the right side of ReaComp."],
            "ardour": ["Plug-in box → **ACE Compressor**."]},
       fx={"live": dict(device="Compressor", set=[["disp", ["Ratio"], 3], ["disp", ["Attack"], 15], ["disp", ["Release"], 100], ["disp", ["Threshold"], -18]]),
           "reaper": dict(device="ReaComp (Cockos)", set=[["shown", "Ratio", 3], ["shown", "Attack", 15], ["shown", "Release", 100], ["shown", "Thresh", -18]])},
       action={d: dict(kind="fx") for d in LR}),
  dict(id="deess", title="De-essing: soften the S's", daws=LR,
       say=["After EQ and compression, \"s\" and \"t\" sounds can get sharp. A **de-esser** is a compressor that only listens "
            "to that hissy range and turns it down just for those moments.",
            "hypnomix's first pass also finds harsh S's and can soften them in a new copy of the recording, if you'd rather "
            "fix it at the source."],
       settings=[["Frequency", "5-8 kHz (find where the S's bite)", "female voices often higher, male lower"], ["Reduction", "3-6 dB, only on the S's", "more makes a lisp"]],
       how={"live": ["Live has no separate de-esser: use a **Compressor**, open its Sidechain section, turn on **EQ**, choose a band-pass around 6 kHz, and set the threshold so only the S's trigger it.",
                     "Press the headphone button in the sidechain EQ to hear what it's listening to."],
            "reaper": ["FX → **ReaXcomp**: keep one band, set it to about 5-9 kHz, and lower its threshold until only the S's turn down."]}),
  dict(id="reverb", title="Reverb on a send: a shared space", daws=ALL,
       say=["**Reverb** is the sound of a room: it puts a dry recording somewhere. Instead of a reverb on every track, put one "
            "on a **return** (send) track and send a little of each track to it, so everything sounds like it's in the "
            "same place, and one knob sets how much.",
            "On a return, the reverb is set to 100% wet (only the room, none of the dry sound), and the send knobs decide how "
            "much of each track goes in. Less than you think: if you can clearly hear it, it's often too much."],
       terms=[["Send", "a knob on a track that sends a copy of it to a return track."], ["Wet / dry", "the effect alone, or the original alone."],
              ["Decay", "how long the room rings."], ["Pre-delay", "a short gap before the room starts, which keeps the words clear."]],
       settings=[["Dry/Wet (on the return)", "100% wet", "the track's own sound stays on the track"], ["Decay", "1.2-2 s", "a room to a small hall"],
                 ["Pre-delay", "20-40 ms", "keeps the vocal in front"], ["Low cut / high cut on the reverb", "200 Hz / 8 kHz", "a cleaner, darker room"],
                 ["Send from the vocal", "start around -15 dB", "raise until you just hear it, then back off a little"]],
       how={"live": ["Live sets come with return tracks A and B. Drag **Reverb** (or Hybrid Reverb) onto return A and set Dry/Wet to 100%.",
                     "On each track, turn send knob **A** up to send it to the reverb."],
            "reaper": ["Add a track called Reverb with **ReaVerbate** (or ReaVerb), wet 0 dB, dry off.",
                       "Drag from a track's route button (I/O) to the Reverb track to make a send, then set its level."],
            "ardour": ["Make a bus (Track → Add Track, Bus or VCA…, an Audio Bus) with **ACE Reverb**.",
                       "On each track's strip, right-click the plug-in box → New Aux Send → the reverb bus."]},
       fx={"live": dict(device="Reverb", track="A", set=[["disp", ["Dry/Wet"], 100], ["disp", ["Decay Time"], 1800], ["disp", ["Predelay"], 30]])},
       action={"live": dict(kind="fx")}),
  dict(id="delay", title="Delay: echoes in time", daws=LR,
       say=["A **delay** repeats the sound, in time with the song. A quiet eighth- or quarter-note echo on a return makes a "
            "vocal feel bigger without the wash of a reverb. Like the reverb, it lives on a return, 100% wet."],
       settings=[["Time", "1/4 or 1/8 note, synced to the tempo", "the echoes fall on the beat"], ["Feedback", "20-35%", "two or three repeats"],
                 ["Filter", "cut the lows and the highs of the echoes", "so they sit behind the dry sound"]],
       how={"live": ["Drag **Delay** (or Echo) onto return B, set Dry/Wet to 100%, Sync on, 1/8 or 1/4; send to it with knob B."],
            "reaper": ["A second send track with **ReaDelay**: set the length in musical time (1/8 or 1/4)."]}),
  dict(id="saturation", title="Saturation: warmth and weight", daws=("live",),
       say=["**Saturation** adds a little gentle distortion, the way tape and old gear did. A touch makes a bass or vocal "
            "feel thicker and helps it come through on small speakers. Blend it in; you should miss it when it's off rather "
            "than notice it when it's on."],
       settings=[["Type", "Soft Sine or Analog Clip", "gentle shapes"], ["Drive", "2-4 dB", "a touch"], ["Dry/Wet", "20-40%", "blend, don't replace"],
                 ["Output", "lower it to match the level", "a fair comparison"]],
       how={"live": ["Audio Effects → **Saturator**, on the bass or the vocal, after the compressor."]},
       fx={"live": dict(device="Saturator", set=[["disp", ["Drive"], 3], ["disp", ["Dry/Wet"], 30], ["disp", ["Output"], -2]])},
       action={"live": dict(kind="fx")}),
  dict(id="groups", title="Groups: mix the drums as one", daws=("live", "reaper"),
       say=["Once you have several drum or backing-vocal tracks, put them in a **group** (a bus): their sound comes together "
            "on one track, with one fader and one set of effects. Turning the whole drum kit down a little becomes one move."],
       how={"live": ["Select the tracks (click the first, Shift+click the last) and press Cmd+G (Ctrl+G).", "The group track's fader now sets all of them; you can fold it with its triangle."],
            "reaper": ["Select the tracks, right-click → **Move tracks to new folder** (or make a track and drag the others into it): the folder track is the bus."]}),
  dict(id="automation", title="Automation: the mix moves", daws=LR,
       say=["Real mixes move: the vocal comes up a little in the chorus, the reverb swells at the end. **Automation** records "
            "those moves, so a fader or knob follows a line you draw over time.",
            "Do it last, after the balance and effects are set, and keep the moves small."],
       how={"live": ["Press **A** in the Arrangement to show automation; choose the track's Volume in its lane menu, then click points in and drag them."],
            "reaper": ["Click the track's envelope button (trim/arm), tick Volume, then click points on the envelope lane."]}),
  dict(id="mix-check", title="Let hypnomix check the mix", daws=ALL,
       say=["When it sounds good to you, run hypnomix's **first pass** on the song. It looks for what's easy to miss: two parts "
            "fighting over the same frequencies, a part much louder in one section, a plug-in left switched off, clipping. "
            "Every finding is a suggestion with a before and after to hear; you decide."],
       app=dict(view="home", label="Open the Songs tab")),
 ]),

 dict(id="master", levels=("101",), title="Mastering", sub="what it is, and a good chain to start from", steps=[
  dict(id="what", title="What mastering is", daws=ALL,
       say=["**Mastering** is the last step: one gentle pass over the finished stereo mix so it sounds its best everywhere "
            "(phones, cars, earbuds, a club), sits at the right loudness for streaming, and has no peaks that distort when "
            "it's turned into an MP3 or AAC.",
            "It isn't where a song gets fixed. If the vocal is too quiet, go back to the mix: mastering moves everything at "
            "once. Good mastering is small moves, a dB here and there."],
       terms=[["LUFS", "how loud a song feels on average. Spotify, YouTube and Apple turn songs to about -14 LUFS (Apple -16), so going louder buys nothing."],
              ["True peak (dBTP)", "the real highest point after the file is turned back into sound. Keep it at -1 dBTP or lower."],
              ["Limiter", "a very fast compressor that stops anything going over a ceiling."], ["Reference track", "a finished song you love, to compare with."]]),
  dict(id="prepare", title="Prepare the mix", daws=ALL,
       say=["Take off anything you put on the master while mixing to make it loud, check the master peaks around -6 dB, and "
            "export the whole song as a **24-bit WAV** from the very start to the end of the last ring-out. That bounce is "
            "what you master (or what hypnomix masters for you)."],
       how={"live": ["File → Export Audio/Video: Rendered Track **Master**, the whole song selected, WAV, 24-bit, sample rate as the set, Normalize off, Dither off."],
            "reaper": ["File → Render: Source **Master mix**, Bounds Entire project, WAV 24-bit."],
            "ardour": ["Session → Export → Export to Audio File(s): WAV, 24-bit, Normalize off."]}),
  dict(id="chain", title="A good mastering chain", daws=ALL,
       say=["The usual order, each doing a little: **EQ** for the overall tone (tiny moves, and a low cut at about 25 Hz for "
            "rumble you can't hear), a **glue compressor** that barely touches it (2:1, slow attack, 1 to 3 dB), **bass in "
            "mono** below about 120 Hz so the low end is solid on every system, and last a **limiter** with its ceiling at -1 dB "
            "true peak, turned up until the song reaches its loudness target.",
            "hypnomix can build that chain from your DAW's own plug-ins, every gain starting at 0 dB, so you add only what the "
            "song needs."],
       settings=[["EQ", "low cut 25 Hz; shelves and bells within ±1 dB", "gentle overall tone"], ["Glue compressor", "2:1, attack 30 ms, auto release, 1-3 dB", "holds the mix together"],
                 ["Bass mono", "below 120 Hz", "a solid low end on every system"], ["Limiter ceiling", "-1 dBTP", "safe after MP3 / AAC"],
                 ["Limiter gain", "until about -14 LUFS (streaming)", "no more than about 3 dB of limiting on average"]],
       how={"live": ["On the **Master** track: EQ Eight, Glue Compressor, Utility (Bass Mono on, 120 Hz) and Limiter, in that order.",
                     "Or put the hypnomix **HypnomixMain** device on the master and press **Build chain** (see Wiki → the mastering chain)."],
            "reaper": ["On the master: ReaEQ, ReaComp, then **ReaLimit** (ceiling -1).", "With Hypnomix Main on the master, its **Build chain** button does it, bass mono included."],
            "ardour": ["On the master strip: ACE EQ, ACE Compressor, and a limiter (x42 Digital Peak Limiter, bundled with Ardour's own downloads).",
                       "Or let hypnomix master the exported WAV: the next step."]},
       action={d: dict(kind="chain") for d in LR}),
  dict(id="loud", title="Loudness, A/B and the reference", daws=ALL,
       say=["Turn the limiter's gain up while the loudest part plays until the master reads about **-14 LUFS** (a loudness "
            "meter, or hypnomix's Match target). Then compare with the mix **at the same loudness**: a louder version always "
            "sounds better for a moment, so match levels before you judge.",
            "Play a song you love next to yours, also level-matched, and listen for the low end, the brightness and how wide "
            "it feels. hypnomix's `match` lists the differences for you."],
       how={"live": ["HypnomixMain's **Match target** turns the limiter until the master hits the target, and its A/B is level-matched."],
            "reaper": ["Hypnomix Main's **Match target** does the same on REAPER's master."],
            "ardour": ["Use a loudness meter on the master (Window → Loudness Assistant), or master the WAV with hypnomix."]}),
  dict(id="deliver", title="Check it and export", daws=ALL,
       say=["Before you send it out, run hypnomix's checks on the master: `qc` (no clipping, the right loudness and peaks, "
            "silence at the ends) and `translate` (how it sounds on a phone, in mono, as an MP3). Then export the final WAV "
            "and you're done. Congratulations: that's a song, start to finish.",
            "Or let hypnomix master the bounce for you with `master` and approve each stage: Tools → master, or the Assistant."],
       app=dict(view="tools", label="Open the Tools tab")),
 ]),
 dict(id="hypnomix", levels=("tour", "101"), title="hypnomix in your DAW", sub="the app, the devices, and the loop: scan, hear, decide, apply", steps=[
  dict(id="hm-loop", title="How hypnomix works", daws=ALL,
       say=["hypnomix is a second engineer that never touches your original. Every job follows one loop: **preferences → "
            "scan → review → apply → listen**. The scan is read-only; the review lists each finding with a proposed fix and, "
            "where it can, a before and after to hear; you approve or skip; Apply writes only what you approved into a "
            "**new** set or project (or new audio files) next to yours.",
            "Taste stays yours. It finds technical things (clicks at edits, level jumps between takes, flat notes, "
            "masking, hum, loudness and true peak) and proposes gentle, partial fixes. Timing and tuning keep the human "
            "feel: nothing is quantised or hard-tuned, and a protected track is never changed without asking again."],
       how={"live": ["Answer the Preferences tab once (targets, protected tracks, how much to explain): every proposal starts from it."],
            "reaper": ["Answer the Preferences tab once: every proposal starts from it."],
            "ardour": ["Answer the Preferences tab once: every proposal starts from it."]},
       app=dict(view="prefs", label="Open Preferences")),
  dict(id="hm-connect-live", title="Connect hypnomix to Live", daws=("live",),
       say=["Two links, both optional for scanning a saved set. **AbletonOSC** (a control surface script) lets hypnomix "
            "drive the open set: arm and route tracks, punch-record, load Live's own devices, play bars. The **Max for Live "
            "devices** measure inside Live and follow the review; they need Max for Live (Suite, or the add-on) and the "
            "app running."],
       how={"live": ["Setup → Ableton Live copies the AbletonOSC script into your User Library (or `hypnomix install`). Restart Live.",
                     "Live → Settings → Link, Tempo & MIDI → Control Surface: **AbletonOSC**.",
                     "Keep the hypnomix app open while you work: the devices talk to it."]},
       action={"live": dict(kind="devices")}),
  dict(id="hm-connect-reaper", title="Connect hypnomix to REAPER", daws=("reaper",),
       say=["The **bridge** is a script that runs inside the open REAPER: nothing is installed and no setting changes, and "
            "every change it makes is one undo step named \"hypnomix: …\". The **JSFX** (Hypnomix Probe and Hypnomix Main) "
            "measure inside REAPER and carry the song card and the mastering chain buttons."],
       how={"reaper": ["`hypnomix reaper start` (or Setup → REAPER) runs the bridge, opening REAPER if it's closed.",
                       "`hypnomix reaper probes install` copies the JSFX into REAPER's Effects/hypnomix (the button below does it)."]},
       action={"reaper": dict(kind="devices")}),
  dict(id="hm-connect-ardour", title="hypnomix with Ardour", daws=("ardour",),
       say=["hypnomix reads Ardour 3 to 9 sessions (tracks, buses, regions with Ardour's layering, fades, gain envelopes, "
            "plug-ins, automation), renders each track itself, and runs the same first-pass checks. It can't write a new "
            "session or drive the open Ardour yet: session changes come back as a list for you to make, and audio fixes "
            "(tuning, de-hiss, de-ess) as repaired files to bring in.",
            "The reader hasn't been checked against a running Ardour yet: if a render sounds different from Ardour's export, say so."],
       how={"ardour": ["Save the session. On the Songs tab, choose the session folder (or its .ardour file) and Scan.",
                       "Ardour can stay open: nothing is written next to your session."]}),
  dict(id="hm-devices-live", title="The devices in Live", daws=("live",),
       say=["Three pass-through Max for Live devices (audio untouched), under User Library → Presets → Audio Effects → Max "
            "Audio Effect → Hypnomix:",
            "**HypnomixProbe**, last on every track, return and group: measures the track after all its plug-ins (loudness, "
            "peak, 8 bands, width), and holds what the track is, its priority (focus / background) and Protect. "
            "**HypnomixMain**, on Main: the mix meter, the **song card** (genre, key, scale, chords, target LUFS, ceiling, "
            "limiter character, amount), the mastering chain, and Record and review before export. **Hypnomix**, on any "
            "track: follows the app's review, jumps Live to each finding, Approve / Skip, and A / B / Blind in an A/B set.",
            "**Hypnomix Align** aligns a vocal stack (timing, optionally pitch and formant) to a guide track from inside "
            "Live, writing warp markers into a new set. It's the newest device: keep your original and listen."],
       how={"live": ["`hypnomix probe insert \"Song.als\"` writes \"Song (probes).als\" with a probe on every track, return and group, and Main on Main.",
                     "Set each probe's What it is (or leave auto), Priority and Protect; fill in the song card on HypnomixMain. They're Live parameters, so they're saved in the set and `scan` reads them.",
                     "The app's Live tab shows every probe while Live plays; Record → play → Stop makes a review from what was heard (frequency fights, the lead against the band, mono low end, loudness)."]}),
  dict(id="hm-devices-reaper", title="The JSFX in REAPER", daws=("reaper",),
       say=["**Hypnomix Probe** (last on each track) and **Hypnomix Main** (on the master) are the same meters as Live's "
            "devices, as REAPER effects: each probe holds what the track is, its priority and Protect; Main holds the song "
            "card (genre, key, scale, limiter character, target, ceiling, amount) and the buttons for the mastering chain "
            "and Record and review. The **Hypnomix panel** (`hypnomix reaper review`) steps through the app's review "
            "inside REAPER with A / B / Blind."],
       how={"reaper": ["`hypnomix reaper probes insert \"Song.rpp\"` writes \"Song (probes).rpp\" with a probe on every track and Main on the master (or Add FX → JS → Hypnomix Probe by hand).",
                       "With the bridge running and the app open, the app's Live tab shows every probe while REAPER plays; Record → play → Stop makes a review from what was heard.",
                       "When the bridge starts it gives each probe a slot number, so REAPER may ask to save once."]}),
  dict(id="hm-scan", title="The first pass: scan and review", daws=ALL,
       say=["On the **Songs** tab choose the saved set, project or session (or a folder of stems from any DAW), add a bounce of the "
            "mix if you have one (loudness, release checks, the key) and Scan. Every check runs in parallel and nothing "
            "changes. **Deep scan** also renders every track for frequency fights and mic phase.",
            "The review lists findings by severity. **Approve**, **Skip** or **Change** (with a note) each; *Approve all "
            "low* is there for the small ones. Checks that didn't run are listed at the top: no finding there means nothing."],
       how={"live": ["Save the set first: the scan reads the saved .als.", "Give the key on the Songs tab or the song card before any vocal tuning is applied."],
            "reaper": ["Save the project: the scan reads the .rpp and finds files the way REAPER does."],
            "ardour": ["Save the session, then scan its folder."]},
       app=dict(view="home", label="Open the Songs tab")),
  dict(id="hm-ab", title="Hear each fix in your DAW", daws=LR,
       say=["The review's players are quick renders. To hear a fix with every plug-in playing, **Build A/B set** "
            "(`hypnomix abset`) writes one new set or project where each fix sits beside what you have, switched off: a "
            "copy of the changed device, or a muted copy of the track with the fix.",
            "Switch **A · now** and **B · fix** instantly, turn **Match** on so B plays at A's loudness, or go **Blind** (X and "
            "Y in random order; your picks are kept and shown in the review). The A/B set is only for listening: Apply always "
            "writes from your original."],
       how={"live": ["In the review: Build A/B set for Live. Close the original, open \"Song (A-B).als\", put the Hypnomix device on any track."],
            "reaper": ["`hypnomix abset scan/Song`, open \"Song (A-B).rpp\", then `hypnomix reaper review` for the Hypnomix panel."]}),
  dict(id="hm-apply", title="Apply, history and undo", daws=ALL,
       say=["**Apply** writes only the approved fixes: a new set or project next to the original (close it in the DAW "
            "first), or repaired copies in the scan's fixed folder for audio. Every applied version is kept; undo writes "
            "another new version, it never deletes. Teach it as you go: what you skip and change shapes the next proposals."],
       how={"live": ["Close the set in Live, Apply, then open \"Song (fixed).als\"."], "reaper": ["Close the project tab, Apply, then open the new .rpp (tuned vocals arrive as new takes)."],
            "ardour": ["Apply lists the session changes to make by hand; repaired audio lands in the scan's fixed folder."]}),
  dict(id="hm-tracking", title="Tracking helpers", daws=ALL,
       say=["Before you record, `hypnomix soundcheck` listens to an interface input and tells you which way to turn the "
            "gain (peaks -12 to -6 dBFS in 24-bit), and flags noise, hum and DC. After recording, `takes` ranks whole "
            "takes and lists the best one per section, `vocalign` sits doubles and harmonies with the lead (gently: halfway "
            "toward the group, never forced onto the lead), and `clipmatch` evens out takes recorded on different days."],
       how={"live": ["`hypnomix live arm`, `live input`, `live record 17 8 3` punch-record through AbletonOSC (three passes = three take lanes).",
                     "Live 12's take lanes + `takes` for the comp; Hypnomix Align for stacks."],
            "reaper": ["Record takes as usual; export them from the same start and run `hypnomix takes`."],
            "ardour": ["Export the takes from the same start and run `hypnomix takes`; `vocalign` makes aligned copies to import."]},
       action={d: dict(kind="level") for d in ALL}),
  dict(id="hm-mixing", title="Mixing helpers", daws=ALL,
       say=["`stems` shows what each part contributes and its role; `masking` finds parts fighting over the same "
            "frequencies (your priority wins); `prep` and `automix` make many moves at once, so run them with `--plan` and "
            "review each move. `chain strips` loads your DAW's own EQ, compressor and utility with the recipe's settings, "
            "and `motion` offers effect moves for repetitive sections, learned from your own automation."],
       how={"live": ["`hypnomix chain strips recipe.json --dry-run` shows the plan; drop --dry-run to load EQ Eight, Compressor and Utility on each track."],
            "reaper": ["`hypnomix chain strips` builds the same strips from ReaEQ and ReaComp."],
            "ardour": ["Run them on exported stems; set the moves by hand in Ardour."]}),
  dict(id="hm-master", title="The mastering chain", daws=ALL,
       say=["On the master device, **Build chain** puts your DAW's own plug-ins before it: Tone (EQ, low cut 25 Hz, "
            "everything else at 0 dB), Glue (2:1, slow attack, never more than 3 dB), Tame and Warmth (switched off until "
            "needed), Width (bass mono below 120 Hz) and the Limiter (ceiling from the song card). **Match target** plays "
            "the loudest part and turns the limiter until the master hits the card's target LUFS. **Save** keeps any chain, "
            "yours included, as a template.",
            "Offline, `hypnomix master mix.wav --plan` turns each stage into a finding to approve, with test AAC and MP3 "
            "copies to keep the true peak safe."],
       how={"live": ["HypnomixMain → Mastering chain → Build chain (needs Live 12.3+): an Audio Effect Rack called Hypnomix Master, editable."],
            "reaper": ["Hypnomix Main's window → Build chain / Match target / Save chain (needs the bridge), or `hypnomix reaper chain build`."],
            "ardour": ["Export the mix and run `hypnomix master mix.wav --plan` (Tools tab → master)."]},
       action={d: dict(kind="chain") for d in LR}),
  dict(id="hm-export", title="Review before export", daws=ALL,
       say=["The last check: **Record and review before export** on the master device plays the song while every probe "
            "listens, then reviews the master against the song card: loudness and true peak, `qc`, `translate` (phone, mono, "
            "codecs) and `master --plan`. Fix any FAIL before you deliver."],
       how={"live": ["HypnomixMain → Record and review before export. Live's own Export makes the final file."],
            "reaper": ["Hypnomix Main → Record and review before export (or `hypnomix reaper record`): REAPER renders exactly what played and the app reviews it."],
            "ardour": ["Export the master, then run `qc` and `translate` on it from the Tools tab."]},
       app=dict(view="tools", label="Open the Tools tab")),
  dict(id="hm-ai", title="Working with an AI (optional)", daws=ALL,
       say=["Everything above works with no AI. If you'd like one: the **Assistant** tab runs the same loop by chat with your "
            "own key (Gemini's free tier, Claude, OpenRouter, OpenAI) or a model on your computer, and asks before anything "
            "writes. An agent app (Claude Code, Codex, Cursor) works through whole songs from the AI agent folder, with the "
            "first-pass, mix, mastering and tracking skills. Setup → How you work switches between them."],
       app=dict(view="chat", label="Open the Assistant")),
 ]),
]


def steps(daw, level="101"):
    """The chapters of one course (LEVELS) with only this DAW's steps, each step's 'how', settings and action
    resolved for it."""
    out = []
    for ch in CHAPTERS:
        if level not in ch.get("levels", ("101",)):
            continue
        ss = []
        for s in ch["steps"]:
            if daw not in s.get("daws", ALL):
                continue
            t = {k: s[k] for k in ("id", "title", "say") if k in s}
            for k in ("terms", "settings", "listen", "app"):
                if s.get(k):
                    t[k] = s[k]
            t["how"] = (s.get("how") or {}).get(daw, [])
            a = (s.get("action") or {}).get(daw)
            if a:
                t["action"] = describe(daw, s, a["kind"])
            ss.append(t)
        title = ch["title"].replace("your DAW", DAWS[daw]) if daw in DAWS else ch["title"]
        out.append(dict(id=ch["id"], title=title, sub=ch["sub"], steps=ss))
    return out


def count(daw, level="101"):
    return sum(len(c["steps"]) for c in steps(daw, level))


# ---------------------------------------------------------------- the hands-on actions
# What each action does, said before it's done: `fields` are the person's choices (with defaults), `will` the
# sentence they read before they click "Do it".

def _fx_of(daw, step):
    return (step.get("fx") or {}).get(daw)


def describe(daw, step, kind):
    name = DAWS[daw]
    if kind == "tempo":
        return dict(kind=kind, label="Set the tempo", fields=[dict(id="bpm", label="Tempo (BPM)", value=90, type="number")],
                    will=f"Set the song's tempo in {name} to {{bpm}} BPM.", changes=True)
    if kind == "click":
        return dict(kind=kind, label="Turn the click on", fields=[], will=f"Switch {name}'s metronome on.", changes=True)
    if kind == "drums":
        return dict(kind=kind, label="Add a drum beat", fields=[dict(id="feel", label="Feel", value="straight", options=["straight", "half-time"]),
                                                                dict(id="bars", label="Bars", value=4, type="number")],
                    will=(f"Add a MIDI track called Drums with {'a drum kit from the Browser' if daw == 'live' else 'ReaSynDr, REAPER’s drum synth'} "
                          "and a {bars}-bar {feel} beat (kick, snare on 2 and 4, eighth-note hi-hats, a little variation in how hard each hit lands)"
                          + (", as a clip in the first slot of the Session View: drag it into the Arrangement or loop it there." if daw == "live" else ", looped from the start of the project.")),
                    changes=True)
    if kind == "track":
        return dict(kind=kind, label="Make the track", fields=[dict(id="name", label="Name", value="Vocal"), dict(id="input", label="Interface input", value=1, type="number")],
                    will=f"Add an audio track called {{name}} in {name}, recording from input {{input}} of your audio interface, armed and with monitoring on"
                         + (" Auto." if daw == "live" else "."), changes=True)
    if kind == "level":
        return dict(kind=kind, label="Check my level", fields=[dict(id="input", label="Interface input", value=1, type="number")],
                    will="Listen to input {input} of your audio interface for 8 seconds while you play or sing the loudest part, then say which way to turn the gain. Nothing is recorded or saved.",
                    changes=False)
    if kind == "record":
        return dict(kind=kind, label="Record", fields=[dict(id="bars", label="Bars", value=8, type="number")] if daw == "live" else [],
                    will=("Record {bars} bars from bar 1 on every armed track in the Arrangement, after one bar of count-in, then stop."
                          if daw == "live" else "Start recording in REAPER on every armed track, from the edit cursor. Press Space in REAPER (or Stop here) to stop."),
                    changes=True)
    if kind == "fx":
        fx = _fx_of(daw, step)
        on = fx.get("track")
        return dict(kind=kind, label=f"Add {fx['device'].replace(' (Cockos)', '')}",
                    fields=[] if on else [dict(id="track", label="On the track", value="Vocal")],
                    will=(f"Add {fx['device'].replace(' (Cockos)', '')} to " + (f"return track {on}" if on else "the track {track}") +
                          " with the starting settings above (anything it can't set is listed for you to set by hand)."), changes=True)
    if kind == "devices":
        if daw == "live":
            return dict(kind=kind, label="Make the devices", fields=[],
                        will="Write HypnomixProbe, HypnomixMain and the Hypnomix review device into your Live User Library (Presets → Audio Effects → Max Audio Effect → Hypnomix). Your sets aren't touched; an older copy of a device is replaced.",
                        changes=True)
        return dict(kind=kind, label="Install the JSFX", fields=[],
                    will="Copy Hypnomix Probe and Hypnomix Main into REAPER's Effects/hypnomix folder. Your projects aren't touched; an older copy is replaced.",
                    changes=True)
    if kind == "chain":
        return dict(kind=kind, label="Build the mastering chain", fields=[],
                    will=("Add EQ Eight, Glue Compressor, Utility (bass mono below 120 Hz) and Limiter to the end of the Master track, every gain at 0 dB. Nothing already there is removed."
                          if daw == "live" else "Build the mastering chain on REAPER's master (Hypnomix Main's Build chain when Main is there; otherwise ReaEQ, ReaComp and ReaLimit). Nothing already there is removed."),
                    changes=True)
    raise ValueError(f"no such action {kind!r}")


def beat(bars=4, feel="straight", seed=7):
    """A plain drum beat with a little life: (pitch, start beat, length, velocity). General MIDI drums: 36 kick,
    38 snare, 42 closed hi-hat. Timing stays on the beat; only how hard each hit lands varies (a programmed part,
    so no one's playing is being moved)."""
    rnd = random.Random(seed)
    bars = max(1, min(int(bars), 16))
    out = []
    for b in range(bars):
        o = b * 4
        if feel == "half-time":
            kicks, snares = [0, 2.5], [2]
        else:
            kicks, snares = [0, 2, 2.5] if b % 2 else [0, 2], [1, 3]
        for k in kicks:
            out.append((36, o + k, 0.25, 104 + rnd.randint(-6, 6) if k == 0 else 92 + rnd.randint(-8, 6)))
        for s in snares:
            out.append((38, o + s, 0.25, 100 + rnd.randint(-6, 6)))
        for h in range(8):
            on = h % 2 == 0
            out.append((42, o + h * 0.5, 0.2, (84 if on else 62) + rnd.randint(-7, 7)))
    return sorted(out, key=lambda n: (n[1], n[0]))


def _live():
    from hypnomix.live.osc import Live
    return Live()


def _reaper():
    from hypnomix.reaper.client import Reaper
    return Reaper()


def connections():
    """Can the DAWs be driven right now? (Live: AbletonOSC answers; REAPER: the bridge is running.)"""
    out = {}
    try:
        lv = _live()
        try:
            out["live"] = lv.ping()
        finally:
            lv.close()
    except Exception:
        out["live"] = False
    try:
        out["reaper"] = _reaper().alive()
    except Exception:
        out["reaper"] = False
    out["ardour"] = False
    return out


REC = {"busy": False, "msg": ""}


def _fx_live(lv, fx, track):
    tid = lv.tid(track)
    i = lv.load_stock_device(tid, fx["device"])
    done, by_hand = [], []
    for how, names, value in fx["set"]:
        p = None
        try:
            p = lv.find_param(tid, i, names)
            if p is None:
                raise KeyError(names[0])
            (lv.set_param_display if how == "disp" else lv.set_param)(tid, i, p["name"], value)
            done.append(f"{p['name']} {value}")
        except Exception:
            by_hand.append(f"{names[0]}: {value}")
    return done, by_hand


def _fx_reaper(r, fx, track):
    idx = r.add_fx(track, fx["device"])["fx"]
    done, by_hand = [], []
    for how, p, value in fx["set"]:
        try:
            if how == "named":
                r.named(track, idx, p, value)
            else:
                r.set_shown(track, idx, p, value)
            done.append(f"{p} {value}")
        except Exception:
            by_hand.append(f"{p}: {value}")
    return done, by_hand


def _find_step(sid):
    for ch in CHAPTERS:
        for s in ch["steps"]:
            if s["id"] == sid:
                return s
    raise ValueError(f"no such step {sid!r}")


def level(inp=1, secs=8.0):
    from hypnomix.studio import soundcheck as SC
    try:
        y, sr = SC.record(None, int(inp), float(secs))
    except SystemExit as e:
        raise RuntimeError(str(e))
    except ImportError:
        raise RuntimeError("the level check needs the sounddevice package (pip install sounddevice); use the track's meter instead")
    r = SC.analyse(y, sr)
    return dict(done=" ".join(r["advice"]), peak=round(r["peak"], 1))


def run(daw, sid, kind, args):
    """Do one action. -> dict(done=text, by_hand=[...]). Raises on failure (the message says what to do)."""
    if daw not in DAWS:
        raise ValueError("choose your DAW first")
    step = _find_step(sid)
    allowed = ((step.get("action") or {}).get(daw) or {}).get("kind")
    if kind != allowed and not (kind == "stop" and allowed == "record" and daw == "reaper"):
        raise ValueError(f"that step has no {kind} action in {DAWS[daw]}")
    a = dict(args or {})
    if kind == "level":
        return level(a.get("input", 1))
    if kind == "devices":
        return make_devices(daw)
    if daw == "live":
        return _run_live(step, kind, a)
    if daw == "reaper":
        return _run_reaper(step, kind, a)
    raise ValueError(f"hypnomix can't drive {DAWS[daw]} yet: follow the steps above")


def _cli(*args):
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *args], capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise RuntimeError(f"hypnomix {' '.join(args)} failed: {(r.stderr or r.stdout).strip()[-400:]}")
    return r.stdout


def make_devices(daw):
    if daw == "live":
        _cli("probe", "device")
        _cli("device")
        return dict(done="Made HypnomixProbe, HypnomixMain and Hypnomix: in Live's Browser under User Library → Presets → Audio Effects → Max Audio Effect → Hypnomix.")
    if daw == "reaper":
        _cli("reaper", "probes", "install")
        return dict(done="Installed Hypnomix Probe and Hypnomix Main: in REAPER, Add FX → JS → hypnomix. (Restart REAPER's FX browser if they don't show yet.)")
    raise ValueError("Ardour has no hypnomix devices yet")


def _num(a, k, default, lo, hi):
    try:
        v = float(a.get(k, default))
    except (TypeError, ValueError):
        raise ValueError(f"{k} should be a number")
    if not lo <= v <= hi:
        raise ValueError(f"{k} should be between {lo:g} and {hi:g}")
    return v


def _run_live(step, kind, a):
    from hypnomix.live.osc import LiveError
    lv = _live()
    try:
        if not lv.ping():
            raise LiveError("Live isn't answering: open Live, and in Settings → Link, Tempo & MIDI choose AbletonOSC as a Control Surface (Setup → Ableton Live installs it)")
        if kind == "tempo":
            bpm = _num(a, "bpm", 90, 40, 250)
            lv.set_tempo(bpm)
            return dict(done=f"Tempo set to {bpm:g} BPM.")
        if kind == "click":
            on = lv.metronome(True)
            return dict(done="The click is on." if on else "Live didn't switch the click on: click the metronome icon by the tempo.")
        if kind == "drums":
            bars = int(_num(a, "bars", 4, 1, 16))
            feel = "half-time" if a.get("feel") == "half-time" else "straight"
            tid = lv.new_track("midi", "Drums")
            by_hand = []
            try:
                lv.load_browser_item(tid, "drums", "")
            except LiveError as e:
                by_hand.append(f"No drum kit loaded ({e}). In the Browser, open Drums and drag a kit onto the Drums track.")
            lv.new_clip(tid, 0, bars * 4, "Beat")
            notes = beat(bars, feel)
            lv.add_notes(tid, 0, notes)
            return dict(done=f"Added a Drums track with a {bars}-bar {feel} beat ({len(notes)} hits) in its first Session slot. Click the clip's play button to hear it.",
                        by_hand=by_hand)
        if kind == "track":
            name = str(a.get("name") or "Vocal")[:40]
            ch = int(_num(a, "input", 1, 1, 64))
            tid = lv.new_track("audio", name)
            by_hand = []
            try:
                kinds = lv.inputs(tid)[0]
                ext = next((k for k in kinds if str(k).lower().startswith("ext")), None)
                if ext:
                    lv.set_input(tid, ext, None)
                chans = lv.inputs(tid)[1]
                want = next((c for c in chans if str(c).strip() == str(ch)), None)
                if want:
                    lv.set_input(tid, None, want)
                else:
                    by_hand.append(f"Input {ch} isn't on the list for this interface: choose it under Audio From on the {name} track.")
            except Exception:
                by_hand.append(f"Choose Audio From → Ext. In → {ch} on the {name} track.")
            lv.monitor(tid, "auto")
            lv.arm(tid, True)
            return dict(done=f"Made the {name} track, recording from input {ch}, armed, monitoring Auto.", by_hand=by_hand)
        if kind == "record":
            bars = int(_num(a, "bars", 8, 1, 64))
            if REC["busy"]:
                raise ValueError("already recording")

            def go():
                l2 = _live()
                try:
                    REC.update(busy=True, msg="")
                    l2.record(1, bars, 1, preroll=1)
                    REC["msg"] = f"Recorded {bars} bars."
                except Exception as e:
                    REC["msg"] = f"Recording stopped: {e}"
                finally:
                    REC["busy"] = False
                    l2.close()
            lv.close()
            lv = None
            threading.Thread(target=go, daemon=True).start()
            return dict(done=f"Recording {bars} bars from bar 1, after a bar of count-in. Live stops on its own.")
        if kind == "fx":
            fx = _fx_of("live", step)
            track = fx.get("track") or str(a.get("track") or "")
            if not track:
                raise ValueError("which track?")
            done, by_hand = _fx_live(lv, fx, track)
            return dict(done=f"Added {fx['device']} to {track}" + (f": {', '.join(done)}." if done else "."),
                        by_hand=[f"Set by hand: {x}" for x in by_hand])
        if kind == "chain":
            from hypnomix.app.masterchain import STOCK
            added, by_hand = [], []
            for st in STOCK["stages"]:
                if not st["on"]:
                    continue
                fx = dict(device=st["device"], set=[[("raw" if how == "raw" else "disp"), names, v]
                                                    for names, v, how in st["set"] if how in ("raw", "disp")])
                d, h = _fx_live(lv, fx, "Master")
                added.append(st["device"])
                by_hand += [f"{st['device']}: {x}" for x in h]
            return dict(done=f"Added {', '.join(added)} to the Master track. Raise the Limiter's gain until the song reaches its target (next step).",
                        by_hand=[f"Set by hand: {x}" for x in by_hand])
        raise ValueError(f"no such action {kind!r}")
    finally:
        if lv is not None:
            lv.close()


def _run_reaper(step, kind, a):
    from hypnomix.reaper.client import ReaperError
    r = _reaper()
    if not r.alive():
        raise ReaperError("REAPER's bridge isn't running: open REAPER, then run `hypnomix reaper start` (Wiki → hypnomix in REAPER)")
    if kind == "tempo":
        bpm = _num(a, "bpm", 90, 40, 250)
        out = r.call("teach_tempo", bpm=bpm)
        return dict(done=f"Tempo set to {float(out.get('bpm', bpm)):g} BPM.")
    if kind == "click":
        out = r.call("teach_click", on=1)
        return dict(done="The metronome is on." if out.get("on") else "REAPER didn't switch the metronome on: click its button in the transport.")
    if kind == "drums":
        bars = int(_num(a, "bars", 4, 1, 16))
        feel = "half-time" if a.get("feel") == "half-time" else "straight"
        notes = beat(bars, feel)
        out = r.call("teach_drums", name="Drums", beats=bars * 4, notes=";".join(f"{p},{s:g},{d:g},{v}" for p, s, d, v in notes))
        by_hand = [] if (out.get("fx", -1) >= 0) else ["ReaSynDr didn't load: add a drum instrument to the Drums track (FX → Instruments)."]
        return dict(done=f"Added a Drums track with ReaSynDr and a looped {bars}-bar {feel} beat ({out.get('notes', len(notes))} hits).", by_hand=by_hand)
    if kind == "track":
        name = str(a.get("name") or "Vocal")[:40]
        ch = int(_num(a, "input", 1, 1, 64))
        r.call("teach_track", name=name, input=ch, arm=1, monitor=1)
        return dict(done=f"Made the {name} track, recording from input {ch}, armed, monitoring on.")
    if kind == "record":
        r.transport(go="record")
        return dict(done="Recording. Press Space in REAPER (or Stop here) to stop.")
    if kind == "stop":
        r.transport(go="stop")
        return dict(done="Stopped.")
    if kind == "fx":
        fx = _fx_of("reaper", step)
        track = str(a.get("track") or "")
        if not track:
            raise ValueError("which track?")
        done, by_hand = _fx_reaper(r, fx, track)
        return dict(done=f"Added {fx['device']} to {track}.", by_hand=[f"Set by hand: {x}" for x in by_hand])
    if kind == "chain":
        try:
            r.call("chain_build", name="hypnomix stock", yes=1)
            return dict(done="Built the mastering chain before Hypnomix Main on the master.")
        except ReaperError:
            added, by_hand = [], []
            for dev, sets in (("ReaEQ (Cockos)", [["named", "BANDTYPE0", "4"], ["shown", 0, 25]]),
                              ("ReaComp (Cockos)", [["shown", "Ratio", 2], ["shown", "Attack", 30], ["shown", "Thresh", -12]]),
                              ("ReaLimit (Cockos)", [["shown", "Ceiling", -1]])):
                d, h = _fx_reaper(r, dict(device=dev, set=sets), "master")
                added.append(dev.replace(" (Cockos)", ""))
                by_hand += h
            return dict(done=f"Added {', '.join(added)} to the master (for bass mono and Match target, put Hypnomix Main on the master and press Build chain).",
                        by_hand=[f"Set by hand: {x}" for x in by_hand])
    raise ValueError(f"no such action {kind!r}")


# ---------------------------------------------------------------- state
def load_progress():
    try:
        return json.loads(progress_file().read_text())
    except (OSError, ValueError):
        return {}


def save_progress(p):
    progress_file().parent.mkdir(parents=True, exist_ok=True)
    progress_file().write_text(json.dumps(p, indent=1))


def choice():
    """-> (daw, course level or "" when teacher mode is off, how they work)"""
    from hypnomix.app import setup as SU
    s = SU.load()
    lv = s.get("teach_level") or ("101" if s.get("teach") else "")
    return s.get("daw", ""), lv if lv in LEVELS else "", s.get("mode", "")


def state(daw=None, level=None):
    d, lv, mode = choice()
    daw = daw if daw in DAWS else d if d in DAWS else ""
    level = level if level in LEVELS else lv or "101"
    p = load_progress()
    return dict(daw=daw, daws=DAWS, level=level, levels=LEVELS, teach=bool(lv), mode=mode,
                chapters=steps(daw, level) if daw else [],
                done=sorted(p.get(daw, {}).get("done", [])) if daw else [], at=p.get(daw, {}).get("at", "") if daw else "",
                recording=REC)


def mark(daw, sid, done=True, at=None, level=None):
    p = load_progress()
    q = p.setdefault(daw, {"done": []})
    s = set(q.get("done", []))
    if sid:
        (s.add if done else s.discard)(sid)
    q["done"] = sorted(s)
    if at is not None:
        q["at"] = at
    save_progress(p)
    return state(daw, level)


def assistant_note():
    """For the Assistant's instructions when teacher mode is on: who it's talking to."""
    d, lv, _ = choice()
    if not lv:
        return ""
    if lv == "tour":
        return (f"\n\nTeacher mode is on (the hypnomix tour): the person already knows recording and mixing, and is learning "
                f"hypnomix with {DAWS.get(d, 'their DAW')}: its loop, its devices for that DAW, the song card, A/B inside the DAW, "
                "the mastering chain. Skip audio basics unless asked; be precise about hypnomix's commands, buttons and limits, "
                "and follow the Teacher tab's order when they ask what's next.")
    return (f"\n\nTeacher mode is on (the 101 crash course): the person is a beginner who may never have used a DAW before, working in "
            f"{DAWS.get(d, 'their DAW')}. Explain in plain words, one idea at a time, define each term the first time you "
            "use it, say exactly where to click in their DAW, and check they're ready before moving on. The Teacher tab "
            "holds the lessons (record to a click, arm a track, set input gain, each effect as it's added, mastering); "
            "follow its order when they ask what's next. Encourage them: mistakes are fine and nothing changes without their OK.")


# ---------------------------------------------------------------- the wiki: one article per DAW, from the lessons
def _md_text(t):
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _esc(t))


def _esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


WIKI_GROUP = {"live": "DAW: Ableton Live", "reaper": "DAW: REAPER", "ardour": "DAW: Ardour"}


def wiki_article(daw, level="101"):
    """One course for one DAW as a wiki article (HTML in the wiki's own style)."""
    name = DAWS[daw]
    thing = "set" if daw == "live" else "project" if daw == "reaper" else "session"
    lead = (f"A crash course for people new to audio: the words, recording to a click, each effect as you add it, and mastering, "
            f"from an empty {name} {thing} to a mastered song, then hypnomix's own tools. " if level == "101" else
            f"For people who already record and mix: hypnomix with {name}, its devices, and the loop from scan to master. ")
    parts = [f'<p class="lead">{lead}In the app, the <b>Teacher</b> tab walks you through the same steps, and can do the '
             'hands-on ones for you (it asks first).</p>']
    for ch in steps(daw, level):
        parts.append(f"<h3>{_esc(ch['title'])}</h3><p><i>{_esc(ch['sub'])}</i></p>")
        for s in ch["steps"]:
            parts.append(f"<h4>{_esc(s['title'])}</h4>" + "".join(f"<p>{_md_text(x)}</p>" for x in s.get("say", [])))
            if s.get("terms"):
                parts.append("<dl>" + "".join(f"<dt>{_esc(w)}</dt><dd>{_esc(m)}</dd>" for w, m in s["terms"]) + "</dl>")
            if s.get("settings"):
                parts.append('<div class="tablewrap"><table><tr><th>Control</th><th>Where to start</th><th>Why</th></tr>' +
                             "".join(f"<tr><td>{_esc(a)}</td><td>{_esc(b)}</td><td>{_esc(c)}</td></tr>" for a, b, c in s["settings"]) + "</table></div>")
            if s.get("how"):
                parts.append(f"<p><b>In {name}</b></p><ol>" + "".join(f"<li>{_esc(x)}</li>" for x in s["how"]) + "</ol>")
            if s.get("listen"):
                parts.append(f'<div class="note-box"><b>Listen:</b> {_esc(s["listen"])}</div>')
    if daw == "ardour":
        parts.append('<div class="note-box">Ardour gets the short version for now: hypnomix can read and scan Ardour sessions, '
                     'but can\'t drive Ardour yet, so every step here is done by hand.</div>')
    html = '<div class="prose paper">' + "\n".join(parts) + "</div>"
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
    aid = f"learn-{daw}" if level == "101" else f"tour-{daw}"
    title = f"101: make a song from scratch in {name}" if level == "101" else f"Guided tour: hypnomix in {name}"
    sub = ("teacher mode · the words, recording to a click, each effect, mastering" if level == "101"
           else "teacher mode · the devices, the song card, A/B, the mastering chain")
    return dict(id=aid, group=WIKI_GROUP[daw], title=title, sub=sub, no="", teaser="",
                html=html, text=text, url=f"https://hypnomix.bradfieldenterprises.org/wiki/#{aid}",
                file=str(Path(__file__).resolve()), generated=True)


# ---------------------------------------------------------------- the server's routes
def handle_get(path, q):
    if path == "/teacher.js":
        return 200, Path(__file__).with_name("teacher.js").read_bytes(), "text/javascript; charset=utf-8"
    if path == "/api/teach/state":
        return 200, state(q.get("daw"), q.get("level"))
    if path == "/api/teach/connections":
        return 200, connections()
    return None


def handle_post(path, body):
    if path == "/api/teach/mark":
        daw = str(body.get("daw", ""))
        if daw not in DAWS:
            return 400, dict(error="choose your DAW first")
        return 200, mark(daw, str(body.get("step", "")), bool(body.get("done", True)), body.get("at"), body.get("level"))
    if path == "/api/teach/do":
        if body.get("ok") is not True:
            return 400, dict(error="this changes your song: it needs your OK first")
        try:
            return 200, run(str(body.get("daw", "")), str(body.get("step", "")), str(body.get("kind", "")), body.get("args") or {})
        except ValueError as e:
            return 400, dict(error=str(e))
        except Exception as e:
            return 500, dict(error=str(e))
    return None
