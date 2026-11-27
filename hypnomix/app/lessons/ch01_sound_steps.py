"""Sound and hearing: what sound is, frequency, loudness, waveforms, phase, mono and stereo, and looking after your ears."""
from hypnomix.app.lessons._common import ALL

STEPS = [
 dict(id="snd-what-is-sound", title="What sound is", daws=ALL,
      say=["Sound is a vibration that travels through the air. A guitar string, a speaker cone or your vocal cords push the air "
           "back and forth, and the push moves outward as small changes in air pressure. When those changes reach your ear, "
           "you hear sound. Nothing travels except the pressure change: the air itself stays roughly where it was.",
           "A **microphone** has a thin surface that moves with those pressure changes and turns the movement into a tiny "
           "electrical signal. A **speaker** does the reverse: it takes an electrical signal and moves a cone, which pushes "
           "the air and makes the same pattern again. Recording is catching that pattern and storing it. Playback is making it again.",
           "Every sound has three qualities you can describe. **Pitch** is how high or low it is. **Loudness** is how strong "
           "it is. **Tone** (also called timbre) is what makes a piano sound different from a voice playing the same note at "
           "the same level. Most of mixing is shaping one of these three, so keep them apart in your head."],
      terms=[["Sound wave", "a pattern of air-pressure changes that travels outward from a vibrating thing."],
             ["Microphone", "a device that turns air-pressure changes into an electrical signal."],
             ["Speaker", "a device that turns an electrical signal back into air-pressure changes."],
             ["Pitch", "how high or low a sound is. It follows the speed of the vibration."],
             ["Loudness", "how strong a sound seems. It follows the size of the pressure change."],
             ["Tone (timbre)", "the character of a sound, what lets you tell a flute from a violin on the same note."]],
      listen="Hum a low note, then a high one, then the same note softly and loudly. You have just changed pitch, then loudness, "
             "without changing anything else.",
      mistakes=["Mixing up pitch and loudness: a high sound is not a loud one. Say 'higher' or 'lower' for pitch, 'louder' or 'quieter' for level.",
                "Treating tone as one thing. 'Dull' and 'bright' are tone words; they tell you the balance of low and high, not the level."],
      **{"try": dict(do="Rest two fingers on your throat and hum a low note, then a high one. Then hum the same note softly and loudly.",
                     success="You feel the vibration, and you can say which of pitch, loudness or tone changed in each case.")},
      more=["step:snd-frequency-pitch", "step:snd-loudness-db"]),

 dict(id="snd-frequency-pitch", title="Frequency and pitch", daws=ALL,
      say=["**Frequency** is how many times a vibration repeats each second. The unit is the **hertz** (Hz). A sound at 100 Hz "
           "repeats 100 times a second. 1,000 Hz is one **kilohertz** (kHz). The faster the vibration, the higher the pitch you hear.",
           "Double a frequency and you go up one **octave**: 100 Hz, 200 Hz, 400 Hz, 800 Hz are each an octave apart, and "
           "they sound like the same note at a higher register. The concert tuning note A is 440 Hz; the A an octave above is 880 Hz. "
           "This is why the low end of the spectrum feels crowded on a graph: the octave from 50 to 100 Hz covers 50 Hz, "
           "while the octave from 5 to 10 kHz covers 5,000 Hz.",
           "A young, healthy ear hears from about 20 Hz to 20 kHz. Hearing narrows with age, and most of the loss is at the top: "
           "many adults no longer hear much above 15 kHz, and that is normal. It also means the top of a mix is "
           "something you may need to trust a meter or a friend for."],
      terms=[["Frequency", "how many times a vibration repeats each second."],
             ["Hertz (Hz)", "the unit of frequency: one cycle per second."],
             ["Kilohertz (kHz)", "1,000 hertz. 10 kHz is 10,000 Hz."],
             ["Octave", "a doubling of frequency. Notes an octave apart sound like the same note."],
             ["Spectrum", "the whole range of frequencies in a sound, from low to high."]],
      listen="In the demo, hear a 100 Hz sine, a 1 kHz sine and a 10 kHz sine at the same level. They are the same loudness on a "
             "meter, yet the 1 kHz tone sounds the strongest and the 100 Hz one the weakest.",
      mistakes=["Thinking an octave is a fixed number of hertz. It is a doubling, so it is wider the higher you go.",
                "Assuming everyone hears to 20 kHz. Use the top of the range as a guide, not a promise."],
      **{"try": dict(do="Look for a free tone-generator website or app, or use the demo above. Put on headphones and set the volume very low before you start. Play 1 kHz, then sweep slowly down towards 20 Hz, and then up from 1 kHz towards 20 kHz. Note where the sound fades out at either end. Small speakers cannot play the very lowest notes, so use headphones. Do not turn the volume up to chase the ends: the high tones can be sharper than they seem, and your ears are the one thing you cannot replace.",
                     success="You know roughly where your hearing starts and stops at the low and high ends, and you know it is not the same as a friend's.")},
      quiz=[dict(q="What happens to a sound's frequency when it goes up one octave?", options=["It doubles", "It rises by 100 Hz", "It stays the same but gets louder"], answer=0,
                 why="An octave is a doubling: 220 Hz, 440 Hz and 880 Hz are all the note A, each an octave apart."),
            dict(q="Which is the usual range of human hearing in a young, healthy ear?", options=["100 Hz to 5 kHz", "20 Hz to 20 kHz", "1 kHz to 50 kHz"], answer=1,
                 why="About 20 Hz to 20 kHz. The top end fades with age, often from the late teens onward.")],
      hear=["sine-pitch"],
      more=["step:snd-freq-map", "step:snd-ears"]),

 dict(id="snd-freq-map", title="The frequency map: where voices and instruments sit", daws=ALL,
      say=["It helps to split the spectrum into zones and learn what lives in each. The names and edges differ a little from book "
           "to book, so treat the numbers below as a map, not a rulebook. The first four zones carry most of the body and the "
           "weight of a song; the top two carry the clarity and the shine.",
           "Where do things sit? A **kick drum** has its thump at about 50 to 100 Hz and its click at 2 to 5 kHz. A **bass** "
           "lives from about 40 to 250 Hz. A **voice** has its body at 100 to 300 Hz, its words in the mids and at 2 to 5 kHz, "
           "and its 's' sounds at about 5 to 9 kHz. A **guitar** fills the low-mids and mids, with its pick and string noise "
           "above 2 kHz. **Cymbals** sit mostly above 3 kHz and run up to the top of hearing.",
           "Describing a problem in plain words points to the zone. **Muddy**: too much in the low-mids, around 150 to 400 Hz. "
           "**Boxy**: a hollow, cardboard-like build-up around 300 to 600 Hz. **Harsh**: too much around 2 to 5 kHz, where the "
           "ear is most sensitive. **Airy**: a pleasant open top above about 10 kHz. When a mix sounds wrong, try to find "
           "the word first. The word tells you where to look."],
      terms=[["Sub", "the lowest zone, below about 60 Hz. You feel it as much as you hear it."],
             ["Bass (frequency zone)", "about 60 to 250 Hz: the weight of kick, bass and the body of a voice."],
             ["Low-mids", "about 250 to 500 Hz: warmth when right, mud when there is too much."],
             ["Mids", "about 500 Hz to 2 kHz: where most instruments and the core of a voice live."],
             ["Presence", "about 2 to 6 kHz: clarity and attack. Too much sounds harsh."],
             ["Air", "above about 6 kHz: the shine of cymbals and the open top of a voice."],
             ["Muddy", "too much low-mid energy (around 150 to 400 Hz): the sound is thick and unclear."],
             ["Boxy", "a hollow, cardboard-like quality (around 300 to 600 Hz)."],
             ["Harsh", "too much energy around 2 to 5 kHz: it sounds hard or sharp and tires the ear."],
             ["Airy", "open and light at the top, from the highs above about 10 kHz."]],
      settings=[["Sub", "about 20-60 Hz", "kick and bass weight, felt in the chest. Many small speakers and headphones cannot play it."],
                ["Bass", "about 60-250 Hz", "kick thump, bass notes, the body of a voice. Sounds 'boomy' when too loud."],
                ["Low-mids", "about 250-500 Hz", "warmth of guitars, keys and snare body. Too much sounds muddy or boxy."],
                ["Mids", "about 500 Hz-2 kHz", "the core of a voice, guitars, snare. Too much sounds honky or nasal."],
                ["Presence", "about 2-6 kHz", "vocal clarity, guitar and snare attack, kick click. Too much sounds harsh."],
                ["Air", "about 6-20 kHz", "cymbals, 's' sounds, shimmer. Too little sounds dull; too much sounds hissy."]],
      listen="In the demo, the same music is played through one zone at a time. Learn what each zone contributes: sub is felt, "
             "bass is weight, low-mids are warmth, mids are the tune, presence is clarity, air is sparkle.",
      mistakes=["Learning numbers without listening. The ranges move with the instrument and the player. Use them to start looking, then trust your ears.",
                "Fixing 'harsh' by turning down the whole top. Look at 2 to 5 kHz first; the air above is probably fine.",
                "Blaming one track for mud. Mud is usually the sum of many tracks, so check them together."],
      **{"try": dict(do="Put a song you know well on, and describe it in three words from the map above (for example 'warm', 'bright', 'boomy'). Then find the zone each word points to.",
                     success="You can name the zone behind each word and say which instrument in the song fills it.")},
      hear=["freq-bands"],
      more=["step:eq", "step:mix-lowcuts"]),

 dict(id="snd-loudness-db", title="Loudness and decibels", daws=ALL,
      say=["The **decibel** (dB) is not a unit like a metre. It is a ratio: it compares one level to another. "
           "That is why a fader in a DAW says '-6 dB': it means 6 dB lower than where it was, or lower than the reference point.",
           "Two scales matter. **dB SPL** measures real sound pressure in a room, with 0 dB SPL near the quietest sound you can hear. "
           "**dBFS** (decibels relative to full scale) measures digital signal level inside a DAW. **0 dBFS** is the digital "
           "ceiling: a signal cannot go above it without **clipping**. Everything in a DAW sits at or below 0 dBFS, so the "
           "numbers are mostly negative.",
           "Your ear's rules of thumb: a change of about 1 dB is barely noticeable. About 3 dB is clearly audible. "
           "6 dB roughly doubles the signal's amplitude, and it seems a good deal louder. About 10 dB is what most people call 'twice as loud'. "
           "Small moves of 1 to 2 dB are the daily work of a mix; moves of 10 dB change the whole picture."],
      terms=[["Decibel (dB)", "a ratio between two levels. Six dB up doubles the amplitude."],
             ["dB SPL", "decibels of real sound pressure in the air, measured with a sound-level meter."],
             ["dBFS", "decibels relative to full scale: the digital level inside a DAW. 0 dBFS is the maximum."],
             ["Clipping", "when a signal tries to go above the maximum and gets flattened off, which sounds harsh."],
             ["Headroom", "the room left below the maximum level before clipping."]],
      how={"live": ["Play the loudest part of a song.",
                    "Make the Mixer taller by dragging up on its top edge until the track meters grow. Look for the small peak-level number that comes with the track's meter (not the volume number): it shows the highest peak so far in dB, and clicking it resets it.",
                    "Raise or lower the fader by 1 dB, then 3 dB, and listen to how big each step sounds."],
           "reaper": ["Play the loudest part of a song.",
                      "Open the mixer (View → Mixer, or Ctrl+M / Cmd+M). Each strip's meter has a small number above it: the highest peak so far, in dB (not the fader's level). Click the number to reset it.",
                      "Move the fader by 1 dB, then 3 dB (its level in dB shows as you drag), and listen to how big each step sounds."],
           "ardour": ["Play the loudest part of a song.",
                      "Watch the peak display above the mixer strip's meter. Click it to reset it.",
                      "Move the strip's fader by 1 dB, then 3 dB, and listen to how big each step sounds."]},
      listen="Play a song and change the track or master fader by 1 dB, then 3 dB, then 6 dB. A 1 dB step is hard to hear, 3 dB is clear and 6 dB is plainly louder.",
      mistakes=["Treating dB as an absolute number. '-6 dB' is only meaningful against a reference: a level, a fader's start or full scale.",
                "Confusing dB SPL and dBFS. A signal at -20 dBFS can be any loudness in a room; it depends on the volume knob.",
                "Dismissing 1 dB moves as pointless. Small steps add up across many tracks."],
      **{"try": dict(do="Take one track, set its fader to -6 dB, then raise it 1 dB at a time to 0 dB, playing the same bar each time. Note which steps you can hear.",
                     success="You can say that single 1 dB steps are subtle, a 3 dB gap is clear and the full 6 dB is obvious.")},
      quiz=[dict(q="What is a decibel?", options=["A fixed unit of loudness, like a metre", "A measure of pitch", "A ratio that compares one level to another"], answer=2,
                 why="It is a ratio, so it only means something against a reference: full scale in a DAW, or the quietest audible sound in the air."),
            dict(q="In a DAW, what is 0 dBFS?", options=["Silence", "The digital ceiling: a signal cannot go higher without clipping", "The average level of a song"], answer=1,
                 why="0 dBFS is full scale. Digital levels are measured downward from it, so they are mostly negative numbers."),
            dict(q="About how big a level change is clearly audible, but not huge?", options=["0.1 dB", "3 dB", "30 dB"], answer=1,
                 why="About 1 dB is barely noticeable; about 3 dB is clearly audible; about 10 dB sounds roughly twice as loud.")],
      more=["step:gain", "step:snd-louder-better"]),

 dict(id="snd-louder-better", title="Why louder seems better", daws=ALL,
      say=["Play the same song twice, once 2 dB louder, and most people say the louder one sounds better: fuller, clearer, "
           "more exciting. Nothing was improved. It is just louder. The ear and the brain prefer a louder version in a quick "
           "comparison, and they do it even when the person knows the trick.",
           "That makes it easy to fool yourself in a mix. Turn up an equaliser band or a compressor's make-up gain, and the result "
           "sounds richer, so you keep it. But some of that 'richer' is only the extra level. The same goes for a plug-in's "
           "bypass switch: if the plug-in raises the level, the processed side wins every time, however little it helps.",
           "The cure is to compare at the **same loudness**. Match the level of the two versions by ear or by meter, then decide. "
           "If the change still sounds better, keep it. If it only sounded better because it was louder, leave it out. "
           "This is the most important habit in this course. Every later chapter on EQ, compression and mastering depends on it."],
      terms=[["Matched loudness", "two versions set to the same level, so the louder one cannot win just by being louder."],
             ["Loudness bias", "the tendency to prefer whatever is louder in a quick comparison."],
             ["Make-up gain", "gain added after a processor (like a compressor) to bring the level back up."],
             ["Bypass", "switching a processor off so the signal goes through untouched."]],
      listen="In the demo, the same clip is heard 2 dB apart, and the louder one seems better. Then a tone change is heard at matched "
             "level, where the difference is only the tone.",
      mistakes=["Judging an effect by flicking it on and off without matching the level. The 'on' side usually wins by volume.",
                "Matching by eye on the fader, not by ear. After matching, listen again and nudge by ear.",
                "Raising the whole mix to 'check it better'. The mix is not better, it is only louder."],
      **{"try": dict(do="Take a track and put an EQ on it with a 3 dB boost at 3 kHz. Flip the EQ on and off a few times. Then, with the EQ on, turn the EQ's own output gain down (or add a simple gain or Utility device after it) until it is no louder than with the EQ off, checking by ear and by meter. Flip again. Do not use the track fader for this: it changes both sides equally.",
                     success="You hear that part of the 'improvement' was loudness, and you can say whether the tone change itself is worth keeping.")},
      quiz=[dict(q="Why does a slightly louder version of the same song often win a quick comparison?", options=["The ear and brain prefer the louder one", "It really is better mixed", "Louder versions have more bass"], answer=0,
                 why="Loudness bias: we hear louder as better. That is why you compare at matched loudness."),
            dict(q="What should you do before judging whether a plug-in made a mix better?", options=["Turn the plug-in up as far as it goes", "Match the level with it on and off", "Listen once on headphones only"], answer=1,
                 why="If the level differs, the louder side tends to win. Match the level first, then decide if the change itself is better.")],
      hear=["loudness-bias"],
      more=["step:mix-check", "mixing-mastering"]),

 dict(id="snd-waveforms", title="Waveforms: sine, triangle, square, saw and noise", daws=ALL,
      say=["A **waveform** is the shape of the vibration drawn over time. Five shapes are worth knowing, because every synth and "
           "most test tones are built from them. A **sine** is the smoothest: one pure frequency and nothing else. A **triangle** "
           "is a little brighter, with weak odd harmonics added. A **square** is hollow and buzzy, with strong odd harmonics. "
           "A **saw** (sawtooth) is bright and full, with every harmonic. **Noise** has no pitch at all: it is energy "
           "at every frequency at once.",
           "Real instruments are not sine waves. A violin note is a **fundamental** (the pitch you hear) plus a stack of "
           "**harmonics**, which are whole-number multiples of that frequency (2x, 3x, 4x and so on). How strong each harmonic "
           "is gives the instrument its tone. This is why a synth with a saw wave sounds richer than one with a sine, "
           "and why filtering a saw is the classic way to shape a sound.",
           "Two kinds of noise come up. **White noise** has equal energy at every frequency, so it sounds hissy and bright. "
           "**Pink noise** drops 3 dB per octave, so each octave carries the same energy, which sounds more even and natural. "
           "Pink noise is used to test speakers and rooms. And this ties to **distortion**: when a signal clips, it grows "
           "new harmonics that were not there, which is why clipping sounds harsh and a gentle saturation sounds warm."],
      terms=[["Waveform", "the shape of a vibration drawn over time."],
             ["Sine wave", "the purest waveform: one frequency and no harmonics."],
             ["Triangle wave", "a waveform with weak odd harmonics: softer than a square."],
             ["Square wave", "a hollow, buzzy waveform with strong odd harmonics."],
             ["Sawtooth wave (saw)", "a bright, full waveform with every harmonic."],
             ["Harmonics", "whole-number multiples of a pitch (2x, 3x, 4x...) that give a sound its tone."],
             ["Fundamental", "the lowest frequency of a note, the one that sets the pitch you hear."],
             ["White noise", "noise with equal energy at every frequency. It sounds bright and hissy."],
             ["Pink noise", "noise that falls 3 dB per octave, so each octave has equal energy. It sounds more even."],
             ["Distortion", "a change to a waveform that adds new harmonics, from gentle warmth to harsh clipping."]],
      listen="If your DAW has a synth, play the same note with a sine, a triangle, a square and a saw, then noise. Notice that "
             "the pitch is the same but the tone is different: the harmonics are the difference.",
      mistakes=["Expecting noise to have a pitch. It has a colour (bright or dark), not a note.",
                "Thinking a sine wave is 'the real sound'. It is a test tone; real instruments are always richer.",
                "Calling all distortion bad. A small amount adds harmonics that can make a thin sound fuller."],
      **{"try": dict(do="Open a synth or sampler in your DAW (or a free online oscillator) and play one note on each waveform in turn. Then, if you can, add a low-pass filter and slowly lower its cutoff on the saw.",
                     success="You can hear that the sine is plain, the saw is bright, and that the filter makes the saw duller by removing harmonics.")},
      quiz=[dict(q="Which waveform has no harmonics, just one frequency?", options=["Saw", "Square", "Sine"], answer=2,
                 why="A sine wave is a single frequency. Saws and squares are built from many harmonics."),
            dict(q="What is the difference between white noise and pink noise?", options=["White noise is quieter", "White noise has equal energy at every frequency; pink noise falls 3 dB per octave", "Pink noise has a pitch"], answer=1,
                 why="Pink noise has equal energy per octave, so it sounds more even to the ear. White noise has equal energy per hertz, so it sounds brighter."),
            dict(q="Why does clipping sound harsh?", options=["It makes the sound quieter", "It adds new harmonics that were not in the original", "It removes the highs"], answer=1,
                 why="Flattening a wave makes new harmonics. Strong, high ones are what the ear hears as harshness.")],
      more=["step:saturation", "step:snd-freq-map"]),

 dict(id="snd-phase-polarity", title="Phase and polarity", daws=ALL,
      say=["When two signals play together, they add. If both push the air the same way at the same moment, they get "
           "louder. If one pushes while the other pulls, they **cancel**, and the sound gets thinner or even disappears.",
           "Two ideas are mixed up here. **Polarity** is the direction of the push: normal or flipped. Flipping polarity "
           "(the button marked with a circle and a slash) turns the wave upside down. **Phase** is about timing: how far one "
           "copy is shifted against another. A shift of half a cycle looks like a polarity flip at that one frequency, but a "
           "time shift cancels different frequencies differently, which gives a hollow, 'comb' sound. In everyday talk, people say "
           "'phase' for both, and it usually does not matter, but the fix differs: flip a polarity, nudge a time.",
           "It bites in two common places. **Two mics on one source**, like a pair on a guitar amp or a room mic and a close mic on a "
           "drum: the sound reaches them at different times, so some frequencies cancel. And **a snare with a mic on top and "
           "one below**: the bottom mic sees the head moving the other way, so one of them is usually flipped to match. "
           "Flip one and keep the version that sounds fuller, especially in the lows."],
      terms=[["Phase", "how far one copy of a wave is shifted in time against another."],
             ["Polarity", "whether a signal pushes the air outward or inward first. Flipping it turns the wave upside down."],
             ["Polarity flip (phase invert)", "a switch that turns a signal upside down. It is often marked with a circle and a diagonal line."],
             ["Cancellation", "two signals that are opposite each other adding to nothing, or less than either alone."],
             ["Comb filtering", "a hollow, notched sound caused by mixing a signal with a delayed copy of itself."]],
      how={"live": ["Put **Utility** (Audio Effects) on the second mic's track.",
                    "Click **Phz-L** and **Phz-R** (the phase-invert buttons) to flip the polarity of both channels.",
                    "Listen to both mics together with and without it, and keep the fuller sound."],
           "reaper": ["On the second mic's track, click the **Ø** (invert phase) button on the track control panel or on its mixer strip. If you cannot see it, make the track taller. If it is still missing, add the stock 'JS: Stereo Channel Volume/Pan/Polarity Control' to the track and set both Phase switches to Invert.",
                      "Click it on and off while both mics play, and keep the fuller sound."],
           "ardour": ["On the second mic's mixer strip, click the polarity button (marked with a circle and a diagonal line).",
                      "Click it on and off while both mics play, and keep the fuller sound."]},
      listen="In the demo, A has the two mics adding, so it sounds full. In B one mic is flipped, so they cancel and it sounds thin, hollow and quieter. The level meter usually drops too, most in the low end. With real mics the change can be smaller, so trust the fuller sound.",
      mistakes=["Flipping polarity on everything 'just in case'. Do it only when two mics on one source sound thin, and compare both ways.",
                "Judging by eye on the waveforms. The ear decides: keep whichever sounds fuller.",
                "Ignoring it because one track alone sounds fine. The problem only shows when the two play together."],
      **{"try": dict(do="Duplicate a track, flip polarity on the copy, and play both together.",
                     success="They cancel and the sound nearly disappears, which shows you what a polarity flip does. Undo it afterwards.")},
      quiz=[dict(q="Two mics on one snare sound thin together. What is the quickest first thing to try?", options=["Add reverb", "Flip the polarity of one mic and compare", "Turn both mics down 6 dB"], answer=1,
                 why="Opposite polarity makes the two cancel. A flip often brings the fullness back."),
            dict(q="What is the difference between polarity and phase, in plain words?", options=["They are the same thing", "Polarity is the direction of the push; phase is a time shift between copies", "Polarity is loudness; phase is pitch"], answer=1,
                 why="A polarity flip turns a wave upside down. A phase shift moves a copy in time. People often say 'phase' for both."),
            dict(q="If you flip polarity on a mono track playing alone, what do you hear?", options=["It gets much quieter", "It goes out of tune", "Almost no difference"], answer=2,
                 why="Alone, an upside-down signal sounds the same. The effect only shows when it combines with another signal.")],
      hear=["polarity"],
      more=["step:snd-mono-stereo", "hypnomix align"]),

 dict(id="snd-mono-stereo", title="Mono and stereo", daws=ALL,
      say=["**Mono** is one channel of sound, played the same from every speaker. **Stereo** is two channels, left and right, "
           "which let sounds sit across a width between the speakers. The width in a stereo mix comes from the left and the "
           "right being different: a guitar played slightly more in the left, another in the right, a stereo-miked "
           "piano, a short delay on one side. A stereo effect on top helps, but it cannot make width out of a signal that is the same in both.",
           "A lot of people hear your music in mono, or close to it. A phone speaker is one small driver. Many club "
           "systems are summed to mono so everyone on the floor hears the same. A smart speaker, a shop sound system or a "
           "Bluetooth speaker may do the same. If your mix collapses in mono (a part vanishes, or the whole thing gets thin) "
           "that is usually a phase problem between left and right.",
           "So **check in mono**. Switch the mix to mono now and then, and listen: do the vocal, the bass and the kick stay "
           "solid? Does anything disappear? Fix what does, and the mix will survive on every speaker. Keep the bass and the "
           "lead vocal near the centre, and use the width for the parts that can afford it."],
      terms=[["Mono", "one channel of sound, the same from every speaker."],
             ["Stereo", "two channels, left and right, that give a sense of width."],
             ["Stereo width", "how far apart left and right are, and how wide the mix sounds."],
             ["Pan", "placing a sound between left and right."],
             ["Mono compatibility", "how well a stereo mix still sounds when it is summed to mono."]],
      how={"live": ["Add **Utility** (Audio Effects) to the Main track (the master).",
                    "Switch its **Mono** button on to hear the mix in mono, and off again to go back to stereo.",
                    "Remove it, or turn it off, before you export."],
           "reaper": ["Click the master track's **FX** button and add the stock 'JS: Channel Mixer', leaving its four mix sliders at their default -6 dB: it then plays the left and right channels mixed equally into both sides, which is mono. Or use the Mono button on the master strip in the Mixer if your layout shows one. Switch it on and off to compare, and take it off before you export.",
                      "Switch it on and off to compare, and remove it before you export."],
           "ardour": ["Turn on the monitor section (Session > Properties > Monitoring > 'Use monitor section in this session'), then press its **Mono** button to hear the mix in mono. Press it again to go back to stereo. It only changes what you hear, so there is nothing to remove before you export.",
                      "Switch it on and off to compare, and remove it before you export."]},
      listen="In the demo, the same mix is heard in mono and then wide. Listen for parts that become quieter or thinner when summed to mono, and for the centre getting stronger.",
      mistakes=["Leaving a mono check on while exporting. Take it off before the final render.",
                "Making everything wide. Bass, kick and lead vocal belong near the centre; the sides are for supporting parts.",
                "Using a stereo-widening effect on a mono sound and expecting width. Record or arrange left and right differently instead."],
      **{"try": dict(do="Play a finished song in stereo, then switch the master to mono. Listen for what drops, thins or disappears.",
                     success="You can name one part that changed in mono, and say whether it still does its job.")},
      quiz=[dict(q="Where does stereo width mostly come from?", options=["A widening effect on the master", "Left and right being different from each other", "Turning the volume up"], answer=1,
                 why="If left and right are identical, the sound is mono, whatever the effect. Width comes from different left and right signals."),
            dict(q="Why check a mix in mono?", options=["It makes the mix louder", "It removes the need to master", "Many phones, clubs and speakers play mono, and phase problems show up there"], answer=2,
                 why="Parts that cancel between left and right can vanish in mono. Catching it early keeps the mix solid on every playback system.")],
      hear=["mono-wide"],
      more=["step:snd-phase-polarity", "step:mix-check"]),

 dict(id="snd-ears", title="How we hear, and looking after your ears", daws=ALL,
      say=["The ear is a tiny, delicate machine. Sound is collected by the outer ear, passes the eardrum and three small "
           "bones, and reaches the **cochlea**, a fluid-filled spiral lined with thousands of fine hair cells. Each region reacts to "
           "a different frequency. Those hair cells do not grow back once damaged, so protecting them is the most important "
           "tool you have in audio.",
           "The ear is not a flat microphone. We hear the mids and upper mids (about 2 to 5 kHz) best, which is why that band "
           "sounds harsh when there is too much of it. At low volumes the ear loses bass and treble, so a mix sounds thin and bass-light when it is "
           "quiet and fuller when it is loud. The same mix can seem to change just by moving the volume knob. And ears get tired. After a long, loud session, high frequencies seem duller, and your "
           "judgement drifts. That is **ear fatigue**.",
           "So work at a comfortable level. Roughly the level of a normal conversation, a little above it at most, is "
           "enough for most mixing. Do short loud checks only, a few seconds at a time. Take a break every 45 to 60 "
           "minutes, and come back to your mix with fresh ears. Wear earplugs made for music at gigs and rehearsals. "
           "If your ears ring or sound muffled after a loud night, rest them. If it lasts, or you notice ringing (**tinnitus**) "
           "or muffled hearing that does not go away, see a doctor. This is not medical advice, only a good rule."],
      terms=[["Cochlea", "the fluid-filled spiral in the inner ear where hair cells turn vibration into nerve signals."],
             ["Ear fatigue", "temporary tiredness of the ears after long or loud listening: the highs seem duller and judgement drifts."],
             ["Tinnitus", "a ringing or buzzing in the ears with no outside source. See a doctor if it lasts."],
             ["Hearing protection", "earplugs or ear defenders that lower the level so loud sound does less harm. Plugs made for music keep it clear."]],
      listen="Notice when your ears are tired: the highs seem softer, and you keep wanting more top or more volume. That is your cue to stop and rest.",
      mistakes=["Mixing loud 'to hear everything'. Quieter is better for judging balance, and safer.",
                "Skipping breaks because the mix is going well. Fatigue hides itself: the mix may sound good until you return the next day.",
                "Ignoring ringing after a loud gig. Rest your ears, and see a doctor if it does not go away."],
      **{"try": dict(do="Set your listening volume so that you can talk to someone beside you without raising your voice. Mix for 45 minutes at that level, then take a 10-minute break in a quiet room.",
                     success="You finish with ears that feel fresh, and your mix still sounds balanced when you return.")},
      quiz=[dict(q="About how loud should you usually work when mixing?", options=["As loud as the speakers go", "Around conversation level, with short loud checks", "Too quiet to hear the bass at all"], answer=1,
                 why="A moderate level protects your ears, keeps your judgement steady and lets you hear the balance without fatigue."),
            dict(q="What should you do if your ears ring or feel muffled after loud listening, and it does not go away?", options=["Turn the volume up to test them", "See a doctor", "Wait a few weeks and carry on"], answer=1,
                 why="Persistent ringing or muffled hearing is a reason to see a doctor, not to carry on."),
            dict(q="Which part of the spectrum are our ears most sensitive to?", options=["The sub, below 60 Hz", "The air, above 15 kHz", "The upper mids, about 2 to 5 kHz"], answer=2,
                 why="The ear is most sensitive around 2 to 5 kHz, which is why a build-up there sounds harsh and tiring.")],
      more=["step:snd-loudness-db", "step:snd-louder-better"]),
]

ENRICH = {}
