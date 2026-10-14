"""Python-source helpers on top of the standard `ast` module. Nothing here executes repo code."""
import ast
import re

from .. import count
from .source import MAX_INDEX_FILES, read_source


def py_tree(text):
    try:
        return ast.parse(text)
    except (SyntaxError, RecursionError, ValueError, MemoryError):
        return None


def member(node):
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def members(node, consts):
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        out = [member(e) for e in node.elts]
        return None if any(m is None for m in out) else out
    one = member(node)
    return None if one is None else [one]


def _module_consts(tree):
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if isinstance(node.value, (ast.Tuple, ast.List, ast.Set)):
                got = members(node.value, {})
                if got is not None:
                    out[node.targets[0].id] = got
    return out


class PyIndex:
    """Top-level functions, classes and tuple constants of every readable Python file."""

    def __init__(self, repo_root):
        self.trees, self.funcs, self.classes, self.consts = {}, {}, {}, {}
        for n, (rel, _full) in enumerate(count.iter_files(repo_root, (".py",))):
            if n >= MAX_INDEX_FILES:
                break
            text = read_source(repo_root, rel)
            tree = py_tree(text) if text else None
            if tree is None:
                continue
            self.trees[rel] = tree
            self.consts[rel] = _module_consts(tree)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.funcs.setdefault(node.name, []).append((rel, node))
                elif isinstance(node, ast.ClassDef):
                    self.classes.setdefault(node.name, []).append((rel, node))


STATUS_NAME_RE = re.compile(r"HTTP_(\d{3})_")


def _status(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    m = STATUS_NAME_RE.search(ast.unparse(node)) if node is not None else None
    return int(m.group(1)) if m else None


def http_exception(call):
    """(status, detail_node) of an HTTPException(...) call; None if `call` is something else."""
    if not isinstance(call, ast.Call) or member(call.func) != "HTTPException":
        return None
    kw = {k.arg: k.value for k in call.keywords if k.arg}
    status_node = kw.get("status_code", call.args[0] if call.args else None)
    detail = kw.get("detail", call.args[1] if len(call.args) > 1 else None)
    return _status(status_node), detail
