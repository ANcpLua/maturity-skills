---
name: mutation-tester
description: Run mutation testing and turn surviving mutants into targeted tests. Use when the user asks for mutation testing, a mutation score, Stryker, "how good are my tests really", test-suite strength auditing, or wants test gaps found beyond line coverage.
---

Run mutation testing, find surviving mutants, and pin the exposed behavior with targeted tests. A high line-coverage number says the code *ran*; only a killed mutant proves a test would *fail* if the code broke.

## Ground rules

- Detect the stack first: `*.sln`/`*.csproj` means C#/.NET (Stryker.NET: `dotnet tool install -g dotnet-stryker`, then `dotnet stryker --project <proj>`); `package.json` + `tsconfig.json` means TypeScript (StrykerJS). Both present: each part with its own toolchain.
- Mutate in an isolated git worktree, never the main checkout. Mutation runs leave build litter and must not race other work.
- Verification gate: build + full tests green before anything ships.
- Time-box the tool: if Stryker will not run on this stack version within ~10 minutes of setup effort, fall back to manual mutation probing. Pick ~15 high-value sites (boundary comparisons, merge/aggregation logic, epsilon guards, parser branches), apply one mutant at a time (flip an operator, off-by-one a boundary, swap Max/Min, drop a guard), run the suite, revert, record survivors.

## Judge survivors

A surviving mutant is a candidate, not automatically a finding.

1. Classify each survivor: equivalent mutant (no observable behavior change: note it, no action), dead code (route to a dead-code routine), or a real test gap.
2. For real gaps, write the smallest test that kills the mutant while asserting user-visible behavior, never a test that mirrors implementation text. Verify it actually kills: re-apply the mutant, confirm the new test fails, revert.
3. Prioritize by blast radius: mutants in verdict/gating/money/merge logic first; formatting cosmetics last.

## Ship

- One PR (or one commit per area on the agreed delivery flow) with the new tests and the before/after mutation score.
- Report: score before/after, survivors killed, equivalent mutants noted, dead code routed elsewhere.

Finish with a summary: mutation score, tests added, survivors deliberately left and why.
