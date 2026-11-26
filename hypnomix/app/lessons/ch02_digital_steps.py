"""Chapter: Digital audio. Sample rate and bit depth, clipping, buffers, file types, project folders."""
from hypnomix.app.lessons._common import ALL, LR

STEPS = [
 dict(id="dig-sample-rate-bits", title="Sample rate and bit depth", daws=ALL,
      say=["A computer can't store a smooth sound wave, so it measures it many times a second and keeps the numbers. "
           "Each measurement is a **sample**. The **sample rate** is how many samples it takes per second: 44,100 for "
           "CD-style audio (44.1 kHz), 48,000 for most video and many studios (48 kHz). A rate can only capture sounds up "
           "to **half** of itself, called the Nyquist limit: 44.1 kHz reaches about 22 kHz, and 48 kHz reaches 24 kHz. "
           "Human hearing tops out near 20 kHz, so both are enough.",
           "The **bit depth** is how finely each measurement is written down. Think of a ruler: 16 bit has about 65,000 "
           "tick marks, 24 bit has about 16 million. The finer ruler lets very quiet sounds be written down cleanly. "
           "The practical result is the **noise floor**, the faint hiss of rounding error under everything: about 96 dB "
           "below the top at 16 bit, about 144 dB below at 24 bit. At 24 bit that floor is far below any room or microphone, "
           "so you can record at a modest level and never worry about it.",
           "Choose once and leave it. Start the project at 48 kHz (or 44.1 kHz if the song is only going to music "
           "services; either is fine), record and mix at 24 bit, and use 16 bit only when you make a final CD-style file. "
           "Don't change the sample rate in the middle of a project: the DAW has to convert every recording, and the "
           "tempo and timing of existing audio can go wrong. Higher rates such as 96 kHz are not needed to start, and "
           "they make files bigger and the computer work harder for little you can hear."],
      terms=[["Sample", "one measurement of the sound wave. Digital audio is a long list of them."],
             ["Sample rate", "how many samples are taken each second, in kHz. 44.1 kHz and 48 kHz are the usual choices."],
             ["Nyquist limit", "half the sample rate: the highest frequency the rate can capture. 22.05 kHz at 44.1 kHz."],
             ["Bit depth", "how finely each sample is measured. 16 bit and 24 bit are the usual ones."],
             ["Noise floor", "the quiet hiss that is always under a recording. A higher bit depth puts it lower."],
             ["Dither", "a tiny, deliberate noise added when going from 24 bit down to 16 bit, so the rounding sounds smooth instead of gritty. The mastering chapter covers it."]],
      settings=[["Sample rate", "48 kHz (or 44.1 kHz)", "both capture everything you can hear; pick one and keep it for the whole song"],
                ["Bit depth, recording and mixing", "24 bit", "the noise floor is far below anything audible, so you can record with room to spare"],
                ["Bit depth, final CD-style file", "16 bit, with dither", "only the last export, never the working files"],
                ["96 kHz and above", "not needed to start", "bigger files and a heavier load for a difference few people can hear"]],
      how={"live": ["Live's sample rate is the audio device's. Open Live's Settings (called Preferences in Live 11), found under the Live menu on a Mac or the Options menu on Windows. Go to the **Audio** tab and set **Sample Rate**. Set it before you open or start the song.",
                    "The **Record, Warp & Launch** tab of the same window (Record/Warp/Launch in Live 11) has the file type and bit depth for new recordings: choose WAV and 24 bit if they are not already.",
                    "The bit depth of an exported file is chosen in the export window: File → Export Audio/Video."],
           "reaper": ["Open the project's settings (Project → Project settings, or Alt+Enter) and check the project sample rate there; Options → Preferences → Audio → Device holds the interface's own rate.",
                      "The recording format (WAV, 24 bit) is in the same project settings window, in its Media section."],
           "ardour": ["The session's sample rate is chosen when you make it, and the interface's rate is in Window → Audio/MIDI Setup: keep them the same.",
                      "The session's recording format (for example 24 bit) is in the session's properties, under Media."]},
      listen="Play the 'bit depth' demo: a clean sound, the same sound with a low bit depth, and one with aliasing. Low bit depth "
             "sounds grainy and hissy as it fades out. Aliasing adds odd, metallic tones that were never in the music.",
      mistakes=["Changing the sample rate halfway through a song. Pick it before the first recording and leave it.",
                "Recording at 16 bit to 'save space'. Disk space is cheap; a clean 24 bit recording gives you room for mistakes.",
                "Chasing 96 kHz or 192 kHz because bigger sounds better. For a first project it only costs space and speed."],
      **{"try": dict(do="Open your DAW's audio settings and find the sample rate and, for new recordings, the bit depth. Write both down. Then record 10 seconds and check the file's properties.",
                     success="You can say your project's sample rate and bit depth from memory, and the recording shows the same numbers.")},
      quiz=[dict(q="What is the highest frequency a 44.1 kHz sample rate can capture?", options=["About 44 kHz", "About 22 kHz", "About 10 kHz"], answer=1,
                 why="A rate captures up to half of itself (the Nyquist limit), so 44.1 kHz reaches about 22 kHz, just past the top of human hearing."),
            dict(q="When is 16 bit the right choice?", options=["While recording, to save disk space", "While mixing, to keep the computer fast", "Only for a final CD-style export"], answer=2,
                 why="Record and mix at 24 bit. Go down to 16 bit only for the last file, and add dither when you do.")],
      hear=["bit-depth"],
      more=["step:dig-clipping-headroom", "step:dig-file-types", "step:gain"]),

 dict(id="dig-clipping-headroom", title="Clipping and headroom", daws=ALL,
      say=["In a digital system **0 dBFS** is a hard ceiling: the loudest number it can write down. Push a sound past it "
           "and the top of the wave is simply flattened off. That is **digital clipping**. It sounds harsh and buzzy, and "
           "once it is in the recording, it cannot be repaired. No plug-in puts back the peak that was never stored.",
           "Analogue gear overloads more gently. Tape and tubes squash the peaks gradually, and some people like the "
           "result. Digital clipping has no such softness: the wave hits the wall and stops. That is why the habit is "
           "to leave **headroom**, the gap between your loudest peak and 0 dBFS.",
           "While recording at 24 bit, aim for peaks around **-12 to -6 dBFS** on your loudest part. That sounds quiet, but at 24 bit the noise "
           "floor is so low that nothing is lost, and you never come near clipping if the singer suddenly gets louder. "
           "Quieter than that is also safe at 24 bit, so there is no need to chase level. "
           "Watch the meter: if it turns **red**, or a clip indicator lights, a peak has reached the ceiling. Turn the "
           "input gain down and record again.",
           "Inside a DAW the mixing maths is usually **floating-point**, which has an enormous range. A track can go over "
           "0 dB on its own meter without clipping, as long as you turn it down before the output. But the ceiling is "
           "still real at the audio interface, at the master output, at the file you export, and inside many plug-ins "
           "and converters, which can clip even when the track is fine. Keep each track's peaks sensible anyway."],
      terms=[["dBFS", "decibels relative to full scale: the digital loudness scale. 0 dBFS is the top; every other level is negative."],
             ["Digital clipping", "flattening of a peak at 0 dBFS, because the system can't store anything louder. Harsh, and permanent."],
             ["Headroom", "the space between your loudest peak and 0 dBFS."],
             ["Peak", "the highest point a sound reaches. Meters show peaks."],
             ["Floating point", "a number format with a huge range, used inside a DAW's mixer. An over on one track won't clip until the output, but plug-ins and converters can still clip."]],
      settings=[["Recording peaks (24 bit)", "-12 to -6 dBFS", "far from the ceiling, and the noise floor is still far below the sound"],
                ["Track peaks while mixing", "below about -6 dBFS", "leaves room for plug-ins and for the sum of all tracks"],
                ["Master peaks before mastering", "-6 dBFS or lower", "the mastering stage needs room to work"]],
      listen="Play the 'limiter-clip' demo, which sets hard clipping against a limiter at the same loudness. Hard clipping adds a "
             "crackly, gritty edge; the limiter stays smooth. Then check your own recording for that edge on its loudest notes.",
      mistakes=["Recording as hot as possible 'to get a strong signal'. At 24 bit that gains nothing and risks clipping the first loud note.",
                "Setting the level on the quiet verse. Set it on the loudest part of the song, then check the quiet part still sounds fine.",
                "Ignoring a red light because 'it's only for a moment'. A single flattened peak can be heard, and it stays in the file.",
                "Believing a track meter that goes over 0 is always safe inside the DAW. It may be fine on the track and clip at a plug-in or the master."],
      **{"try": dict(do="Arm a track and sing or play your loudest part at full effort while you watch the meter. Adjust the input gain until the loudest peaks sit between -12 and -6 dBFS.",
                     success="The meter never turns red on the loudest part, and the recording still sounds clear, not thin.")},
      quiz=[dict(q="What happens to a peak that hits 0 dBFS during recording?", options=["The DAW lowers it automatically", "The top of the wave is flattened and can't be repaired", "It is saved and can be restored with a plug-in"], answer=1,
                 why="Digital clipping throws the peak away. There is nothing stored to restore."),
            dict(q="Why can you record at -18 dBFS at 24 bit without worry?", options=["The noise floor is still far below the sound", "Quiet recordings sound warmer", "The meter reads wrongly at low levels"], answer=0,
                 why="At 24 bit the noise floor sits near -144 dBFS, so a -18 dBFS recording is still far above it, with plenty of headroom."),
            dict(q="A track's meter goes over 0 dB inside a DAW. What is true?", options=["It has certainly clipped", "It may be fine on the track, but the output, plug-ins and converters can still clip", "It can never matter"], answer=1,
                 why="Floating-point mixing gives the track a huge range, but the ceiling returns at plug-ins that clip, the interface and the exported file.")],
      hear=["limiter-clip"],
      more=["step:dig-sample-rate-bits", "step:gain", "step:loud"]),

 dict(id="dig-buffer-latency", title="Buffer size and latency", daws=ALL,
      say=["Your computer can't process sound one sample at a time. It collects a small batch, called the **buffer**, "
           "works on it, and then sends it on. The buffer size is counted in samples: 64, 128, 256, 512, 1024.",
           "The wait that causes is **latency**. Divide the buffer by the sample rate: 128 samples at 48 kHz is about "
           "2.7 milliseconds. A small buffer means little delay, but the computer has less time per batch, so a busy "
           "project can crackle or drop out. A big buffer gives the computer plenty of time, but the delay gets longer.",
           "What you feel when recording is **round-trip latency**: the time from sound going into the interface, through "
           "the buffer, through the computer and back out to your headphones. It is more than the buffer alone, because "
           "the converters and the driver add their own. Up to about 10 ms feels live; much more and singing against "
           "yourself becomes awkward.",
           "So change the buffer to suit the job. **Recording**: small, around 64 to 128 samples, so you hear yourself "
           "with no delay. **Mixing**: large, 512 to 1024 samples or more, because nothing is live and plug-ins need "
           "the headroom. Recorded audio is placed correctly on the timeline whatever the buffer was, so changing it "
           "does not hurt your take."],
      terms=[["Buffer", "the small batch of samples the computer processes at once. Measured in samples."],
             ["Latency", "the delay between a sound going in and coming out. Roughly buffer divided by sample rate."],
             ["Round-trip latency", "the full delay from input to headphones, including the converters and the driver."],
             ["Dropout", "a crackle or gap when the computer can't keep up with a small buffer."],
             ["Driver", "the program that lets the DAW talk to your interface."]],
      settings=[["Buffer when recording", "64-128 samples", "about 1.3-2.7 ms each way at 48 kHz (plus the converters and driver): you hear yourself without a noticeable delay"],
                ["Buffer when mixing", "512-1024+ samples", "gives the computer time, so large projects stay clean"],
                ["If you hear crackles", "raise the buffer one step", "the computer needs more time per batch"],
                ["If recording feels late", "lower the buffer one step", "less delay, at the cost of more load"]],
      how={"live": ["Open Live's Settings (Preferences in Live 11), under the Live menu on a Mac or the Options menu on Windows, and go to the **Audio** tab.",
                    "Choose your interface as the Audio Device, then change **Buffer Size**. On Windows with an ASIO driver, click **Hardware Setup** and set the buffer in the interface's own control panel instead. Live shows the resulting input and output latency beneath it.",
                    "Close the window and play: crackles mean raise it; a late-feeling take means lower it."],
           "reaper": ["Open Options → Preferences → Audio → Device.",
                      "Choose your interface, and set the block size (buffer) the driver offers; the same page reports the resulting latency.",
                      "Click Apply, then play your project to test it."],
           "ardour": ["Open Window → Audio/MIDI Setup.",
                      "Choose your interface and set the **Buffer size** (and the sample rate).",
                      "Apply or Start, then play to test: crackles mean raise it."]},
      listen="First make sure you are hearing yourself through the DAW (the track armed and the DAW's input monitoring on), with your interface's direct-monitor switch off. Then record a clap against the click with a very large buffer, then a small one. With the large buffer you hear a clear "
             "gap between your clap and its echo in the headphones; with the small buffer it feels immediate.",
      mistakes=["Mixing with the recording buffer. A busy project then crackles; raise the buffer when you move to mixing.",
                "Recording with a 1024-sample buffer and fighting the delay in your headphones. Drop to 128 or lower first.",
                "Blaming the plug-ins for crackles when the buffer is simply too small for the project."],
      **{"try": dict(do="Set the buffer to 512, play your project, then drop it to 64 and play again. Note the latency your DAW reports each time, and compute buffer divided by sample rate to check it.",
                     success="You can say what the latency is at each size, and which setting you will use for recording and which for mixing.")},
      quiz=[dict(q="Roughly how much delay is a 128-sample buffer at 48 kHz?", options=["About 0.3 ms", "About 2.7 ms", "About 27 ms"], answer=1,
                 why="128 divided by 48,000 is about 0.0027 seconds, or 2.7 milliseconds, each way."),
            dict(q="Which buffer suits mixing a big project?", options=["64 samples", "128 samples", "512 to 1024 samples or more"], answer=2,
                 why="Nothing is live while mixing, so a large buffer costs you nothing and keeps the computer from crackling."),
            dict(q="You hear crackles in playback with a 64-sample buffer. What do you try first?", options=["Raise the buffer a step", "Lower the sample rate to 22 kHz", "Turn the volume down"], answer=0,
                 why="The computer isn't getting enough time per batch. A larger buffer gives it that time.")],
      more=["step:dig-sample-rate-bits", "step:words-audio-settings", "step:rec-monitoring"]),

 dict(id="dig-file-types", title="File types: WAV, AIFF, FLAC, MP3 and AAC", daws=ALL,
      say=["Audio files come in three families. **Uncompressed** files (WAV and AIFF) hold every sample exactly, "
           "so they are big. **Lossless** files (FLAC) are squeezed like a zip file: smaller, but when opened they are "
           "bit-for-bit identical to the original. **Lossy** files (MP3 and AAC) throw away detail the codec judges you won't "
           "notice, so they are small but can never be restored.",
           "Use each where it fits. **Recording and mixing**: WAV (or AIFF, which is equivalent), 24 bit. **Archiving** a "
           "finished song: WAV, or FLAC to save space. **Sending a quick preview** by message or email: MP3 or AAC, because "
           "it is small. **Uploading** to a service: the service tells you what it accepts; a 16 or 24 bit WAV is the usual "
           "safe choice.",
           "Never mix from MP3s. Each time a file is encoded to MP3 or AAC it loses a little, and the damage builds if you "
           "mix, export, encode and mix again. Always keep the WAV originals. Encode to a lossy format only as the very "
           "last step, and keep the WAV master.",
           "One more thing for later: encoding to MP3 or AAC can make the peaks a little higher than they were in the "
           "WAV, so a master that just touched 0 dBFS can clip afterwards. The mastering chapter shows how to leave room for that."],
      terms=[["WAV", "the standard uncompressed audio file. Big, exact, and read everywhere."],
             ["AIFF", "an uncompressed file much like WAV, common on Macs. Same quality."],
             ["FLAC", "a lossless compressed file. Smaller than WAV, and identical to it when opened."],
             ["MP3", "a lossy compressed file. Small, with some detail permanently removed."],
             ["AAC", "a lossy compressed file, usually a bit cleaner than MP3 at the same size. Used by many streaming services."],
             ["Lossless", "compression that loses nothing: the original can be rebuilt exactly."],
             ["Lossy", "compression that throws detail away for good."],
             ["Codec", "the method used to encode and decode a file, such as MP3 or FLAC."]],
      settings=[["Recording and mixing", "WAV, 24 bit", "exact, with the most room for processing"],
                ["Archive of the finished song", "WAV, or FLAC", "FLAC saves space and loses nothing"],
                ["Quick preview by message", "MP3 or AAC", "small enough to send; never use it to mix"],
                ["Upload to a service", "the format the service asks for; otherwise a WAV", "the service converts it itself, so give it the cleanest source"]],
      listen="Take one finished song and export both a WAV and a low-quality MP3. Play the MP3 through headphones: listen to the "
             "cymbals and reverb tails, where a lossy encode usually leaves a watery, smeared sound.",
      mistakes=["Throwing away the WAVs after making an MP3. The MP3 can't be turned back into the original.",
                "Re-importing an MP3 into a project to remix it. Go back to the originals.",
                "Sending a file with no way to tell versions apart. Name previews with the version, such as 'Song v3 preview.mp3'."],
      **{"try": dict(do="Export one song as a 24 bit WAV and as an MP3. Compare the two file sizes, then listen to the MP3's reverb tail and the WAV's.",
                     success="You can say how much smaller the MP3 is and point to one detail it changed, and you've kept the WAV safe.")},
      quiz=[dict(q="Which of these keeps every sample exactly and is also smaller than a WAV?", options=["MP3", "FLAC", "AAC"], answer=1,
                 why="FLAC is lossless compression: it opens back into the identical audio. MP3 and AAC are lossy."),
            dict(q="When should you encode an MP3?", options=["Before mixing, to save space", "In the middle of mixing", "Only as the final step, keeping the WAV"], answer=2,
                 why="Encoding loses detail permanently, so it comes last, and the WAV stays as your master."),
            dict(q="Which file is the right one to record and mix with?", options=["A 320 kbps MP3", "A 24 bit WAV", "An AAC file"], answer=1,
                 why="Recording and mixing want uncompressed audio at 24 bit: nothing is lost before you start.")],
      more=["step:dig-sample-rate-bits", "step:dig-project-files", "step:deliver"]),

 dict(id="dig-project-files", title="Project folders, saving, backups and versions", daws=ALL,
      say=["Keep **one folder for each song**. Inside it live the project file and all its recordings. If everything is in "
           "one place, you can copy, move or back up the song without losing a single sample. If a project points at "
           "recordings scattered across the computer, moving it breaks it.",
           "Make your DAW keep the audio **inside the project**. Each DAW has a command that copies every recording the "
           "song uses into its own folder. Use it before you move the song or send it to someone.",
           "Save often, and save **versions**. A version is a new file you keep, not an overwrite: 'Song v1', 'Song v2', 'Song v3'. "
           "Add a short note when it means something: 'Song v4 vocal comp'. If a change goes wrong, you can go back to the "
           "last good one. Version when you start a new stage, before a big change, and at the end of a work session.",
           "For backups, use the **3-2-1 rule**: keep **three** copies of the song, on **two** different kinds of storage "
           "(your computer and an external drive), with **one** copy somewhere else (a cloud folder, or a drive at another "
           "address). A drive that breaks takes everything on it, so the second copy has to be somewhere different. "
           "hypnomix only ever writes new files and never replaces your original, so your versions stay safe."],
      terms=[["Project folder", "the one folder that holds a song's project file and every recording it uses."],
             ["Collect and save", "copying every recording the song uses into the project folder, so the song stands alone."],
             ["Version", "a separate saved copy of the project at one moment, such as 'Song v2', that you can go back to."],
             ["Backup", "an extra copy kept in case the first is lost or damaged."],
             ["3-2-1 rule", "three copies, on two kinds of storage, with one held somewhere else."]],
      settings=[["Folder per song", "one folder, named with the song", "everything for the song in one place"],
                ["Version names", "Song v1, Song v2, Song v3, with an optional note", "a plain running number you can sort and go back to"],
                ["When to save a new version", "start of a stage, before a big change, end of the day", "gives you a safe place to return to"],
                ["Backups", "3 copies, 2 kinds of storage, 1 somewhere else", "survives a broken drive, a theft or a fire"]],
      how={"live": ["Open File → **Collect All and Save** to copy every recording the Set uses into its folder.",
                    "For a new version, use File → Save Live Set As... and give it the next name, such as Song v2."],
           "reaper": ["Use File → **Save project as...** and give it the next version name.",
                      "In the Save dialog, choose the option to copy all media into the project directory, if it is offered, so the project is self-contained."],
           "ardour": ["Use the Session menu's Save As and Snapshot commands to keep a numbered version.",
                      "An Ardour session is already a folder with its recordings inside, so copy that whole folder when you back up."]},
      listen="After copying the song to a second drive, open the copy from there and play it. Every clip should play, "
             "with no missing-file messages.",
      mistakes=["Saving only over the same file. One bad edit or crash and the earlier work is gone; save versions.",
                "Backing up to a second partition of the same drive. If the drive fails, both copies go. Use a separate drive.",
                "Leaving recordings in a Downloads folder or on the desktop, so the project can't find them after a move. Collect them into the project."],
      **{"try": dict(do="Pick one song. Use your DAW's collect or copy-media command, save it as 'Song v1', then copy the whole folder to an external drive and open it from there.",
                     success="The copy opens and plays completely, and you have one version saved and one copy on another drive.")},
      quiz=[dict(q="What does the 3-2-1 backup rule ask for?", options=["Three copies, on two kinds of storage, one held somewhere else", "Three drives, two cables, one computer", "Save three times a day, in two places, with one version"], answer=0,
                 why="Three copies, two kinds of storage, and one copy somewhere else, so one failure or one disaster can't take everything."),
            dict(q="You want to try a risky edit on your vocal. What do you do first?", options=["Make it, and undo it if it goes wrong", "Save a new version, such as 'Song v5', then edit", "Delete the old files to save space"], answer=1,
                 why="A saved version is a place you can always return to, even after a crash or a long chain of edits.")],
      more=["step:dig-file-types", "step:daw", "what"]),
]

ENRICH = {}
