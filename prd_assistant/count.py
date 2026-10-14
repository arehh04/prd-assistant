"""Independent route/screen counters. Shares no code with the CodeGraph extractor on purpose."""
import os
import re
from pathlib import Path

from . import paths
from .mask import line_of, mask, match_brace

SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", ".next", ".nuxt", ".venv", "venv",
             "__pycache__", ".codegraph", "coverage", "storage", ".idea", ".vscode"}
BACKEND_FRAMEWORKS = {"fastapi", "nestjs", "express", "laravel"}
SCREEN_FRAMEWORKS = {"vue-router", "react-router"}

FASTAPI_RE = re.compile(r"^[ \t]*@[\w.]+\.(?:get|post|put|patch|delete|options|head)\(", re.M)
NEST_RE = re.compile(r"^[ \t]*@(?:Get|Post|Put|Patch|Delete|Options|Head|All)\(", re.M)
EXPRESS_RE = re.compile(
    r"^[ \t]*[\w.]*(?:app|router|Router)\w*\.(?:get|post|put|patch|delete|options|head)\(\s*['\"`]", re.M)
LARAVEL_RE = re.compile(r"Route::(?:get|post|put|patch|delete|options)\s*\(")


_UNREADABLE = set()


def reset_unreadable():
    _UNREADABLE.clear()


def unreadable_paths():
    return sorted(_UNREADABLE)


def read_text(path):
    """Read a source file; an unreadable file is recorded (see unreadable_paths) instead of aborting."""
    try:
        return Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        _UNREADABLE.add(str(path))
        return ""


def iter_files(root, suffixes, include_tests=False):
    root = Path(root)
    suffixes = tuple(suffixes)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if not name.endswith(suffixes) or paths.is_secret_name(name):
                continue
            full = Path(dirpath) / name
            if not full.is_file():  # broken symlinks, FIFOs, odd entries named like source files
                continue
            rel = full.relative_to(root).as_posix()
            if not include_tests and paths.exclusion_reason(rel):
                continue
            yield rel, full


def detect_frameworks(root):
    found = set()
    for rel, full in iter_files(root, (".json", ".txt", ".toml"), include_tests=True):
        name = Path(rel).name
        is_manifest = (name in ("package.json", "composer.json", "pyproject.toml")
                       or (name.startswith("requirements") and name.endswith(".txt")))
        if not is_manifest:
            continue
        text = read_text(full)
        if name == "package.json":
            if '"@nestjs/core"' in text:
                found.add("nestjs")
            if re.search(r'"express"\s*:', text):
                found.add("express")
            if '"vue-router"' in text:
                found.add("vue-router")
            if re.search(r'"react-router(?:-dom)?"', text):
                found.add("react-router")
        elif name == "composer.json":
            if '"laravel/framework"' in text:
                found.add("laravel")
        elif (name.startswith("requirements") and name.endswith(".txt")) or name == "pyproject.toml":
            if re.search(r"(?i)(?<![\w-])fastapi(?![\w-])", text):
                found.add("fastapi")
    return found


def _scan(root, suffixes, regex, mask_kind=None):
    """Return {(rel_path, line)} for each regex hit. mask_kind: None, "plain" or "hash"."""
    hits = set()
    for rel, full in iter_files(root, suffixes):
        text = read_text(full)
        if mask_kind is not None:
            text = mask(text, hash_comments=(mask_kind == "hash"))
        for m in regex.finditer(text):
            hits.add((rel, line_of(text, m.start())))
    return hits


def _laravel_routes(root):
    hits = set()
    for rel, full in iter_files(root, (".php",)):
        if "/routes/" not in "/" + rel:
            continue
        text = mask(read_text(full), hash_comments=True)
        for m in LARAVEL_RE.finditer(text):
            hits.add((rel, line_of(text, m.start())))
    return hits


def independent_routes(root, frameworks):
    hits = set()
    if "fastapi" in frameworks:
        hits |= _scan(root, (".py",), FASTAPI_RE)
    if "nestjs" in frameworks:
        hits |= _scan(root, (".ts",), NEST_RE)
    if "express" in frameworks:
        hits |= _scan(root, (".js", ".mjs", ".cjs", ".ts"), EXPRESS_RE, mask_kind="plain")
    if "laravel" in frameworks:
        hits |= _laravel_routes(root)
    return hits


ROUTER_MARKERS = ("createRouter(", "createBrowserRouter(", "createHashRouter(", "createMemoryRouter(",
                  "RouteObject", "RouteRecordRaw")
PATH_KEY_RE = re.compile(r"\bpath\s*:\s*['\"`]")
CHILDREN_RE = re.compile(r"\bchildren\s*:")
JSX_PATH_RE = re.compile(r"\bpath\s*=\s*(?:\"[^\"]*\"|'[^']*'|\{\s*[\"'][^\"']*[\"']\s*\})")


def _enclosing_object(masked, pos):
    depth = 0
    for i in range(pos - 1, -1, -1):
        ch = masked[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            if depth == 0:
                return i
            depth -= 1
    return None


def _leaf_object_route_lines(text, masked):
    lines = set()
    for hit in PATH_KEY_RE.finditer(masked):
        start = _enclosing_object(masked, hit.start())
        if start is None:
            continue
        segment = masked[start:match_brace(masked, start) + 1]
        if CHILDREN_RE.search(segment):
            continue
        lines.add(line_of(text, hit.start()))
    return lines


def _leaf_jsx_route_lines(text, masked):
    lines = set()
    for m in re.finditer(r"<Route\b", masked):
        i, depth = m.end(), 0
        while i < len(masked):
            ch = masked[i]
            if ch in "{(":
                depth += 1
            elif ch in "})":
                depth -= 1
            elif ch == ">" and depth == 0 and masked[i - 1] != "=":
                break
            i += 1
        self_closing = masked[i - 1] == "/"
        if self_closing and JSX_PATH_RE.search(text[m.start():i + 1]):
            lines.add(line_of(text, m.start()))
    return lines


def independent_screens(root, frameworks):
    if not frameworks & SCREEN_FRAMEWORKS:
        return set()
    hits = set()
    for rel, full in iter_files(root, (".ts", ".tsx", ".js", ".jsx", ".mjs")):
        text = read_text(full)
        masked = mask(text)
        if any(marker in masked for marker in ROUTER_MARKERS):
            hits |= {(rel, n) for n in _leaf_object_route_lines(text, masked)}
        if rel.endswith((".tsx", ".jsx")) and "<Route" in masked:
            hits |= {(rel, n) for n in _leaf_jsx_route_lines(text, masked)}
    return hits
