# maturity-skills

Evidence-first maintenance routines for codebases, as agent skills. Born in
autonomous maintenance runs on [dotcov](https://github.com/ANcpLua/dotcov),
where each of these routines earned its place by finding verified bugs that
line coverage, linters, and review had all missed.

The house rule across all three: **findings need repros, not vibes.** Every
routine produces evidence (a killed-or-surviving mutant, a corpus file plus
observed-vs-expected numbers, a measurement table) before anything is called
a finding.

## Install

Claude Code:

```
/plugin marketplace add ANcpLua/maturity-skills
/plugin install maturity-skills@ancplua
```

Codex and other agents: copy the skill folders you want from
`skills/maturity/` into your harness's skill directory. Pick one route, not
both.

## Skills

### Model-invoked

- **[mutation-tester](./skills/maturity/mutation-tester/SKILL.md)**: Run
  mutation testing and turn surviving mutants into targeted tests. A high
  line-coverage number says the code ran; only a killed mutant proves a test
  would fail if the code broke.
- **[emitter-corpus](./skills/maturity/emitter-corpus/SKILL.md)**: Validate a
  parser/importer against a corpus of files as real upstream producers
  actually write them. A parser validated only against its own ecosystem's
  dominant emitter has never met the format.
- **[perf-gate](./skills/maturity/perf-gate/SKILL.md)**: Measure the
  project's own performance claims (README, docs) against reality and
  attribute regressions to code before accusing it.
- **[agent-log-scan](./skills/maturity/agent-log-scan/SKILL.md)**: Mine
  agent-transcript corpora for antipatterns (retry-loops, permission-thrash,
  API dead-ends, limit interruptions) with a deterministic streaming scanner,
  and turn them into allowlist, routine, and harness changes. The agent reads
  the aggregate, never the raw logs.

## Layout

- `skills/maturity/<name>/SKILL.md`: the skill itself
- `skills/maturity/<name>/agents/openai.yaml`: harness interface metadata
- `docs/maturity/<name>.md`: human-facing docs page per skill
- `.claude-plugin/`: plugin + single-plugin-marketplace manifests
- `.changeset/` + `.github/workflows/release.yml`: changesets-driven versioning
