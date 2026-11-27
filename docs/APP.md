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
| DAW | HypnoMix DAW's window on its engine, with the Assistant beside it: see "DAW mode" below (the first page with `hypnomix app --daw`; only there when an engine is found, attached or `--daw` was given: the engine is an add-on, not available yet) |
| Songs | choose a Live set (.als), a REAPER project (.rpp), a HypnoMix DAW session (`.ardour`) or a folder of recordings from any DAW, with the chooser or by pasting the path (a pasted path may keep the quotes a file manager's "copy as path" adds; where the app has no chooser, as in the installed Windows app, the page shows only the Path boxes); optionally a bounce of the mix, a song you love, the key (the browser remembers this form, and the tab and review you were on, so a refresh puts you back). "Start the first pass" runs `scan`, then `ab`. Each song has its own scan folder: the same path always goes back to it (a re-scan), a different path never shares one even with the same name (`Song`, `Song (2)`), and a card shows its folder when two songs share a name. **Re-scan** on a card runs the scan again; a Live set keeps your decisions (`scan --since`), the other kinds set the old answers aside in `decisions before re-scan.json`. A song whose results or decisions file is damaged stays in the list with a red tag. With no songs yet, **Try it on a demo song** (when `hypnomix demo` exists) makes a short demo song in the app's folder and scans it |
| Activity | how far the command has got, from what it prints (never a percentage): a scan says "4 of 12 checks done", which checks are still running and, when an earlier scan of the song exists, about how long is left from that scan's own seconds (a first scan shows the time so far and says there is no estimate); the clip builder and an apply show their steps. Then the log of each command as it runs, with a Stop button that ends the command and everything it started (each job runs in its own process group), removes the temporary `(fix step N)` sets a stopped fix left, and lists the files a finished job made, each with a Show-in-folder button. A failed job says why in the command's own words. The log keeps the newest 4,000 lines of a long command (`LOG_KEEP`): the oldest 1,000 go each time it passes that, and a page that had not read them yet says "N older lines of the output left out", so the last lines of a long job (its summary, its exit code) always show |
| Review | the fixes you can hear first, by severity (then the ones with no clip yet, then questions for you: a key question has an answer box, and what you type goes in with Apply as `fix --answer`); by-hand and info items wait in a collapsed **By hand in your DAW** section with the handoff button, outside the approve / skip flow. A filter row (All, Undecided, Approved, Skipped, To change, By hand, and by tool) is remembered per song. **A long review** (more than 150 cards on screen: `LAZY_ABOVE` in `review.js`) is built a page at a time: every group keeps its full count in its heading, the first big group opens with its first 100 cards, the other big groups wait behind a **Show the first 100** button (a group of 40 or fewer is built whole), an open group builds 100 more when its end scrolls into view (or with its button), the by-hand and low-priority boxes build their cards when they are opened, and `j` / `k` / `[` / `]` / `a` / `s` build the card they reach. The bar, the counts and the Apply card read the findings, never the page, so they always cover every finding. A short review is drawn whole, as before. "The N like this" counts come from ranges in `oversight.like_runs` (positions in `like_order`) instead of every id list (`/api/review` for 2,000 findings: 5.7 MB before, under 2 MB, about 100 KB gzipped), and a note comes back as that finding's notes (`/api/note`) instead of the whole review being fetched again. Each card has one player with **A** and **B** buttons that swap the clip at the same moment. Approve, Skip or Change with a note, at the keyboard (see below) or with the mouse; a decision changes only its own card, the counts and the Apply card, never the list, so the clip you are hearing and your place on the page stay. It remembers which clips you played: the bar says "12 approved, 5 of them never played" and an approval with a clip you never heard is marked on its card (it never blocks a decision). **Approve all low…** and **Approve the N like this** show the whole list first (id, track, what, whether it has a preview, whether you played it) and record nothing until you confirm; "all low" never takes tuning, harmony balance, motion, colour, borrowed moves or variations (taste calls), a track reorder, removal or merge, a protected track or a by-hand item. Saved as you act. Steps that are **on by default** (track order, removing switched-off tracks, one instrument onto one track) show "On by default" and **Turn off** (it records a skip); banners say if the project was saved after the scan, or the original is missing. **Re-scan** and **Make the handoff list** (`hypnomix handoff`: a checklist and a marker at every by-hand spot) are in the header. A damaged `decisions.json` shows what was lost and, if `decisions.json.bak` exists, **Restore the backup** (the damaged file is kept as `decisions.damaged.json`) |
| Apply | says first what will happen: how many approved fixes, which on-by-default steps also run and what each does (the archive copy it writes and how many tracks it removes), how many approved items are by hand and will **not** be applied, and the exact file names it will create. The new file takes the ending of the project (`.als`, `.rpp`, `.ardour`; nothing for a folder, whose repaired copies go to the scan's `fixed` folder), is named `Song (fixed).als`, then `Song (fixed 2).als` if that is taken, and the name can be edited. Apply is enabled only when something can really be written; a by-hand-only selection offers the handoff list instead. Then it writes only that (`fix --approved`) |
| Result | after an apply: the new file and its folder with a Show button, what was applied, what was not and why, any FAILED line in red (said in the page's words: the box to fill, not a command-line flag), "listen at these spots" from the applied findings (only when a new file was written: a run that stopped before writing anything says "Apply stopped" and "Nothing was written", and one that stopped after writing says "Applied in part"), and buttons: open the review again, **Undo this**, make the handoff list. The log is shown as text under its own headings (not applied, on by default, failed), whatever those say |
| History | a collapsed section of the review (`hypnomix history DIR --json`): every apply of the song, with **Undo** (`history --undo N`, after a confirm that names the file it will write) for Live sets. REAPER projects, HypnoMix DAW sessions and folders keep no snapshot, so the page says so instead of offering a button |
| Preferences | the questions asked once: targets, protected tracks, what is deliberate. The loudness and true-peak targets take any number the help names (the usual ones are suggestions), and a saved answer shows as the answer |
| Tools | every other command with its help and a form: tempo, variations, mastering, and the rest. **Add a set / an audio file / a folder** put the chosen path after the flag the command's own usage line names (`key` takes `--set` and `--audio`), or bare where the command takes it as an argument |
| Updates | the version at the top right: checks for a new version (once a day, or now), and in the installed app **Update now** downloads it, checks its fingerprint (against the release's own list: this catches damage or a swapped file, not a hijacked release, as installers aren't yet signed with a publisher key) and installs it with one click. Source installs are told to `git pull` |
| Disk care | the free space at the top right: HypnoMix clears its own bulky leftovers (render cache, audio in scans idle two weeks, `hypnomix-out` audio, HypnoMix's own temporary folders (`hypnomix-render-…`) a stopped command left, old master bounces, and the Store's unfinished downloads after 2 days, kept installers after 30 and the trash of replaced plug-ins after 60) weekly, and straight away when the disk is nearly full. Preview, clean now, switch it off, or also move old Desktop / Downloads WAVs to a 14-day holding folder. Audio a Live, REAPER or HypnoMix DAW project uses is never touched. Unprefixed temp folders that older versions left (`tmpXXXXXXXX` holding only WAV files or a small track-name list) are listed with their size and cleared only by a click on **Clear them** (`python -m hypnomix.app.diskcare --clear-old` from a terminal asks y/N first). Folders you add must be inside your home folder (not the home folder itself, Library, or all of Music, Desktop or Documents) |
| Teacher | teacher mode: a guided course in your DAW (Live, REAPER or HypnoMix DAW). The **tour** of HypnoMix and its devices for people who already engineer, the **101 crash course** (the words, recording to a click, each effect, mastering), or **The complete course, A to Z** (13 chapters, 138 to 146 lessons depending on your DAW: sound and hearing, digital audio, gear and rooms, recording, editing, mixing, mastering, releasing, troubleshooting and cheat sheets, with common mistakes, exercises, self-marking quizzes, **Hear it** audio examples made on the spot by `hypnomix/app/teach_audio.py` (cached in `~/.hypnomix/cache/teach`), and a searchable **Glossary**; the 101 course is a subset of it). The lessons are the package `hypnomix/app/lessons/` (one module per chapter) and are also the wiki's per-chapter course articles. Hands-on steps in Live and REAPER (tempo, click, a drum beat, an armed track, effects, the mastering chain) each wait for **Do it**. Progress in `~/.hypnomix/teacher.json` |
| Assistant | a chat with an AI of your choice that runs HypnoMix for you (bring your own key; Claude Sonnet 5.5 is the default model, every other model stays selectable) and, optionally, a Listener that hears a bounce. Shows the tokens and cost as you go (exact for Claude, an estimate for Gemini), clears old results from what it re-reads as a long chat grows, asks "keep going?" when one message uses more than 400,000 input tokens (a setting), and stops if it repeats the same call three times. Anything that writes waits for your click. Details: the wiki's "The Assistant and the Listener" |
| Setup | the guided setup (it opens by itself the first time): how you work (just the app, an AI key, a model on this computer, or a desktop AI app such as Claude Code), your DAW (Ableton Live, REAPER, HypnoMix DAW or something else; choosing HypnoMix DAW shows what it is and, once an archive is published, an **Add HypnoMix DAW** button: today it says it is not available yet and remembers the choice) and teacher mode, the key and a connection test, the connection to your DAW (Live's AbletonOSC script, REAPER's bridge), and for desktop AI apps a `hypnomix` command (one that is already there and was not made by the setup is left as it is) plus an agent folder. The dialog keeps the keyboard (Escape is the same as Skip setup), and the last step says when an AI chosen on the way was not connected. Costs and pros and cons for each: [Setting up, and choosing an AI](guides/09-setup-and-ai.md) |
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

## DAW mode: HypnoMix DAW in the app

What HypnoMix DAW is, and where it comes from: the wiki article "HypnoMix DAW".

```bash
hypnomix app --daw                              # the DAW view first; starts (or finds) the HypnoMix engine (the add-on)
hypnomix app --daw --session "Song/Song.ardour" # ... and opens that session in it
```

The **DAW** tab (first in the navigation; the page the app opens on in DAW mode) is HypnoMix DAW's window:
Arrangement, Session clips, Mixer and Review, the browser on the left, one device chain along the bottom and the
Assistant in its own column on the right. **Songs**, **Assistant** and **Wiki** at the top go back to the rest of the
app. Press `?` in it for every shortcut.

**When the DAW tab is there.** There is one app and one installer for everyone, and DAW mode's engine is not inside
them: HypnoMix DAW, HypnoMix's own DAW, is an **add-on** that is added from
**Setup** on a click (below). It is **not available yet**: the manifest shipped in the app names no archive, so there is
nothing to add, the app downloads nothing, and with no engine found the app shows no DAW tab. The tab appears when an
engine program is found (the add-on once it is added, or one of the lookups below), when the app is attached to a
running HypnoMix DAW window (see the table below), or when the app was started with `--daw` (`--session` alone turns DAW
mode on too). The add-on's fingerprint is checked when the engine is added, not again when it is started: the app starts the
program it finds (`engine/<version>/bin/hypnomix-engine`, or the one `HYPNOMIX_ENGINE` or `daw.json` names), and no request or
page can change which program that is; anyone who can write into your HypnoMix folder can already run programs as you. With no
engine connected the DAW view says so and offers **Start the engine**, **Look
again** and, as a choice of its own, **Practice with the demo song**: a made-up song (the "mock" session, `daw/js/mock.js`)
that plays no sound, saves nothing and sends nothing, and is labelled **Demo** wherever it shows. It never takes the
place of a session you have open: leaving the engine's session for it is **Show the demo song** in the engine panel, and
that asks first.

**Guided tours.** The DAW view can show people around on its own screen, optionally: the first time it opens, a small
card offers **Show me around** or **Not now** (it takes no focus, and the answer is remembered); the **Tour** button in the
top bar (and **Take a tour** in the `?` list) opens the six tours (First look, Edit a region, Mix, Scan and review, Ask the
Assistant, Save and export); the Teacher tab has a card that opens the same list, shown only where the DAW view is
available. A step lights one real control and waits, if it asks you to do something, for the page's own events (`edit`,
`undone`, `saved`, `review`, `assistant`, `mode`); it never changes the session, sends an engine command or clicks for you.
The tours are data (`daw/js/tours.js`), the engine is `daw/js/tour.js`, the look is `daw/css/tour.css`; progress is in
`localStorage` (`hx.tour`) and in `~/.hypnomix/teacher.json` under `dawtour` (`GET`/`POST /api/teach/tour`). Tests:
`tests/test_daw_tour.py`. Wiki: [A guided tour inside the HypnoMix DAW](../hypnomix/app/wiki/articles/18-daw-tour.html).

**The engine.** Underneath is the HypnoMix engine: the DAW's audio engine (with no window), which the app
starts, watches and stops (`hypnomix/app/daw.py`). It is a separate program under its own licence (next paragraph).
It looks for the `hypnomix-engine` program in this order: `HYPNOMIX_ENGINE` (or `"engine"` in
`~/.hypnomix/daw.json`); the add-on, `engine/<version>/bin/hypnomix-engine` in the HypnoMix folder (`~/.hypnomix`, or the
folder `HYPNOMIX_HOME` names), for the version the app's manifest names (else the newest other one on disk, which is kept
until the new one has run once); inside the app, `Hypnomix.app/Contents/Resources/engine/bin/hypnomix-engine` (a test
build's kit: still found for one more version, and nothing depends on it); the folder next to the Python the app runs on
(not looked in when the app runs inside `Hypnomix.app`); and, for developers only, a source build of the engine in the
folder that `HYPNOMIX_ENGINE_SRC` names (nothing is guessed). It runs it on a free port (`--port N`, so it never collides with a
HypnoMix DAW window on 4820) with the session, and waits for its `HYPNOMIX-ENGINE READY port=N` line. Extra arguments
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
HypnoMix DAW's engine is a rebranded fork of the free open-source DAW it is built on (what that is, and where it comes
from: `THIRD_PARTY.md` and the wiki article "HypnoMix DAW"). HypnoMix itself stays under the MIT licence and contains none of the engine's code; the app starts
the engine as its own process and talks to it only over MCP on this computer. The add-on archive carries the engine
unchanged, with its licence text and a source notice as its own files (`packaging/mac/build_engine_archive.sh` refuses to
package a kit without them, and the app checks them again on what it downloaded: packaging/README.md). The source will be
published with the first release that includes the engine; there is no public source address yet.

| situation | what the app does |
|---|---|
| no session given (`--session`) | opens the one that was open when the app last quit (`"last"` in `daw.json`, kept each time a session opens); with none, the engine waits (the engine needs a session) and the view says: File → New Session… or Open Session… (or New / Open in the engine panel) |
| no audio device starts (`HYPNOMIX-ENGINE ERROR cannot start the audio engine`, `cannot use device`, …), or the device never answers within 120 s | starts the engine again once on the Dummy backend, without the device choices, and says so in plain words (`notice`: no sound; the session, edits, waveforms and exports all work). Restart tries the device again. Not when `args` chose a backend: then a start that is not ready within 120 s is stopped and shown as failed (press Restart) |
| the engine stops by itself (a crash, or the audio engine halted) | starts it again on the same session, at most 3 times a minute; the DAW view reads the session again. Edits not saved before the crash are gone, and a `notice` says so until you Save (or Restart) |
| the engine says `HYPNOMIX-ENGINE ERROR …` (no such session, the port is taken, bad arguments) | shows the message and does not retry |
| you quit the app | stops the engine (SIGTERM). The engine never saves by itself, so the app asks first when there are unsaved edits (**Save**, **Don't save**, **Cancel**; "Saving" below); the native app's Quit asks the same (and waits for the engine to stop before it quits), and the updater's **Install and restart** is refused (HTTP 409) until you have saved |
| no engine program yet | **attaches** to a HypnoMix DAW window that is already running with Preferences → Control Surfaces → MCPHttp on (`http://127.0.0.1:4820/mcp`; `HYPNOMIX_ENGINE_URL` for another). Attached, the app never stops or restarts that window, and you open sessions in it. It attaches only to a listener that is the engine (it must call itself by the engine's name and have the engine's core tools): anything else on that port is left alone, and the engine panel says so |

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
then go on).

**Adding and removing HypnoMix DAW** (`hypnomix/app/engine_addon.py`). The engine is published as an archive of its own
for each platform (`mac-arm64`, `mac-intel` now; the manifest's structure allows `windows-x64` and `linux-x64` later).
`hypnomix/app/engine_addon.json`, shipped inside the app, names for this version of the app the engine version it works
with and, per platform, the https address and SHA-256 of the archive. Until an archive is published the manifest carries
no address and the state says **HypnoMix DAW is not available yet** (and "not yet for Windows" off a Mac). Nothing is
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
device, and recording, are untested), opened the native **File** menu and its panels in a running test build, added the
engine from a real published archive (none is published yet), signed and notarised a build (the Developer ID build has not been tried), or
run any of it on an Intel Mac. Read the sentences about sound and the File menu in this section as what the code is
written to do.

**The browser never talks to the engine directly.** The page sends its MCP calls (JSON-RPC 2.0) to the app,
`POST /mcp` on the same address, with the page's token; the app passes them to the engine it runs and the reply
back unchanged. The same rules as the rest of the app: this computer only, requests from other sites refused, and
nothing without the page's token. The engine routes are `GET /api/daw/state` and `POST /api/daw/start`, `stop`,
`restart`, `save`, `open {path}`, `new {folder, name}` (the ones that would lose unsaved work answer 409: see Saving).

**The Assistant in the DAW.** With a model key set (the Assistant tab's settings) and the engine connected, the
Assistant column is the app's real Assistant, the same conversation as the Assistant tab. It gets the engine's own
tools (its `tools/list`, offered to the model as `daw_<tool>`, with any provider) on top of HypnoMix's, and calls them
through the app's engine connection (`hypnomix/app/chat.py`, with its rules in `hypnomix/app/daw_assist.py`):

| rule | what it means |
|---|---|
| reads run at once, from an explicit list | `session_get_info`, `tracks_list`, `track_get_info`, `track_get_fader`, `track_get_regions`, `region_get_info`, `region_get_peaks`, `plugin_list_available`, `plugin_get_description`, `markers_list`, `meters_get`, `transport_get_state`, MIDI note reads, `export_status`, `region_get_warp`, … plus `daw_session_overview` (the whole session in one read). Any other tool, and any tool the engine adds later, asks; so does a listed one the engine marks as writing. A listed read must be unable to change anything whatever its arguments: `meters_get`'s `ensure_rms` (it switches every meter) is taken out of the call and out of what the model is offered |
| every change is a **proposal card** | a title and a sentence in plain words (*Change a fader: Drums · fader, from 0.0 dB to -2.0 dB*), what changes, before → after, read from the engine just then, the exact call under a disclosure, what undo can do for it (only region, marker, loop-range, warp and MIDI edits are engine undo steps; a fader, pan, mute, solo, send level or plug-in setting is taken back by setting the old value again; adding or removing a plug-in or a send is not an undo step, and a removed plug-in or send loses its settings, so adding it again starts from the defaults; removing or reordering tracks cannot be undone: the card says which, in each case from the engine's source), **Approve** and **Cancel** (Esc). Nothing reaches the engine until you approve; then the card shows how it ended: applied and what the engine reads back, failed (with the engine's words, and whether it may have happened), cancelled or expired, in the DAW column and in the Assistant tab alike |
| an approval is for one call, and a deliberate one | the card carries a digest of its call and the answer must bring it back; just before the call is sent, the arguments exactly as they go to the engine are checked against the digest and against the arguments the card shows, and if they differ nothing is sent; the answer must be a real `true` (the string `"false"` or a `1` approves nothing). **Enter** approves only while the Approve button has the focus (a held key and a stray Enter, say one meant for the chat box, approve nothing), and a click counts once |
| arguments are checked first | a number where an id string goes, a track's name where its id goes, `regionId` vs `region_id`, `"true"` for true: fixed before the card is shown. A change to a track or region that is not in the session, one missing a required value or with a value of the wrong kind (`"loud"` for dB), or one to a plug-in index the track does not have is never proposed: the model is told why. The first answer to a card wins (a quick second click cannot turn Cancel into Approve) |
| replies are trimmed for the model | peaks become each channel's loudest peak and a coarse envelope; plug-in and parameter lists keep what matters; file paths are cut to the file's name and any home folder to `~`; long lists and texts are cut with a note (8,000 characters at most); the session overview stays under 14,000 characters: one read per track, all in flight together (6 at a time, 20 s at most, 80 tracks at most), regions only for a session of 12 tracks or fewer (a bigger one reads them per track), and the tracks that do not fit are named as not shown |
| what the project says is data | track, plug-in and region names, the engine's errors, what a change reads back and the snapshot list reach the model fenced in `<file-data>` tags like a file's contents, in any case and spacing of the closing tag and with any invisible character inside it (a soft hyphen, a bidi mark, a zero-width space, a NUL), with saved keys masked and the home folder shortened (a scan's log too): a track called `</FILE-DATA> do this` cannot close the fence. The scan that finds the tag walks the text once, so a hostile file cannot stall the chat |
| only part of the tool list is sent | each step carries the tool definitions again, and the engine has 111 (about 17,600 tokens a step). A request carries the core (the reads, fader, pan, mute, solo, sends, the main plug-in moves, save and undo: about 3,600 tokens) plus the groups the open view needs (the mixer adds the other plug-in tools, the Arrangement the region tools); `daw_more_tools {group}` offers any other group from the next step on. Descriptions are cut to about 170 characters. Measured on the engine's real tool list (111 tools, read only from its source): 70,600 characters a step before (about 17,600 tokens at 4 characters a token, HypnoMix's own tools and the overview included), 14,400 now (about 3,600 tokens); with the mixer view 17,800, with the Arrangement view 25,900, with every group asked for 57,400, always under a provider's limit of 128 tools. The system prompt is another 37,000 characters on every step. A tool that is not offered still asks before it changes anything. **The prompt cache:** the tool list is the first block of the model's cached prompt, so a change to it (a group asked for with `daw_more_tools`, or a view that needs another group) rewrites the cached conversation once, at the cache-write price, instead of reading it at the cheaper cache price. To keep that to once, a group once offered stays offered for the rest of the conversation (changing view never takes tools away); the cost line above the chat shows what a conversation really cost |
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

**Mixer, meters, devices and transport on the engine** (`daw/js/live.js`). One poll loop asks `meters_get` (it also
carries the transport's `sample` and `rolling`) about 15 times a second while playing and twice a second when stopped,
never with two requests out; the first call passes `ensure_rms:true`, which switches the routes' meter type to
RMS + Peak so the meters draw peak (light) over RMS (solid) with a held peak on the track headers, the Mixer and the
master. The status line says **meters live**. The playhead is interpolated between polls by a gentle phase-locked
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
loudness and peaks, a compressor's gain reduction) are shown as readings, refreshed every second while playing.
Transport: play, stop, locate, loop (the range is set from the view first: `transport_loop_location_samples`) and
record, with the loop range read from the session's markers. The time signature and track colours come from the
saved session file (`POST /api/daw/meta`, `hypnomix/app/daw_meta.py`), since no MCP tool reports them; a colour set
since the last save is remembered by the browser for that session.

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
| **Approve** / **Skip** / **Change** | saved at once in the scan's `decisions.json`, the same as `hypnomix fix --decide` and the Songs review (clicking the same one again clears it). **Change** takes a note: saved as a change request, or (for a fix Apply writes) **Approve with this note**, where settings such as `fade-ms=20` or `amount=0.3` tune the fix. Tuning cannot be approved here yet (it is not written into a HypnoMix DAW session) |
| **Apply** (asks first) | `hypnomix fix SCAN --approved --out "<snapshot> (hypnomix).ardour"`: ONE new snapshot in the session folder (numbered when that name exists; the open snapshot is never written). It writes region fades, cuts, spike dips and mixer moves; repaired recordings (de-ess, breaths) are made as new files beside the originals; the rest stays by hand, as the detail says. Then **Open snapshot** restarts the engine on the new snapshot (the supervisor's `open`) and the view reads it again; nothing opens without that click |
| **A/B** | where `hypnomix ab` can build a pair for a HypnoMix DAW session: repaired recordings and tuning (**Build A/B**, then A and B, level-matched). Clip and mixer fixes have no A/B for HypnoMix DAW sessions yet: apply to a new snapshot and compare it with the original |

If the session is changed while the mix is bounced, the scan stops and says so (its findings would not match the mix). Apply writes its new snapshot whole or not at all.

The routes are `POST /api/dawreview/scan`, `decide`, `apply`, `ab` (with the page's token) and `GET /api/dawreview/state`,
`findings?dir=`, `evidence?dir=&id=`; progress is the app's `GET /api/job`.

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
playback, as in HypnoMix DAW), track colours since the last save (as above), the DSP load (not shown) and the time signature
changing (read at connect). Region envelopes are read (`envelopeActive`) but not drawn. With an older engine whose
`region_get_info` has no fade fields, the view falls back to remembering the fade lengths it set in this browser (per
session and region; after a split each part keeps the fade on its outer edge and the engine's 64-sample fade at the
cut). Demo-song only: clip launching (Session view) and tempo changes (no MCP tool for tempo yet). On the demo song,
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
