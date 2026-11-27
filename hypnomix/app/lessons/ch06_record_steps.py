"""Your first recording: the extra steps (monitoring to keeping takes) and teaching fields for the existing steps."""
from hypnomix.app.lessons._common import ALL, LR

STEPS = [
 dict(id="rec-monitoring", title="Monitoring and latency", daws=ALL,
      say=["While you record, you need to hear yourself. There are two ways. With **direct monitoring** your interface sends "
           "what comes in straight back to your headphones, inside the box, with no delay. With **software monitoring** the "
           "sound travels into the computer, through the DAW, and back out, so it arrives a little late.",
           "That lateness is **latency**, and it depends on the **buffer size** you set for the audio driver. A big buffer is "
           "safe for the computer but late for you; a small one is quick but asks more of the computer. Singing against your own "
           "voice a few hundredths of a second late is off-putting, and players start to rush or drag to compensate. "
           "Aim for a round trip of roughly 10 ms or less, and lower the buffer while you record (you can raise it again for mixing).",
           "Use one path or the other, not both. If you hear a doubled, slightly echoing voice, you are hearing the interface "
           "and the DAW at once: turn one of them off."],
      terms=[["Latency", "the delay between a sound going in and coming back out of your headphones. Smaller is better while recording."],
             ["Software monitoring", "you hear the input after it has gone through the DAW: you can hear effects, but with a small delay."]],
      settings=[["Buffer size while recording", "64 to 128 samples at 44.1 or 48 kHz", "small enough that the delay is hardly noticeable; raise it if the audio crackles"],
                ["Buffer size while mixing", "256 to 1024 samples", "latency no longer matters, and plug-ins run more safely"],
                ["Round trip", "about 10 ms or less", "beyond this most players feel the delay"]],
      how={"live": ["On the track, find the **Monitor** buttons in its I/O section: **In** always lets the input through, **Auto** lets it through while the track is armed, **Off** never does.",
                    "With the interface's own direct monitoring on, set the track to **Off** so you don't hear yourself twice. Otherwise use **Auto**.",
                    "To change the buffer: open Live's Preferences (called Settings in Live 12), go to Audio, and change the buffer size there."],
           "reaper": ["Click the speaker (monitor) icon next to the track's arm button to switch monitoring on and off. Right-clicking the arm button also lists the record monitoring choices.",
                      "With direct monitoring on the interface, leave the track's monitoring off so you don't hear yourself twice.",
                      "To change the buffer: Options → Preferences → Audio → Device."],
           "ardour": ["On the track's strip, use the input monitoring buttons (**In** and **Disk**) to choose whether you hear the live input or the recorded track.",
                      "With direct monitoring on the interface, set the track so the DAW's own input monitoring is off.",
                      "To change the buffer: Window → Audio/MIDI Setup."]},
      listen="Say a few words and clap into the mic with the headphones on. If you hear a short echo of yourself, your delay "
             "is too long or two monitoring paths are on. A single, immediate sound is what you want.",
      mistakes=["Direct monitoring on the interface and software monitoring in the DAW both on: you hear a doubled, phasey voice. Turn one off.",
                "Recording with a big buffer left over from mixing, then fighting the delay. Lower it before you arm.",
                "Raising the buffer to stop crackles and forgetting to say so when something sounds 'late': know which setting you changed."],
      **{"try": dict(do="Plug in your headphones, arm a track, and speak into the mic. Switch between your interface's direct monitoring and the DAW's monitoring, one at a time, and note which you prefer.",
                     success="You hear yourself clearly with no echo, and you know which of the two ways your setup uses.")},
      quiz=[dict(q="You hear your voice with a slight echo while recording. What is the likeliest cause?", options=["The microphone is too close", "Direct and software monitoring are both on", "The tempo is too slow"], answer=1,
                 why="The same voice reaches your ears twice, once straight from the interface and once, a little later, through the DAW. Turn one off."),
            dict(q="Which setting do you lower to make software monitoring feel quicker?", options=["The buffer size", "The track's fader", "The sample rate to 22 kHz"], answer=0,
                 why="A smaller buffer shortens the delay. If the audio starts to crackle, raise it a step.")],
      more=["step:dig-buffer-latency", "step:track", "step:gain"]),

 dict(id="rec-headphone-mix", title="The headphone mix", daws=ALL,
      say=["The performer hears only what you put in their headphones, and it decides how well they play and sing. A thin, "
           "harsh or too-quiet mix makes people force, go sharp or lose the beat. A good headphone mix makes them want to perform.",
           "Give them enough of **themselves**, enough of the **click or the track**, and a little reverb on the voice, so it "
           "sounds like a room rather than a head in a box. Keep the level comfortable, never loud: loud headphones leak into "
           "the mic and tire the ears. Use **closed-back** headphones for recording; open ones leak sound that the mic picks up.",
           "Many DAWs and interfaces can send a different mix to the performer than the one you hear in the speakers. That "
           "separate mix is the **cue mix** (or headphone mix). It lets you turn the vocal down in the room while the singer hears it clearly."],
      terms=[["Cue mix", "a separate mix sent to the performer's headphones, different from the one in your speakers."],
             ["Aux send", "a control on a track that sends a copy of it to another channel, with its own level: the usual way to build a cue mix."]],
      settings=[["The performer's own voice or instrument", "close to the level of the backing, just a little higher if they struggle to pitch", "if they can't hear themselves they push; too loud and they under-sing"],
                ["Click", "just loud enough to follow, no louder", "a click that is too loud tires the ears and bleeds into the mic"],
                ["Reverb on the voice", "a little, in the headphones only", "a touch of room feels better to sing into"],
                ["Overall headphone level", "comfortable and well below pain, never loud", "loud headphones leak into the mic and damage hearing"]],
      how={"live": ["Make a **return track** with the voice effects you want, and use the track's **Sends** to feed it.",
                    "The cue mix goes to the performer through a separate output pair (your interface's headphone output). Switch that pair on in Live's Preferences (called Settings in Live 12) → Audio → Output Config, then set the return track's **Audio To** to that pair."],
           "reaper": ["Add a track called Headphones (Ctrl+T / Cmd+T) and click its route button: untick **Master send** so it stays out of the main mix, and use **Add new hardware output** to send it to your interface's headphone outputs.",
                      "On each track the performer should hear, click its route button → **Add new send** → Headphones, and set each send's level: that is the performer's own balance. Add a send to your reverb track's return too if they want reverb.",
                      "Set those sends to **Pre-Fader (Post-FX)** in the send's mode menu, so your own fader moves don't change what the performer hears."],
           "ardour": ["Make a bus and send each track to it with an aux send, then route the bus to the headphone output of your interface."]},
      listen="Put the headphones on yourself and sing a line. Do you hear the beat, your own pitch and a bit of the track "
             "without having to strain? If you are leaning toward one part, turn it up.",
      mistakes=["Mixing for yourself, not the singer: the vocal turned down because it sounds good in the speakers, and the singer can't hear themselves.",
                "Too much reverb in the performer's ears, so they sing late. Use a short, quiet one.",
                "Open-back headphones that leak the click and the track into the vocal mic. Use closed-back."],
      **{"try": dict(do="Ask a friend to put on your headphones (or do it yourself) and set the click, the backing and the voice so you can sing along comfortably. Then add a very small touch of reverb to the voice.",
                     success="You can sing a whole verse without pushing, and the click is audible but not harsh.")},
      quiz=[dict(q="Why use closed-back headphones to record?", options=["They sound brighter", "They are always cheaper", "They stop the track leaking into the microphone"], answer=2,
                 why="Open-back headphones let sound out. A mic near the performer picks up that leak, and you cannot remove it later."),
            dict(q="The singer says they can't hear themselves. What should you do first?", options=["Turn the whole track up", "Turn their own voice up in their headphone mix", "Move the mic closer"], answer=1,
                 why="The cue mix is theirs alone: raise the voice there, and the room mix can stay as it is.")],
      more=["step:rec-monitoring", "step:click"]),

 dict(id="rec-tune-up", title="Tune up first", daws=ALL,
      say=["Tune every guitar and bass at the start of each session, and again between takes. Strings drift as the room warms "
           "and as you play, and a string that was in tune ten minutes ago may not be now.",
           "This matters more than almost anything, because a pitch problem is hard to fix later. A guitar that is slightly flat "
           "can be nudged by software, but only so far, and it sounds odd. An interval that is 30 **cents** out sounds sour, "
           "and several instruments each a little out together make the whole song uneasy.",
           "Use a **tuner**, not the ear alone. Your DAW has a tuner of its own (see below), or a tuner app will do. Tune "
           "from below the note up to it, so the string settles. **Intonation** is whether the instrument plays in tune "
           "up the neck, not only on open strings: check a note at the 12th fret against the open string, and have a "
           "technician set the instrument if it is far off."],
      terms=[["Tuner", "a device or plug-in that shows which note you're playing and how far above or below it you are."],
             ["Cent", "one hundredth of a semitone. 100 cents make a semitone."],
             ["Intonation", "whether an instrument plays in tune along its whole range, not only on the open strings."]],
      settings=[["Reference pitch", "A = 440 Hz", "the standard unless the whole band has agreed on another"],
                ["How close to be", "within about 5 cents on every string", "a few cents is hard to hear; about 30 cents sounds sour"],
                ["Re-tune", "at the start of each session and between takes", "strings drift as they warm, and bends move them"]],
      how={"live": ["Audio Effects → **Tuner**: drag it onto the guitar track (if your edition has it), arm the track, and play one string at a time."],
           "reaper": ["Click the track's **FX** button → Cockos → **ReaTune**, and play one string at a time."],
           "ardour": ["Add a tuner plug-in to the strip if you have one, or use a tuner app or clip-on tuner, and play one string at a time."]},
      listen="Tune one string, then play two strings together as a chord or a fifth. A tuner can say 'in tune' and the "
             "pair can still beat or sound sour; listen as well as looking.",
      mistakes=["Tuning once at the start and never again: guitars drift within a song or two. Tune between takes.",
                "Tuning to the ear in a noisy room. Use a tuner, and mute the strings you're not tuning.",
                "Trusting open-string tuning and ignoring that the guitar plays out of tune at the 12th fret: check the intonation."],
      **{"try": dict(do="Tune your guitar or bass, play for ten minutes, then check it again. Notice which strings moved.",
                     success="You can see which strings drift, and you know that re-tuning is a habit, not a fix.")},
      quiz=[dict(q="About how far out does an interval start to sound sour?", options=["1 cent", "A whole semitone, 100 cents", "Around 30 cents"], answer=2,
                 why="Singers and players start to hear it at somewhere around 20 to 30 cents. A semitone is far too much, it is a different note."),
            dict(q="When should you check the tuning of your guitar?", options=["Once, when you buy it", "At the start of each session and between takes", "Only when it sounds bad"], answer=1,
                 why="Strings drift with temperature and playing. A quick check between takes avoids unfixable pitch problems.")],
      hear=["interval-tune"],
      more=["step:rec-guitar-bass", "step:rec-voice"]),

 dict(id="rec-voice", title="Recording a voice well", daws=ALL,
      say=["A voice recorded well needs far less repair. Most of what makes it good is how you stand and sing, not what you buy.",
           "Keep the **distance and angle** the same for every take: about a hand's width from the mic, with a pop filter between "
           "your mouth and the mic, and the mic a little above or to the side so the 'p' and 'b' breaths miss the capsule. "
           "Moving closer makes you boomier; moving away makes you roomier. If you need to sing louder, step back a little "
           "rather than turning your head away. Stay in the same spot all session.",
           "**Warm up** for ten minutes or so with easy humming and scales. Sip **room-temperature water**; don't strain or force. "
           "Read the lyric as if you were telling it to someone, and sing it to a person, not to a microphone: the emotion shows up "
           "in the sound. **Track in sections** (a verse, then a chorus), and record several whole takes, with a break between. "
           "Leave a little breathing room before each line, and don't chop the ends of words.",
           "Watch the level: it should peak around -12 to -6 dBFS on your loudest line, and your singing should stay "
           "consistent from take to take so the takes join together well."],
      settings=[["Peaks at your loudest line", "-12 to -6 dBFS", "room for a louder take; never touching 0"],
                ["Distance from the mic", "about a hand's width (10 to 20 cm), kept the same", "closer is boomier, further is roomier; changing it between takes makes takes hard to join"],
                ["Takes per section", "three to five", "enough to choose from without tiring the voice"],
                ["Warm-up", "about ten minutes, easy and quiet", "a cold voice strains; a warm one is steadier"]],
      how={"live": ["Arm the track, set the interface's gain while you sing the loudest line, and record whole takes in the Arrangement."],
           "reaper": ["Arm the track, set the interface's gain while you sing the loudest line, and record whole takes."],
           "ardour": ["Arm the track, set the interface's gain while you sing the loudest line, and record whole takes."]},
      listen="Play the take back and listen to the first word of each line and the ends of words. Are they all there? Is the "
             "voice at the same distance throughout? Does it sound like someone telling you something?",
      mistakes=["Moving around the room or turning the head between takes: the takes then sound like different singers. Mark the spot with tape.",
                "Singing until the voice is tired before recording. Warm up, record, then rest.",
                "Singing to the microphone, not to anyone. Pick a person and sing to them.",
                "Setting the gain on the quiet verse. Set it on the loudest line, and leave room."],
      **{"try": dict(do="Record the same line three times: once at your normal distance, once much closer, once much further. Listen to all three without changing the gain.",
                     success="You can hear how distance changes the tone and the level, and you know why you stay in one spot.")},
      quiz=[dict(q="Why keep the same distance from the mic on every take?", options=["So the takes match in tone and level when you join them", "Because the mic breaks if you move", "It makes the voice louder"], answer=0,
                 why="Distance changes tone and level. Takes recorded at the same distance can be mixed together without sounding like different singers."),
            dict(q="What is a good drink while recording vocals?", options=["Cold water straight from the fridge", "Sip room-temperature water", "Fizzy water, in gulps"], answer=1,
                 why="Room-temperature water is gentle on the voice. Don't push or strain; if it hurts, stop.")],
      more=["step:gain", "step:rec-doubling", "vocal-production"]),

 dict(id="rec-guitar-bass", title="Recording guitar and bass: DI and amp", daws=ALL,
      say=["There are two ways to record an electric guitar or bass. A **DI** (direct input) takes the clean signal from the "
           "instrument, through an instrument input or a DI box. A **mic'd amp** places a microphone in front of the amp's speaker and "
           "records the sound the room and the amp make together.",
           "The DI is clean and flexible: you can run it through an amp plug-in, a different amp sound or a different tone after the "
           "fact (**re-amping**), and the performance is safe whatever you decide later. The mic'd amp gives the real sound "
           "of the speaker, the room and the amp's own character. Many engineers record **both at once**, on two tracks, "
           "and choose or blend later. For bass, DI plus amp is a classic: the DI for the low end, the amp for the grit.",
           "No amp? An **amp-style plug-in** in your DAW is a fine way to hear a guitar sound while you record. Record the "
           "DI clean, with the plug-in on only for monitoring, so you can change the sound later. Start with fresh strings, "
           "and watch out for hum: single-coil pickups pick up noise from screens and lights, so turn the guitar away from the "
           "monitor, or move until the hum drops."],
      terms=[["Re-amping", "playing a recorded clean signal back through an amplifier (or amp plug-in) to change the sound after recording."],
             ["Single-coil pickup", "a guitar pickup with one coil. It sounds bright and clear and picks up hum from screens and lights."]],
      settings=[["Peaks (DI or mic)", "-12 to -6 dBFS", "room for the loudest strum; guitars have fast peaks"],
                ["Mic on the amp", "a few centimetres from the speaker, about on the cone's edge", "closer is tighter and brighter; further adds room"],
                ["Bass tracks", "a DI and an amp mic, kept as two tracks", "blend them later; check they line up in time and polarity"],
                ["Strings", "fresh, stretched in", "old strings sound dull and drift out of tune"]],
      how={"live": ["For a DI: plug into the interface's instrument input, arm an audio track, and set the gain.",
                    "For both: arm two audio tracks on two inputs (the DI and the amp mic), and record them together.",
                    "To hear an amp sound while recording a clean DI: add an amp-style device to a second track that listens to the same input, or use the stock **Overdrive** or **Saturator** for a rough idea."],
           "reaper": ["For a DI: plug into the interface's instrument (Hi-Z) input, add a track, arm it, choose that input (right-click the record button), and set the gain.",
                      "For both: arm two tracks on two inputs (the DI and the amp mic) and record together.",
                      "To hear an amp sound while recording a clean DI, add an amp-style plug-in to the track's monitoring effects (FX chain), or to a second track that listens to the same input."],
           "ardour": ["For both: arm two tracks on two inputs and record together.",
                      "To hear an amp sound, add an amp-style plug-in to the track, and record the clean signal on a separate track or with the plug-in after the recording point."]},
      listen="With the DI and the amp mic on separate tracks, play them one at a time and then together. If the "
             "together version sounds thinner than either, the two are fighting: flip the polarity of one, or nudge it in time.",
      mistakes=["Recording only the amp-plug-in sound and not a clean DI, then wanting a different tone. Record the DI too.",
                "Playing with the guitar facing the screen and getting hum. Turn away and listen.",
                "Putting the amp mic on the loudest point and not listening: a few centimetres sideways changes the tone a lot. Move it while the amp plays.",
                "Old strings. Change them before the session."],
      **{"try": dict(do="Record the same riff twice: once clean through the instrument input, once through an amp-style plug-in. Switch the plug-in on and off on the clean take afterward.",
                     success="You can hear the DI take with any amp sound you like on top, and you know why the clean one is worth keeping.")},
      quiz=[dict(q="What is the main advantage of recording a clean DI as well as the amp?", options=["It is louder", "You can change the amp sound later", "It removes hum"], answer=1,
                 why="A clean DI can be run through any amp or plug-in later (re-amping), so the performance survives a change of mind about the tone."),
            dict(q="You hear a buzz that changes when you turn on the guitar. What is likely?", options=["Hum from a screen or light picked up by single-coil pickups", "The tempo is wrong", "The buffer is too small"], answer=0,
                 why="Single-coil pickups pick up electrical noise. Move away from screens and lights, and the hum drops.")],
      more=["step:gear-cables-levels", "step:gain"]),

 dict(id="rec-punch-loop", title="Punching in, loop recording and takes", daws=ALL,
      say=["Two tools let you record just the part you need. **Punching in** starts recording at a place you choose, over an "
           "existing take, and **punching out** stops it: you fix one phrase without redoing the whole song. **Loop recording** "
           "repeats a section, and each pass becomes a new take, so you can try one phrase several times in a row.",
           "Both give you more choice, so use it. When you record again over something you already have, **don't erase "
           "the old take**. Modern DAWs keep every pass as a take lane or a layer. You can listen to them all, compare and "
           "pick the best bits, which is **comping**.",
           "Give yourself a bar or two before the part (a pre-roll) so you can feel the song again before you come in, and "
           "listen back to each pass before you decide."],
      terms=[["Punch out", "stop recording at a place you choose, after a punch in."],
             ["Loop recording", "recording while a section repeats, so each pass makes a new take."],
             ["Take lane", "a row under the track that shows each take, so you can compare them and choose between them."],
             ["Pre-roll", "playing the song for a bar or two before the punch in, so you feel the music before you record."]],
      how={"live": ["In the Arrangement, set the loop brace around the part and switch Loop on, then record: Live keeps each pass as a take lane (right-click the track → Show Take Lanes).",
                    "For a punch: use the **Punch-In** and **Punch-Out** switches next to the loop switch, with the loop brace around the part you want to fix."],
           "reaper": ["Set a loop or time selection around the part you want to fix.",
                      "Right-click the record button in the transport and choose time selection auto-punch, then record: REAPER only records inside the selection.",
                      "Each pass becomes a take: press T to cycle, or right-click → Take → Show all takes in lanes."],
           "ardour": ["Set the punch range around the part and switch on **Punch In** and **Punch Out**, then record: HypnoMix Studio records only inside the range.",
                      "Each pass is a new region on a layer above the last; the track's context menu has the Layers options to show them."]},
      listen="Play the punched phrase against the take before and after it. A good punch is invisible: same tone, same "
             "level, no click where it joins. If you hear the join, redo it with a little more of the previous phrase.",
      mistakes=["Deleting a take because it wasn't good enough. Keep it: part of it may be best.",
                "Punching in at the exact start of a word: leave a little before it, so the first consonant isn't clipped.",
                "Changing the gain or the mic position between the first take and the punch: the join then sounds different."],
      **{"try": dict(do="Record a four-bar phrase. Then punch in over just the last two bars, or loop those bars and record three passes.",
                     success="You have several takes of the same bars on separate lanes or layers, and the earlier ones are still there.")},
      quiz=[dict(q="What is a punch in?", options=["Recording over just a section of an existing take", "Making the take louder", "Deleting the previous take"], answer=0,
                 why="You start recording at a chosen point and stop at another, so you replace only that part."),
            dict(q="Why use take lanes (layers) instead of recording over the old take?", options=["It saves disk space", "Every pass stays available, so you can pick the best bits", "It is easier to arm the track"], answer=1,
                 why="Comping needs the choice. Once a good take is gone, it is gone.")],
      more=["step:take", "step:rec-good-enough"]),

 dict(id="rec-doubling", title="Doubling a part", daws=ALL,
      say=["A **double** is a second performance of the same part, recorded separately and played with the first. Two takes "
           "are never exactly the same: small differences in timing and tone make the sound thicker and wider than one "
           "take or a copy. It is a classic way to make a chorus bigger.",
           "Keep the double similar to the lead, not identical: same words, same notes, but really played again. Pan the two a "
           "little apart, or one of them wide, and set the double lower in level than the lead so the lead still stands "
           "out. A **harmony** is different: it sings other notes, usually a third or a fifth above or below.",
           "Doubles and harmonies are as good as their timing: words that start together sound like one big voice; words "
           "that don't sound sloppy. `hypnomix vocalign` lines the words of your doubles and harmonies up to the lead's, "
           "without touching the pitch. With two or more overdubs it works gently by default: words that are not clearly "
           "off move only a very little toward the group, and only the words that are further off are fixed. "
           "That keeps a little human looseness. It writes new files and never changes your originals."],
      terms=[["Double", "a second recording of the same part, played again, mixed with the first to thicken it."],
             ["Harmony", "a part that sings different notes from the lead, usually a third or a fifth above or below."],
             ["Stack", "all the layers of a part together: the lead, the doubles and the harmonies."]],
      settings=[["Double level under the lead", "about 3 to 6 dB lower", "the lead stays in front; the double thickens it"],
                ["Panning", "a little left and right, or one wide", "separates the two so they sound like two voices, not a louder one"],
                ["Harmonies", "about 1.5 dB lower than the part they sit under", "harmonies colour the melody; they should not cover it"]],
      how={"live": ["Make a second audio track, record the same part again, and pan it with the track's Pan control.",
                    "For tighter timing: `hypnomix alignset` (in a Live set) writes the timing as warp markers on the clips."],
           "reaper": ["Make a second track, record the same part again, and pan it with the track's pan knob.",
                      "For tighter timing: `hypnomix alignset` (in a REAPER project) writes the timing as stretch markers on the clips."],
           "ardour": ["Make a second track, record the same part again, and pan it with the strip's pan control.",
                      "For tighter timing, export the parts from the same bar and use `hypnomix vocalign`."]},
      listen="Switch the double on and off while the chorus plays. The chorus should get fuller and wider, and the lead "
             "should still be clear. If the double makes the words muddy, the timing is probably loose.",
      mistakes=["Copying the lead and calling it a double: a copy only gets louder, it doesn't thicken. Record a real second take.",
                "A double as loud as the lead, so the lead disappears into it. Lower the double.",
                "Pulling every word to the lead's timing exactly until it sounds robotic. Keep a little looseness."],
      **{"try": dict(do="Record a chorus line, then record it again as a double. Pan them slightly apart and set the double a few dB lower.",
                     success="The line sounds fuller, with the lead clear in front and the double behind it.")},
      quiz=[dict(q="What makes a double different from a copy of the take?", options=["It is played again, so the timing and tone vary a little", "It is louder", "It has a different key"], answer=0,
                 why="The natural small differences between two takes are what thicken the sound. A copy has none."),
            dict(q="Where should a double usually sit in level, compared with the lead?", options=["Louder than the lead", "Exactly the same", "A little lower than the lead"], answer=2,
                 why="The lead must stay in front. The double supports it and adds width.")],
      more=["hypnomix vocalign", "vocal-alignment", "vocal-production"]),

 dict(id="rec-good-enough", title="When a take is good enough, and keeping your takes", daws=ALL,
      say=["A take is good enough when it **feels** right, not when it is perfect. Songs are heard as a whole, and "
           "a slightly rough note with the right emotion beats a flawless one that feels cold. Before you redo a line, ask: "
           "**would I notice this in the song?** If you only hear it when you listen for it, leave it.",
           "Stop when a take has the right emotion. Singers and players get worse as they tire or try too hard. A mistake that "
           "gives the part character (a cracked note, a breath, a slide) may be the best thing in the song. Keep it.",
           "**Name your takes** as you go (Vox_V1_T3: vocal, verse 1, take 3), and **keep every take** until the song is "
           "finished, because the part you rejected on Tuesday may be the one you need on Friday. When you have several "
           "takes, `hypnomix takes` ranks them for you on clipping, noise, pitch and timing, and gives a comp list for each section. "
           "It proposes and you decide: it measures what can be measured, and only your ears can judge feeling."],
      terms=[["Comp list", "a list of which take to use for each section when building one best performance."],
             ["Take naming", "a short label on each take (such as Vox_V1_T3) so you can find it later."]],
      how={"live": ["Rename each take clip (select it and press Cmd+R / Ctrl+R) and keep unused takes in the take lanes."],
           "reaper": ["Right-click the item → Item properties and type a name in the take name box; keep unused takes in the item."],
           "ardour": ["Double-click a region's name to rename it, and keep older layers until the song is done."]},
      listen="Play your favourite take and the one `hypnomix takes` ranked best. If they differ, listen to both again without "
             "looking at the screen. Trust what you feel, and use the ranking as a second opinion.",
      mistakes=["Chasing a perfect take until the voice is tired. Stop at the first one that feels right and has no distracting fault.",
                "Deleting the 'bad' takes to save space. Keep them until the song is finished.",
                "Letting the ranking decide for you. The tool measures clipping, noise, pitch and timing; it can't hear feeling."],
      **{"try": dict(do="Take your three takes of one line. Name them, listen to each with your eyes shut, and choose one by feel. Then see which one `hypnomix takes` would have ranked first.",
                     success="You have chosen by ear first, and you know whether the numbers agree.")},
      quiz=[dict(q="What is a good test for a small mistake in a take?", options=["Delete the take at once", "Always redo it until it is perfect", "Ask whether you would notice it in the finished song"], answer=2,
                 why="Listeners hear the whole song, not the flaw you know about. If it doesn't stand out in context, the feeling matters more."),
            dict(q="What does `hypnomix takes` do?", options=["Records new takes for you", "Ranks your takes on clipping, noise, pitch and timing and suggests a comp list", "Deletes the worst takes"], answer=1,
                 why="It scores each take on what an engineer listens for and writes a suggestion. You decide, and your originals are untouched.")],
      more=["hypnomix takes", "step:take", "step:takes-hypnomix"]),
]

ENRICH = {
 "tempo": dict(
     mistakes=["Guessing the tempo and then fighting the click: tap along to the song first and use the number it gives.",
               "Choosing a tempo that is comfortable for the drummer in your head, not the singer: sing the chorus at it before you record.",
               "Changing the tempo after recording: parts recorded to the old one will no longer line up with the bar lines."],
     **{"try": dict(do="Play or hum your song and tap the tempo box or the TAP button in time with it. Then play the click at that tempo.",
                    success="The click ticks in time with your foot, and you can sing the chorus at that speed without rushing or dragging.")},
     quiz=[dict(q="What does the tempo set?", options=["The speed of the click and the position of the bar lines", "The loudness of the song", "The key of the song"], answer=0,
                why="Tempo in BPM (beats per minute) decides how quickly the click ticks and where the bars fall."),
           dict(q="Why choose the tempo before you record?", options=["It is required by every DAW", "Changing it afterwards is awkward, because recorded parts keep their own timing", "It makes the recording louder"], answer=1,
                why="A recording does not speed up or slow down with the project unless you stretch it, which can change its sound.")],
     more=["step:click"]),
 "click": dict(
     mistakes=["Click in the room speakers: it ends up on the vocal mic. Send it to your headphones only.",
               "Playing *on top* of the click like a machine: lean into it, and let the feel breathe a little.",
               "No count-in, so the first bar is always rushed: set one or two bars."],
     **{"try": dict(do="Turn on the click and a 1-bar count-in, record eight bars of any simple part (clapping will do), then listen back.",
                    success="Your part sits near the click, a little ahead or behind in places, and the count-in gave you a clean start.")},
     quiz=[dict(q="What is a count-in?", options=["Bars of click before recording begins", "A counter that numbers each take", "A way to speed the song up"], answer=0,
                why="It gives you a bar or two to feel the tempo before you play."),
           dict(q="Where should the click be heard?", options=["In the room, loud", "In the headphones only", "Only in the final mix"], answer=1,
                why="A click in the room is picked up by the mic and stays on your recording.")],
     more=["step:rec-headphone-mix", "step:tempo"]),
 "drums": dict(
     mistakes=["A beat that is too busy to sing over: start simple, kick, snare and a steady hat.",
               "Treating the beat as final: it is a guide, and you can swap the kit later without re-recording.",
               "Leaving every hit at the same velocity: it sounds like a machine."],
     **{"try": dict(do="Add a four-bar beat, loop it, and play or sing along over it for a minute. Then change the kit or the velocity of one hit.",
                    success="You can follow the beat easily, and you've seen that a MIDI part changes without re-recording.")},
     quiz=[dict(q="What does a MIDI track hold?", options=["Recorded sound", "Only the tempo", "Notes that an instrument turns into sound"], answer=2,
                why="MIDI says which note, when and how hard; the instrument on the track makes the sound, so you can change it any time."),
           dict(q="What is velocity?", options=["How fast the song is", "How hard a note is played", "How long a note lasts"], answer=1,
                why="Velocity is the strength of a note, from 1 to 127. Small differences make a beat feel human.")],
     more=["step:click"]),
 "track": dict(
     mistakes=["Recording on the wrong input: the track records silence. Play something and check that its meter moves.",
               "Forgetting to arm: only armed tracks record. Check for the red light.",
               "Leaving two tracks armed: both record the same input. Arm only the one you need."],
     **{"try": dict(do="Make an audio track, name it, set its input to the socket your mic or guitar is on, arm it and make a noise.",
                    success="The track's meter moves when you play or sing, and you hear yourself once, not twice.")},
     quiz=[dict(q="Which tracks record when you press record?", options=["All tracks", "Only armed tracks", "Only the selected track"], answer=1,
                why="A track must be armed to take in a recording. This stops you from recording over something by accident."),
           dict(q="What does monitoring let you do?", options=["Hear the input while you play", "Make the file smaller", "Fix pitch"], answer=0,
                why="Monitoring plays the input through the track so you can hear yourself with the backing.")],
     more=["step:rec-monitoring", "step:gain"]),
 "gain": dict(
     mistakes=["Setting the gain while talking or singing softly, then recording the loud chorus: it clips. Set it on the loudest part.",
               "Turning the DAW's fader to change what is recorded: the fader does not change the recording. Use the interface knob.",
               "Recording hot to be safe: in 24-bit there is no need, and clipped peaks can't be repaired."],
     **{"try": dict(do="Arm the track, sing or play the loudest part of your song, and turn the interface's gain knob until the peaks sit around -12 to -6 dB.",
                    success="Peaks land in that range, and nothing reaches the red or touches 0.")},
     quiz=[dict(q="Why can't you fix a clipped recording later?", options=["The file is locked", "The DAW refuses to open it", "The peaks are cut off for good, and the lost shape can't be restored"], answer=2,
                why="Clipping flattens the top of the wave. That information is gone and can only be disguised, not restored."),
           dict(q="Where do you set the level for recording?", options=["On the interface's gain knob", "On the track's fader", "On the master fader"], answer=0,
                why="The interface's gain sets what is recorded. The DAW's faders only change what you hear afterwards.")],
     more=["step:gear-cables-levels", "step:rec-voice", "hypnomix soundcheck"]),
 "take": dict(
     mistakes=["Stopping at every small slip: keep going. The best parts of several takes can be joined later.",
               "Recording over a good take: use take lanes (layers) and keep them all.",
               "Not listening back before moving on: a take with a fault is easier to spot now than later."],
     **{"try": dict(do="Record two or three whole takes of one section. Stop each one only when the section ends, even if you make a slip.",
                    success="You have several takes of the same section, each one kept, and you can play any of them.")},
     quiz=[dict(q="What is comping?", options=["Putting a compressor on a take", "Building one best performance from the best parts of several takes", "Recording with a count-in"], answer=1,
                why="You choose the best phrases from several takes and join them into one."),
           dict(q="You slip on a word. What should you do?", options=["Stop and start over every time", "Keep going and record the whole take", "Delete the take"], answer=1,
                why="Whole takes keep the feel. You can fix a word later with a punch in or by comping.")],
     more=["step:rec-punch-loop", "step:rec-good-enough"]),
 "session-sketch": dict(
     mistakes=["Treating a loop as a finished part: record it into the Arrangement before you finish.",
               "Launching clips out of time because quantisation is off: leave it on, so they land on the bar.",
               "Recording over a good idea in a slot: use a new slot for each try."],
     **{"try": dict(do="Record a four-bar loop in one slot and a second idea in the next, then launch the two scenes in turn.",
                    success="Two ideas play in time, one after the other, and you've picked which to keep.")},
     quiz=[dict(q="What is a scene in Live?", options=["A single clip", "A row of clips launched together", "A kind of effect"], answer=1,
                why="A scene is a row across the tracks. Launching it starts every clip in the row."),
           dict(q="Why does launch quantisation matter?", options=["Clips start on the next bar and stay in time", "It makes clips louder", "It changes the key"], answer=0,
                why="Clips wait for the bar, so whenever you click, they stay in time with the rest.")],
     more=["step:take"]),
 "takes-hypnomix": dict(
     mistakes=["Fixing everything the first pass suggests at once: change one thing at a time and listen after each.",
               "Treating the report as a verdict: it is a list of proposals, and you decide.",
               "Running it before you've listened yourself: listen first, then compare with what it found."],
     **{"try": dict(do="Run the first pass on a few takes of one section and read what it suggests. Listen to one suggested fix before and after.",
                    success="You've heard one fix with and without, and you've decided yes or no yourself.")},
     quiz=[dict(q="What does HypnoMix do with your original recording?", options=["Overwrites it with the fix", "Deletes it after the fix", "Leaves it alone and writes new files"], answer=2,
                why="Its tools write new files and never change your originals. It proposes, you decide."),
           dict(q="What does the first pass check for?", options=["Which song to release", "Technical problems such as clicks, level jumps, drift, hum and hiss", "Whether the lyric is good"], answer=1,
                why="It looks for the technical faults that ears miss at first, and suggests a fix for each.")],
     more=["hypnomix takes", "first-pass", "step:rec-good-enough"]),
}
