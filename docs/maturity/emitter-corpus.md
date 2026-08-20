# emitter-corpus

## What it does

Builds an on-disk corpus of input files as real upstream producers write them
(each sample grounded in the producer's actual writer source or docs), runs
the real built tool against every sample, and reports wrong totals, crashes,
and silently dropped or fused data with observed-vs-expected numbers.

## When to reach for it

- A parser has only ever been validated against its own ecosystem's dominant
  emitter.
- Interop bug reports arrive from users of a foreign toolchain.
- You want a permanent regression corpus for an input format.

## Common questions

**Why not synthesize samples from the spec?** Producers deviate from specs.
The corpus mirrors what tools actually emit, which is what users actually
feed you; every sample notes its upstream reference.

**What counts as a finding?** A difference between the file's semantic truth
(computed by hand) and the tool's output, a crash, or silently vanished data.
Severity follows how mainstream the producer is.

## It's working if

Every sample maps to a named producer with an upstream reference, findings
carry exact commands plus observed-vs-expected numbers, and the corpus reruns
green as a regression suite after fixes land.
