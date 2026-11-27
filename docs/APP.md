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

A second copy of the app (a test copy beside the real one) needs its own ports. The Max for Live devices talk to
the app on port 8791 (`HYPNOMIX_PORT` changes it) and the probes send their measurements by UDP to port 8792
(`HYPNOMIX_PROBE_PORT`). Start the copy with `hypnomix app --port N`, and make its devices (`hypnomix device`,
`hypnomix probe device`, `hypnomix reaper review`) in a terminal where `HYPNOMIX_PORT=N` and
`HYPNOMIX_PROBE_PORT=M` are set, so the devices use the same numbers. If the probe port is taken, the app's status
says which port and how to change it.

| screen | what you do there |
|---|---|
| DAW | HypnoMix Studio's window on its engine, with the Assistant beside it: see "DAW mode" below (the first page with `hypnomix app --daw`; only there when an engine is found, attached or `--daw` was given: the engine is an add-on, for Apple-silicon Macs only so far) |
| Songs | choose a Live set (.als), a REAPER project (.rpp), a HypnoMix Studio session (`.ardour`) or a folder of recordings from any DAW, with the chooser or by pasting the path (a pasted path may keep the quotes a file manager's "copy as path" adds; where the app has no chooser, as in the installed Windows app, the page shows only the Path boxes); optionally a bounce of the mix, a song you love, the key (the browser remembers this form, and the tab and review you were on, so a refresh puts you back). "Start the first pass" runs `scan`, then `ab`. Each song has its own scan folder: the same path always goes back to it (a re-scan), a different path never shares one even with the same name (`Song`, `Song (2)`), and a card shows its folder when two songs share a name. **Re-scan** on a card runs the scan again; a Live set keeps your decisions (`scan --since`), the other kinds set the old answers aside in `decisions before re-scan.json`. A song whose results or decisions file is damaged stays in the list with a red tag. With no songs yet, **Try it on a demo song** (when `hypnomix demo` exists) makes a short demo song in the app's folder and scans it |
| Activity | how far the command has got, from what it prints (never a percentage): a scan says "4 of 12 checks done", which checks are still running and, when an earlier scan of the song exists, about how long is left from that scan's own seconds (a first scan shows the time so far and says there is no estimate); the clip builder and an apply show their steps. Then the log of each command as it runs, with a Stop button that ends the command and everything it started (each job runs in its own process group), removes the temporary `(fix step N)` sets a stopped fix left, and lists the files a finished job made, each with a Show-in-folder button. A failed job says why in the command's own words. The log keeps the newest 4,000 lines of a long command (`LOG_KEEP`): the oldest 1,000 go each time it passes that, and a page that had not read them yet says "N older lines of the output left out", so the last lines of a long job (its summary, its exit code) always show |
| Review | the fixes you can hear first, by severity (then the ones with no clip yet, then questions for you: a key question has an answer box, and what you type goes in with Apply as `fix --answer`); by-hand and info items wait in a collapsed **By hand in your DAW** section with the handoff button, outside the approve / skip flow. A filter row (All, Undecided, Approved, Skipped, To change, By hand, and by tool) is remembered per song. **A long review** (more than 150 cards on screen: `LAZY_ABOVE` in `review.js`) is built a page at a time: every group keeps its full count in its heading, the first big group opens with its first 100 cards, the other big groups wait behind a **Show the first 100** button (a group of 40 or fewer is built whole), an open group builds 100 more when its end scrolls into view (or with its button), the by-hand and low-priority boxes build their cards when they are opened, and `j` / `k` / `[` / `]` / `a` / `s` build the card they reach. The bar, the counts and the Apply card read the findings, never the page, so they always cover every finding. A short review is drawn whole, as before. "The N like this" counts come from ranges in `oversight.like_runs` (positions in `like_order`) instead of every id list (`/api/review` for 2,000 findings: 5.7 MB before, under 2 MB, about 100 KB gzipped), and a note comes back as that finding's notes (`/api/note`) instead of the whole review being fetched again. Each card has one player with **A** and **B** buttons that swap the clip at the same moment. Approve, Skip or Change with a note, at the keyboard (see below) or with the mouse; a decision changes only its own card, the counts and the Apply card, never the list, so the clip you are hearing and your place on the page stay. It remembers which clips you played: the bar says "12 approved, 5 of them never played" and an approval with a clip you never heard is marked on its card (it never blocks a decision). **Approve all low…** and **Approve the N like this** show the whole list first (id, track, what, whether it has a preview, whether you played it) and record nothing until you confirm; "all low" never takes tuning, harmony balance, motion, colour, borrowed moves or variations (taste calls), a track reorder, removal or merge, a protected track or a by-hand item. Saved as you act. Steps that are **on by default** (track order, removing switched-off tracks, one instrument onto one track) show "On by default" and **Turn off** (it records a skip); banners say if the project was saved after the scan, or the original is missing. **Re-scan** and **Make the handoff list** (`hypnomix handoff`: a checklist and a marker at every by-hand spot) are in the header. A damaged `decisions.json` shows what was lost and, if `decisions.json.bak` exists, **Restore the backup** (the damaged file is kept as `decisions.damaged.json`) |
| Apply | says first what will happen: how many approved fixes, which on-by-default steps also run and what each does (the archive copy it writes and how many tracks it removes), how many approved items are by hand and will **not** be applied, and the exact file names it will create. The new file takes the ending of the project (`.als`, `.rpp`, `.ardour`; nothing for a folder, whose repaired copies go to the scan's `fixed` folder), is named `Song (fixed).als`, then `Song (fixed 2).als` if that is taken, and the name can be edited. Apply is enabled only when something can really be written; a by-hand-only selection offers the handoff list instead. Then it writes only that (`fix --approved`) |
| Result | after an apply: the new file and its folder with a Show button, what was applied, what was not and why, any FAILED line in red (said in the page's words: the box to fill, not a command-line flag), "listen at these spots" from the applied findings (only when a new file was written: a run that stopped before writing anything says "Apply stopped" and "Nothing was written", and one that stopped after writing says "Applied in part"), and buttons: open the review again, **Undo this**, make the handoff list. The log is shown as text under its own headings (not applied, on by default, failed), whatever those say |
| History | a collapsed section of the review (`hypnomix history DIR --json`): every apply of the song, with **Undo** (`history --undo N`, after a confirm that names the file it will write) for Live sets. REAPER projects, HypnoMix Studio sessions and folders keep no snapshot, so the page says so instead of offering a button |
| Preferences | the questions asked once: targets, protected tracks, what is deliberate. The loudness and true-peak targets take any number the help names (the usual ones are suggestions), and a saved answer shows as the answer |
| Tools | every other command with its help and a form: tempo, variations, mastering, and the rest. **Add a set / an audio file / a folder** put the chosen path after the flag the command's own usage line names (`key` takes `--set` and `--audio`), or bare where the command takes it as an argument |
| Updates | the version at the top right: checks for a new version (once a day, or now), and in the installed app **Update now** downloads it, checks its fingerprint (against the release's own list: this catches damage or a swapped file, not a hijacked release, as installers aren't yet signed with a publisher key) and installs it with one click. Source installs are told to `git pull` |
| Disk care | the free space at the top right: HypnoMix clears its own bulky leftovers (render cache, audio in scans idle two weeks, `hypnomix-out` audio, HypnoMix's own temporary folders (`hypnomix-render-…`) a stopped command left, old master bounces, and the Store's unfinished downloads after 2 days, kept installers after 30 and the trash of replaced plug-ins after 60) weekly, and straight away when the disk is nearly full. Preview, clean now, switch it off, or also move old Desktop / Downloads WAVs to a 14-day holding folder. Audio a Live, REAPER or HypnoMix Studio project uses is never touched. Unprefixed temp folders that older versions left (`tmpXXXXXXXX` holding only WAV files or a small track-name list) are listed with their size and cleared only by a click on **Clear them** (`python -m hypnomix.app.diskcare --clear-old` from a terminal asks y/N first). Folders you add must be inside your home folder (not the home folder itself, Library, or all of Music, Desktop or Documents) |
| Teacher | teacher mode: a guided course in your DAW (Live, REAPER or HypnoMix Studio). The **tour** of HypnoMix and its devices for people who already engineer, the **101 crash course** (the words, recording to a click, each effect, mastering), or **The complete course, A to Z** (13 chapters, 138 to 146 lessons depending on your DAW: sound and hearing, digital audio, gear and rooms, recording, editing, mixing, mastering, releasing, troubleshooting and cheat sheets, with common mistakes, exercises, self-marking quizzes, **Hear it** audio examples made on the spot by `hypnomix/app/teach_audio.py` (cached in `~/.hypnomix/cache/teach`), and a searchable **Glossary**; the 101 course is a subset of it). The lessons are the package `hypnomix/app/lessons/` (one module per chapter) and are also the wiki's per-chapter course articles. Hands-on steps in Live and REAPER (tempo, click, a drum beat, an armed track, effects, the mastering chain) each wait for **Do it**. Progress in `~/.hypnomix/teacher.json` |
| Assistant | a chat with an AI of your choice that runs HypnoMix for you (bring your own key; Claude Sonnet 5.5 is the default model, every other model stays selectable) and, optionally, a Listener that hears a bounce. Shows the tokens and cost as you go (exact for Claude, an estimate for Gemini), clears old results from what it re-reads as a long chat grows, asks "keep going?" when one message uses more than 400,000 input tokens (a setting), and stops if it repeats the same call three times. Anything that writes waits for your click. Details: the wiki's "The Assistant and the Listener" |
| Setup | the guided setup (it opens by itself the first time): how you work (just the app, an AI key, a model on this computer, or a desktop AI app such as Claude Code), your DAW (Ableton Live, REAPER, HypnoMix Studio or something else; choosing HypnoMix Studio shows what it is and, on an Apple-silicon Mac, an **Add HypnoMix Studio** button; where no archive is published for the computer (Intel Macs, Windows) it says it is not available there yet and remembers the choice) and teacher mode, the key and a connection test, the connection to your DAW (Live's AbletonOSC script, REAPER's bridge), and for desktop AI apps a `hypnomix` command (one that is already there and was not made by the setup is left as it is) plus an agent folder. The dialog keeps the keyboard (Escape is the same as Skip setup), and the last step says when an AI chosen on the way was not connected. Costs and pros and cons for each: [Setting up, and choosing an AI](guides/09-setup-and-ai.md) |
| Store | free and open-source plug-ins, synths, instruments, drum kits and sample packs from their publishers' own downloads: search, filter by kind, format, licence and MPE (a small **MPE** mark on the items whose maker documents per-note pitch bend, pressure and slide; Details says what the maker documents and where it is switched on, and carries a **Note** for what to know before installing), read each licence and source, then **Install**, **Update** or **Uninstall** with progress. **Mac only for now**: on another system the tab and `hypnomix store` say so instead of failing. Plug-ins go into `~/Library/Audio/Plug-Ins`, sounds into `~/Music/Hypnomix Library`. Nothing downloaded is run: an item that ships as an installer package (found inside a disk image or archive, or the download itself) is kept and opens in Apple's Installer for you. An unpack gets 15 minutes plus a second per 2 MB, at most 2 hours, and Cancel stops it. A download that cannot be checked against a SHA-256 the publisher gave (or one pinned in the catalogue) is not installed unless you confirm a second time, in plain words, that it is not verified (the tab and the Assistant's card ask; in a terminal it is `--unverified`). Also `hypnomix store` in a terminal (`--kind`, `--format`, `--open`, `--licence`, `--mpe`, `--replace`, `--unverified`; `hypnomix store -h` explains each); the Wiki's **The store** article has the details |
| Wiki | lessons, how-to guides, every command and the FAQ, with screenshots and videos, searchable and offline. The same articles as the website's [/wiki/](https://hypnomix.bradfieldenterprises.org/wiki/); the app shows the website's copy when it is newer. In a git checkout, **Edit** opens the article's file and **Publish** commits and pushes the wiki: the website rebuilds within about 10 minutes and every app follows. The app asks the website for its article list at most once an hour, and only while the Wiki is in use (`CHECK_EVERY`; **Check now** and the checkbox "keep up to date from the website" are the person's, and off means never): the ask carries the `ETag` / `Last-Modified` the website gave for the copy on this computer (kept in `wiki-live/articles.meta.json`, valid only while that file is exactly the one they were given for), an unchanged list is a few hundred bytes (304), a changed one is downloaded gzipped and read at most 20 MB unpacked, and a failed ask is repeated after 10 minutes. The list is read and checked once per change of its file, not on every click, and the tab fetches it once when it opens |
| Report a problem | the button at the top right (and **Report this** on every error message, failed job and the crash notice) opens a window with two boxes (what happened, what you expected), a few choices (the end of the last job's log, the last crash record, finding counts per tool for the open scan, **Keep names**, off by default) and a live preview of the exact report text (it also lists the versions of numpy, scipy and soundfile, and which helpers are there). **Copy the report**, **Save as a file** (a new file in `reports` in the work folder, then Show in folder) and **Copy it and open the issue page** (copies, then opens the project's new-issue page in your browser with the template's name only in its address: you paste the report there). HypnoMix never sends anything itself, and the report has its paths, names and keys hidden as far as HypnoMix can tell (`~` for your home folder, `<file 1>.wav`, `<track 3>`, `<hidden>`); it can miss one (a folder name with an apostrophe or a question mark in it, a track name in plain error text), so read it before you share it. A bug in the app (an unhandled error in a request or a job, or a script error in the page, the DAW view's included (its status bar links to the dialog), a few a minute at most) is saved as a **crash record** in `~/.hypnomix/crashes` (the newest 20 are kept) and the page shows a quiet notice with See it, Report it and Dismiss, which never takes the focus; a record from an earlier run is offered once, the next time the app starts. Routes: `GET` or `POST /api/report/preview` (the dialog posts, so two long text boxes fit), `POST /api/report/save`, `POST /api/report/open`, `GET /api/crashes`, `POST /api/crashes/dismiss`, `POST /api/crashes/page` (all POSTs carry the page's token). The same report from a terminal: `hypnomix report` (`--crash`, `--list`, `--out`, `--copy`, `--open`); the Wiki's **Reporting a problem** article has the details |

### Where the wiki lives

The wiki exists in three copies, all built from the same files in this repository (the articles in
`hypnomix/app/wiki/articles/`, the guides, `docs/*.md`, the top-level documents, the skills and subagents, the command
list from `hypnomix/cli.py` and the teacher-mode course): the app's Wiki tab, the website's
[/wiki/](https://hypnomix.bradfieldenterprises.org/wiki/), and this repository's **GitHub wiki**. Nobody edits the
GitHub wiki: when a change to those files is pushed to `main`, `.github/workflows/wiki.yml` runs
`python -m hypnomix.app.wiki_github` and replaces every page of the wiki's repository (this repository's name with `.wiki`)
with the build, deleting pages that no longer exist, and commits only when something changed. It deletes everything else in
that repository too (except `.git`), so a page or an image added by hand in the wiki is deleted by the next build. A page's
name comes from its article's id (`learn-live-mix` is `Learn-live-mix`, lesson `l3` is `Lesson-3`; the word `ardour` in an
id becomes `HypnoMix-DAW`, so no page's title or address uses the old name), so a link survives a new title; `Home`
lists every page in the site's order with its teaser, `_Sidebar` folds the groups, and every page ends with a link to
the same article on the site. The articles' HTML becomes GitHub Markdown through a small converter (tables, nested lists,
code, links, definition lists, `details`; links between articles become links between pages, a link to a screen of the app
becomes plain text, pictures and videos point at the site) and the build prints how many things it had to simplify
(none today). The guides and docs are Markdown already and pass through with their relative links fixed. You can build the
pages yourself into a new folder to see them: `python -m hypnomix.app.wiki_github --out /tmp/wiki-pages`.

One setting is by hand, once: GitHub makes a wiki's repository only when its first page is saved in the web interface.
Settings, General, Features: tick **Wikis**; open the repository's Wiki tab, click **Create the first page** and save it as
it is; then run the workflow (Actions, wiki, Run workflow). Until that is done the workflow stops and says so, instead of
failing in git. The workflow has not been run on GitHub yet, and the pages were checked as files here, not as GitHub draws them.

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

Every command the app starts runs this copy of HypnoMix, in its own process group. A request that is missing something, or carries a field of the wrong kind (a list where text belongs), is answered with a plain sentence (a 400), never a Python error or a dropped connection. The result page lists "Listen at these spots" only for fixes that name a real place (a bar or a time), and the Apply card says each on-by-default step runs only if it is still needed once the others have run.

It is a web server on this computer only. It refuses requests from other sites and will not be shown inside another
webpage (a name longer than the file system allows is answered with a 400 and one sentence, and a clip is served only if
its real file is inside the scan folder), cleans the wiki articles it takes from the website (scripts, forms, frames and unusual links are removed;
pictures, videos and sounds only in the usual kinds, up to 50 MB each), only reads and writes scans inside its own
folder (`~/Documents/Hypnomix`; change with `--home`), takes a recording to review only from its own `bounces` folder
and a set to align only if it is a saved `.als` or `.rpp` file, closes a connection that goes quiet for a minute, refuses
a request larger than 1 MB, and never overwrites a set. The app trusts every program on this computer, not only your browser: the calls that the Live
devices and the REAPER panels make (stepping and deciding, A/B, the mastering chain templates, the Align and probe cards) carry
no page token, because those callers are not pages and cannot be handed one, so only the this-computer-only check protects
them; the page's own changes, the probe's Start and Stop included, need its token. What the page asks every second is kept rather than redone: the Songs list re-reads a scan's results only when one of its files changed, the
Tools list is sent once (`/api/commands`; `/api/state` says when it changed), a set's tempo is read once per saved version, and a command's
`-h` text is run once. `/api/state` carries a `rev` (a digest of everything in it): the page asks with `?rev=` and an unchanged state comes back as `{"rev": ..., "same": true}` (41 bytes, not every song's row), and after ten asks in a row that found nothing new, while no job runs and neither Activity nor Live is open, it asks every fifth second (it asks at once when the tab comes back into view). The big JSON answers (the review, the Wiki list) are gzipped when the browser says it takes gzip. A batch of decisions is one request (`/api/decide` with `ids`), "the N like this" and "all low" list first
(`dry_run`), and the clips you played are kept in `heard.json` in the scan folder and copied into each decision. Its own settings (setup, updates, the Assistant's key) live in
`~/.hypnomix`, or the folder `HYPNOMIX_HOME` names for the setup and update files, so a test copy with its own `HYPNOMIX_HOME`
can't touch your real ones.

## DAW mode: HypnoMix Studio in the app

What HypnoMix Studio is, and where it comes from: the wiki article "HypnoMix Studio".

```bash
hypnomix app --daw                              # the DAW view first; starts (or finds) the HypnoMix engine (the add-on)
hypnomix app --daw --session "Song/Song.ardour" # ... and opens that session in it
```

The **DAW** tab (first in the navigation; the page the app opens on in DAW mode) is HypnoMix Studio's window:
Arrangement, Session clips, Mixer and Review, the browser on the left, one device chain along the bottom and the
Assistant in its own column on the right. **Songs**, **Assistant** and **Wiki** at the top go back to the rest of the
app. Press `?` in it for every shortcut.

**When the Studio tab is there.** There is one app and one installer for everyone, and DAW mode's engine is not inside
them: HypnoMix Studio, HypnoMix's own DAW, is an **add-on** that is added from
**Setup** on a click (below). The first engine, **0.1.0**, is published for **Apple-silicon Macs only**. On an Intel Mac,
on Windows and on Linux it is **not available yet**: the manifest shipped in the app names no archive for them, so there is
nothing to add, the app downloads nothing, and with no engine found the app shows no Studio tab. The tab appears when an
engine program is found (the add-on once it is added, or one of the lookups below), when the app is attached to a
running HypnoMix Studio window (see the table below), or when the app was started with `--daw` (`--session` alone turns DAW
mode on too). The add-on's fingerprint is checked when the engine is added, not again when it is started: the app starts the
program it finds (`engine/<version>/bin/hypnomix-engine`, or the one `HYPNOMIX_ENGINE` or `daw.json` names), and no request or
page can change which program that is; anyone who can write into your HypnoMix folder can already run programs as you. With no
engine connected the DAW view says so and offers **Start the engine**, **Look
again** and, as a choice of its own, **Practice with the demo song**: a made-up song (the "mock" session, `daw/js/mock.js`)
that plays no sound, saves nothing and sends nothing, and is labelled **Demo** wherever it shows. It never takes the
place of a session you have open: leaving the engine's session for it is **Show the demo song** in the engine panel, and
that asks first.

**Top bar and status bar.** The page never scrolls sideways: at every width, whatever does not fit in the top bar scrolls
inside the bar (the tours scroll a control they point at into view). At 1520 px wide or less the top bar gives way first:
the DSP meter, the clock and the time signature are hidden, and the name block may shrink down to the mark. The engine's loudness in the top bar is
one number (short-term LUFS) at every width; momentary LUFS, true peak and correlation are in the status bar. The status
bar names the engine **HypnoMix engine** and its version (`MCP · HypnoMix engine 0.1.0 · … tools · … kHz · meters
streaming`): never the name the engine's MCP surface gives itself in its `initialize` reply, so renaming that surface
changes nothing on the page. Tests: `tests/test_daw_topbar.py`.

**Guided tours.** The DAW view can show people around on its own screen, optionally: the first time it opens, a small
card offers **Show me around** or **Not now** (it takes no focus, and the answer is remembered); the **Tour** button in the
top bar (and **Take a tour** in the `?` list) opens the six tours (First look, Edit a region, Mix, Scan and review, Ask the
Assistant, Save and export); the Teacher tab has a card that opens the same list, shown only where the DAW view is
available. A step lights one real control and waits, if it asks you to do something, for the page's own events (`edit`,
`undone`, `saved`, `review`, `assistant`, `mode`); it never changes the session, sends an engine command or clicks for you.
The tours are data (`daw/js/tours.js`), the engine is `daw/js/tour.js`, the look is `daw/css/tour.css`; progress is in
`localStorage` (`hx.tour`) and in `~/.hypnomix/teacher.json` under `dawtour` (`GET`/`POST /api/teach/tour`). Tests:
`tests/test_daw_tour.py`. Wiki: [A guided tour inside the HypnoMix Studio](../hypnomix/app/wiki/articles/18-daw-tour.html).

**The engine.** Underneath is the HypnoMix engine: the DAW's audio engine (with no window), which the app
starts, watches and stops (`hypnomix/app/daw.py`). It is a separate program under its own licence (next paragraph).
It looks for the `hypnomix-engine` program in this order: `HYPNOMIX_ENGINE` (or `"engine"` in
`~/.hypnomix/daw.json`); the add-on, `engine/<version>/bin/hypnomix-engine` in the HypnoMix folder (`~/.hypnomix`, or the
folder `HYPNOMIX_HOME` names), for the version the app's manifest names (else the newest other one on disk, which is kept
until the new one has run once); inside the app, `Hypnomix.app/Contents/Resources/engine/bin/hypnomix-engine` (a test
build's kit: still found for one more version, and nothing depends on it); the folder next to the Python the app runs on
(not looked in when the app runs inside `Hypnomix.app`); and, for developers only, a source build of the engine in the
folder that `HYPNOMIX_ENGINE_SRC` names (nothing is guessed). It runs it on a free port (`--port N`, so it never collides with a
HypnoMix Studio window on 4820) with the session, and waits for its `HYPNOMIX-ENGINE READY port=N` line. Extra arguments
(for example `-b "None (Dummy)"` with no audio interface) go in `HYPNOMIX_ENGINE_ARGS` or `"args"` in `daw.json`.
Without a backend there, on a Mac the app is written to add the default output device (`--output-device`, read from
System Settings → Sound; not yet tried with a real sound card) and `--input-device None`: the engine's CoreAudio backend otherwise takes the first device in its list (a
loopback driver can be first and never answer), and an input device makes macOS hold the engine's start until someone
answers the microphone question. To record, give an input device in `"args"`. `/api/daw/state` reports the `backend`
the engine runs on.

The engine is started in a minimal environment (the app's own keys, tokens and passwords are not passed on, because
the engine loads other people's plug-ins in its own process; `HYPNOMIX_*` is) with the session's folder as its working
folder, and the session and snapshot names go after `--`, so a name can never be read as an option (a new session's name
may not start with `-` or `.`). Only a whole `HYPNOMIX-ENGINE READY port=N` or `ERROR` line on the engine's standard
output counts, and N must be the port the app gave it; its log (standard error) is only shown in the engine panel. The
app's calls to the engine, and the REAPER panels' and Live device's calls to the app itself, never go through an HTTP proxy (`hypnomix/core/loopback.py`: this computer only, no redirect followed). One start, stop, restart or open runs at a time: a second
request meanwhile is answered 409 "busy" (wait a moment and try again).

**The engine's licence.** The engine is a separate program under the GNU General Public License (version 2 or later):
HypnoMix Studio's engine is a rebranded fork of the free open-source DAW it is built on (what that is, and where it comes
from: `THIRD_PARTY.md` and the wiki article "HypnoMix Studio"). HypnoMix itself stays under the MIT licence and contains none of the engine's code; the app starts
the engine as its own process and talks to it only over MCP on this computer. The add-on archive carries the engine
unchanged, with its licence text and a source notice as its own files (`packaging/mac/build_engine_archive.sh` refuses to
package a kit without them, and the app checks them again on what it downloaded: packaging/README.md). The engine's source
is public at https://github.com/drtranceypants/hypnomix-daw.

| situation | what the app does |
|---|---|
| no session given (`--session`) | opens the one that was open when the app last quit (`"last"` in `daw.json`, kept each time a session opens); with none, the engine waits (the engine needs a session) and the view says: File → New Session… or Open Session… (or New / Open in the engine panel) |
| no audio device starts (`HYPNOMIX-ENGINE ERROR cannot start the audio engine`, `cannot use device`, …), or the device never answers within 120 s | starts the engine again once on the Dummy backend, without the device choices, and says so in plain words (`notice`: no sound; the session, edits, waveforms and exports all work). Restart tries the device again. Not when `args` chose a backend: then a start that is not ready within 120 s is stopped and shown as failed (press Restart) |
| the engine stops by itself (a crash, or the audio engine halted) | starts it again on the same session, at most 3 times a minute; the DAW view reads the session again. Edits not saved before the crash are gone, and a `notice` says so until you Save (or Restart) |
| the engine says `HYPNOMIX-ENGINE ERROR …` (no such session, the port is taken, bad arguments) | shows the message and does not retry |
| you quit the app | stops the engine (SIGTERM). The engine never saves by itself, so the app asks first when there are unsaved edits (**Save**, **Don't save**, **Cancel**; "Saving" below); the native app's Quit asks the same (and waits for the engine to stop before it quits), and the updater's **Install and restart** is refused (HTTP 409) until you have saved |
| no engine program yet | **attaches** to a HypnoMix Studio window that is already running with Preferences → Control Surfaces → MCPHttp on (`http://127.0.0.1:4820/mcp`; `HYPNOMIX_ENGINE_URL` for another). Attached, the app never stops or restarts that window, and you open sessions in it. It attaches only to a listener that is the engine (it must call itself by the engine's name and have the engine's core tools): anything else on that port is left alone, and the engine panel says so |

Click the button at the top right of the DAW view (it reads **No engine**, **Demo** or the engine's state) for the engine
panel: its state, session and log line, **Connect**, and **Start**, **Restart**, **Stop**, **Open** (a session file or its folder) and **New** (type the folder and the new
session's name). If the engine refuses a session you **Open**, the one that was open is opened again (from its last save) and the refusal is shown. When the engine is up the view connects by itself. When the engine is started again (Restart, or
after a crash) the view reads the session again, as the engine reopened it from its last save, and starts a new undo
history.

**Saving.** The engine never saves by itself, so the app keeps track of unsaved work: any change that went through
(from the page or from the Assistant) marks the session unsaved, a successful save clears it, and a session that was
just made or opened starts clean. The view has a **Save** button (⌘S, Ctrl+S) and shows when there is something
unsaved; before anything that would lose it (Stop, Restart, Open, New, quitting, leaving the page) it asks **Save**,
**Don't save** or **Cancel**. The same is in the routes: `GET /api/daw/state` carries `dirty`, `POST /api/daw/save`
saves through the engine, and `stop`, `restart`, `open` and `new` answer HTTP 409 `{"error": "unsaved", "dirty": true}`
while there is unsaved work, unless the request says `"discard": true` (go on without saving) or `"save": true` (save,
then go on). A change that reaches the engine without going through the app counts too: `hypnomix tidy`, `order` and
`duck` with `--engine`, `hypnomix loops` and `variations` with `--cues`, or any script on the engine's own port. The
engine keeps its own unsaved flag (the `dirty` of its read-only `session_list_snapshots`), and the app reads it before
every Stop, Restart, Open and New, for quitting and the updater (`daw.dirty()`), and for `GET /api/daw/state`: one
reading shared by all of them, at most every 2 s, so the view's Save button and title show it within a few seconds. Unsaved is the app's own count or the
engine's flag; a save clears both, the engine's flag never clears the app's own count, and an engine that does not
answer keeps its last answer (no answer is no information: it neither blocks nor clears; a look waits at most 3 s). A
command that wrote less than 2 s before Stop or quit can be missed if the last reading came just before it. It is read only for an engine the app
started: a HypnoMix Studio window the app only attached to is that window's to save, and its flag is not shown. Those
commands find the app's engine with `--engine URL`: the address is shown in the engine panel and is the `url`
of `GET /api/daw/state`. Checked on the engine itself (Dummy backend): a session just opened reports clean,
`session_save` clears the flag, and none of the read-only tools set it. Not checked live: the native app's Quit dialog
and the updater's refusal (both go through `daw.dirty()`, which the unit tests cover). The engine's flag never
comes from reading: the view's one change on connecting, switching the meters to RMS + Peak (`meters_get`'s
`ensure_rms`), is held back while the session is clean and goes in with the first real change (see Meters below).

**Adding and removing HypnoMix Studio** (`hypnomix/app/engine_addon.py`). The engine is published as an archive of its own
for each platform. The first one, engine 0.1.0, is published for `mac-arm64` (Apple-silicon Macs) only; the manifest's structure allows `mac-intel` and `windows-x64` later, and `linux-x64` for people who build it (the project does not test on Linux).
`hypnomix/app/engine_addon.json`, shipped inside the app, names for this version of the app the engine version it works
with and, per platform, the https address and SHA-256 of the archive. For a platform with no archive the manifest carries
no address and the state says **HypnoMix Studio is not available for** that computer **yet** (for example "HypnoMix Studio is not
available for Windows yet"). The archive is on the HypnoMix release page, and it is installed to
`<HypnoMix home>/engine/0.1.0/`. Nothing is
downloaded without a click, and nothing in a request names the address or a folder: the routes are
`GET /api/setup/engine` (the state) and `POST /api/setup/engine/install` and `/remove` (the page's token, no foreign
origin, and a body that names anything is refused with 400). An add downloads over https with a size limit (the manifest's
size plus a megabyte) and a deadline (30 minutes), checks the SHA-256 **before** anything is unpacked (a mismatch deletes
the download and says so), unpacks with the Store's protections (no entry outside the folder, no link pointing out, entry
and size limits), checks the kit as `packaging/mac/check_kit.sh` does (the engine program, `COPYING` with the GNU General
Public License, `SOURCE.txt`, no symbolic links, no builder's home path inside any file), and moves it into
`<HypnoMix home>/engine/<version>/` in one step; a failed or interrupted add leaves nothing half-added and can simply be
run again, a second add of a whole engine downloads nothing. **Remove** deletes it and is refused, with one sentence,
while the engine runs, from any process (the app writes `engine/.running` while it runs an engine from the add-on, so the command line and the Assistant see it too; a marker left by an engine that is gone is ignored). An app update that names a newer engine says so in the DAW view and in Setup and offers the new
one (`GET /api/daw/state` carries `addon`); the old version is removed after the new one has run once. A kit rebuilt and published under the same version is noticed by its SHA-256 and offered the same way. In a terminal:
`hypnomix engine` (status), `engine where`, and `engine install` / `engine remove`, which report and change nothing
until `--yes`. The Assistant may run `engine` and `engine status` unasked; anything else on it needs your click.

**What has not been tried.** DAW mode was tested against stand-in engines in the unit tests and against the real engine
on its silent test backend (no sound). Nobody has yet run it with a real sound card (so playback through a real output
device, and recording through a real input, are untested), clicked through the native **File** menu and its panels in
the built app, added the engine from the published archive on an installed app, signed and notarised the engine (the
Developer ID build has not been tried), used MPE with a real MPE controller, or run any of it on an Intel Mac (there is no
Intel engine). Read the sentences about sound and the File menu in this section as what the code is
written to do. Round 2 (take lanes and comping, groups and sidechains, the meter stream, the Session view's cue slots, the A/B session, and the `--engine` / `--cues` forms of `tidy`, `order`, `duck`, `loops` and `variations`) was tested against stand-in engines in the unit tests and against a development build of the engine on its silent test backend with a made-up session. Not verified: the meter stream inside the Mac app's own window (a same-origin WebSocket under the page's `connect-src 'self'`; if that window refuses it, the meters fall back to polling) and its reconnect after an engine restart, any of it on Windows or with real audio hardware, and anything by ear (comp crossfades, cue launches, the A/B level match, the duck and sidechain settings).

**The browser never talks to the engine directly.** The page sends its MCP calls (JSON-RPC 2.0) to the app,
`POST /mcp` on the same address, with the page's token; the app passes them to the engine it runs and the reply
back unchanged. The app reads each call strictly (UTF-8 JSON only, no NaN and no number too big to write back such as 1e999, and no name given twice in one object:
`400 bad request: repeated name in the message`), and what it sends on is that message written out again, never the
bytes it came as, so the tool the app checked (and counted for unsaved work) is the tool the engine runs. The same rules as the rest of the app: this computer only, requests from other sites refused, and
nothing without the page's token. The engine routes are `GET /api/daw/state` and `POST /api/daw/start`, `stop`,
`restart`, `save`, `open {path}`, `new {folder, name}` (the ones that would lose unsaved work answer 409: see Saving). The meter stream is `GET /api/daw/meters?t=<token>`
(a WebSocket upgrade; 403 without the token, 400 when it is not a WebSocket request, 429 when four streams are already
open, 503 when the engine has no stream, 502 when the engine's stream does not answer or refuses:
see "The meter stream" below).

**The Assistant in the DAW.** With a model key set (the Assistant tab's settings) and the engine connected, the
Assistant column is the app's real Assistant, the same conversation as the Assistant tab. It gets the engine's own
tools (its `tools/list`, offered to the model as `daw_<tool>`, with any provider) on top of HypnoMix's, and calls them
through the app's engine connection (`hypnomix/app/chat.py`, with its rules in `hypnomix/app/daw_assist.py`):

| rule | what it means |
|---|---|
| reads run at once, from an explicit list | `session_get_info`, `tracks_list`, `track_get_info`, `track_get_fader`, `track_get_regions`, `region_get_info`, `region_get_peaks`, `plugin_list_available`, `plugin_get_description`, `markers_list`, `meters_get`, `transport_get_state`, MIDI note reads, `export_status`, `region_get_warp`, `session_get_card` (the song card), `cue_list`, `ab_list`, and on an engine with MIDI inputs and MPE `midi_ports_list`, `track_get_mpe` and `midi_monitor_get` (the per-note input monitor: its first read attaches a tap to the track's input port, which changes nothing saved or heard),, and on an engine with automation and the tempo map `automation_list` (a route's automatable controls, and whether it is a bus and what it carries), `automation_get` (one control's points) and `tempo_get_map`, … plus `daw_session_overview` (the whole session in one read). Any other tool, and any tool the engine adds later, asks; so does a listed one the engine marks as writing. A listed read must be unable to change anything whatever its arguments: `meters_get`'s `ensure_rms` (it switches every meter) is taken out of the call and out of what the model is offered |
| every change is a **proposal card** | a title and a sentence in plain words (*Change a fader: Drums · fader, from 0.0 dB to -2.0 dB*), what changes, before → after, read from the engine just then, the exact call under a disclosure, what undo can do for it (only region, marker, loop-range, warp, take-comp (`comp_range`) and MIDI edits are engine undo steps; a fader, pan, mute, solo, send level or plug-in setting is taken back by setting the old value again; adding or removing a plug-in or a send is not an undo step, and a removed plug-in or send loses its settings, so adding it again starts from the defaults; removing or reordering tracks cannot be undone; on an engine with MIDI inputs and MPE, *Set MPE on a track* (`track_set_mpe`) is one undo step, while a port's flags (kept in this computer's MIDI port settings, not the session) and a track's MIDI input connections are not undo steps: the card says to put them back with another card, from the flags or connections the engine reports as before, and stopping the input monitor changes nothing saved: the card says which, in each case from the engine's source; on an engine with automation, *Write automation* (`automation_write`) is one undo step holding the points and the playback state together and *Clear automation* is one, while *Switch automation playback on or off* (`automation_set_state`) is not an undo step, as in the editor (the card says to set the old state again); *Change the tempo map* (`tempo_set_points`) and *Change the time signature* are one undo step each, and audio regions keep their time while MIDI follows the bars), **Approve** and **Cancel** (Esc). Nothing reaches the engine until you approve; then the card shows how it ended: applied and what the engine reads back, failed (with the engine's words, and whether it may have happened), cancelled or expired, in the DAW column and in the Assistant tab alike |
| an approval is for one call, and a deliberate one | the card carries a digest of its call and the answer must bring it back; just before the call is sent, the arguments exactly as they go to the engine are checked against the digest and against the arguments the card shows, and if they differ nothing is sent; the answer must be a real `true` (the string `"false"` or a `1` approves nothing). **Enter** approves only while the Approve button has the focus (a held key and a stray Enter, say one meant for the chat box, approve nothing), and a click counts once |
| arguments are checked first | a number where an id string goes, a track's name where its id goes, `regionId` vs `region_id`, `"true"` for true: fixed before the card is shown. A change to a track or region that is not in the session, one missing a required value or with a value of the wrong kind (`"loud"` for dB), or one to a plug-in index the track does not have is never proposed: the model is told why. The first answer to a card wins (a quick second click cannot turn Cancel into Approve) |
| replies are trimmed for the model | peaks become each channel's loudest peak and a coarse envelope; plug-in and parameter lists keep what matters; file paths are cut to the file's name and any home folder to `~`; long lists and texts are cut with a note (8,000 characters at most); the session overview stays under 14,000 characters: one read per track, all in flight together (6 at a time, 20 s at most, 80 tracks at most), regions only for a session of 12 tracks or fewer (a bigger one reads them per track), and the tracks that do not fit are named as not shown |
| what the project says is data | track, plug-in and region names, the engine's errors, what a change reads back and the snapshot list reach the model fenced in `<file-data>` tags like a file's contents, in any case and spacing of the closing tag and with any invisible character inside it (a soft hyphen, a bidi mark, a zero-width space, a NUL), with saved keys masked and the home folder shortened (a scan's log too): a track called `</FILE-DATA> do this` cannot close the fence. The scan that finds the tag walks the text once, so a hostile file cannot stall the chat |
| only part of the tool list is sent | each step carries the tool definitions again, and the engine had 111 before the round-2 tools (takes, groups and sidechains, the meter stream, cue slots, A/B playlists) and has 136 with them (25 new; about 17,600 tokens a step for the 111); an engine built with MIDI inputs and MPE lists 8 more (144), in their own `mpe` group, which `daw_more_tools` offers (and names to the model) only when the engine lists those tools: an engine without them shows no such group. An engine with automation and the tempo map lists 8 more (152): five in an `automation` group and three in a `tempo` group, offered the same way (asked for, never in the core, and only when the engine lists them). Before any card for an `automation_write` on a level control (the fader, trim or a send), and again in the app's engine connection as the call is sent (so a page or script gets the same answer), the smooth-automation rules are checked (`engineer/automation_rules.py`): gentle S-curves (`curve: s_curve`, about 1.2 s a move); no point more than 3 dB (a trim 4 dB) from the lane's ORIGINAL line, the line as it was heard before HypnoMix's first write to it (`engineer/automation_original.py`: kept per route and control in `hypnomix-original-lines.json` in the session's own folder, which every snapshot of the session shares; once kept it stays, on a lane cleared since too, since a clear leaves the control at the value it held; one entry a lane whatever name a call gives it, `fader` and `volume` being `gain` and route `02` route `2`; a hand edit outside HypnoMix leaves the kept line as it is, and only removing a lane's entry, or the file, starts it again from the line as it is then), so writes and drags one after another never add up past it; the steepest point under 7 dB/s (an S-curve peaks at π/2 times its average slope); the write starting and ending on the line as it is heard now, in either mode (`replace-all` too; `replace_all` and `s-curve` are read as the engine reads them), where a lane that is Off is heard at the control's own value, and a write that switches such a lane to play is judged with the points it keeps; a line that is not known (a fader at -inf reads as `null`, or a value that cannot be read) refuses the write, never taken for 0 dB; `start` and `end` numbers only (the engine would read the text "5" as 5 s), and `state`, `mode` and `curve` words only (the engine reads a list or an object there as left out, so `state: ["write"]` would be play); never `force`; never a recording state (`write`, `touch`, `latch`, nor `keep` on a lane in one: any later fader move would be recorded as a jump), on a level or a plug-in lane; an `automation_set_state` to play is held to the same rules (the points start and end on the control's value, under 7 dB/s, within the 3 dB); and never on a bus, a group's bus or the master that carries any track that is not a vocal (from `automation_list`'s `busOfGroup` members and `feeders`, by HypnoMix's own track roles; a feeder is a route whose output is wired to the bus or that has an aux send to it, pre- or post-fader, switched off too, and a bus among them is followed in turn. For a session file, `ardour_automation.facts_of` reads the same from the file, plus external sends wired to the bus's input; a plug-in's sidechain key is not counted). A plug-in parameter (`plugin:<processorId>:<index>`, in the plug-in's own units) is held to that last rule only: its automation is never written on such a bus (it would move those tracks too; automate a vocal track's plug-in instead), while clearing a plug-in lane is always allowed. A write they refuse gets no card: the model is told why in one sentence (fenced as data, since it names the session's tracks), and the engine connection answers it as a tool error without sending it (the session stays saved). The engine connection reads a request strictly: a name given twice in one object (the engine's parser keeps the first, Python the last), or two automation calls on one lane in one request, are refused. A ranged `automation_clear` on a level control is refused the same way when the points either side of the range are not level with each other (clearing it would join them with a straight move, not an S-curve), and so is a range with only a start or only an end, or one past the lane's last point (or before its first) that would leave the ridden value there to the end (or from the start) of the song; clearing a whole lane is always allowed. A request carries the core (the reads, fader, pan, mute, solo, sends, the main plug-in moves, save and undo: about 3,600 tokens) plus the groups the open view needs (the mixer adds the other plug-in tools, the Arrangement the region tools); `daw_more_tools {group}` offers any other group from the next step on. Descriptions are cut to about 170 characters. Measured on the engine's real tool list (111 tools, read only from its source): 70,600 characters a step before (about 17,600 tokens at 4 characters a token, HypnoMix's own tools and the overview included), 14,400 now (about 3,600 tokens); with the mixer view 17,800, with the Arrangement view 25,900, with every group asked for 57,400 (all on the 111-tool list). A provider takes at most 128 tools in one request: with every group asked for, the engine's own part is held to `MAX_OFFERED` (112, `daw_assist.py`) by leaving out the second forms of a tool first (`SECOND_FORMS`: the bars-and-beats and fader-position forms, parameter setters by control, a gain in linear units, markers by id, and `ab_list` / `ab_use_playlist`, which `playlist_list` / `playlist_select` cover; for the 144-tool engine also the loop range by samples, copies and moves by beats or by a distance, a note at a sample, `track_get_fader` and a new MIDI region from JSON, each done by a form that stays, and listed last so a 136-tool engine keeps them), the form kept doing the same job; under the limit nothing is left out. If that is still not enough (the 152-tool engine with every group asked for is), whole groups are put away, never a few tools of a group: `other` first, then the group asked for longest ago; never the core, the open view's groups or the group asked for last (the one the conversation is working on). Asking for a put-away group again brings it back and puts away the next oldest. Only if one group alone were still too big would tools be cut one by one (the core and the open view's kept, `other` first). What was put away or left out is said in a note in the chat, to the model in an app note, and in the `daw_more_tools` reply, which only ever names tools that are really offered (never the app-only `meters_stream_info`). The system prompt is another 37,000 characters on every step. A tool that is not offered still asks before it changes anything. **The prompt cache:** the tool list is the first block of the model's cached prompt, so a change to it (a group asked for with `daw_more_tools`, or a view that needs another group) rewrites the cached conversation once, at the cache-write price, instead of reading it at the cheaper cache price. To keep that to once, a group once offered stays offered for the rest of the conversation (changing view never takes tools away), unless the limit makes the app put it away as above; the cost line above the chat shows what a conversation really cost |
| a bounce never replaces a file | `session_export_mix` onto a path that exists is not proposed (the engine would replace it): the model picks a new name. The file checked is the one the engine would write (its name without the suffix, plus `.wav`, in any letter case), and a path with a control or invisible character in it (a NUL cuts a name short in the engine) is refused. A file that appears while the card waits stops it too. A running export is polled with `export_status`, which waits a few seconds when the job is still running, and a poll is not "the same call three times" (it is a circle only after 12 identical answers, and the note then says 12) |
| **Hear it** (the scripted demo's cards, with an engine) | really changes the open session, so it counts as an unsaved change, and the card says plainly **LIVE NOW** while it is being heard (it is never saved: Hear it again, Cancel or Approve puts it back first). The app holds what puts each value back and does it when the card is cancelled, approved or replaced by another card's Hear it, when the session is saved (however the save reaches the engine: the Save button and Ctrl/Cmd+S, a "save and go on" answer before a stop, restart, open or new, the Review panel's scan, and the Assistant's own save and scan: all put it back first, so a tried value is never written into the session file), when the page reloads or closes (the page's heartbeat stops for 8 s, or the next page load asks at once) and never into an engine that restarted. Only faders, pans, mutes, solos, sends and plug-in settings can be held |
| a window the app only attached to | the Assistant uses it only when it answers the handshake with the engine's own name and has the engine's core tools; nothing a foreign window wrote reaches the model as words: only the engine's own tool names are offered, each with this app's own title, and its schemas are rebuilt from property names, types and numeric limits (no description, enum, default or odd property name is copied; a newer tool this app does not know is not offered through an attached window). The name check is not authentication: a program of the same user can copy the name, which is why it is given no words of its own and why every change still needs your card. A stranger on the port is named as such and nothing is sent to it; the handshake is checked again before the overview and every call |
| an unanswered card expires | after 10 minutes: nothing changes and the model is told. A change the engine does not answer within 30 s is reported as "may or may not have happened: read it back" |
| the engine restarts | the conversation goes on. The next message tells the model (and you) that the session went back to its last save; a card approved after a restart is not applied |
| an export runs | the engine refuses `transport_*` (except `transport_get_state`) and a second export with `-32003`; the card says plainly that a bounce is running, nothing changed, and to check `export_status`. `-32002` from `region_get_peaks` is said as "still building this file's waveform: try again in a few seconds" |
| **scan this song** | `scan_session`: after Approve, runs the Review panel's own Scan session job (saves the session, bounces the mix, `hypnomix scan --mix` into `scan/<Song> (DAW)`, so the findings show in the Review panel), then the Assistant reads the review and explains the findings. The scan folders it is shown (`list_songs`, `scan_session`, `read_review`) have the home folder as `~` so a login name never reaches a model, and `read_review` takes that form back |
| the provider is busy or out of quota | `RateLimitError` / 5xx after the SDK's own retries: tried again after 10, 30, 60 s (or the provider's `Retry-After` / Gemini's `retryDelay`), each wait said in the chat and ended by Stop; a wait over 90 s (a daily quota) is not waited for: the error names the quota and when it resets. Gemini's errors come as a list body, so their message is read from it (not "Error code: 400") |

After approved calls the view reads the mix again from the engine (regions are placed again after a region change;
the whole session is read when a plug-in, region, marker, name or track was added or removed, or after an undo). A
mute, solo or plug-in on/off is read back until the engine shows it (it applies these a moment after it answers). Without a
key, without the engine, or with the page opened outside the app, the Assistant column is the scripted demo
(marked **DEMO · SCRIPTED**): its proposals are real edits on the same path as yours, but its replies are canned.

**Mixer, meters, devices and transport on the engine** (`daw/js/live.js`). **The meter stream** comes first: the
engine measures every route off the audio thread and pushes about 20 frames a second over a WebSocket on a loopback
port of its own (MCP `meters_stream_info` gives `ws://127.0.0.1:PORT/meters?token=T`). The page opens
`ws://<the app>/api/daw/meters?t=<the page's token>` (`hypnomix/app/daw_meters.py`): the app checks the token (and
Host and Origin, as for every request), asks the engine where its stream is, opens it, and copies the bytes both
ways, so the page never learns the engine's port or token, and the engine refuses any browser Origin that is not
loopback. How another web page is kept out: both the app and the engine's stream listen on 127.0.0.1 only; the app
refuses a Host that is not 127.0.0.1 or localhost (a DNS-rebinding page carries its own name there), any Origin but
its own two (`http://127.0.0.1:PORT`, `http://localhost:PORT`; a browser always sends Origin with a WebSocket) and a
request a browser marks `Sec-Fetch-Site: cross-site`; then `t` must be the page's token (written into the app's own
page, which another page cannot read), compared in constant time, or it answers 403. The engine's address comes from
`meters_stream_info`, which only the app calls: the page's `POST /mcp` refuses that tool (`daw.APP_ONLY_TOOLS`) and
the Assistant is never offered it. At most four streams are open at once (each holds one of the app's threads): a
fifth closes the one open longest (so streams nobody reads cannot keep the page out), and only when none gives way
does it answer 429. A stream is closed when nothing comes from either side for 15 s (the engine sends about 20 frames
a second, so quiet means it has gone) or when one side takes nothing for 5 s, and the engine's answer to the upgrade
must come within 3 s in all; the page then polls `meters_get` and tries the stream again. The token travels in the query because a browser's WebSocket cannot send a header of its own;
the app does not log request lines. Each frame carries, for every route and the master: peak and RMS per channel (dBFS, at the route's meter
point), momentary / short-term / integrated LUFS (integrated since the transport last started), the estimated true
peak and its maximum, stereo correlation and 8 band levels (the Hypnomix Probe's own measuring and band splits), the
playhead `sample`, `rolling`, `speed` and `exporting`, and the readings of each Hypnomix Probe / Main (output
values, by parameter index, when they change). The meters, the playhead's clock and the devices' readings take
their values from it, the transport bar shows one number, the master's short-term loudness (LUFS), at every width,
and the status bar the rest: **M** (momentary LUFS), **TP** (dBTP) and **C** (correlation); no width rule hides or
reshapes the loudness readouts. A screen reader hears them in words (master loudness short-term, momentary loudness,
true peak, stereo correlation). When the stream drops, the loudness readouts go until it is back (they only come with
the stream), so no stale number looks live. The status line also says **meters streaming**. With no stream (an engine without it: the relay answers 503), or when it
drops (it is opened again with a growing pause, up to 30 s), one poll loop asks `meters_get` (it also
carries the transport's `sample` and `rolling`) about 15 times a second while playing and twice a second when stopped,
never with two requests out; the first call passes `ensure_rms:true`, which switches the routes' meter type to
RMS + Peak so the meters draw peak (light) over RMS (solid) with a held peak on the track headers, the Mixer and the
master. The meter type is kept in the session file, so on a session with nothing unsaved the app takes `ensure_rms`
out of that call and sends it with the first change (from the view, the Assistant or a command): looking at a session
never makes it unsaved, and until then a session whose meters were never switched shows peak only. The status line says **meters live**. The playhead is interpolated between polls by a gentle phase-locked
clock: it learns the engine's real speed (a dummy or busy backend runs slower than the wall clock), never steps
backwards, and snaps only on a jump (locate, loop). Every mixer change (fader, pan, mute, solo, arm, send level,
colour, order) and every device change is read back from the engine (`track_get_info`, `plugin_get_description`)
a moment later; a light refresh every 3 s (`tracks_list`, `track_get_info` per route, `session_get_info`) picks up
changes made by the Assistant or another client, and a track added or removed elsewhere makes the view read the
session again. Track order is `track_reorder {order}` (one undo step in the view; the engine cannot undo it), delete
is `track_remove {confirm:true}` after a confirmation, colours are `track_set_color`. The device chain is the track's
real plug-ins: knobs (log, integer, toggle and list parameters as the plug-in describes them) call
`plugin_set_parameter_by_index_value`, the light `plugin_set_enabled`, dragging a title `plugin_reorder`, × twice
`plugin_remove`, and **+** or a double-click in the browser (whose Audio Effects, Plug-ins and Hypnomix Tools lists
are the engine's `plugin_list_available`) `plugin_add_by_plugin_id`. Output parameters (the Hypnomix Probe's
loudness and peaks, a compressor's gain reduction) are shown as readings, refreshed every second while playing (the
Hypnomix devices' readings also arrive with the meter stream, as they change).
Transport: play, stop, locate, loop (the range is set from the view first: `transport_loop_location_samples`) and
record, with the loop range read from the session's markers. The time signature and track colours come from the
saved session file (`POST /api/daw/meta`, `hypnomix/app/daw_meta.py`), since no MCP tool reports them; a colour set
since the last save is remembered by the browser for that session.

**Group tracks and sidechains on the engine** (`daw/js/groups.js`, `daw/js/sidechain.js`). A group track is what
Live has: on the engine a route group plus its subgroup bus, made together by `group_create` (the tracks'
outputs go to the bus, the bus goes to the master and sits right above its tracks). The view reads `group_list`
with the session and every 3 s: the bus is the group's header in the Arrangement and the Mixer (its fader is the
group fader), its tracks are indented under it, and **▸ / ▾** on the header folds them away (`group_set folded`,
the route group's hidden flag, so it is saved with the session). **Group…** in the Arrangement's tools (⌘G) asks for
a name and the tracks (every selected track ticked: shift-click a track header, mixer strip or Session column
header for the range from the last plain click, ⌘-click (Ctrl-click on Windows) to add or take away one; `HX.selectClick`
in `daw/js/store.js`; a press on a button, a value, or the Mixer's fader or knobs inside a header or strip keeps the
selection, so shift-dragging a fader stays the fine drag) and makes the group. The dialog works by keyboard: Tab and
Shift+Tab go round the name box, each track's tick box and the buttons (the focus starts on Cancel), Space types a space
in the name and ticks a box, and Enter only presses a focused button. ⌘G with no engine says groups need the engine.
If the group is made but reading the session again fails, the view says so ("Grouped as …, but the view could not read
the session again") instead of "Not grouped", and reads it again within a few seconds. A track folded away is never the
selected one: the up and down arrows skip it, M and S do nothing to one, and folding a group that holds the selected
track (from this view or from the engine) selects the group's header instead. **Ungroup** on the header (`group_delete`, named
"Ungroup <group>" for a screen reader)
sends the tracks to the master again and removes the bus. Both ask first: the engine keeps routing, route groups and
plug-ins out of its undo history, so neither is a step of ⌘Z. A device that can take a key (`plugin_get_sidechain`:
an ACE Compressor, Expander, any plug-in with sidechain pins) shows **Sidechain: none / <track>** (every other track and bus but the master and its own group's bus, which would feed back): choosing a track
calls `plugin_set_sidechain` (a pre-fader send from that track into the plug-in's key input, and the plug-in's own
Sidechain switch on), **none** removes the send; that choice is an ordinary op, so ⌘Z sends the previous source
again. The Assistant reads `group_list` and `plugin_get_sidechain` at once; every group and sidechain change is a
proposal it asks about. Not done yet: dragging a strip in the Mixer while a group is folded counts only the strips
shown; nested groups are made by the engine but drawn one level deep.

**The Arrangement on the engine** (`daw/js/regions.js`, `daw/js/arrange.js`). Regions come from
`track_get_regions` (place, length, name, mute) and `region_get_info` (gain, and the fades: `fadeInSamples`,
`fadeOutSamples`, `fadeInActive`, `fadeOutActive`, `envelopeActive`; a fade that is switched off is drawn as none).
Waveforms are the engine's peaks (`region_get_peaks`), which the engine builds itself for every region, also for a
session or an import that had no peak files: tiles of 2048 pixels at a power-of-two samples-per-pixel matched to the
zoom, cached by region id + resolution + tile, asked for after the view has rested 140 ms, two requests at a time, each
within the engine's own cap of 40000 [min, max] pairs over all channels (the engine writes its replies in 16 KB
chunks with a Content-Length, so big or overlapping replies arrive whole; each reply is still range-checked and asked
once more when it is not). Each region also gets one coarse pass (48 points a beat) for the clip detail and while
tiles load. `-32002` means the engine is still building that file's peaks (just after an import): the region says
"the engine is building its waveform" and the view asks again, backing off, for up to about two minutes (a tile asks
again after 5 s). Edits are ops on the same path as every other change (`{trackId, param, key, before, after}`), each
one engine undo step:

| edit in the Arrangement | op `param` | engine tool | engine undo name |
|---|---|---|---|
| drag a clip (also onto another track; ⌘ = no snap) | `regionMove` | `region_move_to_sample` (+`trackId`) | move region |
| drag a clip's left / right edge | `regionTrim` | `region_resize_samples` | resize region |
| click (sets the playhead), ⌘E | `regionSplit` | `region_split` | split region |
| drag a top-corner handle | `regionFades` | `region_set_fades` | set region fades |
| drag the gain line (4 px a dB, shift = fine) | `clipGain` | `region_set_gain_db` (sent once, on release) | set region gain |
| 0 | `regionMute` | `region_mute` | mute / unmute region |
| Delete / Backspace | `regionRemove` | `region_remove` | remove region |
| drop files, or **Import…** | `regionImport` | `session_import_audio` | insert file |

Undo and redo of these run `session_undo` / `session_redo` one step at a time and check each step's name; when the
engine's last step is not this edit (the Assistant or another client changed the session), it is put back and
nothing is undone. The engine keeps 200 undo steps. After each edit, undo or redo the view reads the touched tracks
again from the engine: places, lengths, gains and fades (`region_get_info`), so what is drawn is what the engine has;
a clip-gain edit reads its region's gain back the same way. Other ops (faders, pans, mutes, solos, sends, colours,
plug-ins) go through the mixer's path (`daw/js/live.js`): sent while you drag, re-sending their before / after value
on undo and redo, and read back with `track_get_info` a moment later. Edits, undos and redos reach the engine one
after another, so an undo never overtakes the edit it undoes, and an op the engine refuses is taken out of the view's
history (it is not in the engine's either). With the demo song the same ops apply locally.

**Automation lanes and the tempo track** (`daw/js/automation.js`, with small hooks in `arrange.js` and
`regions.js`). On an engine that lists `automation_list`, a track header's **A** button opens a chooser of the route's
automatable controls (`automation_list`: fader, trim, pan, width, mute, sends, plug-in parameters); each ticked one is a
lane under the track (and under its take lanes), its points read with `automation_get` (seconds, natural units). Which
lanes show is remembered per session in this browser. Every gesture is ONE engine call and ONE engine undo step on the
shared op path: dragging a point writes the stretch from the point before it to the point after it again
(`automation_write`, `replace-range` from a hair before the first to a hair after the last, `guard: false`, so the
outer points are written again as read: the engine reports values to 0.001 dB, and a guard point beside a point read
that way would be a jump it refuses; level controls with `curve: s_curve`), a double-click adds one point on the line
as it is (nothing heard changes), ⌥-click or Delete removes a point (a level point by writing its neighbours again as
one S-curve, any other with `automation_clear`), and Play / Off is `automation_set_state` (not an engine undo step, as
in the editor: its undo sets the old state again). Undo and redo go through `session_undo` / `session_redo`, checked
against the engine's step names (*write automation*, *clear automation*), and the lane is read back after each. On a
focused lane header the keys are ← → (pick a point), ↑ ↓ (move it 0.5 dB, ⇧ 0.1 dB), A or + (add at the playhead),
Delete (remove) and P (play / off). Level lanes keep to the smooth-automation rules while dragging (no point more than
3 dB, a trim 4 dB, from the lane's original line, which the page reads from the app, `POST /api/daw/original
{track_id, control}` → `{points}` or `{value}`, so a second drag of 3 dB stops where the first left it; the steepest
point under 7 dB/s; the first and last points keep their value; a lane that is Off is heard at the control's value, so
a write or Play on it is checked with its points as a whole first), and the app's engine
connection checks the same rules (`engineer/automation_rules.py`) and the bus rule before the call is sent (under any
name the engine takes for the tool, `automation_write`, `automation/write` or `automation.write`, and the fader's
aliases; a bus that feeds the bus is read in turn and judged by what it carries, not by its name); a refusal
puts the lane back and shows the sentence. The bus rule covers plug-in lanes too: on a bus, a group's bus or the master
the page asks the app what it carries (`POST /api/daw/carries {track_id}` → `{trackName, others, level, plugin}`, the
two refusals in the app's words, "" when allowed) and refuses a level or plug-in write there before sending it (a
drag does not start); clearing a point is still allowed. The draggable points of a level lane are where its line turns or is flat; the
S-curve's own points are drawn, not dragged. The **Tempo** button shows `tempo_get_map` as a row at the top: each
tempo point, a ramp drawn as a slope to its end tempo, labelled; the bar grid still counts at the first tempo. With the
mock session the first vocal track has a fader lane with one ride. Tested with stand-ins (`tests/test_daw_automation.py`)
and in a browser against a development build of the engine on its silent test backend.

**Takes and comping** (`daw/js/takes.js`, with small hooks in `arrange.js`, `store.js` and `regions.js`). On the
engine a track's takes are its playlists named `<track>.take N` (`take_list`); the track plays its comp, its active
playlist. A recording pass lands on the comp and also goes into a new take (the engine's session option
`hx-record-takes`, on by default); `playlist_new` makes an empty take (or one copied from the comp with
`copy_active`). A track with takes gets a **T** button on its header: it shows one lane per take under the track,
drawn from the engine's peaks like any region, with the stretches the comp plays from that take lit (a comp region
that plays the take's file at the take's alignment). Dragging across a take lane (snapped; ⌘ = no snap) comps that
range: op `takeComp` → `comp_range {track_id, take, start_sample, end_sample, xfade_ms: 10}`, ONE engine undo step
("comp range", undone and redone with `session_undo` / `session_redo` like the region edits). The take plays alone
from start + 5 ms to end − 5 ms, the comp is untouched outside start − 5 ms .. end + 5 ms, and each join is a 10 ms
crossfade centred on it; comp regions inside the range are removed, those across a join trimmed (or split). The view
then reads the track's regions and takes again. The comp's pieces are ordinary regions playing the take's own file,
so fixes stay clip edits on the comp and the takes are never changed. With the mock session the first vocal track
gets three invented takes and the comp is done locally (undo puts the clips back). The Assistant reads takes at once
(`playlist_list`, `take_list`); `comp_range`, `playlist_new` and `playlist_select` are proposals ("Vocals · comp
10–14 s: take 1, 10 ms crossfades (one undo step)"). **By keyboard** each take's header is a group named "Take 2 of
Vocals" (", in the comp" when the comp plays from it) with a **Comp** button: it asks for the bars (from the loop range,
or four bars from the playhead when there is none) in a dialog and makes the same comp as a drag, one undo step. A drag
that is under way when the session is read again (a group made, an engine restart) is dropped quietly. After the T
button, a fold button or any redraw of the track headers, the control that had the focus has it again (found by its
track and its kind, not its name, which changes with its state); a track folded away hands it to its group's header.

**Import.** A page cannot see a dropped file's path, so a drop sends the file to the app first:
`POST /api/daw/upload?name=F` (the raw bytes, the page's token; audio types only, up to 4 GB) saves it in
`daw-uploads/<random>/F` in the app's work folder (`~/Documents/Hypnomix`, or `HYPNOMIX_APP_HOME`; `HYPNOMIX_DAW_UPLOADS`
names another folder). Only the app's own random folders there that are older than a day are removed, whatever else
the folder holds. Then the page calls `session_import_audio` on that path: onto the track it was dropped on
(`mode:"to_track"`) or as new tracks, at the drop point. **Import…** takes typed or pasted absolute paths. The app
gives `session_import_audio` up to 10 minutes (the engine copies the files before it answers). An import's undo
removes its regions; new tracks stay (the DAW does not undo track creation).

**Review in the DAW.** Connected to the engine, the **Review** view (⌘4) runs the real HypnoMix first-pass loop on the session
the engine has open (`hypnomix/app/dawreview.py`; the demo song keeps its scripted findings):

| step | what happens |
|---|---|
| **Scan** (asks first) | saves the session (`session_save`) when it has unsaved changes (the request must say `"save": true`, which the view sends only after you click **Save and scan**; without it the route answers 409 `unsaved` and does nothing; a session with nothing unsaved is not saved again), bounces the mix into the scan folder (`session_export_mix`, progress from `export_status`), then runs `hypnomix scan SESSION.ardour --mix "<scan>/mix (engine bounce).wav"` through the app's job runner, with its progress in the view. The scan folder is `~/Documents/Hypnomix/scan/<snapshot> (DAW)` |
| the findings | the real `findings.json` as master and detail: each with its track, where it is, what Apply does with it, and its evidence (the short-term level of its track, from the scan's render or the recording it names, and of the bounced mix, with the spot shaded). Selecting one moves the playhead to it (`transport_locate_sample`) and selects its track; the findings are also marked on the Arrangement |
| **Approve** / **Skip** / **Change** | saved at once in the scan's `decisions.json`, the same as `hypnomix fix --decide` and the Songs review (clicking the same one again clears it). **Change** takes a note: saved as a change request, or (for a fix Apply writes) **Approve with this note**, where settings such as `fade-ms=20` or `amount=0.3` tune the fix. Tuning cannot be approved here yet (it is not written into a HypnoMix Studio session) |
| **Apply** (asks first) | `hypnomix fix SCAN --approved --out "<snapshot> (hypnomix).ardour"`: ONE new snapshot in the session folder (numbered when that name exists; the open snapshot is never written). It writes region fades, cuts, spike dips and mixer moves; repaired recordings (de-ess, breaths) are made as new files beside the originals; the rest stays by hand, as the detail says. Then **Open snapshot** restarts the engine on the new snapshot (the supervisor's `open`) and the view reads it again; nothing opens without that click |
| **A/B** | where `hypnomix ab` can build a pair for a HypnoMix Studio session: repaired recordings and tuning (**Build A/B**, then A and B, level-matched). Clip and mixer fixes (fades, cuts, spike dips, fader / pan / mute): **Build A/B session** runs `hypnomix abset SCAN --out "<snapshot> (A-B).ardour"` (`workflow/abset_ardour.py`: one new snapshot, each clip fix as another playlist of its track named `<playlist>.B <id>`, each mixer move as A/B values, `match_db` from a rough mix without plug-ins around the spot, muted tracks left out so a mute or unmute fix is matched too; mixer A/B fader values are the fader alone, without the track's trim; `ab_ardour.json` in the scan keeps every snapshot built from it, so a numbered rebuild leaves the earlier one reviewable; the snapshot is written to a hidden name, checked, and only then put in place, never over a file or through a link). **Open A/B session** (asks first) restarts the engine on it; the view then still reviews the original's scan. **A** / **B** (or `B`) switch the finding over MCP while it plays (`ab_use_playlist`, or `track_set_fader_db` / `track_set_pan` / `track_set_mute`), the louder side turned down on the master fader by `match_db` (at most 12 dB: a fix that silences or brings in most of what plays at the spot keeps its measured difference as `level_db`, with `match_capped`, and the note under A and B shows that difference and the 12 dB it is turned down by) and put back when you move on, before a Save or a scan, when you leave Review and when the page closes (kept-alive calls, nothing waits for them). The switches run one after another, so fast presses never overlap; the master's level to come back to is read from the engine (`track_get_info`) when a flip starts from A, never from the view's own copy; a switch that fails half-way puts A back and says so (checked against a stand-in engine in `tests/test_daw_review_ab.py`, not yet with a real A/B session open). `HX.onEnd` (`daw/js/util.js`) is the one list of things a Save, a scan or a closing page puts back first (the Assistant's **Hear it** is the other); **Blind** plays X and Y in a random order, you choose, then it says which was which (kept in the scan's `blind.json`) |

If the session is changed while the mix is bounced, the scan stops and says so (its findings would not match the mix). Apply writes its new snapshot whole or not at all.

The routes are `POST /api/dawreview/scan`, `decide`, `apply`, `ab`, `abset {dir}`, `blind {dir, id, picked: X|Y, was: A|B}`
(with the page's token) and `GET /api/dawreview/state` (with `ab_session` when the engine has a scan's A/B snapshot open),
`findings?dir=`, `evidence?dir=&id=`, `abstate?dir=`; progress is the app's `GET /api/job`.

**The Session view on the engine** (`daw/js/cues.js`, `daw/js/clips.js`). The grid is the engine's cue slots: every
audio and MIDI track's 16 slots from `cue_list`, read about every 600 ms while the Session view is open (every 150 ms
while a clip is queued or playing, never two requests out), and not polled in the other views (read once when the
session or the engine changes, and soon after play or stop in the Session view; a read that is already due sooner is
never put off, so frequent events cannot hold it back). A failed read is said under the grid at once ("cue slots: …"), and the
playing slots' bars stop moving until a read works again. Launching and stopping change nothing that is saved, so they
do not mark the session unsaved; filling or clearing a slot does. A click on a clip is `cue_launch` (it starts on the slot's
quantization, the next bar by default, and rolls the transport if it is stopped; a clip playing on the track hands
over there); an empty slot or a track's stop button is `cue_stop {track_id}`, the bottom-right stop `cue_stop {}`, a
scene (or keys 1-8) `scene_launch`. Slots light as the engine reports them: queued (`waiting_to_start`), playing, and
stopping or switching on the next bar, with the clip's position between polls moved on by the clock. To fill a slot,
drag a region from the strip under the grid (the selected track's regions) onto it, or drop an audio file (uploaded
as for an import, then `cue_set_clip {file}`); × clears it. `cue_set_clip` answers once the clip is loaded, so the app
gives it 90 s. While any slot of a track holds a clip (launched or not), that track's Arrangement regions do not
play (the engine's default; clearing the track's last clip brings them back at once), so loops go on their own track: `hypnomix loops SESSION.ardour --track T --cues` and `hypnomix variations SESSION.ardour --cues`
make one next to the part (`hypnomix/project/ardour_cues.py`). Slot changes are not undo steps; save to keep them.
The command-line writers into the open engine (these two with `--cues`, and `tidy`, `order` and `duck` on a
session with `--engine --ids`) first check that the engine has that very session file open, by its full path: a
copy of the same name in another folder, another session, or an engine that names no saved file is refused with
one sentence and nothing is written. `duck` also checks that each route id still carries the track name the scan
saw, and for a tune that the plug-in at its index is the ACE Compressor. A clip that finds no empty slot, or an
option not written, makes the command exit 1; an id given to `--ids` that is not among the options listed is
refused before the engine is asked anything. The engine's address for `--engine URL` is in the engine panel.
**By keyboard** the slots are one Tab stop, together with each row's scene (at its right) and the stop buttons under
them (a roving tabindex: the cell last focused keeps it, also when the grid is drawn again after a poll). The arrow keys
move as the grid looks: left and right between tracks (and on to the scene), up and down between slots (and on to the
stop buttons; Home / End to the row's ends, Page Up / Down to the column's ends). Moving onto a track's slot selects
that track, so the strip under the grid shows its regions. The region chips in the strip are buttons: Enter on one
picks it (it shows pressed, the focus goes back to the grid), then Enter on a slot puts it there, the same
`cue_set_clip {region_id}` as a drop; Esc lets it go. Scenes are named "Launch scene 2, 3 clips", stop buttons "Stop the
clip of Drums" and "Stop all clips". Messages (the toasts) are a polite live region, so a screen reader hears them.
When less motion is asked for (the system setting), the slots' lights hold still instead of blinking. The names were
read from the page, not with a real screen reader, and the still lights were not looked at with the setting on. Enter or Space is a click on the slot
(launch, or stop the track on an empty one) and Delete or Backspace is the slot's × (the same `cue_set_clip {clear}`,
toast and unsaved mark; there is no confirmation, as for ×). The slots are buttons named for a screen reader as
"Drums, slot 2, Loop A" or "Drums, slot 3, empty", with ", playing", ", queued" or ", stopping" while lit, and the
focus ring is 2 px in the text colour around a band of the page colour, so it reads on every clip colour in both
themes. A slot the mouse clicked does not take the keys (Space still plays, the arrows still move the playhead).

**While an export runs** (Review's scan bounces the mix with `session_export_mix`; the Assistant or another client
may too), the engine refuses every `transport_*` tool but `transport_get_state` with `-32003`, so a bounce cannot be
cut short. The view reads `export_status` on its light refresh (every second while a job runs) and at once when a
transport call comes back `-32003`: the play, stop, go-to-start, record and loop buttons are disabled, the transport
bar says **Exporting N %**, the keys and clicks that would move the playhead say why instead, and the engine's
freewheeling (it reports `rolling` while it bounces) is not shown as playback. When the export is done the buttons
come back and the view says so.

From the engine now: meters (peak over RMS), the playhead, every mixer and device setting, regions with their gain
and fades, and real waveforms for every region. Not from the engine yet: the transport's loop and record state (no
tool reads them without changing them, so the buttons show what was last set here; `transport_loop_toggle`'s
`playLoop` is the state *before* the request, so it is not read back, and turning the loop on while stopped starts loop
playback, as in HypnoMix Studio), track colours since the last save (as above), the DSP load (not shown) and the time signature
changing (read at connect). Region envelopes are read (`envelopeActive`) but not drawn. With an older engine whose
`region_get_info` has no fade fields, the view falls back to remembering the fade lengths it set in this browser (per
session and region; after a split each part keeps the fade on its outer edge and the engine's 64-sample fade at the
cut). Demo-song only: tempo changes (no MCP tool for tempo yet). On the demo song,
Review's findings are scripted.

**Environment variables** (the ones DAW mode, the Store and `chain --ardour` read, and the folders a test run moves):

| variable | what it does |
|---|---|
| `HYPNOMIX_PORT`, `HYPNOMIX_PROBE_PORT` | the port the app listens on (default 8791) and the UDP port the probes report to (default 8792); a test copy sets both, and so do the devices made for it |
| `HYPNOMIX_DAW` | `1` is the same as `--daw`: open the DAW view first (a developer's switch; it does not find an engine) |
| `HYPNOMIX_ENGINE` | the `hypnomix-engine` program to run (also `"engine"` in `daw.json`) |
| `HYPNOMIX_ENGINE_ARGS` | extra arguments for the engine (also `"args"` in `daw.json`), such as `-b "None (Dummy)"` |
| `HYPNOMIX_ENGINE_SRC` | developers only: the folder of a source build of the engine, run with its own environment script (nothing is guessed when it is not set) |
| `HYPNOMIX_ENGINE_URL` | the MCP address to attach to when no engine program is found (default `http://127.0.0.1:4820/mcp`) |
| `HYPNOMIX_MCP_URL` | the MCP address `chain master --ardour` talks to (default the same; `--mcp-url` for one run) |
| `HYPNOMIX_DAW_UPLOADS` | where dropped audio waits for the engine (default `daw-uploads` in the app's work folder) |
| `HYPNOMIX_STORE_ROOT` | puts every Store target (plug-ins, library, manifest, downloads) under that folder, for trying the Store out; it also lets the Store run on a system that is not a Mac |
| `HYPNOMIX_STORE_NO_OPEN` | the Store does not open Apple's Installer for a `.pkg` item (for tests) |
| `HYPNOMIX_GITHUB_TOKEN`, `GITHUB_TOKEN` | a GitHub token for the Store's release look-ups (a higher limit than the 60 an hour without one); only sent to GitHub |
| `HYPNOMIX_UPDATE_URL` | tests only: a feed on this computer (`http://127.0.0.1:PORT`) in place of GitHub's release list for the updater |
| `HYPNOMIX_UPDATE_GRACE` | seconds (default 45) the updater waits for the app and the engine to quit before it stops what is left and swaps the app |
| `HYPNOMIX_DISKCARE` | `off` keeps Disk care's hourly look from starting (test and preview copies of the app) |
| `HYPNOMIX_TEST_HOOKS` | tests only: `1` adds two routes that make a real crash on demand (`POST /api/test/crash`, `POST /api/test/jobcrash`, token as for every POST), to try the crash record and the page's notice. Not set in a normal run: the routes do not exist then |
| `HYPNOMIX_HOME`, `HYPNOMIX_APP_HOME`, `HYPNOMIX_USER_HOME`, `HYPNOMIX_OUT` | where the settings, the app's work folder, the home folder Disk care measures and the default output folder are. A test run sets all four (and `HOME`) to folders that exist: `tests/_isolate.py` does it for the unit tests when they are unset |

## The installed app (Mac and Windows)

The installers on the [download page](https://hypnomix.bradfieldenterprises.org) install the same app with its own
Python and ffmpeg inside it. On a Mac it is `Hypnomix.app` (a window of its own; quitting it stops it). On Windows
the Start menu's **HypnoMix** opens it in your browser and **Quit HypnoMix** stops it. Your songs' scans are kept in
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
- The app remembers where HypnoMix is installed. If you move or reinstall that folder, build again (or the
  app asks you to point at the folder).
- It is the same page as `hypnomix app`. Nothing is lost by using the browser instead, and on Windows
  the browser is the way (on Linux too, but the project does not test on Linux).
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
