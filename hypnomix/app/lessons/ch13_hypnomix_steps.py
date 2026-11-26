"""hypnomix in your DAW: teaching fields (mistakes, try, quiz, more) added to the steps in ch13_hypnomix.py."""

STEPS = []


def _q(q, options, answer, why):
    return dict(q=q, options=options, answer=answer, why=why)


ENRICH = {
 "hm-loop": {
     "mistakes": ["Expecting hypnomix to change your original. It never does: Apply writes a new set, project or files next to yours.",
                  "Skipping the Preferences tab. Every proposal starts from it, so answer it once and honestly."],
     "try": dict(do="Open the Preferences tab and answer it. Say out loud, in order, the five words of the loop.",
                 success="You can say: preferences, scan, review, apply, listen, and you know the scan changes nothing."),
     "quiz": [_q("Which part of the loop writes anything?", ["Scan", "Apply, and only what you approved", "Review"], 1,
                 "The scan is read-only and the review only lists findings. Apply writes the approved fixes into a new set, project or files.")],
     "more": ["step:hm-scan", "step:hm-apply"]},
 "hm-connect-live": {
     "mistakes": ["Forgetting to restart Live after the AbletonOSC script is copied.",
                  "Closing the hypnomix app while the devices are open: the devices talk to it, so keep it open while you work."],
     "try": dict(do="Open Live's settings window, go to the Link, Tempo and MIDI tab and look at the Control Surface list.",
                 success="AbletonOSC is chosen as a control surface, and you know the Max for Live devices need Max for Live."),
     "quiz": [_q("Which of the two links is needed to scan a saved set?", ["Neither: both are optional", "AbletonOSC", "The Max for Live devices"], 0,
                 "The step says both links are optional for scanning a saved set. They add driving the open set and measuring inside Live.")],
     "more": ["step:hm-devices-live"]},
 "hm-connect-reaper": {
     "mistakes": ["Thinking the bridge installs something in REAPER. It is a script that runs inside the open REAPER; nothing is installed and no setting changes.",
                  "Forgetting to install the JSFX. `hypnomix reaper probes install` copies them into REAPER's Effects/hypnomix."],
     "try": dict(do="Start the bridge with `hypnomix reaper start` (or Setup → REAPER). Then make a small change through hypnomix and look at REAPER's Undo menu.",
                 success="The change shows as a single undo step named \"hypnomix: …\"."),
     "quiz": [_q("How does an action made by the bridge appear in REAPER's undo history?", ["It can't be undone", "As one undo step named \"hypnomix: …\"", "As many small steps"], 1,
                 "Every change the bridge makes is one undo step named \"hypnomix: …\".")],
     "more": ["step:hm-devices-reaper"]},
 "hm-connect-ardour": {
     "mistakes": ["Expecting hypnomix to change everything in an Ardour session, or to drive the open Ardour. It writes a new snapshot for fades, region gain, dips and fader, pan and mute moves only. Names, order, stacks, timing and sidechain come back as a list for you to make by hand.",
                  "Forgetting to save the session before you scan it."],
     "try": dict(do="Save your session, choose the session folder on the Songs tab and press Start the first pass.",
                 success="You get a review, your session is unchanged, and any audio fixes arrive as repaired files to import."),
     "quiz": [_q("How do fixes come back for Ardour?", ["Everything is written into your own session file", "Fades, gain, dips and fader, pan and mute moves go into a new snapshot; the rest is a list to do by hand, and audio fixes are repaired files", "They don't"], 1,
                 "Apply writes a new snapshot beside your session for fades, region gain, dips and fader, pan and mute moves. Track names and order, stacks, timing and sidechain stay a list for you, and audio fixes (tuning, de-hiss, de-ess) are repaired files to bring in. Your own session file is never changed.")],
     "more": ["step:hm-scan"]},
 "hm-devices-live": {
     "mistakes": ["Dragging the devices by hand on every track. Tick Live devices at the first pass (or run `hypnomix probe insert`) and it writes a new set with them already in place.",
                  "Leaving each track's What it is, Priority and Protect unset and then wondering why proposals differ from what you want. Set them, or leave What it is on auto."],
     "try": dict(do="Run the first pass with Live devices ticked on a copy of a song, and open \"Song (hypnomix devices).als\".",
                 success="Each track, group and return has a probe at the end, and HypnomixMain is on Main."),
     "quiz": [_q("Where does HypnomixProbe sit on a track?", ["First, before the plug-ins", "Last, after all its plug-ins", "Only on Main"], 1,
                 "It is last on every track, return and group, so it measures what the track sounds like after all its plug-ins.")],
     "more": ["step:hm-scan", "live"]},
 "hm-devices-reaper": {
     "mistakes": ["Adding Hypnomix Probe in the middle of a chain. It goes last on each track, so it measures after all the effects.",
                  "Being surprised when REAPER asks to save once: the bridge gives each probe a slot number when it starts."],
     "try": dict(do="Run `hypnomix reaper probes insert \"Song.rpp\"` on a copy of a project and open the new \"Song (probes).rpp\".",
                 success="Every track has a probe and the master has Hypnomix Main."),
     "quiz": [_q("What does `hypnomix reaper probes insert` write?", ["Changes to your original .rpp", "A new \"Song (probes).rpp\"", "Nothing, it only reports"], 1,
                 "It writes \"Song (probes).rpp\" with a probe on every track and Main on the master. Your original is not changed.")],
     "more": ["step:hm-connect-reaper", "reaper"]},
 "hm-scan": {
     "mistakes": ["Scanning without saving the set: the scan reads the saved file, so unsaved changes are not in it.",
                  "Reading an empty review as a clean bill of health. Checks that didn't run are listed at the top: no finding there means nothing.",
                  "Giving the key only after vocal tuning has been applied. Give it first."],
     "try": dict(do="Run the first pass on a saved song, then open the review and approve one small finding, skip one, and leave the rest.",
                 success="Nothing in your song changed, and you know which checks ran and which didn't."),
     "quiz": [_q("What does the scan change in your song?", ["Nothing: it only reads", "Only the small findings", "Levels, if you approve"], 0,
                 "Every check runs in parallel and nothing changes. Only Apply writes, and only what you approved.")],
     "more": ["first-pass", "step:hm-ab"]},
 "hm-ab": {
     "mistakes": ["Judging a fix without Match on: a louder B often sounds better only because it is louder. Turn Match on so B plays at A's loudness.",
                  "Thinking the A/B set is the fixed version. It is only for listening: Apply always writes from your original."],
     "try": dict(do="Build an A/B set for a song, switch A and B on one finding, then try Blind.",
                 success="You can say which of X and Y you preferred before you saw which was which, and your picks show in the review."),
     "quiz": [_q("What does Match do?", ["Makes B play at A's loudness", "Applies the fix", "Lines up the timing"], 0,
                 "With Match on, B plays at A's loudness, so you compare the change and not the volume.")],
     "more": ["step:hm-apply"]},
 "hm-apply": {
     "mistakes": ["Applying while the set is open in the DAW. Close it first.",
                  "Looking for the change in your original. Apply writes a new set or project next to it, and repaired audio goes in the scan's fixed folder."],
     "try": dict(do="Approve one fix and Apply, then open the new set or project beside the original.",
                 success="The original is untouched and the new version holds only the approved fix."),
     "quiz": [_q("What does undo do in the history?", ["Deletes the latest version", "Writes another new version", "Restores the original file over the top"], 1,
                 "Every applied version is kept, and undo writes another new version. It never deletes.")],
     "more": ["step:hm-scan"]},
 "hm-tracking": {
     "mistakes": ["Setting gain by feel. `hypnomix soundcheck` listens to an input and tells you which way to turn the gain (peaks -12 to -6 dBFS in 24-bit).",
                  "Forcing doubles and harmonies onto the lead. With two or more parts, `vocalign` is gentle by default: only words clearly off the group are moved most of the way, the rest barely at all."],
     "try": dict(do="Run `hypnomix soundcheck` on an interface input while you sing or play your loudest.",
                 success="It tells you whether to raise or lower the gain, and your peaks sit between -12 and -6 dBFS."),
     "quiz": [_q("Which command ranks whole takes and lists the best one per section?", ["takes", "clipmatch", "soundcheck"], 0,
                 "`takes` does this after recording. `soundcheck` sets the gain before, and `clipmatch` evens out takes recorded on different days.")],
     "more": ["step:hm-mixing"]},
 "hm-mixing": {
     "mistakes": ["Running `prep` or `automix` without `--plan`. They make many moves at once, so review each one first.",
                  "Letting a masking finding choose for you. It finds parts fighting over the same frequencies, and your priority wins."],
     "try": dict(do="Run `hypnomix automix` on a folder of stems (it writes new files, including recipe.json, and leaves your stems alone), then run `hypnomix chain strips recipe.json --dry-run` (add --reaper in REAPER) on a copy of your project and read the plan before loading anything.",
                 success="You can read which devices would go on each track, and nothing was loaded."),
     "quiz": [_q("What does `--dry-run` do on `chain strips`?", ["Loads the devices quietly", "Shows the plan without loading", "Removes the devices"], 1,
                 "It shows the plan. Drop --dry-run to load the DAW's own EQ, compressor and utility on each track.")],
     "more": ["step:hm-master"]},
 "hm-master": {
     "mistakes": ["Guessing at the limiter gain instead of measuring. Play the loudest part and press Match target (or watch a loudness meter): it turns the limiter until the master meets the card's target LUFS.",
                  "Leaving the song card empty: the chain's ceiling and target come from it."],
     "try": dict(do="Fill in the song card, then Build chain, then Match target on a copy of a song.",
                 success="The chain sits before the master device, each stage can be edited, and the master meets the card's target."),
     "quiz": [_q("What does the Glue stage of the chain use?", ["2:1, slow attack, never more than 3 dB", "10:1, fast attack", "No compression"], 0,
                 "Glue is set to 2:1, slow attack, and never more than 3 dB of reduction.")],
     "more": ["mastering", "step:hm-export"]},
 "hm-export": {
     "mistakes": ["Delivering with a FAIL still in the review. Fix any FAIL first.",
                  "Skipping the review because the master sounded fine at your desk. It also checks true peak, phone, mono and codec behaviour."],
     "try": dict(do="Run Record and review before export on a finished master, and read the result.",
                 success="You know which checks passed and which, if any, need fixing before you deliver."),
     "quiz": [_q("When should you fix a FAIL in the final review?", ["Before you deliver", "After you deliver", "Never"], 0,
                 "The review is the last check, so fix every FAIL before you deliver the file.")],
     "more": ["mastering"]},
 "hm-ai": {
     "mistakes": ["Thinking you need an AI to use hypnomix. Everything works with none.",
                  "Letting an assistant write without checking. It asks before anything writes: read what it asks."],
     "try": dict(do="Open the Assistant tab and ask it to explain one finding in a review, without applying anything.",
                 success="You get an explanation and nothing in your song or set changed."),
     "quiz": [_q("Is an AI required to use hypnomix?", ["No: everything works without one", "Yes, for the review", "Yes, for Apply"], 0,
                 "The step says everything works with no AI. An AI assistant is optional and asks before anything writes.")],
     "more": ["step:hm-loop"]},
}
