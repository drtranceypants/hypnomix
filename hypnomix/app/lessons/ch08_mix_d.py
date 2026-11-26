"""Mixing, part D: rides, the mix bus, references, translation, ear fatigue, finishing, common mistakes.
Steps are added to the chapter in ch08_mix.py."""
from hypnomix.app.lessons._common import ALL, LR

STEPS = [
 dict(id="mix-rides", title="Rides: moving the fader to follow the song", daws=ALL,
      say=["A **ride** is a small, deliberate fader move that follows the music. An engineer sits with a hand on the fader "
           "and nudges the vocal up for a quiet line, down for a shouted one, and brings a bass note forward where it "
           "gets lost. Today you draw those moves as **automation** instead of doing them live.",
           "A compressor evens out a vocal by rule. A ride evens it out by judgement: you hear that one line is buried "
           "and you lift it. Use both. Compress first for the broad control, then ride what is still uneven. Three common "
           "places: a vocal line by line, a single bass note that disappears, and a guitar solo that needs to lift "
           "over the band and then step back.",
           "Keep the moves small: 1 to 3 dB is plenty. If you can hear the fader moving, the ride is too big. The aim is "
           "that the song moves, not the fader. Do rides after the balance and effects are set, and leave the master alone.",
           "To see where a vocal needs rides, `hypnomix vocallevel -h` explains a check that measures vocal level line by line and "
           "whether the upper harmonies sit under the melody. With `--apply` it writes volume-automation fixes to a new set, never over the original. "
           "You listen and decide which to keep."],
      terms=[["Ride", "a small fader move that follows the music, made by hand or drawn as automation."],
             ["Automation", "a recorded or drawn line that moves a fader or knob over time."],
             ["Clip gain", "a volume change on one recorded clip, set before the track's effects. Good for fixing one word or one note."],
             ["Read mode", "the DAW plays back the automation you made. Nothing you touch is recorded."],
             ["Write mode", "the DAW records your fader moves as automation while the song plays. Anything it passes over is replaced."],
             ["Touch mode", "the DAW records only while you are holding the fader, and returns to the old line when you let go."]],
      settings=[["Size of a ride", "1-3 dB", "enough to be felt; bigger moves are heard as a moving fader"],
                ["Vocal rides", "up 1-2 dB on weak lines, down 1-2 dB on loud ones", "lifts what a compressor leaves behind, line by line"],
                ["Bass note ride", "up 1-3 dB on the one note that drops out", "a single note can sit in a room dip; ride it, don't boost the whole track"],
                ["Guitar solo", "up 1-3 dB for the solo, back at the end", "the solo steps forward, then the band closes around it"],
                ["Fade of a move", "a short ramp (tens of ms to a second), not a jump", "a sudden step is heard as a click or a pump"]],
      how={"live": ["Press **A** to turn automation mode on in the Arrangement; in the track's lane choosers pick the **Mixer** device and the **Track Volume** control.",
                    "Press **B** for draw mode and draw a gentle line, or click to add points and drag them. Press B again to go back to normal editing."],
           "reaper": ["Click the track's **Env** button (or use the action 'Show track volume envelope') to show the volume envelope.",
                      "Click on the envelope to add points and drag them; keep each move to a few dB."],
           "ardour": ["Click the track's **A** button (automation) and choose **Fader**. Set the automation mode, then add points on the line with the mouse."]},
      listen="Play a section with the rides on, then off, at the same overall loudness. The rides should be hard to hear as moves, but "
             "the quiet lines should be easier to follow and the loud ones less pushy.",
      mistakes=["Rides of 6 dB or more: the vocal seems to surf. Lower them, or fix the line at the source with clip gain or a better compressor setting.",
                "Riding the master fader to fix one track: ride the track that needs it.",
                "Riding in Write mode over good work: in Write the DAW replaces what it passes. Use Touch or draw points by hand, and keep a saved version first."],
      **{"try": dict(do="Pick the lead vocal. Find the quietest line you can barely follow. Add four automation points: before it, at its start, at its end, after it. Lift the middle two by 1.5 dB.",
                     success="The line is easier to understand, and when you play it with the other lines nobody would say 'the fader moved'.")},
      quiz=[dict(q="What size is a good starting ride on a vocal line?", options=["1 to 3 dB", "6 to 10 dB", "Exactly 0.1 dB"], answer=0,
                 why="Small enough that the fader move isn't heard, big enough that the line is easier to follow."),
            dict(q="When is clip gain a better tool than a fader ride?", options=["For the whole song's balance", "For one loud word or one weak note, before the track's effects", "Never; the two are identical"], answer=1,
                 why="Clip gain changes the level going into the effects, so a compressor reacts to an even signal; the fader moves it after. Both are useful for different jobs.")],
      more=["step:automation", "hypnomix vocallevel"]),

 dict(id="mix-bus", title="The mix bus: light touches on the master", daws=ALL,
      say=["The **mix bus** (the master) is where every track meets. Anything you put on it changes the whole song at once. "
           "So the usual answer while mixing is: put almost nothing on it.",
           "If you add something, make it gentle: a **glue compressor** turning down 1 to 2 dB on the loudest moments, to make "
           "the parts feel like one performance. Keep the **limiter off** until mastering. A limiter on the master during "
           "mixing hides peaks, makes everything seem louder, and tricks you into mixing too hot.",
           "Leave **headroom**. With the master fader at 0, aim for peaks around -6 dBFS. A mastering engineer (or you, "
           "later) needs room to work. That is the **handoff**: mixing ends with a clean, un-limited file, and mastering "
           "starts from it.",
           "When you switch the bus compressor on and off, match the level first. Turn the makeup gain until the loudness is "
           "the same. If it is louder, you will like it whether or not it is better."],
      terms=[["Mix bus", "the track everything is summed to before it reaches the speakers. Also called the master."],
             ["Glue compressor", "a gentle compressor on the whole mix, at a low ratio and a small amount of gain reduction, that makes the parts feel together."],
             ["Headroom", "the space between your loudest peak and the digital maximum (0 dBFS)."],
             ["Handoff", "the moment the finished mix goes to mastering, with room to spare and no limiter."],
             ["Level matching", "setting two versions to the same loudness before comparing them."]],
      settings=[["Master fader", "0 dB", "leave it; turn tracks down, not the master"],
                ["Master peaks", "about -6 dBFS", "headroom for mastering"],
                ["Bus compressor ratio", "2:1", "a gentle glue, not a squeeze"],
                ["Bus compressor gain reduction", "1-2 dB on the loudest moments", "more starts to change the balance"],
                ["Bus compressor attack and release", "attack 10-30 ms, release 100-300 ms or auto", "lets the start of each hit through; recovers before the next beat"],
                ["Limiter on the master", "off", "save it for mastering"]],
      how={"live": ["Click the **Master** track's device view and drag **Glue Compressor** onto it, if your edition has it (otherwise **Compressor**).",
                    "Set ratio 2:1 and a threshold that shows 1-2 dB on the meter on the loudest moments; set makeup to match the bypassed level.",
                    "Do not add a Limiter yet."],
           "reaper": ["Show the master track (View menu → Master track), click its **FX** button and add **ReaComp**.",
                      "Ratio 2:1, threshold until the loudest moments show 1-2 dB of reduction; no ReaLimit on it yet."],
           "ardour": ["In the Mixer (Alt+M), find the **Master** strip's plug-in box and add **ACE Compressor**; ratio 2:1, threshold for 1-2 dB of reduction."]},
      listen="Switch the bus compressor in and out with the makeup gain set so the loudness is the same. It should feel a bit more "
             "together, not louder or squashed. If you can't hear a difference, leave it out.",
      mistakes=["Leaving a limiter on the master 'to hear how it will sound': you will mix too hot and the file you hand over is already limited. Take it off before you bounce.",
                "Comparing the bus compressor on and off without matching the level: the louder one always wins. Match the level first.",
                "Peaks at -0.1 dBFS 'because it sounds good': mastering then has no room. Turn the tracks down."],
      **{"try": dict(do="Add a gentle bus compressor (ratio 2:1) and lower the threshold until the loudest moments show 1 dB of reduction. Then set makeup so the loudness matches bypass, and switch it on and off.",
                     success="You can say whether it made the mix feel more together, and whether you would keep it. Both answers are fine.")},
      quiz=[dict(q="What should be on the master while you mix?", options=["A limiter set as hot as possible", "Usually nothing, or a gentle compressor taking 1-2 dB", "A strong EQ boost for brightness"], answer=1,
                 why="The master is for light touches. A limiter belongs in mastering, not in the mix."),
            dict(q="About how high should the master's peaks be at the end of a mix?", options=["0 dBFS", "-6 dBFS", "-30 dBFS"], answer=1,
                 why="Around -6 dBFS leaves headroom for mastering, without being so quiet that you lose detail.")],
      more=["step:chain", "step:mix-references", "mixing-mastering"]),

 dict(id="mix-references", title="Reference songs", daws=ALL,
      say=["A **reference** is a finished song, in the style of yours, that you love and trust. You play it next to your mix to "
           "check your ears. After an hour of mixing, your ears have moved. A reference brings them back to a fixed point.",
           "Pick two or three songs. Put each on its **own track** in your project, so they don't pass through your plug-ins. "
           "Then **match the level**: turn the reference down until it is as loud as your mix, then switch between them. "
           "A louder song always seems better. That is a trick of the ear, not a fact about the mix.",
           "Listen to four things: the **low end** (how much, how tight), the **vocal level** against the band, the "
           "**brightness**, and the **width**. Do not copy the sound. Ask what it has that yours lacks, then decide if you want it.",
           "hypnomix can help. `hypnomix match -h` compares a mix with a reference at matched loudness and lists proposals "
           "(tone in eight bands, dynamics, width, loudness) as a report: it processes nothing. `hypnomix reference -h` takes a mix "
           "and a reference and has `--out` and `--keep` options; use `match` when you want the readable list of proposals."],
      terms=[["Reference track", "a finished song you compare your mix against. It stays on its own track, unprocessed."],
             ["Level matching", "setting two sounds to the same loudness so you judge the sound, not the volume."],
             ["Tonal balance", "how the lows, middles and highs share the sound."],
             ["Width", "how far the sound spreads left to right."]],
      settings=[["Reference level", "turn it down until it matches your mix's loudness", "otherwise the louder one wins"],
                ["How many references", "2-3, in the style of your song", "one can mislead; a few show what is normal"],
                ["Switching", "short sections of the same part (a chorus against a chorus), a few seconds at a time", "your ears forget quickly"],
                ["Plug-ins on the reference track", "none", "you want to hear it as it is"]],
      how={"live": ["Drag the reference file from your computer into the Arrangement, on an empty spot, so Live makes a new audio track.",
                    "If the clip is warped, switch **Warp** off in the clip so it plays unchanged. Lower the track's fader until the loudness matches."],
           "reaper": ["Use Insert → **Media file...** (or drag the file in) to put it on a new track.", "Lower that track's fader until the loudness matches; leave its FX list empty."],
           "ardour": ["Use Session → **Import** to add the file on a new track.", "Lower that track's fader until the loudness matches; add no plug-ins."]},
      listen="At the same loudness, switch between the reference and your mix a few seconds at a time. Ask in turn: is my bass the same weight? "
             "Is my vocal as clear? Is the top as bright? Is it as wide?",
      hear=["loudness-bias"],
      mistakes=["Comparing at different volumes: a reference that is 2 dB louder will beat any mix. Turn it down first.",
                "Running the reference through your master plug-ins: it no longer sounds like the record. Keep it on its own track and the master clean.",
                "Copying the reference's sound note for note: your song is different. Use it for the question, not the answer."],
      **{"try": dict(do="Import one song you love in your style on its own track. Match its loudness to your mix by ear, then compare only the low end: switch back and forth on a chorus.",
                     success="You can say in one sentence whether your bass is lighter, heavier or the same, and what you'd change, if anything.")},
      quiz=[dict(q="Why turn the reference down before comparing?", options=["Loud songs are always bad", "A louder sound seems better, so an unmatched comparison misleads you", "It saves your speakers"], answer=1,
                 why="Our ears favour louder sounds. Matching the level makes the comparison about tone and balance."),
            dict(q="Where should the reference sit in your project?", options=["On its own track, with no plug-ins", "Through your master EQ", "Inside your vocal group"], answer=0,
                 why="Plug-ins would change the reference, and then you're not comparing against the finished record.")],
      more=["hypnomix match", "hypnomix reference", "step:snd-louder-better"]),

 dict(id="mix-translation", title="Checking in mono, on small speakers, earbuds and in a car", daws=ALL,
      say=["A mix has to survive the places people will hear it. A phone speaker. Laptop speakers. Earbuds. A car. A club "
           "or a shop that plays it in **mono**. And at a low volume, late at night. If it only works on your good "
           "speakers, it only half works.",
           "Listen for three things. The **bass disappears**: small speakers can't play deep notes, so a bass that is mostly "
           "sub will vanish. The **vocal gets lost**: if it's only clear because of width or effects, it will sink in mono. "
           "**Harshness**: earbuds and phones lift the highs, and a sharp mix becomes tiring.",
           "You don't need to fix everything. The question is whether the song still works: can you follow the bass line, "
           "hear every word, and listen to the end. Fix the biggest problem, then check again.",
           "`hypnomix translate -h` checks a file for you: what is lost in mono, how it holds up on a small phone speaker, cheap "
           "earbuds and a car, how much streaming services turn it up or down, and whether it clips after MP3 and AAC encoding. "
           "`--render` writes the phone, earbud, car and mono versions so you can listen; `--preview` writes what the MP3 and AAC "
           "encoders (and a Spotify-style normalisation) hand back, so you can hear it. `hypnomix qc -h` runs the release checks "
           "(format, silence, true peak, loudness, phase) on a finished file."],
      terms=[["Mono", "the left and right channels added into one. Phones held sideways, small Bluetooth speakers and some PAs play it."],
             ["Translation", "how well a mix keeps its balance on other speakers and in other places."],
             ["Codec", "the way a file is squeezed for streaming (MP3, AAC). It can add small peaks."],
             ["Streaming normalisation", "a service turning your song up or down so everything plays at a similar loudness."]],
      settings=[["Mono check", "sum the master to mono for a minute", "shows what cancels: the vocal, the guitars, the width"],
                ["Quiet listen", "very low volume, as quiet as you can still hear the vocal", "tells you the balance without loudness helping"],
                ["Small speakers", "a phone or laptop speaker, at a normal level", "can you still hear the bass line and the words?"],
                ["Earbuds and car", "a pair you know well; a drive if you can", "tests harshness and low-end boom"]],
      how={"live": ["Add **Utility** on the master (after everything else) and switch its **Mono** button on to hear the mix in mono. Remove or switch it off before you bounce."],
           "reaper": ["Put a mono (sum to mono) control at the end of the master's FX chain: REAPER's own utility effects include one, or use the master's own channel setting. Switch it off before you bounce."],
           "ardour": ["Use the Monitor section's mono button if your session has one turned on, or add a mono (sum to mono) plug-in at the end of the master's plug-in box. Switch it off before you bounce."]},
      listen="Switch between stereo and mono at the same loudness. The vocal and the bass should stay; if something vanishes or "
             "gets thin, that part is relying on phase or width.",
      hear=["mono-wide"],
      mistakes=["Only listening on the monitors you made the mix on: the room and the speakers hide the problems. Check on two or three other systems.",
                "Making a big fix for a small change: a 1 dB difference in phone speakers is normal. Fix only what makes the song fail.",
                "Forgetting to switch mono off before bouncing the mix: the file comes out in mono."],
      **{"try": dict(do="Bounce or play your mix and listen on three systems: your monitors, a phone speaker, and earbuds. On each, write down one thing that changed (the bass, the vocal, the highs).",
                     success="You have a short note for each system, and you have decided on at most one change to try.")},
      quiz=[dict(q="What often vanishes first on a phone speaker?", options=["The vocal's words", "The deep bass notes", "The hi-hat"], answer=1,
                 why="Small speakers can't move enough air for the lowest notes. If the bass line is mostly sub, it disappears."),
            dict(q="Why check a mix in mono?", options=["Because most listening is mono", "To find parts that cancel out or rely on width", "To make it louder"], answer=1,
                 why="Some places sum left and right. Parts that are out of phase or only clear because of width get weaker or vanish.")],
      more=["hypnomix translate", "hypnomix qc", "step:mix-finished"]),

 dict(id="mix-ear-fatigue", title="Ear fatigue, breaks and a fresh listen", daws=ALL,
      say=["Your hearing adapts. After an hour or so of loud listening, you lose some of the highs, and your sense of "
           "balance drifts. This is **ear fatigue**. A mix made while tired often sounds wrong the next day: too bright, "
           "too much bass, over-compressed. Your ears told you it was fine.",
           "The fix is simple and boring. Take a **10-minute break** every hour, in quiet. Mix at a **low volume** most of "
           "the time and turn it up only briefly to check. Stop when you're tired.",
           "Come back the next day. The **first listen of the day** is gold: fresh ears hear everything that is out of "
           "place. Write down what you notice before you touch anything. A friend with fresh ears can do the same job in a "
           "minute."],
      terms=[["Ear fatigue", "the temporary loss of sensitivity (especially to highs) after long or loud listening."],
             ["Fresh ears", "your hearing and judgement after a rest, before it has adapted to the mix."]],
      settings=[["Listening level", "about conversation level", "lower is easier on your ears; turn it up only briefly to check a loud section"],
                ["Break", "10 minutes every hour", "quiet, away from the screen"],
                ["Session length", "2-3 hours at most before a longer rest", "judgement fades before you notice"],
                ["Overnight pause", "before a final decision", "fresh ears catch what tired ears miss"]],
      listen="After a rest, play the mix once without touching anything. Note what you notice first: too bright, too boomy, a vocal too quiet. "
             "That first impression is the one to trust.",
      mistakes=["Mixing for four hours without a break, then keeping the changes: re-listen the next day before you accept them.",
                "Turning it up when it feels dull: your ears have adapted. Take a break instead.",
                "Making big decisions when tired: save a version and decide tomorrow."],
      **{"try": dict(do="Mix for 45 minutes, then take a break of 10 minutes away from sound. Come back and listen to the mix once without touching a thing. Write down the first three things you notice.",
                     success="You have a short list from fresh ears, and at least one item you didn't notice before the break.")},
      quiz=[dict(q="What is a good way to protect your judgement while mixing?", options=["Mix louder to hear the detail", "Take a break every hour and mix at a low volume", "Mix without stopping so you stay in the groove"], answer=1,
                 why="Short breaks and a lower level slow the adaptation of your ears, so your judgement stays reliable for longer.")],
      more=["step:snd-ears", "step:mix-finished"]),

 dict(id="mix-finished", title="When is a mix finished?", daws=ALL,
      say=["A mix is never perfect. It is **finished** when the song moves you, when it holds up on the checks in the translation lesson "
           "(mono, small speakers, earbuds), and when you have stopped making changes you can't hear when you A/B them.",
           "The danger is the **'one more tweak' loop**: nudging a fader by 0.2 dB, then 0.3 dB back, forever. If you can't "
           "hear the difference when you switch between two versions at the same loudness, the change doesn't matter. Stop.",
           "Accept imperfection. Records you love have small flaws. Set a **deadline**. Then **bounce a version**, "
           "save the project under a new name, and listen to the bounce away from the screen: in the kitchen, in the car, "
           "on a walk. If nothing bothers you after a couple of listens, release it to mastering.",
           "Two hypnomix checks fit the end. `hypnomix scan -h` is a read-only review: it runs the checks on a song, changes nothing, "
           "and writes one review list for you to go through. `hypnomix qc -h` runs release checks and says PASS, WARN or FAIL "
           "per check. They propose; you decide."],
      terms=[["Bounce", "render the mix to a stereo audio file."],
             ["Version", "a saved copy of the project at a point in time, so you can go back."],
             ["Deadline", "a time you decide in advance when the mixing stops."]],
      settings=[["Version names", "song-mix-v1, v2, v3", "you can always go back, and you can see how far you've come"],
                ["Listening away from the screen", "2 or 3 plays, in different rooms", "problems show when you're not looking at the waveform"],
                ["Deadline", "a fixed day, or a fixed number of sessions", "stops the loop"]],
      how={"live": ["File → **Export Audio/Video...** to bounce; File → **Save Live Set As...** under a new name for the version."],
           "reaper": ["File → **Render...** to bounce; File → **Save project as...** for the version."],
           "ardour": ["Session → **Export** → Export to Audio File(s) to bounce; Session → **Save As...** for the version."]},
      listen="Listen to the bounce away from the screen and the DAW, at a normal level. Notice whether you are following the song or "
             "listening for problems. When you're following the song, you're done.",
      mistakes=["Treating mastering as a rescue for a mix you aren't happy with: fix the big problems in the mix, then hand over.",
                "Chasing tiny changes you can't hear when you A/B: stop and save the version.",
                "No saved version before the last changes: keep each version so you can go back."],
      **{"try": dict(do="Bounce your mix. Listen to it twice away from the screen (a different room, or earbuds). Write down at most three changes that matter. Make only those.",
                     success="You have a version saved, a short list, and the feeling that the next change would be small.")},
      quiz=[dict(q="When is a mix finished?", options=["When every meter is green", "When the song moves you, it holds up on your checks and further tweaks make no audible difference", "When it is as loud as a commercial record"], answer=1,
                 why="Finished is a judgement by ear: the song works, it translates, and you are no longer making changes you can hear."),
            dict(q="How can you tell a tweak is worth keeping?", options=["It makes the waveform look better", "You can hear it when you switch back and forth at the same loudness", "It took a long time to do"], answer=1,
                 why="A change you can't hear in an A/B, at matched loudness, does not help the listener.")],
      more=["step:mix-translation", "hypnomix qc", "hypnomix scan"]),

 dict(id="mix-mistakes", title="The ten most common beginner mistakes", daws=ALL,
      say=["Almost everyone makes the same mistakes at first. Here they are, each with the fix. The lesson that fixes it is in brackets.",
           "**1. Mixing too loud for too long.** Your ears tire and your judgement slips. Fix: low volume, a break every hour (Ear fatigue). "
           "**2. No low cuts.** Rumble builds up and the mix goes muddy. Fix: a low cut on every track that doesn't need the lows (Low cuts). "
           "**3. Boosting instead of cutting.** Boosts add up and make everything harsh. Fix: cut what is in the way first (EQ: cut first).",
           "**4. Too much reverb.** The mix washes out and loses the words. Fix: lower the send until you only just notice it (Reverb). "
           "**5. Over-compressing everything.** The mix goes flat and lifeless. Fix: 3-6 dB on the loudest words, and leave some tracks alone (Compression in depth). "
           "**6. Soloing everything.** A part that sounds great alone may not fit. Fix: set sounds with the whole mix playing.",
           "**7. Comparing without level matching.** The louder version always seems better (Why louder seems better). "
           "**8. No reference.** Without one you don't know what normal is (Reference songs). "
           "**9. Mixing through the master limiter.** It hides peaks and fools you into mixing hot. Fix: take it off until mastering (The mix bus). "
           "**10. Not checking in mono and on small speakers.** Fix: check before you call it done (Checking in mono, on small speakers, earbuds and in a car)."],
      terms=[],
      listen="Look at your current project and tick off the ten. Which one would you fix first?",
      mistakes=["Trying to fix all ten at once: change one thing at a time, and compare at the same loudness.",
                "Treating the list as rules: every one has exceptions. Use your ears."],
      **{"try": dict(do="Go through the ten against a mix you are working on. For each, write yes, no or not sure. Pick the one that is most likely to be affecting the sound and fix only that.",
                     success="You have one change made, you compared before and after at the same loudness, and you can say what you heard.")},
      quiz=[dict(q="Which of these is a common beginner mistake?", options=["Comparing two versions without matching their loudness", "Taking a break every hour", "Checking the mix on small speakers"], answer=0,
                 why="The louder version always seems better, so an unmatched comparison misleads you.")],
      more=["step:mix-lowcuts", "step:mix-references", "step:mix-bus", "step:mix-translation"]),
]

ENRICH = {
 "automation": dict(
     mistakes=["Big moves: a 6 dB jump on a vocal sounds like a fader, not a performance. Keep moves to 1-3 dB; see the lesson on rides.",
               "Drawing automation before the balance is set: do it last, otherwise you redo it after every change.",
               "Forgetting existing automation: when you add moves, look at what is already there before you draw over it."],
     **{"try": dict(do="Pick a vocal, find a chorus, and draw a rise of 1.5 dB at its start and a fall of the same size at its end, with ramps of about a second.",
                    success="The chorus lifts without you hearing the move. Switch the automation off and on to confirm it is working.")},
     quiz=[dict(q="What is automation?", options=["A line that moves a fader or knob over time", "A plug-in that mixes for you", "A way to make the master louder"], answer=0,
                why="It records or draws a control's movement so the DAW repeats it on every play.")],
     more=["step:mix-rides"]),
 "mix-check": dict(
     mistakes=["Treating the findings as orders: every one is a suggestion with a before and after to hear. You decide.",
               "Running it before the mix is roughly balanced: run it once it sounds good to you, then again before the final export."],
     **{"try": dict(do="Run hypnomix's first pass on a finished song. Pick one finding, play its before and after at the same loudness, and decide whether to keep it.",
                    success="You have approved or skipped each finding you looked at by ear, and none was applied without a listen.")},
     quiz=[dict(q="What does hypnomix do with its findings?", options=["Proposes them, and you decide by listening", "Applies them automatically", "Deletes the original files"], answer=0,
                why="hypnomix proposes and you decide. Its tools write new files and never change your originals.")],
     more=["first-pass", "step:mix-finished"]),
}
