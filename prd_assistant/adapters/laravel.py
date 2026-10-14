"""Parse Laravel routes/api.php and routes/web.php. Plain verbs, group closures and prefix() only.

Anything else is reported as unsupported instead of being guessed at.
"""
import re
from pathlib import Path

from .. import count
from ..mask import line_of, mask, match_brace

ROUTE_RE = re.compile(r"Route::(get|post|put|patch|delete|options)\s*\(")
GROUP_RE = re.compile(r"->\s*group\s*\(\s*(?:static\s+)?function\b[^{;]*\{")
IMPORT_RE = re.compile(r"^\s*use\s+([\\\w]+)(?:\s+as\s+(\w+))?\s*;", re.M)
PREFIX_RE = re.compile(r"prefix\s*\(\s*['\"]([^'\"]*)['\"]\s*\)")
PATH_ARG_RE = re.compile(r"\s*(['\"])(.*?)\1", re.S)
HANDLER_ARRAY_RE = re.compile(r"\s*,\s*\[\s*([\\\w]+)::class\s*,\s*(['\"])(\w+)\2\s*\]")
HANDLER_INVOKABLE_RE = re.compile(r"\s*,\s*([\\\w]+)::class\b")
UNSUPPORTED_RE = re.compile(
    r"Route::(?:resource|apiResource|match|any|redirect|view|controller|fallback|singleton|apiSingleton|group)\s*\("
    r"|->\s*controller\s*\("
    r"|Route::\w+\([^;{}]*?\)\s*->\s*(?:get|post|put|patch|delete|options)\s*\("
)
API_PREFIX_RE = re.compile(r"apiPrefix\s*:\s*['\"]([^'\"]*)['\"]")


def _join(*parts):
    segments = [p.strip("/") for p in parts if p and p.strip("/")]
    return "/" + "/".join(segments)


def _imports(masked):
    table = {}
    for m in IMPORT_RE.finditer(masked):
        fqcn = m.group(1).lstrip("\\")
        table[m.group(2) or fqcn.rsplit("\\", 1)[-1]] = fqcn
    return table


def _qualified(class_ref, method, imports):
    ref = class_ref.lstrip("\\")
    first, _, rest = ref.partition("\\")
    if first in imports:
        fqcn = imports[first] + ("\\" + rest if rest else "")
    else:
        fqcn = ref
    namespace, _, short = fqcn.rpartition("\\")
    return f"{namespace}::{short}::{method}" if namespace else f"{short}::{method}"


def _groups(text, masked):
    groups = []
    for g in GROUP_RE.finditer(masked):
        open_i = g.end() - 1
        close_i = match_brace(masked, open_i)
        start = max(masked.rfind(";", 0, g.start()), masked.rfind("{", 0, g.start()),
                    masked.rfind("}", 0, g.start())) + 1
        groups.append((open_i, close_i, PREFIX_RE.findall(text[start:g.start()])))
    return groups


def parse_file(text, rel_file, api_prefix=""):
    masked = mask(text, hash_comments=True)
    imports = _imports(masked)
    groups = _groups(text, masked)
    routes, unsupported = [], []

    for m in UNSUPPORTED_RE.finditer(masked):
        unsupported.append({"file": rel_file, "line": line_of(text, m.start()),
                            "text": " ".join(masked[m.start():m.end()].split())[:60]})

    for m in ROUTE_RE.finditer(masked):
        line = line_of(text, m.start())
        path_arg = PATH_ARG_RE.match(text, m.end())
        if path_arg is None:
            unsupported.append({"file": rel_file, "line": line, "text": "non-literal route path"})
            continue
        prefixes = [p for (o, c, ps) in groups if o < m.start() < c for p in ps]
        full_path = _join(api_prefix, *prefixes, path_arg.group(2))
        handler = None
        array = HANDLER_ARRAY_RE.match(text, path_arg.end())
        if array:
            handler = _qualified(array.group(1), array.group(3), imports)
        else:
            invokable = HANDLER_INVOKABLE_RE.match(text, path_arg.end())
            if invokable:
                handler = _qualified(invokable.group(1), "__invoke", imports)
        method = m.group(1).upper()
        routes.append({
            "id": f"route:{rel_file}:{line}:{method}:{full_path}", "kind": "route",
            "method": method, "path": full_path, "file": rel_file, "line": line,
            "source": f"{rel_file}:{line}", "origin": "adapter:laravel",
            "handler_qualified_name": handler,
        })
    unsupported.sort(key=lambda u: u["line"])
    return routes, unsupported


def load(repo_root):
    repo_root = Path(repo_root)
    routes, unsupported = [], []
    for rel, full in count.iter_files(repo_root, (".php",)):
        parts = rel.split("/")
        if len(parts) < 2 or parts[-2] != "routes" or parts[-1] not in ("api.php", "web.php"):
            continue
        prefix = ""
        if parts[-1] == "api.php":
            prefix = "api"
            bootstrap = full.parent.parent / "bootstrap" / "app.php"
            if bootstrap.is_file():
                found = API_PREFIX_RE.search(count.read_text(bootstrap))
                if found:
                    prefix = found.group(1)
        r, u = parse_file(count.read_text(full), rel, prefix)
        routes += r
        unsupported += u
    return routes, unsupported
