# regression-review

## What it does

Takes the previous change-set's diff (last run, merged PR, or merge commit),
works through its prime suspects — new invariants, new helpers duplicating
existing semantics, gates and their disjuncts, exception filters, boundary
comparisons — reading the current code around every hunk, and confirms only
findings with a concrete failure scenario. Every confirmed regression lands
with its fix and a pinning test that fails on the reviewed code.

## When to reach for it

- An autonomous run, a big PR, or a batch of fixes just merged and nobody
  has adversarially reviewed what it changed.
- As the opening step of every follow-up maintenance run: the previous run's
  diff is the newest, least-reviewed code in the repo.
- A user reports a behavior that worked before a recent change.

## Common questions

**Does reviewing only the diff actually catch anything?** In four autonomous
maintenance runs on dotcov, the regression pass scored a real self-introduced
bug in three consecutive runs — 3/3. Run 002 caught run 001's merge
mismatch-arm data loss; run 003 caught run 002's ungated diff
filename-pairing fabricating Modified entries; run 004 caught run 003's
raw-spelling SourceRoots union permanently re-poisoning root comparison.
Every one shipped inside a change-set whose build and full suite were green.

**Why not just review the whole codebase?** Pre-existing bugs are a
different routine's job, and mixing them in dilutes the hunt. Scoping to the
diff keeps the question falsifiable — "did THIS change break it" — and
makes the prime-suspect list (what change-sets characteristically break)
actually apply.

**Why read current code when the diff shows the change?** A hunk can be
locally correct and wrong in interaction: run 003's regression was a union
of raw and normalized spellings that was fine at the change site and
poisonous at the comparison that consumed it later.

## It's working if

Every finding maps to a hunk in the stated diff range, carries a concrete
inputs-to-wrong-output scenario, and ships with a pinning test verified to
fail on the pre-fix code; pre-existing issues found along the way were
routed to their owning routine, not reported as regressions.
