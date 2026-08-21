# mutation-tester

## What it does

Runs mutation testing (Stryker where it works, manual mutation probing where
it does not) in an isolated worktree, classifies every surviving mutant as
equivalent, dead code, or a real test gap, and ships the smallest tests that
kill the real gaps — each verified apply-fail-revert (the mutant is
re-applied, the new test fails, the mutant is reverted). It runs in two
modes: hunting (first pass: raise the score) and baseline gating (every
later pass: record the score per target, treat any drop below baseline as a
finding naming the regressed areas, and kill survivors in new code).

## When to reach for it

- Line coverage is high but you do not trust the suite.
- Before refactoring verdict/gating/merge logic you cannot afford to break.
- After a large test-writing push, to check what the new tests actually pin.
- On repeated maintenance runs, to prove the previous run did not quietly
  weaken the suite (the recorded baseline is the tripwire).

## Common questions

**Is a surviving mutant always a bug?** No. Equivalent mutants change nothing
observable and are noted, not fixed. Only survivors exposing untested
observable behavior become tests.

**Does it need Stryker?** No. The tool attempt is time-boxed; the fallback is
manual probing of ~15 high-value sites, one mutant at a time, suite run,
revert, record.

**When does it stop?** Hunting stops when the remaining survivors are only
cosmetics and equivalents — chasing those manufactures work without pinning
behavior (a real target went 82.47 -> 92.47 -> 94.12 and then held). The
baseline gate keeps running forever: re-measure, compare, flag any drop, and
demand kills for new-code survivors.

## It's working if

Each new test demonstrably kills its mutant (re-apply mutant, test fails,
revert), the score is at or above the recorded baseline, any drop is
reported as a finding naming the regressed areas, and no test asserts
implementation text.
