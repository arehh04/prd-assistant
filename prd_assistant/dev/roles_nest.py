"""NestJS: who may call a handler, from @Roles()/@Public() and wrapper decorators."""
import re

from .. import count
from ..mask import line_of, mask
from .source import paren_args, read_source

ALIAS_RE = re.compile(r"\bconst\s+(\w+)\s*=\s*\(\s*\)\s*=>\s*Roles\(")
AS_RE = re.compile(r"\b(\w+)\s+as\s+(\w+)\b")
IMPORT_RE = re.compile(r"import\s*(?:type\s*)?\{[^}]{0,2000}\}")
DECORATOR_RE = re.compile(r"@(\w+)\s*\(")
CLASS_RE = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+\w+")
FAIL_CLOSED_RE = re.compile(r"!\s*\w+\s*\|\|\s*\w+\.length\s*===\s*0\s*\)\s*\{\s*throw")


def build_aliases(repo_root):
    out = {}
    for rel, _full in count.iter_files(repo_root, (".ts", ".js")):
        text = read_source(repo_root, rel)
        if text is None or "Roles(" not in text:
            continue
        clean = mask(text, blank_strings=False)
        rename = {b: a for a, b in AS_RE.findall(" ".join(IMPORT_RE.findall(clean)))}
        for m in ALIAS_RE.finditer(clean):
            args = paren_args(clean, m.end() - 1)
            if args is None:
                continue
            expr = re.sub(r"\b\w+\b", lambda w: rename.get(w.group(0), w.group(0)), args)
            out.setdefault(m.group(1), []).append((expr, rel, line_of(clean, m.start())))
    return {name: defs[0] for name, defs in out.items() if len(defs) == 1}


def fail_closed(repo_root):
    """'denied' when a global RolesGuard throws for a route that declares no roles."""
    has_global = guard_throws = False
    for rel, _full in count.iter_files(repo_root, (".ts",)):
        text = read_source(repo_root, rel)
        if text is None:
            continue
        if "APP_GUARD" in text and "RolesGuard" in text:
            has_global = True
        if "class RolesGuard" in text and FAIL_CLOSED_RE.search(mask(text, blank_strings=False)):
            guard_throws = True
    return "denied" if has_global and guard_throws else "unknown"


def _decorators_above(clean, line):
    lines = clean.splitlines()
    seg, i = [], line - 2
    while i >= 0:
        stripped = lines[i].strip()
        if stripped == "" or (stripped.endswith(("{", ";", "}")) and not stripped.startswith("@")):
            break
        seg.append((i + 1, lines[i]))
        i -= 1
    block = "\n".join(text for _, text in reversed(seg))
    first_line = seg[-1][0] if seg else line
    found = []
    for m in DECORATOR_RE.finditer(block):
        args = paren_args(block, m.end() - 1)
        found.append((m.group(1), args, first_line + block.count("\n", 0, m.start())))
    return found


def _class_line(clean, line):
    lines = clean.splitlines()
    for i in range(min(line, len(lines)) - 1, -1, -1):
        if CLASS_RE.match(lines[i]):
            return i + 1
    return None


def read_roles(rel, text, line, index, aliases, fail_closed="unknown"):
    clean = mask(text, blank_strings=False)
    method = _decorators_above(clean, line)
    cls = _class_line(clean, line)
    class_level = _decorators_above(clean, cls) if cls else []
    for decos in (method, class_level):
        for name, _args, dline in decos:
            if name == "Public":
                return {"status": "public", "roles": None, "authenticated": False, "via": ["@Public()"],
                        "source": f"{rel}:{dline}"}
        picked = [d for d in decos if d[0] == "Roles" or d[0] in aliases]
        if picked:
            name, args, dline = picked[-1]
            expr = args if name == "Roles" else aliases[name][0]
            got = None if expr is None else index.expand(expr)
            source = f"{rel}:{dline}"
            if got is not None and not got[0]:
                return {"status": "not_read", "roles": None, "authenticated": False, "via": [], "source": source,
                        "reason": f"@{name}() lists no roles (the guard treats that as no declaration)"}
            if got is None:
                return {"status": "not_read", "roles": None, "authenticated": False, "via": [], "source": source,
                        "reason": f"the role list behind @{name}() could not be resolved"}
            roles, via = got
            label = f"@{name}()" + (" -> " + ", ".join(via) if via else "")
            return {"status": "read", "roles": roles, "authenticated": False, "via": [label], "source": source}
    seen = sorted({d[0] for d in method + class_level})
    return {"status": "undeclared", "roles": None, "authenticated": False, "via": [], "decorators": seen,
            "undeclared_means": fail_closed, "source": f"{rel}:{line}"}
