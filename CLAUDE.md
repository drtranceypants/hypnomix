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
- `.mcp.json` connects the Ableton MCP (telemetry off) for creating tracks and loading devices. It drives the
  open Live set: the same rules as the Live tools apply (ask first, one driver at a time).
- Ask before taste calls, before any change to a set, before `hypnomix install`, and before opening, saving or
  quitting anything in Live.
