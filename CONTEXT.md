# Maturity Skills

Evidence-first maintenance routines loaded by agent harnesses. Skills live in
buckets under `skills/` and ship as a Claude Code plugin.

## Language

**Routine**:
One maintenance skill run end to end against a repo (a mutation-tester run, an
emitter-corpus run). Routines produce **Findings**.
_Avoid_: check, scan (too weak; a routine includes judging and shipping)

**Finding**:
A defect claim backed by evidence: a repro command, a surviving mutant, a
measurement table. A claim without evidence is a candidate, not a finding.

**Survivor**:
A mutant the test suite failed to kill. Survivors are candidates; only a
survivor classified as a real test gap becomes a finding.

**Corpus**:
The on-disk set of upstream-verified sample files an emitter-corpus run builds
and reruns as a regression suite. Every sample carries its upstream reference.

**Baseline**:
The full measurement table a perf-gate run publishes even when green; the next
run diffs against it.
