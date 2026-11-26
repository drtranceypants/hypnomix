# The app and the Live device

Two ways to do the whole first pass by clicking, without an AI: a web app on your own computer (which you
can optionally build into a Mac app), and a device inside Ableton Live. Both drive the same commands the rest of this guide describes, and the same
rules hold: the scan changes nothing, you decide each item, approved fixes go into a new set.

## The web app

```bash
hypnomix app            # opens http://127.0.0.1:8791 in your browser
```

That is all it takes: the app is a page served from your own computer. Leave the terminal window open while
you use it; Ctrl-C stops it.

| screen | what you do there |
|---|---|
| Songs | choose a Live set (.als), a REAPER project (.rpp), an Ardour session (.ardour) or a folder of recordings from any DAW, with the chooser or by pasting the path (on every system); optionally a bounce of the mix, a song you love, the key (the browser remembers this form, and the tab and review you were on, so a refresh puts you back). "Start the first pass" runs `scan`, then `ab`. Each song has its own scan folder: the same path always goes back to it (a re-scan), a different path never shares one even with the same name (`Song`, `Song (2)`), and a card shows its folder when two songs share a name. **Re-scan** on a card runs the scan again; a Live set keeps your decisions (`scan --since`), the other kinds set the old answers aside in `decisions before re-scan.json`. A song whose results or decisions file is damaged stays in the list with a red tag. With no songs yet, **Try it on a demo song** (when `hypnomix demo` exists) makes a short demo song in the app's folder and scans it |
| Activity | how far the command has got, from what it prints (never a percentage): a scan says "4 of 12 checks done", which checks are still running and, when an earlier scan of the song exists, about how long is left from that scan's own seconds (a first scan shows the time so far and says there is no estimate); the clip builder and an apply show their steps. Then the log of each command as it runs, with a Stop button that ends the command and everything it started (each job runs in its own process group), removes the temporary `(fix step N)` sets a stopped fix left, and lists the files a finished job made, each with a Show-in-folder button. A failed job says why in the command's own words |
| Review | the fixes you can hear first, by severity (then the ones with no clip yet, then questions for you); by-hand and info items wait in a collapsed **By hand in your DAW** section with the handoff button, outside the approve / skip flow. A filter row (All, Undecided, Approved, Skipped, To change, By hand, and by tool) is remembered per song. Each card has one player with **A** and **B** buttons that swap the clip at the same moment. Approve, Skip or Change with a note, at the keyboard (see below) or with the mouse; a decision changes only its own card, the counts and the Apply card, never the list, so the clip you are hearing and your place on the page stay. It remembers which clips you played: the bar says "12 approved, 5 of them never played" and an approval with a clip you never heard is marked on its card (it never blocks a decision). **Approve all low…** and **Approve the N like this** show the whole list first (id, track, what, whether it has a preview, whether you played it) and record nothing until you confirm; "all low" never takes tuning, harmony balance, motion, colour, borrowed moves or variations (taste calls), a track reorder, removal or merge, a protected track or a by-hand item. Saved as you act. Steps that are **on by default** (track order, removing switched-off tracks, one instrument onto one track) show "On by default" and **Turn off** (it records a skip); banners say if the project was saved after the scan, or the original is missing. **Re-scan** and **Make the handoff list** (`hypnomix handoff`: a checklist and a marker at every by-hand spot) are in the header. A damaged `decisions.json` shows what was lost and, if `decisions.json.bak` exists, **Restore the backup** (the damaged file is kept as `decisions.damaged.json`) |
| Apply | says first what will happen: how many approved fixes, which on-by-default steps also run and what each does (the archive copy it writes and how many tracks it removes), how many approved items are by hand and will **not** be applied, and the exact file names it will create. The new file takes the ending of the project (`.als`, `.rpp`, `.ardour`; nothing for a folder, whose repaired copies go to the scan's `fixed` folder), is named `Song (fixed).als`, then `Song (fixed 2).als` if that is taken, and the name can be edited. Apply is enabled only when something can really be written; a by-hand-only selection offers the handoff list instead. Then it writes only that (`fix --approved`) |
| Result | after an apply: the new file and its folder with a Show button, what was applied, what was not and why, any FAILED line in red, "listen at these spots" from the applied findings, and buttons: open the review again, **Undo this**, make the handoff list. The log is shown as text under its own headings (not applied, on by default, failed), whatever those say |
| History | a collapsed section of the review (`hypnomix history DIR --json`): every apply of the song, with **Undo** (`history --undo N`, after a confirm that names the file it will write) for Live sets. REAPER projects, Ardour sessions and folders keep no snapshot, so the page says so instead of offering a button |
| Preferences | the questions asked once: targets, protected tracks, what is deliberate |
| Tools | every other command with its help and a form: tempo, variations, mastering, and the rest |
| Updates | the version at the top right: checks for a new version (once a day, or now), and in the installed app **Update now** downloads it, checks its fingerprint (against the release's own list: this catches damage or a swapped file, not a hijacked release, as installers aren't yet signed with a publisher key) and installs it with one click. Source installs are told to `git pull` |
| Disk care | the free space at the top right: hypnomix clears its own bulky leftovers (render cache, audio in scans idle two weeks, hypnomix-out audio, old master bounces) weekly, and straight away when the disk is nearly full. Preview, clean now, switch it off, or also move old Desktop / Downloads WAVs to a 14-day holding folder. Audio a Live, REAPER or Ardour project uses is never touched. Folders you add must be inside your home folder (not the home folder itself, Library, or all of Music, Desktop or Documents) |
| Teacher | teacher mode: a guided course in your DAW (Live, REAPER or Ardour). The **tour** of hypnomix and its devices for people who already engineer, the **101 crash course** (the words, recording to a click, each effect, mastering), or **The complete course, A to Z** (13 chapters, about 145 lessons per DAW: sound and hearing, digital audio, gear and rooms, recording, editing, mixing, mastering, releasing, troubleshooting and cheat sheets, with common mistakes, exercises, self-marking quizzes, **Hear it** audio examples made on the spot by `hypnomix/app/teach_audio.py` (cached in `~/.hypnomix/cache/teach`), and a searchable **Glossary**; the 101 course is a subset of it). The lessons are the package `hypnomix/app/lessons/` (one module per chapter) and are also the wiki's per-chapter course articles. Hands-on steps in Live and REAPER (tempo, click, a drum beat, an armed track, effects, the mastering chain) each wait for **Do it**. Progress in `~/.hypnomix/teacher.json` |
| Assistant | a chat with an AI of your choice that runs hypnomix for you (bring your own key; Claude Sonnet 5.5 is the default model, every other model stays selectable) and, optionally, a Listener that hears a bounce. Shows the tokens and cost as you go (exact for Claude, an estimate for Gemini), clears old results from what it re-reads as a long chat grows, asks "keep going?" when one message uses more than 400,000 input tokens (a setting), and stops if it repeats the same call three times. Anything that writes waits for your click. Details: the wiki's "The Assistant and the Listener" |
| Setup | the guided setup (it opens by itself the first time): how you work (just the app, an AI key, a model on this computer, or a desktop AI app such as Claude Code), your DAW and teacher mode, the key and a connection test, the connection to your DAW (Live's AbletonOSC script, REAPER's bridge), and for desktop AI apps a `hypnomix` command plus an agent folder. Costs and pros and cons for each: [Setting up, and choosing an AI](guides/09-setup-and-ai.md) |
| Wiki | lessons, how-to guides, every command and the FAQ, with screenshots and videos, searchable and offline. The same articles as the website's [/wiki/](https://hypnomix.bradfieldenterprises.org/wiki/); the app shows the website's copy when it is newer. In a git checkout, **Edit** opens the article's file and **Publish** commits and pushes the wiki: the website rebuilds within about 10 minutes and every app follows |

### The review at the keyboard

| key | does |
|---|---|
| `j` / `k` (or the down / up arrow) | next / previous finding |
| `a` / `s` | approve / skip the finding you are on, then go on to the next undecided one (a box in the `?` list turns that off) |
| `c` | change: records it and opens the note box (Esc leaves the box) |
| space | play or pause the clip |
| `b` | switch between A and B at the same moment (the same player, the other clip) |
| `[` / `]` | previous / next undecided finding |
| `?` | show or hide this list |

The keys are off while a text box, list or slider has the cursor, so typing a note never approves anything. They only record
answers: nothing is applied from them. Every control is also reachable with Tab and shows where it is; messages and errors appear in a
message region at the top of the page (a screen reader reads it), the counts and a job's progress are live regions, and the review
is a list of cards, each with a heading.

Every command the app starts runs this copy of hypnomix, in its own process group. A request that is missing something, or carries a field of the wrong kind (a list where text belongs), is answered with a plain sentence (a 400), never a Python error or a dropped connection. The result page lists "Listen at these spots" only for fixes that name a real place (a bar or a time), and the Apply card says each on-by-default step runs only if it is still needed once the others have run.

It is a web server on this computer only. It refuses requests from other sites and will not be shown inside another
webpage, cleans the wiki articles it takes from the website (scripts, forms, frames and unusual links are removed;
pictures, videos and sounds only in the usual kinds, up to 50 MB each), only reads and writes scans inside its own
folder (`~/Documents/Hypnomix`; change with `--home`), takes a recording to review only from its own `bounces` folder
and a set to align only if it is a saved `.als` or `.rpp` file, closes a connection that goes quiet for a minute, refuses
a request larger than 1 MB, and never overwrites a set. What the page asks every second is kept rather than redone: the Songs list re-reads a scan's results only when one of its files changed, the
Tools list is sent once (`/api/commands`; `/api/state` says when it changed), a set's tempo is read once per saved version, and a command's
`-h` text is run once. A batch of decisions is one request (`/api/decide` with `ids`), "the N like this" and "all low" list first
(`dry_run`), and the clips you played are kept in `heard.json` in the scan folder and copied into each decision. Its own settings (setup, updates, the Assistant's key) live in
`~/.hypnomix`, or the folder `HYPNOMIX_HOME` names for the setup and update files, so a test copy with its own `HYPNOMIX_HOME`
can't touch your real ones.

## The installed app (Mac and Windows)

The installers on the [download page](https://hypnomix.bradfieldenterprises.org) install the same app with its own
Python and ffmpeg inside it. On a Mac it is `Hypnomix.app` (a window of its own; quitting it stops it). On Windows
the Start menu's **hypnomix** opens it in your browser and **Quit hypnomix** stops it. Your songs' scans are kept in
`~/Documents/Hypnomix` either way, and an update just installs over the old version.

## Optional: your own Mac app (from a source install)

If you would rather have an icon in the Dock than a browser tab, build `Hypnomix.app`: a small window around
the same web app that starts it when you open the app and stops it when you quit.

```bash
xcode-select --install      # once: Apple's command line tools (the Swift compiler)
macapp/build.sh             # from the hypnomix folder; about a minute
open macapp/dist/Hypnomix.app
```

Drag `macapp/dist/Hypnomix.app` into Applications if you want to keep it. Things to know:

- You build it yourself, so it is made for your Mac and macOS trusts it. A copy sent to someone else will be
  blocked by macOS unless it is signed and notarised with an Apple developer account: tell them to build
  their own with the three lines above.
- The app remembers where hypnomix is installed. If you move or reinstall that folder, build again (or the
  app asks you to point at the folder).
- It is the same page as `hypnomix app`. Nothing is lost by using the browser instead, and on Windows or
  Linux the browser is the way.
- To remove it, delete the app. Your songs' scans stay in `~/Documents/Hypnomix`.

## The Live device (Max for Live)

```bash
hypnomix device         # writes Hypnomix.amxd + hypnomix_device.js into your Live User Library
```

Drag **Hypnomix** from Live's browser (User Library → Presets → Audio Effects → Max Audio Effect → Hypnomix)
onto any track. Audio passes through it untouched. With the app running and a review open:

- the device shows the finding you are on: track, bar, the problem and the proposed fix
- **Prev / Next / Next open** step through the findings, and Live jumps to each: the track is selected, the
  playhead moves to the spot, the loop brace is put around it (looping is not switched on) and the clip opens
- **Approve / Skip** record your decision, exactly like a click in the app. Nothing is applied from Live
- **Show in Live** buttons in the app do the same jump through the device
- **Brace off** leaves your loop brace where it is
- **Float** (top right of the device) opens the same panel in a small floating window. Use it while stepping:
  a jump selects the finding's track, so Live shows that track's clip where the device was, and the floating
  panel stays in view. Click Float again to close it

Applying still happens in the app, into a new set, with the original closed. The device never edits the set
it sits in.

It needs Max for Live (Live Suite, or the add-on). Loaded in Live 12 Suite on a real set (2026-11-25): it
connects, follows the review, jumps Live to each finding and opens the floating panel. It is built from the blank Max Audio Effect inside your
own copy of Live plus one script file; keep the two files in the same folder.

## For an AI agent

- If the person prefers clicking to chatting, start `hypnomix app` for them (as a background process, not a
  blocking shell) and say what each screen does. Their decisions land in the same `decisions.json` you read.
- The app is not a way round the rules: it runs `fix --approved`, with the same gates.
- The Live devices were tested in Live 12 Suite on a real set (stepping, jumps, A / B / Blind, loudness matching,
  the probes, Record and review). They are still new: say so, and keep the person's original set closed while an
  A/B set is open.
