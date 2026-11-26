"""Your room and your gear, part B: the room, quiet recording and starting mic positions."""
from hypnomix.app.lessons._common import ALL, LR

STEPS = [
 dict(id="gear-room", title="The room: reflections and cheap treatment", daws=ALL,
      say=["A microphone hears the room as well as the voice. Sound leaves the singer, hits the walls, floor and ceiling, "
           "and comes back a few milliseconds later. The mic records the direct sound and all those copies together. "
           "In a bare, small room that sounds boxy, hard or hollow, and no plug-in removes it cleanly afterwards.",
           "Three problems are common. **Flutter echo** is a fast buzzy ring between two parallel bare walls: clap and you hear it. "
           "**Comb filtering** is what happens when a reflection arrives just after the direct sound and the two partly cancel, "
           "which leaves a hollow, phasey tone. **Standing waves** pile up low notes in certain spots, especially in corners, "
           "so the room sounds boomy on some notes and thin on others.",
           "You can fix most of it cheaply. Soft, thick, uneven things soak up reflections: a sofa, curtains, a rug, a bookcase full of books, "
           "a duvet or moving blankets hung behind the singer. Thick absorbent panels (rockwool or similar, around 5 to 10 cm) work. "
           "Egg boxes and thin foam sheets mostly kill the highs and leave the boxy low mids alone. "
           "Put thicker absorbers (**bass traps**) in corners, where low notes build up.",
           "Before buying anything, find the best room you already have and put the mic in the right place. For a voice, a "
           "cupboard or a corner full of hanging clothes is often the best booth in the house. Mic placement and a quiet, "
           "soft room matter more than the price of the mic."],
      terms=[["Reflection", "sound that bounces off a wall, floor or ceiling and reaches the mic after the direct sound."],
             ["Flutter echo", "a quick buzzy ringing between two flat, parallel, hard walls. You hear it when you clap."],
             ["Comb filtering", "a hollow, phasey tone made when a sound and a slightly late copy of itself are added together."],
             ["Standing wave", "a low note that builds up between room surfaces, so some notes boom and others vanish depending on where you stand."],
             ["Absorber", "a soft, thick material that soaks sound up instead of bouncing it back."],
             ["Bass trap", "a thick absorber placed in a corner to calm low notes that build up there."]],
      settings=[["Absorber thickness", "5 to 10 cm of dense absorbent material, or a thick duvet", "thin material only takes the highs; low mids need depth"],
                ["Behind the singer", "a duvet or moving blanket on a stand or on the wall, with a small gap behind it if you can", "stops the reflection that goes back into the mic"],
                ["Corners", "the thickest absorbers or a pile of cushions and blankets", "low notes collect in corners"],
                ["Floor", "a rug or carpet under the mic and singer", "a hard floor gives a strong early reflection"]],
      listen="Record a few seconds of speech in the bare room, then again with a duvet behind you and a rug underneath. "
             "The second take sounds closer and drier, less hollow.",
      mistakes=["Covering the walls with egg boxes or thin foam sheets: they kill the highs but not the boxy tone. Use thick, dense material.",
                "Treating only one wall. Reflections come from everywhere, so soften the wall behind the singer and the one behind the mic first, then the corners.",
                "Moving the mic away to 'get more room' in a small room. In a small untreated room that only adds more boxiness: get closer and soften the room."],
      **{"try": dict(do="Do the blanket test. Stand where you will record, clap once and listen to the ring. Hang a duvet or put clothes around you, clap again, and compare. Then record a spoken sentence both ways.",
                     success="You can hear the ring shrink when the room gets softer, and the second recording sounds closer and less hollow.")},
      quiz=[dict(q="You clap in your room and hear a quick buzzy ring. What is that?", options=["Standing wave", "Flutter echo between hard parallel walls", "Preamp noise"], answer=1,
                 why="Flutter echo is a fast ring between flat, parallel, hard surfaces. Soft furnishings and absorbers break it up."),
            dict(q="Why are egg boxes a poor way to treat a room?", options=["They absorb mostly the highs and leave the low mids", "They are too heavy", "They add too much bass"], answer=0,
                 why="Thin, light material only takes the highest frequencies. Boxy and boomy tone needs thick, dense absorbers."),
            dict(q="What is the cheapest way to get a better vocal sound at home?", options=["Buy a more expensive mic", "Record in the softest room you have, close to the mic, with a duvet behind you", "Turn the gain up"], answer=1,
                 why="A soft room and good mic placement beat expensive gear. Fix the source before the mix.")],
      more=["step:gear-quiet", "step:gear-mic-voice"]),

 dict(id="gear-quiet", title="A quiet recording: noise sources, pop shield and the proximity effect", daws=ALL,
      say=["Every recording has a **noise floor**: the constant low hiss and hum under the music. Your job is to keep the sound you want "
           "well above it. The gap between the two is the **signal-to-noise ratio**. A bigger gap means a cleaner recording, and noise "
           "cannot be removed later without costing some of the sound you wanted.",
           "Start with the room. Computer fans, a fridge, the heating, traffic outside and a buzzing light all reach the mic. "
           "Switch off what you can, and move the computer or put it in another room. Listen on headphones with the mic live "
           "and no one playing: if you hear it there, it will be on the recording. Then get close to the sound. "
           "Halving the mic's distance makes the wanted sound about 6 dB louder against the room and the noise, so close recording cuts noise without touching a control.",
           "Voices make bursts of air on **P** and **B** sounds (plosives). A **pop shield** (a mesh disc) or a foam **windscreen** "
           "breaks the burst up before it hits the mic. Put a pop shield about a hand's width from the mic, "
           "with the singer a little behind it.",
           "Directional mics have a **proximity effect**: the closer you get, the more bass you hear. Used on purpose it adds warmth to a thin voice; "
           "too close it turns boomy. Last point: do not record quietly and turn it up later. The noise comes up with it."],
      terms=[["Noise floor", "the constant hiss and hum under a recording. Keep the wanted sound well above it."],
             ["Signal-to-noise ratio", "how far the sound you want sits above the noise. Bigger is cleaner."],
             ["Plosive", "a burst of air on P and B sounds that makes the mic thump."],
             ["Pop shield", "a mesh disc between singer and mic that breaks up plosive air blasts."],
             ["Windscreen", "a foam cover on the mic that softens air blasts and light wind."],
             ["Proximity effect", "the bass boost a directional mic gives as the sound source gets closer."]],
      settings=[["Pop shield distance", "a hand's width (about 8 to 10 cm) from the mic", "far enough to slow the air, close enough to be in the way"],
                ["Singer to pop shield", "another hand's width", "keeps the singer near the mic without hitting it"],
                ["Noise check", "listen on headphones with the mic live and nobody playing", "if you can hear it now, it is on the recording"],
                ["Recording peaks", "around -12 to -6 dBFS on the meter", "high enough above the noise floor, low enough to leave room for a surprise"]],
      listen="Turn off every noise source you can, record 10 seconds of 'silence', and listen to it with the volume up. "
             "Then compare the noise-floor demo: a loud recording against a quiet one turned up.",
      hear=["noise-floor"],
      mistakes=["Recording quietly 'to be safe' and turning it up later. The hiss rises with it. Record healthy peaks instead.",
                "Leaving the fridge, a fan or a computer running because you can't hear it. The mic does. Check on headphones.",
                "A pop shield pressed right against the mic. The air still reaches it. Give it a hand's width."],
      **{"try": dict(do="Record 10 seconds of silence with everything off, then again with the computer fan or the heating on. Record a sentence with lots of P and B words with and without a pop shield.",
                     success="You can hear which noise sources show up and how much of the P and B thump the shield removes.")},
      quiz=[dict(q="You record a vocal very quietly and boost it later. What happens to the noise?", options=["It stays the same", "It is boosted with the voice", "It disappears"], answer=1,
                 why="The noise floor was recorded with the voice, so lifting the level lifts both. Record healthy levels in the first place."),
            dict(q="What is the proximity effect?", options=["Plosives get louder", "A directional mic gives more bass as you get closer", "The mic hears more of the room"], answer=1,
                 why="Directional mics boost low frequencies at short distances. Use it for warmth, or step back if it gets boomy."),
            dict(q="Where does a pop shield go?", options=["Touching the mic", "About a hand's width from the mic, between it and the singer", "Behind the singer"], answer=1,
                 why="It needs some distance from the mic so the air is slowed before it reaches the capsule.")],
      more=["step:gear-room", "step:gain"]),

 dict(id="gear-mic-voice", title="Starting mic positions: voice", daws=ALL,
      say=["Mic position is the first EQ on the track. A few centimetres change the tone more than a plug-in would. "
           "Every number below is a place to start. Move the mic, listen on headphones, then choose.",
           "With a **cardioid** condenser mic, start about 15 to 20 cm away, roughly a hand span, with a pop shield between you and the mic. "
           "Closer gives more bass and a more intimate, in-your-ear sound but more plosives and mouth noise. "
           "Further gives a thinner sound with more room in it.",
           "Aim the mic slightly **off axis**. Put it a little above the mouth, angled down, or just to one side. "
           "The air blasts from P and B sounds pass the capsule instead of hitting it, and sharp S sounds soften. "
           "Keep the singer's position steady: if the voice moves, the tone and level move too. "
           "On loud notes, lean back a little; on quiet lines, stay put.",
           "A **reflection filter** (a curved absorber behind the mic) helps in a bare room, and a closed-back headphone keeps the "
           "click and the backing track out of the mic. Make sure the singer can hear themselves comfortably."],
      terms=[["Cardioid", "a mic pattern that hears mostly in front, less at the sides, least behind."],
             ["Off axis", "not pointing straight at the sound source. It softens plosives and sibilance."],
             ["Reflection filter", "a curved absorber that sits behind the mic and catches room reflections."],
             ["Closed-back headphones", "headphones that seal around the ear so little sound leaks into the mic."]],
      settings=[["Mic distance", "15 to 20 cm (a hand span)", "close enough to beat the room, far enough to avoid boom and plosives"],
                ["Closer for intimate / quiet", "10 to 15 cm", "more bass and presence; watch plosives"],
                ["Further for loud / belting", "25 to 30 cm, or lean back on loud notes", "stops the preamp and capsule being overloaded"],
                ["Height and angle", "a little above the mouth, angled down toward it", "air blasts miss the capsule; sibilance softens"],
                ["Pop shield", "a hand's width from the mic", "see the quiet-recording lesson"]],
      listen="Record the same line from three distances and from straight on and off to one side. Listen on headphones and "
             "pick the one with the fullest voice and the least thump and hiss.",
      mistakes=["Standing too close for a loud song, then fighting boom and distortion. Back up on the loud lines.",
                "Changing position between takes. Mark the floor or the stand so the tone matches.",
                "Using open-back headphones to record: the backing track leaks into the mic. Use closed-back."],
      **{"try": dict(do="Set a cardioid mic at about 15 cm with a pop shield, record one verse, then repeat at 25 cm and with the mic slightly above and angled down.",
                     success="You can hear the distance change the bass and room, and the angle soften P, B and S, and you pick a position on purpose.")},
      quiz=[dict(q="What does aiming a mic slightly off axis from the mouth help with?", options=["Plosives and harsh S sounds", "Bass boost", "Noise from the fridge"], answer=0,
                 why="Air blasts and sharp S sounds travel straight out; a little off axis lets them pass the capsule."),
            dict(q="A good starting distance for a cardioid condenser on a voice is:", options=["1 to 3 cm", "15 to 20 cm", "2 metres"], answer=1,
                 why="A hand span is a common starting point. Move closer for warmth, further for a thinner, roomier sound."),
            dict(q="Why use closed-back headphones to record?", options=["They sound brighter", "Less of the backing track leaks into the mic", "They need no cable"], answer=1,
                 why="Open-back headphones leak sound that the mic picks up as a ghost of the track.")],
      more=["step:gear-quiet", "step:gear-mic-instruments"]),

 dict(id="gear-mic-instruments", title="Starting mic positions: acoustic guitar, an amp, piano and keys, hand percussion", daws=ALL,
      say=["The rule for every instrument is the same: **the mic position is the EQ before the EQ**. Put the mic, listen on headphones, "
           "move it a few centimetres, listen again. The numbers below are where to start.",
           "**Acoustic guitar.** Start 20 to 30 cm from the guitar, aimed at the point where the neck meets the body, "
           "between the 12th fret and the sound hole. Pointing straight into the sound hole sounds boomy. Closer to the "
           "bridge sounds thinner and brighter; closer to the hole sounds warmer.",
           "**Guitar amp.** Use a dynamic mic close to the speaker cone, a few centimetres away. "
           "Aim at the centre of the cone for a brighter, harder tone; toward the edge for a darker, smoother tone. "
           "**Piano.** Use a pair of mics inside the lid for a close sound, or a stereo pair some distance away for more room. "
           "**Keyboards and digital pianos:** use the line output or a DI box, no mic needed.",
           "**Hand percussion** (shaker, tambourine, congas): a small-diaphragm condenser about 30 to 50 cm away, "
           "off to one side of the player and away from the line of the strike or air blast."],
      terms=[["Dynamic mic", "a rugged mic that handles loud sources well, often used on amps and drums."],
             ["Small-diaphragm condenser", "a condenser mic with a thin capsule, good for detail on acoustic instruments and percussion."],
             ["Speaker cone", "the moving part of a speaker. On an amp, mic position across it changes brightness."],
             ["Stereo pair", "two mics set up together to capture width and position."]],
      settings=[["Acoustic guitar", "20 to 30 cm, aimed at the 12th fret to sound hole area", "avoids the boomy sound-hole and picks up the whole body"],
                ["Guitar amp (dynamic mic)", "a few cm from the grille, centre to edge of cone", "centre is bright, edge is darker"],
                ["Piano", "a pair inside the lid, or a stereo pair 1 to 2 m back", "close = clear and dry; further = more room and natural blend"],
                ["Keyboards, digital piano", "line out or DI", "a clean signal with no room"],
                ["Hand percussion", "30 to 50 cm, off to the side", "avoids the blast of air and the loudest strike"]],
      listen="Move the mic a hand's width at a time and listen on headphones. Choose the spot where the instrument sounds like it does in the room, not just the loudest.",
      mistakes=["Pointing a mic straight into the sound hole of an acoustic guitar. It turns boomy. Aim between the 12th fret and the hole.",
                "Putting a mic right in front of a shaker or tambourine, where air bursts hit it. Move off to the side.",
                "Using a mic on a digital keyboard in a noisy room when a cable from its line out would be clean."],
      **{"try": dict(do="Pick one instrument you have. Record 15 seconds with the mic in a first position, then move it 10 cm and record again, then once more at a third spot. Listen on headphones.",
                     success="You can hear tone changes from position alone, and you choose the best spot by ear, not by habit.")},
      quiz=[dict(q="Where do you aim a mic on an acoustic guitar to avoid boom?", options=["Straight into the sound hole", "Between the 12th fret and the sound hole", "At the headstock"], answer=1,
                 why="The sound hole is where low frequencies pile up. Aiming where the neck joins the body picks up a balanced tone."),
            dict(q="On a guitar amp, what does moving the mic toward the edge of the speaker cone do?", options=["Makes it brighter", "Makes it darker and smoother", "Makes it quieter only"], answer=1,
                 why="The centre of the cone is brighter; toward the edge is darker and less harsh."),
            dict(q="How do you record a digital piano or keyboard cleanly?", options=["A mic in the room", "Its line output or a DI box", "A pop shield"], answer=1,
                 why="A line out gives a clean signal with none of the room.")],
      more=["step:gear-mic-voice", "step:gear-two-mics"]),

 dict(id="gear-two-mics", title="Two mics on one source and the 3-to-1 rule", daws=ALL,
      say=["Sometimes one source gets two mics: a guitar amp and a room mic, an acoustic guitar close and far, a snare top and bottom. "
           "Two mics give you two tones to blend, but also a problem. The sound reaches one mic a little before the other, "
           "and when the two are added together some frequencies cancel. The result sounds thin or hollow.",
           "The **3-to-1 rule** helps when two mics are on different sources, like two singers or two instruments side by side. "
           "Put the second mic at least three times as far from the first source as the first mic is. "
           "If mic 1 is 10 cm from its singer, mic 2 should be at least 30 cm from that singer. "
           "That keeps the leakage roughly 10 dB quieter than the direct sound, so it neither cancels much nor adds much.",
           "Sound takes about 3 milliseconds to travel 1 metre. A difference of 30 cm between two mics on the same source is "
           "about a millisecond of delay. Flip the **polarity** (the phase button on the interface, or a polarity or phase-invert control in the DAW) on one mic, "
           "sum them to mono and listen. If the low end gets fuller, keep the flip. If it gets thinner, undo it. "
           "Use `hypnomix align` to measure it: it compares each file to the first one and reports "
           "time offset, polarity and how much fuller the sum gets once fixed."],
      terms=[["Leakage (bleed)", "sound from one source that is picked up by another source's mic."],
             ["3-to-1 rule", "the second mic is at least three times as far from the first source as the first mic is, so leakage stays small."],
             ["Polarity", "whether a signal's wave goes up or down first. Flipping it turns it upside down."],
             ["Phase cancelling", "two copies of a sound that are slightly late or flipped adding together and thinning the sound."],
             ["Time offset", "how much later the sound reaches one mic than the other, in milliseconds."]],
      settings=[["Second mic on a different source", "at least 3 times the first mic's distance from the first source", "keeps leakage low, so it cancels or adds little"],
                ["Two mics on one source", "measure the distance difference; 30 cm is about 1 ms", "tells you the delay you might line up"],
                ["Polarity check", "flip one mic, sum to mono, compare the two", "the fuller one wins"],
                ["Time alignment", "a small nudge, often under a few ms", "only if the sum thins out and a flip did not fix it"]],
      listen="Play both mics together in mono. Flip one and compare. The fuller, warmer one is right. Hear the polarity demo for what cancelling sounds like.",
      hear=["polarity"],
      mistakes=["Judging polarity with the stereo image. Sum to mono: that is where cancelling shows.",
                "Flipping polarity on everything. It only helps when two mics hear the same source.",
                "Aligning two mics so exactly that it sounds lifeless. A small offset is part of the sound; fix only what thins the tone."],
      **{"try": dict(do="Record a guitar (or your voice) with two mics at different distances. Pan both centre, flip one's polarity, and compare in mono. Optional: run `hypnomix align` on the two files.",
                     success="You can hear the sum thin or fill out when the polarity changes, and you keep the setting that sounds fuller.")},
      quiz=[dict(q="What does the 3-to-1 rule say?", options=["Use three mics per source", "The second mic is at least three times as far from the first source as the first mic is", "Mix at three times the volume"], answer=1,
                 why="That distance ratio keeps leakage quiet enough that cancelling is small."),
            dict(q="Two mics on one guitar sound thin when summed. What is the first thing to try?", options=["Add a reverb", "Flip the polarity of one mic and listen again", "Turn both down"], answer=1,
                 why="A flipped polarity makes the mics cancel. Flipping one can restore the fullness."),
            dict(q="About how long is the delay from 1 metre of extra distance?", options=["About 3 ms", "About 30 ms", "About 300 ms"], answer=0,
                 why="Sound travels roughly 343 metres a second, so a metre takes about 3 milliseconds.")],
      more=["step:gear-mic-instruments", "hypnomix align", "align"]),
]

ENRICH = {}
