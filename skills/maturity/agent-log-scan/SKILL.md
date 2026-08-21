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

## Detector anchoring

Substring detectors drown in conversational mentions: a transcript corpus is full of agents *talking about* errors, limits, and permissions. Every detector marker must be anchored **structurally** — to how the harness writes the event into the transcript — not to phrases that also occur in prose:

- Canonical case: the limit-interrupt detector matched limit phrases anywhere and reported 89 hits; anchored structurally (harness injections are `isMeta` user turns whose content string *starts* with the sentinel; conversational text never fires) it reported 40, all true positives.
- Same cure for permission-thrash: a **denial result** is a `tool_result` with `is_error: true` whose text starts with a verbatim harness denial sentinel; a **denial report** is an unquoted active-voice "classifier denied ..." in free text (peer messages, queue-operation records, prose). Documentation about permissions, the cross-session boilerplate that mentions "denied permission" hypothetically, ALLOW decisions, and tool results that merely quote a denial never fire.
- When extending a detector, derive the anchor from observed real nodes (`slice` into confirmed events and read their structure: entry type, flags, block type, text position), add each false-positive class to the adversarial fixture, and re-verify the ground-truth counts. A sentinel nobody has observed is a guess, not a detector.

## Judge: classify every antipattern

Drill into each finding with `slice` until you can put it in exactly one class:

1. **Infrastructure fault**: API errors and overload dead-ends, limit-interrupts with no continuation after. The provider or harness stopped the run, not the agent. The fix is checkpoint/resume habits and retry cadence, never prompt blame.
2. **Agent-native fault**: retry-loops (same tool, same error signature, 3+ consecutive), hot tools with outlier error rates, sessions ending on an unhandled tool error. The agent's routine failed. The fix is routine tuning: a fallback after the second identical failure, a different tool choice, reading the error signature instead of re-running.
3. **User-flow fault**: permission-thrash (repeated denial results, plus relayed denial reports — the finding says how many of each), silence-gaps clustered around approval points. The human-in-the-loop is the bottleneck; each denial *result* names the exact tool call behind it, and only those feed allowlist proposals.

## Ship: what to change

The point is raising the approval/autonomy range from mass data. End with a concrete change list:

- Permission allowlist additions for the exact commands and tools behind permission-thrash — under the conduct rules below.
- Routine tuning for agent-native faults: the retry-loop's error signature states what the routine should do differently.
- Harness config for infrastructure faults: checkpoint cadence, session-resume habits, scheduling work around usage-limit windows.

### Allowlist conduct rules

Denial evidence authorizes narrow proposals, never self-service:

- Propose only operations that are **read-only, high-frequency, and unambiguous**, and only when each proposed rule is backed by an observed denial in the scan (the finding's `file:line` is the citation).
- Never propose allowlisting writes, deletes, installs, network sends, or anything whose safety depends on its arguments. If an operation is ambiguous, it stays behind the prompt.
- Settings and permission-config changes are always **proposed to the human, never applied by the agent**. Present the exact `permissions.allow` rules (or hand off to the fewer-permission-prompts routine) and stop; observed sessions show agents retrying config self-edits through different write mechanisms after a denial — up to four attempts — and every such attempt is itself permission-thrash.

## Workflow efficiency ledger

`scripts/agentlog.py ledger <workflows-root-or-project-dir>...` aggregates subagent workflow runs (`wf_*/` dirs holding `journal.jsonl` + `agent-<id>.jsonl`) into a per-run/per-agent table: agents started/completed, tool calls, output tokens, input+cache tokens, context tokens (each agent's final context footprint — the same figure the workflow runner reports as per-agent tokens), wall and per-agent durations, and agent labels. Deterministic, streaming, and privacy-default like the rest of the tool: labels and numbers only, never prompt or message text. `--outcomes <json>` joins a run-id -> `{confirmed, fixed, tests_added, mutants_killed, note}` map and adds a tokens-per-finding column; `--json` is the machine form.

The routine:

- Run the ledger **before starting a new maintenance target** so the scale decision is priced, not guessed: what did the last comparable run cost in agents, tokens, and wall time?
- Keep the outcomes file current (one entry per finished run) and **compare tokens-per-finding across runs**: a 14-agent sweep that lands 49 confirmed findings at ~22k context tokens each beats a 6-agent run landing 2 findings at ~240k each; the delta is the argument for changing fleet size, wave structure, or target choice.
- Feed the numbers into scale decisions explicitly — pick agent counts and phase splits from the cheapest tokens-per-finding shapes in the ledger, and say so in the plan. Fleet size is a cost knob with measured settings, not a vibe.

Finish with a summary: sessions scanned, antipatterns by class, top error clusters, and the change list, with zero raw log lines having entered context.
