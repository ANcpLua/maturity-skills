# maintenance-run

## What it does

Runs the whole maintenance loop as one routine: parallel read-only finders
(reusing the sibling maturity skills as finder dimensions), root-cause
dedupe before verification — the bundled deterministic tool
(`scripts/findings.py`) merges the mechanical share and flags the rest on
an `ambiguous` list the dedupe arbiter judges, with split-and-merge
authority backed by stated code evidence — an adversarial verifier per cluster
with authority to override the proposed fix, a fixer fleet with disjoint
file ownership in isolated worktrees, single-writer integration, a run
report, and a hard termination rule that ends the loop when it starts
finding only its own regressions.

## When to reach for it

- A repo needs a full autonomous health pass, not one dimension of it.
- Maintenance is being scheduled to recur and needs a defined stopping
  point, not an open-ended subscription.
- Previous ad-hoc multi-agent sweeps produced merge conflicts, duplicate
  findings, or fixes that were themselves wrong.

## Common questions

**Why dedupe before verification?** Measured on dotcov: run 001 verified
raw findings and refuted 11 of 60 after the fact; run 002 clustered 34 raw
findings into 26 root-cause clusters first, and the verifiers then refuted
0. Clustering spends every verifier pass on a distinct claim. The arbiter
reads code where clustering is unclear; two findings whose fixes land on
the same code for the same reason are one cluster.

**Why is part of dedupe a tool instead of a judgment call?** House
doctrine: agents treat prompt rules as guidelines and lose them
mid-context; a deterministic tool with an exit code does not negotiate.
`scripts/findings.py dedupe` merges only the provably mechanical share —
near-identical normalized root-cause signatures and identical normalized
titles, transitive closure — with byte-identical output for the same
input. Line proximity never merges: replayed against run 002's arbiter
ground truth, 4 of 7 same-file near-line pairs were distinct claims and
no window setting separates them (the closest false pair sat one line
apart while a true pair sat fourteen apart), so near-line pairs are
flagged on the explicit `ambiguous` list with their distance instead of
being fused. The arbiter judges that list, may split a tool cluster with
a stated reason, and may merge unflagged pairs with stated code
evidence — tool merges are a floor, not a ceiling. The cross-file
root-cause merges are exactly where the arbiter's code reading remains
load-bearing, which is why the handoff requires a real per-finding
`root_cause` field for the signature rule to bite on.

**Why does the verifier override the finder's fix?** Across four runs the
refute-by-default verifiers' `fix_adjustment` prevented at least five wrong
fixes, including an API-breaking rename, an integer-space comparison that
could not keep a documented no-drift promise, and a fix that did not cover
the case it claimed. The finder proves the bug; the verifier owns the fix.

**Does disjoint ownership actually prevent conflicts?** Four runs, up to
four parallel writers in separate git worktrees, zero merge conflicts.
Two-wave sequencing matters just as much: wave 2 starts from the merged
wave-1 state, never from declared-but-unbuilt signatures.

**Why is the termination rule a hard rule?** The dotcov findings curve ran
49 confirmed (all pre-existing), then 26, then 8, then 2 — and the final
run's findings were 100% regressions self-introduced by the previous run.
Past that point the loop manufactures its own work: each run's diff becomes
the next run's bug supply. When findings are predominantly regressions of
the previous run's own changes, the target is done — closing report, stop
scheduling, say so. Tuning notes never justify a next run on their own.

## It's working if

Findings drop run over run while baselines (e.g. mutation score) rise, the
verifiers refute near-zero clusters because dedupe already collapsed the
duplicates (`findings.py dedupe` exits 2 when it merged anything, and the
arbiter's attention went only to its `ambiguous` list and to splits it
could state a reason for), integration merges every fixer commit without
conflicts, each
run report states the findings-curve datapoint with the self-introduced
share, and the loop ends with an explicit closing report instead of
trailing off into runs that only re-review themselves.
