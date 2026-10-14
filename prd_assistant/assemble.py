"""Substitute verified slots into the scaffold. The model never touches the tables."""
import re

from . import verify

PLACEHOLDER_RE = re.compile(r"\{\{slot:([^}]+)\}\}")
FOOTER = (
    "\n---\n\n"
    "_How this draft was made: tables, counts and citations were computed from the code by scripts. "
    "The prose slots were written by a model and checked by a lint script. "
    "Verified: every citation points at a real source, every digit comes from the evidence, every double-quoted string is verbatim. "
    "NOT verified: whether the prose is accurate or well judged, and spelled-out numbers. A person must review it._\n"
)


class AssembleError(RuntimeError):
    def __init__(self, errors):
        super().__init__(f"{len(errors)} problem(s): " + "; ".join(f"{e['slot']}: {e['rule']}" for e in errors[:5]))
        self.errors = errors


def assemble(scaffold_text, slots, template):
    errors = verify.verify(slots, template)
    if errors:
        raise AssembleError(errors)
    found = PLACEHOLDER_RE.findall(scaffold_text)
    placeholders = set(found)
    repeated = sorted({k for k in found if found.count(k) > 1})
    if repeated:
        raise AssembleError([{"slot": k, "rule": "keys", "detail": "placeholder appears more than once"}
                             for k in repeated])
    keys = {s["key"] for s in template["slots"]}
    if placeholders != keys:
        raise AssembleError([{"slot": k, "rule": "keys", "detail": "scaffold and template disagree"}
                             for k in sorted(placeholders ^ keys)])
    text = PLACEHOLDER_RE.sub(lambda m: slots[m.group(1)].strip(), scaffold_text)
    return text + FOOTER
