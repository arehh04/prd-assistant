"""Safe file reading and small parsing helpers shared by the developer-guide readers."""
import re
from pathlib import Path

from .. import count, paths
from ..mask import line_of, mask
from ..ui_text import _inside

DEV_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".vue", ".php", ".py")
MAX_FILE_BYTES = 1_000_000
MAX_INDEX_FILES = 4000
MAX_PAREN = 20_000


def read_source(repo_root, rel):
    """Text of a repo file, or None when it must not be read (secret, symlink, outside, oversize, odd type)."""
    full = Path(repo_root) / rel
    if (not str(rel).endswith(DEV_SUFFIXES) or full.is_symlink() or not full.is_file()
            or paths.is_secret_name(full.name) or not _inside(repo_root, full)):
        return None
    if full.stat().st_size > MAX_FILE_BYTES:
        count.mark_unreadable(full)
        return None
    return count.read_text(full)


def split_source(source):
    rel, _, line = source.rpartition(":")
    return rel, int(line)


def line_start(text, line):
    offset = 0
    for _ in range(line - 1):
        nxt = text.find("\n", offset)
        if nxt == -1:
            return len(text)
        offset = nxt + 1
    return offset


def paren_args(text, open_idx):
    """The text between the parenthesis at open_idx and its partner (string-aware), or None."""
    depth, quote, i = 0, None, open_idx
    limit = min(len(text), open_idx + MAX_PAREN)
    while i < limit:
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1:i]
        i += 1
    return None


def split_args(args):
    """Split on top-level commas (strings and brackets respected)."""
    parts, depth, quote, last, i = [], 0, None, 0, 0
    while i < len(args):
        c = args[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(args[last:i])
            last = i + 1
        i += 1
    parts.append(args[last:])
    return [p for p in parts if p.strip()]


CONST_RE = re.compile(
    r"\b(?:export\s+)?const\s+([A-Z][A-Za-z0-9_]*)\b(?:\s*:[^=\n]+)?\s*=\s*(?:new\s+Set\(\s*)?\[([^\]]{0,2000})\]", re.S)
ITEM_RE = re.compile(r"\.\.\.\s*([A-Za-z_]\w*)|(['\"])([^'\"]+)\2|([A-Za-z_]\w*)\.([A-Za-z_]\w*)")


def scan_consts(text):
    clean = mask(text, blank_strings=False)
    out = {}
    for m in CONST_RE.finditer(clean):
        out.setdefault(m.group(1), (m.group(2), line_of(clean, m.start())))
    return out


class ConstIndex:
    """Array constants (role lists) found in TypeScript sources; ambiguous names resolve to None."""

    def __init__(self, repo_root):
        self.defs = {}
        for n, (rel, _full) in enumerate(count.iter_files(repo_root, (".ts", ".tsx", ".js", ".vue"))):
            if n >= MAX_INDEX_FILES:
                break
            text = read_source(repo_root, rel)
            if text is None or "[" not in text:
                continue
            for name, (body, line) in scan_consts(text).items():
                self.defs.setdefault(name, []).append((body, rel, line))

    def _items(self, body, depth, local, local_rel):
        roles, via = [], []
        for m in ITEM_RE.finditer(body):
            if m.group(1):
                sub = self.resolve(m.group(1), depth - 1, local, local_rel)
                if sub is None:
                    return None
                roles += sub[0]
                via.append(f"{m.group(1)} ({sub[1]})")
            elif m.group(3) is not None:
                roles.append(m.group(3))
            else:
                roles.append(m.group(5))
        if re.search(r"[^\s,\[\]]", ITEM_RE.sub("", body)):
            return None   # something in the list is not a plain name or string (a call, a template): do not guess
        return list(dict.fromkeys(roles)), via

    def resolve(self, name, depth=3, local=None, local_rel=""):
        """(roles, 'file:line') for a constant, or None when unknown, ambiguous, cyclic or too deep."""
        if depth <= 0:
            return None
        if local and name in local:
            entries = [(local[name][0], local_rel, local[name][1])]
        else:
            entries = self.defs.get(name, [])
        results = []
        for body, rel, line in entries:
            got = self._items(body, depth, local, local_rel)
            if got is None:
                return None
            results.append((got[0], f"{rel}:{line}"))
        if not results or any(r[0] != results[0][0] for r in results):
            return None
        return results[0]

    def expand(self, expr, local=None, local_rel=""):
        """(roles, via) for a decorator/array argument text, or None if any part cannot be resolved."""
        expr = expr.strip()
        if re.fullmatch(r"[A-Za-z_]\w*", expr):
            got = self.resolve(expr, 3, local, local_rel)
            return None if got is None else (got[0], [f"{expr} ({got[1]})"])
        got = self._items(expr, 3, local, local_rel)
        return None if got is None else (got[0], got[1])
