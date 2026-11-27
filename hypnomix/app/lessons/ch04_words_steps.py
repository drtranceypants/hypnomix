"""Chapter: The words and the screen (az course additions). Audio settings, a starting template, naming and colouring."""
from hypnomix.app.lessons._common import ALL, LR

STEPS = [
 dict(id="words-audio-settings", title="Audio settings and the buffer", daws=ALL,
      say=["Before the first recording, tell your DAW which audio device to use. If it is set wrongly, you hear nothing, "
           "or you hear your laptop's own speakers, or the mic never records. It takes two minutes and you only do it once.",
           "Choose your **audio interface** as both the **input** (where sound comes in) and the **output** (where the "
           "DAW plays out to your headphones and speakers). Then check the **sample rate** matches what you want for the "
           "song (48 kHz or 44.1 kHz), and pick a first **buffer size**. Start with 128 samples while you record and "
           "raise it to 512 or more when you mix; the lesson on buffers explains the trade.",
           "Then test it. Play a sound and watch the meter. If the meter moves and you hear it, output is working. For input, "
           "arm a track, make a noise into the mic, and watch that track's meter. A moving meter means the sound is "
           "arriving."],
      terms=[["Audio device", "the thing your DAW sends sound to and gets sound from: usually your audio interface. The laptop's own speakers and mic are also devices."],
             ["Input / output", "input is where sound enters the DAW (the mic); output is where it leaves (headphones, speakers)."],
             ["Driver type", "the way the DAW talks to the device. On a Mac the default is fine; on Windows an ASIO driver from the interface's maker is usually best."],
             ["Meter", "the level display on a track or the master. Moving means signal is arriving."]],
      settings=[["Audio device", "your audio interface, for input and output", "the laptop's own speakers and mic add delay and are poor quality"],
                ["Sample rate", "48 kHz (or 44.1 kHz)", "match what the song will use; keep it for the whole project"],
                ["First buffer size", "128 samples", "low enough to record without a noticeable delay"],
                ["Buffer when mixing", "512 samples or more", "gives the computer time for plug-ins"]],
      how={"live": ["Open the Audio tab of Live's Settings (called Preferences in Live 11): the Live menu on a Mac, the Options menu on Windows.",
                    "Set the Audio Device to your interface (the driver type first, if Live asks for one), then check the Sample Rate and Buffer Size.",
                    "Make a new audio track, set its input in the track's In/Out section, arm it, and watch the meter while you speak."],
           "reaper": ["Open Options → Preferences → Audio → Device.",
                      "Choose your interface for both input and output (on Windows, the ASIO driver first, if your interface has one).",
                      "Check the sample rate and the buffer (block) size: on a Mac with Request sample rate and Request block size; on Windows with ASIO, through ASIO Configuration, the interface's own control panel.",
                      "Click Apply, add a track, arm it and choose its input (right-click the record button), and watch the meter while you speak."],
           "ardour": ["Open Window → Audio/MIDI Setup.",
                      "Choose your interface as both the input device and the output device, and set the sample rate and buffer size.",
                      "Start the audio engine, add a track, and watch its meter while you speak."]},
      listen="Play a loud part of any song: the master meter should move, and the sound should come from your headphones or "
             "speakers, not the laptop. Then arm a track and say a word: that track's meter should jump with your voice.",
      mistakes=["Leaving the laptop's own microphone as the input. The track records, but it records the room, not your interface.",
                "Monitoring through both the DAW and the interface so you hear a short echo of yourself. Turn off one of them.",
                "Setting a different sample rate in the DAW and in the interface's own control panel. Match them."],
      **{"try": dict(do="Open your audio settings and choose your interface. Set the buffer to 128, play a song, then arm a track and speak into the mic.",
                     success="You hear the song from the right place and both meters move: the master while it plays, and the track's while you speak.")},
      quiz=[dict(q="You press play and see the master meter move, but you hear nothing. What is the likely cause?", options=["The sample rate is wrong", "The output device isn't your interface", "The buffer is too small"], answer=1,
                 why="The DAW is playing, so the meter moves, but the sound is going to a different output. Choose your interface as the output."),
            dict(q="What is a sensible first buffer size for recording?", options=["64 to 128 samples", "2048 samples", "8192 samples"], answer=0,
                 why="A small buffer keeps the delay low, so you hear yourself without a lag.")],
      more=["step:dig-buffer-latency", "step:signal", "setup"]),

 dict(id="words-template", title="A starting template", daws=ALL,
      say=["Every song starts the same way. You make the tracks, set the click, add a reverb for the voice and a delay, "
           "name everything. If you do that fresh each time, it eats the first ten minutes of every session and it is "
           "where mistakes creep in. A **template** is a project you saved with all of that done, so each new song "
           "begins from it.",
           "Put in only what you use every time. A set of **named tracks** (lead vocal, a harmony, guitar, bass, drums), "
           "the **click** switched on, a **reverb** and a **delay** on shared send tracks, and a **vocal track** set up with "
           "its input chosen and an EQ and a compressor ready. Keep the levels low and the effects off or gentle: the "
           "template is a starting point, not a sound.",
           "Save it with a clear name such as 'Template' and open a copy for each new song, saving it under a new name "
           "straight away so the template stays clean. Update the template when you learn a better way of working."],
      terms=[["Template", "a saved project with your usual setup, used as the start for each new song."],
             ["Send / return track", "a shared effect track (a reverb or delay), fed by a send knob on each track."],
             ["Click", "the metronome. It keeps your playing in time with the tempo."]],
      settings=[["Tracks in the template", "the ones you use on every song, named", "no need to create and name them each time"],
                ["Click", "on, at a sensible default tempo (such as 100 BPM)", "ready to record; change the tempo for each song"],
                ["Reverb and delay sends", "one of each, levels low", "the whole song shares one space, and each track just sends some"],
                ["Vocal track", "input chosen, EQ and compressor loaded", "the one you set up most; ready to record on"]],
      how={"live": ["Set up a new Set with your tracks, return tracks (reverb and delay), and click.",
                    "Use File → Save Live Set As... and save it as 'Template'. For each new song, open it and use Save Live Set As... straight away to give the song its own name.",
                    "Your Live version may also let you save the current Set as the default for new Sets: look in Settings → Library."],
           "reaper": ["Set up the project with your tracks, sends, and click.",
                      "Use File → Project templates → **Save project as template...** and give it a name.",
                      "For a new song, use File → Project templates and choose your template, then File → Save project as… straight away to give the song its own name.",
                      "For one track's set-up on its own (a vocal with its plug-ins), right-click the track and choose **Save tracks as track template**."],
           "ardour": ["Set up a session with your tracks, buses and click.",
                      "HypnoMix DAW can save a session as a template (look in the Session menu), and offers your templates when you create a new session."]},
      listen="Open a new song from the template and press play. The click should sound, the vocal track should meter when you sing, "
             "and the reverb return should be ready but quiet.",
      mistakes=["Saving over the template while working on a song. Save as the song's name first.",
                "Filling the template with effects you don't need, so every song starts with a sound you didn't choose.",
                "Never updating the template. When you notice yourself fixing the same thing in every song, change the template."],
      **{"try": dict(do="Build a project with a lead vocal track, a guitar track, a reverb send and a delay send, with the click on. Save it as a template, then open a new song from it.",
                     success="The new song opens with every track named and the click ready, and you saved it under a different name before you recorded anything.")},
      quiz=[dict(q="What is a template for?", options=["To make your songs sound the same", "To avoid doing the same setup every time", "To fix a mix automatically"], answer=1,
                 why="It holds the setup you repeat on every song, so you start recording sooner. The sound is still yours."),
            dict(q="After opening your template for a new song, what do you do first?", options=["Record straight away", "Save it under the song's name", "Delete the unused tracks"], answer=1,
                 why="Saving under the new name keeps the template clean for the next song.")],
      more=["step:words-naming-colour", "step:dig-project-files"]),

 dict(id="words-naming-colour", title="Naming and colouring tracks", daws=ALL,
      say=["A DAW names new tracks 'Audio 1', 'Audio 2', 'Audio 3'. By the tenth track, nobody knows which is the lead "
           "vocal and which is a harmony. Give every track a **clear name** the moment you make it: 'Lead Vocal', 'Harmony 1', "
           "'Acoustic Guitar', 'Bass', 'Kick'. You will move faster, and you will stop turning down the wrong track.",
           "Then give related tracks the **same colour**. Drums are all one colour, vocals another, guitars a third, bass "
           "its own. On a screen with thirty tracks you can find the vocals at a glance, and a track that is the wrong "
           "colour for its group stands out.",
           "HypnoMix has a command that helps with the naming. `hypnomix name SET.als` is a dry run on a Live set: it proposes a "
           "name for every track that still has a default-style name (\"Audio 2\", \"4-MIDI\", \"7-Group\") by what it sounds "
           "like, using clues in the existing names, clip file names, devices and presets, and the audio itself. It "
           "also names groups after what their tracks mostly are, and in a vocal group the part that sings most is "
           "'Lead Vocal' and the others are 'Harmony 1' upward from low to high. A low-confidence guess is called "
           "'Instrument' and listed for you to name. It changes nothing until you add `--apply`, which renames the tracks in the open "
           "Live set, and `--undo` puts the previous names back. It leaves names you chose yourself alone unless you add `--all`. "
           "HypnoMix proposes; you decide."],
      terms=[["Track name", "the label on a track. A clear one saves time and prevents mistakes."],
             ["Track colour", "a colour you give a track, so related tracks are easy to find at a glance."],
             ["Group", "several tracks combined so you can control them together, such as all the drums. Colour a group the same as its tracks."]],
      settings=[["Names", "short, specific, one idea per track: 'Lead Vocal', 'Harmony 1', 'Bass'", "readable on a narrow track and in the mixer"],
                ["Colour by family", "drums one colour, vocals another, guitars another, bass another", "finds the family at a glance"],
                ["When to name", "as soon as you create the track", "naming later never happens"]],
      how={"live": ["Click the track's name, then press Cmd+R (Ctrl+R on Windows), or right-click the name and choose Rename. Type the name and press Return.",
                    "Right-click the track name to open the menu and pick a colour from it."],
           "reaper": ["Double-click the track's name, type the new name, and press Enter.",
                      "Right-click the track, then choose Track color and pick a colour. Select several tracks first (Ctrl+click / Cmd+click) to colour a whole family at once.",
                      "The mixer and the items on the track use the same colour, so one colour per family (drums, bass, guitars, vocals) makes the song easy to read."],
           "ardour": ["Double-click the track's name, type the new name, and press Enter.",
                      "Click the track's name button to open its menu and choose Color..."]},
      listen="Open the mixer with the song playing and look at the whole thing. You should be able to point to every vocal, "
             "every drum and every guitar without reading a single name.",
      mistakes=["Leaving 'Audio 12' because you'll rename it later. Do it when you create the track.",
                "Using a different colour for every track, which makes the colours meaningless. Colour by family.",
                "Long names that get cut off in the mixer. Keep them short: 'Gtr Rhythm', not 'Rhythm guitar played on the green amp'."],
      **{"try": dict(do="Open a song and name every track. Give all the drum tracks one colour, the vocals another, and the guitars a third.",
                     success="You can find the lead vocal in under two seconds, and no track in the song is still called Audio 1, 2 or 3.")},
      quiz=[dict(q="Why colour related tracks the same?", options=["It makes the song sound better", "You find a family of tracks at a glance", "The DAW needs it to mix"], answer=1,
                 why="Colour doesn't change the sound. It makes a big project readable at a glance."),
            dict(q="What does `hypnomix name SET.als` do without --apply?", options=["Renames the tracks in the open Live set", "Shows proposed names as a dry run, changing nothing", "Deletes tracks with default names"], answer=1,
                 why="Without --apply it is a dry run: it proposes names and prints a report. Only --apply renames, and --undo puts the old names back.")],
      more=["hypnomix name", "step:words-template"]),
]

ENRICH = {
 "daw": dict(
   mistakes=["Working in a project with no clear idea which file you are in. Learn what your DAW calls a song (Set, Project or Session) and where it is saved.",
             "Expecting the DAW to change your recordings. Its edits are non-destructive: the audio files stay as recorded unless you export or bounce.",
             "Trying to learn every button at once. Learn the path first (record, edit, mix, master, export) and the rest follows."],
   **{"try": dict(do="Open your DAW and make a new project. Add one audio track, find the transport (play, stop, record), the timeline and the mixer, and say aloud what each one is for.",
                  success="You can point to the track, the clip (or item or region), the transport and the master, and say what each does.")},
   quiz=[dict(q="What is a DAW?", options=["A microphone preamp", "A recording studio inside your computer", "A kind of audio file"], answer=1,
              why="A digital audio workstation is a program that records, edits, mixes and exports your music."),
         dict(q="What is a track?", options=["One lane that holds one sound", "The whole song", "The master volume"], answer=0,
              why="A track holds one source, such as a vocal or a guitar. The master is the last track that all the others feed.")]),
 "signal": dict(
   mistakes=["Judging a track by its fader alone. A track's level is the recording, its effects and then the fader: check the whole path.",
             "Letting the master meter hit 0 dB while you mix. Keep it well below, so there is room for mastering.",
             "Changing several controls at once, then not knowing which one changed the sound. Change one thing at a time."],
   **{"try": dict(do="Play a song and follow its sound with your eyes: from one track's input, through its effects, to its fader, then the master. Mute that track's effects one at a time.",
                  success="You can say the order the sound travels in, and which effect changed the sound each time you switched it off.")},
   quiz=[dict(q="In what order does sound pass through a track?", options=["Fader, then effects, then input", "Input, then effects, then fader, then master", "Master, then fader, then input"], answer=1,
              why="Sound comes in, passes the effects left to right, goes through the fader, and ends at the master."),
         dict(q="Why keep peaks well under 0 dB?", options=["So nothing distorts", "So the song sounds quiet", "So the meter looks neat"], answer=0,
              why="0 dB is the top of the digital scale. Going over it distorts, so leaving room protects the sound."),
         dict(q="What is a sensible way to learn what a control does?", options=["Change several at once", "Change one thing and listen before and after", "Read about it and never touch it"], answer=1,
              why="One change at a time lets your ears connect the control to the sound.")],
   more=["step:gain", "step:dig-clipping-headroom", "step:daw"]),
}
