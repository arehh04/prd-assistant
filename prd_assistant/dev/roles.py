"""roles.json: backend role per route, frontend role per screen, and where they disagree."""
import re

from . import joins, roles_fastapi, roles_front, roles_laravel, roles_nest
from .pyast import PyIndex, py_tree
from .source import ConstIndex, read_source, split_source


def _not_read(source, reason):
    return {"status": "not_read", "roles": None, "authenticated": False, "via": [], "source": source,
            "reason": reason}


def _norm(role):
    return re.sub(r"[\s-]+", "_", role.strip().lower())


def mismatches(screens, endpoints, joined):
    out = []
    for sid, rec in screens.items():
        if rec["status"] != "read" or rec["roles"] is None:
            continue
        screen_roles = {_norm(r): r for r in rec["roles"]}
        for rid in joined.get(sid, []):
            e = endpoints.get(rid)
            if not e or e["status"] != "read" or e["roles"] is None:
                continue
            allowed = {_norm(r) for r in e["roles"]}
            refused = sorted(v for k, v in screen_roles.items() if k not in allowed)
            if refused:
                out.append({"screen": sid, "endpoint": rid, "screen_roles": rec["roles"],
                            "endpoint_roles": e["roles"], "refused_roles": refused,
                            "detail": "these roles can open the screen but the endpoint it calls refuses them"})
    return out


class _Context:
    def __init__(self, repo_root):
        self.repo_root = repo_root
        self.index = ConstIndex(repo_root)
        self.aliases = roles_nest.build_aliases(repo_root)
        self.closed = roles_nest.fail_closed(repo_root)
        self.pyidx = PyIndex(repo_root)
        self._text = {}

    def text(self, rel):
        if rel not in self._text:
            self._text[rel] = read_source(self.repo_root, rel)
        return self._text[rel]


def _endpoint(route, ctx):
    handler = route.get("handler")
    if not handler:
        return _not_read(route.get("source", ""), "the route has no handler fact")
    rel, line = split_source(handler["source"])
    text = ctx.text(rel)
    if text is None:
        return _not_read(handler["source"], "the handler file could not be read")
    if rel.endswith((".ts", ".js")):
        rec = roles_nest.read_roles(rel, text, line, ctx.index, ctx.aliases, ctx.closed)
        rec["stack"] = "nestjs"
    elif rel.endswith(".py"):
        tree = ctx.pyidx.trees.get(rel) or py_tree(text)
        rec = roles_fastapi.read_roles(rel, tree, text, line, ctx.pyidx)
        rec["stack"] = "fastapi"
    elif rel.endswith(".php"):
        routes_text = ctx.text(route["file"])
        if routes_text is None:
            return _not_read(handler["source"], "the routes file could not be read")
        rec = roles_laravel.read_roles(route["file"], routes_text, route["line"])
        rec["checks"] = roles_laravel.handler_checks(text, line)
        rec["stack"] = "laravel"
    else:
        return _not_read(handler["source"], "no reader for this file type")
    return rec


def build(repo_root, facts, ui, links_result):
    ctx = _Context(repo_root)
    endpoints = {}
    for route in facts["routes"]:
        try:
            endpoints[route["id"]] = _endpoint(route, ctx)
        except Exception as exc:  # a hostile file must not stop the run
            endpoints[route["id"]] = _not_read(route.get("source", ""), f"reader error: {type(exc).__name__}")
    table = roles_front.nav_tables(repo_root, ctx.index)
    screens = {}
    for screen in facts["screens"]:
        try:
            screens[screen["id"]] = roles_front.screen_roles(screen, table, repo_root, ctx.index)
        except Exception as exc:
            screens[screen["id"]] = _not_read(screen.get("source", ""), f"reader error: {type(exc).__name__}")
    joined = joins.screen_endpoints(ui, links_result, repo_root)
    names = sorted({r for rec in list(endpoints.values()) + list(screens.values()) for r in (rec["roles"] or [])})
    statuses = [rec["status"] for rec in endpoints.values()]
    return {"schema_version": 1, "endpoints": endpoints, "screens": screens, "role_names": names,
            "joined": joined, "mismatches": mismatches(screens, endpoints, joined),
            "counts": {"routes": len(statuses), "read": statuses.count("read"), "public": statuses.count("public"),
                       "undeclared": statuses.count("undeclared"), "not_read": statuses.count("not_read")}}
