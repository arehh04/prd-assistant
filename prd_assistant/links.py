"""Link HTTP calls found in tests and frontend code to extracted routes."""
import re
from pathlib import Path

from . import count, groups, paths
from .mask import line_of, mask

WILD = "{}"
BUCKETS = ("matched", "ambiguous", "unmatched", "dynamic")
INTERP_RE = re.compile(r"\$\{[^}]*\}|\{\$[^}]*\}|\{[^}]*\}")


class LinkError(RuntimeError):
    """The linker's own bookkeeping did not add up."""


def segments(path):
    path = path.split("?", 1)[0].split("#", 1)[0]
    path = INTERP_RE.sub(WILD, path)
    out = []
    for seg in path.strip("/").split("/"):
        if not seg:
            continue
        out.append(WILD if (WILD in seg or seg.startswith(":")) else seg)
    return tuple(out)


def _score(call_segs, route_segs):
    if len(call_segs) != len(route_segs):
        return None
    static = both = 0
    for c, r in zip(call_segs, route_segs):
        if c == WILD and r == WILD:
            both += 1
        elif c == WILD or r == WILD:
            continue
        elif c == r:
            static += 1
        else:
            return None
    return (static, both)


def _best(call_segs, method, routes, suffix=False):
    best, ids = None, []
    for r in routes:
        if method and r["method"] not in (method, "ALL"):
            continue
        if suffix and len(r["segs"]) < len(call_segs):
            continue
        route_segs = r["segs"][len(r["segs"]) - len(call_segs):] if suffix else r["segs"]
        score = _score(call_segs, route_segs)
        if score is None or (call_segs and score[0] == 0):
            continue  # a match must share at least one static segment (except the root path)
        if best is None or score > best:
            best, ids = score, [r["id"]]
        elif score == best:
            ids.append(r["id"])
    return ids


def match_call(call_segs, method, routes, prefix):
    call_segs = tuple(call_segs)
    if call_segs and all(s == WILD for s in call_segs):
        return "dynamic", [], False  # nothing static to match on
    ids = _best(call_segs, method, routes)
    via_prefix = False
    if not ids and call_segs and call_segs[0] == WILD:
        # a leading ${BASE_URL}-style segment stands for an unknown base path: match the end of the route
        ids = _best(call_segs[1:], method, routes, suffix=True)
    elif not ids and prefix:
        ids = _best(tuple(prefix) + call_segs, method, routes)
        via_prefix = bool(ids)
    if not ids:
        return "unmatched", [], False
    if len(ids) == 1:
        return "matched", ids, via_prefix
    return "ambiguous", ids, via_prefix


VERBS = "get|post|put|patch|delete"
GENERIC_RE = re.compile(r"\.(" + VERBS + r")\(")
PHP_JSON_RE = re.compile(r"\b(" + VERBS + r")Json\(")
PHP_THIS_RE = re.compile(r"\$this->(" + VERBS + r")\(")
PHP_JSON_METHOD_RE = re.compile(r"->json\(\s*(['\"])(GET|POST|PUT|PATCH|DELETE)\1\s*,")
FETCH_RE = re.compile(r"\bfetch\(")
LOOSE_RE = re.compile(r"(?:\.|\b)(?:" + VERBS + r")(?:Json)?\(")
ARG_RE = re.compile(r"\s*[fFrRbBuU]{0,2}(['\"`])")
METHOD_OPT_RE = re.compile(r"""\bmethod\s*:\s*['"](\w+)['"]""")
LANGUAGE_BY_SUFFIX = {".py": "py", ".php": "php", ".ts": "js", ".tsx": "js", ".js": "js", ".jsx": "js",
                      ".mjs": "js", ".cjs": "js", ".vue": "js"}


def language_of(rel):
    return LANGUAGE_BY_SUFFIX.get(Path(rel).suffix.lower())


def first_arg(text, pos):
    """Parse the first argument at `pos`: ("literal"|"concat"|"dynamic", value, end)."""
    m = ARG_RE.match(text, pos)
    if not m:
        return "dynamic", None, pos
    quote, start = m.group(1), m.end()
    j = start
    while j < len(text) and text[j] != quote:
        if text[j] == "\n" and quote != "`":
            return "dynamic", None, pos
        j += 2 if text[j] == "\\" else 1
    value = text[start:j]
    k = j + 1
    while k < len(text) and text[k] in " \t":
        k += 1
    if k < len(text) and text[k] in "+.":
        return "concat", value, j + 1
    return "literal", value, j + 1


def _call_text(blanked, code, open_pos):
    depth = 0
    for i in range(open_pos, len(blanked)):
        if blanked[i] == "(":
            depth += 1
        elif blanked[i] == ")":
            depth -= 1
            if depth == 0:
                return code[open_pos:i + 1]
    return code[open_pos:open_pos + 400]


def parse_calls(text, rel, side, language):
    hash_comments = language in ("py", "php")
    code = mask(text, hash_comments=hash_comments, blank_strings=False)
    blanked = mask(text, hash_comments=hash_comments)
    heads = []  # (start, args_pos, method, sure) ; sure = unambiguously an HTTP call
    if language in ("py", "js"):
        heads += [(m.start(), m.end(), m.group(1).upper(), False) for m in GENERIC_RE.finditer(code)]
    if language == "php":
        heads += [(m.start(), m.end(), m.group(1).upper(), True) for m in PHP_JSON_RE.finditer(code)]
        heads += [(m.start(), m.end(), m.group(1).upper(), False) for m in PHP_THIS_RE.finditer(code)]
        heads += [(m.start(), m.end(), m.group(2), True) for m in PHP_JSON_METHOD_RE.finditer(code)]
    if language == "js" and side == "frontend":
        heads += [(m.start(), m.end(), None, True) for m in FETCH_RE.finditer(code)]
    heads.sort(key=lambda h: (h[0], h[1]))

    calls, spans = [], []
    for start, args_pos, method, sure in heads:
        kind, value, _ = first_arg(code, args_pos)
        if kind == "literal":
            path, dynamic = value, False
            if "://" in path:
                continue
            if not path.startswith("/"):
                if not sure:
                    continue
                path = "/" + path
        elif kind == "concat":
            if not sure and not value.startswith("/"):
                continue
            path, dynamic = value, True
        else:
            if not sure:
                continue
            path, dynamic = None, True
        if method is None:
            found = METHOD_OPT_RE.search(_call_text(blanked, code, args_pos - 1))
            method = found.group(1).upper() if found else None
        calls.append({"side": side, "file": rel, "line": line_of(code, start),
                      "method": method, "raw": path, "dynamic": dynamic})
        spans.append((start, args_pos))

    lines = code.split("\n")
    ignored = []
    for m in LOOSE_RE.finditer(code):
        if any(s < m.end() and m.start() < e for s, e in spans):
            continue
        number = line_of(code, m.start())
        ignored.append({"file": rel, "line": number, "text": lines[number - 1].strip()[:120]})
    return calls, ignored


def frontend_roots(repo_root):
    roots = []
    for rel, full in count.iter_files(repo_root, (".json",), include_tests=True):
        if Path(rel).name != "package.json":
            continue
        text = count.read_text(full)
        if '"vue-router"' in text or re.search(r'"react-router(?:-dom)?"', text):
            parent = Path(rel).parent.as_posix()
            roots.append("" if parent == "." else parent)
    return roots


def collect_calls(repo_root, side):
    calls, ignored = [], []
    if side == "tests":
        files = [(rel, full) for rel, full in count.iter_files(repo_root, tuple(LANGUAGE_BY_SUFFIX), include_tests=True)
                 if paths.exclusion_reason(rel) == "test" and not rel.endswith(".vue")]
    else:
        roots = frontend_roots(repo_root)
        files = [(rel, full) for rel, full in count.iter_files(repo_root, tuple(LANGUAGE_BY_SUFFIX))
                 if language_of(rel) == "js" and any(r == "" or rel.startswith(r + "/") for r in roots)]
    for rel, full in files:
        language = language_of(rel)
        if language is None:
            continue
        found, skipped = parse_calls(count.read_text(full), rel, side, language)
        calls += found
        ignored += skipped
    return calls, ignored


def link(repo_root, facts):
    route_list = [{"id": r["id"], "method": r["method"], "segs": segments(r["path"])} for r in facts["routes"]]
    route_segs = {r["id"]: r["segs"] for r in route_list}
    prefix = tuple(groups.global_prefix([r["path"] for r in facts["routes"]]))
    out = {"schema": 1, "tests": None, "frontend": None, "calls": [],
           "routes": {r["id"]: {"http_tests": [], "frontend": []} for r in facts["routes"]}}
    for side in ("tests", "frontend"):
        calls, ignored = collect_calls(repo_root, side)
        totals = {"call_sites": len(calls), "matched": 0, "matched_via_prefix": 0, "ambiguous": 0,
                  "unmatched": 0, "dynamic": 0, "ignored_candidates": len(ignored)}
        for c in calls:
            if c["dynamic"]:
                bucket, ids, via = "dynamic", [], False
            else:
                bucket, ids, via = match_call(segments(c["raw"]), c["method"], route_list, prefix)
                if (bucket == "ambiguous" and side == "frontend" and c["method"] is None
                        and len({route_segs[i] for i in ids}) == 1):
                    bucket = "matched"  # same path, routes differ only by HTTP method
            totals[bucket] += 1
            if bucket == "matched" and via:
                totals["matched_via_prefix"] += 1
            if bucket == "matched":
                slot = "http_tests" if side == "tests" else "frontend"
                for rid in (ids if side == "frontend" else ids[:1]):
                    out["routes"][rid][slot].append({"file": c["file"], "line": c["line"]})
            out["calls"].append({"side": side, "file": c["file"], "line": c["line"], "method": c["method"],
                                 "raw": c["raw"], "bucket": bucket, "route_ids": ids})
        if sum(totals[b] for b in BUCKETS) != totals["call_sites"]:
            raise LinkError(f"{side}: buckets {totals} do not add up to the call-site total")
        out[side] = {"totals": totals, "ignored_sample": ignored[:20]}
    return out
