---
name: agent-log-scan
description: Scan Claude Code agent transcripts (session-history JSONL) for antipatterns and turn them into config and routine changes. Use when the user asks to scan agent logs or transcripts, analyze session history, "why do my agents keep failing", "what happened across my sessions", wants retry loops / permission thrash / API dead-ends / usage-limit interruptions found, or wants to learn from agent history to raise autonomy and cut permission prompts.
---

Mine an agent-transcript corpus for antipatterns with the bundled scanner and read only its aggregate. A corpus is hundreds of megabytes; the lesson it carries fits on a page. The agent never reads raw logs.

## Ground rules

- Run `scripts/agentlog.py scan <corpus>` (Python 3 stdlib, streaming, deterministic) on the corpus: `~/.claude/projects` for everything, or one project folder. Read ONLY the aggregate it prints. Never open or `cat` a `.jsonl`: one line can be a 5 MB base64 image and one file can be 100 MB+.
- Privacy default: the scanner emits signatures, counts, tool names, and `file:line @offset` only. `--show-text` (snippets <=160 chars) is opt-in, and only when the human asked for text.
- Drill down by coordinates, not by reading: `slice <file> <line> --around K` prints K one-line node summaries either side of a finding; `bisect <file>` reports the top cohesion boundaries of one session with byte offsets, so you jump O(1) into the middle of a huge session and divide and conquer instead of reading forward.
- Exit code 2 means the detectors (retry-loop, permission-thrash, api-dead-end, limit-interrupt) found antipatterns, so CI and scripts can gate on it. Exit 0 is a clean corpus; exit 1 is bad usage/paths.

## Judge: classify every antipattern

Drill into each finding with `slice` until you can put it in exactly one class:

1. **Infrastructure fault**: API errors and overload dead-ends, limit-interrupts with no continuation after. The provider or harness stopped the run, not the agent. The fix is checkpoint/resume habits and retry cadence, never prompt blame.
2. **Agent-native fault**: retry-loops (same tool, same error signature, 3+ consecutive), hot tools with outlier error rates, sessions ending on an unhandled tool error. The agent's routine failed. The fix is routine tuning: a fallback after the second identical failure, a different tool choice, reading the error signature instead of re-running.
3. **User-flow fault**: permission-thrash (repeated classifier/permission denials), silence-gaps clustered around approval points. The human-in-the-loop is the bottleneck, and each denial names the exact tool call to allowlist.

## Ship: what to change

The point is raising the approval/autonomy range from mass data. End with a concrete change list:

- Permission allowlist additions for the exact commands and tools behind permission-thrash (settings.json `permissions.allow`, or the fewer-permission-prompts routine).
- Routine tuning for agent-native faults: the retry-loop's error signature states what the routine should do differently.
- Harness config for infrastructure faults: checkpoint cadence, session-resume habits, scheduling work around usage-limit windows.

Finish with a summary: sessions scanned, antipatterns by class, top error clusters, and the change list, with zero raw log lines having entered context.
