# emitter-corpus

## What it does

Builds an on-disk corpus of input files as real upstream producers write them
(each sample grounded in the producer's actual writer source or docs), runs
the real built tool against every sample, and reports wrong totals, crashes,
and silently dropped or fused data with observed-vs-expected numbers. The
end-state is the corpus checked into the target repo as permanent CI
fixtures: each sample with hand-computed semantic expectations encoded as
test assertions, plus a README mapping sample to producer to upstream
reference, so every future build reruns the whole corpus.

## When to reach for it

- A parser has only ever been validated against its own ecosystem's dominant
  emitter.
- Interop bug reports arrive from users of a foreign toolchain.
- You want a permanent regression corpus for an input format that the normal
  build runs without anyone remembering a script.

## Common questions

**Why not synthesize samples from the spec?** Producers deviate from specs.
The corpus mirrors what tools actually emit, which is what users actually
feed you; every sample notes its upstream reference.

**What counts as a finding?** A difference between the file's semantic truth
(computed by hand) and the tool's output, a crash, or silently vanished data.
Severity follows how mainstream the producer is.

**Why hand-computed expectations?** Because the expected numbers come from
the file's meaning, not from the tool under test, they never need the tool
to regenerate them — a fixture that derives its expectation from the code it
tests can only ever agree with it.

## It's working if

Every sample maps to a named producer with an upstream reference, findings
carry exact commands plus observed-vs-expected numbers, the samples and
README are committed under the repo's test-fixture layout wired into the
existing suite, and a later parser change that breaks a producer's dialect
fails the build by name.
