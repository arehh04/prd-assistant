"""form_rules.json: request fields per route, form fields per screen, and limits that differ."""
from . import joins, rules_front, rules_laravel, rules_pydantic, zodschema
from .pyast import PyIndex, py_tree
from .source import read_source, split_source

STRINGY = {"string", "str", None}
NUMERIC = {"number", "integer", "numeric", "int", "float"}


def _empty(source, reason):
    return {"source": source, "fields": [], "not_read": [reason], "stack": None}


def _skipped(source, reason):
    """A route with no handler fact: nothing is known about its input, so it is not counted as input."""
    return {"source": source, "fields": [], "not_read": [], "skipped": reason, "stack": None}


def _compare(sid, rid, form, ep, kind, form_value, ep_value):
    return {"screen": sid, "endpoint": rid, "field": ep["name"], "kind": kind, "form_value": form_value,
            "endpoint_value": ep_value, "form_source": form["source"], "endpoint_source": ep["source"]}


def mismatches(forms, endpoints, joined):
    out = []
    for sid, form_rec in forms.items():
        for rid in joined.get(sid, []):
            ep_fields = {f["name"]: f for f in endpoints.get(rid, {}).get("fields", [])}
            for form in form_rec["fields"]:
                ep = ep_fields.get(form["field"])
                if ep is None:
                    continue
                pairs = []
                if ep.get("type") in STRINGY:
                    pairs += [("min_length", form.get("minlength"), ep.get("min")),
                              ("max_length", form.get("maxlength"), ep.get("max"))]
                if ep.get("type") in NUMERIC:
                    pairs += [("min", form.get("min"), ep.get("min")), ("max", form.get("max"), ep.get("max"))]
                for kind, form_value, ep_value in pairs:
                    if (isinstance(form_value, (int, float)) and isinstance(ep_value, (int, float))
                            and form_value != ep_value):
                        out.append(_compare(sid, rid, form, ep, kind, form_value, ep_value))
    return out


def _endpoint(route, repo_root, schemas, pyidx, texts):
    handler = route.get("handler")
    if not handler:
        return _skipped(route.get("source", ""), "the route has no handler fact")
    rel, line = split_source(handler["source"])
    if rel not in texts:
        texts[rel] = read_source(repo_root, rel)
    text = texts[rel]
    if text is None:
        return _empty(handler["source"], "the handler file could not be read")
    if rel.endswith((".ts", ".js")):
        return zodschema.read_request(rel, text, line, schemas)
    if rel.endswith(".py"):
        return rules_pydantic.read_request(rel, pyidx.trees.get(rel) or py_tree(text), line, route["path"], pyidx)
    if rel.endswith(".php"):
        return rules_laravel.read_request(rel, text, line, repo_root)
    return _empty(handler["source"], "no reader for this file type")


def build(repo_root, facts, ui, links_result):
    schemas = zodschema.SchemaIndex(repo_root).schemas
    pyidx = PyIndex(repo_root)
    texts, endpoints = {}, {}
    for route in facts["routes"]:
        try:
            endpoints[route["id"]] = _endpoint(route, repo_root, schemas, pyidx, texts)
        except Exception as exc:  # a hostile file must not stop the run
            endpoints[route["id"]] = _empty(route.get("source", ""), f"reader error: {type(exc).__name__}")
    forms = {}
    for sid, screen in ui["screens"].items():
        try:
            forms[sid] = rules_front.read_forms(repo_root, screen["files"], schemas)
        except Exception as exc:
            forms[sid] = {"fields": [], "schemas": [], "unnamed": 0, "error": type(exc).__name__}
    methods = {r["id"]: r["method"] for r in facts["routes"]}
    takes = [rid for rid, e in endpoints.items()
             if methods[rid] in ("POST", "PUT", "PATCH") or e["fields"] or e["not_read"]]
    unread = [rid for rid in takes if endpoints[rid]["not_read"]]
    joined = joins.screen_endpoints(ui, links_result, repo_root)
    return {"schema_version": 1, "endpoints": endpoints, "forms": forms,
            "mismatches": mismatches(forms, endpoints, joined),
            "counts": {"routes": len(endpoints), "takes_input": len(takes),
                       "read": len(takes) - len(unread), "not_read": len(unread)}}
