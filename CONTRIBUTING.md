# Contributing: bug reports, ideas, and building with your AI agent

HypnoMix gets better when musicians who use it send back what broke, what was confusing and what they wish it
did. You don't need to be a programmer. If you use an AI coding agent (Claude Code, Codex, Cursor, Aider,
OpenCode or another), it can do the programming with you while you test on your own songs.

## Report a bug

Open a [bug report](https://github.com/drtranceypants/hypnomix/issues/new?template=bug_report.yml) on GitHub.
The form asks for:

- **What you did:** the command or the button you clicked, and on what (a Live set, a REAPER project, a folder
  of stems).
- **What happened, and what you expected.**
- **Your setup:** Mac or Windows, the app version from the download page (or `git rev-parse --short HEAD` if you
  run from source), your DAW and its version.
- **`hypnomix doctor` output.** It checks your setup and changes nothing.
- **The error, if there was one:** the end of the Activity log in the app, or the terminal output.

Never attach audio or a whole set. If a finding is wrong, paste its lines from `REVIEW.md` instead. Remove
anything personal first, such as your name in file paths.

No GitHub account? Use the [feedback form](https://hypnomix.bradfieldenterprises.org/feedback/) on the website.
Every message is read.

## Suggest a feature

Open a [feature idea](https://github.com/drtranceypants/hypnomix/issues/new?template=feature_request.yml). The
most useful ideas describe a chore: "every song, I spend twenty minutes doing X by hand". Say what you'd want to
decide yourself and what could be automatic. `docs/ROADMAP.md` lists what's already planned.

## Build it with your AI agent

The repo is set up for AI agents. `AGENTS.md` tells any agent what HypnoMix is, the rules that protect a
person's music, and how to change the code. `CLAUDE.md` adds the Claude Code details. Your agent reads them; you
bring the songs, the ears and the judgement.

1. **Fork and clone.** Fork the repo on GitHub, then `git clone` your fork and open your agent in that folder.
2. **Set it up.** Ask your agent to follow the setup in `AGENTS.md`: `uv venv && uv pip install -e .`, then
   `hypnomix doctor`.
3. **Pick an issue or bring your own.** Look for issues labelled
   [`good first issue`](https://github.com/drtranceypants/hypnomix/labels/good%20first%20issue) or
   [`help wanted`](https://github.com/drtranceypants/hypnomix/labels/help%20wanted), or describe the bug or chore
   in your own words. Comment on the issue so nobody duplicates the work.
4. **Test first.** Ask your agent to write a test that shows the bug or the missing feature
   (`python -m unittest discover -s tests` runs them all), then make it pass.
5. **Try it on your own music, in report mode.** Run it on a *copy* of a real song and listen. Compare the
   numbers before and after. This is the part only you can do: the agent measures, you hear.
6. **Open a pull request.** The [template](.github/PULL_REQUEST_TEMPLATE.md) asks what changed, how you tested it,
   on which DAW, and which AI agent helped.

Small pull requests are easiest to review: one fix or one feature each.

### What makes a change fit

Your agent will find these in `AGENTS.md`, but they're worth knowing:

- **The person decides.** Tools find and propose. They apply only what was approved, and into new files. Never
  change someone's original set or recordings.
- **Options, not fixed rules.** Every tool offers choices and fine controls with a sensible default; it never
  forces one way of doing it.
- **Keep the human feel.** Gentle, optional pitch and timing edits; nothing that quantises a performance flat.
- **No audio in the repo.** Tests build synthetic audio and sets in a temp folder.
- **Work on macOS and Windows, which the tests run on.** Do not break Linux knowingly, but the project does not test there (patches from people who use Linux are welcome). Name the encoding of every text file and pipe (`encoding="utf-8"`; a test walks the
  source and fails on a bare `open`, `read_text`, `write_text` or `text=True`), and ask the system where a folder is
  (`hypnomix.install.user_library()`, not a hard-coded Mac folder).
- **No paid product names** in code, docs, tests or screenshots, and no personal paths or details.
- **Keep the wiki current.** The wiki in the app and on the website is built from the Markdown in this repo:
  `README.md`, `AGENTS.md`, this file, `docs/*.md` and `docs/guides/`. A change people can see updates its
  article in the same pull request. There are **three copies** of the wiki and you edit none of them by hand: the
  app's Wiki tab, the website's `/wiki/` page and this repository's GitHub wiki are all built from the same files
  (`hypnomix/app/wiki.py`). When a change to those files lands on `main`, the website rebuilds itself and
  `.github/workflows/wiki.yml` rebuilds the GitHub wiki (`python -m hypnomix.app.wiki_github --out DIR` shows you its
  pages before you push), so a fix to an article reaches all three. Edit the sources, never the GitHub wiki's pages: the
  next build replaces every one of them.
- **Say what's untested.** If you couldn't check something in a real DAW, say so in the pull request and in
  the docs.

### Testing without touching your own setup

HypnoMix keeps your preferences and your scans in your own folders, and a few commands write into Ableton's User
Library. To try a change safely, run it in an instance that cannot reach any of that:

1. **Point four folders at scratch space.** Make an empty folder and set `HOME`, `HYPNOMIX_HOME`,
   `HYPNOMIX_APP_HOME` and `HYPNOMIX_USER_HOME` to folders inside it, in the same terminal, before you run anything:

   ```bash
   S=/tmp/hypnomix-test && mkdir -p $S/fakehome $S/home $S/work
   export HOME=$S/fakehome HYPNOMIX_HOME=$S/home HYPNOMIX_APP_HOME=$S/work HYPNOMIX_USER_HOME=$S/fakehome
   ```

2. **A test copy of the app:** `hypnomix app --port 8795 --no-open --home $S/work`, then open
   `http://127.0.0.1:8795`. Pick a port that is not 8791 (your own app's). If you also test the probes, give the
   test copy its own probe port with `HYPNOMIX_PROBE_PORT` (the default is 8792).
3. **Never run these bare:** `hypnomix install`, `hypnomix device`, `hypnomix aligndevice` and
   `hypnomix probe device`. They write into the Ableton User Library. Use `--out FOLDER` (the device commands) or
   `--dry-run` (`install`) so they write somewhere else, or show what they would do.
4. **Do not start Live or REAPER from a test run** unless the test is about them. A test that needs them says so.
5. **The unit tests need none of this:** `python -m unittest discover -s tests` builds synthetic audio and sets in a
   temp folder, and moves itself onto temporary folders of its own when the four variables above are not set
   (`tests/_isolate.py`; it removes them at the end). A tool or extra the tests use that is not installed (the
   `assistant` extra, Node.js, Rubber Band, ffmpeg) is named in the first lines of the run, because the tests that
   need it are skipped, and a skip still says OK. With `CI=true` a missing extra or Node.js fails the run instead.
   The page scripts are all parsed by one helper (`tests/_jscheck.py`): with Node.js, else with the JavaScript engine
   macOS ships (osascript), else the test is skipped and says that nothing could parse them. The tests that RUN a page
   or device script (against stand-ins for the page or for Live) start it through the same file, `_jscheck.runner()`:
   Node.js (with `print` defined for it), else macOS's JavaScriptCore, else a skip that says which is missing.
   The Assistant's Claude library needs Python 3.10 or newer, so on 3.9 the tests use an empty stand-in module of that name
   (`tests/_isolate.py`); none of them calls the real library.
   Run only the files for your area while you work, as `python -m unittest tests.test_NAME` (several names are fine)
   or `python -m unittest discover -s tests -t . -p 'test_NAME.py'`. Leave out the `-t .` and the run is NOT isolated: it
   writes into your real `~/.hypnomix` and `~/Documents/Hypnomix`.

### Making it easier to use

Clearer wording, better error messages, a missing step in a guide, a confusing button: these are some of the
most valuable changes, and a good first one to make with an agent. If something took you a while to figure
out, it'll take the next person a while too.

## Licence

HypnoMix is MIT licensed. By opening a pull request you agree your contribution is released under the same
licence.
