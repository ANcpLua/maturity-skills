---
name: regression-review
description: Adversarially review only the previous change-set's diff, hunting bugs that change-set itself introduced. Use when the user asks whether the last run/PR/merge broke anything, "did that fix introduce a bug", "review what the previous run changed", wants a post-merge or post-run regression hunt, wants an autonomous run's own output audited, or as the opening step of a follow-up maintenance run.
---

Review ONLY the previous change-set's diff and hunt for bugs that change-set *introduced*. Pre-existing issues are a different routine's job; a change that fixed nine things and quietly broke a tenth is this one's.

## Ground rules

- Derive the diff range from the last run, PR, or merge: the previous run report's commit range, `gh pr view`/`gh pr diff` for a merged PR, or the last merge commit's two parents. State the exact range in the report; every finding must be traceable to a hunk inside it.
- Scope discipline: pre-existing issues discovered along the way are noted and routed to the owning routine, never reported as findings here. The question is always "did THIS change-set break it", not "is this code good".
- Read the CURRENT code around every suspect hunk, not just the hunk. A change can be locally correct and wrong in interaction with the code that now surrounds it, calls it, or merges its output.
- Reproduce with the real artifact (built binary, real inputs) where possible, not just by reasoning over the diff.

## Prime suspects

Work the diff in this order; these are where change-sets break things:

1. **New invariants**: anything the change-set now asserts, assumes, or promises (sortedness, uniqueness, normalized paths) — check every producer and consumer actually upholds it.
2. **New helpers duplicating existing semantics**: a fresh function that re-implements comparison, normalization, or pairing that exists elsewhere — hunt for drift between the two on the inputs where they differ.
3. **Gates and their disjuncts**: a condition added into an existing gate (new `||`/`&&` arm, new early return) — check each disjunct alone, and what the gate now lets through or blocks that it did not before.
4. **Exception filters**: new or widened `catch`/`when` clauses — what do they now swallow?
5. **Comparisons near boundaries**: off-by-one, inclusive/exclusive flips, epsilon guards, integer-vs-float space changes introduced by the diff.

## Judge

A suspicion is a candidate, not a finding. A finding needs a concrete failure scenario: the inputs and state, the wrong output or lost data they produce under the new code, and the correct behavior the pre-change code (or the spec) gave. If you cannot state the scenario, keep digging or clear the suspect.

## Ship

- Every confirmed finding lands with its fix AND a pinning test that fails on the reviewed change-set's code and passes on the fixed code. The test is the proof the regression existed and the lock against its return.
- Deliver on the repo's agreed flow with build and full suite green.

Finish with a summary: diff range reviewed, findings confirmed (each with its failure scenario and pinning test), suspects examined and cleared, pre-existing issues routed elsewhere.
