# mutation-tester

## What it does

Runs mutation testing (Stryker where it works, manual mutation probing where
it does not) in an isolated worktree, classifies every surviving mutant as
equivalent, dead code, or a real test gap, and ships the smallest tests that
kill the real gaps. Reports mutation score before and after.

## When to reach for it

- Line coverage is high but you do not trust the suite.
- Before refactoring verdict/gating/merge logic you cannot afford to break.
- After a large test-writing push, to check what the new tests actually pin.

## Common questions

**Is a surviving mutant always a bug?** No. Equivalent mutants change nothing
observable and are noted, not fixed. Only survivors exposing untested
observable behavior become tests.

**Does it need Stryker?** No. The tool attempt is time-boxed; the fallback is
manual probing of ~15 high-value sites, one mutant at a time, suite run,
revert, record.

## It's working if

Each new test demonstrably kills its mutant (re-apply mutant, test fails,
revert), the mutation score rose, and no test asserts implementation text.
