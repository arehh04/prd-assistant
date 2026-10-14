"""FastAPI request fields: path/query/header parameters and pydantic body models, read with ast."""
import ast

from .pyast import member

SKIP_ANNOTATIONS = {"Request", "Response", "BackgroundTasks", "WebSocket", "HTTPConnection"}
MARKERS = {"Query": "query", "Header": "header", "Cookie": "cookie", "Path": "path", "Body": "body"}
CONSTRAINTS = {"ge": "min", "gt": "min", "min_length": "min", "le": "max", "lt": "max", "max_length": "max",
               "pattern": "pattern", "regex": "pattern"}
_BUILTIN_CAPS = {"None", "True", "False", "Decimal", "Path", "Enum"}
KNOWN_TYPES = ("Optional", "Literal", "Annotated", "List", "Dict", "Union", "Any", "Sequence", "Set", "Tuple", "UUID")


def _num(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    return None


def _apply_call(f, call):
    """Apply Field(...)/Query(...) arguments to a field; return True if a default was given."""
    has_default = False
    if call.args:
        first = call.args[0]
        has_default = not (isinstance(first, ast.Constant) and first.value is Ellipsis)
    for kw in call.keywords:
        if kw.arg in ("default", "default_factory"):
            has_default = True
        elif kw.arg in CONSTRAINTS:
            key = CONSTRAINTS[kw.arg]
            f[key] = ast.unparse(kw.value) if key == "pattern" else _num(kw.value)
    return has_default


def _blank(name, location, source):
    return {"name": name, "location": location, "required": True, "type": None, "min": None, "max": None,
            "pattern": None, "format": None, "one_of": None, "messages": [], "raw": [], "source": source}


def _annotation_parts(f, ann):
    """Fill type / one_of / nullable from an annotation; return the Field(...) calls found in Annotated[...]."""
    calls = []
    if isinstance(ann, ast.Subscript):
        outer = member(ann.value)
        inner = ann.slice
        if outer == "Annotated" and isinstance(inner, ast.Tuple):
            calls = [e for e in inner.elts[1:] if isinstance(e, ast.Call)]
            _annotation_parts(f, inner.elts[0])
            return calls
        if outer == "Optional":
            f["nullable"] = True
            _annotation_parts(f, inner)
            return calls
        if outer == "Literal":
            elts = inner.elts if isinstance(inner, ast.Tuple) else [inner]
            f["one_of"] = [str(e.value) for e in elts if isinstance(e, ast.Constant)]
            f["type"] = "Literal"
            return calls
    if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
        f["nullable"] = f.get("nullable") or any(isinstance(s, ast.Constant) and s.value is None
                                                 for s in (ann.left, ann.right))
        _annotation_parts(f, ann.right if isinstance(ann.left, ast.Constant) else ann.left)
        return calls
    f["type"] = f["type"] or (ast.unparse(ann) if ann is not None else None)
    return calls


def _model_fields(cls_node, rel, idx, depth, notes):
    fields = []
    for base in cls_node.bases:
        name = member(base)
        entries = idx.classes.get(name, []) if name and name != "BaseModel" else []
        if depth > 0 and len(entries) == 1:
            fields += _model_fields(entries[0][1], entries[0][0], idx, depth - 1, notes)
    for stmt in cls_node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(member(d.func if isinstance(d, ast.Call) else d) in ("field_validator", "validator", "model_validator")
                   for d in stmt.decorator_list):
                if "validators are not read" not in notes:
                    notes.append("validators are not read")
        if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
            continue
        f = _blank(stmt.target.id, "body", f"{rel}:{stmt.lineno}")
        calls = _annotation_parts(f, stmt.annotation)
        has_default = stmt.value is not None
        if isinstance(stmt.value, ast.Call) and member(stmt.value.func) == "Field":
            has_default = _apply_call(f, stmt.value)
        for call in calls:
            if member(call.func) == "Field":
                has_default = _apply_call(f, call) or has_default
        f["required"] = not has_default
        f["raw"] = [ast.unparse(stmt)[:200]]
        fields.append(f)
    return fields


def _find_handler(tree, line):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno == line:
            return node
    return None


def _names(ann):
    return [n.id for n in ast.walk(ann) if isinstance(n, ast.Name)]


def read_request(rel, tree, line, route_path, idx):
    source = f"{rel}:{line}"
    out = {"source": source, "fields": [], "not_read": [], "notes": [], "stack": "fastapi"}
    fn = _find_handler(tree, line) if tree is not None else None
    if fn is None:
        out["not_read"].append("the handler function was not found in its file")
        return out
    args = fn.args
    positional = args.posonlyargs + args.args
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    pairs = list(zip(positional, defaults)) + list(zip(args.kwonlyargs, args.kw_defaults))
    for arg, default in pairs:
        if arg.arg in ("self", "cls"):
            continue
        marker = member(default.func) if isinstance(default, ast.Call) else None
        if marker == "Depends":
            continue
        ann = arg.annotation
        names = _names(ann) if ann is not None else []
        if any(n in SKIP_ANNOTATIONS for n in names):
            continue
        model = next((n for n in names if n in idx.classes), None)
        if model and marker not in ("Query", "Header", "Cookie", "Path"):
            entries = idx.classes[model]
            if len(entries) != 1:
                out["not_read"].append(f"model {model} is defined more than once")
                continue
            out["fields"] += _model_fields(entries[0][1], entries[0][0], idx, 2, out["notes"])
            continue
        in_path = f"{{{arg.arg}}}" in route_path
        if (isinstance(ann, ast.Name) and ann.id[:1].isupper() and ann.id not in KNOWN_TYPES
                and marker is None and not in_path and ann.id not in _BUILTIN_CAPS):
            out["not_read"].append(f"parameter {arg.arg} has the type {ann.id}, which is not a model found in the repo")
            continue
        location = MARKERS.get(marker, "path" if in_path else "query")
        f = _blank(arg.arg, location, f"{rel}:{arg.lineno}")
        if ann is not None:
            _annotation_parts(f, ann)
        has_default = default is not None
        if isinstance(default, ast.Call) and marker in MARKERS:
            has_default = _apply_call(f, default)
        f["required"] = not has_default or location == "path"
        f["raw"] = [ast.unparse(arg)[:200]]
        out["fields"].append(f)
    return out

