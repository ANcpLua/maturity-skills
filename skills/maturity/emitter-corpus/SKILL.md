---
name: emitter-corpus
description: Validate a parser or importer against a corpus of files as real upstream producers actually write them, and land that corpus as permanent CI fixtures. Use when the user asks whether a parser handles other tools' output, wants format-compatibility testing, interop validation, "does it work with X's files", or a regression corpus or interop fixtures for an input format.
---

Build an upstream-verified corpus of input files as real producers emit them, run the parser/importer under test against every sample, and report wrong results, crashes, and silently dropped data. A parser validated only against its own ecosystem's dominant emitter has never met the format.

## Ground rules

- Ground every sample in upstream reality: check the producer's actual writer source, docs, or real output (web search/fetch) before authoring a sample. Never invent a dialect from memory. Note the upstream reference per sample.
- Run the REAL tool end to end (installed binary or built artifact), not just unit-level parse calls.
- The corpus is files on disk from the first sample, with a README mapping sample to producer to upstream reference — built to be committed, not to be a scratch run.

## Corpus construction

Cover at least: the format's reference implementation (its DTD/schema and full element set), the dominant emitter for the project's own ecosystem, and the major foreign emitters. Example for Cobertura XML: Coverlet (default and DeterministicSourcePaths), gcovr, coverage.py (`--cov-report=xml`, with and without branch data), JaCoCo-to-Cobertura converters (cover2cover), grcov, ReportGenerator. Add structural edge cases: source-root declarations (absolute vs relative filenames), the same relative filename under different roots (monorepo), duplicate entries for one file (partial classes), empty containers, attribute variants, huge and unusual-but-legal values.

## Judge

1. For each sample, compute the semantically correct expected result by hand from the file's meaning, not from what the tool outputs.
2. Findings: wrong totals vs semantic truth, crashes/hangs, silently dropped or fused data, identity mistakes when merging/diffing across producers, false gate verdicts. Severity by how mainstream the producer is.
3. Evidence per finding: sample path, exact command, observed vs expected numbers.

## Ship: the corpus becomes CI

The proven end-state is not a report — it is the corpus checked into the target repo as permanent fixtures, so every future build reruns it:

- Commit the samples under the repo's test-fixture layout, each with its hand-computed semantic expectations encoded as test assertions (the expected numbers came from the file's meaning, so they never need the tool under test to regenerate them).
- Commit the corpus README alongside: sample -> producer -> upstream reference, so a failing fixture immediately names whose output broke and where its format is documented.
- Wire the samples into the existing test suite so the normal build runs them; a one-off script that must be remembered is not a gate.
- Findings fixed during the run get their sample as the regression test; samples that pass today are the tripwire for tomorrow's parser change.

Finish with a summary: producers covered, samples added, findings by severity, and the fixture/test paths where the corpus now lives in CI.
