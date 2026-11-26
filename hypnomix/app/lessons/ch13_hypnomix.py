"""Chapter: hypnomix in your DAW."""
from hypnomix.app.lessons._common import ALL, LR

CHAPTER = dict(id="hypnomix", levels=("tour", "101", "az"), title="hypnomix in your DAW", sub="the app, the devices, and the loop: scan, hear, decide, apply", steps=[
  dict(id="hm-loop", title="How hypnomix works", daws=ALL,
       say=["hypnomix is a second engineer that never touches your original. Every job follows one loop: **preferences → "
            "scan → review → apply → listen**. The scan is read-only; the review lists each finding with a proposed fix and, "
            "where it can, a before and after to hear; you approve or skip; Apply writes only what you approved into a "
            "**new** set or project (or new audio files) next to yours.",
            "Taste stays yours. It finds technical things (clicks at edits, level jumps between takes, flat notes, "
            "masking, hum, loudness and true peak) and proposes gentle, partial fixes. Timing and tuning keep the human "
            "feel: nothing is quantised or hard-tuned, and a protected track is never changed without asking again."],
       how={"live": ["Answer the Preferences tab once (targets, protected tracks, how much to explain): every proposal starts from it."],
            "reaper": ["Answer the Preferences tab once: every proposal starts from it."],
            "ardour": ["Answer the Preferences tab once: every proposal starts from it."]},
       app=dict(view="prefs", label="Open Preferences")),
  dict(id="hm-connect-live", title="Connect hypnomix to Live", daws=("live",),
       say=["Two links, both optional for scanning a saved set. **AbletonOSC** (a control surface script) lets hypnomix "
            "drive the open set: arm and route tracks, punch-record, load Live's own devices, play bars. The **Max for Live "
            "devices** measure inside Live and follow the review; they need Max for Live (Suite, or the add-on) and the "
            "app running."],
       how={"live": ["Setup → Ableton Live copies the AbletonOSC script into your User Library (or `hypnomix install`). Restart Live.",
                     "Live → Settings → Link, Tempo & MIDI → Control Surface: **AbletonOSC**.",
                     "Keep the hypnomix app open while you work: the devices talk to it."]},
       action={"live": dict(kind="devices")}),
  dict(id="hm-connect-reaper", title="Connect hypnomix to REAPER", daws=("reaper",),
       say=["The **bridge** is a script that runs inside the open REAPER: nothing is installed and no setting changes, and "
            "every change it makes is one undo step named \"hypnomix: …\". The **JSFX** (Hypnomix Probe and Hypnomix Main) "
            "measure inside REAPER and carry the song card and the mastering chain buttons."],
       how={"reaper": ["`hypnomix reaper start` (or Setup → REAPER) runs the bridge, opening REAPER if it's closed.",
                       "`hypnomix reaper probes install` copies the JSFX into REAPER's Effects/hypnomix (the button below does it)."]},
       action={"reaper": dict(kind="devices")}),
  dict(id="hm-connect-ardour", title="hypnomix with Ardour", daws=("ardour",),
       say=["hypnomix reads Ardour 3 to 9 sessions (tracks, buses, regions with Ardour's layering, fades, gain envelopes, "
            "plug-ins, automation), renders each track itself, and runs the same first-pass checks. It can't write a new "
            "session or drive the open Ardour yet: session changes come back as a list for you to make, and audio fixes "
            "(tuning, de-hiss, de-ess) as repaired files to bring in.",
            "The reader hasn't been checked against a running Ardour yet: if a render sounds different from Ardour's export, say so."],
       how={"ardour": ["Save the session. On the Songs tab, choose the session folder (or its .ardour file) and Scan.",
                       "Ardour can stay open: nothing is written next to your session."]}),
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
       say=["**Hypnomix Probe** (last on each track) and **Hypnomix Main** (on the master) are the same meters as Live's "
            "devices, as REAPER effects: each probe holds what the track is, its priority and Protect; Main holds the song "
            "card (genre, key, scale, limiter character, target, ceiling, amount) and the buttons for the mastering chain "
            "and Record and review. The **Hypnomix panel** (`hypnomix reaper review`) steps through the app's review "
            "inside REAPER with A / B / Blind."],
       how={"reaper": ["`hypnomix reaper probes insert \"Song.rpp\"` writes \"Song (probes).rpp\" with a probe on every track and Main on the master (or Add FX → JS → Hypnomix Probe by hand).",
                       "With the bridge running and the app open, the app's Live tab shows every probe while REAPER plays; Record → play → Stop makes a review from what was heard.",
                       "When the bridge starts it gives each probe a slot number, so REAPER may ask to save once."]}),
  dict(id="hm-scan", title="The first pass: scan and review", daws=ALL,
       say=["On the **Songs** tab choose the saved set, project or session (or a folder of stems from any DAW), add a bounce of the "
            "mix if you have one (loudness, release checks, the key) and Scan. Every check runs in parallel and nothing "
            "changes. **Deep scan** also renders every track for frequency fights and mic phase.",
            "The review lists findings by severity. **Approve**, **Skip** or **Change** (with a note) each; *Approve all "
            "low* is there for the small ones. Checks that didn't run are listed at the top: no finding there means nothing."],
       how={"live": ["Save the set first: the scan reads the saved .als.", "Give the key on the Songs tab or the song card before any vocal tuning is applied."],
            "reaper": ["Save the project: the scan reads the .rpp and finds files the way REAPER does."],
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
            "reaper": ["`hypnomix abset scan/Song`, open \"Song (A-B).rpp\", then `hypnomix reaper review` for the Hypnomix panel."]}),
  dict(id="hm-apply", title="Apply, history and undo", daws=ALL,
       say=["**Apply** writes only the approved fixes: a new set or project next to the original (close it in the DAW "
            "first), or repaired copies in the scan's fixed folder for audio. Every applied version is kept; undo writes "
            "another new version, it never deletes. Teach it as you go: what you skip and change shapes the next proposals."],
       how={"live": ["Close the set in Live, Apply, then open \"Song (fixed).als\"."], "reaper": ["Close the project tab, Apply, then open the new .rpp (tuned vocals arrive as new takes)."],
            "ardour": ["Apply lists the session changes to make by hand; repaired audio lands in the scan's fixed folder."]}),
  dict(id="hm-tracking", title="Tracking helpers", daws=ALL,
       say=["Before you record, `hypnomix soundcheck` listens to an interface input and tells you which way to turn the "
            "gain (peaks -12 to -6 dBFS in 24-bit), and flags noise, hum and DC. After recording, `takes` ranks whole "
            "takes and lists the best one per section, `vocalign` sits doubles and harmonies with the lead (gently: halfway "
            "toward the group, never forced onto the lead), and `clipmatch` evens out takes recorded on different days."],
       how={"live": ["`hypnomix live arm`, `live input`, `live record 17 8 3` punch-record through AbletonOSC (three passes = three take lanes).",
                     "Live 12's take lanes + `takes` for the comp; Hypnomix Align for stacks."],
            "reaper": ["Record takes as usual; export them from the same start and run `hypnomix takes`."],
            "ardour": ["Export the takes from the same start and run `hypnomix takes`; `vocalign` makes aligned copies to import."]},
       action={d: dict(kind="level") for d in ALL}),
  dict(id="hm-mixing", title="Mixing helpers", daws=ALL,
       say=["`stems` shows what each part contributes and its role; `masking` finds parts fighting over the same "
            "frequencies (your priority wins); `prep` and `automix` make many moves at once, so run them with `--plan` and "
            "review each move. `chain strips` loads your DAW's own EQ, compressor and utility with the recipe's settings, "
            "and `motion` offers effect moves for repetitive sections, learned from your own automation."],
       how={"live": ["`hypnomix chain strips recipe.json --dry-run` shows the plan; drop --dry-run to load EQ Eight, Compressor and Utility on each track."],
            "reaper": ["`hypnomix chain strips` builds the same strips from ReaEQ and ReaComp."],
            "ardour": ["Run them on exported stems; set the moves by hand in Ardour."]}),
  dict(id="hm-master", title="The mastering chain", daws=ALL,
       say=["On the master device, **Build chain** puts your DAW's own plug-ins before it: Tone (EQ, low cut 25 Hz, "
            "everything else at 0 dB), Glue (2:1, slow attack, never more than 3 dB), Tame and Warmth (switched off until "
            "needed), Width (bass mono below 120 Hz) and the Limiter (ceiling from the song card). **Match target** plays "
            "the loudest part and turns the limiter until the master hits the card's target LUFS. **Save** keeps any chain, "
            "yours included, as a template.",
            "Offline, `hypnomix master mix.wav --plan` turns each stage into a finding to approve, with test AAC and MP3 "
            "copies to keep the true peak safe."],
       how={"live": ["HypnomixMain → Mastering chain → Build chain (needs Live 12.3+): an Audio Effect Rack called Hypnomix Master, editable."],
            "reaper": ["Hypnomix Main's window → Build chain / Match target / Save chain (needs the bridge), or `hypnomix reaper chain build`."],
            "ardour": ["Export the mix and run `hypnomix master mix.wav --plan` (Tools tab → master)."]},
       action={d: dict(kind="chain") for d in LR}),
  dict(id="hm-export", title="Review before export", daws=ALL,
       say=["The last check: **Record and review before export** on the master device plays the song while every probe "
            "listens, then reviews the master against the song card: loudness and true peak, `qc`, `translate` (phone, mono, "
            "codecs) and `master --plan`. Fix any FAIL before you deliver."],
       how={"live": ["HypnomixMain → Record and review before export. Live's own Export makes the final file."],
            "reaper": ["Hypnomix Main → Record and review before export (or `hypnomix reaper record`): REAPER renders exactly what played and the app reviews it."],
            "ardour": ["Export the master, then run `qc` and `translate` on it from the Tools tab."]},
       app=dict(view="tools", label="Open the Tools tab")),
  dict(id="hm-ai", title="Working with an AI (optional)", daws=ALL,
       say=["Everything above works with no AI. If you'd like one: the **Assistant** tab runs the same loop by chat with your "
            "own key (Gemini's free tier, Claude, OpenRouter, OpenAI) or a model on your computer, and asks before anything "
            "writes. An agent app (Claude Code, Codex, Cursor) works through whole songs from the AI agent folder, with the "
            "first-pass, mix, mastering and tracking skills. Setup → How you work switches between them."],
       app=dict(view="chat", label="Open the Assistant")),
 ])
