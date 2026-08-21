# agent-log-scan

## What it does

Streams an entire Claude Code transcript corpus (JSONL session history,
hundreds of megabytes) through a deterministic stdlib-Python scanner and
reports antipatterns as an aggregate: retry-loops (same tool failing 3+
times in a row on the same error), permission-thrash (repeated denials,
split into denial results and relayed denial reports), API dead-ends
(sessions that end on a provider error), usage-limit interruptions,
silence-gaps, cross-session error clusters, and per-tool error rates.
Every finding carries `file:line @byte-offset`, so `slice` jumps straight
to the neighborhood and `bisect` finds a long session's topic boundaries
by signature distance. The agent reads kilobytes of aggregate about
megabytes of logs; message text stays out of context unless `--show-text`
is passed.

## When to reach for it

- Agents keep failing and nobody knows whether the harness, the routine,
  or the permission loop is at fault.
- You want to raise an agent's autonomy range with evidence: which exact
  tool calls get denied, which errors repeat, where sessions die.
- CI should gate on transcript health (`scan` exits 2 when detectors fire).

## Common questions

**Why never read the raw logs?** A single transcript line can be a 5 MB
base64 image; a file can top 100 MB. Reading raw logs burns the context
window on noise. The scanner's aggregate plus targeted `slice` calls carry
the same signal at a fraction of the tokens.

**How do detectors avoid counting talk about failures?** Every marker is
anchored structurally — to how the harness writes the event — not to
phrases that also occur in prose. Usage-limit hits fire only on
harness-injected `isMeta` turns whose text starts with the sentinel
(anchoring took one real corpus from 89 hits to 40, all true positives);
permission hits fire only on `is_error` tool results starting with a
verbatim denial sentinel, or on unquoted first-person denial reports in
free text. Documentation about permissions, cross-session boilerplate,
ALLOW decisions, and tool output quoting a denial never count.

**What do the three fault classes mean?** Infrastructure faults (API
errors, limit cuts) need checkpoint/resume habits; agent-native faults
(retry-loops, unhandled tool errors) need routine tuning; user-flow faults
(permission-thrash) need allowlist and harness-config changes. The routine
ends with a change list, not a chart.

**Does the scan let an agent grant itself permissions?** No. Allowlist
proposals cover only read-only, high-frequency, unambiguous operations,
each backed by an observed denial — never writes, deletes, installs, or
network sends — and settings changes are always proposed to the human,
never applied by the agent.

**Is any of it heuristic ML?** No. Detection is deterministic pattern
matching and counting; error clustering normalizes paths, ids, and numbers
out of the first error line. Same corpus in, same findings out.

## Workflow efficiency ledger

`agentlog.py ledger <workflows-root-or-project-dir>...` turns subagent
workflow runs (`wf_*/` dirs with `journal.jsonl` and per-agent
transcripts) into a cost table: agents started/completed, tool calls,
output tokens, input+cache tokens, context tokens (each agent's final
context footprint, matching the workflow runner's own per-agent counter),
wall and per-agent durations, and agent labels — deterministic,
streaming, byte-identical on rerun, and label/number-only like the rest
of the tool. `--outcomes <json>` joins per-run results (`confirmed`,
`fixed`, `tests_added`, `mutants_killed`, `note`) and adds
tokens-per-finding, so fleet-size and wave-structure decisions for the
next maintenance run are priced against what comparable runs actually
cost. Run it before starting a new target; keep the outcomes file
current; pick the shapes with the cheapest tokens-per-finding.

## It's working if

A 600 MB corpus scans in seconds within a bounded memory footprint, every
finding drills down via `slice file line`, permission findings count only
verified denials (results split from reports, prose and quotes excluded),
no raw message text appears anywhere by default, and the report ends with
concrete allowlist, routine, and harness changes attributed to specific
findings.
