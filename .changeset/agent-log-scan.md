---
"maturity-skills": minor
---

Add agent-log-scan: a model-invoked skill plus a deterministic, stdlib-only streaming scanner (`agentlog.py`) that mines Claude Code transcript corpora for antipatterns — retry-loops, permission-thrash, API dead-ends, usage-limit interruptions, silence-gaps, cross-session error clusters, and per-tool error rates — without ever loading raw logs into context. Findings carry file:line and byte offsets for O(1) drill-down via `slice` and `bisect`, message text is withheld by default (`--show-text` opts in), and `scan` exits 2 when detectors fire so CI can gate on transcript health. The routine classifies each antipattern as an infrastructure, agent-native, or user-flow fault and ends with concrete allowlist, routine, and harness-config changes.
