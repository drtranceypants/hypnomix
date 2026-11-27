---
title: Setting Up, and Choosing an AI
subtitle: Install the app on a Mac or Windows PC, then pick how you work: on your own, with an AI key, with a model on your own computer, or with a desktop AI app
wiki_id: setup-ai
teaser: The installers, the guided setup, and the four ways to work (just the app, an AI key such as Gemini's free tier, a free model on your own computer, or Claude Code), with costs, pros and cons, and step-by-step setup for each.
---

# Setting up

There is one app and one installer for everyone. It carries every HypnoMix tool, for Live, REAPER, HypnoMix DAW or any DAW from
exported tracks. **HypnoMix DAW** is HypnoMix's own DAW. It is an **add-on**, not a second download: you choose it in Setup (Your DAW) and press **Add
HypnoMix DAW**, and only then is anything fetched (expected to be about 100 MB, once, from the project's release page, checked against a
SHA-256 fingerprint before it is used; it runs only while the DAW view is open, and **Setup → Extras** removes it). It is
**not available yet**: no archive of it is published, so today Setup says so and remembers your choice, and nothing is
downloaded. Its engine is a separate program under the GNU General Public License (version 2 or later), a rebranded fork
of the free open-source DAW it is built on (the wiki article "HypnoMix DAW" says what that is); HypnoMix itself stays MIT and contains none of its code, and the source will be published with the first
release that includes the engine. What has been tried so far: it runs against the real engine on a silent test backend
only (no sound card, no recording, no native File menu, no signed or Intel build, no download from a real release).

There are two ways to install the app. The **installer** is for most people: download it, open it, done. It
carries its own Python and ffmpeg, and the first time the app opens a short **guided setup** asks how you want to
work. The **source install** (the Getting Started guide and the README) is for people who use a terminal or want to work
on HypnoMix itself. The installed app gets every optional extra too (the setup's **Extras** step), and the Claude
Code skills (the **A desktop AI app** option).

## Install the app

1. Go to **hypnomix.bradfieldenterprises.org/download**, pick your computer (Mac with Apple silicon, Mac with an
   Intel chip, or Windows 10/11), tick the box to agree to the terms, and download.
2. **Mac**: open the `.dmg` and drag **HypnoMix** onto **Applications**. **Windows**: run the setup `.exe`. It
   installs for you only and doesn't need administrator rights.
3. Open it. The installers are not signed by Apple or Microsoft yet, so the first time your computer says it can't
   check who made it. The download page shows how to open it anyway, step by step. In short:
   - **macOS 15 and later**: click **Done**, then **System Settings → Privacy & Security → Open Anyway**.
   - **macOS 12–14**: right-click the app, choose **Open**, then **Open**.
   - **Windows**: on "Windows protected your PC", click **More info → Run anyway**.
4. The guided setup opens. It takes about two minutes, and you can run it again any time with the **Setup**
   button at the top of the app.

Not sure which Mac you have? Apple menu → **About This Mac**: "Chip: Apple M…" is Apple silicon, "Processor:
Intel" is Intel.

> The download page also links to the public virus-scan reports for every installer, their SHA-256 checksums,
> and GitHub's record of the build. You can check a download is exactly what the public source code built.

## Updating

The installed app tells you when a new version is out: a banner at the top says what's new, with **Update
now**. The app downloads the new installer, checks its SHA-256 fingerprint against the one published with the
release (a mismatch is deleted, never installed), and with **Install and restart** it closes, puts the new
version in place and opens again. Your songs, settings and keys stay as they are.

- It checks GitHub once a day at most. Click the version number at the top right to check now, or to switch
  the daily check off.
- **Later** hides the banner until the next version.
- Installed from the source? The banner shows the command instead: `git pull && uv pip install -e .`

**What the update check does and doesn't protect against.** The app only accepts a release whose name is a plain
version number, and only downloads from the project's own release page on github.com (a redirect must stay on
GitHub's own servers, and anything else is refused). The installer's fingerprint must match the one published with
the release; the app checks it again just before installing, and on a Mac the updater checks the new app is intact
(`codesign --verify`) and says it is the version the release claimed, before it replaces the old one, and leaves the old one
in place if not. The files must sit in that release's own download folder, so a release can't point at an older version's
installer. If you use a proxy, the update check uses your computer's proxy settings like any other app. That protects you
from a damaged download, and from a file on GitHub's download servers being swapped for another. It does **not**
protect you from someone who controls the GitHub release itself: they could publish a bad installer and a matching
fingerprint, because the installers aren't yet signed with a publisher key the app can check (the Mac check shows
the app is whole, not who made it). If that matters to you, update from the source: `git pull`, after reading the
changes.

HypnoMix's own settings and state files in `~/.hypnomix` (updates, setup, Disk care) can be read by your account alone
on a Mac. On Windows that folder sits in your own user folder, which Windows keeps to your account and the computer's administrators; HypnoMix adds no lock of its own there.

## The guided setup

| step | what it asks |
|---|---|
| How you work | just the app, an AI key, a model on your computer, or a desktop AI app (compared below) |
| Your DAW | Ableton Live, REAPER, HypnoMix DAW or something else (the Wiki puts your DAW's pages first; choosing HypnoMix DAW shows what it is and an **Add HypnoMix DAW** button, or says it is not available yet), and **teacher mode**: no thanks, the tour of HypnoMix in your DAW (for engineers), the 101 crash course, or the complete course, A to Z (for people new to audio). The wiki's Teacher mode page has all three |
| Connect | for an AI key: which company, your key, a test. For a local model: Ollama or LM Studio, and a test. For a desktop app: a `hypnomix` command and an agent folder |
| your DAW's step | Live: copies the AbletonOSC remote script into Live's User Library, on your click (and offers to update an older copy for teacher mode). REAPER: starts the bridge. HypnoMix DAW: the **Add HypnoMix DAW** button, when it is available. Another DAW: nothing to install |
| Extras | the optional extras, each on a click, and a card for HypnoMix DAW with its state, an add button when an archive is published, and Remove |
| Done | where to start (the Teacher tab, with teacher mode on) |

## Choosing how to work with AI

HypnoMix doesn't need an AI. Every tool works from the app's buttons. An AI adds a helper that explains each
finding in plain words, answers your questions, runs the scans and checks for you, and works through a whole song
with you. **Whichever way you choose, nothing that changes a set happens without your OK**, and HypnoMix never
overwrites your original.

| | Just the app | AI key in the Assistant | Model on your computer | Desktop AI app |
|---|---|---|---|---|
| Cost | free | Gemini free tier $0; otherwise pay per use (table below) | free | Claude Pro $20/month; Max $100 or $200 |
| Account needed | none | with the AI company | none | Claude (or your agent's) |
| What leaves your computer | nothing | text reports go to the AI company; audio only if you allow a listen | nothing | text reports go to the AI company |
| Computer needed | any | any | 16 GB of memory for a good model | any |
| Best for | learning the tools, full control | most people: help inside the app | privacy, no budget | whole songs, batches, the most capable help |

### What an AI key costs per song

Rough estimates for **one song from scan to approved fixes**, about 40 assistant steps: around 1.2 million input
tokens (most of it the same context sent again, which Claude bills at a discount) and 20 thousand output tokens.
A short question costs a fraction of this. A long session with many re-scans costs more. List prices, checked
2026-11-26:

| model | price per million tokens (input / output) | one song, roughly |
|---|---|---|
| Google Gemini Flash, free tier | free, with daily limits | $0 |
| Google Gemini Flash, paid tier | $0.75 / $3.75 (introductory; $1.50 / $7.50 from 2027) | about $0.97 (about $1.95 from 2027) |
| Claude Haiku 5.5 | $0.10 / $0.50 | about $0.04 |
| Claude Sonnet 5.5 | $2 / $10 | about $0.79 |
| Claude Opus 5.5 | $4 / $20 | about $1.58 |
| OpenRouter, OpenAI and others | see each model's page | varies |

Claude Haiku 5.5 costs $0.50 / $2.50 instead for any request whose prompt is longer than 100,000 tokens, which a long
session reaches, so a very long song on Haiku costs about $0.22 rather than $0.04.

The Assistant tab counts the tokens of every conversation and shows the cost as you go: exactly for Claude, as an
estimate for Gemini (at the paid-tier price above; the free tier costs nothing), and for other companies as tokens only
(their own page has the price). Every company lets you set a monthly spending limit. Set one.

**Keeping a long conversation cheap.** Every step re-reads the whole conversation, so the Assistant clears the full
text of old results (a page of findings, a report, a listen) once the conversation has grown long, leaving a one-line
note of what each was and how to fetch it again; your files are untouched. It also stops and asks "keep going?" when
a single message has used more than 400,000 input tokens (change the number in the Assistant's settings), and stops
if it calls the same tool with the same arguments three times in a row.

## Just the app

Nothing to set up. On the **Songs** tab choose a song's Live set (or a folder of stems), click **Scan**, and go
through the review: each finding has a before and after to hear, and **Approve**, **Skip** or **Change**. Then
**Apply** writes only what you approved into a new set next to the original. The **Wiki** tab has a short lesson
with a video for each step.

**Pros**: free, private, every tool. **Cons**: you read the reports and make every call on your own.

## An AI key in the Assistant

The **Assistant** tab is a chat inside the app. You bring a key from an AI company; the key is saved on your
computer only (`~/.hypnomix/ai.json`) and is sent only to that company. On a Mac only your account can read that file.
On Windows the file sits in your own user folder, which Windows keeps to your account and the computer's administrators; HypnoMix adds no lock of its own there.

**Pros**: help right inside the app, pay only for what you use (or nothing on Gemini's free tier), and Gemini can
also be the *Listener*, hearing a bounce for notes by ear. **Cons**: an account and a key, the text reports go to that company,
and costs add up with the bigger models on long sessions.

### Google Gemini (recommended to start: free tier)

1. Open **aistudio.google.com/apikey** (Google AI Studio) and sign in with any Google account.
2. Click **Create API key**. If it asks for a project, let it create one.
3. Copy the key. It starts with `AIza`.
4. In HypnoMix: **Setup → An AI key → Google Gemini**, paste the key, keep the model `gemini-flash-latest`, and
   click **Save and test**. It should say how many models it can reach.
5. Leave **Also make it the Listener** ticked if you'd like notes by ear. The Assistant asks before each listen
   and sends only a reduced mono copy (about 1 to 5 cents a listen on the paid tier). Before each one it shows the
   length, the model, the tokens (the review that goes along as text included) and an estimated cost; a song over 12
   minutes asks whether to send all of it or the first 12 minutes; notes already heard for the same song, model and
   question come back free. `hypnomix critique "Song.wav" --estimate` only prints what would be sent and roughly what it costs; without `--estimate`, `critique` prints the same and asks y/N (anywhere that is not a terminal it refuses unless `--yes`, which is only for when you have said yes to exactly what `--estimate` shows), and a song over 12 minutes is warned about (`--minutes N` sends only the first N minutes). Which Gemini model hears best, and how to give the Listener a key of its own: the wiki
   article "The Assistant and the Listener".

The free tier needs no card and has daily limits. If you hit them, the Assistant says "too many requests": wait,
or set up billing in AI Studio for the paid tier. On the **free tier Google may use what you send to improve its
products**; the paid tier doesn't. Don't use the free tier for songs you need kept private before release.

### Claude (Anthropic)

1. Open **console.anthropic.com**, sign up or sign in.
2. Under **Billing**, add credit (prepaid). Set a monthly limit there too.
3. Under **Settings → API keys**, click **Create Key** and copy it (it starts with `sk-ant-`).
4. In HypnoMix: **Setup → An AI key → Claude**, paste it, choose a model and **Save and test**.

Which model: **Sonnet 5.5** (`claude-sonnet-5-5`) is the everyday choice, and the one the Assistant uses until you
pick another (the picker marks it *default*; a model you saved stays). **Opus 5.5** thinks harder and costs about
twice as much. **Haiku 5.5** is very cheap and fine for quick questions, but makes more mistakes on long jobs. Every
model your key can use stays selectable: **List models**, or type its name.

A Claude Pro or Max subscription doesn't include API keys. To use your subscription, choose **a desktop AI app**
instead (below).

### OpenRouter and OpenAI

**OpenRouter** (openrouter.ai): one key reaches models from many companies. Add credit, create a key under
**Keys** (it starts with `sk-or-`), paste it. It can also do Listening. **OpenAI** (platform.openai.com): add
credit under Billing, create a key under API keys. Groq, Mistral and any other OpenAI-compatible service are in
the Assistant tab's settings.

## A model on your own computer

An open-source model runs on your computer, and the Assistant talks to it. It's free, private and works offline.
It's slower, and small models make more mistakes when they run tools. The Assistant still asks before anything
changes a set.

| your computer's memory | try |
|---|---|
| 8 GB | `qwen3:8b` (about 5 GB download); lighter, less reliable on long jobs: one request at a time |
| 16 GB or more | `gpt-oss:20b` (about 14 GB download), an open-weight model built for tool use |

### Ollama

1. Download Ollama from **ollama.com/download** and open it. It runs in the menu bar (Mac) or system tray
   (Windows).
2. In Terminal (Mac) or PowerShell (Windows), get a model that can run tools:

```
ollama pull gpt-oss:20b
```

3. Give it room to think: in Ollama's **Settings**, drag the context length to **64k**. The Assistant reads long
   reports, and Ollama's default is too short.
4. In HypnoMix: **Setup → A model on this computer → Ollama**, model `gpt-oss:20b` (or `qwen3:8b`), **Test the
   connection**.

To drive HypnoMix with a free open-source *agent* instead of the Assistant (OpenCode, in a terminal), see the
wiki's "Run your own AI, free and offline".

### LM Studio

1. Download LM Studio from **lmstudio.ai** and open it.
2. Search for a model with tool use (gpt-oss 20B, or Qwen3 8B with 8 GB of memory), download it and load it
   with a context length of 64k.
3. Open the **Developer** tab and switch on **Start server** (port 1234).
4. In HypnoMix: **Setup → A model on this computer → LM Studio**, **Test the connection**. Type the model's name
   as LM Studio shows it; left empty, HypnoMix uses the first model LM Studio lists and says which.

## A desktop AI app

An AI agent such as **Claude Code** runs HypnoMix commands, reads the reports and works through a whole song with
you, in a chat beside the app. This is the strongest option for long, many-step work (a whole song, a batch, your
own requests), at a flat monthly price. HypnoMix is built and tested with Claude Code. Codex, Cursor and other
agents that read `AGENTS.md` work too.

**Pros**: the most capable help, a flat price, comes with the HypnoMix skills for Claude Code, works with every optional extra. **Cons**: a subscription with
usage limits; the work happens in the agent's chat, not inside the app.

### Set it up

1. Get **Claude** from **claude.com/download**. The desktop app includes Claude Code in its **Code** tab. Claude
   Code needs a **Pro** plan ($20/month) or **Max** ($100 or $200/month for heavy use). Prefer the terminal?
   Install Claude Code from claude.com/product/claude-code.
2. In HypnoMix: **Setup → A desktop AI app → Make the command and folder**. This makes:
   - a `hypnomix` command that runs the app's own copy (Mac: `~/.local/bin/hypnomix`; Windows: in your user's
     WindowsApps folder, which is already on your PATH). A command that is already there and was not made by
     this setup (pipx and `pip --user` leave one) is never replaced: the setup says so and leaves it as it is
   - a folder `Documents/Hypnomix/AI agent` with `CLAUDE.md`, `AGENTS.md` and `GUIDE.md`: the instructions
     the agent reads first
   - the repository's **Claude Code skills** in that folder's `.claude/skills` (first-pass, mix-engineer,
     mastering-engineer, live-mixing, harmony-balance, tracking-session) and the scanner subagent in
     `.claude/agents`. Claude Code finds them on its own. For a new song, ask for a *first pass*: it scans with
     parallel subagents, then walks you through the fixes one at a time. Clicking the button again updates them
     to the app's version.
3. Mac only, once: if the setup says `hypnomix` isn't on your PATH yet, run the line it shows in Terminal, then
   open a new Terminal window.

### Use it

- **Claude desktop app**: open the **Code** tab, choose the **AI agent** folder, and say: *"Read CLAUDE.md, run
  `hypnomix doctor`, then scan my song"*, and drag the song's `.als` file in.
- **Terminal**: `cd` into the AI agent folder and run `claude`.
- **Other agents**: open the AI agent folder in them.

Keep the HypnoMix app open alongside: the review page's A/B players are the quickest way to hear what the agent
proposes. The optional extras are on the setup's **Extras** step (below).

## Optional extras

The installer leaves out three extras: two are GPL-3.0 (HypnoMix itself stays MIT), and one is about a gigabyte.
The setup's **Extras** step (after your DAW's step) installs any of them on a click:

| Extra | Adds | Licence | Size |
|---|---|---|---|
| Reference matching | `reference`: what it would take to sound like a reference song | GPL-3.0 (matchering) | about 150 MB |
| Your own plug-ins | `plugrender`, `ab --plugins`: render through your real VST3 / AU chains | GPL-3.0 (pedalboard) | about 10 MB |
| Stem separation and audio to MIDI | `separate`, `midi` | MIT, with PyTorch (BSD) | about 1 GB, plus a 320 MB model the first time stem separation runs |

They download from PyPI into `~/.hypnomix/extras` (on Windows, `C:\Users\<you>\.hypnomix\extras`), outside
the app. An update to the app keeps them, and deleting that folder removes them. Libraries the app already
has stay at the app's own versions: if an extra needs a different version, it doesn't install, and the step shows
pip's message. Stem separation may not install on an Intel Mac, because PyTorch no longer builds for them. The
Assistant and the Listener are already included. In a source install the same buttons install into that Python.

## Connecting Ableton Live

The setup's **Ableton Live** step copies the AbletonOSC remote script into Live's User Library (a different copy
already there is backed up first). Then **restart Live** and choose **Settings → Link, Tempo & MIDI → Control
Surface: AbletonOSC**. Scanning set files works without it; reading and controlling the open set needs it.
REAPER needs nothing installed: see the guide "HypnoMix in REAPER". HypnoMix DAW sessions are read without it too; HypnoMix DAW itself is the add-on described at the top of this guide.

## When something doesn't work

| what you see | what to do |
|---|---|
| "refused the key" | the key was copied wrong or deleted: make a new one and paste it again |
| "too many requests (or no credit left)" | on a free tier, wait or add billing; on a paid account, add credit |
| "doesn't know that model name" | in the Assistant tab's settings, click **List models** and pick one |
| "Can't reach Ollama" | open the Ollama app (or `ollama serve`) and try again |
| `hypnomix: command not found` (Mac) | run the PATH line from the setup, then open a new Terminal window |
| the app doesn't open (Mac) | System Settings → Privacy & Security → Open Anyway (see Install the app) |
| Windows: no "Run anyway" button | Smart App Control blocks unsigned installers: use the source install, or wait for a signed version |

## Privacy, in one place

- The app runs on your computer and talks only to your own computer (`127.0.0.1`).
- Your audio never leaves the computer unless you turn on Listening and click **Send it** for a listen.
- With an AI key or a desktop AI app, the text reports and your messages go to that AI company, under its terms.
- With a local model, nothing leaves your computer.
- Your keys are stored in `~/.hypnomix/ai.json`, readable only by you. Delete a key from the Assistant tab's
  settings, or delete that file.
- HypnoMix has no server of its own: no usage data, no analytics, no automatic crash reports. When it hits a bug it
  saves a crash record in `~/.hypnomix/crashes` (the newest 20; nothing in it is sent), and **Report a problem** in
  the app (or `hypnomix report`) writes a report you read first, with paths, names and keys hidden as far as HypnoMix can tell. You copy it, save
  it, or open the project's public issue page and paste it yourself. Nothing is posted for you.
