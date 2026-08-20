# agent-log-scan

## What it does

Streams an entire Claude Code transcript corpus (JSONL session history,
hundreds of megabytes) through a deterministic stdlib-Python scanner and
reports antipatterns as an aggregate: retry-loops (same tool failing 3+
times in a row on the same error), permission-thrash (repeated classifier
denials), API dead-ends (sessions that end on a provider error), usage-limit
interruptions, silence-gaps, cross-session error clusters, and per-tool
error rates. Every finding carries `file:line @byte-offset`, so `slice`
jumps straight to the neighborhood and `bisect` finds a long session's
topic boundaries by signature distance. The agent reads kilobytes of
aggregate about megabytes of logs; message text stays out of context
unless `--show-text` is passed.

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

**What do the three fault classes mean?** Infrastructure faults (API
errors, limit cuts) need checkpoint/resume habits; agent-native faults
(retry-loops, unhandled tool errors) need routine tuning; user-flow faults
(permission-thrash) need allowlist and harness-config changes. The routine
ends with a change list, not a chart.

**Is any of it heuristic ML?** No. Detection is deterministic pattern
matching and counting; error clustering normalizes paths, ids, and numbers
out of the first error line. Same corpus in, same findings out.

## It's working if

A 600 MB corpus scans in seconds within a bounded memory footprint, every
finding drills down via `slice file line`, no raw message text appears
anywhere by default, and the report ends with concrete allowlist, routine,
and harness changes attributed to specific findings.
