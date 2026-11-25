"""Teach mode: a few plain words on why each technique is used, shown with every finding in REVIEW.md and on the
review page when the preference `review.teach` is on (the default; `hypnomix prefs set review.teach=off` hides it).

  why(finding)       why this kind of fix exists and what to listen for
  practice(finding)  what engineers commonly do about it (a habit, not a rule: your ears decide)

Texts are looked up by (tool, kind), then by tool, then a general fallback, so a new check always gets something.
"""

# (tool, kind) or (tool, None) -> (why, common practice)
TEXT = {
    # clips and edits
    ("smooth", "click"): (
        "A clip that starts or stops on a sample that isn't zero jumps instantly from silence to sound. The speaker "
        "can't move that fast, so you hear a click. A fade of a few milliseconds lets the waveform start from zero.",
        "a 2-10 ms fade at every edit; longer on sustained sounds, never long enough to soften the attack"),
    ("smooth", "cut"): (
        "When the next clip is much louder or quieter than the one before, the level jumps at the edit. Your ear "
        "hears the join instead of the performance. Easing the volume across the cut hides the seam.",
        "match clip levels at comp edits within 1-2 dB, then crossfade"),
    ("smooth", "spike"): (
        "A burst much louder than the phrase around it (a plosive 'p', a knock, a bumped mic) pokes out of the mix "
        "and makes compressors after it clamp down. Dipping just that moment keeps the phrase even.",
        "clip-gain or volume dips on single plosives and bumps; a high-pass for low thumps"),
    ("smooth", "step"): (
        "A lasting level change inside one take (the singer moved off the mic) makes one half of a phrase sit "
        "differently in the mix. Evening it out is like riding the fader by hand.",
        "ride the clip gain so phrases sit at a steady level before any compression"),
    ("smooth", None): (
        "Clicks, level jumps and bursts at clip edits pull the ear to the edit instead of the music. Small fades and "
        "volume eases hide them without changing the performance.", "a short fade at every edit; even out levels at cuts"),
    ("edges", None): (
        "A clip edge or fade placed on the start of a word turns its first sound down, so the word loses its "
        "consonant ('sing' becomes 'ing'). Moving the fade off the word keeps it intelligible.",
        "start comp edits in the gap just before a word, with short fades"),
    ("cliplevel", None): (
        "A harmony clip far quieter than the rest of its own track disappears in that phrase. Raising that clip "
        "brings it back to where the part sits elsewhere, without touching the fader.",
        "even out a part's clips first, then balance the parts with faders"),
    ("unroll", None): (
        "A looped clip plays the same audio every pass, so a fix on one pass would change them all. Unrolling makes "
        "each pass its own clip.", "unroll before editing one pass of a loop"),
    # timing
    ("timing", None): (
        "Hits that land far from where the rest of the band plays blur the groove, especially kick and bass on the "
        "beat. Nudging only the outliers part of the way keeps the human feel and tightens what sticks out.",
        "tighten kick and bass on downbeats most; leave fills and melodic parts looser"),
    ("vocalign", None): (
        "When a double or harmony starts and ends its words apart from the lead, the consonants smear and the stack "
        "sounds loose. Lining up word starts and ends (not every note) keeps the blend.",
        "align consonants of doubles to within about 20-30 ms of the lead; leave counter-melodies alone"),
    # pitch
    ("tune", None): (
        "Notes sung a little off the song's pitch rub against the chords. Gentle correction moves only each note's "
        "centre part of the way, so vibrato, scoops and slides stay as sung.",
        "light correction on held notes only; leave notes within about 20 cents alone"),
    ("key", None): (
        "Tuning needs the right scale. Where two scales fit the music equally, a wrong guess would pull notes to "
        "the wrong pitch, so it asks.", "confirm the key by ear before any pitch correction"),
    ("voices", None): (
        "In a vocal stack, a higher part louder than the part below it pulls the ear away from the harmony's shape. "
        "Easing only the overshadowing part keeps every voice audible.",
        "the root and lead stay; upper harmonies a few dB under the part below them, by taste"),
    # vocals cleanup
    ("deess", None): (
        "Sharp 's' and 't' sounds carry far more high-frequency energy than the vowels around them, and compression "
        "and bright EQ make them hiss. A de-esser turns down only the high band during those moments.",
        "a few dB of de-essing on sibilant moments only; listen that words don't lisp"),
    ("breaths", None): (
        "Breaths between phrases rise with compression and can sound louder than intended. Turning them down (not "
        "off) keeps the singer human without the gasp.", "breaths 6-10 dB down, rarely removed entirely"),
    ("dehiss", None): (
        "A take boosted with clip gain lifts its own noise floor by the same amount, so the hiss between phrases "
        "becomes audible. Cleaning the take (or recording hotter) fixes the source; turning it down only hides the part.",
        "gain-stage at the source; gentle broadband de-noise only between phrases"),
    ("cleanup", None): (
        "Hum, rumble and DC offset take up headroom and cause clicks at edits without adding anything musical.",
        "a high-pass around 25-40 Hz on tracks with no real low end"),
    ("recording", None): (
        "A plain measurement of the recording: clipping, very low or very hot levels, noise and DC each limit what "
        "later processing can do.", "record peaks around -12 to -6 dBFS, with a quiet room"),
    ("prep", None): (
        "Getting each take clean before mixing (no clipped peaks, plosives, rumble or long silences) means later "
        "EQ and compression work on the music, not the problems.", "clean the takes first, then mix"),
    # effects and dynamics
    ("distortion", "drive"): (
        "Saturation and drive add harmonics. A little adds warmth; too much, or too much level going in, turns into "
        "audible fuzz on loud notes.", "drive set by ear on the loudest passage, with the input level checked"),
    ("distortion", "compressor"): (
        "A compressor with a very fast attack and release on a bass-heavy part follows the waveform itself and "
        "reshapes it, which is heard as distortion.", "release longer than one cycle of the lowest note (tens of ms)"),
    ("distortion", "limiter"): (
        "A limiter hit hard flattens every peak. Some is normal; a lot sounds squashed and gritty.",
        "a few dB of limiting on peaks; level problems fixed earlier in the chain"),
    ("distortion", "clipper"): (
        "A clipper cuts the top off loud peaks. Hit gently it is invisible; hit hard it adds harshness.",
        "a dB or two of clipping at most, checked at matched loudness"),
    ("distortion", "eq-boost"): (
        "A big EQ boost raises the level of that band a lot, which eats headroom and can overload the next device.",
        "cut what's too much rather than boost; boosts of a few dB"),
    ("distortion", None): (
        "Distortion you didn't choose (clipped peaks, overloaded devices) makes a mix tiring to listen to and gets "
        "worse after mastering and lossy encoding.", "find the device or take that clips and lower what goes into it"),
    ("devices", "compressor"): (
        "A compressor turns a part down when it gets loud. Too much reduction squashes the part; attack and release "
        "outside the usual range for that kind of part either dull its hits or make it pump.",
        "2-6 dB of reduction on most parts; attack slow enough to keep the hit, release in time with the song"),
    ("devices", "gate"): (
        "A gate closes when a track is quiet to cut noise and spill. Set too high it chops the starts and tails of "
        "notes.", "threshold just above the noise, with a release that lets tails ring"),
    ("devices", "limiter"): (
        "A limiter on a track or bus catches peaks; driven hard it flattens the part and adds grit.",
        "limiters mostly on the master; a dB or two elsewhere"),
    ("devices", "eq-lowcut"): (
        "Low-frequency rumble a part doesn't need fills the low end and muddies bass and kick. A low cut removes it.",
        "a low cut just below each part's lowest useful note"),
    ("devices", None): (
        "Each device is judged by what it actually does to the audio it gets, not by its settings alone.",
        "set devices by ear on the part in the mix"),
    ("sidechain", None): (
        "Sidechain compression ducks one part when another plays (the bass under the kick, a pad under the vocal), "
        "so they don't fight. The depth, recovery and timing decide whether it sounds tight or pumps.",
        "a few dB of ducking that recovers before the next hit"),
    ("duck", None): (
        "Reverb and delay on a vocal can cover the words. Ducking the return while the singer sings and letting it "
        "bloom in the gaps keeps the words clear and the space big.",
        "3-6 dB of ducking on vocal delays; lighter on reverbs"),
    ("audit", None): (
        "A look over every device chain for things that often cause trouble: stacked limiters, extreme EQ, devices "
        "left switched off.", "keep chains short and purposeful"),
    # mix
    ("masking", None): (
        "Two parts with similar level in the same frequency range mask each other: neither is clear. A small cut in "
        "the part that should give way lets the other one through.",
        "cut the supporting part a few dB where the lead part lives"),
    ("align", None): (
        "Two mics on one source (kick in and out, snare top and bottom) that are flipped or a little apart in time "
        "cancel part of the low end when summed.", "flip polarity or shift by a fraction of a millisecond, by ear"),
    ("measure", "true-peak"): (
        "Lossy encoders (AAC, MP3) and phone speakers overshoot the sample peaks. A true-peak ceiling under 0 dBTP "
        "leaves room so the release doesn't clip on streaming.", "-1 dBTP for streaming; -2 for very loud masters"),
    ("measure", "loudness"): (
        "Streaming services turn songs to about the same loudness. Mastering much louder than their level only costs "
        "dynamics; much quieter can sound weak next to other songs.", "-14 LUFS integrated for streaming"),
    ("measure", None): ("A measurement of the whole mix against your target.", "check loudness and true peak last"),
    ("qc", None): (
        "Release checks: format, silence at the ends, true peak, loudness and phase, so the file is accepted and plays "
        "right everywhere.", "run release checks on every final bounce"),
    ("translate", None): (
        "How the mix holds up in mono, on phones, earbuds and in a car, and after streaming normalisation.",
        "check a mix on small speakers and in mono before calling it done"),
    ("sections", None): (
        "Songs build: verses, choruses and bridges usually differ in loudness and vocal level. A repeated section "
        "much quieter or louder than its first time, or a flat arc, can make the song feel static.",
        "choruses a little louder than verses; repeats close to each other"),
    ("match", None): (
        "Compared with a song you love: tone by band, dynamics, width and loudness, as moves you might make.",
        "use a reference at matched loudness, and move toward it, not onto it"),
    # structure and naming
    ("name", None): (
        "Clear track names make every later step faster and safer: the tools find the vocals and drums by name, and "
        "so do you.", "name tracks by what they are before mixing"),
    ("order", None): (
        "Tracks in a fixed working order (drums, bass, keys, vocals...) and one track per voice in a stack mean every "
        "song is laid out the same way. Sound is unchanged.", "group and order tracks the same way in every song"),
    ("tidy", None): (
        "Switched-off tracks and one instrument spread over several tracks make a set harder to read and mix. An "
        "archive copy keeps everything; the working set gets lighter.", "archive, then keep the working set lean"),
    ("refs", None): (
        "A clip whose audio file can't be found plays silence, and every check of that track means nothing until it "
        "is found.", "collect and save the set with its files"),
    ("intent", None): (
        "Things that look unusual (automation, hard pans, switched-off tracks) are often deliberate. Listing them as "
        "questions protects your choices from being 'fixed'.", "treat existing automation and effects as intent"),
    ("structure", None): (
        "A quick look at the set itself, without listening: names, fader and clip-gain extremes, and the structure "
        "Live needs to open the set.", "check the structure before opening a set a tool wrote"),
    ("motion", None): (
        "Long loops feel static. Small moves (a filter opening into a chorus, a delay throw at a phrase end, a short "
        "drop-out before a drop) keep the listener's attention.",
        "one or two moves per section transition, drawn as automation"),
    ("borrow", None): (
        "Loops from an earlier version of the song can add variety that already fits it, on switched-off tracks you "
        "can try.", "add layers off, then switch on what serves the song"),
    ("variations", None): ("Spare takes of the same part add small differences to repeats.", "vary every few repeats"),
    ("automix", None): (
        "Each move of the trial mix (EQ, compression, level, pan, reverb) is one choice you can take or leave.",
        "balance first, then EQ and compression, then space"),
    ("master", None): (
        "Each mastering stage (clean-up, tone, glue, width, limiter) is one choice you can take or leave.",
        "small moves per stage; the limiter last"),
}

FALLBACK = ("A measured problem with a proposed fix. Listen to the spot before and after deciding.",
            "fix the source of a problem before treating its symptom")


def _row(f):
    tool, kind = f.get("tool"), f.get("kind")
    return TEXT.get((tool, kind)) or TEXT.get((tool, None)) or FALLBACK


def why(f):
    return _row(f)[0]


def practice(f):
    return _row(f)[1]
