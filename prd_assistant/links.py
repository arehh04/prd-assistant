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


def _best(call_segs, method, routes):
    best, ids = None, []
    for r in routes:
        if method and r["method"] not in (method, "ALL"):
            continue
        score = _score(call_segs, r["segs"])
        if score is None:
            continue
        if best is None or score > best:
            best, ids = score, [r["id"]]
        elif score == best:
            ids.append(r["id"])
    return ids


def match_call(call_segs, method, routes, prefix):
    ids = _best(call_segs, method, routes)
    via_prefix = False
    if not ids and prefix:
        ids = _best(tuple(prefix) + tuple(call_segs), method, routes)
        via_prefix = bool(ids)
    if not ids:
        return "unmatched", [], False
    if len(ids) == 1:
        return "matched", ids, via_prefix
    return "ambiguous", ids, via_prefix
