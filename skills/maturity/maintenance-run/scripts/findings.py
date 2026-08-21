#!/usr/bin/env python3
"""findings: deterministic root-cause dedupe for maintenance-run findings.

Mechanizes the mechanical share of the maintenance-run dedupe-arbiter step
(SKILL.md step 2). Prompt rules decay mid-context; a tool with an exit code
does not negotiate. The tool merges only what is provably mechanical --
root-cause signature overlap or title identity -- and hands the LLM
arbiter an explicit `ambiguous` list of flagged pairs. The arbiter's
judgment stays load-bearing at the edges: it may split a tool cluster and
may merge unflagged pairs, in both cases with stated code evidence
(SKILL.md step 2 owns those rules); the tool's floor is what it never
re-litigates.

Subcommands:
  dedupe <findings.json> [--json|--md] [--window N]
      Cluster raw findings by transitive closure over two join rules:
        (a) root-cause signature token-set overlap >= 1/2 (Jaccard,
            compared in exact integer arithmetic; signature = root_cause,
            falling back to title, normalized agentlog-style: lowercase,
            paths/uuids/hex-runs/numbers stripped, whitespace collapsed);
        (b) identical normalized title.
      Line proximity NEVER merges: replayed against maintenance run-002's
      arbiter ground truth, 4 of 7 same-file near-line pairs were distinct
      claims (the closest false pair sat 1 line apart while a true pair
      sat 14 apart), so no window separates them. Same-file pairs with
      lines within +-window (default 15) are FLAGGED on the `ambiguous`
      list instead, with their line distance.
      Output: clusters (chosen primary = highest severity, then longest
      evidence, then lowest index; max severity; merged categories and
      dimensions; the spanning merge edges with their reasons) plus the
      `ambiguous` list: different-cluster pairs flagged `file-window`
      (same file, lines within +-window) and/or `near-signature`
      (signature overlap >= 1/8 but below the 1/2 join threshold).
  validate <findings.json>
      Schema check with actionable per-field errors.

Input: a JSON array of finding objects, or {"findings": [...]}.
Required per finding: title, file, category (non-empty strings).
Optional: line (positive int or null), severity, root_cause, evidence
(strings), dimension/dimensions (string or array of strings).

Exit codes: 0 nothing merged (every cluster is a singleton; ambiguous
pairs may still exist -- read the output); 2 merges happened; 1 usage or
schema errors.

Deterministic: same input -> byte-identical output. No randomness, no
hash-order dependence (everything sorted), exact fractions for all
similarity comparisons. Python 3.9+, stdlib only.
"""

import argparse
import json
import re
import sys
from fractions import Fraction

# ---------------------------------------------------------------- constants

DEFAULT_WINDOW = 15      # +-lines for the same-file ambiguous flag
JOIN_SIM = Fraction(1, 2)    # rule (a): token-set Jaccard >= 1/2 joins
AMBIG_SIM = Fraction(1, 8)   # [1/8, 1/2): near-signature ambiguous flag
MIN_TOKENS = 3           # signatures with fewer tokens never fire (a)
MD_AMBIG_CAP = 50        # md shows at most this many ambiguous pairs

SEV_RANK = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}

# Signature normalization: same idea as agent-log-scan's agentlog.py --
# strip paths, uuids, hex runs, numbers; collapse whitespace.
_RE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|/)[\w.\-~@+]+(?:[\\/][\w.\-~@+]+)+")
_RE_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_RE_HEX = re.compile(r"\b[0-9a-fA-F]{7,}\b")
_RE_NUM = re.compile(r"\d+")
_RE_WS = re.compile(r"\s+")
_RE_TOKEN = re.compile(r"[a-z]+")

# Fixed stopword list (calibrated on the run-002 corpus; deterministic).
STOPWORDS = frozenset((
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is",
    "are", "its", "it", "as", "by", "with", "that", "this", "not", "no",
    "be", "can", "when", "so", "at", "via", "into", "from",
))


# ------------------------------------------------------------ normalization

def normalize_text(text):
    """Stable identity form of a text: lowercase, placeholder-substituted,
    whitespace-collapsed. Used for rule (c) title identity."""
    t = text.lower()
    t = _RE_PATH.sub("<path>", t)
    t = _RE_UUID.sub("<id>", t)
    t = _RE_HEX.sub("<hex>", t)
    t = _RE_NUM.sub("<n>", t)
    t = _RE_WS.sub(" ", t)
    return t.strip()


def token_set(text):
    """Signature token set: normalize with placeholders REMOVED (so the
    placeholder words never count as shared tokens), then keep lowercase
    word runs of length >= 2 minus stopwords."""
    t = text.lower()
    t = _RE_PATH.sub(" ", t)
    t = _RE_UUID.sub(" ", t)
    t = _RE_HEX.sub(" ", t)
    t = _RE_NUM.sub(" ", t)
    return frozenset(w for w in _RE_TOKEN.findall(t)
                     if len(w) > 1 and w not in STOPWORDS)


def normalize_file(path):
    """Normalized path segments: separators to '/', './' and empty
    segments dropped. Comparison is case-sensitive."""
    p = path.replace("\\", "/")
    segs = tuple(s for s in p.split("/") if s not in ("", "."))
    return segs


def same_file(a_segs, b_segs):
    """Two normalized paths name the same file when equal or when one is
    a whole-segment suffix of the other (absolute finder paths vs
    repo-relative paths for the same file)."""
    if not a_segs or not b_segs:
        return False
    if len(a_segs) == len(b_segs):
        return a_segs == b_segs
    short, long_ = (a_segs, b_segs) if len(a_segs) < len(b_segs) \
        else (b_segs, a_segs)
    return long_[-len(short):] == short


# --------------------------------------------------------------- validation

def _dims_of(entry):
    """Collect dimension values from 'dimension' and/or 'dimensions'."""
    out = []
    for key in ("dimension", "dimensions"):
        v = entry.get(key)
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            out.extend(x for x in v if isinstance(x, str))
    return out


def validate_findings(data):
    """Return (findings, errors). findings is the list when the container
    shape is usable (even if entries have errors), else None."""
    errors = []
    if isinstance(data, list):
        findings = data
    elif isinstance(data, dict):
        f = data.get("findings")
        if isinstance(f, list):
            findings = f
        else:
            got = ("object without a 'findings' array" if "findings"
                   not in data else "'findings' is %s, not an array"
                   % type(data["findings"]).__name__)
            errors.append("top-level: must be a JSON array of findings or "
                          "an object with a 'findings' array (got %s)" % got)
            return None, errors
    else:
        errors.append("top-level: must be a JSON array of findings or an "
                      "object with a 'findings' array (got %s)"
                      % type(data).__name__)
        return None, errors

    for i, entry in enumerate(findings):
        where = "findings[%d]" % i
        if not isinstance(entry, dict):
            errors.append("%s: must be an object (got %s)"
                          % (where, type(entry).__name__))
            continue
        for key in ("title", "file", "category"):
            v = entry.get(key)
            if not isinstance(v, str) or not v.strip():
                if key not in entry:
                    errors.append("%s.%s: required key is missing"
                                  % (where, key))
                else:
                    errors.append("%s.%s: must be a non-empty string "
                                  "(got %r)" % (where, key, v))
        line = entry.get("line")
        if line is not None and "line" in entry:
            if isinstance(line, bool) or not isinstance(line, int) \
                    or line < 1:
                errors.append("%s.line: must be a positive integer or null "
                              "(got %r)" % (where, line))
        for key in ("severity", "root_cause", "evidence"):
            v = entry.get(key)
            if v is not None and key in entry and not isinstance(v, str):
                errors.append("%s.%s: must be a string (got %s)"
                              % (where, key, type(v).__name__))
        for key in ("dimension", "dimensions"):
            v = entry.get(key)
            if v is None or key not in entry:
                continue
            ok = isinstance(v, str) or (
                isinstance(v, list) and all(isinstance(x, str) for x in v))
            if not ok:
                errors.append("%s.%s: must be a string or an array of "
                              "strings" % (where, key))
    return findings, errors


def load_input(path):
    """Return (findings, errors) for a findings.json path."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as exc:
        return None, ["cannot read %s: %s" % (path, exc)]
    except ValueError as exc:
        return None, ["%s is not valid JSON: %s" % (path, exc)]
    return validate_findings(data)


# --------------------------------------------------------------- clustering

class Prepared(object):
    __slots__ = ("index", "title", "ntitle", "file", "fsegs", "line",
                 "sev_rank", "severity", "evidence_len", "category",
                 "dims", "tokens")


def prepare(findings):
    prepped = []
    for i, e in enumerate(findings):
        p = Prepared()
        p.index = i
        p.title = e["title"]
        p.ntitle = normalize_text(e["title"])
        p.file = e["file"]
        p.fsegs = normalize_file(e["file"])
        line = e.get("line")
        p.line = line if isinstance(line, int) and not isinstance(
            line, bool) and line >= 1 else None
        sev = e.get("severity")
        p.severity = sev if isinstance(sev, str) else None
        p.sev_rank = SEV_RANK.get(sev.strip().lower(), 0) \
            if isinstance(sev, str) else 0
        ev = e.get("evidence")
        p.evidence_len = len(ev) if isinstance(ev, str) else 0
        p.category = e["category"]
        p.dims = _dims_of(e)
        sig_src = e.get("root_cause")
        if not (isinstance(sig_src, str) and sig_src.strip()):
            sig_src = e["title"]
        p.tokens = token_set(sig_src)
        prepped.append(p)
    return prepped


def pair_signature_sim(a, b):
    """Exact token-set Jaccard, or None when not computable (either
    signature is below MIN_TOKENS, or the union is empty)."""
    if len(a.tokens) < MIN_TOKENS or len(b.tokens) < MIN_TOKENS:
        return None
    union = len(a.tokens | b.tokens)
    if not union:
        return None
    return Fraction(len(a.tokens & b.tokens), union)


def pair_join_reasons(a, b, sim):
    """Deterministic join reasons for one pair (may be empty).

    Line proximity is deliberately NOT a join reason: on run-002's
    ground truth 4 of 7 same-file near-line pairs were distinct claims,
    and no window separates them (closest false pair 1 line apart, a
    true pair 14 apart). Near-line pairs are flagged ambiguous instead.
    """
    reasons = []
    if sim is not None and sim >= JOIN_SIM:
        reasons.append("signature")
    if a.ntitle and a.ntitle == b.ntitle:
        reasons.append("title")
    return reasons


def pair_window_distance(a, b, window):
    """Line distance when both findings carry a line in the same file
    and sit within +-window, else None."""
    if a.line is not None and b.line is not None \
            and same_file(a.fsegs, b.fsegs) \
            and abs(a.line - b.line) <= window:
        return abs(a.line - b.line)
    return None


def dedupe(findings, window):
    """Return (clusters, ambiguous, merges).

    clusters: list of dicts sorted by min member index.
    ambiguous: list of dicts, file-window flags first (distance asc),
    then near-signature flags (similarity desc), ties by (a, b).
    merges: how many findings were merged away (n - len(clusters)).
    """
    pp = prepare(findings)
    n = len(pp)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    merge_edges = []   # spanning edges: (i, j, reasons) that united roots
    flag_pairs = []    # (i, j, distance-or-None, frac-or-None) ambiguous

    for i in range(n):
        a = pp[i]
        for j in range(i + 1, n):
            b = pp[j]
            sim = pair_signature_sim(a, b)
            reasons = pair_join_reasons(a, b, sim)
            if reasons:
                ra, rb = find(i), find(j)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
                    merge_edges.append((i, j, reasons))
                continue
            dist = pair_window_distance(a, b, window)
            near = sim is not None and sim >= AMBIG_SIM
            if dist is not None or near:
                flag_pairs.append((i, j, dist, sim))

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    ordered = sorted(groups.values(), key=lambda ms: ms[0])

    clusters = []
    cluster_of = {}
    for pos, members in enumerate(ordered):
        cid = "D%d" % (pos + 1)
        for m in members:
            cluster_of[m] = cid
        primary = max(members,
                      key=lambda m: (pp[m].sev_rank, pp[m].evidence_len,
                                     -m))
        sev_best = max(members, key=lambda m: (pp[m].sev_rank, -m))
        edges = [[i, j, list(r)] for i, j, r in merge_edges
                 if find(i) == members[0]]
        clusters.append({
            "id": cid,
            "members": members,
            "primary": primary,
            "title": pp[primary].title,
            "file": pp[primary].file,
            "line": pp[primary].line,
            "severity": pp[sev_best].severity,
            "categories": sorted({pp[m].category for m in members}),
            "dimensions": sorted({d for m in members for d in pp[m].dims}),
            "member_titles": [pp[m].title for m in members],
            "merge_edges": edges,
        })

    def flag_key(t):
        i, j, dist, frac = t
        if dist is not None:      # file-window first, closest lines first
            return (0, dist, 0, i, j)
        return (1, 0, -frac, i, j)   # then near-signature, most similar

    ambiguous = []
    for i, j, dist, frac in sorted(flag_pairs, key=flag_key):
        if cluster_of[i] == cluster_of[j]:
            continue   # already joined transitively; nothing to judge
        reasons = []
        if dist is not None:
            reasons.append("file-window")
        if frac is not None and frac >= AMBIG_SIM:
            reasons.append("near-signature")
        ambiguous.append({
            "a": i,
            "b": j,
            "a_cluster": cluster_of[i],
            "b_cluster": cluster_of[j],
            "reasons": reasons,
            "line_distance": dist,
            "similarity": ("%d/%d" % (frac.numerator, frac.denominator)
                           if frac is not None else None),
            "pct": ((100 * frac.numerator) // frac.denominator
                    if frac is not None else None),
            "relation": ("same-file" if same_file(pp[i].fsegs, pp[j].fsegs)
                         else "cross-file"),
            "a_title": pp[i].title,
            "b_title": pp[j].title,
        })

    return clusters, ambiguous, n - len(clusters)


# ---------------------------------------------------------------- rendering

def render_json(path, n, window, clusters, ambiguous, merges, exit_code):
    obj = {
        "input": {"path": path, "findings": n},
        "params": {
            "window": window,
            "join_similarity": "%d/%d" % (JOIN_SIM.numerator,
                                          JOIN_SIM.denominator),
            "ambiguous_similarity": "%d/%d" % (AMBIG_SIM.numerator,
                                               AMBIG_SIM.denominator),
            "min_tokens": MIN_TOKENS,
        },
        "summary": {
            "clusters": len(clusters),
            "merges": merges,
            "multi_member_clusters": sum(
                1 for c in clusters if len(c["members"]) > 1),
            "ambiguous_pairs": len(ambiguous),
            "exit_code": exit_code,
        },
        "clusters": clusters,
        "ambiguous": ambiguous,
    }
    return json.dumps(obj, indent=1)


def _short(text, cap=90):
    t = text.replace("|", "\\|")
    return t if len(t) <= cap else t[:cap - 3] + "..."


def render_md(path, n, window, clusters, ambiguous, merges, exit_code):
    out = []
    w = out.append
    w("# findings dedupe")
    w("")
    w("- input: %s (%d findings) -> %d clusters (%d merged away)"
      % (path, n, len(clusters), merges))
    w("- params: join >= %s token-set overlap or identical title | "
      "flags: file-window +-%d lines, near-signature >= %s | "
      "min tokens %d"
      % (JOIN_SIM, window, AMBIG_SIM, MIN_TOKENS))
    w("- exit code: %d (%s)" % (exit_code,
                                "merges happened" if exit_code == 2
                                else "nothing merged"))
    w("")

    multi = [c for c in clusters if len(c["members"]) > 1]
    single = [c for c in clusters if len(c["members"]) == 1]

    w("## Merged clusters (%d)" % len(multi))
    w("")
    if not multi:
        w("none")
        w("")
    for c in multi:
        loc = "%s:%s" % (c["file"], c["line"] if c["line"] else "-")
        w("### %s: %s" % (c["id"], _short(c["title"])))
        w("")
        w("- primary: #%d @ %s | severity: %s | members: %s"
          % (c["primary"], loc, c["severity"] or "-",
             ", ".join("#%d" % m for m in c["members"])))
        if c["dimensions"]:
            w("- categories: %s | dimensions: %s"
              % (", ".join(c["categories"]), ", ".join(c["dimensions"])))
        else:
            w("- categories: %s" % ", ".join(c["categories"]))
        for m, title in zip(c["members"], c["member_titles"]):
            w("- #%d %s" % (m, _short(title)))
        for i, j, reasons in c["merge_edges"]:
            w("- joined #%d + #%d via %s" % (i, j, ", ".join(reasons)))
        w("")

    w("## Singletons (%d)" % len(single))
    w("")
    if single:
        w("| id | # | title | file:line |")
        w("|---|---|---|---|")
        for c in single:
            loc = "%s:%s" % (c["file"], c["line"] if c["line"] else "-")
            w("| %s | %d | %s | %s |"
              % (c["id"], c["primary"], _short(c["title"], 70), loc))
        w("")
    else:
        w("none")
        w("")

    w("## Ambiguous pairs (%d) -- arbiter judgment required" % len(ambiguous))
    w("")
    w("file-window = same file, lines within +-%d (line proximity is a "
      "lead, NOT proof: on run-002 ground truth 4 of 7 near-line pairs "
      "were distinct claims). near-signature = token-set overlap in "
      "[%s, %s). Judge each pair; the arbiter may also merge unflagged "
      "pairs with stated code evidence and may split any cluster above."
      % (window, AMBIG_SIM, JOIN_SIM))
    w("")
    if ambiguous:
        w("| a | b | clusters | why | dist | sim | relation | titles |")
        w("|---|---|---|---|---|---|---|---|")
        for p in ambiguous[:MD_AMBIG_CAP]:
            sim = ("%s (%d%%)" % (p["similarity"], p["pct"])
                   if p["similarity"] is not None else "-")
            dist = (str(p["line_distance"])
                    if p["line_distance"] is not None else "-")
            w("| #%d | #%d | %s vs %s | %s | %s | %s | %s | %s / %s |"
              % (p["a"], p["b"], p["a_cluster"], p["b_cluster"],
                 ", ".join(p["reasons"]), dist, sim, p["relation"],
                 _short(p["a_title"], 45), _short(p["b_title"], 45)))
        w("")
        if len(ambiguous) > MD_AMBIG_CAP:
            w("... and %d more (use --json for the full list)"
              % (len(ambiguous) - MD_AMBIG_CAP))
            w("")
    else:
        w("none")
        w("")
    return "\n".join(out)


# ------------------------------------------------------------------- main

def cmd_dedupe(args):
    findings, errors = load_input(args.findings)
    if errors:
        for e in errors:
            sys.stderr.write("findings: %s\n" % e)
        return 1
    missing_rc = sum(
        1 for e in findings
        if isinstance(e, dict) and not (
            isinstance(e.get("root_cause"), str)
            and e["root_cause"].strip()))
    if missing_rc:
        sys.stderr.write(
            "findings: note: %d/%d findings have no root_cause; the "
            "signature rule falls back to titles and under-merges -- "
            "cross-file duplicates of one root cause will surface only "
            "on the ambiguous list or via arbiter code evidence\n"
            % (missing_rc, len(findings)))
    clusters, ambiguous, merges = dedupe(findings, args.window)
    exit_code = 2 if merges else 0
    render = render_json if args.json else render_md
    sys.stdout.write(render(args.findings, len(findings), args.window,
                            clusters, ambiguous, merges, exit_code))
    sys.stdout.write("\n")
    return exit_code


def cmd_validate(args):
    findings, errors = load_input(args.findings)
    if errors:
        for e in errors:
            sys.stderr.write("findings: %s\n" % e)
        sys.stderr.write("findings: %d error%s in %s\n"
                         % (len(errors), "" if len(errors) == 1 else "s",
                            args.findings))
        return 1
    print("ok: %d finding%s, schema valid"
          % (len(findings), "" if len(findings) == 1 else "s"))
    return 0


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("findings: error: %s\n" % message)
        sys.exit(1)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = Parser(
        prog="findings.py",
        description="Deterministic root-cause dedupe for maintenance-run "
                    "findings. Merges only signature/title-identity "
                    "joins; same-file near-line pairs are flagged on the "
                    "`ambiguous` list for the LLM arbiter, never merged. "
                    "Exit 2 means merges happened.")
    sub = parser.add_subparsers(dest="command")

    p_d = sub.add_parser("dedupe", help="cluster raw findings")
    p_d.add_argument("findings", help="findings.json (array or "
                                      "{findings: [...]})")
    fmt = p_d.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true",
                     help="machine-readable output")
    fmt.add_argument("--md", action="store_true",
                     help="markdown output (default)")
    p_d.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                     metavar="N",
                     help="same-file line window for the file-window "
                          "ambiguous flag (default %d; never merges)"
                          % DEFAULT_WINDOW)

    p_v = sub.add_parser("validate", help="schema-check a findings file")
    p_v.add_argument("findings")

    args = parser.parse_args(argv)
    if args.command == "dedupe":
        if args.window < 0:
            sys.stderr.write("findings: --window must be >= 0\n")
            return 1
        return cmd_dedupe(args)
    if args.command == "validate":
        return cmd_validate(args)
    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
