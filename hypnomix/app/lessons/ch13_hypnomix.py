"""Chapter: hypnomix in your DAW."""
from hypnomix.app.lessons._common import ALL, LR, az_only, enrich, place
from hypnomix.app.lessons import ch13_hypnomix_steps

CHAPTER = dict(id="hypnomix", levels=("tour", "101", "az"), title="HypnoMix in your DAW", sub="the app, the devices, and the loop: scan, hear, decide, apply", steps=[
  dict(id="hm-loop", title="How HypnoMix works", daws=ALL,
       say=["HypnoMix is a second engineer that never touches your original. Every job follows one loop: **preferences → "
            "scan → review → apply → listen**. The scan is read-only; the review lists each finding with a proposed fix and, "
            "where it can, a before and after to hear; you approve or skip; Apply writes only what you approved into a "
            "**new** set or project (or new audio files) next to yours.",
            "Taste stays yours. It finds technical things (clicks at edits, level jumps between takes, flat notes, "
            "masking, hum, loudness and true peak) and proposes gentle, partial fixes. Timing and tuning keep the human "
            "feel: nothing is quantised or hard-tuned, and a protected track is never changed without asking again."],
       how={"live": ["Answer the Preferences tab once (targets, protected tracks, how much to explain): every proposal starts from it."],
            "reaper": ["Answer the Preferences tab once (targets, protected tracks, how much to explain): every proposal starts from it.",
                       "In REAPER, each track's HypnoMix Probe also has a Protect switch. It is saved in the project and the app's review of what it heard lists the track as protected, but `scan` and Apply on a REAPER project do not read it yet: to keep Apply off a track, add it to the protected tracks in the Preferences tab."],
            "ardour": ["Answer the Preferences tab once: every proposal starts from it."]},
       app=dict(view="prefs", label="Open Preferences")),
  dict(id="hm-connect-live", title="Connect HypnoMix to Live", daws=("live",),
       say=["Two links, both optional for scanning a saved set. **AbletonOSC** (a control surface script) lets HypnoMix "
            "drive the open set: arm and route tracks, punch-record, load Live's own devices, play bars. The **Max for Live "
            "devices** measure inside Live and follow the review; they need Max for Live (Suite, or the add-on) and the "
            "app running."],
       how={"live": ["Setup → Ableton Live copies the AbletonOSC script into your User Library (or `hypnomix install`). Restart Live.",
                     "Open Live's settings window (called Settings in Live 12 and Preferences in Live 11; it is in the Live menu on a Mac and the Options menu on Windows), go to the tab for Link, Tempo and MIDI, and under Control Surface choose **AbletonOSC**.",
                     "Keep the HypnoMix app open while you work: the devices talk to it."]},
       action={"live": dict(kind="devices")}),
  dict(id="hm-connect-reaper", title="Connect HypnoMix to REAPER", daws=("reaper",),
       say=["The **bridge** is a script that runs inside the open REAPER: nothing is installed and no setting changes, and "
            "every change it makes is one undo step named \"hypnomix: …\". The **JSFX** (HypnoMix Probe and HypnoMix Main) "
            "measure inside REAPER and carry the song card and the mastering chain buttons."],
       how={"reaper": ["`hypnomix reaper start` (or Setup → REAPER) runs the bridge, opening REAPER if it's closed.",
                       "`hypnomix reaper probes install` copies the JSFX into REAPER's Effects/hypnomix (the button below does it).",
                       "Keep the HypnoMix app open while you work: the probes and Main talk to it through the bridge. `hypnomix reaper status` shows what the bridge sees (REAPER's version, the open project, its tempo and tracks); `hypnomix reaper stop` stops it, and it also stops when REAPER quits."]},
       action={"reaper": dict(kind="devices")}),
  dict(id="hm-connect-ardour", title="Connect HypnoMix to HypnoMix Studio", daws=("ardour",),
       say=["HypnoMix reads HypnoMix Studio sessions (`.ardour`: tracks, buses, regions with their layering, fades, gain envelopes, "
            "plug-ins, automation), renders each track itself, and runs the same first-pass checks. Apply writes one new "
            "snapshot next to your session, inside its folder, with the fades, region gain, volume dips and fader, pan and "
            "mute moves you approved. Track names and order, vocal stacks, timing and sidechain stay a list for you to make "
            "by hand, and audio fixes (tuning, de-hiss, de-ess) come back as repaired files to bring in. In these lessons it does not click in the open DAW for you: you make each change yourself.",
            "The reader and the new snapshot haven't been tried in the running DAW yet: open the snapshot, and if anything "
            "looks or sounds different from what HypnoMix listed, say so."],
       how={"ardour": ["Save the session. On the Songs tab, choose the session folder (or its `.ardour` file) and press Start the first pass.",
                       "HypnoMix Studio can stay open while you scan: a scan writes nothing next to your session. Apply writes a new snapshot beside it: open that one in HypnoMix Studio when it is done."]}),
  dict(id="hm-devices-live", title="The devices in Live", daws=("live",),
       say=["Three pass-through Max for Live devices (audio untouched), under User Library → Presets → Audio Effects → Max "
            "Audio Effect → Hypnomix:",
            "**HypnomixProbe**, last on every track, return and group: measures the track after all its plug-ins (loudness, "
            "peak, 8 bands, width), and holds what the track is, its priority (focus / background) and Protect. "
            "**HypnomixMain**, on Main: the mix meter, the **song card** (genre, key, scale, chords, target LUFS, ceiling, "
            "limiter character, amount), the mastering chain, and Record and review before export. **Hypnomix**, on any "
            "track: follows the app's review, jumps Live to each finding, Approve / Skip, and A / B / Blind in an A/B set.",
            "**Hypnomix Align** aligns a vocal stack (timing, optionally pitch and formant) to a guide track from inside "
            "Live, writing warp markers into a new set. It's the newest device: keep your original and listen."],
       how={"live": ["Tick Live devices when you start the first pass (or run `hypnomix probe insert \"Song.als\"`): it writes \"Song (hypnomix devices).als\" with a probe on every track, group and return, and the review device and HypnomixMain on Main. No dragging.",
                     "Set each probe's What it is (or leave auto), Priority and Protect; fill in the song card on HypnomixMain. They're Live parameters, so they're saved in the set and `scan` reads them.",
                     "The app's Live tab shows every probe while Live plays; Record → play → Stop makes a review from what was heard (frequency fights, the lead against the band, mono low end, loudness)."]}),
  dict(id="hm-devices-reaper", title="The JSFX in REAPER", daws=("reaper",),
       say=["Two pass-through REAPER effects (JSFX: the audio is untouched), in the FX browser under JS → hypnomix:",
            "**HypnoMix Probe** (last on each track) measures the track after all its plug-ins (loudness, peak, 8 bands, width) "
            "and holds what the track is, its priority (focus / background) and Protect. **HypnoMix Main** (on the master) is "
            "the mix meter and holds the song card (genre, key, scale, limiter character, target, ceiling, amount), **Record and "
            "review before export**, and three buttons for the mastering chain: **Build chain** puts REAPER's own plug-ins just "
            "before Main, each renamed \"HypnoMix · ...\"; **Match target** plays and turns ReaLimit until the master lands on "
            "the card's target; **Save chain** keeps everything before Main as an FX chain file you can build again. These "
            "buttons need the bridge running, not the app.",
            "Two panels open in windows of their own inside REAPER (they are not plug-ins, so they are not in the FX list). The "
            "**HypnoMix Review panel** (`hypnomix reaper review`) steps through the app's review inside REAPER: Prev / Next jump to "
            "each finding, **A · now** and **B · fix** switch instantly in an A/B project, **Match** plays B at A's loudness, "
            "**Blind** plays X and Y in random order and records which you liked, and Approve / Skip record your decision. The "
            "**HypnoMix Align panel** (`hypnomix reaper align`) aligns a vocal stack to a guide track (timing, optionally pitch "
            "and formant) and writes the result into a new project, \"Song (aligned).rpp\": your own project is never written. "
            "It's the newest part: keep your original and listen."],
       how={"reaper": ["`hypnomix reaper probes insert \"Song.rpp\"` writes \"Song (probes).rpp\" with a probe on every track and Main on the master (or open the track's FX window, press Add, type Hypnomix in the search box and pick HypnoMix Probe).",
                       "To open a plug-in's window, click the track's **FX** button and select it in the list. The settings are chips and menus inside each plug-in's own window (not REAPER's slider rows): set each probe's What it is (or leave auto), Priority and Protect, and fill in the song card on HypnoMix Main (click the master's **FX** button; View → Master track shows the master if it is hidden). Click a chip: Protect switches on and off, the others open a menu. They are saved in the project and the app uses them while you play (the review of what it heard, Record and review, the mastering chain); `scan` does not read them yet.",
                       "With the bridge running and the app open, the app's Live tab shows every probe while REAPER plays; Record → play → Stop makes a review from what was heard.",
                       "For the HypnoMix Review panel, build an A/B project (`hypnomix abset` on the scan folder), open it in REAPER, open the song's review in the app, then run `hypnomix reaper review`. Moving to another finding puts the last one back to A, and stopping `hypnomix reaper review` (or closing the panel) leaves the whole project on A. While the panel is in front, space plays and stops, and Esc closes the guide, or the panel when no guide is showing. Other keys do nothing there: click REAPER's own window first for its shortcuts.",
                       "For the Align panel, save the project first (Align reads the saved .rpp), keep the app open and run `hypnomix reaper align`: select the guide track and press Guide ←, select the other parts and press + Part, then Align. Open project opens the aligned copy in a new tab.",
                       "When the bridge starts it gives each probe a slot number, so REAPER may ask to save once. If a panel isn't the window in front, the first click only brings it forward."]}),
  dict(id="hm-guide-reaper", title="The HypnoMix plug-ins' built-in guide", daws=("reaper",),
       say=["HypnoMix Probe, HypnoMix Main, the HypnoMix Review panel and the HypnoMix Align panel each have a **?** button in "
            "the top-right corner of their window. It starts a step-by-step guide to that window's controls, one control at a "
            "time, with what each one does: **Next** and **Back** move through it, **Done** closes it at the end, and **Skip "
            "guide** closes it early.",
            "The guide shows by itself the first time each one is opened, so you meet every control once. With the bridge "
            "running, REAPER remembers that you have seen it, so it shows once on your computer. Without the bridge, Probe and "
            "Main forget it when REAPER restarts (a plug-in that has already shown it stays quiet). After that it stays out of "
            "the way until you press **?** again."],
       how={"reaper": ["Open HypnoMix Main's window (click the master's **FX** button and select HypnoMix Main) and press **?** in the top-right corner.",
                       "Step through with **Next** and **Back**, and press **Done** at the end (or **Skip guide** to close it early).",
                       "Do the same on a track's HypnoMix Probe, in the HypnoMix Review panel (`hypnomix reaper review`) and in the HypnoMix Align panel (`hypnomix reaper align`)."]}),
  dict(id="hm-scan", title="The first pass: scan and review", daws=ALL,
       say=["On the **Songs** tab choose the saved set, project or session (or a folder of stems from any DAW), add a bounce of the "
            "mix if you have one (loudness, release checks, the key) and press Start the first pass. Every check runs in parallel and nothing "
            "changes. **Deep scan** also renders every track for frequency fights and mic phase.",
            "The review lists the fixes you can hear first, by severity. **Approve**, **Skip** or **Change** (with a note) each, with the mouse "
            "or the keys (j and k move, a, s and c decide, space plays, b switches A and B, ? lists them all); *Approve all "
            "low* shows you a list of the small, safe ones to confirm (never tuning or other taste calls). Checks that didn't run are listed at the top: no finding there means nothing."],
       how={"live": ["Save the set first: the scan reads the saved .als.", "Give the key on the Songs tab or the song card before any vocal tuning is applied."],
            "reaper": ["Save the project first (File → Save, Ctrl+S / Cmd+S): the scan reads the saved .rpp and finds files the way REAPER does.",
                       "Give the key on the Songs tab before any vocal tuning is applied: the scan of a REAPER project does not read HypnoMix Main's key chip yet."],
            "ardour": ["Save the session, then scan its folder."]},
       app=dict(view="home", label="Open the Songs tab")),
  dict(id="hm-ab", title="Hear each fix in your DAW", daws=LR,
       say=["The review's players are quick renders. To hear a fix with every plug-in playing, **Build A/B set** "
            "(`hypnomix abset`) writes one new set or project where each fix sits beside what you have, switched off: a "
            "copy of the changed device, or a muted copy of the track with the fix.",
            "Switch **A · now** and **B · fix** instantly, turn **Match** on so B plays at A's loudness, or go **Blind** (X and "
            "Y in random order; your picks are kept and shown in the review). The A/B set is only for listening: Apply always "
            "writes from your original."],
       how={"live": ["In the review: Build A/B set for Live. Close the original, open \"Song (A-B).als\", put the Hypnomix device on any track."],
            "reaper": ["`hypnomix abset \"hypnomix-out/scan/Song\"` (the folder the scan wrote; the app's Songs tab shows where yours is), open \"Song (A-B).rpp\", then `hypnomix reaper review` for the HypnoMix Review panel."]}),
  dict(id="hm-apply", title="Apply, history and undo", daws=ALL,
       say=["**Apply** writes only the approved fixes: a new set or project next to the original (close it in the DAW "
            "first), or repaired copies in the scan's fixed folder for audio. Every applied version is kept; undo writes "
            "another new version, it never deletes. Teach it as you go: what you skip and change shapes the next proposals."],
       how={"live": ["Close the set in Live, Apply, then open \"Song (fixed).als\"."], "reaper": ["Close the project tab, Apply, then open the new .rpp (tuned vocals arrive as new takes)."],
            "ardour": ["Close the session in HypnoMix Studio, Apply, then open the new snapshot (`Song (fixed).ardour`) from the same session folder. It holds the fades, gain, dips and fader, pan and mute moves you approved; names, order, stacks and timing come back as a list to do by hand, and repaired audio lands in the scan's fixed folder."]}),
  dict(id="hm-tracking", title="Tracking helpers", daws=ALL,
       say=["Before you record, `hypnomix soundcheck` listens to an interface input and tells you which way to turn the "
            "gain (peaks -12 to -6 dBFS in 24-bit), and flags noise, hum and DC. After recording, `takes` ranks whole "
            "takes and lists the best one per section, `vocalign` lines doubles and harmonies up with each other, gently: with two or more parts nobody is forced onto the lead, only the words clearly off the group move most of the way and the rest barely move, and `clipmatch` evens out takes recorded on different days."],
       how={"live": ["`hypnomix live arm`, `live input`, `live record 17 8 3` punch-record through AbletonOSC (three passes = three take lanes).",
                     "Live's take lanes (Live 11 and 12) + `takes` for the comp; Hypnomix Align for stacks."],
            "reaper": ["Before you record, the level check below (or `hypnomix soundcheck`) tells you which way to turn the interface's gain.",
                       "Record takes as usual: each pass over the same spot becomes a take inside the item. Export them from the same start and run `hypnomix takes` to rank them.",
                       "For doubles and harmonies, the HypnoMix Align panel (`hypnomix reaper align`) lines a stack up into a new project."],
            "ardour": ["Export the takes from the same start and run `hypnomix takes`; `vocalign` makes aligned copies to import."]},
       action={d: dict(kind="level") for d in ALL}),
  dict(id="hm-mixing", title="Mixing helpers", daws=ALL,
       say=["`stems` shows what each part contributes and its role; `masking` finds parts fighting over the same "
            "frequencies (your priority wins); `prep` and `automix` make many moves at once, so run them with `--plan` and "
            "review each move. `chain strips` (in Live or REAPER) loads your DAW's own EQ, compressor and utility with the recipe's settings, "
            "and, in a Live set, `motion` offers effect moves for repetitive sections, learned from your own automation."],
       how={"live": ["`hypnomix chain strips recipe.json --dry-run` shows the plan; drop --dry-run to load EQ Eight, Compressor and Utility on each track."],
            "reaper": ["`hypnomix chain strips recipe.json --reaper --dry-run` shows the plan; without --dry-run it builds the same strips in the open REAPER from ReaEQ and ReaComp. recipe.json is written by `hypnomix automix`."],
            "ardour": ["Run `stems`, `masking`, `prep` and `automix` on exported stems; set the moves by hand in HypnoMix Studio (`motion` needs a Live set, and `chain strips` needs Live or REAPER)."]}),
  dict(id="hm-master", title="The mastering chain", daws=ALL,
       say=["On the master device, **Build chain** puts your DAW's own plug-ins before it: Tone (EQ, low cut 25 Hz, "
            "everything else at 0 dB), Glue (2:1, slow attack, never more than 3 dB), Tame and Warmth (switched off until "
            "needed), Width (bass mono below 120 Hz) and the Limiter (ceiling from the song card). In Live, play "
            "the loudest part yourself, then press **Match target**: it turns the limiter until the master hits the card's target LUFS "
            "(in REAPER it starts playback itself and stops what it started). **Save** keeps any chain, "
            "yours included, as a template.",
            "Offline, `hypnomix master mix.wav --plan` turns each stage into a finding to approve, with test AAC and MP3 "
            "copies to keep the true peak safe."],
       how={"live": ["HypnomixMain → Mastering chain → Build chain (needs Live 12.3+): an Audio Effect Rack called HypnoMix Master, editable."],
            "reaper": ["HypnoMix Main's window → Build chain / Match target / Save chain (needs the bridge), or `hypnomix reaper chain build`."],
            "ardour": ["Export the mix and run `hypnomix master mix.wav --plan` (Tools tab → master)."]},
       action={d: dict(kind="chain") for d in LR}),
  dict(id="hm-export", title="Review before export", daws=ALL,
       say=["The last check: **Record and review before export** on the master device plays the song while every probe "
            "listens, then reviews the master against the song card: loudness and true peak, `qc`, `translate` (phone, mono, "
            "codecs) and `master --plan`. Fix any FAIL before you deliver."],
       how={"live": ["HypnomixMain → Record and review before export. Live's own Export makes the final file."],
            "reaper": ["HypnoMix Main → Record and review before export (or `hypnomix reaper record`): REAPER renders exactly what played and the app reviews it."],
            "ardour": ["Export the master, then run `qc` and `translate` on it from the Tools tab."]},
       app=dict(view="tools", label="Open the Tools tab")),
  dict(id="hm-ai", title="Working with an AI (optional)", daws=ALL,
       say=["Everything above works with no AI. If you'd like one: the **Assistant** tab runs the same loop by chat with your "
            "own key from an AI service (some have a free tier) or a model on your computer, and asks before anything "
            "writes. A desktop AI coding assistant works through whole songs from the AI agent folder, with the "
            "first-pass, mix, mastering and tracking skills. Setup → How you work switches between them."],
       app=dict(view="chat", label="Open the Assistant")),
 ])


_ORDER = [s["id"] for s in CHAPTER["steps"]] + [s["id"] for s in ch13_hypnomix_steps.STEPS]
CHAPTER["steps"] = enrich(place(CHAPTER["steps"] + az_only(ch13_hypnomix_steps.STEPS), _ORDER), ch13_hypnomix_steps.ENRICH)
