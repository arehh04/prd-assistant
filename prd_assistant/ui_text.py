"""What a screen shows: component resolution and user-facing text. Pattern-based and read-only."""
import bisect
import os
import re
from pathlib import Path

from . import count, links, paths
from .mask import mask, match_brace

UI_SUFFIXES = (".tsx", ".jsx", ".vue", ".ts", ".js")
GUESS_SUFFIXES = (".tsx", ".ts", ".jsx", ".js", ".vue", ".mjs")
MAX_FILE_BYTES = 2_000_000
STRING_RE = re.compile(r"""(['"`])((?:\\.|(?!\1).)*)\1""", re.S)
VITE_ALIAS_RE = re.compile(r"""['"]([@~][\w-]*)['"]\s*:\s*([^\n]+)""")
TS_PATH_RE = re.compile(r'"([^"*]+)/\*"\s*:\s*\[\s*"([^"]+?)/?\*?"')
IMPORT_RE = re.compile(r"""^\s*import\s+(?:(?P<clause>[^'"]+?)\s+from\s+)?(['"])(?P<spec>[^'"]+)\2""", re.M)
LAZY_RE = re.compile(
    r"""\b(?:const|let|var)\s+([A-Z]\w*)\s*=\s*(?:React\.)?lazy\(\s*\(\)\s*=>\s*import\(\s*(['"`])(.*?)\2""", re.S)


def _abs(path):
    return Path(os.path.abspath(path))


def _alias_target(config_dir, rhs):
    for m in STRING_RE.finditer(rhs):
        value = m.group(2)
        if "://" in value or not re.fullmatch(r"[\w./@-]+", value):
            continue
        return _abs(Path(config_dir) / value.lstrip("/"))
    return None


def load_aliases(repo_root, start_dir):
    repo_root = _abs(repo_root)
    directory = _abs(repo_root / start_dir)
    directories = [directory]
    while directory != repo_root and repo_root in directory.parents:
        directory = directory.parent
        directories.append(directory)
    aliases = []
    for d in directories:
        for pattern in ("vite.config.*", "tsconfig*.json", "jsconfig.json"):
            for cfg in sorted(d.glob(pattern)):
                text = count.read_text(cfg)
                if cfg.name.startswith("vite"):
                    for m in VITE_ALIAS_RE.finditer(text):
                        target = _alias_target(d, m.group(2))
                        if target:
                            aliases.append((m.group(1), target))
                else:
                    for m in TS_PATH_RE.finditer(text):
                        aliases.append((m.group(1), _abs(d / m.group(2))))
    return list(dict.fromkeys(aliases))


def resolve_module(spec, base_dir, aliases, repo_root):
    """Repo-relative posix path of the file a module specifier points to, or None."""
    repo_root = _abs(repo_root)
    if spec.startswith("."):
        base = _abs(repo_root / base_dir / spec)
    else:
        base = None
        for prefix, target in aliases:
            if spec == prefix or spec.startswith(prefix + "/"):
                base = _abs(target / spec[len(prefix):].lstrip("/"))
                break
        if base is None:
            return None
    candidates = [base] + [Path(str(base) + s) for s in GUESS_SUFFIXES] + [base / ("index" + s) for s in GUESS_SUFFIXES]
    for cand in candidates:
        if cand.is_file() and not cand.is_symlink() and repo_root in cand.parents:
            return cand.relative_to(repo_root).as_posix()
    return None


def parse_imports(text):
    names, specs = {}, []
    for m in IMPORT_RE.finditer(text):
        spec = m.group("spec")
        specs.append(spec)
        clause = (m.group("clause") or "").strip()
        default = re.match(r"([A-Za-z_$][\w$]*)\s*(?:,|$)", clause)
        if default and not clause.startswith(("{", "*")):
            names[default.group(1)] = spec
        for named in re.findall(r"\{([^}]*)\}", clause):
            for part in named.split(","):
                part = part.strip()
                if part:
                    names[re.split(r"\s+as\s+", part)[-1].strip()] = spec
    for m in LAZY_RE.finditer(text):
        names[m.group(1)] = m.group(3)
        specs.append(m.group(3))
    return names, specs


TAG_START_RE = re.compile(r"(?<![\w$)\]])<([A-Za-z][\w.\-]*)")
WRAPPERS = {"Suspense", "Navigate", "Fragment", "Outlet", "ErrorBoundary", "Route", "Routes",
            "React.Fragment", "React.Suspense"}


class Source:
    """A file prepared for pattern scanning: comments blanked, offsets preserved."""

    def __init__(self, text):
        self.text = text
        self.code = mask(text, blank_strings=False, apostrophe_in_words=True)
        self.blanked = mask(text, apostrophe_in_words=True)
        self.starts = [0] + [m.end() for m in re.finditer("\n", text)]

    def line_at(self, pos):
        return bisect.bisect_right(self.starts, pos)


def tag_end(blanked, i):
    """Index of the '>' that closes the opening tag whose name ends at i, or -1."""
    depth, n = 0, len(blanked)
    while i < n:
        ch = blanked[i]
        if ch in "{(":
            depth += 1
        elif ch in "})":
            depth -= 1
        elif ch == ">" and depth <= 0 and blanked[i - 1] != "=":
            return i
        i += 1
    return -1


def close_paren(blanked, open_idx):
    depth = 0
    for i in range(open_idx, len(blanked)):
        if blanked[i] == "(":
            depth += 1
        elif blanked[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return len(blanked) - 1


def _enclosing_object(blanked, pos):
    depth = 0
    for i in range(pos - 1, -1, -1):
        ch = blanked[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            if depth == 0:
                return i
            depth -= 1
    return None


def _top_level_value(blanked, start, limit):
    depth, i = 0, start
    while i < limit:
        ch = blanked[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif ch == "," and depth == 0:
            break
        i += 1
    return i


def _component_tags(code, blanked, start, end):
    names, zones = [], []
    for m in TAG_START_RE.finditer(code, start, end):
        if any(a <= m.start() < b for a, b in zones):
            continue
        name = m.group(1)
        if name in WRAPPERS:
            zones.append((m.start(), max(tag_end(blanked, m.end()), m.start())))
            continue
        if name[:1].isupper() and name not in names:
            names.append(name)
    return names


def _object_components(src, obj, obj_end):
    names, direct = [], []
    segment = src.code[obj:obj_end + 1]
    for m in re.finditer(r"\b(element|Component|component)\s*:\s*", segment):
        start = obj + m.end()
        end = _top_level_value(src.blanked, start, obj_end)
        expr = src.code[start:end]
        if m.group(1) == "element" or expr.lstrip().startswith("<"):
            names += _component_tags(src.code, src.blanked, start, end)
            continue
        imp = re.search(r"import\(\s*(['\"`])(.*?)\1", expr, re.S)
        if imp:
            direct.append(imp.group(2))
            continue
        ident = re.match(r"\s*([A-Z][\w$]*)", expr)
        if ident:
            names.append(ident.group(1))
    return names, direct


def resolve_component(screen, src, aliases, repo_root):
    base_dir = Path(screen["file"]).parent.as_posix()
    result = {"status": "unresolved", "component_file": None, "candidates": [], "title": None}
    line = screen["line"]
    if not 1 <= line <= len(src.starts):
        return result
    line_start = src.starts[line - 1]
    line_end = src.starts[line] if line < len(src.starts) else len(src.code)
    names, direct = [], []
    tag = src.code.find("<Route", line_start, line_end)
    if tag != -1:
        end = tag_end(src.blanked, tag + len("<Route"))
        if end != -1:
            m = re.search(r"\b(?:element|Component)\s*=\s*\{", src.code[tag:end])
            if m:
                open_i = tag + m.end() - 1
                names = _component_tags(src.code, src.blanked, open_i + 1, match_brace(src.blanked, open_i))
    else:
        key = re.compile(r"\bpath\s*:").search(src.code, line_start, line_end)
        obj = _enclosing_object(src.blanked, key.start()) if key else None
        if obj is not None:
            obj_end = match_brace(src.blanked, obj)
            names, direct = _object_components(src, obj, obj_end)
            title = re.search(r"\btitle\s*:\s*(['\"`])(.*?)\1", src.code[obj:obj_end + 1])
            if title:
                result["title"] = {"text": " ".join(title.group(2).split()),
                                   "line": src.line_at(obj + title.start(2))}
    imports, _ = parse_imports(src.text)
    cands = []
    for name in dict.fromkeys(names):
        spec = imports.get(name)
        cands.append({"name": name, "file": resolve_module(spec, base_dir, aliases, repo_root) if spec else None})
    for spec in direct:
        cands.append({"name": Path(spec).stem, "file": resolve_module(spec, base_dir, aliases, repo_root)})
    hint = screen.get("component")
    if hint and hint.get("file"):
        cands = [{"name": hint["name"], "file": hint["file"]}]
    result["candidates"] = cands
    files = [c for c in cands if c["file"]]
    if files:
        result["component_file"] = files[0]["file"]
        result["status"] = "conditional" if len(cands) > 1 else "resolved"
    return result
