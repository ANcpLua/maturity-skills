# perf-gate

## What it does

Collects the performance claims the project makes about itself ("streaming",
"handles 50 MB+", "O(n)"), builds reproducible workloads at multiple scales,
measures wall time and peak memory against the real artifact, and attributes
every suspicious number to a code path before calling it a finding.

## When to reach for it

- The README makes a size or throughput claim nobody has measured.
- A user reports slowness or memory blowups within the claimed envelope.
- You want a perf baseline table so the next run can diff against it.

## Common questions

**Why attribute before accusing?** A retained data model legitimately grows
with input; that is not a streaming failure. The finding threshold is memory
or time growth the code path cannot justify against the claim.

**What about hard limits?** A limit that silently caps the claimed envelope
with no override or actionable error is itself a finding, even when
performance inside the limit is fine.

## It's working if

Claims are each marked validated or contradicted with numbers, generators and
harness are committed for rerun, and the report ends with the full baseline
table even when everything is green.
