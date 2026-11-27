"""Releasing: the files, the metadata, the cover art, the distributor, copyright and splits, and the archive. Steps are added to the chapter that sets the course."""
from hypnomix.app.lessons._common import ALL

STEPS = [
 dict(id="rel-files", title="The files you need", daws=ALL,
      say=["Releasing a song takes more than the song. Before you start, collect a small set of files in one folder: "
           "the **master** (the finished, mastered song as a WAV), an **MP3** for sending a preview to a friend or a playlist "
           "curator, the **instrumental** (the same master without the vocal), a **lyric sheet** as plain text, and the **cover art**.",
           "Ask your distributor what format it wants for the master. Most want a **16-bit / 44.1 kHz WAV**; many also take "
           "**24-bit** WAV at your session's sample rate. If the distributor says one thing and this lesson says another, follow the distributor. "
           "Do not send an MP3 as the master: it has already thrown away some of the sound, and the service will encode it again.",
           "Keep the **mix** and the **master** as separate files in separate folders. If you later need a different master "
           "(a quieter one for vinyl, say), you go back to the mix. Name every file the same way: "
           "`Artist - Title (Master).wav`, `Artist - Title (Instrumental).wav`, `Artist - Title (Preview).mp3`. A name with the artist, the title and "
           "the version tells you what the file is in two years' time.",
           "Before you send anything, run `hypnomix qc` on the master. Its help describes it as the release checks a mastering engineer runs "
           "before a file goes to a distributor: PASS, WARN or FAIL per check, and it exits with code 1 if anything fails. "
           "You pass it the file, and you can give a loudness target with `--target` or a destination with `--for streaming`, `--for cd` or `--for vinyl`. "
           "Run `hypnomix qc -h` to see the options. HypnoMix proposes, you decide: it only reads the file and writes nothing over your original."],
      terms=[["Master", "the finished, mastered stereo file you release. Keep it apart from the mix."],
             ["Instrumental", "the song with no vocals at all. Used for playlists, videos, and as a backup if someone wants to sing over it."],
             ["Lyric sheet", "the words of the song as plain text, checked for spelling."],
             ["Preview", "a small MP3 of the song for sharing before release. Never the file you deliver."]],
      settings=[["Master WAV", "16-bit / 44.1 kHz, or 24-bit at your session's sample rate: whichever the distributor asks for", "most services accept both; the distributor's page is the rule"],
                ["Preview MP3", "320 kbps, or 256 kbps if the file must be small", "good enough to judge the song; small enough to send"],
                ["Instrumental", "same length, same start point and the same master chain as the full master", "it lines up exactly with the full version"],
                ["File names", "Artist - Title (Master).wav", "the same pattern for every file, so nothing is mistaken for another version"],
                ["Folder", "one release folder with Master, Instrumental, Preview, Art and Lyrics inside", "everything in one place when you upload"]],
      how={"live": ["File → **Export Audio/Video**: Rendered Track **Master**, the whole song selected, WAV, with the bit depth and sample rate the distributor asks for.",
                    "For the instrumental, mute the vocal tracks and export again with a new file name."],
           "reaper": ["File → **Render**: Source **Master mix**, Bounds **Entire project**, WAV, the bit depth and sample rate the distributor asks for.",
                      "For the instrumental, mute the vocal tracks and render again with a new file name."],
           "ardour": ["Session → Export → **Export to Audio File(s)**: WAV, the bit depth and sample rate the distributor asks for.",
                      "For the instrumental, mute the vocal tracks and export again with a new file name."]},
      listen="Play the final files once from start to end, in the order you will deliver them. Listen for an early cut-off, a missing "
             "ring-out, or the vocal still audible in the instrumental.",
      mistakes=["Sending the mix instead of the master (or an old master). Name the final file with (Master) and move older ones to an Old folder.",
                "Sending an MP3 as the master. Always send WAV; the MP3 is only for previews.",
                "A master that starts or ends mid-sound. Export from the very start to the end of the last ring-out, and listen to both ends."],
      **{"try": dict(do="Make a release folder for one finished song. Export the master WAV in the format your chosen distributor asks for, a 320 kbps MP3 preview and an instrumental, "
                        "and name them with the `Artist - Title (Version)` pattern. Run `hypnomix qc` on the master and read each line of its report.",
                     success="The folder holds one master, one instrumental and one preview with matching names, and you can say what each line of the qc report means.")},
      quiz=[dict(q="Which file should you deliver to a distributor as the song itself?", options=["The master as a WAV", "A 128 kbps MP3 of the mix", "The session file"], answer=0,
                 why="A distributor wants the finished master in a lossless format. An MP3 is for previews, and the session file is for you."),
            dict(q="Why keep the mix and the master as separate files?", options=["It saves disk space", "So you can make another master later without a mix that was already processed", "Distributors require two folders"], answer=1,
                 why="The mix is the source for every future master. If you overwrite it with the master, you can never go back.")],
      more=["step:deliver", "step:dig-file-types", "hypnomix qc"]),

 dict(id="rel-metadata", title="Titles, credits and other metadata", daws=ALL,
      say=["**Metadata** is the information that travels with a song: the title, the artist, who wrote it and who played on it. "
           "Services, playlists, search and royalty reports all use it. A typo or an inconsistent name can send your credit and your money to the wrong place.",
           "Gather it before you upload, in one text file: **title**, **artist**, **album** (or single), **track number**, **year**, **genre**, "
           "**songwriters**, **producers**, **performers**, **language** and the **explicit** flag (yes if the lyrics contain strong language). "
           "Spell every name the same way each time, and use the **same artist name** on every platform; a second spelling creates a second artist page.",
           "**Credits matter for being paid.** Royalties are paid to the people named against a recording. If a co-writer or the producer is missing "
           "or misspelt, nobody can tell who to pay. Write down real names and roles now, with the agreed shares (see the copyright step).",
           "Two codes you will meet. An **ISRC** is a code that identifies one recording. Your distributor, or a national agency, issues it; it belongs "
           "to that recording and does not change, even if you move to another distributor or re-release the song. A **UPC** (a barcode number) "
           "identifies the release as a whole, a single or an album. Do not invent codes, and do not reuse one from another song: ask your distributor for them."],
      terms=[["Metadata", "the information that goes with a song: title, artist, credits, codes."],
             ["ISRC", "the code that identifies one recording. Issued to you by your distributor or a national agency; it stays with that recording for good."],
             ["UPC", "the barcode number that identifies a whole release (a single or an album)."],
             ["Credits", "the list of who wrote, produced and performed a song, and in what role."],
             ["Explicit flag", "the mark that tells services the lyrics contain strong language."]],
      settings=[["Title and artist", "typed exactly as you want them shown, the same on every upload", "a second spelling creates a second artist page or a split report"],
                ["Songwriters, producers, performers", "full legal names, with roles", "the credits decide who is paid"],
                ["Genre", "one main genre, one optional second", "used for playlists and search"],
                ["Language", "the language of the lyrics (or instrumental)", "services route and label by language"],
                ["Explicit flag", "yes if there is strong language; no if there is not", "labelling it wrongly can get a release held or removed"],
                ["ISRC", "one per recording, from your distributor or national agency", "never invent one; it is how plays and money find your song"]],
      listen="Read the whole metadata file out loud, slowly, as if you were reading it to someone checking it against a form. Typos jump out when you hear them.",
      mistakes=["Writing the artist name three ways across three platforms. Pick one spelling and copy it every time.",
                "Leaving a co-writer or producer off the credits to save time. Add everyone now; fixing credits after release is slow.",
                "Making up an ISRC or UPC. Always use codes issued to you."],
      **{"try": dict(do="Write a plain text file for one finished song with the title, artist, album or single, track number, year, genre, songwriters, producers, performers, language and explicit flag. "
                        "Add the codes if your distributor has given you them.",
                     success="Every field is filled, every name is spelt exactly as you want it published, and a friend can read it and tell who made the song.")},
      quiz=[dict(q="What does an ISRC identify?", options=["One recording, for good", "The whole album", "The artist's account"], answer=0,
                 why="An ISRC belongs to one recording and does not change when you move distributor or release it again. A UPC is the code for the release."),
            dict(q="Why use the same artist name on every platform?", options=["It saves typing", "Services reject long names", "Different spellings can create separate artist pages and misdirect credits and royalties"], answer=2,
                 why="Services match names as text. A different spelling is a different artist to them.")],
      more=["step:rel-files", "step:rel-copyright"]),

 dict(id="rel-cover-art", title="Cover art sizes", daws=ALL,
      say=["The **cover art** is the first thing a listener sees, usually as a small square next to your song. It has to look good at that "
           "small size, and it has to meet the services' rules, or the upload is refused.",
           "The common target is a **square image, 3000 × 3000 pixels**. Many services accept less, but at least **1400 × 1400 pixels** is the usual minimum, "
           "so make the largest square you can and shrink it if needed. Use **RGB** colour (not CMYK) and save as **JPG** or **PNG**. "
           "Specifications change, so check your distributor's current specification before you finish the art.",
           "Rules of thumb: no blurry or stretched art (start from a big enough picture, never enlarge a small one); no web addresses, prices, "
           "social handles or the logos of other companies on the picture; keep the title and artist readable when the image is the size of a thumbnail on a phone. "
           "Do not use other people's photos or artwork unless you have the right to: that needs clearance, and it is not legal advice here, so ask a qualified person if unsure."],
      terms=[["Cover art", "the square picture that represents a song or release on services and stores."],
             ["Pixel", "one dot of an image. 3000 × 3000 means 3000 dots across and 3000 dots down."],
             ["RGB", "the colour mode of screens: red, green, blue. The right mode for cover art, unlike CMYK, which is for print."]],
      settings=[["Shape", "square, 1:1", "services crop or refuse anything else"],
                ["Size", "3000 × 3000 px (never less than 1400 × 1400 px)", "the common target; many services refuse smaller"],
                ["Colour mode", "RGB", "screens use RGB; CMYK can look dull or be rejected"],
                ["File type", "JPG or PNG", "the two formats services accept"],
                ["Text", "large and short: title and artist only", "it must be readable at a thumbnail"],
                ["Content", "no URLs, prices, or other companies' logos", "services reject them"]],
      listen="Shrink the image to about the size of a stamp on your screen. If you can still read the title and tell what the picture is, it will work on a phone.",
      mistakes=["Enlarging a small image to reach 3000 px: it comes out blurry. Start with a bigger original.",
                "Saving in CMYK or leaving a border on the edge. Export as RGB, with the art filling the whole square.",
                "Putting a lot of small text on it. Small text turns to noise at thumbnail size."],
      **{"try": dict(do="Make or open a square cover image. Export it at 3000 × 3000 px in RGB as a JPG. Then view it at about 100 px wide on your screen.",
                     success="At 100 px you can still read the title and recognise the picture, and the exported file is exactly square at the size you chose.")},
      quiz=[dict(q="What is the common size target for cover art?", options=["1000 × 500 px", "A4 at 300 dpi", "3000 × 3000 px"], answer=2,
                 why="A 3000 × 3000 px square is the common target, with 1400 × 1400 px as a frequent minimum. Always check your distributor's current specification."),
            dict(q="Which of these should not be on cover art?", options=["A web address or another company's logo", "The artist name", "A photo you took yourself"], answer=0,
                 why="Services commonly refuse art with web addresses, prices and other companies' logos.")],
      more=["step:rel-files", "step:rel-distributor"]),

 dict(id="rel-distributor", title="What a distributor does", daws=ALL,
      say=["A **distributor** is the company that puts your song into the streaming services and the online stores for you. You upload the master, "
           "the cover art and the metadata; it delivers them in the form each service wants, collects the money the services pay, and passes it to you. "
           "It takes a **fee**, a **share** of the money, or both. You keep your masters: a distributor is delivering your recording, not buying it.",
           "Choosing one is a comparison, not a ranking. Look at: the **fees** (a yearly charge, a per-release charge, a share of royalties); the "
           "**payouts** (how often, the minimum, and how you are paid); **splits support** (can it pay your co-writers directly, if you have them?); "
           "and **speed** (how long delivery takes). Read the terms yourself: what happens to your releases if you leave, and what happens if you stop paying. "
           "Terms change, so look again before every release.",
           "Plan the **lead time**. Allow at least a week, and ideally two or more, before your release day. That time lets the services check the files, and "
           "lets you submit the song to playlist editors (many services have a pitch form that must be filled before release). A **pre-save** link lets fans "
           "ask the service to add the song to their library on the day it comes out."],
      terms=[["Distributor", "a company that delivers your song to streaming services and stores and collects the money."],
             ["Royalties", "the money paid when a song is played or sold."],
             ["Payout", "the money the distributor pays you, usually monthly or quarterly."],
             ["Lead time", "the time between uploading a release and its release day."],
             ["Pre-save", "a link that lets fans ask a service to add your song to their library the moment it is released."]],
      settings=[["Lead time", "upload at least 1 week before release day; 2 or more is better", "services check files, and you need time to pitch for playlists"],
                ["Fees", "compare yearly, per-release and per-royalty-share charges", "the cheapest sticker price is not always the cheapest overall"],
                ["Payouts", "note the schedule, the minimum and the method", "so you know when and how you get paid"],
                ["Splits support", "check if it can pay co-writers directly", "saves you doing the sums by hand"],
                ["Terms", "read what happens if you leave or stop paying", "your releases could be taken down"]],
      listen="Read the terms page out loud once, slowly, and write down every sentence that mentions fees, ownership or removal. If a sentence says the distributor owns your recording, stop and ask.",
      mistakes=["Uploading on the day you want it released. Services need time to check; plan at least a week.",
                "Choosing by headline price alone. Compare fees, share of money, payouts and what happens if you leave.",
                "Not reading the terms. A distributor should not take ownership of your recording; if it appears to, ask a qualified person."],
      **{"try": dict(do="Pick three distributors and write a four-row table: fee, share, payout schedule, splits support. Fill it from each one's own page.",
                     success="You can say which one fits your situation and why, from facts you read yourself, not from what anyone told you.")},
      quiz=[dict(q="What does a distributor do?", options=["Owns your songs and sells them", "Mixes and masters the song", "Delivers your song to services, collects the money and takes a fee or a share"], answer=2,
                 why="A distributor delivers and collects. You keep your masters."),
            dict(q="How much lead time is a sensible minimum before release day?", options=["None", "At least about a week, and more if you want to pitch to playlists", "Six months"], answer=1,
                 why="Services check files and you may want time to pitch. One week is a minimum; two or more is better.")],
      more=["step:rel-metadata", "step:rel-copyright"]),

 dict(id="rel-copyright", title="Copyright, splits and samples", daws=ALL,
      say=["This is plain-words background, not legal advice; check with a qualified person for your situation.",
           "In most countries **copyright** arises when you make the song: you do not have to register it. There are two things in a recorded song, "
           "and each has its own copyright. The **song** (the composition: melody and words) belongs to the writers. The **recording** (the master: this particular performance) "
           "belongs to whoever made it, often the artist or the producer who paid for it. Two people can own the two halves.",
           "**Splits** are the agreed shares of who owns what. Agree them **in writing before release**: who wrote what, who produced, who gets what share of the song and the recording. "
           "A short email that everyone replies 'agreed' to is better than a memory. Disagreements after a song earns money are the most common and the most avoidable problem.",
           "**Cover songs** (someone else's song, recorded by you) usually need a licence, often from the writers or their publisher (a 'mechanical licence' in some places). The rules differ by country and some distributors can arrange it, so check yours and ask a qualified person if unsure. **Samples** (a piece of someone else's recording) need clearance of **both** the recording and the song. "
           "**Royalty-free loops** and sample packs are not free of rules: read the licence for what you may do (usually it covers using them in a song, not reselling them as loops). "
           "A **collecting society** in your country collects some royalties for writers, and you register with it as a writer; ask your distributor or look up the society for your country."],
      terms=[["Copyright", "the legal right of the maker of a song or a recording to decide how it is copied, shared and sold."],
             ["Composition", "the song itself: its melody and lyrics, apart from any one recording."],
             ["Split", "the agreed share of ownership or income that each person gets."],
             ["Cover song", "your recording of a song someone else wrote. It usually needs a licence."],
             ["Sample", "a piece of an existing recording used in a new song. It needs clearance."],
             ["Clearance", "permission, usually written, from the owners of a recording and a song to use them."],
             ["Collecting society", "an organisation that collects royalties for its members, in general from public performances and broadcasts."]],
      settings=[["Splits", "agreed in writing before release", "avoids disputes once money arrives"],
                ["Cover songs", "get any licence you need before you release", "releasing without one can get the song removed"],
                ["Samples", "clearance for both the recording and the song", "each has a different owner"],
                ["Royalty-free loops", "read the licence for what you may do", "'free' rarely means 'unlimited'"],
                ["Collecting society", "register as a writer in your own country", "so writer royalties can reach you"]],
      listen="Before sending a release, read your own splits note as if you were a co-writer who was not in the room. Does it say clearly who gets what?",
      mistakes=["Leaving splits to 'sort out later'. Write them down before release, while everyone is still friends.",
                "Assuming a sample is fine because it is only a few seconds. Short does not mean cleared.",
                "Assuming royalty-free means free for everything. Read the licence."],
      **{"try": dict(do="Write a half-page splits note for one song: the people, their roles, the share of the song and the share of the recording for each, and the date. Send it to everyone who worked on it and ask for a reply.",
                     success="Every person has replied agreed, and the percentages for the song and for the recording each add up to 100.")},
      quiz=[dict(q="What are the two copyrights in a recorded song?", options=["Audio and video", "The song (composition) and the recording (master)", "Mix and master"], answer=1,
                 why="The song belongs to the writers; the recording to whoever made it. They can have different owners."),
            dict(q="What does a sample need before release?", options=["Clearance of both the recording and the song", "Nothing if it is under ten seconds", "Only the artist's permission"], answer=0,
                 why="A sample uses someone's recording and someone's song, and each has its own owner."),
            dict(q="When should splits be agreed?", options=["After the first payment", "Only if there is a dispute", "In writing, before release"], answer=2,
                 why="Agreed in writing before money arrives, splits stop most disputes.")],
      more=["step:rel-metadata", "step:rel-distributor"]),

 dict(id="rel-archive", title="Archiving the project and stems so you can open it in ten years", daws=ALL,
      say=["A song is not finished when it is released. In a few years, the plug-ins, the DAW version, even the computer may have changed, and the project may not "
           "open. An **archive** is a copy of the song kept so you can always come back to it: to remix it, make an instrumental, or fix a mistake.",
           "First, **collect all the media into the project folder** so the project does not depend on audio files scattered around your disk. "
           "Then **bounce stems**: a WAV of every track, each starting at the same point (usually the very start of the project), at **24-bit**. Stems open in any DAW, forever. "
           "Also save the **final mix** and the **master**, and **export the MIDI** of any software instruments.",
           "Add a text file noting the **tempo**, the **key**, the **DAW name and version**, and a list of the **plug-ins** you used. "
           "Plain WAV files and text are future-proof. Then keep **two copies on two kinds of storage** (for example an external drive and a cloud folder), and check "
           "once a year that they still open."],
      terms=[["Stem", "a WAV of one track or one group (all the drums, say), bounced from the same start point as every other stem."],
             ["Archive", "a complete copy of a finished project, kept so you can reopen it later."],
             ["Collect and save", "copying every audio file a project uses into the project's own folder."],
             ["Bounce", "to render a track or a mix to an audio file."]],
      settings=[["Stems", "one WAV per track, 24-bit, all starting at the project start", "they line up in any DAW, with no project file"],
                ["Final files", "the mix and the master, as WAV", "the finished song in its original form"],
                ["MIDI", "export each software-instrument track as a MIDI file", "the notes are still yours when the instrument is gone"],
                ["Notes file", "tempo, key, DAW and version, sample rate, plug-in list", "tells you how to rebuild it"],
                ["Copies", "two, on two kinds of storage, in different places", "one drive failing should not lose the song"],
                ["Check", "once a year: open it, play it", "a backup you never opened may be broken"]],
      how={"live": ["File → **Collect All and Save**: copies the audio the set uses into the set's folder.",
                    "For stems: File → **Export Audio/Video**, and choose all individual tracks in the Rendered Track menu, with the whole song selected, WAV, 24-bit.",
                    "Then copy the whole project folder, with the notes file, to your two storage places."],
           "reaper": ["File → **Save project as...**, with the option to copy all media into the project directory ticked, only if you are sure you want it there; the original is not changed.",
                      "For stems: File → **Render**, Source **Stems (selected tracks)** with all tracks selected, Bounds **Entire project**, WAV, 24-bit.",
                      "Then copy the whole project folder, with the notes file, to your two storage places."],
           "ardour": ["A HypnoMix DAW session is a self-contained folder, with its audio inside it, so copying the whole session folder is the archive.",
                      "For stems: Session → Export → **Stem Export...**, WAV, 24-bit.",
                      "Then copy the whole session folder, with the notes file, to your two storage places."]},
      listen="Open the stems in a new, empty project, all at the same start point, and play them together. Do they sound like your master? If so the archive works.",
      mistakes=["Archiving the project file alone. If the audio lives elsewhere, the project opens with missing files. Collect the media first.",
                "Stems that start at different points. Bounce all from the same start so they line up.",
                "One copy, on one drive. Keep two, on two kinds of storage, and check them."],
      **{"try": dict(do="Pick a finished song. Collect its media, bounce its stems at 24-bit from the same start, write a notes file (tempo, key, DAW and version, plug-ins), and copy the folder to a second place.",
                     success="In a new, empty project you can import the stems, play them together, and hear the same song as the master.")},
      quiz=[dict(q="Why bounce stems from the same start point?", options=["It makes them louder", "They line up in any DAW without the project file", "They take less space"], answer=1,
                 why="Aligned stems drop into any project and play together, with no timing information needed."),
            dict(q="What is the safest way to store the archive?", options=["One copy on your main drive", "Only in the cloud", "Two copies on two kinds of storage, checked once a year"], answer=2,
                 why="One failure should never lose the song. Two kinds of storage cover different risks, and checking proves they still open.")],
      more=["step:dig-project-files", "step:dig-file-types"]),
]

ENRICH = {}
