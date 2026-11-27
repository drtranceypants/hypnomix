"""Chapter: Mixing."""
from hypnomix.app.lessons._common import ALL, LR, az_only, enrich, place
from hypnomix.app.lessons import ch08_mix_a, ch08_mix_b, ch08_mix_c, ch08_mix_d

CHAPTER = dict(id="mix", levels=("101", "az"), title="Mixing, one effect at a time", sub="balance first, then each effect: what it does, why, where to start", steps=[
  dict(id="balance", title="Balance and pan first", daws=ALL,
       say=["Most of a good mix is just **levels**. Before any effect, pull every fader down, then bring them up one at a "
            "time, starting with the most important part (usually the vocal or the drums), until the song sounds like a song.",
            "Then **pan**: spread things left and right so they don't sit on top of each other. Keep the vocal, kick, snare and "
            "bass in the middle; move guitars, keys and backing vocals out to the sides, often in pairs.",
            "Leave the master fader at 0 and keep the master's peaks around -6 dB: if it's hotter, turn the tracks down, not the master."],
       settings=[["Lead vocal, kick, snare, bass", "pan centre", "the song's anchors"], ["Two guitars or two keyboard parts", "one left, one right (30-70%)", "they make room for each other"],
                 ["Master peaks", "about -6 dBFS", "headroom for mastering"]],
       how={"live": ["The track faders and pan knobs are in the Mixer section (View → Mixer)."],
            "reaper": ["Each track's volume and pan knobs are on the track, and in the mixer (Ctrl+M / Cmd+M)."],
            "ardour": ["The faders and pan are in the Mixer window (Alt+M)."]}),
  dict(id="eq", title="EQ: shape the tone", daws=ALL,
       say=["An **equaliser** turns some frequencies up or down: the low thump, the middle body, the high air. Use it to "
            "remove what you don't need and to make each part sit in its own space.",
            "Start with a **low cut** (high-pass): almost nothing but bass and kick needs the deep lows, and cutting them "
            "clears mud you can't hear on its own. Then cut before you boost: a narrow cut where something boxy or harsh "
            "rings, a wide gentle boost where you want more. Small moves: 1 to 3 dB."],
       terms=[["Hz (hertz)", "how low or high: 100 Hz is a deep thump, 1 kHz the middle, 10 kHz the air."],
              ["Low cut / high-pass", "removes everything below a frequency."], ["Bell", "a boost or cut around one frequency."],
              ["Q", "how narrow a bell is: high Q is narrow."], ["Shelf", "raises or lowers everything above (or below) a frequency."]],
       settings=[["Low cut (vocal, guitar)", "80-120 Hz", "removes rumble and mic thumps"], ["Mud", "200-400 Hz, -2 to -4 dB, only if it sounds boxy", "clears space for the bass and kick"],
                 ["Presence", "3-5 kHz, +1 to +2 dB, wide", "brings the words forward"], ["Air", "a shelf above 10 kHz, +1 to +2 dB", "a little sparkle"]],
       listen="Switch the EQ off and on at the same loudness: better should mean clearer, not just louder.",
       how={"live": ["Browser → Audio Effects → **EQ Eight**, drag it onto the track (or onto its Device View).",
                     "Band 1: click its type and choose the low cut, then drag its dot to about 100 Hz.", "Click a dot and drag up or down for gain; Alt+drag (Option+drag) changes Q."],
            "reaper": ["Click the track's **FX** button → Cockos → **ReaEQ**.", "Click band tab 1 and set its **Type** drop-down to High pass, with the frequency at about 100 Hz.",
                       "Drag the other bands' dots up or down; the scroll wheel on a dot changes its width."],
            "ardour": ["Double-click in the strip's plug-in box → **ACE EQ** (a-EQ in older versions)."]},
       fx={"live": dict(device="EQ Eight", set=[["disp", ["1 Frequency A"], 100], ["raw", ["1 Filter Type A"], 1], ["raw", ["1 Filter On A"], 1],
                                               ["raw", ["3 Filter Type A"], 3], ["disp", ["3 Frequency A"], 3500], ["disp", ["3 Gain A"], 1.5], ["disp", ["3 Resonance A", "3 Q A"], 0.8]]),
           "reaper": dict(device="ReaEQ (Cockos)", set=[["named", "BANDTYPE0", "4"], ["shown", 0, 100], ["named", "BANDTYPE2", "8"], ["shown", 6, 3500], ["shown", 7, 1.5]])},
       action={d: dict(kind="fx") for d in LR}),
  dict(id="comp", title="Compression: even out the loud and quiet", daws=ALL,
       say=["A **compressor** turns a sound down when it gets loud, so the quiet words and the loud ones sit closer "
            "together. A vocal without it jumps in and out of the mix; with too much it sounds flat and squashed.",
            "Set the **ratio** (how hard it turns down), then lower the **threshold** until the meter shows it turning the "
            "loudest words down by 3 to 6 dB. **Attack** is how fast it grabs: slower lets the start of each word through, "
            "which keeps it lively. Then raise the **makeup** (output) gain until it's as loud as it was with the "
            "compressor off, so you judge the sound, not the volume."],
       terms=[["Threshold", "the level where it starts turning down."], ["Ratio", "how much: at 4:1, 4 dB over the threshold comes out as 1 dB over."],
              ["Attack / release", "how fast it turns down, and how fast it lets go."], ["Gain reduction", "how much it's turning down right now, in dB."]],
       settings=[["Ratio", "3:1 (2:1 gentle, 4:1 firm)", "vocals and bass usually sit between 2 and 4"], ["Attack", "10-30 ms", "faster catches peaks but dulls the consonants"],
                 ["Release", "50-150 ms (or Auto)", "lets go between words"], ["Threshold", "until the loudest words show 3-6 dB of gain reduction", "control without squashing"],
                 ["Makeup / output", "the same loudness as bypassed", "a fair comparison"]],
       listen="Listen to the quietest and the loudest line: they should feel closer, with the words still breathing.",
       how={"live": ["Audio Effects → **Compressor**, after the EQ Eight on the same track.", "Watch the orange gain-reduction meter while the loudest part plays."],
            "reaper": ["FX → **ReaComp**, after ReaEQ.", "The gain-reduction meter is the one on the right side of ReaComp."],
            "ardour": ["Plug-in box → **ACE Compressor**."]},
       fx={"live": dict(device="Compressor", set=[["disp", ["Ratio"], 3], ["disp", ["Attack"], 15], ["disp", ["Release"], 100], ["disp", ["Threshold"], -18]]),
           "reaper": dict(device="ReaComp (Cockos)", set=[["shown", "Ratio", 3], ["shown", "Attack", 15], ["shown", "Release", 100], ["shown", "Threshold", -18]])},
       action={d: dict(kind="fx") for d in LR}),
  dict(id="deess", title="De-essing: soften the S's", daws=LR,
       say=["After EQ and compression, \"s\" and \"t\" sounds can get sharp. A **de-esser** is a compressor that only listens "
            "to that hissy range and turns it down just for those moments.",
            "HypnoMix's first pass also finds harsh S's and can soften them in a new copy of the recording, if you'd rather "
            "fix it at the source."],
       settings=[["Frequency", "5-8 kHz (find where the S's bite)", "female voices often higher, male lower"], ["Reduction", "3-6 dB, only on the S's", "more makes a lisp"]],
       how={"live": ["Live has no separate de-esser: use a **Compressor**, open its Sidechain section, turn on **EQ**, set its Freq to about 6 kHz and shape it (with the filter-type, Gain and Q controls) so the S range stands out in what the compressor listens to, and set the threshold so only the S's trigger it.",
                     "Press the headphone button in the sidechain EQ to hear what it's listening to."],
            "reaper": ["FX → **ReaXcomp**: it splits the sound into bands (the numbered tabs). Drag the thin vertical lines between the bands (or set each band's top frequency) so that one band covers only about 5-9 kHz, where the S's are. Leave the other bands doing nothing: set their Ratio to 1:1 (or their Threshold all the way up). Then lower the threshold of the S band until only the S's turn down, and use **Solo current band** to hear that slice of the sound."]}),
  dict(id="reverb", title="Reverb on a send: a shared space", daws=ALL,
       say=["**Reverb** is the sound of a room: it puts a dry recording somewhere. Instead of a reverb on every track, put one "
            "on a **return** (send) track and send a little of each track to it, so everything sounds like it's in the "
            "same place, and one knob sets how much.",
            "On a return, the reverb is set to 100% wet (only the room, none of the dry sound), and the send knobs decide how "
            "much of each track goes in. Less than you think: if you can clearly hear it, it's often too much."],
       terms=[["Send", "a knob on a track that sends a copy of it to a return track."], ["Wet / dry", "the effect alone, or the original alone."],
              ["Decay", "how long the room rings."], ["Pre-delay", "a short gap before the room starts, which keeps the words clear."]],
       settings=[["Dry/Wet (on the return)", "100% wet", "the track's own sound stays on the track"], ["Decay", "1.2-2 s", "a room to a small hall"],
                 ["Pre-delay", "20-40 ms", "keeps the vocal in front"], ["Low cut / high cut on the reverb", "200 Hz / 8 kHz", "a cleaner, darker room"],
                 ["Send from the vocal", "start around -15 dB", "raise until you just hear it, then back off a little"]],
       how={"live": ["Live sets come with return tracks A and B. Drag **Reverb** (or Hybrid Reverb) onto return A and set Dry/Wet to 100%.",
                     "On each track, turn send knob **A** up to send it to the reverb."],
            "reaper": ["Add a track (Ctrl+T / Cmd+T) and name it Reverb. Click its **FX** button and add **ReaVerbate** (or ReaVerb): set Wet to 0 dB and turn Dry all the way down, so the track plays only the room.",
                       "Drag from a track's route button (I/O) to the Reverb track to make a send (or click the route button, then Add new send → Reverb), then set its level.",
                       "Each send shows in the track's route window and as a small knob on its mixer strip: turn that one to set how much of the track goes into the room."],
            "ardour": ["Make a bus (Track → Add Track, Bus or VCA…, an Audio Bus) with **ACE Reverb**.",
                       "On each track's strip, right-click the plug-in box → New Aux Send → the reverb bus."]},
       fx={"live": dict(device="Reverb", track="A", set=[["disp", ["Dry/Wet"], 100], ["disp", ["Decay Time"], 1800], ["disp", ["Predelay"], 30]]),
           "reaper": dict(device="ReaVerbate (Cockos)", bus="Reverb", set=[["shown", ["Wet"], 0, "0 dB"], ["norm", ["Dry"], 0, "off"]])},
       action={d: dict(kind="fx") for d in LR}),
  dict(id="delay", title="Delay: echoes in time", daws=LR,
       say=["A **delay** repeats the sound, in time with the song. A quiet eighth- or quarter-note echo on a return makes a "
            "vocal feel bigger without the wash of a reverb. Like the reverb, it lives on a return, 100% wet."],
       settings=[["Time", "1/4 or 1/8 note, synced to the tempo", "the echoes fall on the beat"], ["Feedback", "20-35%", "two or three repeats"],
                 ["Filter", "cut the lows and the highs of the echoes", "so they sit behind the dry sound"]],
       how={"live": ["Drag **Delay** (or Echo) onto return B, set Dry/Wet to 100%, Sync on, 1/8 or 1/4; send to it with knob B."],
            "reaper": ["A second send track with **ReaDelay**: set the length in musical time (1/8 or 1/4)."]}),
  dict(id="saturation", title="Saturation: warmth and weight", daws=LR,
       say=["**Saturation** adds a little gentle distortion, the way tape and old gear did. A touch makes a bass or vocal "
            "feel thicker and helps it come through on small speakers. Blend it in; you should miss it when it's off rather "
            "than notice it when it's on."],
       settings={"live": [["Type", "Soft Sine or Analog Clip", "gentle shapes"], ["Drive", "2-4 dB", "a touch"], ["Dry/Wet", "20-40%", "blend, don't replace"],
                          ["Output", "lower it to match the level", "a fair comparison"]],
                 "reaper": [["Amount", "15-30%", "a touch: the amount is the whole control, so start low"],
                            ["Track fader", "lower it until the track is as loud as with the effect bypassed", "louder always sounds better, so compare at the same level"]]},
       how={"live": ["Audio Effects → **Saturator**, on the bass or the vocal, after the compressor.",
                     "Set Drive to about 3 dB and Dry/Wet to about 30%, then lower Output until switching the device off and on doesn't change the loudness."],
            "reaper": ["Click the bass or vocal track's **FX** button, type **saturation** in the search box and add **JS: Saturation**, after ReaComp in the chain.",
                       "Set Amount to about 20%. Switch it off and on with the tick box beside its name in the FX chain list, and lower the track's fader until both sound equally loud."]},
       fx={"live": dict(device="Saturator", set=[["disp", ["Drive"], 3], ["disp", ["Dry/Wet"], 30], ["disp", ["Output"], -2]]),
           "reaper": dict(device="JS: Saturation", set=[["shown", ["Amount (%)", "Amount"], 20, "20%"]])},
       action={d: dict(kind="fx") for d in LR}),
  dict(id="groups", title="Groups: mix the drums as one", daws=("live", "reaper"),
       say=["Once you have several drum or backing-vocal tracks, put them in a **group** (a bus): their sound comes together "
            "on one track, with one fader and one set of effects. Turning the whole drum kit down a little becomes one move."],
       how={"live": ["Select the tracks (click the first, Shift+click the last) and press Cmd+G (Ctrl+G).", "The group track's fader now sets all of them; you can fold it with its triangle."],
            "reaper": ["Select the tracks, then use the **Track** menu → **Move tracks to folder** and pick a new folder (or run the action 'Track: Move tracks to new folder' from the Actions list): the folder track is the bus."]}),
  dict(id="automation", title="Automation: the mix moves", daws=LR,
       say=["Real mixes move: the vocal comes up a little in the chorus, the reverb swells at the end. **Automation** records "
            "those moves, so a fader or knob follows a line you draw over time.",
            "Do it last, after the balance and effects are set, and keep the moves small."],
       how={"live": ["Press **A** in the Arrangement to show automation; choose the track's Volume in its lane menu, then click points in and drag them."],
            "reaper": ["Click the track's envelope button (trim/arm), tick Volume, then click points on the envelope lane."]}),
  dict(id="mix-check", title="Let HypnoMix check the mix", daws=ALL,
       say=["When it sounds good to you, run HypnoMix's **first pass** on the song. It looks for what's easy to miss: two parts "
            "fighting over the same frequencies, a part much louder in one section, a plug-in left switched off, clipping. "
            "Every finding is a suggestion with a before and after to hear; you decide."],
       app=dict(view="home", label="Open the Songs tab")),
 ])


_ORDER = ['mix-gain-staging', 'balance', 'mix-static', 'mix-panning', 'mix-lowcuts', 'mix-cut-first', 'eq', 'mix-freq-instruments', 'mix-masking', 'comp', 'mix-comp-depth', 'mix-comp-parallel', 'mix-gates', 'deess', 'reverb', 'mix-reverb-kinds', 'delay', 'mix-delay-kinds', 'mix-modulation', 'saturation', 'mix-sidechain', 'mix-sends', 'groups', 'mix-vocal-chain', 'mix-lead-harmonies', 'mix-drums', 'mix-drum-room', 'mix-bass-kick', 'mix-guitars', 'mix-keys-pads', 'automation', 'mix-rides', 'mix-bus', 'mix-references', 'mix-translation', 'mix-check', 'mix-ear-fatigue', 'mix-finished', 'mix-mistakes']
CHAPTER["steps"] = enrich(place(CHAPTER["steps"] + az_only(ch08_mix_a.STEPS + ch08_mix_b.STEPS + ch08_mix_c.STEPS + ch08_mix_d.STEPS), _ORDER), ch08_mix_a.ENRICH, ch08_mix_b.ENRICH, ch08_mix_c.ENRICH, ch08_mix_d.ENRICH)
