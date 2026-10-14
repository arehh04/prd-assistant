"""Frontend role gating: path-to-roles tables (React nav lists) and Vue route meta.roles."""
import re

from .. import count
from ..mask import line_of, mask, match_brace
from .source import line_start, read_source, scan_consts

PATH_FIRST = re.compile(
    r"""\b(?:to|path)\s*:\s*(['"])(/[^'"]*)\1(?:[^{}]|\{[^{}]*\}){0,400}?\broles\s*:\s*(\[[^\]]*\]|[A-Za-z_]\w*)""", re.S)
ROLES_FIRST = re.compile(
    r"""\broles\s*:\s*(\[[^\]]*\]|[A-Za-z_]\w*)(?:[^{}]|\{[^{}]*\}){0,400}?\b(?:to|path)\s*:\s*(['"])(/[^'"]*)\2""", re.S)
ROLES_RE = re.compile(r"\broles\s*:\s*(\[[^\]]*\]|[A-Za-z_]\w*)")
MAX_TABLE_FILE = 300_000


def nav_tables(repo_root, index):
    entries, seen = [], set()
    for rel, _full in count.iter_files(repo_root, (".ts", ".tsx", ".js")):
        text = read_source(repo_root, rel)
        if text is None or len(text) > MAX_TABLE_FILE or "roles" not in text:
            continue
        clean = mask(text, blank_strings=False)
        local = scan_consts(text)
        found = [(m.group(2), m.group(3), m.start()) for m in PATH_FIRST.finditer(clean)]
        found += [(m.group(3), m.group(1), m.start()) for m in ROLES_FIRST.finditer(clean)]
        for path, expr, pos in found:
            got = index.expand(expr, local=local, local_rel=rel)
            key = (rel, path, tuple(got[0]) if got else None)
            if key in seen:
                continue
            seen.add(key)
            entries.append({"path": path, "roles": got[0] if got else None, "via": got[1] if got else [],
                            "file": rel, "line": line_of(clean, pos)})
    return entries


def _enclosing_object(masked, offset):
    depth = 0
    for i in range(min(offset, len(masked) - 1), -1, -1):
        c = masked[i]
        if c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                return i, match_brace(masked, i)
            depth -= 1
    return None


def screen_roles(screen, entries, repo_root, index):
    path = screen["path"]
    best = None
    for e in entries:
        to = e["path"]
        if path == to or (to != "/" and path.startswith(to.rstrip("/") + "/")):
            if best is None or len(to) > len(best["path"]):
                best = e
    if best is not None:
        source = f"{best['file']}:{best['line']}"
        if best["roles"] is None:
            return {"status": "not_read", "roles": None, "authenticated": False, "via": [], "source": source,
                    "reason": f"the roles listed for {best['path']} could not be resolved"}
        return {"status": "read", "roles": best["roles"], "authenticated": False,
                "via": [f"{best['path']} -> " + ", ".join(best["via"])] if best["via"] else [best["path"]],
                "source": source}
    text = read_source(repo_root, screen["file"])
    if text is not None:
        masked = mask(text)
        clean = mask(text, blank_strings=False)
        span = _enclosing_object(masked, line_start(text, screen["line"]))
        if span:
            block = clean[span[0]:span[1] + 1]
            block = block.split("children", 1)[0]
            m = ROLES_RE.search(block)
            if m:
                got = index.expand(m.group(1), local=scan_consts(text), local_rel=screen["file"])
                source = f"{screen['file']}:{line_of(clean, span[0] + m.start())}"
                if got is None:
                    return {"status": "not_read", "roles": None, "authenticated": False, "via": [], "source": source,
                            "reason": "the meta.roles list could not be resolved"}
                return {"status": "read", "roles": got[0], "authenticated": False,
                        "via": ["meta.roles"] + got[1], "source": source}
    return {"status": "not_read", "roles": None, "authenticated": False, "via": [],
            "source": f"{screen['file']}:{screen['line']}",
            "reason": "no role table entry or meta.roles covers this screen"}
