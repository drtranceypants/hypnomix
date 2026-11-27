# Lessons: the mistakes behind the rules

HypnoMix was built while mixing real songs with an AI agent, and most of its rules exist because something went
wrong once. If you are an agent, read this as a list of traps you will walk into too. Each entry: what
happened, why, and what to do instead. Where the tools now enforce the lesson, it says so.

## Changing things in a set

1. **A restore wiped a fade-out.** Putting mixer values back from a snapshot set an automated control, which
   overrode its envelope; the song's fade was missing from the next export.
   *Do:* list automation before setting any control (`hypnomix automation list`), restore only what you
   changed, run `hypnomix live reenable` after Live edits, and compare the export with the previous bounce.
2. **Deliberate automation looked like a defect.** A reverb whose decay was automated from 17 s to 60 s over the
   outro is a choice, not a bug.
   *Do:* treat existing automation, effects and levels as intent. Ask the person what is deliberate
   (`hypnomix prefs`, `protect.notes`); it is shown on every review.
3. **A taste change was applied without asking.** Ducking the vocal delays made the mix "cleaner" and removed
   exactly the lush chorus delays the artist loved. It was reverted.
   *Do:* reverb, delay, tone, vocal level and tuning amount are always asked, one at a time, with an A/B.
4. **A "revert" didn't revert everything.** An A/B helper put the faders back but not the device parameters it
   had changed.
   *Do:* a tool that offers undo must undo everything it touched, and the undo must be tested.
5. **Ids pointed at the wrong thing.** Finding ids are positions in a list. After one fix was applied, the list
   was one shorter and "the fifth finding" was a different clip.
   *Now enforced:* `fix` looks every approved finding up again by track, kind and position in the set it is
   about to write, and skips what it cannot find. If you call `smooth`/`timing`/`distortion --apply` yourself,
   take the ids from a fresh report on that exact set.
6. **Findings went stale.** A set saved again after the scan no longer matches its findings.
   *Now enforced:* `fix` stops when the set is newer than the scan.

## Knowing what you are looking at

7. **Wrong track role, wrong fix.** Clips with a very large clip gain were turned down as if they were vocals;
   they were violin parts, and it had to be undone.
   *Do:* confirm what a track is (`hypnomix name`, then ask when unsure) before proposing anything on it.
8. **The noise was blamed on the wrong source.** Hiss heard "on the vocals" was coming from a string group.
   *Do:* render or solo the suspects and measure each before fixing anything.
9. **Clip gain raised the noise.** Hiss appeared exactly where heavily boosted clips came in: +20 dB of clip gain
   is +20 dB of noise floor.
   *Do:* when a part is boosted a lot, check the noise under it; clean the take (`dehiss`) before the gain.
10. **Two "problems" were tool bugs.** Odd numbers were reported as mix problems; the measurements were wrong.
    *Do:* when a number looks strange, check the measurement first: another tool, a shorter range, the raw file.
11. **A failed check read as "clean".** A check that crashed produced no findings, and no findings looked like
    good news.
    *Now enforced:* failed checks are listed in the review under "did NOT run", and the scan prints them.

## Working with Live and with people

12. **Two agents drove Live at once and it crashed.** One opened a file while another was loading a set.
    *Do:* one driver at a time. Ask before opening, saving or quitting anything in Live.
13. **Automation that needs the screen stops when the screen locks.** An overnight job stalled at a dialog.
    *Do:* prefer tools that read and write files. Live is the last resort, and never unattended.
14. **Restarting Live is expensive for the person.** They asked for it to be a last resort.
    *Do:* reach for clip gain, file tools and offline set edits before anything that needs a restart.
15. **A feature was described before it was tried.** The person went looking for a menu option that wasn't
    there.
    *Do:* say what you verified and what you assume. `chain` and `clipmatch --als --apply` stayed marked
    untested until they had run in Live (where `chain` turned out to set one control wrongly).
16. **A fix was approved, failed quietly, and the problem stayed.** Nobody measured afterwards.
    *Now enforced:* `fix` measures the new set again and reports "no longer measured" or "still measured";
    failures set exit code 1. Report exactly that.
17. **A fallback ran silently.** A repair's main method failed and a cruder one took over without saying so.
    *Do:* a report names the method that actually ran.
18. **Assumed what the person owns.** Advice was given for tools they only had on trial.
    *Do:* ask (`hypnomix prefs`, `tools.plugins`); propose only what they have. This repo names free tools only.
19. **Read-only commands left files around.** A report mode wrote JSON into the working folder.
    *Do:* read-only commands write only into their report folder.

## Finishing

20. **"Done" was declared before the whole export was checked.** The spot was fixed; the intro level had moved.
    *Do:* after a pass, compare a full export with the previous one: length, intro and fade loudness, true peak.
21. **Lossy encodes clipped.** A master that was fine as WAV overshot after AAC encoding; dense masters can need
    2 dB or more of true-peak headroom.
    *Do:* `hypnomix translate` and `qc` on every master; `master` lowers its own ceiling when a test encode clips.
22. **A batch cost far more than one job suggested.** Not audio, same lesson: time one track before a whole
    song, and say how long the full run will take.

## Building and testing HypnoMix itself

Found in the final review of the work after the public release. Each is a trap for the next person who changes the code.

23. **A test instance still reached the real home folder.** Setting only `HYPNOMIX_HOME` is not enough: code that asks
    the system for the user's home (the plug-in folders, `~/Documents`, the library scan) ignores it.
    *Do:* a test instance sets `HOME` as well as `HYPNOMIX_HOME` (and the app's own folders), and a test of anything that
    writes checks that nothing landed outside the scratch folder.
24. **A bare smoke test of an install or device command acts on the real machine.** `install`, `device`, `aligndevice`,
    `probe device` and `chain` write into a User Library or drive a DAW, and running one with no arguments to see "that it
    still starts" does exactly that.
    *Do:* never smoke-test those commands bare. Use `-h` or `--dry-run`, in a scratch home, with the DAW closed.
25. **The de-esser got louder.** A band split built on a causal crossover (one that shifts phase) made the automix
    de-esser louder instead of quieter.
    *Do:* split bands with a zero-phase filter, and test the level of the band after the move, not only that it ran.
26. **A silent fallback hid a bug.** A sign error in the novelty curve meant no section change was ever found, and the
    song was cut into even slices without a word, so the result looked plausible.
    *Do:* a fallback says it is a fallback ("no clear section changes were found, so the song is cut into equal
    slices"), and a test makes sure the real path is the one that runs on a case it should find.
27. **Decisions followed positions, not findings.** Decisions were kept by finding number, and after a re-scan the list
    had shifted, so "approve" landed on a different clip.
    *Now enforced:* a decision is keyed by what the finding is (tool, track, kind and place); one that matches nothing is
    counted, set aside in a file and never applied. Key by identity wherever a list can change under you.
28. **A deny-list gate was walked around.** The Assistant was kept from running risky commands by a list of forbidden
    ones, and a flag written in its short, abbreviated form (the command-line parser accepts any unique start of a flag)
    was not on the list, so it got through.
    *Now enforced:* commands run without a click only from a read-only allow-list, per command; an option that is not
    listed for it, abbreviated or not, is refused. Gate with what is safe, never with what is not.

## The pattern

Almost every entry is one of four things: acting before asking, trusting a number that wasn't checked, changing
something that was a choice, or calling something done without measuring it again. The loop in `AGENTS.md`
(preferences → scan → review → apply → verify → listen) is built to make those four hard to do. Entries 23 to 28 are
a fifth, for people who change HypnoMix itself: a test, a fallback or a gate that looks as if it did its job and did not.

Found a new trap? Add it here, in the same three lines, and add the rule to `AGENTS.md` if it is general.
