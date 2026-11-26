# CLAUDE.md

Read `AGENTS.md` first: what hypnomix is, the loop (preferences → scan → review → apply → verify → listen →
learn), the rules, the command map and how to change the code. `docs/LESSONS.md` explains where the rules come
from. Claude Code specifics:

- Skills in `skills/` load automatically (`.claude/skills` links there): **first-pass** (preferences, parallel
  scan, review one fix at a time, apply, verify), **mix-engineer**, **mastering-engineer**,
  **tracking-session**, **live-mixing**, **harmony-balance** (learn how the person spaces harmonies from their own
  finished songs, then only correct what falls outside that).
- Subagent definitions in `agents/` (`.claude/agents` links there): **hypnomix-scanner** runs one scan group,
  read-only. Start several in one message to scan in parallel. Scanning is the only thing to hand to
  subagents: the review and every decision stay in the conversation with the person.
- Before the review, `hypnomix ab DIR` builds before / after clips; `hypnomix review DIR --serve` gives the
  person a page to listen and click on (start it with the preview tool or in their terminal, not a blocking shell).
- Use the question tool for approve / skip / change, with your recommendation first, and record each answer
  with `hypnomix fix DIR --decide` as it is given.
- After the fixes, `hypnomix handoff DIR` turns what `fix` could not do into a checklist in the person's DAW's words,
  with markers (a new set with locators, a new REAPER project with markers, or a MIDI file and CSV).
- For a newcomer, point at the app's **Teacher** tab (`hypnomix app`): free courses in their own DAW (Live, REAPER or
  Ardour), the complete course A to Z, a 101 crash course and a tour. It needs no AI, and it is theirs to use, not
  something to drive.
- Say what has been checked where, never more: the Live devices and fix paths were tested in Live 12 and REAPER
  support in REAPER 7.86, and the newest REAPER files (the demo project, a fixed project, masking cuts as ReaEQ bands,
  the handoff markers, the A/B project) were opened and read back in REAPER 7.86. The newest Live sets and the Ardour
  snapshots pass unit tests and structure checks only and have not been opened in their DAWs; none of the newest tools
  has been run on real songs or judged by ear (AGENTS.md has the list).
- `.mcp.json` connects the Ableton MCP (telemetry off) for creating tracks and loading devices. It drives the
  open Live set: the same rules as the Live tools apply (ask first, one driver at a time).
- Ask before taste calls, before any change to a set, before `hypnomix install` (and `device`, `aligndevice`,
  `probe device`, which also write into Live's User Library), and before opening, saving or quitting anything in Live.

- Every change that alters what a person sees or does updates its wiki article in the same commit (AGENTS.md,
  "Keep the wiki current"); pushing to main updates the app's Wiki and the website on its own.
