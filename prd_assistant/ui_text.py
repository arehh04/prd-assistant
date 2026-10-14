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
