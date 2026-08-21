---
name: maintenance-run
description: Orchestrate a full autonomous maintenance run on a repo - parallel finders, root-cause dedupe, adversarial verification, a fixer fleet with disjoint ownership, single-writer integration, and a hard termination rule. Use when the user asks for an autonomous maintenance run, a repo health pass, "find and fix everything", recurring or scheduled repo maintenance, a multi-agent bug-hunting sweep, or asks whether/when a maintenance loop should stop.
---

Run the full find-verify-fix-integrate loop as one routine. Findings need repros; fixes need adversarial review before they land; and the loop needs a termination condition, or it manufactures its own work.

## 1. Scope and finders

Fix the target scope, then launch read-only finders in parallel, one per dimension. Reuse the sibling maturity routines as finder dimensions where they fit: mutation-tester (test-gap hunting, mutation-score baseline), emitter-corpus (interop/parser truth), perf-gate (performance claims), agent-log-scan (harness/autonomy health), plus code-reading finders for logic, merge, and boundary bugs. Every raw finding needs evidence: a repro command, a failing input, a measurement — not a vibe.

## 2. Dedupe by root cause BEFORE verification

Mechanical first: collect the raw findings as JSON (`title`/`file`/`category` required; `line`, `severity`, `evidence`, `dimension` strongly encouraged; per-finding `root_cause` is REQUIRED in the finder handoff — the signature rule bites on it, and title-only output demonstrably under-merges: on run-002's replay it reached none of the cross-file merges) and run `scripts/findings.py dedupe <findings.json>` (Python 3 stdlib, deterministic: same input, byte-identical output; `validate` gates the finder handoff). It merges only what is provably mechanical — root-cause signatures with ≥ 1/2 token-set overlap after agentlog-style normalization (paths/ids/hex/numbers stripped), or identical normalized titles — takes the transitive closure, picks each cluster's primary by severity then evidence, and reports every merge edge with its reason. Line proximity never merges: on run-002's ground truth, 4 of 7 same-file near-line pairs were distinct claims and no window setting separates them (the closest false pair sat 1 line apart, a true pair 14 apart), so same-file pairs within ±15 lines are flagged on the `ambiguous` list with their distance instead of being fused. Exit 2 means merges happened, 0 means nothing merged, 1 means the findings file is malformed (fix the finder output, don't hand-edit).

The dedupe arbiter then works the tool's `ambiguous` list — file-window pairs and near-threshold signature pairs — reading the code where the pair text is not enough. Tool merges are a floor, not a ceiling: the arbiter may SPLIT a tool cluster with a stated reason, and may MERGE pairs the tool did not flag when it states the shared root cause with evidence from the code — run-002's cross-file duplicate-policy cluster is reachable only this way when finders skimp on `root_cause`. What the arbiter never does is re-cluster from scratch or depart from tool output without stated evidence. Two findings whose fixes land on the same code for the same reason are one cluster. Verifying raw findings wastes verifier passes refuting duplicates after the fact; verifying clusters spends every pass on a distinct claim.

## 3. Adversarial verification per cluster

Every cluster gets a verifier whose mandate is to REFUTE it: default not-real, confirmed only when the failure scenario survives an active attempt to break it against the current code. The verifier also reviews the proposed fix, and its `fix_adjustment` OVERRIDES the finder's proposal — the verified fix is what the fixers implement, not the original suggestion.

## 4. Fixer fleet

- **Disjoint file ownership**: every fixer owns an explicit, non-overlapping file set and works in its own isolated git worktree. Work outside the boundary goes into `cross_boundary_notes` handed to the owning fixer — never fixed by trespassing.
- **Two-wave sequencing**: when one fixer's work depends on another's new API, the dependent fixer runs in wave 2, starting from the merged wave-1 state — never from declared-but-unbuilt signatures.
- **Per-fixer gate**: build with 0 warnings plus the full test suite green before the fixer's single commit. One commit per fixer.
- **Conduct rules**: a user rejection of a command is TERMINAL for that exact command — never re-issue it; ask, or propose an alternative. After ONE settings/permissions denial, report the proposed permission rule to the human instead of retrying through a different write mechanism. Allowlist proposals cover only read-only, high-frequency, unambiguous operations, each backed by an observed denial — never writes, deletes, installs, or network sends.

## 5. Integration

A single writer merges all fixer commits, runs full verification (build, suite, and any baselines such as the mutation score against the recorded floor), and delivers per the repo's agreed flow. Nobody else writes to the integration branch.

## 6. Run report

Record: findings confirmed and fixed, clusters refuted (with the refutations), baselines before/after, the findings-curve datapoint (total findings, and how many were regressions of the previous run's own changes), and tuning notes for the routine itself.

## 7. Next run opens with regression-review

The next run's first finder is the regression-review routine over THIS run's diff. The previous change-set is the newest code in the repo and the least reviewed; it gets the adversarial pass before anything else does.

## 8. The termination rule

This is a hard rule, not guidance. Track the findings curve and the self-introduced share across runs. When a run's findings are predominantly regressions of the previous run's own changes, the target is DONE: the loop is no longer finding the repo's bugs, it is finding its own. Write a closing report, stop scheduling runs, and say so explicitly. Tuning notes must never be the only reason a next run exists.

Finish with the run report, the updated findings curve, and an explicit continue-or-terminate verdict under the termination rule.
