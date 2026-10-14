"""Acceptance-criteria candidates: the slice 3b facts reshaped into cited, labelled statements."""
import re

from .devguide import _who

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
                    "role_refused", subject, f"Role {r} is refused on {label}.",
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
