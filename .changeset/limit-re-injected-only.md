---
"maturity-skills": patch
---

agent-log-scan: the limit-interrupt detector now fires only on harness-injected usage-limit nodes, not conversational mentions. `LIMIT_RE` is anchored to the two texts the harness injects verbatim (`[Usage limit approaching. Checkpoint now: ...` and `Your claude.ai usage limit has reset. Continue the task ...`) at the very start of the node text, and the marker is applied structurally: only `isMeta: true` user turns and non-message injection records (e.g. the `queue-operation` enqueue of the auto-continuation) qualify. Agent prose about limits, tool results quoting the sentinel, and user discussion no longer count as interruptions; on a 600MB+ real corpus the finding count dropped from 89 to 40, all verified injections.
