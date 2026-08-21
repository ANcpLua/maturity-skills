#!/usr/bin/env python3
"""agentlog: deterministic streaming scanner for Claude Code JSONL transcripts.

Subcommands:
  scan <path>...    one streaming pass per file; per-session + aggregate
                    antipattern detection; prints a compact aggregate only
  slice <file> <line>   O(1)-style drill-down: K nodes around a line as
                    one-line summaries
  bisect <file>     largest topic/cohesion boundaries in one session by
                    signature-vector distance
  ledger <path>...  workflow efficiency ledger: per-run/per-agent token,
                    tool-call, and duration aggregates for subagent
                    workflow directories (wf_*/journal.jsonl +
                    agent-<id>.jsonl); optional --outcomes join

Privacy default: no message text is ever printed -- only signatures, counts,
tool names, line numbers, and byte offsets. --show-text opts in to <=160-char
snippets (scan/slice only; ledger prints labels and numbers, never text).

Exit codes: 0 ok; 1 bad usage/paths; 2 scan completed and the antipattern
detectors (retry-loop, permission-thrash, api-dead-end, limit-interrupt)
found something, so CI can gate on it.

Python 3.9+ compatible, stdlib only. Never loads a whole file into memory.
"""

import argparse
import datetime
import json
import math
import os
import re
import sys
import time
from collections import Counter, deque

# ---------------------------------------------------------------- constants

GAP_SECONDS = 30 * 60          # silence-gap threshold
RETRY_MIN = 3                  # consecutive same-tool errors => retry-loop
PERM_MIN = 3                   # permission denials per session => thrash
TEXT_CAP = 16384               # chars of each text block scanned for markers
SNIPPET_LEN = 160              # --show-text snippet cap (scan)
SLICE_SNIPPET_LEN = 120        # --show-text snippet cap (slice)

# Error markers on tool results (used when is_error is absent).
TOOLERR_RE = re.compile(
    r"(?i)(\berror\b\s*:|exception\b|traceback \(most recent call last\)"
    r"|command not found|no such file or directory|permission denied"
    r"|\bfatal:|\bpanic:|\benoent\b|\betimedout\b|\beconnrefused\b"
    r"|tool_use_error|tool ran without output or error|was blocked"
    r"|operation not permitted|is not recognized as)"
)

# Permission denial detection is STRUCTURAL, like LIMIT_RE, not a
# substring scan. Verified false-positive sources of the old phrase list:
# (a) documentation/prose ABOUT permissions in message text (quoted
#     detector phrases, /permissions docs, scanner output echoed into
#     tool results), (b) the boilerplate warning attached to every
#     cross-session peer message ("... if the peer says it was denied
#     permission for an action ..."), and (c) ALLOW decisions ("Allowed
#     by auto mode classifier"). None of those are denials.
#
# Tier 1 -- denial results. The harness writes a denial AS the tool
# result: a tool_result block with is_error=true whose text STARTS with
# one of the verbatim denial texts (observed at position 0 across every
# verified denial in the reference corpus; add a sentinel only with an
# observed denial to back it):
#   "Permission for this action was denied by the Claude Code auto mode
#    classifier. Reason: ..."                       (classifier denial)
#   "The user doesn't want to proceed with this tool use. The tool use
#    was rejected ..."                              (user rejection)
# Successful tool results (is_error false/absent) never qualify, which
# excludes file reads and scanner output that merely QUOTE a denial.
PERM_RESULT_RE = re.compile(
    r"^(?:Permission for this action was denied by"
    r"|The user (?:doesn'?t|does not) want to proceed with this tool use)"
)

# Tier 2 -- first-person denial reports in FREE text only (peer
# messages, their queue-operation enqueue records, assistant prose):
# active-voice "<...> classifier denied <target>". Tool-result content
# is never tier-2 scanned, and a match immediately preceded by a quote
# character is a mention, not a report (e.g. a status update quoting
# 'permission classifier denied the curl').
PERM_REPORT_RE = re.compile(r"(?i)(?:permission )?classifier denied\b")
PERM_QUOTES = "'\"`“”‘’„«»"

# API dead-end markers (session-fatal API/harness errors).
API_RE = re.compile(
    r"(?i)(\bapi error\b|start a new session|overloaded_error"
    r"|internal server error|invalid_request_error|prompt is too long"
    r"|context window exceeded|no conversation found|connection error\b)"
)

# Usage-limit markers: only the two texts the harness injects verbatim,
# anchored at the very start of the node text. Observed ground truth in
# real transcripts:
#   - type=user, isMeta=true, message.content is a plain string
#     "[Usage limit approaching. Checkpoint now: ...]" (turn companion)
#   - type=user, isMeta=true, origin.kind=auto-continuation,
#     "Your claude.ai usage limit has reset. Continue the task ..."
#   - type=queue-operation, top-level content string with the same
#     reset text (the enqueue record of that auto-continuation)
# Conversational mentions (prose about limits, quoted sentinels inside
# tool results or task prompts) are excluded structurally: the marker is
# only applied to isMeta user turns and non-message entries whose text
# starts with one of these sentinels (see parse_node).
LIMIT_RE = re.compile(
    r"^(?:\[?Usage limit approaching\."
    r"|Your claude\.ai usage limit has reset\.)"
)

# Signature normalization: strip paths, ids, hex, numbers.
_RE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|/)[\w.\-~@+]+(?:[\\/][\w.\-~@+]+)+")
_RE_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_RE_HEX = re.compile(r"\b[0-9a-fA-F]{7,}\b")
_RE_NUM = re.compile(r"\d+")
_RE_WS = re.compile(r"\s+")
_RE_CTRL = re.compile(r"[\x00-\x1f\x7f]")

# A successful Read/file result: cat -n style "<lineno>\t..." content.
# Its text is file source, not tool output, so error words inside it
# (e.g. "InvalidOperationException" in C#) are not tool errors.
_RE_CATN = re.compile(r"^\s{0,8}\d+\t")

DETECTOR_GATE = ("retry-loop", "permission-thrash", "api-dead-end",
                 "limit-interrupt")


# ------------------------------------------------------------------ helpers

def normalize_signature(text):
    """Collapse an error text to a stable cluster key: first meaningful
    line with paths, uuids, hex runs, and numbers replaced."""
    t = text.strip()
    for ln in t.splitlines():
        ln = ln.strip()
        if ln:
            t = ln
            break
    t = t[:240]
    t = _RE_PATH.sub("<path>", t)
    t = _RE_UUID.sub("<id>", t)
    t = _RE_HEX.sub("<hex>", t)
    t = _RE_NUM.sub("<n>", t)
    t = _RE_WS.sub(" ", t)
    return t[:160]


def sanitize_snippet(text, cap):
    t = _RE_CTRL.sub(" ", text)
    t = _RE_WS.sub(" ", t).strip()
    return t[:cap]


def parse_ts(v):
    if not isinstance(v, str) or len(v) < 19:
        return None
    try:
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(v).timestamp()
    except ValueError:
        return None


def fmt_ts(epoch):
    if epoch is None:
        return "-"
    return datetime.datetime.fromtimestamp(
        epoch, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d%s" % (n, unit)) if unit == "B" else ("%.1f%s" % (n, unit))
        n /= 1024.0
    return "%dB" % n


def fmt_dur(seconds):
    seconds = int(seconds)
    if seconds < 3600:
        return "%dm%02ds" % (seconds // 60, seconds % 60)
    return "%dh%02dm" % (seconds // 3600, (seconds % 3600) // 60)


def iter_texts(content):
    """Yield text pieces of a message/tool_result content value."""
    if isinstance(content, str):
        yield content
    elif isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                t = b.get("text")
                if isinstance(t, str):
                    yield t


def iter_jsonl(path):
    """Stream (line_no, byte_offset, raw_bytes) from a file. Never loads
    the whole file; tolerates missing trailing newline."""
    offset = 0
    line_no = 0
    with open(path, "rb", buffering=1 << 20) as f:
        for raw in f:
            line_no += 1
            yield line_no, offset, raw
            offset += len(raw)


def path_error(p):
    """Explain why a path is unusable ('' if it is a regular file/dir)."""
    if os.path.exists(p):
        return "not a regular file or directory: %s" % p
    return "no such file or directory: %s" % p


def collect_files(paths):
    """Expand args into a sorted list of .jsonl files. Returns (files,
    error_messages)."""
    files = []
    errors = []
    for p in paths:
        p = os.path.expanduser(p)
        if os.path.isfile(p):
            files.append(p)
        elif os.path.isdir(p):
            for root, dirs, names in os.walk(p):
                dirs.sort()
                for name in sorted(names):
                    if name.endswith(".jsonl"):
                        files.append(os.path.join(root, name))
        else:
            errors.append(path_error(p))
    # de-dupe, keep deterministic order
    seen = set()
    uniq = []
    for f in files:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq, errors


# ------------------------------------------------------------- node parsing

class Node(object):
    """Lightweight per-line signature (no message text retained unless
    show_text asked for a snippet)."""
    __slots__ = ("line", "offset", "size", "etype", "role", "ts",
                 "tools", "results", "markers", "meaningful", "snippet",
                 "perm")

    def __init__(self):
        # Annotations are for type checkers only; function-body annotations are
        # never evaluated at runtime, so the 3.9 floor is unaffected.
        self.line = 0
        self.offset = 0
        self.size = 0
        self.etype = "?"
        self.role: "str | None" = None
        self.ts: "float | None" = None
        self.tools = ()        # tool_use names on this node
        self.results = ()      # (tool_use_id, is_err, sig) per tool_result
        self.markers = ()      # marker classes found in text
        self.meaningful = False
        self.snippet: "str | None" = None
        self.perm: "str | None" = None   # "result" | "report" | None


def parse_node(entry, line_no, offset, size, show_text):
    """Build a Node signature from a decoded JSONL entry (a dict)."""
    node = Node()
    node.line = line_no
    node.offset = offset
    node.size = size
    etype = entry.get("type")
    node.etype = etype if isinstance(etype, str) else "?"
    node.ts = parse_ts(entry.get("timestamp"))

    if node.etype not in ("user", "assistant"):
        # Tolerate everything else (summary, system, attachment, ...) as
        # opaque timestamped filler; still scan a top-level string content
        # (free text: e.g. the queue-operation enqueue record of a peer
        # message reporting a denial).
        c = entry.get("content")
        if isinstance(c, str):
            markers = scan_markers(c[:TEXT_CAP], free_text=True)
            if "permission" in markers:
                node.perm = "report"
            # Harness injection records (e.g. queue-operation enqueue of
            # the usage-limit auto-continuation) carry the sentinel at
            # the start of their top-level content string.
            if LIMIT_RE.match(c):
                markers.append("limit")
            node.markers = tuple(markers)
        return node

    msg = entry.get("message")
    content = None
    if isinstance(msg, dict):
        role = msg.get("role")
        node.role = role if isinstance(role, str) else node.etype
        content = msg.get("content")
    else:
        node.role = node.etype

    tools = []
    results = []
    markers = set()
    first_text = None

    if isinstance(content, str):
        first_text = content
        markers.update(scan_markers(content[:TEXT_CAP], free_text=True))
        node.meaningful = bool(content.strip())
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_use":
                name = block.get("name")
                tools.append(name if isinstance(name, str) else "?")
                node.meaningful = True
            elif btype == "tool_result":
                rid = block.get("id") or block.get("tool_use_id")
                text = ""
                for t in iter_texts(block.get("content")):
                    text = t
                    break
                err_flag = block.get("is_error")
                is_err = err_flag is True
                # Fall back to text markers ONLY when is_error is absent;
                # an explicit false means the tool succeeded even if its
                # output happens to contain words like "exception".
                if err_flag is None and text and \
                        not _RE_CATN.match(text) and \
                        TOOLERR_RE.search(text[:TEXT_CAP]):
                    is_err = True
                # Tier-1 permission denial: the harness wrote the denial
                # AS this error result, sentinel at text start. Successful
                # results that merely quote a denial never qualify.
                if is_err and text and PERM_RESULT_RE.match(text):
                    markers.add("permission")
                    node.perm = "result"
                sig = normalize_signature(text) if (is_err and text) else None
                results.append((rid if isinstance(rid, str) else None,
                                is_err, sig))
                if text:
                    markers.update(scan_markers(text[:TEXT_CAP]))
                    if first_text is None:
                        first_text = text
                node.meaningful = True
            elif btype == "text":
                t = block.get("text")
                if isinstance(t, str) and t.strip():
                    if first_text is None:
                        first_text = t
                    markers.update(scan_markers(t[:TEXT_CAP],
                                                free_text=True))
                    node.meaningful = True

    # Harness-injected usage-limit turns are user entries flagged
    # isMeta=true whose text STARTS with the injected sentinel. Anything
    # else (agent prose, tool results, users quoting the sentinel) is a
    # conversational mention and never gets the limit marker.
    if node.etype == "user" and entry.get("isMeta") is True:
        inj_text = content if isinstance(content, str) else first_text
        if isinstance(inj_text, str) and LIMIT_RE.match(inj_text):
            markers.add("limit")

    if node.perm is None and "permission" in markers:
        node.perm = "report"
    node.tools = tuple(tools)
    node.results = tuple(results)
    node.markers = tuple(sorted(markers))
    if show_text and first_text:
        node.snippet = sanitize_snippet(first_text, SNIPPET_LEN)
    return node


def perm_report(text):
    """True when free text carries an unquoted first-person denial
    report ("... classifier denied <target>"). A match whose preceding
    character is a quote is a mention of the phrase, not a report."""
    for m in PERM_REPORT_RE.finditer(text):
        i = m.start()
        if i > 0 and text[i - 1] in PERM_QUOTES:
            continue
        return True
    return False


def scan_markers(text, free_text=False):
    # "limit" is NOT text-scanned here: it is structural (harness-injected
    # nodes only) and applied in parse_node via LIMIT_RE.match at text
    # start, so conversational mentions of limits never carry it.
    # "permission" is likewise structural: tier 1 (denial results) is
    # applied in parse_node on is_error tool_results via PERM_RESULT_RE
    # at text start; only tier 2 (denial reports) runs here, and only on
    # free text -- never on tool_result content, where quoted denials
    # from file reads and scanner output would drown the signal.
    found = []
    if free_text and perm_report(text):
        found.append("permission")
    if API_RE.search(text):
        found.append("api")
    return found


# ------------------------------------------------------------------- scan

class Aggregate(object):
    def __init__(self):
        self.files = 0
        self.bytes = 0
        self.lines = 0
        self.nodes = 0
        self.malformed = 0
        self.empty = 0
        self.entry_types = Counter()
        self.ts_min = None
        self.ts_max = None
        self.tool_uses = Counter()
        self.tool_errors = Counter()
        self.error_clusters = {}   # sig -> [count, example "file:line", offset]
        self.findings = {
            "retry-loop": [],
            "permission-thrash": [],
            "api-dead-end": [],
            "limit-interrupt": [],
            "silence-gap": [],
        }


def scan_file(path, agg, show_text):
    """One streaming pass: update aggregate + run per-session detectors."""
    pending_tools = {}   # tool_use_id -> tool name
    results_seq = []     # (tool, is_err, sig, line, offset, snippet)
    perm_hits = []       # (line, offset, sig)
    limit_hits = []      # (line, offset, node_index)
    node_index = 0
    last_meaningful = None   # (line, offset, node_index, node)
    prev_ts = None
    prev_ts_line = None
    file_lines = 0
    file_bytes = 0

    for line_no, offset, raw in iter_jsonl(path):
        file_lines += 1
        file_bytes += len(raw)
        stripped = raw.strip()
        if not stripped:
            agg.empty += 1
            continue
        if not stripped.startswith(b"{"):
            agg.malformed += 1
            continue
        try:
            entry = json.loads(stripped)
        except Exception:
            agg.malformed += 1
            continue
        if not isinstance(entry, dict):
            agg.malformed += 1
            continue

        node = parse_node(entry, line_no, offset, len(raw), show_text)
        agg.nodes += 1
        agg.entry_types[node.etype] += 1

        if node.ts is not None:
            if agg.ts_min is None or node.ts < agg.ts_min:
                agg.ts_min = node.ts
            if agg.ts_max is None or node.ts > agg.ts_max:
                agg.ts_max = node.ts
            if prev_ts is not None and node.ts - prev_ts > GAP_SECONDS:
                agg.findings["silence-gap"].append({
                    "file": path, "line": line_no, "offset": offset,
                    "gap": fmt_dur(node.ts - prev_ts),
                    "gap_seconds": int(node.ts - prev_ts),
                    "after_line": prev_ts_line,
                })
            prev_ts = node.ts
            prev_ts_line = line_no

        for name in node.tools:
            agg.tool_uses[name] += 1
        for rid, is_err, sig in node.results:
            tool = pending_tools.pop(rid, None) if rid else None
            if tool is None:
                tool = "?"
            if is_err:
                agg.tool_errors[tool] += 1
                if sig:
                    cluster = agg.error_clusters.get(sig)
                    if cluster is None:
                        agg.error_clusters[sig] = [
                            1, "%s:%d" % (path, line_no), offset]
                    else:
                        cluster[0] += 1
            results_seq.append((tool, is_err, sig, line_no, offset,
                                node.snippet))
        # register tool_use ids after consuming results (results reference
        # earlier uses, never this same node's)
        if node.tools and node.etype == "assistant":
            msg = entry.get("message")
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and \
                            block.get("type") == "tool_use":
                        bid = block.get("id")
                        name = block.get("name")
                        if isinstance(bid, str):
                            pending_tools[bid] = (
                                name if isinstance(name, str) else "?")

        if "permission" in node.markers:
            perm_hits.append((line_no, offset, node.perm,
                              node.snippet if show_text else None))
        # The limit marker is structural (parse_node sets it only on
        # harness-injected isMeta user turns and injection records like
        # queue-operation whose text starts with the sentinel), so every
        # marked node is a real interruption, never a mention.
        if "limit" in node.markers:
            limit_hits.append((line_no, offset, node_index,
                               node.snippet if show_text else None))
        if node.etype in ("user", "assistant") and node.meaningful:
            last_meaningful = (line_no, offset, node_index, node)
        node_index += 1

    agg.files += 1
    agg.lines += file_lines
    agg.bytes += file_bytes

    # --- detector: retry-loop -------------------------------------------
    i = 0
    n = len(results_seq)
    while i < n:
        tool, is_err = results_seq[i][0], results_seq[i][1]
        if is_err and tool != "?":
            j = i
            while j < n and results_seq[j][0] == tool and results_seq[j][1]:
                j += 1
            if j - i >= RETRY_MIN:
                sigs = Counter(s[2] for s in results_seq[i:j] if s[2])
                finding = {
                    "file": path, "line": results_seq[i][3],
                    "offset": results_seq[i][4], "tool": tool,
                    "count": j - i,
                    "signature": (sigs.most_common(1)[0][0]
                                  if sigs else "(no error text)"),
                }
                if show_text:
                    finding["snippet"] = next(
                        (s[5] for s in results_seq[i:j] if s[5]), None)
                agg.findings["retry-loop"].append(finding)
            i = j
        else:
            i += 1

    # --- detector: permission-thrash ------------------------------------
    if len(perm_hits) >= PERM_MIN:
        finding = {
            "file": path, "line": perm_hits[0][0],
            "offset": perm_hits[0][1], "count": len(perm_hits),
            "results": sum(1 for h in perm_hits if h[2] == "result"),
            "reports": sum(1 for h in perm_hits if h[2] == "report"),
            "last_line": perm_hits[-1][0],
        }
        if show_text:
            finding["snippet"] = next(
                (h[3] for h in perm_hits if h[3]), None)
        agg.findings["permission-thrash"].append(finding)

    # --- detector: api-dead-end -----------------------------------------
    if last_meaningful is not None:
        line_no, offset, idx, node = last_meaningful
        reason = None
        if "api" in node.markers:
            reason = "api-error"
        elif node.etype == "user" and node.results and \
                all(r[1] for r in node.results) and not node.tools:
            reason = "unhandled-tool-error"
        if reason:
            sig = None
            for rid, is_err, s in node.results:
                if s:
                    sig = s
                    break
            finding = {
                "file": path, "line": line_no, "offset": offset,
                "reason": reason,
                "signature": sig or "(marker on final node)",
            }
            if show_text:
                finding["snippet"] = node.snippet
            agg.findings["api-dead-end"].append(finding)

    # --- detector: limit-interrupt --------------------------------------
    last_idx = last_meaningful[2] if last_meaningful else -1
    for line_no, offset, idx, snippet in limit_hits:
        finding = {
            "file": path, "line": line_no, "offset": offset,
            "continued": idx < last_idx,
        }
        if show_text:
            finding["snippet"] = snippet
        agg.findings["limit-interrupt"].append(finding)


def render_md(agg, top, elapsed, show_text):
    out = []
    w = out.append
    w("# agentlog scan")
    w("")
    w("## Corpus")
    w("")
    w("- files (sessions): %d" % agg.files)
    w("- bytes: %s | lines: %d | nodes parsed: %d | malformed: %d | empty: %d"
      % (fmt_bytes(agg.bytes), agg.lines, agg.nodes, agg.malformed,
         agg.empty))
    w("- span: %s -> %s" % (fmt_ts(agg.ts_min), fmt_ts(agg.ts_max)))
    types = ", ".join("%s=%d" % (k, v)
                      for k, v in agg.entry_types.most_common(8))
    w("- entry types: %s" % (types or "-"))
    w("- scan time: %.1fs" % elapsed)
    w("")

    gate_total = sum(len(agg.findings[k]) for k in DETECTOR_GATE)
    w("## Findings (%d antipattern%s)" %
      (gate_total, "" if gate_total == 1 else "s"))
    w("")

    def table(header, rows):
        w("| " + " | ".join(header) + " |")
        w("|" + "|".join("---" for _ in header) + "|")
        for r in rows:
            w("| " + " | ".join(str(c).replace("|", "\\|") for c in r)
              + " |")
        w("")

    def with_text(header, rowfn):
        """Append a text column when --show-text is on."""
        if not show_text:
            return header, rowfn
        return (header + ["text"],
                lambda f: tuple(rowfn(f)) + (f.get("snippet") or "-",))

    def section(name, items, header, rowfn):
        header, rowfn = with_text(header, rowfn)
        shown = items[:top]
        more = len(items) - len(shown)
        title = "### %s (%d)" % (name, len(items))
        w(title)
        w("")
        if not items:
            w("none")
            w("")
            return
        table(header, [rowfn(f) for f in shown])
        if more > 0:
            w("... and %d more (raise --top or use --json)" % more)
            w("")

    section("retry-loop", agg.findings["retry-loop"],
            ["file:line", "offset", "tool", "consecutive errors",
             "signature"],
            lambda f: ("%s:%d" % (f["file"], f["line"]), f["offset"],
                       f["tool"], f["count"], f["signature"]))
    section("permission-thrash", agg.findings["permission-thrash"],
            ["file:line", "offset", "denials", "results", "reports",
             "last at line"],
            lambda f: ("%s:%d" % (f["file"], f["line"]), f["offset"],
                       f["count"], f["results"], f["reports"],
                       f["last_line"]))
    section("api-dead-end", agg.findings["api-dead-end"],
            ["file:line", "offset", "reason", "signature"],
            lambda f: ("%s:%d" % (f["file"], f["line"]), f["offset"],
                       f["reason"], f["signature"]))
    section("limit-interrupt", agg.findings["limit-interrupt"],
            ["file:line", "offset", "continued after"],
            lambda f: ("%s:%d" % (f["file"], f["line"]), f["offset"],
                       "yes" if f["continued"] else "no"))
    section("silence-gaps", agg.findings["silence-gap"],
            ["file:line", "offset", "gap"],
            lambda f: ("%s:%d" % (f["file"], f["line"]), f["offset"],
                       f["gap"]))

    w("## Error clusters (%d distinct)" % len(agg.error_clusters))
    w("")
    if agg.error_clusters:
        ranked = sorted(agg.error_clusters.items(),
                        key=lambda kv: (-kv[1][0], kv[0]))[:top]
        table(["count", "signature", "example"],
              [(c[0], sig, "%s @%d" % (c[1], c[2])) for sig, c in ranked])
    else:
        w("none")
        w("")

    w("## Hot tools")
    w("")
    if agg.tool_uses or agg.tool_errors:
        names = Counter()
        names.update(agg.tool_uses)
        for k, v in agg.tool_errors.items():
            names.setdefault(k, 0)
        ranked = sorted(names, key=lambda k2: (-agg.tool_uses[k2], k2))[:top]
        rows = []
        for name in ranked:
            uses = agg.tool_uses[name]
            errs = agg.tool_errors[name]
            rate = ("%.1f%%" % (100.0 * errs / uses)) if uses else "-"
            rows.append((name, uses, errs, rate))
        table(["tool", "uses", "errors", "error rate"], rows)
    else:
        w("none")
        w("")

    if not show_text:
        w("_message text withheld (privacy default); --show-text opts in,"
          " or drill down with `slice <file> <line>`_")
    return "\n".join(out)


def render_json(agg, top, elapsed, exit_code):
    clusters = sorted(agg.error_clusters.items(),
                      key=lambda kv: (-kv[1][0], kv[0]))
    obj = {
        "corpus": {
            "files": agg.files,
            "bytes": agg.bytes,
            "lines": agg.lines,
            "nodes": agg.nodes,
            "malformed": agg.malformed,
            "empty": agg.empty,
            "entry_types": dict(agg.entry_types),
            "span": [fmt_ts(agg.ts_min), fmt_ts(agg.ts_max)],
            "scan_seconds": round(elapsed, 2),
        },
        "findings": {
            "retry_loop": agg.findings["retry-loop"],
            "permission_thrash": agg.findings["permission-thrash"],
            "api_dead_end": agg.findings["api-dead-end"],
            "limit_interrupt": agg.findings["limit-interrupt"],
            "silence_gaps": agg.findings["silence-gap"],
        },
        "error_clusters": [
            {"signature": sig, "count": c[0], "example": c[1],
             "offset": c[2]} for sig, c in clusters[:top]
        ],
        "hot_tools": [
            {"tool": name, "uses": agg.tool_uses[name],
             "errors": agg.tool_errors.get(name, 0)}
            for name in sorted(set(agg.tool_uses) | set(agg.tool_errors),
                               key=lambda k: (-agg.tool_uses[k], k))
        ],
        "exit_code": exit_code,
    }
    return json.dumps(obj, indent=1)


def cmd_scan(args):
    files, errors = collect_files(args.paths)
    for e in errors:
        sys.stderr.write("agentlog: %s\n" % e)
    if errors:
        return 1
    if not files:
        sys.stderr.write("agentlog: no .jsonl files found under: %s\n"
                         % " ".join(args.paths))
        return 1

    agg = Aggregate()
    start = time.monotonic()
    for path in files:
        try:
            scan_file(path, agg, args.show_text)
        except OSError as exc:
            sys.stderr.write("agentlog: skipping %s: %s\n" % (path, exc))
    elapsed = time.monotonic() - start

    gate_total = sum(len(agg.findings[k]) for k in DETECTOR_GATE)
    exit_code = 2 if gate_total else 0
    if args.json:
        print(render_json(agg, args.top, elapsed, exit_code))
    else:
        print(render_md(agg, args.top, elapsed, args.show_text))
    return exit_code


# ------------------------------------------------------------------- slice

def summarize_node(line_no, offset, raw, show_text, mark):
    stripped = raw.strip()
    prefix = ">" if mark else " "
    base = "%s L%-6d @%-10d %s" % (prefix, line_no, offset,
                                   fmt_bytes(len(raw)).rjust(7))
    if not stripped:
        return base + "  (empty line)"
    if not stripped.startswith(b"{"):
        return base + "  (malformed: not JSON)"
    try:
        entry = json.loads(stripped)
    except Exception:
        return base + "  (malformed: bad JSON)"
    if not isinstance(entry, dict):
        return base + "  (non-object entry)"
    node = parse_node(entry, line_no, offset, len(raw), show_text)
    parts = [node.etype]
    if node.role and node.role != node.etype:
        parts.append("role=%s" % node.role)
    if node.ts is not None:
        parts.append(fmt_ts(node.ts))
    if node.tools:
        parts.append("tools=[%s]" % ",".join(node.tools))
    errs = [r for r in node.results if r[1]]
    if node.results:
        parts.append("results=%d%s" %
                     (len(node.results),
                      " (%d err)" % len(errs) if errs else ""))
    if node.markers:
        shown = [("permission:%s" % node.perm)
                 if (m == "permission" and node.perm) else m
                 for m in node.markers]
        parts.append("markers=[%s]" % ",".join(shown))
    line = base + "  " + " ".join(parts)
    if show_text and node.snippet:
        line += '  text:"%s"' % node.snippet[:SLICE_SNIPPET_LEN]
    elif errs and errs[0][2]:
        line += '  sig:"%s"' % errs[0][2]
    return line


def cmd_slice(args):
    path = os.path.expanduser(args.file)
    if not os.path.isfile(path):
        sys.stderr.write("agentlog: %s\n" % path_error(path))
        return 1
    target = args.line
    k = args.around
    lo, hi = max(1, target - k), target + k
    before = deque(maxlen=2 * k + 1)
    found = False
    for line_no, offset, raw in iter_jsonl(path):
        if line_no < lo:
            continue
        if line_no > hi:
            break
        before.append((line_no, offset, raw))
        if line_no == target:
            found = True
    if not found and not any(ln == target for ln, _, _ in before):
        sys.stderr.write("agentlog: %s has fewer than %d lines\n"
                         % (path, target))
        return 1
    print("%s : %d node(s) around line %d" % (path, len(before), target))
    for line_no, offset, raw in before:
        print(summarize_node(line_no, offset, raw, args.show_text,
                             line_no == target))
    return 0


# ------------------------------------------------------------------ bisect

def node_features(node):
    feats = []
    if node.role:
        feats.append("role:%s" % node.role)
    else:
        feats.append("type:%s" % node.etype)
    for t in node.tools:
        feats.append("tool:%s" % t)
    for m in node.markers:
        feats.append("err:%s" % m)
    for r in node.results:
        if r[1]:
            feats.append("err:tool-error")
            break
    return feats


def cosine_distance(a, b):
    if not a or not b:
        return 1.0
    dot = 0.0
    for k, v in a.items():
        if k in b:
            dot += v * b[k]
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 1.0
    return 1.0 - dot / (na * nb)


def cmd_bisect(args):
    path = os.path.expanduser(args.file)
    if not os.path.isfile(path):
        sys.stderr.write("agentlog: %s\n" % path_error(path))
        return 1
    if args.metric != "cohesion":
        sys.stderr.write("agentlog: unknown metric: %s\n" % args.metric)
        return 1

    feats = []   # (line, offset, feature list)
    for line_no, offset, raw in iter_jsonl(path):
        stripped = raw.strip()
        if not stripped.startswith(b"{"):
            continue
        try:
            entry = json.loads(stripped)
        except Exception:
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("type") not in ("user", "assistant"):
            continue
        node = parse_node(entry, line_no, offset, len(raw), False)
        if node.meaningful or node.tools or node.results:
            feats.append((line_no, offset, node_features(node)))

    window = max(5, min(25, len(feats) // 10))
    if len(feats) < 2 * window + 1:
        print("%s: only %d meaningful nodes; too few for boundary "
              "detection (need %d)" % (path, len(feats), 2 * window + 1))
        return 0

    # sliding window: distance between the feature mass before and after
    # each candidate boundary
    scores = []
    left = Counter()
    right = Counter()
    for _, _, fs in feats[:window]:
        left.update(fs)
    for _, _, fs in feats[window:2 * window]:
        right.update(fs)
    for i in range(window, len(feats) - window):
        scores.append((cosine_distance(left, right), i))
        if i + window < len(feats):
            # advance both windows by one node
            old = feats[i - window][2]
            left.subtract(old)
            left += Counter()          # drop zero/negative entries
            left.update(feats[i][2])
            right.subtract(feats[i][2])
            right += Counter()
            right.update(feats[i + window][2])

    scores.sort(key=lambda s: (-s[0], s[1]))
    picked = []
    for dist, i in scores:
        if any(abs(i - j) < window for _, j in picked):
            continue
        picked.append((dist, i))
        if len(picked) >= 5:
            break

    print("%s : top %d cohesion boundaries (window=%d nodes, %d "
          "meaningful nodes)" % (path, len(picked), window, len(feats)))
    for rank, (dist, i) in enumerate(picked, 1):
        line_no, offset, _ = feats[i]
        lc = Counter()
        rc = Counter()
        for _, _, fs in feats[max(0, i - window):i]:
            lc.update(fs)
        for _, _, fs in feats[i:i + window]:
            rc.update(fs)
        ltop = ",".join(k for k, _ in lc.most_common(3))
        rtop = ",".join(k for k, _ in rc.most_common(3))
        print("%d. line %d @%d  distance=%.3f  before=[%s] after=[%s]"
              % (rank, line_no, offset, dist, ltop, rtop))
    print("drill down: agentlog.py slice %s <line> --around 5" % path)
    return 0


# ------------------------------------------------------------------ ledger
#
# Workflow runs live in <session>/subagents/workflows/wf_<id>/ with a
# journal.jsonl ({"type":"started"|"result","agentId":...} per agent) and
# one agent-<agentId>.jsonl transcript per agent. The workflow runner also
# writes a state file <session>/workflows/wf_<id>.json; the ledger reads
# ONLY workflowName and per-agent labels from it (never promptPreview or
# result text) and computes every number from the transcripts.
#
# Token composition (verified against the runner's own counters on a
# 12-run / 87-agent reference corpus):
#   output    sum of final output_tokens per API message. Transcripts
#             append one entry per streaming batch, all carrying the same
#             message.id with cumulative usage snapshots; the LAST
#             snapshot per id is the final usage for that message.
#   in+cache  sum of final input_tokens + cache_creation_input_tokens +
#             cache_read_input_tokens per API message.
#   context   input + cache_creation + cache_read + output taken from the
#             FIRST recorded snapshot of the agent's LAST message: the
#             agent's final context-window footprint. This is the figure
#             the workflow runner reports as per-agent "tokens" (exact on
#             83/87 reference agents; the rest differ <1.5% because the
#             runner sampled a mid-stream snapshot the transcript does
#             not retain).
# Tool calls: distinct tool_use block ids across assistant entries
# (exact vs the runner's toolCalls on all 87 reference agents).

_AGENT_FILE_RE = re.compile(r"^agent-([A-Za-z0-9]+)\.jsonl$")


def _usage_int(usage, key):
    v = usage.get(key)
    return v if isinstance(v, int) else 0


def scan_agent_transcript(path):
    """One streaming pass over an agent transcript. Returns a stats dict;
    never retains message text."""
    final = {}          # message id -> latest usage snapshot
    first_snap = {}     # message id -> first usage snapshot
    order = []
    last_mid = None
    tool_ids = set()
    tool_unnamed = 0
    ts_min = None
    ts_max = None
    for _line_no, _offset, raw in iter_jsonl(path):
        stripped = raw.strip()
        if not stripped.startswith(b"{"):
            continue
        try:
            entry = json.loads(stripped)
        except Exception:
            continue
        if not isinstance(entry, dict):
            continue
        ts = parse_ts(entry.get("timestamp"))
        if ts is not None:
            if ts_min is None or ts < ts_min:
                ts_min = ts
            if ts_max is None or ts > ts_max:
                ts_max = ts
        if entry.get("type") != "assistant":
            continue
        msg = entry.get("message")
        if not isinstance(msg, dict):
            continue
        mid = msg.get("id")
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and \
                        block.get("type") == "tool_use":
                    bid = block.get("id")
                    if isinstance(bid, str):
                        tool_ids.add((mid, bid))
                    else:
                        tool_unnamed += 1
        usage = msg.get("usage")
        if isinstance(usage, dict) and isinstance(mid, str):
            if mid not in final:
                order.append(mid)
                first_snap[mid] = usage
            final[mid] = usage
            last_mid = mid
    out_tokens = 0
    in_cache = 0
    for mid in order:
        u = final[mid]
        out_tokens += _usage_int(u, "output_tokens")
        in_cache += (_usage_int(u, "input_tokens")
                     + _usage_int(u, "cache_creation_input_tokens")
                     + _usage_int(u, "cache_read_input_tokens"))
    ctx_tokens = 0
    if last_mid is not None:
        u = first_snap[last_mid]
        ctx_tokens = (_usage_int(u, "input_tokens")
                      + _usage_int(u, "cache_creation_input_tokens")
                      + _usage_int(u, "cache_read_input_tokens")
                      + _usage_int(u, "output_tokens"))
    return {
        "output_tokens": out_tokens,
        "in_cache_tokens": in_cache,
        "ctx_tokens": ctx_tokens,
        "tool_calls": len(tool_ids) + tool_unnamed,
        "messages": len(order),
        "ts_min": ts_min,
        "ts_max": ts_max,
    }


def _read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            obj = json.load(f)
    except (OSError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _run_labels(run_dir, run_id):
    """Labels + workflow name from the runner state file (numbers are
    never taken from it). State file: <session>/workflows/<run_id>.json
    for a run dir <session>/subagents/workflows/<run_id>."""
    state_path = os.path.normpath(os.path.join(
        run_dir, os.pardir, os.pardir, os.pardir,
        "workflows", run_id + ".json"))
    state = _read_json_file(state_path)
    labels = {}
    name = None
    if state:
        wn = state.get("workflowName")
        if isinstance(wn, str):
            name = wn
        prog = state.get("workflowProgress")
        if isinstance(prog, list):
            for e in prog:
                if isinstance(e, dict) and \
                        e.get("type") == "workflow_agent" and \
                        isinstance(e.get("agentId"), str) and \
                        isinstance(e.get("label"), str):
                    labels[e["agentId"]] = e["label"]
    return name, labels


def load_run(run_dir):
    """Aggregate one workflow run directory."""
    run_id = os.path.basename(os.path.normpath(run_dir))
    started = set()
    completed = set()
    journal = os.path.join(run_dir, "journal.jsonl")
    if os.path.isfile(journal):
        for _line_no, _offset, raw in iter_jsonl(journal):
            stripped = raw.strip()
            if not stripped.startswith(b"{"):
                continue
            try:
                entry = json.loads(stripped)
            except Exception:
                continue
            if not isinstance(entry, dict):
                continue
            aid = entry.get("agentId")
            if not isinstance(aid, str):
                continue
            if entry.get("type") == "started":
                started.add(aid)
            elif entry.get("type") == "result":
                completed.add(aid)
    name, labels = _run_labels(run_dir, run_id)
    agents = []
    for fname in sorted(os.listdir(run_dir)):
        m = _AGENT_FILE_RE.match(fname)
        if not m:
            continue
        aid = m.group(1)
        stats = scan_agent_transcript(os.path.join(run_dir, fname))
        label = labels.get(aid)
        if label is None:
            meta = _read_json_file(
                os.path.join(run_dir, "agent-%s.meta.json" % aid))
            if meta and isinstance(meta.get("agentType"), str):
                label = meta["agentType"]
        stats["agent_id"] = aid
        stats["label"] = label or "-"
        agents.append(stats)
    ts_min = min((a["ts_min"] for a in agents if a["ts_min"] is not None),
                 default=None)
    ts_max = max((a["ts_max"] for a in agents if a["ts_max"] is not None),
                 default=None)
    return {
        "run_id": run_id,
        "workflow": name or "-",
        "agents_started": len(started),
        "agents_completed": len(completed),
        "transcripts": len(agents),
        "output_tokens": sum(a["output_tokens"] for a in agents),
        "in_cache_tokens": sum(a["in_cache_tokens"] for a in agents),
        "ctx_tokens": sum(a["ctx_tokens"] for a in agents),
        "tool_calls": sum(a["tool_calls"] for a in agents),
        "ts_min": ts_min,
        "ts_max": ts_max,
        "agents": agents,
    }


def find_run_dirs(paths):
    """Expand args into a sorted, de-duped list of workflow run dirs. A
    run dir contains journal.jsonl or at least one agent-*.jsonl."""
    def is_run_dir(d):
        try:
            names = os.listdir(d)
        except OSError:
            return False
        return "journal.jsonl" in names or \
            any(_AGENT_FILE_RE.match(n) for n in names)

    runs = []
    errors = []
    for p in paths:
        p = os.path.expanduser(p)
        if not os.path.isdir(p):
            errors.append(path_error(p))
            continue
        if is_run_dir(p):
            runs.append(os.path.normpath(p))
            continue
        for root, dirs, _names in os.walk(p):
            dirs.sort()
            for d in list(dirs):
                full = os.path.join(root, d)
                if is_run_dir(full):
                    runs.append(os.path.normpath(full))
                    dirs.remove(d)   # never recurse into a run dir
    seen = set()
    uniq = []
    for r in runs:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq, errors


def match_outcome(outcomes, run_id):
    """Outcome keys may be the full run id or its short prefix
    (wf_8a76d8d8 matches wf_8a76d8d8-fd3)."""
    if run_id in outcomes:
        return outcomes[run_id]
    for key, val in outcomes.items():
        if run_id.startswith(key + "-") or key.startswith(run_id + "-"):
            return val
    return None


_OUTCOME_INTS = ("confirmed", "fixed", "tests_added", "mutants_killed")


def _outcome_findings(oc):
    """Findings an efficiency ratio can be taken over: confirmed review
    findings or applied fixes, whichever the run produced."""
    n = 0
    for k in ("confirmed", "fixed"):
        v = oc.get(k)
        if isinstance(v, int):
            n += v
    return n


def render_ledger_md(runs, outcomes):
    out = []
    w = out.append
    w("# agentlog ledger")
    w("")
    w("- runs: %d | agents: %d started, %d completed | tool calls: %d"
      % (len(runs),
         sum(r["agents_started"] for r in runs),
         sum(r["agents_completed"] for r in runs),
         sum(r["tool_calls"] for r in runs)))
    w("- tokens: output %s | input+cache %s | context %s"
      % ("{:,}".format(sum(r["output_tokens"] for r in runs)),
         "{:,}".format(sum(r["in_cache_tokens"] for r in runs)),
         "{:,}".format(sum(r["ctx_tokens"] for r in runs))))
    span_min = min((r["ts_min"] for r in runs if r["ts_min"] is not None),
                   default=None)
    span_max = max((r["ts_max"] for r in runs if r["ts_max"] is not None),
                   default=None)
    w("- span: %s -> %s" % (fmt_ts(span_min), fmt_ts(span_max)))
    w("")

    def table(header, rows):
        w("| " + " | ".join(header) + " |")
        w("|" + "|".join("---" for _ in header) + "|")
        for r in rows:
            w("| " + " | ".join(str(c).replace("|", "\\|") for c in r)
              + " |")
        w("")

    header = ["run", "workflow", "agents", "tools", "output tok",
              "in+cache tok", "ctx tok", "wall"]
    if outcomes is not None:
        header += ["conf", "fixed", "tests", "mutants", "tok/finding",
                   "note"]
    rows = []
    for r in runs:
        wall = "-"
        if r["ts_min"] is not None and r["ts_max"] is not None:
            wall = fmt_dur(r["ts_max"] - r["ts_min"])
        agents = "%d/%d" % (r["agents_started"], r["agents_completed"])
        row = [r["run_id"], r["workflow"], agents, r["tool_calls"],
               "{:,}".format(r["output_tokens"]),
               "{:,}".format(r["in_cache_tokens"]),
               "{:,}".format(r["ctx_tokens"]), wall]
        if outcomes is not None:
            oc = match_outcome(outcomes, r["run_id"]) or {}
            for k in _OUTCOME_INTS:
                v = oc.get(k)
                row.append(v if isinstance(v, int) else "-")
            n = _outcome_findings(oc)
            row.append("{:,}".format(int(round(r["ctx_tokens"] / n)))
                       if n else "-")
            note = oc.get("note")
            row.append(note if isinstance(note, str) else "-")
        rows.append(row)
    w("## Runs (sorted by context tokens)")
    w("")
    table(header, rows)

    for r in runs:
        w("## %s — %s" % (r["run_id"], r["workflow"]))
        w("")
        arows = []
        for a in sorted(r["agents"],
                        key=lambda a2: (-a2["ctx_tokens"], a2["agent_id"])):
            dur = "-"
            if a["ts_min"] is not None and a["ts_max"] is not None:
                dur = fmt_dur(a["ts_max"] - a["ts_min"])
            arows.append((a["agent_id"], a["label"],
                          "{:,}".format(a["output_tokens"]),
                          "{:,}".format(a["in_cache_tokens"]),
                          "{:,}".format(a["ctx_tokens"]),
                          a["tool_calls"], dur))
        if arows:
            table(["agent", "label", "output tok", "in+cache tok",
                   "ctx tok", "tools", "duration"], arows)
        else:
            w("no agent transcripts")
            w("")

    w("_tokens: output = final output_tokens summed per API message;"
      " in+cache = final input + cache_creation + cache_read summed per"
      " message; ctx = the agent's final context footprint"
      " (input+cache_creation+cache_read+output at its last message's"
      " first recorded snapshot), the figure the workflow runner reports"
      " as per-agent tokens. No prompt or message text is read._")
    return "\n".join(out)


def render_ledger_json(runs, outcomes):
    jruns = []
    for r in runs:
        jr = {
            "run_id": r["run_id"],
            "workflow": r["workflow"],
            "agents_started": r["agents_started"],
            "agents_completed": r["agents_completed"],
            "transcripts": r["transcripts"],
            "tool_calls": r["tool_calls"],
            "output_tokens": r["output_tokens"],
            "in_cache_tokens": r["in_cache_tokens"],
            "ctx_tokens": r["ctx_tokens"],
            "span": [fmt_ts(r["ts_min"]), fmt_ts(r["ts_max"])],
            "wall_seconds": (int(r["ts_max"] - r["ts_min"])
                             if r["ts_min"] is not None
                             and r["ts_max"] is not None else None),
            "agents": [
                {
                    "agent_id": a["agent_id"],
                    "label": a["label"],
                    "output_tokens": a["output_tokens"],
                    "in_cache_tokens": a["in_cache_tokens"],
                    "ctx_tokens": a["ctx_tokens"],
                    "tool_calls": a["tool_calls"],
                    "messages": a["messages"],
                    "duration_seconds": (int(a["ts_max"] - a["ts_min"])
                                         if a["ts_min"] is not None
                                         and a["ts_max"] is not None
                                         else None),
                } for a in r["agents"]
            ],
        }
        if outcomes is not None:
            oc = match_outcome(outcomes, r["run_id"])
            jr["outcomes"] = oc
            n = _outcome_findings(oc) if oc else 0
            jr["ctx_tokens_per_finding"] = (
                int(round(r["ctx_tokens"] / n)) if n else None)
        jruns.append(jr)
    obj = {
        "runs": jruns,
        "totals": {
            "runs": len(runs),
            "agents_started": sum(r["agents_started"] for r in runs),
            "agents_completed": sum(r["agents_completed"] for r in runs),
            "tool_calls": sum(r["tool_calls"] for r in runs),
            "output_tokens": sum(r["output_tokens"] for r in runs),
            "in_cache_tokens": sum(r["in_cache_tokens"] for r in runs),
            "ctx_tokens": sum(r["ctx_tokens"] for r in runs),
        },
        "token_composition": {
            "output_tokens": "final output_tokens summed per API message "
                             "(entries deduped by message.id, last usage "
                             "snapshot wins)",
            "in_cache_tokens": "final input_tokens + cache_creation_input_"
                               "tokens + cache_read_input_tokens summed "
                               "per API message",
            "ctx_tokens": "input + cache_creation + cache_read + output "
                          "from the first recorded snapshot of the "
                          "agent's last message (final context "
                          "footprint; matches the workflow runner's "
                          "per-agent tokens counter)",
        },
    }
    return json.dumps(obj, indent=1)


def cmd_ledger(args):
    outcomes = None
    if args.outcomes:
        opath = os.path.expanduser(args.outcomes)
        outcomes = _read_json_file(opath)
        if outcomes is None:
            sys.stderr.write("agentlog: unreadable outcomes json: %s\n"
                             % opath)
            return 1
    run_dirs, errors = find_run_dirs(args.paths)
    for e in errors:
        sys.stderr.write("agentlog: %s\n" % e)
    if errors:
        return 1
    if not run_dirs:
        sys.stderr.write("agentlog: no workflow run dirs (journal.jsonl "
                         "or agent-*.jsonl) found under: %s\n"
                         % " ".join(args.paths))
        return 1
    runs = [load_run(d) for d in run_dirs]
    runs.sort(key=lambda r: (-r["ctx_tokens"], r["run_id"]))
    if args.json:
        print(render_ledger_json(runs, outcomes))
    else:
        print(render_ledger_md(runs, outcomes))
    return 0


# -------------------------------------------------------------------- main

class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("agentlog: error: %s\n" % message)
        sys.exit(1)


def main(argv=None):
    parser = Parser(
        prog="agentlog.py",
        description="Deterministic streaming scanner for Claude Code JSONL "
                    "transcripts. Privacy default: never prints message "
                    "text; exit 2 means antipatterns were detected.")
    sub = parser.add_subparsers(dest="command")

    p_scan = sub.add_parser("scan", help="scan transcripts for antipatterns")
    p_scan.add_argument("paths", nargs="+",
                        help=".jsonl files or directories (recursed)")
    fmt = p_scan.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true",
                     help="machine-readable aggregate")
    fmt.add_argument("--md", action="store_true",
                     help="markdown aggregate (default)")
    p_scan.add_argument("--top", type=int, default=10, metavar="N",
                        help="rows per table (default 10)")
    p_scan.add_argument("--show-text", action="store_true",
                        help="opt in to <=160-char text snippets")

    p_slice = sub.add_parser("slice", help="print K nodes around a line")
    p_slice.add_argument("file")
    p_slice.add_argument("line", type=int)
    p_slice.add_argument("--around", type=int, default=3, metavar="K")
    p_slice.add_argument("--show-text", action="store_true",
                         help="opt in to <=120-char text snippets")

    p_bisect = sub.add_parser("bisect",
                              help="find topic/cohesion boundaries")
    p_bisect.add_argument("file")
    p_bisect.add_argument("--metric", default="cohesion",
                          choices=["cohesion"])

    p_ledger = sub.add_parser(
        "ledger", help="workflow efficiency ledger over wf_* run dirs")
    p_ledger.add_argument("paths", nargs="+",
                          help="workflow run dirs, workflows roots, or "
                               "project/session dirs (recursed)")
    lfmt = p_ledger.add_mutually_exclusive_group()
    lfmt.add_argument("--json", action="store_true",
                      help="machine-readable ledger")
    lfmt.add_argument("--md", action="store_true",
                      help="markdown ledger (default)")
    p_ledger.add_argument("--outcomes", metavar="JSON",
                          help="json mapping run-id -> {confirmed, fixed, "
                               "tests_added, mutants_killed, note} to "
                               "join efficiency ratios into the table")

    args = parser.parse_args(argv)
    if args.command == "scan":
        if args.top < 1:
            sys.stderr.write("agentlog: --top must be >= 1\n")
            return 1
        return cmd_scan(args)
    if args.command == "slice":
        if args.line < 1:
            sys.stderr.write("agentlog: line must be >= 1\n")
            return 1
        if args.around < 0:
            sys.stderr.write("agentlog: --around must be >= 0\n")
            return 1
        return cmd_slice(args)
    if args.command == "bisect":
        return cmd_bisect(args)
    if args.command == "ledger":
        return cmd_ledger(args)
    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
