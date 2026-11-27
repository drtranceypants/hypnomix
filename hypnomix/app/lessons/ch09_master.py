"""Chapter: Mastering."""
from hypnomix.app.lessons._common import ALL, LR, az_only, enrich, place
from hypnomix.app.lessons import ch09_master_steps

CHAPTER = dict(id="master", levels=("101", "az"), title="Mastering", sub="what it is, and a good chain to start from", steps=[
  dict(id="what", title="What mastering is", daws=ALL,
       say=["**Mastering** is the last step: one gentle pass over the finished stereo mix so it sounds its best everywhere "
            "(phones, cars, earbuds, a club), sits at the right loudness for streaming, and has no peaks that distort when "
            "it's turned into an MP3 or AAC.",
            "It isn't where a song gets fixed. If the vocal is too quiet, go back to the mix: mastering moves everything at "
            "once. Good mastering is small moves, a dB here and there."],
       terms=[["LUFS", "how loud a song feels on average. Many streaming services play songs back at around -14 LUFS when their loudness normalisation is on (Apple Music's Sound Check is around -16), so going much louder mostly buys nothing. These figures differ and change, so check each service's own guidance."],
              ["True peak (dBTP)", "the real highest point after the file is turned back into sound. Keep it at -1 dBTP or lower."],
              ["Limiter", "a very fast compressor that stops anything going over a ceiling."], ["Reference track", "a finished song you love, to compare with."]]),
  dict(id="prepare", title="Prepare the mix", daws=ALL,
       say=["Take off anything you put on the master while mixing to make it loud, check the master peaks around -6 dB, and "
            "export the whole song as a **24-bit WAV** from the very start to the end of the last ring-out. That bounce is "
            "what you master (or what HypnoMix masters for you)."],
       how={"live": ["File → Export Audio/Video: Rendered Track **Master** (called **Main** in Live 12), the whole song selected, WAV, 24-bit, sample rate as the set, Normalize off, Dither off."],
            "reaper": ["File → Render…: Source **Master mix**, Bounds **Entire project**, WAV, 24 bit, the sample rate the project uses.",
                       "Leave normalising and dither off, and take off any limiter you only used for checking: mastering needs the mix's own peaks."],
            "ardour": ["Session → Export → Export to Audio File(s): WAV, 24-bit, Normalize off."]}),
  dict(id="chain", title="A good mastering chain", daws=ALL,
       say=["The usual order, each doing a little: **EQ** for the overall tone (tiny moves, and a low cut at about 25 Hz for "
            "rumble you can't hear), a **glue compressor** that barely touches it (2:1, slow attack, 1 to 3 dB), **bass in "
            "mono** below about 120 Hz so the low end is solid on every system, and last a **limiter** with its ceiling at -1 dB "
            "true peak, turned up until the song reaches its loudness target.",
            "HypnoMix can build that chain from your DAW's own plug-ins, every gain starting at 0 dB, so you add only what the "
            "song needs."],
       settings=[["EQ", "low cut 25 Hz; shelves and bells within ±1 dB", "gentle overall tone"], ["Glue compressor", "2:1, attack 30 ms, auto release, 1-3 dB", "holds the mix together"],
                 ["Bass mono", "below 120 Hz", "a solid low end on every system"], ["Limiter ceiling", "-1 dBTP", "safe after MP3 / AAC"],
                 ["Limiter gain", "until about -14 LUFS (streaming)", "no more than about 3 dB of limiting on average"]],
       how={"live": ["On the **Master** track (called **Main** in Live 12): EQ Eight, Glue Compressor, Utility (Bass Mono on, 120 Hz) and Limiter, in that order.",
                     "Or put the HypnoMix **HypnomixMain** device on the master and press **Build chain** (see Wiki → the mastering chain)."],
            "reaper": ["On the master (View → Master track if it is hidden), click **FX** and add, in this order: ReaEQ (a low cut around 25 Hz), ReaComp (2:1, slow attack), then **ReaLimit** (ceiling -1).",
                       "With HypnoMix Main on the master, its **Build chain** button does it, bass mono included."],
            "ardour": ["On the master strip: ACE EQ, ACE Compressor, and a limiter plug-in last (for example the free x42 Digital Peak Limiter, if it is installed on your system).",
                       "Or let HypnoMix master the exported WAV: the next step."]},
       action={d: dict(kind="chain") for d in LR}),
  dict(id="loud", title="Loudness, A/B and the reference", daws=ALL,
       say=["Turn the limiter's gain up while the loudest part plays until the master reads about **-14 LUFS** (a loudness "
            "meter, or HypnoMix's Match target). Then compare with the mix **at the same loudness**: a louder version always "
            "sounds better for a moment, so match levels before you judge.",
            "Play a song you love next to yours, also level-matched, and listen for the low end, the brightness and how wide "
            "it feels. HypnoMix's `match` lists the differences for you."],
       how={"live": ["HypnomixMain's **Match target** turns the limiter until the master hits the target, and its A/B is level-matched."],
            "reaper": ["HypnoMix Main's **Match target** does the same on REAPER's master: it starts playing if REAPER was stopped (play the loudest part), and stops again when it is done.",
                       "In the HypnoMix Review panel, **Match** plays B at A's loudness, so a louder B can't win just by being louder."],
            "ardour": ["Use a loudness meter on the master (HypnoMix DAW's loudness analysis, in its Session menu), or master the WAV with HypnoMix."]}),
  dict(id="deliver", title="Check it and export", daws=ALL,
       say=["Before you send it out, run HypnoMix's checks on the master: `qc` (no clipping, the right loudness and peaks, "
            "silence at the ends) and `translate` (how it sounds on a phone, in mono, as an MP3). Then export the final WAV "
            "and you're done. Congratulations: that's a song, start to finish.",
            "Or let HypnoMix master the bounce for you with `master` and approve each stage: Tools → master, or the Assistant."],
       app=dict(view="tools", label="Open the Tools tab")),
 ])


_ORDER = ['what', 'mst-units', 'mst-streaming', 'prepare', 'chain', 'mst-limiter', 'loud', 'mst-codec', 'mst-dither', 'deliver', 'mst-album', 'mst-versions', 'mst-handoff']
CHAPTER["steps"] = enrich(place(CHAPTER["steps"] + az_only(ch09_master_steps.STEPS), _ORDER), ch09_master_steps.ENRICH)
