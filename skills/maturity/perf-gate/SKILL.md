---
name: perf-gate
description: Measure a project's own performance claims (README, docs) against reality and attribute regressions to code. Use when the user asks to verify a performance claim, benchmark a tool, check "does it really handle X MB / X requests", validate streaming or O(n) claims, or establish a perf baseline.
---

Find the performance claims the project makes about itself (README, docs, package descriptions: "streaming", "handles X MB", "zero-allocation", "O(n)") and validate each with measurements against the real built artifact. A claim nobody has measured is a bug report waiting in a user's terminal.

## Ground rules

- Measure the real artifact (installed binary / release build), not a debug harness.
- Generators and harness are files on disk (e.g. `gen.py`, `bench.sh`) committed to a scratch area so the next run reproduces the exact workload.
- Methodology: 3+ runs per cell, report medians; measure wall time AND peak memory (`/usr/bin/time -l` on macOS, `-v` on Linux); scale inputs across at least three sizes so growth curves are visible (e.g. 1x, 10x, 50x) and include the many-small-inputs merge path, not just one big input.

## Judge: attribute before accusing

1. Read the code paths behind each number before claiming a finding: distinguish legitimate retained-model growth from streaming failure, and startup cost from per-item cost.
2. Findings: a claim the measurements contradict (including hard limits that cap the claimed size), superlinear growth where linear is claimed or expected (quadratic merge folds, per-item rescans), memory scaling with input size where streaming is claimed, hangs/crashes at sizes within the claimed envelope, and limits reachable by users with no override or actionable error.
3. Evidence per finding: the measurement table, the code location responsible, and the claim text it contradicts.
4. Always include the full measurement table in the report. A green table is the perf regression baseline for the next run.

Finish with a summary: claims validated, claims contradicted (with numbers), limits documented vs undocumented, and the baseline table.
