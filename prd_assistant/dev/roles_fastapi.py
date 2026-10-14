"""FastAPI: who may call a handler, from the bodies of its Depends(...) dependency functions."""
import ast
import re

from .pyast import http_exception, member, members

ROUTER_DEPS_RE = re.compile(r"APIRouter\([^)]*dependencies\s*=")


def _depends_in(expr):
    names = []
    for node in ast.walk(expr):
        if isinstance(node, ast.Call) and member(node.func) == "Depends" and node.args:
            name = member(node.args[0])
            if name:
                names.append(name)
    return names


def _depends_names(fn, include_decorators=True):
    names = []
    args = fn.args
    for default in list(args.defaults) + [d for d in args.kw_defaults if d is not None]:
        names += _depends_in(default)
    for arg in args.posonlyargs + args.args + args.kwonlyargs:
        if arg.annotation is not None:
            names += _depends_in(arg.annotation)
    if include_decorators:
        for dec in fn.decorator_list:
            if isinstance(dec, ast.Call):
                for kw in dec.keywords:
                    if kw.arg == "dependencies":
                        names += _depends_in(kw.value)
    return list(dict.fromkeys(names))


def _raises_status(body, code):
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Raise) and node.exc is not None:
                got = http_exception(node.exc)
                if got and got[0] == code:
                    return True
    return False


def _role_check(fn, consts):
    """Roles allowed by `if <x> not in/!= <roles>: raise HTTPException(403, ...)`, or None."""
    for node in ast.walk(fn):
        if not isinstance(node, ast.If) or not _raises_status(node.body, 403):
            continue
        test = node.test
        if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], (ast.NotIn, ast.NotEq)):
            allowed = members(test.comparators[0], consts)
            if allowed is not None:
                return allowed
    return None


def _analyze(name, idx, rel_hint, depth=3, seen=()):
    entries = idx.funcs.get(name, [])
    same = [e for e in entries if e[0] == rel_hint]
    pick = same or entries
    if len(pick) != 1 or depth == 0 or name in seen:
        return {"kind": "unknown", "why": f"dependency {name} could not be found or is ambiguous"}
    rel, fn = pick[0]
    here = f"{name} ({rel}:{fn.lineno})"
    inner = [_analyze(d, idx, rel, depth - 1, seen + (name,)) for d in _depends_names(fn, include_decorators=False)]
    allowed = _role_check(fn, idx.consts.get(rel, {}))
    if allowed is not None or _raises_status(fn.body, 401):
        kind = "roles" if allowed is not None else "signin"
        chain, guards = [here], [f"{rel}:{fn.lineno}"]
        for i in inner:
            if i["kind"] in ("roles", "signin"):
                chain += i["chain"]
                guards += i["guards"]
        return {"kind": kind, "roles": allowed, "chain": chain, "guards": guards}
    for i in inner:
        if i["kind"] in ("roles", "signin"):
            return {**i, "chain": [here] + i["chain"], "guards": [f"{rel}:{fn.lineno}"] + i["guards"]}
    return {"kind": "unknown", "why": f"dependency {name} has no recognised role or sign-in check"}


def _find_handler(tree, line):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno == line:
            return node
    return None


def read_roles(rel, tree, text, line, idx):
    source = f"{rel}:{line}"
    fn = _find_handler(tree, line) if tree is not None else None
    if fn is None:
        return {"status": "not_read", "roles": None, "authenticated": False, "via": [], "source": source,
                "reason": "the handler function was not found in its file"}
    notes = ["router-level dependencies are not followed"] if ROUTER_DEPS_RE.search(text) else []
    deps = _depends_names(fn)
    if not deps:
        return {"status": "undeclared", "roles": None, "authenticated": False, "via": [], "guards": [],
                "undeclared_means": "open", "notes": notes, "source": source}
    results = [_analyze(d, idx, rel) for d in deps]
    unknown = [r for r in results if r["kind"] == "unknown"]
    if unknown:
        return {"status": "not_read", "roles": None, "authenticated": False, "via": [], "source": source,
                "reason": "; ".join(r["why"] for r in unknown), "notes": notes}
    role_results = [r for r in results if r["kind"] == "roles"]
    guards = list(dict.fromkeys(g for r in results for g in r["guards"]))
    via = [" -> ".join(r["chain"]) for r in results]
    if role_results:
        roles = [x for x in role_results[0]["roles"] if all(x in r["roles"] for r in role_results[1:])]
        return {"status": "read", "roles": roles, "authenticated": True, "via": via, "guards": guards,
                "notes": notes, "source": source}
    return {"status": "read", "roles": None, "authenticated": True, "via": via, "guards": guards,
            "notes": notes, "source": source}
