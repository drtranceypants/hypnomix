"""Chapter: Your first recording."""
from hypnomix.app.lessons._common import ALL, LR, az_only, enrich, place
from hypnomix.app.lessons import ch06_record_steps

CHAPTER = dict(id="record", levels=("101", "az"), title="Your first recording", sub="tempo, the click, a beat to play over, a track that's ready, the right level", steps=[
  dict(id="tempo", title="Choose a tempo", daws=ALL,
       say=["Before you record, give the song a tempo. Tap your foot to the song and count: most songs sit between 70 and "
            "130 BPM. The tempo sets the click and the bar lines, so a part recorded to it lines up with everything else.",
            "Not sure? Pick something close; you can change the tempo before you record, not easily after."],
       how={"live": ["Click the tempo field at the top left (it says 120.00) and type a number, or click **TAP** in time with your foot."],
            "reaper": ["Double-click the tempo number in the transport bar and type the BPM, or click the **BPM** button in the transport in time with the music to tap the tempo."],
            "ardour": ["Double-click the tempo marker at the start of the Tempo ruler and type the BPM."]},
       action={d: dict(kind="tempo") for d in LR}),
  dict(id="click", title="Record to a click", daws=ALL,
       say=["The **click** (metronome) ticks on every beat while you play. Recording to it keeps the bar lines meaningful, so "
            "later you can copy a chorus, drop in drums or fix one word without everything drifting.",
            "It doesn't make you a machine. Play with it, not *at* it: being a little ahead or behind is the feel of the "
            "song, and HypnoMix never forces your playing onto the grid. Give yourself a **count-in** (one or two bars of "
            "click before recording starts) so you come in on time.",
            "In your headphones, not the speakers: a click in the room ends up on the vocal mic."],
       how={"live": ["Click the metronome icon (the two circles next to the tempo) so it lights up.",
                     "Its little arrow menu: set **Count-In** to 1 Bar.", "The click goes to your headphones through Live's Cue output (open Live's Preferences, called Settings in Live 12, then Audio, and use the Mixer's Cue Out)."],
            "reaper": ["Click the metronome button in the transport bar (or Options → Metronome) so it's on.",
                       "Right-click it → Metronome settings: tick **Count-in before recording** (2 bars is comfortable)."],
            "ardour": ["Click the **Click** button in the toolbar so it lights up.", "In the Transport menu, choose **Record w/Count-In**: HypnoMix DAW clicks two bars before it starts recording."]},
       action={d: dict(kind="click") for d in LR}),
  dict(id="drums", title="A drum beat to play over (optional)", daws=ALL,
       say=["A click is honest but dull. A simple drum beat on a **MIDI track** is nicer to play to, and you can replace it "
            "with real drums or a better beat later.",
            "MIDI is notes, not sound: each note says *which drum, when, how hard*. The drum kit on the track turns those "
            "notes into sound, so you can change the kit, the tempo or a single hit at any time.",
            "HypnoMix can add a four-bar beat: kick, snare on 2 and 4, eighth-note hi-hats, with small differences in how "
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
            "HypnoMix can listen to your input for about 15 seconds while you sing or play your loudest part (`hypnomix soundcheck`), and tell you which way to turn the knob."],
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
                     "Press Space to stop. Record again over the same bars: Live 11 and 12 keep each pass as a take lane (right-click the track's name → Show Take Lanes)."],
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
            "the song plays, or drag clips across. The drum beat HypnoMix adds lands in the Session View for this reason."],
       terms=[["Scene", "one row of clips, launched together."], ["Launch quantisation", "clips start on the next bar, so they stay in time when you click them."]],
       how={"live": ["Press Tab for the Session View. With a track armed, click a slot's record button (the circle) to record a clip; click again to stop and loop it.",
                     "Click a scene's play button on the right to launch the whole row.",
                     "To record what you launch into the timeline: Arrangement Record (F9), then launch scenes."]}),
  dict(id="takes-hypnomix", title="Let HypnoMix help with the takes", daws=ALL,
       say=["Once you have takes, HypnoMix's **first pass** (the Songs tab) checks the recording for the technical things "
            "ears miss at first: clicks where a take was cut, the level jumping between takes, notes that drifted flat, "
            "hum and hiss. It suggests a fix for each, lets you hear before and after, and changes nothing until you say yes.",
            "For now, keep recording the rest of the song: each instrument gets its own track, recorded the same way."],
       app=dict(view="home", label="Open the Songs tab")),
 ])


_ORDER = ['tempo', 'click', 'drums', 'rec-monitoring', 'rec-headphone-mix', 'rec-tune-up', 'track', 'gain', 'rec-voice', 'rec-guitar-bass', 'take', 'rec-punch-loop', 'rec-doubling', 'session-sketch', 'rec-good-enough', 'takes-hypnomix']
CHAPTER["steps"] = enrich(place(CHAPTER["steps"] + az_only(ch06_record_steps.STEPS), _ORDER), ch06_record_steps.ENRICH)
