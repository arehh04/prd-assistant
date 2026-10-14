"""Laravel: who may call a route, from middleware on the route statement and on enclosing groups."""
import re

from ..mask import match_brace, mask
from .source import line_start

GROUP_RE = re.compile(r"->\s*group\s*\(\s*(?:static\s+)?(?:function|fn)\b[^{;]*\{", re.S)
MW_RE = re.compile(r"middleware\(\s*(\[[^\]]*\]|'[^']*'|\"[^\"]*\")\s*\)", re.S)
STR_RE = re.compile(r"'([^']*)'|\"([^\"]*)\"")
CLS_RE = re.compile(r"([A-Za-z_\\][\w\\]*)::class")
CHECK_RE = re.compile(
    r"(?:\$this->authorize|Gate::(?:authorize|allows|denies|inspect)|->can|->cannot)\(\s*['\"]([\w.:-]+)['\"]")
UNDERSTOOD_NOT = ("permission:", "role_or_permission:", "ability:", "abilities:", "scope:", "scopes:")


def _names(chain):
    names = []
    for m in MW_RE.finditer(chain):
        arg = m.group(1)
        names += [a or b for a, b in STR_RE.findall(arg)]
        names += [c.split("\\")[-1] for c in CLS_RE.findall(arg)]
    return names


def _enclosing_chains(text, masked, offset):
    chains = []
    for m in GROUP_RE.finditer(masked):
        open_idx = m.end() - 1
        if open_idx < offset < match_brace(masked, open_idx):
            cut = max(masked.rfind(";", 0, m.start()), masked.rfind("{", 0, m.start()), masked.rfind("}", 0, m.start()))
            chains.append((cut, text[cut + 1:m.start()]))
    return [chain for _, chain in sorted(chains)]


def _statement(text, masked, line):
    start = line_start(text, line)
    end = masked.find(";", start)
    return text[start:(end + 1 if end != -1 else len(text))]


def read_roles(rel, text, line):
    masked = mask(text, hash_comments=True)
    clean = mask(text, hash_comments=True, blank_strings=False)
    offset = line_start(text, line)
    names = []
    for chain in _enclosing_chains(clean, masked, offset):
        names += _names(chain)
    names += _names(_statement(clean, masked, line))
    roles, abilities, signed_in, unknown = None, [], False, []
    for name in names:
        if name.startswith("role:"):
            wanted = [x.strip() for x in name[5:].split(",") if x.strip()]
            roles = wanted if roles is None else [x for x in roles if x in wanted]
        elif name.startswith("can:"):
            abilities.append(name[4:])
        elif name == "auth" or name.startswith("auth:"):
            signed_in = True
        elif name.startswith(UNDERSTOOD_NOT):
            unknown.append(name)
    source = f"{rel}:{line}"
    notes = [f"middleware not understood: {n}" for n in unknown]
    base = {"authenticated": signed_in or roles is not None, "middleware": list(dict.fromkeys(names)),
            "abilities": abilities, "notes": notes, "source": source}
    via = [f"middleware {n}" for n in dict.fromkeys(names) if n.startswith(("role:", "can:", "auth"))]
    if roles is not None:
        return {"status": "read", "roles": roles, "via": via, **base}
    if unknown:
        return {"status": "not_read", "roles": None, "via": [], "reason": "; ".join(notes), **base}
    if signed_in or abilities:
        return {"status": "read", "roles": None, "via": via, **base}
    return {"status": "undeclared", "roles": None, "via": [], "undeclared_means": "open", **base}


def handler_checks(text, line):
    masked = mask(text, hash_comments=True)
    brace = masked.find("{", line_start(text, line))
    if brace == -1:
        return []
    end = match_brace(masked, brace)
    return sorted(set(CHECK_RE.findall(text[brace:end + 1])))
