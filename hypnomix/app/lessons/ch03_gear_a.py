"""Your room and your gear, part A: interface, microphones, cables, headphones and speakers."""
from hypnomix.app.lessons._common import ALL, LR

STEPS = [
 dict(id="gear-interface", title="The audio interface", daws=ALL,
      say=["An **audio interface** is the box that connects your microphones and instruments to the computer, and the computer "
           "to your headphones and speakers. Inside are the parts that matter: **preamps** that lift quiet signals, **converters** "
           "that turn sound into numbers (and back into sound), and amplifiers for the headphones. The computer's own sound "
           "socket has none of these done well, which is why a basic interface is the first thing worth buying.",
           "Look at the sockets. **Inputs** take microphones (XLR), instruments (the Hi-Z jack, explained in the cables and levels lesson) or line-level gear. "
           "Many have a **combo** socket that takes either an XLR or a jack. **Outputs** go to your speakers (the monitor outputs) "
           "and a headphone socket with its own volume knob. It connects by USB or Thunderbolt: USB is plenty for a few channels; "
           "Thunderbolt is for larger boxes with many inputs.",
           "When you sing or play, you hear yourself late if the sound has to go into the computer and back out. **Direct monitoring** "
           "fixes this: the interface sends your input to the headphones straight away, before the computer, with no delay. "
           "Use it when recording, and turn the DAW's own input monitoring off so you don't hear yourself twice.",
           "For a first one, look for: as many inputs as the sources you will record at the same time (often just two), "
           "phantom power for condenser microphones, a Hi-Z input, a direct-monitoring control, a headphone output that is loud "
           "enough, and a maker that still updates its drivers for your computer. A **driver** is the small program that lets the computer "
           "talk to the box. On a Mac most boxes need none; on Windows you usually install the maker's driver. "
           "More expensive boxes mainly add more inputs, quieter preamps and lower delay, not a different kind of sound."],
      terms=[["Audio interface", "the box that turns microphone and instrument signals into numbers for the computer, and the computer's audio back into sound for your headphones and speakers."],
             ["Converter", "the circuit that turns sound into numbers (analogue to digital) or numbers into sound (digital to analogue)."],
             ["Monitor output", "the output that feeds your speakers. Its knob sets how loud the speakers play."],
             ["Direct monitoring", "hearing the input straight from the interface, before the computer, so there is no delay."],
             ["Combo socket", "an input that accepts both an XLR plug and a quarter-inch jack."],
             ["Driver", "the program that lets the computer talk to the interface."],
             ["Aggregate device", "a Mac feature that joins several audio devices into one, for example an interface plus the computer's own output. Skip it until you need two devices at once."]],
      settings=[["Inputs to look for", "2 for a solo recordist; 4 to 8 if you track a band or a drum kit", "you can only record at once as many things as you have inputs"],
                ["Connection", "USB for most home studios; Thunderbolt only for many channels", "USB is simpler and cheaper, and enough for a small number of channels"],
                ["Phantom power", "a switch for +48 V (see the pickup patterns lesson)", "most condenser microphones need it"],
                ["Headphone output", "its own volume knob; start with it low", "headphones can be much louder than speakers"]],
      how={"live": ["Open the **Audio** tab of Live's Settings (called Preferences in Live 11): it is in the **Live** menu on a Mac and the **Options** menu on Windows. Choose your interface as the audio input and output device. On Windows, pick the interface's ASIO driver as the Driver Type first, then the interface as the Audio Device."],
           "reaper": ["Open **Options → Preferences → Audio → Device**. Choose your audio system (on a Mac, Core Audio; on Windows, ASIO if your interface offers it), then your interface."],
           "ardour": ["Open **Window → Audio/MIDI Setup**. Choose the audio system, your interface as the device for input and output, then start the engine."]},
      listen="Play a song through the interface's headphone output, then through the computer's own headphone socket. The interface is usually cleaner, "
             "louder without distortion, and has a steadier bottom end.",
      mistakes=["Hearing yourself twice, once late from the DAW and once direct from the interface: turn the DAW's input monitoring off, or the interface's direct monitoring off, and use one.",
                "Buying many more inputs than you will use: two good inputs beat eight you never plug anything into.",
                "Skipping the driver on Windows, then wondering why the box has delay or crackles."],
      **{"try": dict(do="Plug in your interface and open your DAW's audio settings. Choose the interface for input and output, then play a track and set the headphone knob so it is comfortably quiet.",
                     success="You hear the DAW's playback from the interface, and you can say which socket is the monitor output and which is the headphone output.")},
      quiz=[dict(q="What does direct monitoring do?", options=["Lets you hear the input straight from the interface, with no delay", "Records your voice at a higher quality", "Adds reverb to the headphones"], answer=0,
                 why="The input goes to your headphones before it reaches the computer, so you don't hear yourself late."),
            dict(q="Which part of the interface turns sound into numbers?", options=["The preamp", "The converter", "The headphone amplifier"], answer=1,
                 why="The preamp lifts the signal, the converter turns it into numbers, and the headphone amplifier powers your headphones.")],
      more=["step:gear-cables-levels", "step:gear-mic-kinds", "step:gain"]),
 dict(id="gear-mic-kinds", title="Microphone kinds: dynamic, condenser and ribbon", daws=ALL,
      say=["A microphone has a thin, light part that the sound pushes, and a way to turn that movement into a signal. "
           "There are three common ways to do it. Each gives a different sound and a different kind of toughness.",
           "A **dynamic** microphone moves a small coil in a magnet. It is rugged, needs no power, and copes with very loud sounds: "
           "the usual choice for a guitar amp, a snare, a kick, and loud singing. It is a little less detailed in the top end. "
           "A **condenser** uses a very light diaphragm close to a metal plate. It needs power (usually phantom power) and hears more fine "
           "detail and more of the room. That makes it the usual choice for voice, acoustic guitar, piano and drum overheads in a quiet space.",
           "A **ribbon** microphone hangs a thin strip of metal in a magnet. It sounds warm and smooth, with a soft top end that flatters "
           "bright sources such as brass, guitar amps and some voices. It is delicate: a strong gust of air, such as a plosive or a blast, can "
           "stretch the ribbon, and some ribbons can be damaged by phantom power. Check the manual first.",
           "Condensers come with a small or a large diaphragm. **Small-diaphragm** ones are usually more even, and keep a more natural tone for sound that arrives from the side, with less loss of brightness: good for acoustic guitar, hi-hats and overheads. **Large-diaphragm** ones are usually fuller and "
           "closer sounding: a common choice for voice. Price isn't the point: a modest mic in the right place usually beats an expensive one in the wrong place."],
      terms=[["Dynamic microphone", "a rugged microphone that needs no power and handles loud sources."],
             ["Condenser microphone", "a sensitive microphone with a very light diaphragm. It needs power and hears fine detail."],
             ["Ribbon microphone", "a delicate microphone with a thin metal ribbon. It sounds warm and smooth."],
             ["Diaphragm", "the thin part of a microphone that the sound pushes."],
             ["Small-diaphragm / large-diaphragm", "the size of a condenser's diaphragm. Small is more even; large is fuller and warmer."],
             ["Plosive", "a burst of air from a sound like P or B that can overload a microphone."]],
      settings=[["Loud sources: amp, snare, kick, loud singer", "dynamic", "it handles high levels and picks up less of the room"],
                ["Voice, acoustic guitar, piano", "condenser", "it hears detail and air, in a quiet room"],
                ["Overheads, hi-hats", "small-diaphragm condenser", "an even, natural tone, even for sound that arrives from the side"],
                ["Bright or harsh sources: brass, some amps", "ribbon, or a dynamic", "a soft top end smooths them"]],
      listen="If you can, record the same voice or guitar on two different kinds of mic, level-matched. Listen for the top end and for how much of the room comes through.",
      mistakes=["Choosing by price: the mic that suits the source and the room beats the expensive one that doesn't.",
                "Putting a condenser in a noisy or echoey room: it hears the room as clearly as the singer. A dynamic microphone close to the mouth hears less of it.",
                "Singing or blowing into a ribbon: breath and plosives can damage it. Keep it back, and use a pop filter on voice."],
      **{"try": dict(do="Write down the microphones you have or could borrow, and for each one say whether it is dynamic, condenser or ribbon. Look at the label, the manual or the maker's page. Then choose the best one for a voice in your room.",
                     success="Each microphone has a kind written next to it, and you can say why you picked one for voice.")},
      quiz=[dict(q="Which kind of microphone needs no power and copes best with very loud sounds, like a close guitar amp?", options=["A ribbon, because it is smooth", "A large-diaphragm condenser, because it is the most detailed", "A dynamic, because it handles loud sound and needs no power"], answer=2,
                 why="Dynamic microphones are rugged and cope with high levels. Condensers can overload, and ribbons are delicate."),
            dict(q="Which kind of microphone can be damaged by phantom power or a loud gust of air?", options=["A ribbon", "A dynamic", "A small-diaphragm condenser"], answer=0,
                 why="Some ribbons, especially older ones, can be harmed by phantom power, and a hard blast can stretch the ribbon. Check the manual.")],
      more=["step:gear-patterns-phantom", "step:gear-interface"]),
 dict(id="gear-patterns-phantom", title="Pickup patterns and phantom power", daws=ALL,
      say=["A microphone doesn't hear equally in all directions. Its **pickup pattern** says where it hears best, and where it hears least. "
           "A **cardioid** pattern, heart-shaped, hears the front well, the sides less, and the back very little. It is the most common, "
           "because you can point it at the voice and away from the speakers and the noise. An **omni** hears equally from every direction: it sounds open and natural, "
           "and also picks up the whole room. A **figure-eight** hears the front and the back, and almost nothing at the sides. Ribbon mics are usually figure-eight.",
           "Which way it faces matters. Most large studio microphones are **side-address**: you speak into the side with the logo or badge. "
           "Many stage microphones are **end-address**: you speak into the top. Check the manual if you are unsure. Point the front at the source "
           "and the back at whatever you want to hear less. Close to a cardioid, the bass gets bigger, an effect called **proximity effect**; "
           "the lesson on a quiet recording room covers it (`step:gear-quiet`).",
           "A condenser microphone needs power for its electronics. Most get it from the interface as **phantom power**, "
           "+48 V sent down the same cable. Turn your speakers and headphones down first. Plug the microphone in with the gain down, then switch +48 V on, wait a few seconds, and only then raise the volume. "
           "Switch it off before you unplug. Dynamic microphones don't need it. Some ribbons can be damaged by it, so read the manual of any ribbon before you switch it on."],
      terms=[["Pickup pattern", "the shape of where a microphone hears: its sensitivity around it. Also called the polar pattern."],
             ["Cardioid", "a heart-shaped pattern that hears the front and rejects the back."],
             ["Omnidirectional (omni)", "a pattern that hears equally from every direction."],
             ["Figure-eight", "a pattern that hears the front and the back and rejects the sides."],
             ["Side-address / end-address", "whether you speak into the side or the end of the microphone."],
             ["Phantom power (+48 V)", "power sent down the microphone cable from the interface, which most condenser microphones need."],
             ["Proximity effect", "the extra bass you get when a directional microphone is very close to the source. A later lesson covers it."]],
      settings=[["Cardioid", "voice, single instruments, noisy rooms", "it rejects the sound behind it, so the room and the speakers matter less"],
                ["Omni", "a good-sounding room, a choir, ambience", "a natural sound, and no extra bass up close"],
                ["Figure-eight", "two sources facing each other, or a ribbon on a single source", "the back and the front are both heard; the sides are rejected"],
                ["Phantom power +48 V", "on for most condensers, off for dynamics and most ribbons", "condensers need it; others may be harmed or gain nothing"]],
      listen="Speak or play at one microphone while you turn it slowly around in front of the source. Listen for the point where the sound is clearest, and where it fades or goes hollow.",
      mistakes=["Facing the microphone the wrong way, so its back points at the singer: it sounds distant and dull.",
                "Switching on phantom power before the microphone is plugged in, or leaving it on while unplugging: this can make a loud bang in the headphones.",
                "Switching phantom power on for a ribbon without checking: some are damaged by it."],
      **{"try": dict(do="Plug in a microphone with the gain down, with phantom power off, and find which end or side you speak into. If it is a condenser, take your headphones off or turn them right down, switch phantom power on, wait a few seconds, then raise the gain slowly. Turn the headphones down and switch it off before unplugging.",
                     success="You know your microphone's front, you can say whether it needs phantom power, and you did the switching in the right order.")},
      quiz=[dict(q="A cardioid microphone hears best...", options=["From every direction equally", "From the sides", "From the front, and least from the back"], answer=2,
                 why="Cardioid means heart-shaped: sensitive in front, less at the sides and very little behind."),
            dict(q="What is the safe order for phantom power?", options=["On before you plug in, off after you unplug", "Plug in, then switch it on; switch it off, then unplug", "Leave it on all the time"], answer=1,
                 why="Plugging a microphone in or unplugging it while phantom power is on can cause a loud thump and, for some ribbons, damage. So connect first, switch +48 V on with the volume down, and switch it off before you unplug."),
            dict(q="Which microphone type can most easily be damaged by phantom power?", options=["A dynamic", "A large-diaphragm condenser", "A ribbon, some of them"], answer=2,
                 why="Some ribbons, especially older ones, can be damaged. Condensers are built for it and dynamics ignore it.")],
      more=["step:gear-mic-kinds", "step:gear-quiet", "step:gear-interface"]),
 dict(id="gear-cables-levels", title="Cables and levels: mic, instrument and line", daws=ALL,
      say=["Three kinds of signal come out of the things you plug in, and each wants a different input. A **microphone** makes "
           "a tiny signal that needs a **preamp** to lift it. A guitar or bass pickup makes a bigger signal that wants a special "
           "high-impedance input (a **Hi-Z** or instrument input). A keyboard, a drum machine or the output of another box makes "
           "a strong **line level** signal that needs no lifting at all.",
           "Plug a line-level signal into a mic input and it distorts, because the preamp lifts something that was already loud. "
           "Plug a guitar into a mic input and it sounds thin and dull, because the input loads the pickups wrongly. The fix "
           "is the right input, or a **DI box** that turns the instrument's signal into a clean, mic-like one.",
           "Cables matter in one way. A **balanced** cable (XLR, or a TRS jack) carries the signal twice, once flipped, so noise "
           "picked up along the way cancels at the far end. An **unbalanced** cable (a guitar lead, an RCA) can't do that, so keep "
           "unbalanced runs short."],
      terms=[["Mic level", "the tiny signal from a microphone. It needs a preamp."],
             ["Instrument level (Hi-Z)", "the signal from a guitar or bass pickup. It wants an instrument input or a DI box."],
             ["Line level", "the strong signal from keyboards, drum machines and gear outputs. It needs no preamp gain."],
             ["Balanced / unbalanced", "a balanced cable cancels the noise it picks up; an unbalanced one doesn't."],
             ["XLR, TRS, TS", "the plugs: XLR is the three-pin mic plug, TRS a jack with a tip, one ring and a sleeve (balanced, or stereo for headphones), TS a jack with only a tip and a sleeve (an unbalanced guitar lead)."],
             ["DI box", "a box that turns an instrument's signal into a balanced, mic-like one, so a long cable doesn't hurt it."],
             ["Preamp", "the circuit that lifts a quiet signal to a level the converter can use. Its knob is the input gain."]],
      settings=[["Microphone", "an XLR mic input, gain up slowly from zero", "mic signals are tiny; the preamp lifts them"],
                ["Electric guitar or bass", "an instrument (Hi-Z) input, or a DI box into a mic input", "keeps the tone full and the level right"],
                ["Keyboard, synth, drum machine", "a line input", "already strong; a mic input would overload"],
                ["Long cable runs", "balanced (XLR or TRS)", "noise cancels over the distance"],
                ["Guitar leads", "unbalanced, as short as practical", "a long lead picks up hum and loses top end"]],
      listen="Record a few seconds of the same guitar into an instrument input and into a mic input. The right input sounds "
             "fuller and clearer; the wrong one sounds thin or buzzy.",
      mistakes=["Plugging a keyboard into a mic input and turning the gain up: the signal is already strong, so the preamp overloads and the sound turns crunchy. Use a line input instead.",
                "Running a 10-metre guitar lead when a short lead and a DI box would stay clean.",
                "Leaving a phantom-power switch on when plugging in or unplugging a mic: switch it off first (see the pickup patterns and phantom power lesson)."],
      **{"try": dict(do="Look at the back and front of your interface and find the mic, instrument and line inputs. Plug in one thing at the matching input and set its gain so the loudest sound peaks around -12 to -6 dBFS on the meter, well below the top and never touching it.",
                     success="You can say which input each of your sources uses and why, and the meter peaks well below the top.")},
      quiz=[dict(q="You plug a keyboard into a mic input and it sounds crunchy. What is the likely cause?", options=["The keyboard is out of tune", "A line-level signal went into a preamp that lifted it further", "The cable is too short"], answer=1,
                 why="A keyboard already puts out a strong line-level signal. Use a line input, or turn the gain right down."),
            dict(q="What does a balanced cable do?", options=["Makes the signal louder", "Cancels noise picked up along the cable", "Adds stereo width"], answer=1,
                 why="It carries the signal twice, once flipped, so noise that gets into both copies cancels when they are recombined.")],
      more=["step:gear-interface", "step:gain"]),
 dict(id="gear-headphones-speakers", title="Headphones against speakers", daws=ALL,
      say=["You need headphones for two jobs, and they are different ones. For **recording**, use **closed-back** headphones. "
           "They seal around the ear and keep the sound in, so the click or the backing track doesn't leak into the microphone. "
           "For **mixing**, **open-back** headphones, or speakers, are the better tools: they sound more natural and tire the ear less. "
           "Open-back headphones leak a lot, so they are no good while a microphone is open.",
           "Each way of listening has strengths. Headphones give you detail, and they leave the room out of it, so a bad room "
           "can't fool you. But they place the sound inside your head, and they can mislead you about bass and about how wide a stereo mix is. "
           "Speakers give real space, and you feel the bass in your body, but they need a good room and a good position. A boomy room will lie to you about the bottom end.",
           "So check on both. A mix that works on headphones and on speakers is likely to work on a phone, a car and a stereo. "
           "Look for a **flat** or neutral pair: one that doesn't push the bass or the top. No pair is perfect, so learn yours: "
           "play songs you know well and love, and note what they sound like. Then when your mix sounds different, you can tell what is missing or too much."],
      terms=[["Closed-back headphones", "headphones that seal around the ear and keep sound in. Good for recording."],
             ["Open-back headphones", "headphones that let sound pass through the cups. They sound more natural but leak. Good for mixing."],
             ["Flat / neutral", "a sound that doesn't add its own bass or treble, so what you hear is what is in the recording."],
             ["Studio monitors", "speakers made for listening to a mix as it is, not for flattering it."],
             ["Leakage (spill)", "sound from your headphones getting into the microphone."],
             ["Translation", "how well a mix still sounds right on other systems, like a phone, a car or a hi-fi."]],
      settings=[["Recording", "closed-back headphones", "the click and the backing track don't leak into the microphone"],
                ["Mixing, first choice", "speakers in a treated room, or open-back headphones", "a natural balance and less ear fatigue"],
                ["Checking", "both, plus a phone or a car", "if the mix works in all of them, it will work almost anywhere"],
                ["Listening level", "low to moderate; turn it up only briefly to check, and never to a level that is uncomfortable, especially on headphones", "the ear tires when loud, and then you hear less"]],
      listen="Play a song you know on speakers, then on headphones, at the same loudness. Notice how the bass, the width and the vocal position change, and what you would need to remember about your own pair.",
      mistakes=["Mixing only on headphones and adding too much bass or width, because both sound different on speakers: check on speakers or another system.",
                "Using open-back headphones to record: the sound leaks into the microphone. Use closed-back.",
                "Mixing loud for hours: your ears tire and your judgement slips. Listen quietly and take breaks."],
      **{"try": dict(do="Choose three songs you know well. Play them on your headphones and on speakers (or on your phone) at the same loudness, and write one line about how each sounds different.",
                     success="You have a short note about what your headphones do to bass, width and brightness, which you can use when you mix.")},
      quiz=[dict(q="Why use closed-back headphones to record?", options=["They keep the sound from leaking into the microphone", "They sound more natural", "They are always cheaper"], answer=0,
                 why="Closed-back cups seal the sound in, so the click or the backing doesn't get into the microphone."),
            dict(q="What is a strength of speakers over headphones?", options=["They remove the effect of the room", "They give real space and you feel the bass", "They never need a good room"], answer=1,
                 why="Speakers play into a real space. The cost is that the room affects them."),
            dict(q="What helps you trust headphones you have never used before?", options=["Learning them with music you know well", "Turning the bass up", "Using them only at low volume"], answer=0,
                 why="Songs you know let you hear what your pair adds or hides, so you can allow for it.")],
      more=["step:gear-speaker-placement", "step:gear-room", "step:gear-interface"]),
 dict(id="gear-speaker-placement", title="Speaker placement and where to sit", daws=ALL,
      say=["Speakers sound best when you sit in the right place relative to them. The starting rule is an **equilateral triangle**: "
           "the two speakers and your head form a triangle with all three sides about the same length. The distance between the speakers "
           "equals the distance from each speaker to you. Turn each speaker in a little (toe it in) so they point at your head, or just behind it.",
           "Put the **tweeters**, the small speakers that make the high sounds, at ear height when you sit. Highs are the most directional, "
           "so a tweeter pointing at your chest or the ceiling sounds dull. If the speakers must sit above or below ear height, tilt them to face your ears. "
           "Stand them on the desk with **isolation pads** or on stands, so the speaker doesn't shake the desk and add bass to it.",
           "Keep the speakers away from walls and corners. The bass bounces back off a nearby surface and piles up, so a speaker pushed into a corner sounds boomy. "
           "Try to leave some space behind them, and have the same distance to the side walls on each side. "
           "Where you sit matters too: a common starting rule is about **38 percent** of the room's length from the front wall (the one behind the speakers). "
           "It is only a place to start. Move your chair a little, listen for where the bass is even, and use that spot. The room itself is the next lesson (`step:gear-room`)."],
      terms=[["Equilateral triangle", "a triangle with three equal sides: here, the distance between the speakers equals the distance from each one to you."],
             ["Toe-in", "turning each speaker inward toward your head."],
             ["Tweeter", "the small driver in a speaker that makes the high sounds."],
             ["Listening position", "the spot where you sit to mix, the corner of the triangle."],
             ["Isolation pad", "a foam or rubber pad under a speaker that stops it vibrating the desk or stand."],
             ["Bass build-up", "extra bass, from sound reflecting off walls and corners, that makes a place sound boomy."]],
      settings=[["Triangle", "speakers and you equally far apart, about 1 to 1.5 metres for desktop speakers", "an even stereo picture: a phantom centre between them"],
                ["Height", "tweeters at ear height; tilt if not", "the highs are directional and are weakest off-axis"],
                ["Distance from wall behind", "30 to 60 cm or more, and never in a corner", "close surfaces cause bass build-up"],
                ["Listening position", "about 38 percent of the room's length from the front wall, then move by ear", "it avoids the worst bass peaks and dips in many rooms, but each room differs"]],
      listen="Play a mono bass-heavy song and move your chair back and forth by 30 cm. Listen for where the bass sounds even, with no boom and no hole.",
      mistakes=["Putting the speakers on the desk against the wall with no pads: the bass booms and the desk vibrates. Pull them out and use pads.",
                "Sitting at the exact middle of the room: it is where several low notes cancel. Move your seat forward or back.",
                "Setting the speakers too far apart, so the middle of the sound opens into a hole. Bring them in until the centre firms up."],
      **{"try": dict(do="Measure the distance between your speakers. Sit that same distance from each one, tweeters at ear level, and toe them in. Then play a song with a centred vocal and move your chair 30 cm forward and back.",
                     success="The singer seems to sit in the middle between the speakers, and you have chosen the seat where the bass sounds most even.")},
      quiz=[dict(q="What is the usual starting shape for speakers and listener?", options=["A straight line", "A right angle", "An equilateral triangle"], answer=2,
                 why="Equal sides give an even stereo picture, with a clear phantom centre."),
            dict(q="Why keep speakers out of corners?", options=["Bass reflects and piles up, so the sound gets boomy", "The highs disappear", "The stereo width doubles"], answer=0,
                 why="The walls and the floor reinforce the bass, and corners do it most."),
            dict(q="What is the 38 percent rule?", options=["A mixing loudness target", "A starting place to sit, measured from the front wall", "A speaker volume setting"], answer=1,
                 why="It is a place to start to try; the right place still depends on your room, so move and listen.")],
      more=["step:gear-room", "step:gear-headphones-speakers"]),
]

ENRICH = {}
