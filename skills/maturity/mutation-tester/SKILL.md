---
name: mutation-tester
description: Run mutation testing and turn surviving mutants into targeted tests, or keep a recorded mutation-score baseline as a regression gate. Use when the user asks for mutation testing, a mutation score, Stryker, "how good are my tests really", test-suite strength auditing, wants test gaps found beyond line coverage, or wants repeated maintenance runs to prove the suite did not weaken.
---

Run mutation testing, find surviving mutants, and pin the exposed behavior with targeted tests. A high line-coverage number says the code *ran*; only a killed mutant proves a test would *fail* if the code broke.

The routine has two modes: **hunting** (first run on a target: raise the score by killing real gaps) and **baseline gating** (every later run: hold the recorded score and chase only what moved). Hunting ends; gating never does.

## Ground rules

- Detect the stack first: `*.sln`/`*.csproj` means C#/.NET (Stryker.NET: `dotnet tool install -g dotnet-stryker`, then `dotnet stryker --project <proj>`); `package.json` + `tsconfig.json` means TypeScript (StrykerJS). Both present: each part with its own toolchain.
- Mutate in an isolated git worktree, never the main checkout. Mutation runs leave build litter and must not race other work.
- Verification gate: build + full tests green before anything ships.
- Time-box the tool: if Stryker will not run on this stack version within ~10 minutes of setup effort, fall back to manual mutation probing. Pick ~15 high-value sites (boundary comparisons, merge/aggregation logic, epsilon guards, parser branches), apply one mutant at a time (flip an operator, off-by-one a boundary, swap Max/Min, drop a guard), run the suite, revert, record survivors.

## Judge survivors

A surviving mutant is a candidate, not automatically a finding.

1. Classify each survivor: equivalent mutant (no observable behavior change: note it, no action), dead code (route to a dead-code routine), or a real test gap.
2. For real gaps, write the smallest test that kills the mutant while asserting user-visible behavior, never a test that mirrors implementation text. Verify it actually kills — apply the mutant, confirm the new test fails, revert, confirm the suite is green (apply-fail-revert-verified). A test that was never seen failing proves nothing.
3. Prioritize by blast radius: mutants in verdict/gating/money/merge logic first; formatting cosmetics last.

## Baseline gate

Record the mutation score per target when a run finishes, alongside the survivors deliberately left and why. On every later run over the same target:

- Re-measure and compare against the recorded baseline. **A score below baseline is itself a finding**: name the regressed files/areas (the mutants that survive now but were killed at baseline) and route them through Judge survivors like any other candidate. A maintenance run that lowered the score has weakened the suite even if all its tests pass.
- Survivors in **new code** (added since the baseline) get the same apply-fail-revert-verified killing tests as hunting mode; new code never inherits the old baseline's tolerance.
- When the remaining survivors are only cosmetics and equivalent mutants, **keep the gate running but stop active hunting**. The gate's job from then on is detecting regression, not manufacturing work: chasing equivalents burns runs for zero behavior pinned (a real target went 82.47 -> 92.47 -> 94.12 and then held; further hunting found nothing that mattered).
- Record the new score as the baseline for the next run only when it is >= the old one.

## Ship

- One PR (or one commit per area on the agreed delivery flow) with the new tests and the before/after mutation score.
- Report: score before/after vs recorded baseline, survivors killed, equivalent mutants noted, dead code routed elsewhere, and the baseline recorded for the next run.

Finish with a summary: mutation score vs baseline, tests added, survivors deliberately left and why, and whether the target is in hunting or gate-only mode.
