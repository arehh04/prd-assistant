"""Lint model-written slots against the evidence they were given. Deterministic; no model involved."""
import re

NEEDS = "NEEDS HUMAN INPUT"
CITE_RE = re.compile(r"\[([^\]\s:]+):(\d+)\]")
QUOTE_RE = re.compile(r'"([^"\n]+)"|“([^”\n]+)”')
NUM_RE = re.compile(r"\d+")
STRUCTURE_RE = re.compile(r"(?m)^\s*(#|\||>|---|===|[-*+]\s|\d+[.)]\s|```)")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")  # newlines, CR, tabs, C1 and line separators
MARKUP_RE = re.compile(r"[<>`]|!\[|\]\(")  # HTML, images, links, code spans
BAD_QUOTE_RE = re.compile(r"[‘«»「」]")  # quote forms the quote check does not understand
MAX_CHARS = 2000


def _norm(text):
    return " ".join(text.split())


def _err(slot, rule, detail):
    return {"slot": slot, "rule": rule, "detail": detail}


def _check_slot(key, text, spec):
    errors = []
    if not isinstance(text, str):
        return [_err(key, "form", "slot value must be a string")]
    stripped = text.strip()
    if stripped == NEEDS:
        if not spec["may_be_needs_human_input"]:
            errors.append(_err(key, "citation", "NEEDS HUMAN INPUT is not allowed for this slot"))
        return errors
    if ("{{" in stripped or CONTROL_RE.search(stripped) or STRUCTURE_RE.search(stripped)
            or MARKUP_RE.search(stripped) or BAD_QUOTE_RE.search(stripped)):
        errors.append(_err(key, "form", "must be one plain line of text: no line breaks, Markdown, HTML, links, "
                                         "code spans, unusual quote marks or {{ }}"))
    if len(stripped) > MAX_CHARS:
        errors.append(_err(key, "length", f"{len(stripped)} characters, limit {MAX_CHARS}"))
    words = len(stripped.split())
    if words > spec["max_words"]:
        errors.append(_err(key, "length", f"{words} words, limit {spec['max_words']}"))
    cites = CITE_RE.findall(stripped)
    if not cites:
        errors.append(_err(key, "citation", "at least one [file:line] citation is required"))
    for path, line in cites:
        if not any(e["file"] == path and e["from_line"] <= int(line) <= e["to_line"]
                   for e in spec["allowed_evidence"]):
            errors.append(_err(key, "resolves", f"[{path}:{line}] is not inside this slot's allowed evidence"))
    allowed = set(spec["allowed_numbers"])
    bad = sorted({n for n in NUM_RE.findall(CITE_RE.sub(" ", stripped)) if n not in allowed}, key=int)
    if bad:
        errors.append(_err(key, "numbers", f"numbers not in the evidence: {', '.join(bad)}"))
    cited_files = {path for path, _ in cites}
    shown = [_norm(e["text"]) for e in spec["evidence_text"] if e["file"] in cited_files]
    for m in QUOTE_RE.finditer(stripped):
        quote = _norm(m.group(1) or m.group(2))
        if not any(quote in text_ for text_ in shown):
            errors.append(_err(key, "quotes", f'quoted text not found in the cited evidence: "{quote}"'))
    terms = spec.get("banned_terms") or []
    if terms:
        visible = QUOTE_RE.sub(" ", CITE_RE.sub(" ", stripped))
        hits = sorted({t for t in terms if re.search(r"(?<!\w)" + r"\s+".join(map(re.escape, t.split())) + r"(?:s|es)?(?!\w)", visible, re.I)})
        if hits:
            errors.append(_err(key, "jargon", "plain-language rule: avoid " + ", ".join(hits)))
    return errors


def verify(slots, template):
    if not isinstance(slots, dict):
        return [_err("*", "keys", "slots.json must be a JSON object of key to text")]
    specs = {s["key"]: s for s in template["slots"]}
    errors = []
    for key in sorted(set(specs) - set(slots)):
        errors.append(_err(key, "keys", "missing slot"))
    for key in sorted(set(slots) - set(specs)):
        errors.append(_err(key, "keys", "unknown slot"))
    for key in sorted(set(specs) & set(slots)):
        errors += _check_slot(key, slots[key], specs[key])
    return errors
