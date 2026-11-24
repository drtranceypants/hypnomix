# CLAUDE.md

Read `AGENTS.md`: it covers what hypnomix is, setup, the command map, the safety rules and how to change the
code. Claude Code specifics:

- Skills in `skills/` load automatically (`.claude/skills` links there): **first-pass** (scan a song with
  parallel subagents, review one fix at a time), **mix-engineer**, **mastering-engineer**, **tracking-session**,
  **live-mixing**.
- Subagent definitions in `agents/` (`.claude/agents` links there): **hypnomix-scanner** runs one scan group,
  read-only. Start several in one message to scan in parallel.
- `.mcp.json` connects the Ableton MCP (telemetry off) for creating tracks and loading devices.
- Ask before taste calls, before any change to a set, and before quitting or saving anything in Live.
