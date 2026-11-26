# Contributing: bug reports, ideas, and building with your AI agent

hypnomix gets better when musicians who use it send back what broke, what was confusing and what they wish it
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

The repo is set up for AI agents. `AGENTS.md` tells any agent what hypnomix is, the rules that protect a
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
- **No paid product names** in code, docs, tests or screenshots, and no personal paths or details.
- **Keep the wiki current.** The wiki in the app and on the website is built from the Markdown in this repo:
  `README.md`, `AGENTS.md`, this file, `docs/*.md` and `docs/guides/`. A change people can see updates its
  article in the same pull request.
- **Say what's untested.** If you couldn't check something in a real DAW, say so in the pull request and in
  the docs.

### Making it easier to use

Clearer wording, better error messages, a missing step in a guide, a confusing button: these are some of the
most valuable changes, and a good first one to make with an agent. If something took you a while to figure
out, it'll take the next person a while too.

## Licence

hypnomix is MIT licensed. By opening a pull request you agree your contribution is released under the same
licence.
