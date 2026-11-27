"""Mastering, new steps for the complete course (az): units, streaming targets, the limiter, codecs, dither, albums,
versions and when to hand a song to someone else. ENRICH adds teaching fields to the existing steps in ch09_master.py."""
from hypnomix.app.lessons._common import ALL

STEPS = [
 dict(id="mst-units", title="LUFS, true peak and loudness range in plain words", daws=ALL,
      say=["Three numbers describe how loud a master is, and each answers a different question. **LUFS** says how loud the "
           "song feels, averaged over time the way an ear hears it (low notes count a little less than mid and high ones, "
           "because that is how hearing works). **True peak** says how high the tallest peak really reaches. "
           "**Loudness range** says how much the loudness moves from quiet parts to loud ones.",
           "LUFS comes in three kinds. **Integrated** is one number for the whole song: the one streaming services use. "
           "**Short-term** looks at the last three seconds, so you can see a chorus against a verse. "
           "**Momentary** looks at the last 0.4 seconds and jumps about with every drum hit. For a finished song, watch integrated and short-term.",
           "True peak, in **dBTP**, matters because a digital file only stores points, and the real wave between two points can "
           "rise higher than both. An ordinary peak meter misses that. A true-peak meter looks between the points, which is "
           "what a converter or an encoder will produce.",
           "No single number tells the whole story. Two songs can both read -14 LUFS and sound very different: one steady and "
           "dense, one dynamic with a quiet verse and a big chorus. Read the numbers together, then listen."],
      terms=[["Integrated loudness", "the loudness of the whole song as one number, in LUFS. This is what streaming services measure."],
             ["Short-term loudness", "the loudness over the last three seconds. It shows how a chorus compares with a verse."],
             ["Momentary loudness", "the loudness over the last 0.4 seconds. It moves fast and is only a guide."],
             ["Loudness range (LRA)", "how far the loudness moves between the quiet and loud parts of a song, in LU. A small number is steady; a large one is dynamic."],
             ["LU", "loudness unit. One LU is the same size as one dB; it is used for differences and for the loudness range."],
             ["Inter-sample peak", "a peak that exists in the real wave between two stored sample points. A true-peak meter shows it."],
             ["dBTP", "decibels of true peak: the unit of a true-peak meter. 0 dBTP is the highest level a converter can play without distortion."]],
      settings=[["Integrated LUFS", "one number for the whole song; the target comes next lesson", "this is what loudness normalisation uses"],
                ["Short-term LUFS", "watch it through the chorus; it often sits 1-3 LU above the integrated number", "shows where the song really gets loud"],
                ["True peak", "-1 dBTP or lower", "leaves room for encoders and cheap converters"],
                ["Loudness range", "often about 4-8 LU for pop and rock, more for acoustic or quiet music", "no right answer: it is the shape of your song"]],
      how={"live": ["Live has no stock loudness meter that I can name here. Put a loudness meter plug-in on the **Master**, last in the chain, "
                    "or export the song and run `hypnomix measure` on the file. If your version of Live has a loudness meter, use it.",
                    "Read the meter while the whole song plays, then read the **integrated** number at the end."],
           "reaper": ["On the **Master** track click **FX** and type \"loudness\" in the search box: REAPER ships a loudness meter among its JS effects. Play the whole song, then read integrated.",
                      "Or export the song and run `hypnomix measure` on the file."],
           "ardour": ["Use HypnoMix DAW's **loudness analysis** (the Loudness step shows where) or a loudness meter plug-in on the master strip. Play the whole song, then read integrated.",
                      "Or export the song and run `hypnomix measure` on the file."]},
      listen="Watch the short-term number while you play a verse and then a chorus. Hear how a 3 LU jump feels: clearly louder, not twice as loud.",
      mistakes=["Trusting the peak meter alone: it tells you nothing about how loud the song feels. Read LUFS as well.",
                "Reading momentary LUFS and chasing it: it jumps with every beat. Use integrated for the song and short-term for sections.",
                "Measuring only the chorus: services measure the whole song, so a quiet verse lowers the integrated number."],
      **{"try": dict(do="Play your master to the end with a loudness meter on the master (or run `hypnomix measure` on the exported file). Write down integrated LUFS, true peak and loudness range.",
                     success="You have three numbers and can say, in a sentence each, what they tell you and what they don't.")},
      quiz=[dict(q="Why does true peak exist as a separate reading from the ordinary peak meter?", options=["It is easier to read", "It measures the bass only", "The real wave between stored points can rise higher than any stored point"], answer=2,
                 why="Samples are points on a wave. The wave between two points can go higher than both, and a converter or encoder will reproduce it."),
            dict(q="Which loudness reading do streaming services use to decide how much to turn a song down?", options=["Integrated", "Momentary", "Short-term"], answer=0,
                 why="Integrated loudness is one number for the whole song, so it is the natural thing to normalise to.")],
      more=["step:mst-streaming", "step:snd-loudness-db", "hypnomix measure"]),

 dict(id="mst-streaming", title="How streaming services turn songs up and down, and sensible targets", daws=ALL,
      say=["Most streaming services use **loudness normalisation**: they measure each song and then turn the loud ones down "
           "(and sometimes the quiet ones up) so a playlist stays at one level. A common reference is about **-14 LUFS** integrated. "
           "Apple Music's Sound Check works to about -16. YouTube also turns loud videos down, at about the same level as Spotify.",
           "So a very loud master does not win. It is played back lower, with less punch than a master that was never squeezed. "
           "That is the reason to aim for the service's level, not above it.",
           "Treat every figure here as a moving target. Services change their numbers, offer listeners a louder or quieter setting, "
           "and treat albums and singles differently. Check each service's own page before you rely on a number.",
           "A sensible aim for most pop, rock and acoustic songs is between **-14 and -9 LUFS integrated**, with the true-peak "
           "ceiling at **-1 dBTP**. Where in that range depends on the genre and the song. Dynamic music (a quiet singer-songwriter "
           "song, jazz, classical) can sit lower, and often should."],
      terms=[["Loudness normalisation", "a playback system that measures each song and turns it up or down to one reference level, so loud songs don't jump out."],
             ["Sound Check", "Apple's name for its loudness normalisation setting."],
             ["Reference level", "the loudness a service plays songs at, for example about -14 LUFS."],
             ["Headroom", "the space between your loudest peak and the maximum. A master with no headroom can't be turned up by a service without distortion."]],
      settings=[["Quiet acoustic, jazz, classical", "-18 to -14 LUFS integrated", "the dynamics are the music; services turn it up little or not at all, and you don't need to squash it"],
                ["Pop, rock, singer-songwriter", "-14 to -10 LUFS integrated", "close to the services' level, with room for punch"],
                ["Dense and loud genres", "-10 to -8 LUFS only if you know why", "services will turn it down; you gain density, not volume"],
                ["True-peak ceiling", "-1 dBTP", "safe after the service's own encoding (next lessons)"],
                ["Apple Music first", "about -16 LUFS", "Sound Check's reference"]],
      how={"live": ["Set the Master's last device (the Limiter) so the integrated loudness lands where you want, then check it on a loudness meter plug-in or with `hypnomix measure`."],
           "reaper": ["Adjust the limiter on the master (ReaLimit) until the integrated loudness lands where you want, then check it on the master's loudness meter or with `hypnomix measure`."],
           "ardour": ["Adjust the master's limiter, then use the loudness analysis or `hypnomix measure` to read the integrated loudness."]},
      listen="Play your master next to a finished song in your genre, level-matched. If the other song sounds bigger at the same loudness, the difference is the mix and the tone, not volume.",
      mistakes=["Pushing to -7 LUFS because \"everyone else is loud\": a service plays it back lower and you keep the distortion.",
                "Treating -14 as a rule: it is a reference. A dynamic song at -16 is fine.",
                "Quoting last year's numbers: check the service's page, and write the date next to what you note."],
      **{"try": dict(do="Run `hypnomix translate` on your master. Read what each service would do to it (turn it down or up, and by how much). Then export a version 4 LU quieter and compare the two at the same loudness.",
                     success="You know how much each service would change your master and can say whether the louder version really sounded better.")},
      quiz=[dict(q="A service plays loud songs down to -14 LUFS. What do you gain by delivering a master at -8 LUFS?", options=["Nothing in volume, and less punch", "A louder song on that service", "More bass"], answer=0,
                 why="It is turned down to the same level as everyone else, so you keep only the squashing."),
            dict(q="Which master has the most reason to sit well below -14 LUFS?", options=["A dense rock track", "A quiet solo piano piece", "A club track"], answer=1,
                 why="Dynamic music loses its shape when it is pushed up. Services turn quiet songs up only as far as the peaks allow (and some do not turn them up at all), so a dynamic song stays quieter and you don't need to squash it.")],
      hear=["loudness-bias"],
      more=["step:mst-units", "step:mst-codec", "hypnomix translate", "mastering"]),

 dict(id="mst-limiter", title="The limiter in depth", daws=ALL,
      say=["A **limiter** is a compressor with an infinite ratio and a very fast attack: nothing gets past its **ceiling**. "
           "It sits last in the chain. You turn its **gain** up, it stops the peaks going over the ceiling, and the whole "
           "song gets louder while the peaks stay put.",
           "A **lookahead** lets the limiter see the peak a moment before it arrives and turn down smoothly in time, so it doesn't "
           "have to chop. **Release** is how fast it lets go afterwards: too fast and bass notes distort; too slow and the "
           "song loses life. Most limiters have an automatic release, a good place to start.",
           "Watch the **gain-reduction meter**. It shows how much the limiter turns the song down, moment to moment. "
           "About **1 to 3 dB** is gentle, 4 to 6 dB is loud, and beyond that you can hear the song pumping: the whole mix ducks "
           "on every kick.",
           "A limiter is not the same as **clipping**. Clipping cuts the tops of the peaks off at once, which adds distortion. "
           "A limiter turns the level down around the peak, so it is cleaner at small amounts. Don't stack limiters: two in a row "
           "each push the song, and you get the distortion of both. Use one, last, with the ceiling set once.",
           "`hypnomix master` has a limiter character option, `--limiter-mode clean|punch|loud`. `clean` is the limiter alone. `punch` and `loud` put a clipper in front, so the limiter does less work (its help gives `--clip-db` for the most the limiter may do). Try `clean` first, and compare the modes at the same loudness."],
      terms=[["Ceiling", "the highest level the limiter lets through. -1 dBTP is a sensible start."],
             ["Lookahead", "the limiter looks a moment ahead, so it can turn down smoothly before a peak arrives."],
             ["Release", "how quickly the limiter lets go after a peak. Slower is smoother; faster is louder but can distort bass."],
             ["Gain reduction", "how many dB the limiter turns the signal down. The meter shows it moment to moment."],
             ["Brick-wall limiter", "a limiter with a ceiling that nothing passes."],
             ["True-peak limiting", "a limiter that measures the real wave between samples, so the ceiling holds after conversion."],
             ["Clipping", "cutting the tops of waves off. It adds harmonic distortion and sounds harsher as it increases."]],
      settings=[["Ceiling", "-1 dBTP", "room for encoders and converters"],
                ["Gain reduction (loudest part)", "1-3 dB gentle; 4-6 dB loud", "beyond that you hear pumping and flatness"],
                ["Release", "automatic, or start around 50-200 ms and adjust", "too fast distorts bass; too slow smears the beat"],
                ["Number of limiters", "one, last", "stacked limiters add distortion"]],
      how={"live": ["Audio Effects → **Limiter**, last device on the **Master**. Set the **Ceiling** to -1 dB and raise **Gain** while the loudest part plays.",
                    "Watch its gain-reduction meter. Don't assume it measures true peak: leave -1 dB and check the result with a loudness meter or `hypnomix measure`."],
           "reaper": ["On the master add **ReaLimit** last in the chain. Set its **Ceiling** to -1 dB and lower its **Threshold** while the loudest part plays. Watch its gain-reduction display."],
           "ardour": ["On the master strip add a limiter last in the chain (x42 Digital Peak Limiter, if you have it). Set the ceiling to -1 dB and push it while the loudest part plays. If it has a true-peak mode, switch it on."]},
      listen="Switch between the limiter at 2 dB and at 6 dB of gain reduction, level-matched. Listen for the kick and the vocal ducking together at 6 dB, and for a flatter, less open feel.",
      mistakes=["Going for 8 dB of gain reduction to reach a loudness number: you hear pumping. Lower the target or fix the mix.",
                "Leaving the ceiling at 0 dB: encoders then clip. Set -1 dBTP.",
                "Using a limiter on the master and another on the stereo bus \"to be safe\": one limiter, last."],
      **{"try": dict(do="Put a limiter on your master with the ceiling at -1 dB. Raise its gain until the gain-reduction meter shows about 2 dB at the loudest part. Then raise it to 6 dB, matching the playback level each time.",
                     success="You can hear where the limiter stops being invisible and starts to pump, and you know what that point looks like on its meter.")},
      quiz=[dict(q="What does a limiter's ceiling do?", options=["Sets how loud the song feels on average", "Sets the highest level that gets through", "Sets how bright the song is"], answer=1,
                 why="Nothing passes the ceiling; the gain control sets how hard the song is pushed up to it."),
            dict(q="About how much gain reduction on the loudest part is gentle?", options=["6 to 10 dB", "1 to 3 dB", "More than 12 dB"], answer=1,
                 why="Up to about 3 dB a good limiter is near invisible. Past about 6 dB the pumping starts to show."),
            dict(q="Why not stack two limiters?", options=["The DAW won't allow it", "They cancel each other out", "Each one adds its own distortion and pumping"], answer=2,
                 why="Each stage pushes and squashes the song, and the artefacts add up.")],
      hear=["limiter-clip"],
      more=["step:chain", "step:mst-codec", "step:mst-streaming", "hypnomix master"]),

 dict(id="mst-codec", title="Why a master can clip after MP3 or AAC encoding, and how much ceiling to leave", daws=ALL,
      say=["Streaming and downloads use **lossy** formats such as MP3 and AAC. They save space by throwing away detail you are unlikely "
           "to hear. That changes the wave, and the new wave can have peaks a little higher than the original, so a master "
           "that peaked at 0 dBFS can come out above it and clip.",
           "The fix is room. A true-peak ceiling of **-1 dBTP** is a common safe start. For a loud master (many dB of limiting, "
           "or a clipper in front of it), go to **-1.5 or -2 dBTP**, because a harder-pushed master has more to overshoot.",
           "Don't guess: test with a real encode. `hypnomix translate` has a codec check (MP3 320 and AAC 256, encoded and decoded back) "
           "that reports whether the file clips after encoding. Add `--preview` to write the decoded files so you can hear them and "
           "compare with the original. Re-run it after every change to the limiter: a new render needs a new check.",
           "`hypnomix master` also runs a codec-safe check on its own ceiling: it may lower the ceiling a little (at most 3 dB) and "
           "warns if the encodes still overshoot. The tool proposes, you decide: listen to the result."],
      terms=[["Lossy codec", "a format such as MP3 or AAC that makes the file smaller by discarding detail. It can't be undone."],
             ["AAC", "a common lossy format used by Apple Music, YouTube and others."],
             ["Overshoot", "a peak that comes out higher after encoding than the original was."],
             ["Codec-safe ceiling", "a limiter ceiling low enough that the song still doesn't clip after encoding."]],
      settings=[["Ceiling, most masters", "-1 dBTP", "enough for most songs at normal loudness"],
                ["Ceiling, loud masters", "-1.5 to -2 dBTP", "more limiting and any clipping give the encoder more to overshoot"],
                ["Test files", "MP3 320 and AAC 256", "what `hypnomix translate` checks"]],
      listen="Play the original and the AAC preview back to back, level-matched. Listen for a gritty crackle on the loudest hits in the encoded one: that is clipping from overshoot.",
      mistakes=["Setting the ceiling at -0.1 dB \"to be loud\": the encoder pushes peaks over and the song clips on the service.",
                "Testing the old render after changing the limiter: always export again and run the check on the new file.",
                "Trusting the DAW's peak meter alone after encoding: encode and decode a copy, then measure that."],
      **{"try": dict(do="Run `hypnomix translate your-master.wav --preview` (read `hypnomix translate -h` first). Compare the original and the decoded AAC at the loudest chorus, and read the codec result.",
                     success="You know whether your master clips after encoding, and if it does you have lowered the ceiling and checked a new render.")},
      quiz=[dict(q="Why can a file that peaks at 0 dBFS clip after AAC encoding?", options=["Encoding adds noise", "Encoding changes the wave and its peaks can rise above the original", "AAC always raises the volume"], answer=1,
                 why="Lossy encoding rebuilds an approximation of the wave, and that approximation can overshoot."),
            dict(q="You push a master with 6 dB of limiting. Which ceiling is the safer start?", options=["-0.1 dBTP", "-1 dBTP", "-2 dBTP"], answer=2,
                 why="A harder-pushed master has more overshoot to allow for, so use the extra margin and check with a real encode.")],
      more=["step:deliver", "step:mst-limiter", "step:mst-dither", "hypnomix translate"]),

 dict(id="mst-dither", title="Dither and bit depth at export", daws=ALL,
      say=["When you turn a 24-bit or 32-bit file into 16-bit, the converter has to round every sample to a coarser step. "
           "The rounding error isn't random: it follows the music, and at low levels (a quiet fade-out, the tail of a reverb) it "
           "sounds like a grainy, gritty distortion.",
           "**Dither** adds a tiny amount of random noise before the rounding. That turns the distortion into a very quiet, steady "
           "hiss, which the ear forgives much more easily. **TPDF** (triangular) dither is the safe default.",
           "Three rules. Dither **once**, as the very last step. Dither **only** when reducing the bit depth, for example to 16-bit "
           "for a CD or a distributor that asks for it. And if you are staying at 24-bit, you don't need to add it.",
           "Never dither twice. Dither on top of dither adds noise for no gain, so turn it off on any copy that will be processed again. "
           "`hypnomix master` writes an optional 16-bit/44.1 kHz CD copy (`--cd`) from the unrounded master, so that copy is dithered once. `--dither tpdf|shaped|off` sets the type and applies to every file it writes: the 24-bit master gets a tiny TPDF dither too by default (far below hearing at 24-bit). If you will process or convert that 24-bit file again, run with `--dither off`."],
      terms=[["Bit depth", "how many steps each sample can take. 16-bit has 65,536; 24-bit has over 16 million."],
             ["Dither", "a tiny amount of noise added before rounding to a smaller bit depth, so rounding errors become a quiet hiss instead of distortion."],
             ["TPDF", "triangular probability density function: the standard kind of dither noise. A safe default."],
             ["Noise shaping", "dither that moves the noise to frequencies where hearing is least sensitive. Optional, for quiet and dynamic 16-bit masters."]],
      settings=[["Staying at 24-bit", "no dither needed", "the rounding error is far below hearing"],
                ["Going to 16-bit", "TPDF dither, once, last", "hides rounding distortion in a fade-out"],
                ["Sample-rate conversion", "do it before dither", "dither belongs at the very end"],
                ["A copy you will process again", "dither off", "dither only on the final file"]],
      how={"live": ["File → **Export Audio/Video**. Choose a 16-bit file and set the dither option the dialog offers (triangular if listed). For a 24-bit file leave dither off."],
           "reaper": ["File → **Render**. For a 16-bit file, tick the dither option in the dialog (a noise-shaping option sits next to it). For 24-bit leave it off."],
           "ardour": ["Session → **Export → Export to Audio File(s)**. In the format's settings choose a 16-bit sample format and a dithering type (triangular); for 24-bit choose none."]},
      listen="Turn a quiet fade-out up loud on a 16-bit export with no dither, then with dither. Without: grainy. With: a soft hiss. The demo exaggerates rounding with only 6 bits and has no dither in it: the gritty noise that follows the notes is the kind of distortion dither hides. (Its aliasing example is a different problem; ignore it here.)",
      mistakes=["Dithering on every export, including copies you will master later: dither the final file only.",
                "Dithering twice: once in the master chain and again in the export dialog. Pick one place.",
                "Choosing 16-bit for a file that stays at home: keep 24-bit and convert once, at the end."],
      **{"try": dict(do="Export the last 20 seconds of a song to 16-bit twice, once with dither off and once with TPDF. Turn the volume up on the fade-out of each.",
                     success="You hear grain on the undithered file and a steady hiss on the dithered one, and you know to apply dither only once.")},
      quiz=[dict(q="When do you need to add dither?", options=["On every export", "When reducing to a smaller bit depth, such as 24 to 16", "Never, it only adds noise"], answer=1,
                 why="Dither hides the rounding error of reducing the bit depth. At 24-bit that error is already inaudible."),
            dict(q="How many times should a file be dithered?", options=["Once, as the last step", "Once at every stage", "Twice, for safety"], answer=0,
                 why="Each pass adds noise. Do it at the end and only there.")],
      hear=["bit-depth"],
      more=["step:dig-sample-rate-bits", "step:prepare", "hypnomix master"]),

 dict(id="mst-album", title="Mastering an EP or an album", daws=ALL,
      say=["A set of songs is heard in order, so the question changes. It is no longer \"does this song sound good?\" but "
           "\"do these songs sound like one record?\" Master them all in the **same session**, and listen in the order they will play.",
           "Match two things from song to song. **Level**: set the perceived loudness within about **1 dB** of each other, by ear first and "
           "the meter second. A slow ballad can sit a little lower, and that is fine. **Tone**: if one song is darker or brighter than "
           "its neighbours, nudge it with a gentle EQ move. Keep it consistent without making them identical: variety is part of the record.",
           "Then the spaces. The **gap** between songs sets the pacing: **1 to 3 seconds** is common, shorter after a driving song and "
           "longer after a quiet one. Trim silence at the start, give each song's end a smooth fade or let its tail ring out, and "
           "listen to each join.",
           "The **order** matters too. Open with a song that says who you are. Make the second one strong too: listeners often judge a record by its first two songs. Pace the middle with changes in tempo and mood, and finish with something that feels like an ending. "
           "Run `hypnomix qc` on all the files together and compare their loudness with `hypnomix measure`. Then fill in the metadata for each file: see `step:rel-metadata`."],
      terms=[["Gap", "the silence between two songs on a record. Often 1 to 3 seconds."],
             ["Sequencing", "choosing the order of the songs on a record."],
             ["Tail", "the ring-out at the end of a song, before silence."],
             ["Perceived loudness", "how loud a song feels to the ear, which the meter only estimates."]],
      settings=[["Loudness match between songs", "within about 1 dB (LU) by ear", "so nobody reaches for the volume knob"],
                ["Tone match", "gentle EQ moves, about 1-2 dB", "makes the songs sound like one record"],
                ["Gap between songs", "1-3 seconds", "faster after a driving song, longer after a quiet one"],
                ["Song end", "let the tail ring out, or fade it smoothly", "a cut sounds like a mistake"]],
      listen="Play the end of one song into the start of the next at one volume setting. If you reach for the volume knob or the tone suddenly changes, fix that song.",
      mistakes=["Matching every integrated LUFS number exactly: a ballad that sits 1 dB lower on the meter can feel right. Trust your ears.",
                "Mastering songs one at a time on different days, then wondering why they don't match: do them in one session.",
                "Choosing the order by the date you wrote the songs: choose it by how the record listens."],
      **{"try": dict(do="Take two finished songs. Measure both with `hypnomix measure`, play the end of the first into the start of the second, and adjust one song's level until neither stands out.",
                     success="You can play both back to back at one volume and don't want to touch the knob.")},
      quiz=[dict(q="Songs on one record should be within about how much of each other in perceived loudness?", options=["About 1 dB", "10 dB", "They should be identical on the meter"], answer=0,
                 why="Within about 1 dB the listener won't reach for the volume. The ear decides in the end, not the meter."),
            dict(q="Which is the best way to judge the gaps between songs?", options=["Set them all to exactly 2 seconds", "Listen to each join in order and adjust to the feel", "Remove all gaps"], answer=1,
                 why="1-3 seconds is a good range, but the right gap depends on how the first song ends and the next begins.")],
      more=["step:rel-metadata", "step:deliver", "hypnomix qc", "hypnomix measure"]),

 dict(id="mst-versions", title="Instrumental, a cappella and other versions", daws=ALL,
      say=["Many songs need more than one version. The **instrumental** has no vocals at all. The **TV track** is the same mix with only the lead vocal removed, so the backing "
           "vocals stay in. The **a cappella** is the vocals alone. A **clean** version has any explicit words changed or removed. "
           "Licensing and sync work often ask for them, and so do DJs and singers who want to perform to a track.",
           "Make each version from the project, not from the finished master. Mute or solo the right tracks, then export through the **same master chain** with the same settings, "
           "so the songs sound as if they belong together. Set each version to about the **same loudness** as the main one: "
           "with the vocal gone the song is a little quieter, so raise the limiter's gain until it matches. A cappellas are the exception: "
           "they usually go out lightly processed, peaking safely under 0 dBFS, so check what the person asking wants.",
           "Name the files clearly: \"Song Title (Instrumental).wav\", \"Song Title (TV Track).wav\", \"Song Title (A Cappella).wav\". "
           "Keep the stems for each song in a clearly labelled folder, because sync work sometimes asks for them.",
           "If you only have a finished stereo file, `hypnomix rebalance` can turn the vocals down in it using separation, or with stems you already have. "
           "Its help calls separation imperfect: small moves of 1 to 3 dB are safest, and a rescue like this will never be as clean as a real instrumental from your project. "
           "If a song contains samples, each version carries the same clearance issues. This is not legal advice: check with a qualified person."],
      terms=[["Instrumental", "a version with no vocals at all. (A TV track keeps the backing vocals.)"],
             ["TV track", "the same mix with only the lead vocal removed, so the backing vocals stay in and a show can use it under speech."],
             ["A cappella", "the vocals alone, with no music."],
             ["Clean version", "a version with explicit words changed or removed, for radio and some platforms."],
             ["Stems", "grouped sub-mixes of a song (drums, bass, vocals, other) exported separately."]],
      settings=[["Level of each version", "match the main version's loudness within about 1 dB", "so it sounds like the same record"],
                ["Master chain", "the same settings as the main", "makes the versions consistent"],
                ["File name", "Song Title (Version).wav", "anyone can tell what's inside"],
                ["Rescue with rebalance", "vocals down 1-3 dB at most as a first try", "bigger moves also move leakage and artefacts"]],
      how={"live": ["Mute all the vocal tracks (or solo the ones you want), then File → **Export Audio/Video** with the same master chain active and the settings you used for the main version."],
           "reaper": ["Mute all the vocal tracks, then File → **Render** with the same master chain and the same settings as the main version."],
           "ardour": ["Mute all the vocal tracks, then Session → **Export → Export to Audio File(s)** with the master chain on and the main version's settings."]},
      listen="Play the main version, then the instrumental, at the same volume. They should sit at one loudness, and apart from the missing vocal the instrumental should not sound duller or thinner.",
      mistakes=["Making the instrumental by turning down the vocals' faders a little: the vocals still bleed through. Mute them.",
                "Sending the a cappella with the vocal reverb and delay baked in, or missing, without asking: ask what the person wants.",
                "Letting the instrumental come out several dB quieter: match it to the main version."],
      **{"try": dict(do="Export an instrumental of one of your songs through the same master chain, then play it against the main version at one volume. If the project isn't to hand, run `hypnomix rebalance -h` and read how it treats a stereo file.",
                     success="The instrumental sits at the same loudness as the main version, and it has no vocals in it.")},
      quiz=[dict(q="What is a TV track?", options=["A video of the song", "The a cappella", "The mix with only the lead vocal removed, so the backing vocals stay in"], answer=2,
                 why="It lets a show lay speech over the music while keeping the song's feel."),
            dict(q="When you export an instrumental, where should it sit in loudness?", options=["About the same as the main version", "Well below the main version", "As loud as the limiter allows"], answer=0,
                 why="Consistency across versions makes them usable side by side. Match them by ear and with a meter.")],
      more=["step:mst-album", "step:rel-metadata", "hypnomix rebalance"]),

 dict(id="mst-handoff", title="When to hand it to a mastering engineer", daws=ALL,
      say=["You can master your own songs with the chain in this course. Still, there are good reasons to hand one to someone else. "
           "The release matters a lot. The mix is final and you can't tell what is wrong with it. You don't trust your room or "
           "speakers. Or it is an album, where a second pair of ears on the whole record is valuable.",
           "A mastering engineer usually works in a room and on speakers tuned for exactly this job, and has heard a great many mixes. "
           "They don't fix a bad mix; they help a good one translate.",
           "Send a **24-bit WAV** of the final mix at the project's sample rate, with **no limiter and no master processing**, and "
           "peaks around **-6 dBFS**. If your mix needs a bus compressor to feel right, send one version with it and one without. "
           "Add notes (what you like, what worries you, anything you want kept) and one or two **reference songs**.",
           "Expect the finished files and a short note; some engineers send a preview of a song first. Ask in advance how many revisions are included, "
           "and ask for a revision with specifics (\"the vocal feels too far back in the second chorus\"), not \"make it better\". "
           "If the engineer says the problem is in the mix, take that seriously and go back to the mix. "
           "This is not a sales pitch. If you prefer, or can't afford it, do it yourself with the chain in this course: it is a legitimate way to finish a song."],
      terms=[["Mastering engineer", "a specialist who does the final pass on a mix: tone, loudness, the ceiling, the order of an album and the delivery files."],
             ["Revision", "a request to change the master after the first version is delivered."],
             ["Reference track", "a finished song that you want yours to sit next to. Send one or two with your notes."],
             ["Bus compressor", "a compressor on the whole mix, sometimes part of how a mix feels. Mention it in your notes."]],
      settings=[["File format", "24-bit WAV, project sample rate", "the highest quality you have; no lossy files"],
                ["Peaks", "about -6 dBFS", "headroom for the engineer's processing"],
                ["Master-bus processing", "none (or send two versions)", "the engineer needs an unlimited mix to work with"],
                ["Notes", "a paragraph and one or two references", "tells them what you want kept and what worries you"]],
      listen="Before you send it, listen to the mix once on speakers, once on headphones, and once on your phone. Write down what bothers you on each, in words, and put that in your notes.",
      mistakes=["Sending a file that is already limited and at -0.1 dBFS: the engineer has nothing to work with. Send the unlimited mix.",
                "Sending a mix that is not final, then sending another one: finish the mix first.",
                "Giving no notes: a short paragraph and a reference save a revision."],
      **{"try": dict(do="Prepare a mix as if you were sending it: remove the master limiter, check the peaks sit about -6 dBFS, export a 24-bit WAV, and write a short note with one reference.",
                     success="You have a clean file and a note, and whether or not you send it, you know what you would send.")},
      quiz=[dict(q="What level should the peaks of a mix be when you send it for mastering?", options=["As loud as possible, 0 dBFS", "-20 dBFS", "About -6 dBFS"], answer=2,
                 why="That leaves room for the engineer's processing without being so quiet that the file's detail is lost."),
            dict(q="Should the mix you send have a limiter on the master?", options=["Yes, for safety", "No, send it unlimited", "Only on the vocal"], answer=1,
                 why="A limiter on the mix takes away the dynamics the engineer needs to work with.")],
      more=["step:prepare", "step:mst-album", "mastering"]),
]

ENRICH = {
 "what": {
     "mistakes": ["Trying to fix the mix in mastering: if the vocal is too quiet, go back to the mix. Mastering moves everything at once.",
                  "Mastering a mix that has a limiter on it from mixing: take it off, or you will limit twice.",
                  "Judging the master louder than the mix: turn the mix up to match before you decide."],
     **{"try": dict(do="Pick a finished song you love and play 30 seconds, then 30 seconds of your own mix at the same loudness. Write down two things that differ in tone or width.",
                    success="You have a short list of differences you could name, rather than \"theirs is better\".")},
     "quiz": [dict(q="The vocal is too quiet in your mix. Where do you fix it?", options=["In mastering, with the limiter", "In the mix", "In the export settings"], answer=1,
                   why="Mastering moves the whole mix at once, so it can't raise one part on its own."),
              dict(q="Why does going louder than -14 LUFS buy nothing on most streaming services?", options=["They turn louder songs down", "Louder files cost more to stream", "They add a limiter of their own"], answer=0,
                   why="The service plays your song back at its own reference level, so only the squashing remains.")],
     "more": ["step:mst-streaming", "step:mst-units", "mastering"]},
 "prepare": {
     "mistakes": ["Leaving the limiter on the master from mixing: export without it. Mastering adds its own at the end.",
                  "Exporting a 16-bit file: export 24-bit and convert to 16-bit once, at the end (see the dither lesson).",
                  "Cutting the end off: export through the last ring-out and the silence after it."],
     **{"try": dict(do="Export your mix as a 24-bit WAV from the very start to the end of the last ring-out. Run `hypnomix measure` on it, and read the true peak.",
                    success="The true peak is around -6 dBFS or lower, and the file ends in silence instead of cutting a note.")},
     "quiz": [dict(q="Why export the mix to be mastered at 24-bit?", options=["It plays on more devices", "It makes the file louder", "It keeps fine detail and leaves room before any final conversion"], answer=2,
                   why="Higher resolution means rounding doesn't matter until the very last step. Convert to 16-bit only once, at the end.")],
     "more": ["step:mst-handoff", "step:mst-dither", "step:dig-clipping-headroom"]},
 "chain": {
     "mistakes": ["Adding every device \"just in case\": each should do a small job. If you can't hear it, take it out.",
                  "Boosting the EQ by more than about 1 dB: in mastering big moves are mix problems. Go back to the mix.",
                  "Setting the limiter ceiling at 0 dB: use -1 dBTP so encoders don't clip."],
     **{"try": dict(do="Build the chain on your master (EQ, glue compressor, bass mono, limiter), every gain at 0 dB. Bypass the whole chain on and off at the same loudness.",
                    success="The difference is small and kind: tighter and a bit more solid, nothing obviously changed.")},
     "quiz": [dict(q="Why put the limiter last in the chain?", options=["It makes the other devices louder", "Nothing after it can push the signal over the ceiling", "It needs the most CPU"], answer=1,
                   why="The ceiling only holds if nothing comes after it that can raise the level."),
              dict(q="About how much gain reduction should the glue compressor show on a master?", options=["1 to 3 dB", "6 to 9 dB", "As much as it takes to reach -14 LUFS"], answer=0,
                   why="Glue is small: it holds the mix together without squashing it. Loudness comes from the limiter, last.")],
     "more": ["step:mst-limiter", "step:mst-codec", "mastering"]},
 "loud": {
     "mistakes": ["Judging a louder version as better: it only sounds better for a moment. Match the levels first.",
                  "Matching a reference by turning yours up to its peak level: match integrated loudness, not peaks.",
                  "Chasing the target number with a limiter at 8 dB of gain reduction: lower the target, or fix the mix."],
     **{"try": dict(do="Play your master next to a reference song, level-matched to within 0.5 dB. Listen for the low end, the brightness and how wide it feels, then write down one thing to change.",
                    success="Your note names one specific difference (more low end, less top, narrower) rather than \"louder\".")},
     "quiz": [dict(q="Why match the loudness before comparing two versions?", options=["Louder sounds better at first, so a comparison without matching is unfair", "A DAW can't play two files at once", "Quieter files are always cleaner"], answer=0,
                   why="The ear prefers the louder one almost every time, so a mismatch decides the comparison before you listen to the content.")],
     "hear": ["loudness-bias"],
     "more": ["step:mst-units", "step:mst-streaming", "step:snd-louder-better"]},
 "deliver": {
     "mistakes": ["Skipping the check because it sounded fine in the DAW: encoding and phones can show what your room hides.",
                  "Exporting with only part of the song selected, or with the master chain off: check both before you export.",
                  "Changing the limiter after the check without checking again: check the exact file you deliver."],
     **{"try": dict(do="Run `hypnomix qc` and `hypnomix translate` on your master. Fix anything marked WARN or FAIL, export again, and check the new file.",
                    success="The new file passes, and you have listened to it in mono and on a phone speaker.")},
     "quiz": [dict(q="After you change the limiter, what do you do?", options=["Nothing, the check still holds", "Turn the limiter off", "Export again and run the check on the new file"], answer=2,
                   why="A check describes one file. A new render is a new file and needs its own check.")],
     "more": ["step:mst-codec", "step:mst-album", "hypnomix qc", "hypnomix translate"]},
}
