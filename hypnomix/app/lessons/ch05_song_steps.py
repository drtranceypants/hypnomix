"""Chapter 'The song before you record': tempo and key, sections, arrangement, MIDI, drum programming, quantise, loops."""
from hypnomix.app.lessons._common import ALL, LR

STEPS = [
 dict(id="song-tempo-key", title="Tempo, time signature and key", daws=ALL,
      say=["Three facts hold a song together: how fast it goes, how the beats are counted, and which notes it lives on. "
           "Settle them before you record, because every part you add is played against them.",
           "**Tempo** is the speed, in beats per minute (**BPM**). To find it, tap your foot to the song for a few bars and "
           "let a **tap tempo** button average your taps: you tap, it shows the number. The **time signature** says how "
           "the beats are grouped. In 4/4 you count 1-2-3-4, the beat of most pop, rock and country. In 3/4 you count "
           "1-2-3, a waltz. In 6/8 there are six short beats in a bar, felt as two big swings of three, a rolling, "
           "lilting feel.",
           "The **key** is the home note of the song and the set of notes it mostly uses. A **major** key tends to sound "
           "bright and settled; a **minor** key tends to sound darker or sadder. To find a key by ear, hum or play "
           "notes until one feels like 'home', the note the song wants to end on. Or let a tool propose: "
           "`hypnomix key -h` says it finds a song's key (the tonic and major or minor) with a confidence, and when it is "
           "not sure it says so and lists candidates, so you decide.",
           "Settle the key before you record vocals. Sing a part in one key, change the key later, and the singer has to "
           "start again. It is much easier to move a programmed instrument than a voice."],
      terms=[["BPM", "beats per minute: how many beats fit into one minute. 60 BPM is one per second."],
             ["Tap tempo", "a button you tap in time with the music; the program works out the tempo from your taps."],
             ["Time signature", "how beats are grouped into a bar, written like 4/4, 3/4 or 6/8."],
             ["Bar (measure)", "one group of beats, counted 1-2-3-4 in 4/4. Bar lines divide the song into bars."],
             ["Key", "the home note of a song and the family of notes it mostly uses, such as C major or A minor."],
             ["Major", "a scale whose chords tend to sound bright and settled."],
             ["Minor", "a scale whose chords tend to sound darker or sadder."],
             ["Scale", "a set of notes in order that a song draws its melody and chords from."]],
      how={"live": ["Click the tempo field at the top left and type the BPM, or click **TAP** in time with your foot.",
                    "The time signature fields sit just to the right of the tempo field: set the top number and the bottom number."],
           "reaper": ["Double-click the tempo number in the transport bar and type the BPM, or click the **BPM** button in the transport in time with the music to tap the tempo.",
                      "For a time signature other than 4/4, add a tempo/time signature marker on the ruler (Insert menu) and set the signature there."],
           "ardour": ["Double-click the tempo marker at the start of the Tempo ruler to set the BPM; the meter marker beside it sets the time signature."]},
      settings=[["Tempo (BPM)", "70-90 slow, 90-120 medium, 120-140 upbeat", "a rough guide only; the song's own feel decides"],
                ["Taps for tap tempo", "8 or more taps, steady", "the first few taps are rough; later ones average out"],
                ["Time signature", "4/4 unless the song counts differently", "most popular music is in four; use 3/4 or 6/8 only if the song truly swings in threes"],
                ["Key for a singer", "check the highest and lowest notes in a comfortable run", "a key that suits the voice sounds easy; one that strains will not"]],
      listen="Play the song and tap along. If your taps keep drifting early or late you have the wrong tempo, or half or double the real one. "
             "Hum the home note: if it sounds finished, you have the key.",
      mistakes=["Taking half or double the real tempo (70 instead of 140): if it feels busy at one number, try half; if it feels dragging, try double.",
                "Leaving the time signature on 4/4 for a song in 3/4 or 6/8: the bar lines then fall in the wrong place and every later edit is harder.",
                "Choosing the key last, after the vocal is recorded: then the singer, not the song, decides what you can change.",
                "Trusting a key finder blindly: it proposes, you decide. Check it against your ear."],
      **{"try": dict(do="Choose a song you know. Tap its tempo on your DAW's tap button for 8 or more taps and write the BPM. Then hum the note it feels like it ends on, and find that note on a keyboard or a tuner.",
                     success="You have a BPM you can say aloud, a note you called home, and you can say whether the song feels major (bright) or minor (darker).")},
      quiz=[dict(q="A song is counted 1-2-3, 1-2-3 like a waltz. Which time signature is it?", options=["4/4", "3/4", "6/8"], answer=1,
                 why="3/4 has three beats in a bar. 4/4 has four, and 6/8 has six short beats felt as two groups of three."),
            dict(q="Which sound is a minor key most likely to give you?", options=["Darker, sadder", "Brighter, more settled", "Faster"], answer=0,
                 why="Major tends to sound bright and settled; minor tends to sound darker. It is a tendency, not a rule."),
            dict(q="Why settle the key before you record the vocals?", options=["It makes the vocal louder", "The singer would have to start again if the key changes later", "Keys cannot be changed on MIDI"], answer=1,
                 why="A recorded voice is hard to move to another key without losing its sound. Programmed parts can change at any time.")],
      more=["step:tempo", "hypnomix key", "tempo"]),

 dict(id="song-sections", title="Song sections and markers", daws=ALL,
      say=["Most songs are built from a few repeating blocks. The **intro** sets the scene. The **verse** tells the story, "
           "with new words each time. The **pre-chorus** is a short rise that leads into the **chorus**, the part that "
           "returns with the same words and the main hook. The **bridge** is a change of scene, usually once, "
           "late in the song. The **outro** ends it.",
           "Sections are counted in **bars**, and most are 4, 8 or 16 bars long. Counting in these lengths keeps the song "
           "predictable to a listener, who feels the change coming even without knowing why. A verse of 16 bars and a "
           "chorus of 8 is a common shape. A song does not have to use them all: many skip the pre-chorus or the bridge.",
           "Put **markers** (some DAWs call them **locators**) at the start of each section and name them: Verse 1, "
           "Chorus, Bridge. Then you can jump straight to the chorus to work on it, loop it, or copy it, instead of "
           "scrolling and guessing."],
      terms=[["Intro", "the opening section, before the first verse."],
             ["Verse", "a section that tells the story; the words change each time it returns."],
             ["Pre-chorus", "a short section that builds toward the chorus."],
             ["Chorus", "the main, returning section with the hook, usually the biggest part of the song."],
             ["Bridge", "a contrasting section, usually once, usually after the second chorus."],
             ["Outro", "the closing section."],
             ["Marker (locator)", "a named flag on the timeline that you can jump to."]],
      how={"live": ["Switch to **Arrangement View** (Tab).",
                    "Right-click the scrub area (the bar-number strip along the top of the arrangement) at the start of a section, or click the **Set** locator button at the left of that strip, to add a locator.",
                    "Right-click the new locator → **Rename**, type the section name, and press Return."],
           "reaper": ["Move the edit cursor to the start of a section and press **M** to add a marker (or Insert → Marker).",
                      "Double-click the marker in the ruler, type its name, and click OK."],
           "ardour": ["Window → Locations (Alt+L) opens the Locations window, where you can add and name markers.",
                      "You can also add a marker from the ruler's right-click menu at the playhead, and rename it by double-clicking it."]},
      settings=[["Intro", "2-8 bars", "long enough to set the groove, short enough to keep the listener"],
                ["Verse", "8 or 16 bars", "gives the story room"],
                ["Pre-chorus", "2-4 bars, or skip", "a short lift into the chorus"],
                ["Chorus", "8 bars", "short enough to stay a hook, long enough to sing along"],
                ["Bridge", "4-8 bars", "a short change of scene before the last chorus"]],
      listen="Play from one marker to the next. Each section should feel like one idea, and the jump into the next should feel like a change.",
      mistakes=["Placing markers by eye so they sit between bars: put each one on a bar line so loops and copies fit.",
                "Leaving the markers as 'Marker 1', 'Marker 2': name them right away, or you lose the point of having them.",
                "Making every section the same length: it sounds mechanical. Use 8 and 16, but let the song set the length."],
      **{"try": dict(do="Play a song you know and write down where each section starts, counted in bars. Then add and name a marker for each in your DAW, on the bar lines.",
                     success="Clicking a marker's name jumps to the start of that section, and you can say how many bars each one lasts.")},
      quiz=[dict(q="Which section usually comes back with the same words and the main hook?", options=["Verse", "Bridge", "Chorus"], answer=2,
                 why="The chorus repeats with the same words. Verses change their words, and the bridge is a one-off contrast."),
            dict(q="Why name your markers?", options=["So you can jump to a section and work on it", "So the song plays louder", "So the key is found automatically"], answer=0,
                 why="A named marker is a bookmark: jump, loop or copy that section without scrolling for it.")],
      more=["step:song-arrangement", "step:tempo"]),

 dict(id="song-arrangement", title="Arrangement: every part has a job", daws=ALL,
      say=["A busy song is not a good arrangement. In a good one each part has a job, and no part is there by "
           "accident. The **groove** (drums and bass) keeps the time. The **harmony** (guitar, keys, pads) fills in the "
           "chords. The **hook** (the vocal, a lead line) is the part people hum. If two parts do the same job by accident, one of "
           "them is probably not needed; a layer you add on purpose to make a part fuller is the exception.",
           "Leave **space**. Silence and sparse bars make the next loud bar feel loud. Think in **build and release**: "
           "strip a part away before the chorus, then let everything back in on the first beat. The chorus should feel "
           "bigger than the verse, and the way to do that is to add parts, an extra layer, a wider sound, a harmony "
           "vocal, and not only to turn the fader up.",
           "To find what you do not need, **mute** parts one at a time while the song plays. If you do not miss "
           "it, leave it out. Contrast between sections is what keeps a song moving: if the verse and chorus use the same "
           "parts at the same level, they sound the same. Less is more."],
      terms=[["Arrangement", "which parts play where in the song, and how they build and release."],
             ["Groove", "the drums and bass together: the rhythmic floor of the song."],
             ["Harmony", "the chords, played by guitar, keys, pads or strings."],
             ["Hook", "the catchy part people remember: a vocal line or a short instrumental riff."],
             ["Layer", "an extra part playing the same job to make it fuller."],
             ["Build and release", "adding parts to raise tension, then dropping them to let it go."]],
      settings=[["Parts in a verse", "3-5", "leaves room for the voice and the story"],
                ["Parts in a chorus", "one or two more than the verse", "the lift comes from what you add, not only the level"],
                ["Strip-out before the chorus", "1-2 beats to a bar of space", "makes the chorus land"],
                ["Mute test", "mute each part for one section", "if you do not miss it, it was not doing a job"]],
      listen="Play the verse, then the chorus, at the same volume. The chorus should still feel bigger: more parts, more width, more energy, with no change in level.",
      mistakes=["Adding more and more parts to fix a dull section: first mute things, then see what the song really needs.",
                "Making the chorus bigger only by raising its level: the lift should come from added parts, and it should still work at the same volume.",
                "Giving every part the busiest line all the time: parts should take turns, with one in front and the others under it."],
      **{"try": dict(do="Take a song you are working on or know well. Play one section and mute one part at a time. Write down the parts you do not miss.",
                     success="You have a list of at least one part that the section does not need, and you can name the job of each part that remains.")},
      quiz=[dict(q="Which of these is a good way to make a chorus feel bigger than a verse?", options=["Add parts and width, and drop parts just before it", "Only raise the volume", "Remove the vocal"], answer=0,
                 why="Added layers and a short strip-out before the chorus make it lift. Level alone just makes the song louder."),
            dict(q="What does the groove usually mean?", options=["The vocal melody", "The drums and bass together", "The reverb"], answer=1,
                 why="Drums and bass set the time and the rhythmic feel the rest of the song sits on."),
            dict(q="You mute a part and the song does not suffer. What does that suggest?", options=["Mute the track forever and try again later", "It may not be needed", "The mix is too quiet"], answer=1,
                 why="A part nobody misses is a candidate to leave out. A leaner arrangement is usually clearer.")],
      more=["step:song-sections", "step:drums"]),

 dict(id="song-midi", title="MIDI basics: notes, velocity and virtual instruments", daws=ALL,
      say=["**MIDI** is a set of instructions, not a recording of sound. Each note says which pitch, when it starts, "
           "how long it lasts and how hard it was played (its **velocity**). A **virtual instrument**, a piano or a drum "
           "kit or a synthesiser made of software, reads those instructions and makes the sound. A **controller** "
           "is a MIDI message for a moving value, such as a pedal press or a knob. A keyboard can send MIDI, or you can click the notes in.",
           "You see and edit the notes in a **piano roll**: a grid with pitch up the side and time along the bottom. "
           "Each note is a bar. Drag it up to change its pitch, drag its end to change its length, and drag it sideways to move it in time.",
           "That is why MIDI is easy to fix. A wrong note is one drag. A sound you do not like is changed by swapping the "
           "instrument, and the notes stay the same. The tempo can change without the pitch changing. Audio recorded "
           "from a microphone cannot do any of that so easily.",
           "You do not need to buy anything. Live has the **Drum Rack** and **Simpler**, and **Wavetable** if your edition has it. "
           "REAPER has **ReaSynth** and **ReaSamplOmatic5000**. Ardour has **ACE Fluid Synth**, which plays a free soundfont (a soundfont file) you download."],
      terms=[["MIDI", "a set of instructions (notes, timing, velocity) that tells an instrument what to play. It is not sound."],
             ["Note", "one instruction: a pitch that starts at a time and lasts a length."],
             ["Velocity", "how hard a note is played, from 1 to 127. Usually harder is louder and brighter."],
             ["Controller (CC)", "a MIDI message that moves a value over time, such as a sustain pedal or a mod wheel."],
             ["Virtual instrument", "software that turns MIDI notes into sound: a piano, a drum kit, a synth."],
             ["Piano roll", "the grid where you see and edit MIDI notes, pitch up the side and time along the bottom."],
             ["Soundfont", "a file of recorded instrument sounds that a synth such as ACE Fluid Synth can play."]],
      how={"live": ["Cmd+Shift+T (Ctrl+Shift+T) creates a new MIDI track.",
                    "In the Browser, open **Instruments** (or **Drums**) and drag an instrument onto the track.",
                    "Double-click in an empty clip slot (or draw in the Arrangement) to make a clip, then double-click it to open the piano roll."],
           "reaper": ["Insert → Virtual instrument on new track, and choose **ReaSynth** or **ReaSamplOmatic5000**.",
                      "Insert → New MIDI item on that track, then double-click it to open the piano roll."],
           "ardour": ["Track → Add Track, Bus or VCA…, and add a **MIDI** track with **ACE Fluid Synth** as its instrument.",
                      "In the synth's window, load a soundfont file you have downloaded.",
                      "Draw a region with the Draw tool and double-click it to open the piano roll."]},
      settings=[["Note length", "short for staccato, held for a pad", "the same note sounds very different short or long"],
                ["Velocity", "60-110 for most parts", "lets you shape loud and soft; 127 on everything sounds flat and fake"],
                ["Instrument for a first try", "a piano or a drum kit", "you hear at once whether the notes are right"]],
      listen="Play the same notes through two different instruments. The notes do not change, only the sound does.",
      mistakes=["Leaving every velocity the same: the part sounds like a machine. Vary them a little.",
                "Thinking the notes ARE the sound: with no instrument on the track you hear nothing.",
                "Drawing notes with no regard to the song's key: check the key you settled on first."],
      **{"try": dict(do="Make a MIDI track, add any virtual instrument, and draw four notes of a simple line. Play it, then change the instrument without touching the notes. Finally drag one note up a step.",
                     success="You heard the same four notes through two different sounds and changed a single note by dragging it.")},
      quiz=[dict(q="What is MIDI?", options=["A recording of sound", "Instructions about notes that an instrument turns into sound", "A kind of microphone"], answer=1,
                 why="MIDI carries note, timing and velocity. The virtual instrument makes the sound."),
            dict(q="What does velocity usually control?", options=["How long the note lasts", "How hard the note is played, so how loud and bright", "The song's tempo"], answer=1,
                 why="Velocity runs from 1 to 127 and shapes how loud, and often how bright, a note sounds."),
            dict(q="Why is a mistake in a MIDI part easier to fix than one in a recorded part?", options=["You can move the note, change the sound or change the tempo", "MIDI never has mistakes", "MIDI is always louder"], answer=0,
                 why="MIDI is editable data: each note can be moved, and the instrument or tempo can change afterward.")],
      more=["step:drums", "step:song-drum-programming"]),

 dict(id="song-drum-programming", title="Programming a drum part that breathes", daws=ALL,
      say=["A programmed drum part should sound like someone played it. Start from the usual grid in 4/4: the **kick** on "
           "beats 1 and 3, the **snare** on 2 and 4, and the **hi-hat** on every eighth note. That is the skeleton of "
           "most pop and rock.",
           "Then make it breathe. Vary the **velocity**: a hi-hat has a stronger hit on the beat and a softer one in between. Add "
           "a few very quiet **ghost notes** on the snare. Vary the **fills**, the short busy bars before a change, so each "
           "is a little different. Before a change, leave out the kick (or stop all the drums) for the last beat or two of the bar, so the first beat of the next section hits harder.",
           "Never copy and paste a single bar 16 times with nothing changed: the ear hears it. Change a note or two every "
           "few bars. The beat hypnomix writes in `step:drums` is built like this: kick, snare on 2 and 4, eighth-note hi-hats, with small differences in how hard each hit lands.",
           "Humanise with **velocity**, not by moving every note off the grid. Random timing shifts on everything sound sloppy, not human."],
      terms=[["Kick", "the bass drum: the low thump, usually on beats 1 and 3."],
             ["Snare", "the sharp crack, usually on beats 2 and 4, called the backbeat."],
             ["Hi-hat", "the small pair of cymbals that keeps a steady pulse, often in eighth notes."],
             ["Ghost note", "a very quiet extra hit, often on the snare, that adds feel without being heard as a beat."],
             ["Fill", "a short, busier bar of drums that leads into a new section."],
             ["Humanise", "make a programmed part feel played, by small differences in velocity and a little in timing."]],
      how={"live": ["Add a MIDI track with a **Drum Rack** or a Kit from the Browser's Drums.",
                    "Open the clip; each row is one drum. Click the notes in, then edit the velocity in the lane under the notes (the clip's Notes panel)."],
           "reaper": ["Add a drum instrument on a MIDI track, open the MIDI item, and draw the notes in the piano roll.",
                      "Change velocities in the velocity lane at the bottom of the MIDI editor."],
           "ardour": ["Add a MIDI track with a drum instrument, open the region, and draw notes in the piano roll.",
                      "Edit velocities by selecting notes in the piano roll (its velocity controls are in the MIDI editor)."]},
      settings=[["Kick", "beats 1 and 3, velocity 100-120", "the solid base of the groove"],
                ["Snare", "beats 2 and 4, velocity 100-120", "the backbeat that people clap on"],
                ["Hi-hat", "every eighth note, velocity 60-100, accents on the beat", "the accent pattern gives it life"],
                ["Ghost notes", "velocity 20-45", "heard as feel, not as notes"],
                ["Change every", "2-4 bars", "stops the loop sounding copy-and-pasted"]],
      listen="Play four bars. Close your eyes: does the hi-hat sound like a tick-tick machine, or does it lean on some beats? Compare it with a bar where every velocity is the same.",
      mistakes=["Setting all velocities to 100 or 127: it sounds like a typewriter. Use a range of at least 30 points on the hats.",
                "Copy-pasting one bar for the whole song: change something every few bars.",
                "Moving every note randomly off the grid to humanise it: change velocity first. The timing should stay tight on the kick and snare."],
      **{"try": dict(do="Program a two-bar loop: kick on 1 and 3, snare on 2 and 4, eighth-note hi-hats. Then change the hat velocities so the on-beat hits are louder, and add one very quiet snare ghost note.",
                     success="The same pattern now sounds played, not typed, and you can hear the difference when you set all the hat velocities back to the same value.")},
      quiz=[dict(q="Which is the usual starting point for a rock or pop drum part in 4/4?", options=["Snare on 1 and 3, kick on 2 and 4", "Kick on 1 and 3, snare on 2 and 4", "Kick and snare on every beat"], answer=1,
                 why="Kick on 1 and 3 with the snare backbeat on 2 and 4 is the standard skeleton."),
            dict(q="What is the best first way to make a programmed drum part sound human?", options=["Vary the velocities", "Move every note a random distance", "Raise the tempo"], answer=0,
                 why="Velocity differences give feel without destroying the timing. Random shifts on all notes sound sloppy."),
            dict(q="Why avoid copy-pasting one bar 16 times unchanged?", options=["It makes the song too loud", "The ear hears the repeat and the part feels lifeless", "It changes the key"], answer=1,
                 why="Tiny changes every few bars keep a part alive.")],
      more=["step:drums", "step:song-midi", "step:song-quantise"]),

 dict(id="song-quantise", title="Quantise, and why not to overdo it", daws=ALL,
      say=["**Quantise** snaps notes to a grid of beats, such as every eighth or sixteenth note. It is useful for programmed "
           "parts that you clicked in by hand, or a sloppy MIDI part that should sit on the beat.",
           "It is dangerous for a part someone played. A human is never exactly on the grid, and the small pushes and "
           "drags are the **feel**. Quantise at 100% and that feel is gone: the part is correct and lifeless. The imperfection is the performance.",
           "So go partway. Use a **strength** (also called amount) of about 50 to 75%: each note moves part of the "
           "way toward the grid, not all of it. Or leave the part alone and fix only the notes that are clearly off. **Swing** "
           "pushes every second note a little late, to give a shuffle: it is a feel, not an error.",
           "hypnomix's `tighten` works this way for a recorded take. Its help (`hypnomix tighten -h`) describes it as pulling a take's hits part of the way toward the click, in place, keeping "
           "the player's feel: it moves each hit by a share of its error (default half way), and leaves hits already close to their slot where they are. It writes a new set, so your original stays. hypnomix proposes, you decide."],
      terms=[["Quantise", "move notes onto a grid of beats."],
             ["Grid", "the evenly spaced beat positions notes can snap to: quarters, eighths, sixteenths."],
             ["Strength (amount)", "how far toward the grid each note moves: 100% is all the way, 50% is halfway."],
             ["Swing", "pushing every second note a little late, to give a shuffling feel."],
             ["Feel", "the small, human timing differences that make a part sound played."]],
      how={"live": ["Select the notes in a MIDI clip (or the clip), and use Edit → **Quantize** (Cmd+U / Ctrl+U) to snap them; Edit → **Quantize Settings** (Cmd+Shift+U / Ctrl+Shift+U) sets the grid and the amount.",
                    "Lower the **Amount** (for example 50%) to move the notes only part of the way."],
           "reaper": ["In the MIDI editor, select the notes and press **Q** to open the quantise dialog; choose the grid and set the **strength** below 100%."],
           "ardour": ["Right-click a MIDI region and look for its Quantize option; choose the grid and lower the strength, if the dialog offers one."]},
      settings=[["Strength", "50-75% for a played part", "keeps part of the feel while tightening the loosest hits"],
                ["Strength for a clicked-in part", "100%", "the notes were never played, so there is no feel to lose"],
                ["Grid", "eighths for a straight pop/rock part; sixteenths only if the part has sixteenth-note hits", "a grid finer than the part moves notes to the wrong place"],
                ["Swing", "start small and listen", "too much sounds like a different style"]],
      listen="A/B the original and the quantised part. Listen for the push and the lag: if the quantised version sounds stiffer or more mechanical, back off the strength.",
      mistakes=["Quantising a played performance at 100%: the feel goes. Use 50-75%, or fix single notes.",
                "Quantising to a grid finer or coarser than the part: notes land on the wrong slot. Match the grid to the shortest note.",
                "Quantising everything because 'it is the rule': tighten the parts that carry the pulse (kick, bass) and leave the others looser."],
      **{"try": dict(do="Play four bars of a simple part on a MIDI keyboard or tap them in by hand. Quantise a copy at 100%, another at 60%, and keep the original. Listen to all three.",
                     success="You can hear which version has the most feel, and you have chosen a strength you would use on a played part.")},
      hear=["timing-feel"],
      quiz=[dict(q="What does quantise do?", options=["Moves notes onto a grid of beats", "Changes the song's key", "Raises the volume"], answer=0,
                 why="It snaps notes to the nearest slot of the chosen grid, fully or by a chosen amount."),
            dict(q="You have a guitar part played by a person. What is the safest quantise approach?", options=["100% strength on everything", "50-75% strength, or fix only the clearly off notes", "Never listen after quantising"], answer=1,
                 why="Part strength keeps the feel while tightening the worst notes. 100% turns a performance into a grid."),
            dict(q="Which can you quantise at 100% with little loss?", options=["A drummer's played fills", "A part you clicked in by hand with the mouse", "A live vocal"], answer=1,
                 why="Notes you clicked in have no human timing to preserve.")],
      more=["hypnomix tighten", "step:song-drum-programming", "timing-tempo-motion"]),

 dict(id="song-loops-samples", title="Loops and samples, and checking you may use them", daws=ALL,
      say=["A **loop** is a short piece of audio or MIDI built to repeat: a drum groove, a bass line, a chord pattern. A "
           "**sample** is any recorded sound you reuse, from a single piano note to a whole phrase. A **one-shot** "
           "is a single sound that plays once, such as a kick, a clap or a vocal shout.",
           "To use a loop, match it to the song. Set the project to the loop's **tempo** (or let the DAW stretch it to "
           "match), and match its **key** if it has notes: a loop in the wrong key sounds wrong against your chords. Many "
           "free **royalty-free** loop packs and free sound libraries exist, with sounds made to be used in songs.",
           "Before you use a loop in a release, check its **licence**. Some free packs forbid commercial use, some "
           "need you to credit the maker, and some limit how you may share the files. Read the licence text that came with the "
           "pack and keep a copy. Never lift a recording by someone else from a song or a video without clearance: "
           "using it without permission can be infringement, even if it is only a second or two.",
           "This is not legal advice. For anything you are unsure about, ask a qualified person. The later lesson `step:rel-copyright` covers it in more detail."],
      terms=[["Loop", "a short piece of audio or MIDI made to repeat."],
             ["Sample", "a recorded sound you reuse in a new piece of music."],
             ["One-shot", "a single sound that plays once when triggered, such as a kick or a clap."],
             ["Royalty-free", "you do not pay each time it is used. It does not always mean 'free of any conditions'."],
             ["Licence", "the written rules for how you may use something."],
             ["Clearance", "permission, from the owners of a recording and its song, to use it."]],
      how={"live": ["Drag a loop file from the Browser into an audio track; in the clip, turn **Warp** on so it follows the project tempo.",
                    "Set the clip's pitch with the clip's **Transpose** (pitch) control in the Clip View if the key is off."],
           "reaper": ["Drag the loop file into the arrange view.",
                      "Right-click the item → Item properties, and use the options for playback rate and pitch if the tempo or key needs matching."],
           "ardour": ["Import the file (Session → Import), and use the region's options for stretching and pitch shifting to match the project, if you need them."]},
      settings=[["Tempo match", "within a few BPM of the song, or stretched to match", "a big stretch makes the sound smeared"],
                ["Key match", "transpose by up to a few semitones", "a large pitch shift changes the character of the sound"],
                ["Licence check", "before the release, not after", "fixing it later can mean replacing a part"]],
      listen="Play the loop against your chords. If a note sounds sour against the chord, the loop is in the wrong key, or has not been matched.",
      mistakes=["Assuming 'free to download' means 'free to release': read the licence for commercial use and credit.",
                "Using a snippet of someone else's song because it is short: length does not make it safe.",
                "Dropping in a loop without matching key and tempo: it fights the rest of the song."],
      **{"try": dict(do="Find a free loop or one-shot pack. Find its licence text. Write down three things: may it be used commercially, does it need credit, and may you share the files. Then drop one loop into a project and match its tempo.",
                     success="You have a short note of the licence terms, and a loop playing at your song's tempo.")},
      quiz=[dict(q="A free loop pack says 'personal use only'. Can you put the loop in a song you sell?", options=["Yes, it was free", "No, check the licence: this wording forbids commercial use", "Yes, if it is under 10 seconds"], answer=1,
                 why="'Personal use only' normally rules out commercial release. Read and follow the pack's licence."),
            dict(q="What is a one-shot?", options=["A single sound that plays once, like a kick", "A loop that repeats once", "A song with one chord"], answer=0,
                 why="A one-shot is not made to repeat, unlike a loop."),
            dict(q="You like a two-second piece of another artist's recording. What should you do?", options=["Use it, it is short", "Get clearance, or use something else", "Pitch it up so no one notices"], answer=1,
                 why="Use of someone else's recording needs permission, whatever its length. This is not legal advice: ask a qualified person.")],
      more=["step:rel-copyright", "step:song-tempo-key"]),
]

ENRICH = {}
