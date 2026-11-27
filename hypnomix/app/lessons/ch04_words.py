"""Chapter: The words and the screen."""
from hypnomix.app.lessons._common import ALL, LR, az_only, enrich, place
from hypnomix.app.lessons import ch04_words_steps

CHAPTER = dict(id="words", levels=("101", "az"), title="The words and the screen", sub="what a DAW is, and the names for everything on it", steps=[
  dict(id="daw", title="What a DAW is", daws=ALL,
       say=["A **DAW** (digital audio workstation) is a recording studio inside your computer: a tape machine, a mixing desk "
            "and a rack of effects in one program. You record into it, arrange the parts, mix them, and export one stereo "
            "file at the end.",
            "Everything you'll do follows one path: **record → edit → mix → master → export**. This course walks it once, "
            "start to finish, with your own song. Take it slowly: nothing here can break your music, and every change "
            "HypnoMix makes asks you first."],
       terms=[["Project / set / session", "your song's file. Live calls it a Set (.als), REAPER a Project (.rpp), HypnoMix DAW a Session (a folder)."],
              ["Track", "one lane for one sound: a vocal, a guitar, the drums. Audio tracks hold recordings; MIDI tracks hold notes that play an instrument."],
              ["Clip / item / region", "a piece of recording or notes on a track. Live says clip, REAPER item, HypnoMix DAW region."],
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
                     "Open the Audio tab of Live's Settings (called Preferences in Live 11): the Live menu on a Mac, the Options menu on Windows. Choose your audio interface for both input and output."]}),
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
                       "Options → Preferences → Audio → Device: choose your audio interface for both input and output.",
                       "Ctrl+T (Cmd+T on a Mac) adds a track; double-click its name to rename it.",
                       "Click a track's **FX** button to open its FX chain: the effects run top to bottom, in the order the sound flows through them.",
                       "Ctrl+M / Cmd+M shows the mixer; View → Master track shows the master if it is hidden. Space plays and stops; Ctrl+R / Cmd+R records.",
                       "Press **?** (or Actions → Show action list) and type a few words to find any command by name."]}),
  dict(id="screen-ardour", title="A tour of HypnoMix DAW's screen", daws=("ardour",),
       say=["HypnoMix DAW has two main windows: the **Editor** (the timeline, with tracks top to bottom) and the **Mixer** "
            "(Alt+M switches between them). A song is a *session*: a folder with the session file and every recording."],
       terms=[["Region", "a piece of recording on a track."], ["Bus", "a track with no recordings of its own, that other tracks feed: used for groups and effects."],
              ["Strip", "one track's column in the Mixer: input, plug-ins, pan, fader."]],
       how={"ardour": ["Start HypnoMix DAW, choose your audio interface in the Audio/MIDI Setup window, and make a new session.",
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
 ])


_ORDER = ['daw', 'screen-live', 'screen-reaper', 'screen-ardour', 'signal', 'words-audio-settings', 'words-template', 'words-naming-colour']
CHAPTER["steps"] = enrich(place(CHAPTER["steps"] + az_only(ch04_words_steps.STEPS), _ORDER), ch04_words_steps.ENRICH)
