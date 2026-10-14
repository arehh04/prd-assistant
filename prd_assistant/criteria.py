"""Acceptance-criteria candidates: the slice 3b facts reshaped into cited, labelled statements."""
import re

from . import groups
from .devguide import _field_text, _who

TOOL_VERSION = "1"
PROVENANCE = "Read from the code at the cited source; the application was not run."
MAX_TEXT = 1000

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "have", "has", "can", "should", "would", "will",
    "not", "are", "was", "let", "make", "need", "when", "what", "who", "how", "all", "any", "too", "many", "more",
    "than", "then", "also", "only", "they", "their", "them", "its", "our", "your", "but", "via", "per",
    "of", "to", "in", "is", "it", "an", "as", "at", "be", "by", "do", "if", "me", "my", "no", "on", "or", "so",
    "up", "us", "we", "id",
}
CAMEL_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+")


def stem(word):
    if len(word) <= 4:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("sses", "shes", "ches", "xes", "zes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def words(text):
    out = []
    for raw in re.findall(r"[A-Za-z0-9]+", str(text)):
        out += [p.lower() for p in CAMEL_RE.findall(raw)]
    return [stem(w) for w in out if len(w) >= 2 and w not in STOPWORDS]


def _norm_role(role):
    return re.sub(r"[\s-]+", "_", str(role).strip().lower())


def _label(route):
    return f"{route['method']} {route['path']}"


def _cand(kind, subject, text, facts, sources, trust, keys, role_keys=(), derived=False):
    return {"id": None, "kind": kind, "subject": subject, "text": text[:MAX_TEXT], "facts": facts,
            "sources": [s for s in dict.fromkeys(sources) if s], "derived": derived,
            "trust": list(dict.fromkeys([PROVENANCE] + list(trust))),
            "keys": sorted(set(keys)), "role_keys": sorted(set(role_keys))}


def _role_words(roles):
    return {w for r in roles for w in words(r)} | {_norm_role(r) for r in roles}


def _role_sentence(label, rec):
    status = rec["status"]
    if status == "read":
        if rec.get("roles"):
            text = f"{label} is allowed for roles {', '.join(rec['roles'])}."
        elif rec.get("authenticated"):
            text = f"{label} is allowed for any signed-in user."
        else:
            text = f"{label} has no role restriction that could be found."
        if rec.get("abilities"):
            text += f" It also requires the abilities: {', '.join(rec['abilities'])}."
        return text
    if status == "public":
        return f"{label} is open to anyone."
    if status == "not_read":
        return f"The roles for {label} could not be read ({rec.get('reason', 'no reason recorded')})."
    return f"{label}: {_who(rec)}."


def role_candidates(facts, roles):
    universe, seen = {}, {}
    for route in facts["routes"]:
        rec = roles["endpoints"].get(route["id"])
        if rec and rec["status"] == "read" and rec.get("roles"):
            stack = rec.get("stack") or "unknown"
            for r in rec["roles"]:
                if _norm_role(r) not in seen.setdefault(stack, set()):
                    seen[stack].add(_norm_role(r))
                    universe.setdefault(stack, []).append(r)
    cands = []
    for route in facts["routes"]:
        rec = roles["endpoints"].get(route["id"])
        if rec is None:
            continue
        label = _label(route)
        subject = {"type": "route", "id": route["id"], "label": label}
        trust = list(rec.get("notes") or [])
        if rec.get("abilities"):
            trust.append("ability checks also apply: " + ", ".join(rec["abilities"]))
        if rec["status"] == "not_read" and rec.get("reason"):
            trust.append(rec["reason"])
        keys = words(route["path"]) + words(route["method"])
        facts_rec = {k: rec.get(k) for k in ("status", "roles", "authenticated", "abilities", "via", "undeclared_means")}
        cands.append(_cand("role", subject, _role_sentence(label, rec), facts_rec,
                           [rec.get("source")] + list(rec.get("guards") or []), trust, keys,
                           _role_words(rec.get("roles") or [])))
        if rec["status"] == "read" and rec.get("roles"):
            stack = rec.get("stack") or "unknown"
            allowed = {_norm_role(r) for r in rec["roles"]}
            everyone = universe.get(stack, [])
            if len(everyone) < 2:
                continue
            for r in everyone:
                if _norm_role(r) in allowed:
                    continue
                cands.append(_cand(
                    "role_refused", subject, f"Role {r} is not in the role list of {label}, so it is treated as refused.",
                    {"role": r, "allowed": rec["roles"], "universe": list(everyone)}, [rec.get("source")],
                    ["derived: the roles seen on read endpoints of this stack are " + ", ".join(everyone)
                     + ", minus the roles this endpoint lists; the refusal's status and message were not read"] + trust,
                    keys, _role_words([r]), derived=True))
    return cands, universe


def screen_candidates(facts, roles):
    joined = roles.get("joined") or {}
    total, with_join = len(joined), sum(1 for v in joined.values() if v)
    out = []
    for screen in facts["screens"]:
        rec = (roles.get("screens") or {}).get(screen["id"])
        if not rec or rec["status"] != "read" or not rec.get("roles"):
            continue
        subject = {"type": "screen", "id": screen["id"], "label": f"screen {screen['path']}"}
        trust = [f"{with_join} of {total} screens were joined to endpoints, so screen/endpoint role mismatches "
                 "were only checked for those"]
        out.append(_cand("screen_roles", subject, f"Screen {screen['path']} is shown to roles {', '.join(rec['roles'])}.",
                         {"roles": rec["roles"], "via": rec.get("via")}, [rec.get("source")], trust,
                         words(screen["path"]), _role_words(rec["roles"])))
    return out


MAX_CANDIDATES = 20_000
KIND_ID = {"role": "ROLE", "role_refused": "REFUSED", "field": "FIELD", "request_unread": "UNREAD",
           "error": "ERROR", "screen_roles": "SCREEN", "mismatch": "MISMATCH"}
ERROR_TRUST = ("only messages in the handler, its guards and the functions it calls directly are read; "
               "messages raised deeper are not included")


def field_candidates(facts, rules):
    out = []
    for route in facts["routes"]:
        rec = rules["endpoints"].get(route["id"])
        if not rec:
            continue
        label = _label(route)
        subject = {"type": "route", "id": route["id"], "label": label}
        base_keys = words(route["path"]) + words(route["method"])
        notes = list(rec.get("notes") or [])
        for f in rec["fields"]:
            trust = ["hand-written input checks (if/else validation in the handler) are not read"] + notes
            if f.get("partial"):
                trust.append("part of the validation chain could not be parsed, so required/optional is unknown")
            if f.get("other"):
                trust.append("refinements and transforms (" + ", ".join(f["other"]) + ") are not evaluated")
            text = f"{label} takes {_field_text(f)}."
            if f.get("messages"):
                text += " Validation message: " + " / ".join(f"'{m}'" for m in f["messages"][:3]) + "."
            facts_rec = {k: v for k, v in f.items() if k != "raw"}
            out.append(_cand("field", subject, text, facts_rec, [f.get("source")], trust,
                             base_keys + words(f["name"]) + [w for m in f.get("messages", []) for w in words(m)]))
        for reason in rec.get("not_read") or []:
            out.append(_cand("request_unread", subject, f"Part of the request of {label} was not read: {reason}.",
                             {"reason": reason}, [rec.get("source")], notes, base_keys))
    return out


def error_candidates(facts, errors):
    by_route = {r["id"]: r for r in facts["routes"]}
    out, seen = [], set()
    for m in errors["messages"]:
        route = by_route.get(m["route"])
        if route is None or (m["route"], m["source"], m["text"]) in seen:
            continue
        seen.add((m["route"], m["source"], m["text"]))
        label = _label(route)
        status = "?" if m["status"] is None else m["status"]
        text = f"{label} returns {status} '{m['text']}'" + (f" (code {m['code']})." if m.get("code") else ".")
        trust = [ERROR_TRUST]
        if m["via"] == "guard":
            trust.append("this message comes from a guard or dependency shared by endpoints")
        elif m["via"] == "helper":
            trust.append("this message is raised in a helper called by the handler")
        out.append(_cand("error", {"type": "route", "id": route["id"], "label": label}, text,
                         {k: m.get(k) for k in ("status", "kind", "text", "via", "helper", "code")}, [m["source"]],
                         trust, words(route["path"]) + words(route["method"]) + words(m["text"])))
    return out


def mismatch_candidates(facts, roles, rules):
    routes = {r["id"]: r for r in facts["routes"]}
    paths = {s["id"]: s["path"] for s in facts["screens"]}
    out = []
    for m in roles.get("mismatches") or []:
        route, spath = routes.get(m["endpoint"]), paths.get(m["screen"])
        if route is None or spath is None:
            continue
        text = (f"Screen {spath} can be opened by role {', '.join(m['refused_roles'])} but the endpoint it calls "
                f"({_label(route)}) refuses {', '.join(m['refused_roles'])}.")
        srcs = [(roles["screens"].get(m["screen"]) or {}).get("source"),
                (roles["endpoints"].get(m["endpoint"]) or {}).get("source")]
        out.append(_cand("mismatch", {"type": "screen", "id": m["screen"], "label": f"screen {spath}"}, text, m, srcs,
                         ["needs a decision: " + m.get("detail", "")], words(spath) + words(route["path"]),
                         _role_words(m["refused_roles"])))
    for m in rules.get("mismatches") or []:
        route, spath = routes.get(m["endpoint"]), paths.get(m["screen"])
        if route is None or spath is None:
            continue
        text = (f"The form on screen {spath} allows {m['form_value']} ({m['kind']}) in {m['field']} but "
                f"{_label(route)} allows {m['endpoint_value']}.")
        out.append(_cand("mismatch", {"type": "screen", "id": m["screen"], "label": f"screen {spath}"}, text, m,
                         [m["form_source"], m["endpoint_source"]],
                         ["needs a decision: fields are matched by exact name across the endpoints joined to the screen"],
                         words(spath) + words(route["path"]) + words(m["field"])))
    return out


def build_bank(facts, roles, rules, errors, cap=MAX_CANDIDATES):
    role_c, universe = role_candidates(facts, roles)
    by_route = {}
    for c in role_c + field_candidates(facts, rules) + error_candidates(facts, errors):
        by_route.setdefault(c["subject"]["id"], []).append(c)
    ordered = []
    for route in facts["routes"]:
        group = by_route.get(route["id"], [])
        for kind in ("role", "role_refused", "field", "request_unread", "error"):
            ordered += [c for c in group if c["kind"] == kind]
    ordered += screen_candidates(facts, roles) + mismatch_candidates(facts, roles, rules)
    truncated = len(ordered) > cap
    ordered = ordered[:cap]
    counters = {}
    for c in ordered:
        counters[c["kind"]] = counters.get(c["kind"], 0) + 1
        c["id"] = f"C-{KIND_ID[c['kind']]}-{counters[c['kind']]:03d}"
    return {"schema_version": 1, "tool_version": TOOL_VERSION, "candidates": ordered, "universe": universe,
            "counts": dict(counters), "truncated": truncated,
            "groups": [{"id": g["id"], "key": g["key"], "routes": len(g["routes"])}
                       for g in groups.group_routes(facts["routes"])]}
