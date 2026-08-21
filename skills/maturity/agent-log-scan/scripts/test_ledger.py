#!/usr/bin/env python3
"""Fixture-based self-test for the `agentlog.py ledger` subcommand.

Builds a synthetic mini-workflow directory with hand-computed numbers and
asserts the ledger reproduces them exactly, deterministically (byte-
identical reruns), in both --json and --md modes, with and without an
--outcomes join. Exercises the parser edge cases that matter:

- streaming duplicate entries sharing one message.id (cumulative usage
  snapshots; the LAST snapshot per id is final, tokens must not be
  double-counted)
- tool_use blocks repeated across snapshots of the same message (deduped
  by (message.id, block.id))
- ctx tokens = input + cache_creation + cache_read + output of the FIRST
  recorded snapshot of the agent's LAST message
- labels from the runner state json, agentType fallback from meta.json
- recursive run-dir discovery from a session dir

Run: python3 test_ledger.py            (exit 0 = pass, 1 = fail)
Stdlib only, no network, no reads outside its own temp dir.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
AGENTLOG = os.path.join(HERE, "agentlog.py")
RUN_ID = "wf_test1-abc"


def jline(obj):
    return json.dumps(obj) + "\n"


def build_fixture(root):
    session = os.path.join(root, "session")
    run_dir = os.path.join(session, "subagents", "workflows", RUN_ID)
    state_dir = os.path.join(session, "workflows")
    os.makedirs(run_dir)
    os.makedirs(state_dir)

    with open(os.path.join(run_dir, "journal.jsonl"), "w") as f:
        f.write(jline({"type": "started", "key": "k1", "agentId": "aaa111"}))
        f.write(jline({"type": "started", "key": "k2", "agentId": "bbb222"}))
        f.write(jline({"type": "result", "key": "k1", "agentId": "aaa111",
                       "result": {}}))
        f.write(jline({"type": "result", "key": "k2", "agentId": "bbb222",
                       "result": {}}))

    def asst(mid, usage, blocks, ts):
        return jline({
            "type": "assistant", "timestamp": ts,
            "message": {"id": mid, "role": "assistant",
                        "content": blocks, "usage": usage},
        })

    # Agent A: msg m1 streams as two snapshots (tool_use tu1 repeated in
    # both -> deduped); msg m2 is single-snapshot and last, so
    # ctx = 20 + 200 + 2000 + 7 = 2227.
    # Final tokens: out 50 + 7 = 57; in+cache (10+100+1000)+(20+200+2000)
    # = 3330. tools: tu1, tu2 = 2. duration 00:00:00 -> 00:01:00 = 1m.
    with open(os.path.join(run_dir, "agent-aaa111.jsonl"), "w") as f:
        f.write(asst(
            "m1",
            {"input_tokens": 10, "cache_creation_input_tokens": 100,
             "cache_read_input_tokens": 1000, "output_tokens": 5},
            [{"type": "tool_use", "id": "tu1", "name": "Bash"}],
            "2026-01-01T00:00:00.000Z"))
        f.write(asst(
            "m1",
            {"input_tokens": 10, "cache_creation_input_tokens": 100,
             "cache_read_input_tokens": 1000, "output_tokens": 50},
            [{"type": "tool_use", "id": "tu1", "name": "Bash"},
             {"type": "tool_use", "id": "tu2", "name": "Read"}],
            "2026-01-01T00:00:10.000Z"))
        f.write(asst(
            "m2",
            {"input_tokens": 20, "cache_creation_input_tokens": 200,
             "cache_read_input_tokens": 2000, "output_tokens": 7},
            [{"type": "text", "text": "done"}],
            "2026-01-01T00:01:00.000Z"))

    # Agent B: one message, two snapshots; last message's FIRST snapshot
    # gives ctx = 1 + 10 + 100 + 2 = 113. Final out 40, in+cache 111.
    # tools: tu3 = 1. duration 00:00:30 -> 00:02:00 = 1m30s.
    with open(os.path.join(run_dir, "agent-bbb222.jsonl"), "w") as f:
        f.write(asst(
            "m3",
            {"input_tokens": 1, "cache_creation_input_tokens": 10,
             "cache_read_input_tokens": 100, "output_tokens": 2},
            [{"type": "tool_use", "id": "tu3", "name": "Write"}],
            "2026-01-01T00:00:30.000Z"))
        f.write(asst(
            "m3",
            {"input_tokens": 1, "cache_creation_input_tokens": 10,
             "cache_read_input_tokens": 100, "output_tokens": 40},
            [{"type": "text", "text": "ok"}],
            "2026-01-01T00:02:00.000Z"))

    # Label for A comes from the runner state json; B falls back to its
    # meta.json agentType. Numbers in the state json are decoys the
    # ledger must NOT copy.
    with open(os.path.join(state_dir, RUN_ID + ".json"), "w") as f:
        json.dump({
            "runId": RUN_ID, "workflowName": "fixture-run",
            "totalTokens": 999999, "totalToolCalls": 999,
            "workflowProgress": [
                {"type": "workflow_agent", "agentId": "aaa111",
                 "label": "fix:alpha", "tokens": 888888},
            ],
        }, f)
    with open(os.path.join(run_dir, "agent-bbb222.meta.json"), "w") as f:
        json.dump({"agentType": "workflow-subagent", "spawnDepth": 1}, f)

    with open(os.path.join(root, "outcomes.json"), "w") as f:
        json.dump({"wf_test1": {"confirmed": 2, "note": "fixture"}}, f)
    return session, run_dir


EXPECT_RUN = {
    "run_id": RUN_ID, "workflow": "fixture-run",
    "agents_started": 2, "agents_completed": 2, "transcripts": 2,
    "tool_calls": 3, "output_tokens": 97, "in_cache_tokens": 3441,
    "ctx_tokens": 2340, "wall_seconds": 120,
}
EXPECT_AGENTS = {
    "aaa111": {"label": "fix:alpha", "output_tokens": 57,
               "in_cache_tokens": 3330, "ctx_tokens": 2227,
               "tool_calls": 2, "messages": 2, "duration_seconds": 60},
    "bbb222": {"label": "workflow-subagent", "output_tokens": 40,
               "in_cache_tokens": 111, "ctx_tokens": 113,
               "tool_calls": 1, "messages": 1, "duration_seconds": 90},
}

_failures = []


def check(name, cond, detail=""):
    if cond:
        print("ok   %s" % name)
    else:
        _failures.append(name)
        print("FAIL %s %s" % (name, detail))


def run_ledger(args):
    proc = subprocess.run(
        [sys.executable, AGENTLOG, "ledger"] + args,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.returncode, proc.stdout, proc.stderr


def main():
    root = tempfile.mkdtemp(prefix="agentlog-ledger-fixture-")
    try:
        session, run_dir = build_fixture(root)
        outcomes = os.path.join(root, "outcomes.json")

        rc, out1, err = run_ledger([session, "--json",
                                    "--outcomes", outcomes])
        check("exit 0", rc == 0, err.decode("utf-8", "replace"))
        rc2, out2, _ = run_ledger([session, "--json",
                                   "--outcomes", outcomes])
        check("byte-identical rerun (json)", rc2 == 0 and out1 == out2)

        data = json.loads(out1.decode("utf-8"))
        check("one run discovered", len(data["runs"]) == 1,
              str(len(data["runs"])))
        run = data["runs"][0]
        for k, v in EXPECT_RUN.items():
            check("run %s == %r" % (k, v), run.get(k) == v,
                  "got %r" % (run.get(k),))
        agents = {a["agent_id"]: a for a in run["agents"]}
        for aid, exp in EXPECT_AGENTS.items():
            for k, v in exp.items():
                check("agent %s %s == %r" % (aid, k, v),
                      agents.get(aid, {}).get(k) == v,
                      "got %r" % (agents.get(aid, {}).get(k),))
        check("outcomes joined by short-id prefix",
              run.get("outcomes") == {"confirmed": 2, "note": "fixture"},
              repr(run.get("outcomes")))
        check("ctx tokens per finding == 1170",
              run.get("ctx_tokens_per_finding") == 1170,
              repr(run.get("ctx_tokens_per_finding")))
        check("totals mirror the single run",
              data["totals"]["ctx_tokens"] == EXPECT_RUN["ctx_tokens"]
              and data["totals"]["tool_calls"] == EXPECT_RUN["tool_calls"])

        # Direct run-dir arg must equal session-dir discovery.
        rc3, out3, _ = run_ledger([run_dir, "--json",
                                   "--outcomes", outcomes])
        check("run dir arg == session dir discovery",
              rc3 == 0 and out3 == out1)

        rc4, md1, err4 = run_ledger([session, "--outcomes", outcomes])
        rc5, md2, _ = run_ledger([session, "--outcomes", outcomes])
        check("markdown exit 0", rc4 == 0,
              err4.decode("utf-8", "replace"))
        check("byte-identical rerun (md)", md1 == md2)
        text = md1.decode("utf-8")
        row = ("| wf_test1-abc | fixture-run | 2/2 | 3 | 97 | 3,441 |"
               " 2,340 | 2m00s | 2 | - | - | - | 1,170 | fixture |")
        check("md aggregate row exact", row in text, "missing: " + row)
        check("md has per-agent labels",
              "fix:alpha" in text and "workflow-subagent" in text)
        # The fixture's only message texts are "done" and "ok"; neither
        # may surface in any output cell (ledger prints labels and
        # numbers only).
        check("privacy: no message text leaks",
              "| done |" not in text and "| ok |" not in text
              and '"done"' not in text)

        rc6, _out6, err6 = run_ledger([os.path.join(root, "nope")])
        check("missing path exits 1", rc6 == 1,
              err6.decode("utf-8", "replace"))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    if _failures:
        print("%d check(s) FAILED" % len(_failures))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
